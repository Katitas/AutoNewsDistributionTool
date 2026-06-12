"""Bedrock Converse API を使った Agentic Tool Use ループ。

Bedrock 自身が以下のループを回す:
    1. プロンプト + 本日の日付を受け取る
    2. キーワードを決定し `search_real_news` ツールを呼ぶ
    3. 検索結果を読んで適切な5件を選定
    4. `submit_news_digest` ツールに構造化結果を渡して終了

Lambda 内では本ファイルの `run_news_agent()` を呼ぶだけで、
内部の tool dispatch はすべて自動で処理される。

`submit_news_digest` は最終出力ツール（実装は無く、Bedrock からの引数を NewsDigest として
そのまま検証して返す）。`search_real_news` のみ Lambda 上で実関数を実行する。
"""

import json
import logging
import os
from copy import deepcopy
from typing import Any

import boto3
from botocore.config import Config
from pydantic import ValidationError

from src.models.news import NewsDigest
from src.services.news_search import (
    PROVIDER_DEFAULT_CAPS,
    NewsSearchError,
    resolve_provider,
    search_news,
)

logger = logging.getLogger(__name__)

SUBMIT_TOOL_NAME = "submit_news_digest"
SUBMIT_TOOL_DESCRIPTION = (
    "本日のニュースダイジェストを5件、構造化データとして送信する。"
    "search_real_news で十分な裏取りを行った後、最後にこのツールを必ず呼び出して終了すること。"
    "プレーンテキストでの応答は禁止。"
)

SEARCH_TOOL_NAME = "search_real_news"
SEARCH_TOOL_DESCRIPTION = (
    "実際のWebニュース記事を検索する。日本語キーワードで実在する記事のtitle/url/snippetを取得できる。"
    "本日のニュースを5件選ぶ前に、必ずこのツールを複数回呼び出して候補記事の裏取りを行うこと。"
    "URL を捏造するのではなく、このツールが返した URL のみを submit_news_digest の source_url に使うこと。"
    "1回の起動で呼び出せる回数には上限あり。上限到達時はその時点までの結果で submit_news_digest を呼び終了すること。"
)

# Tool Use ループの最大ターン数（無限ループ防止）。
# 想定: 検索 5〜8回 + 最終 submit 1回 = 6〜9 ターン。10ターンで打ち止め。
_MAX_AGENT_TURNS = 12

# 1 Lambda invocation あたりの search_real_news 呼び出し上限。
# プロバイダごとのデフォルトは src/services/news_search.py:PROVIDER_DEFAULT_CAPS で管理。
#   Brave Free  : 50/起動（無料 2000 query/月の保護）
#   Tavily Free : 25/起動（無料 1000 query/月の保護）
# 有料プラン移行時は環境変数 NEWS_SEARCH_MAX_PER_INVOCATION で上書き可能。


class BedrockToolUseError(RuntimeError):
    """Bedrock Tool Use 応答が想定形式でなかった、または Pydantic 検証に失敗した場合。

    Attributes:
        message: ヒューマンリーダブルな説明（str(exc) と同じ）。
        stop_reason: Bedrock 応答の最終 stopReason。
        content_blocks: 最終ターンの content ブロック生データ。
        validation_errors: Pydantic ValidationError の文字列表現（スキーマ違反時のみ）。
    """

    def __init__(
        self,
        message: str,
        *,
        stop_reason: str | None = None,
        content_blocks: list[dict[str, Any]] | None = None,
        validation_errors: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stop_reason = stop_reason
        self.content_blocks = content_blocks
        self.validation_errors = validation_errors


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic が生成する $defs/$ref を再帰的にインライン展開する。

    Bedrock Converse API の inputSchema.json は JSON Schema の $ref を解決しないため、
    クライアント側で展開しないとスキーマが Bedrock に正しく伝わらない。
    """
    schema = deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                key = node["$ref"].split("/")[-1]
                return walk(defs[key])
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _build_tool_config() -> dict[str, Any]:
    """Bedrock Converse API に渡す toolConfig を組み立てる。

    Tool が2つ:
        - search_real_news: 自由に複数回呼べる検索ツール
        - submit_news_digest: 最終結果送信用（必ず1回呼ぶ）

    `toolChoice` は `auto` に設定し、Bedrock が判断してツールを使い分ける。
    最終ターンで submit_news_digest が呼ばれることはプロンプトと description で誘導する。
    """
    submit_schema = _inline_refs(NewsDigest.model_json_schema())
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": SEARCH_TOOL_NAME,
                    "description": SEARCH_TOOL_DESCRIPTION,
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": (
                                        "検索キーワード（日本語推奨）。"
                                        "例: '中古住宅 リフォーム 補助金 2026'。"
                                        "1キーワードで広く狙うより、複数回呼び出して個別ニュースを掘る方が望ましい。"
                                    ),
                                },
                                "max_results": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 10,
                                    "default": 5,
                                    "description": "取得する最大件数。デフォルト5。",
                                },
                                "days_back": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 14,
                                    "default": 2,
                                    "description": "何日前まで遡るか。日次配信のため2-3が標準。",
                                },
                            },
                            "required": ["query"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": SUBMIT_TOOL_NAME,
                    "description": SUBMIT_TOOL_DESCRIPTION,
                    "inputSchema": {"json": submit_schema},
                }
            },
        ],
        "toolChoice": {"auto": {}},
    }


def _execute_search_tool(
    tool_input: dict[str, Any],
    *,
    searches_used: int,
    searches_max: int,
) -> dict[str, Any]:
    """`search_real_news` ツール呼び出しを実行し、Bedrock toolResult 用の dict を返す。

    Bedrock toolResult のフォーマット仕様:
        {"toolUseId": "...", "content": [{"json": {...}}], "status": "success" | "error"}

    Tavily 月間予算保護のためソフト上限を持つ。上限到達時は検索を実行せず、
    Bedrock に「予算枯渇」を通知して submit_news_digest 呼び出しを促す（エラーは投げない）。

    Args:
        tool_input: Bedrock からのツール呼び出し引数（query / max_results / days_back）。
        searches_used: 本invocation内の既使用回数。
        searches_max: 本invocation内の上限回数。
    """
    query = tool_input.get("query", "")
    max_results = int(tool_input.get("max_results", 5))
    days_back = int(tool_input.get("days_back", 2))

    # 予算チェック: 上限到達なら API 呼び出しせず Bedrock に通知のみ
    if searches_used >= searches_max:
        logger.warning(
            "search_real_news budget exhausted: used=%d, max=%d, query=%s",
            searches_used,
            searches_max,
            query,
        )
        return {
            "json": {
                "query": query,
                "results": [],
                "count": 0,
                "budget_exhausted": True,
                "message": (
                    f"検索予算上限（{searches_max}回/起動）に到達したため、これ以上の検索はできません。"
                    f"これまでの検索結果から submit_news_digest を呼んで終了してください。"
                ),
            }
        }

    try:
        hits = search_news(query=query, max_results=max_results, days_back=days_back)
        return {
            "json": {
                "query": query,
                "results": [h.to_bedrock_dict() for h in hits],
                "count": len(hits),
                "searches_remaining": searches_max - searches_used - 1,
            }
        }
    except NewsSearchError as e:
        # Bedrock に「失敗した」と伝えると別キーワードで再試行する判断ができる。
        logger.warning("search_real_news failed: %s", e)
        return {
            "json": {
                "query": query,
                "error": str(e),
                "results": [],
                "count": 0,
            }
        }


def _resolve_max_searches(explicit: int | None) -> int:
    """invocation あたりの search 呼び出し上限を解決する。

    優先順位:
        1. 引数 explicit
        2. 環境変数 NEWS_SEARCH_MAX_PER_INVOCATION
        3. 現在のプロバイダの無料枠に基づくデフォルト（PROVIDER_DEFAULT_CAPS）

    プロバイダ切替時（例: tavily → brave）に、明示設定がなければ自動的に
    新プロバイダの推奨上限が反映される。
    """
    if explicit is not None:
        return explicit
    env_value = os.environ.get("NEWS_SEARCH_MAX_PER_INVOCATION", "").strip()
    if env_value:
        try:
            return max(1, int(env_value))
        except ValueError:
            logger.warning(
                "NEWS_SEARCH_MAX_PER_INVOCATION の値が不正: %r。プロバイダ既定値を使用。",
                env_value,
            )
    provider = resolve_provider()
    return PROVIDER_DEFAULT_CAPS[provider]


def run_news_agent(
    *,
    model_id: str,
    prompt: str,
    today: str,
    region_name: str = "ap-northeast-1",
    max_turns: int = _MAX_AGENT_TURNS,
    max_searches_per_invocation: int | None = None,
) -> NewsDigest:
    """Bedrock Tool Use ループを実行し、検索→選定→構造化された NewsDigest を返す。

    処理:
        1. 初期メッセージ（プロンプト + 本日日付）で Converse 呼び出し
        2. Bedrock が `search_real_news` を呼んだら検索実行 → toolResult 返却
        3. Bedrock が `submit_news_digest` を呼んだら検証して NewsDigest を返す
        4. 上記を最大 max_turns まで繰り返す

    検索コスト保護:
        Tavily Free 1000 query/月の枠を超えないよう、invocation あたりの
        search_real_news 呼び出しを `max_searches_per_invocation` で制限する。
        上限到達後は検索結果を空 + budget_exhausted=True で返し、Bedrock に
        手元の情報で submit_news_digest を呼ばせる（エラーは投げない）。

    Args:
        model_id: Bedrock モデル ID（Inference Profile ID 含む）。
        prompt: ユーザープロンプト（Parameter Store 由来）。
        today: JST 本日日付（YYYY-MM-DD）。
        region_name: Bedrock を呼ぶリージョン。
        max_turns: ツールループの最大ターン数。
        max_searches_per_invocation: 1起動あたりの検索 API 呼び出し上限。
            None の場合は環境変数 NEWS_SEARCH_MAX_PER_INVOCATION またはデフォルト。

    Returns:
        Pydantic 検証済み NewsDigest。

    Raises:
        BedrockToolUseError: ループ上限到達 / 想定外応答 / NewsDigest 検証失敗時。
    """
    searches_max = _resolve_max_searches(max_searches_per_invocation)
    searches_used = 0
    active_provider = resolve_provider()
    logger.info(
        "agent start: provider=%s, searches_max=%d", active_provider, searches_max
    )
    client = boto3.client(
        "bedrock-runtime",
        region_name=region_name,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )
    tool_config = _build_tool_config()

    system_prompt = [
        {
            "text": (
                f"本日の日付は {today} です。"
                f"あなたはカチタス（実需中古住宅事業）向けのニュースリサーチャーです。"
                f"利用可能なツール: {SEARCH_TOOL_NAME}（実検索）と {SUBMIT_TOOL_NAME}（最終出力）。"
                f"\n\n"
                f"## 検索ツールの利用予算（重要）\n"
                f"本起動では {SEARCH_TOOL_NAME} を **最大 {searches_max} 回** まで呼び出せます。"
                f"これは Web 検索 API（{active_provider}）の月間無料枠を保護するための制約です。"
                f"上限を超えた呼び出しは検索結果が空で返るため、計画的に使ってください。\n"
                f"推奨配分: 5〜10 キーワードに対し、各 3〜5 回程度で計 {min(searches_max, 30)} 回前後。"
                f"各 toolResult に `searches_remaining` フィールドが含まれるので、"
                f"残り回数を見ながら戦略を調整してください。\n\n"
                f"## 作業フロー\n"
                f"1. 必ず {SEARCH_TOOL_NAME} を複数回呼んで実在記事の裏取りを行う\n"
                f"2. 取得した記事から本日のニュース 5 件を選定\n"
                f"3. 最後に {SUBMIT_TOOL_NAME} を 1 回呼んで終了する\n\n"
                f"## 厳守事項\n"
                f"URL は捏造禁止。{SEARCH_TOOL_NAME} が返した url のみ source_url に使うこと。"
                f"検索予算が尽きた場合（budget_exhausted=true が返ったら）、"
                f"その時点までの検索結果から 5 件選び、{SUBMIT_TOOL_NAME} を呼んで正常終了してください。"
            )
        }
    ]
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": prompt}]}
    ]

    last_stop_reason: str | None = None
    last_content: list[dict[str, Any]] = []

    for turn in range(max_turns):
        logger.info("agent turn=%d start", turn)
        response = client.converse(
            modelId=model_id,
            system=system_prompt,
            messages=messages,
            toolConfig=tool_config,
            inferenceConfig={"maxTokens": 4096, "temperature": 0.4},
        )

        last_stop_reason = response.get("stopReason")
        last_content = response["output"]["message"]["content"]
        logger.info("agent turn=%d stop_reason=%s", turn, last_stop_reason)

        # 1) submit_news_digest が呼ばれたら最終結果として処理して終了
        for block in last_content:
            if "toolUse" not in block:
                continue
            name = block["toolUse"].get("name")
            if name == SUBMIT_TOOL_NAME:
                tool_input = block["toolUse"]["input"]
                logger.info(
                    "agent submit: searches_used=%d/%d, turn=%d",
                    searches_used,
                    searches_max,
                    turn,
                )
                try:
                    return NewsDigest.model_validate(tool_input)
                except ValidationError as e:
                    raise BedrockToolUseError(
                        f"NewsDigest 検証失敗: {e}",
                        stop_reason=last_stop_reason,
                        content_blocks=last_content,
                        validation_errors=str(e),
                    ) from e

        # 2) search_real_news が呼ばれたら検索を実行し、toolResult を作って次ターンへ
        tool_results: list[dict[str, Any]] = []
        for block in last_content:
            if "toolUse" not in block:
                continue
            tu = block["toolUse"]
            if tu.get("name") != SEARCH_TOOL_NAME:
                continue
            result_content = _execute_search_tool(
                tu.get("input", {}),
                searches_used=searches_used,
                searches_max=searches_max,
            )
            # 実際に Tavily を叩いた場合のみカウントを進める。
            # 上限到達による空応答や、searches_max 到達後の追加呼び出しはカウントしない。
            if not result_content["json"].get("budget_exhausted"):
                searches_used += 1
            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [result_content],
                        "status": "success" if "error" not in result_content["json"] else "error",
                    }
                }
            )

        if not tool_results:
            # ツール呼び出しが無く submit もされていない = 想定外（プレーンテキスト応答等）
            raise BedrockToolUseError(
                f"想定外の応答: ツール呼び出しなし。stopReason={last_stop_reason}, "
                f"content={json.dumps(last_content, ensure_ascii=False, default=str)[:1000]}",
                stop_reason=last_stop_reason,
                content_blocks=last_content,
            )

        # アシスタントの toolUse メッセージを履歴に追加（必須）
        messages.append({"role": "assistant", "content": last_content})
        # ユーザー側として toolResult を返す
        messages.append({"role": "user", "content": tool_results})

    raise BedrockToolUseError(
        f"エージェントループが {max_turns} ターン到達したが submit_news_digest が呼ばれなかった。"
        f" (searches_used={searches_used}/{searches_max})",
        stop_reason=last_stop_reason,
        content_blocks=last_content,
    )


# 後方互換: 既存呼び出し元（テスト等）が `fetch_news_digest` を使っているため alias を残す。
# 内部実装は agentic loop に置換済み。
def fetch_news_digest(
    *,
    model_id: str,
    prompt: str,
    today: str,
    region_name: str = "ap-northeast-1",
) -> NewsDigest:
    """[互換用] `run_news_agent` への薄いラッパ。

    既存の handler / テストとの互換のため残置。新規コードは `run_news_agent` を直接呼ぶこと。
    """
    return run_news_agent(
        model_id=model_id, prompt=prompt, today=today, region_name=region_name
    )
