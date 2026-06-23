"""外部 Web Search API（Brave / Tavily）を使った実ニュース検索クライアント。

Bedrock の Tool Use ループで `search_real_news` ツールが呼ばれた際の
実際の検索処理を担う。プロバイダ層を抽象化し、API 切替を容易にする。

サポート:
    - Brave Search API（デフォルト。無料 2000 query/月）
    - Tavily Search API（LLM 特化。無料 1000 query/月）

各プロバイダの無料枠に応じた1起動あたり推奨上限値も併せて公開する
（`PROVIDER_DEFAULT_CAPS`）。

選定理由は docs/guides/news-search-provider.md を参照。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SEC = 15

SearchProvider = Literal["brave", "tavily"]

# プロバイダごとの 1 invocation あたり推奨上限（無料枠 ÷ 30日 × 0.75 ≒ 25%バッファ）。
# 有料プラン移行時は環境変数 NEWS_SEARCH_MAX_PER_INVOCATION で上書き可能。
#
#   Brave Free  : 2000 query/月 → 50/起動 × 30 = 1500/月（25%バッファ）
#   Tavily Free : 1000 query/月 → 25/起動 × 30 =  750/月（25%バッファ）
PROVIDER_DEFAULT_CAPS: dict[SearchProvider, int] = {
    "brave": 50,
    "tavily": 25,
}

# デフォルトのプロバイダ。Brave の方が無料枠が広いため採用。
DEFAULT_PROVIDER: SearchProvider = "brave"


@dataclass(frozen=True)
class SearchHit:
    """検索結果1件分の正規化スキーマ（プロバイダ非依存）。

    Bedrock に返す際は `to_bedrock_dict()` で dict 化する。
    """

    title: str
    url: str
    snippet: str
    published_at: str | None  # ISO8601 もしくは空。プロバイダによっては取得不可。

    def to_bedrock_dict(self) -> dict[str, Any]:
        """Bedrock の toolResult に詰められるシリアライズ可能な dict に変換する。"""
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_at": self.published_at or "",
        }


class NewsSearchError(RuntimeError):
    """ニュース検索 API 呼び出し失敗時に投げる。

    Attributes:
        provider: 使用していたプロバイダ名。
        status_code: HTTP ステータスコード（あれば）。
    """

    def __init__(
        self,
        message: str,
        *,
        provider: SearchProvider | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


def resolve_provider(explicit: SearchProvider | None = None) -> SearchProvider:
    """利用するプロバイダを解決する。

    優先順位: 引数 > 環境変数 NEWS_SEARCH_PROVIDER > DEFAULT_PROVIDER。
    未知の値はデフォルトにフォールバック（警告ログ）。
    """
    candidate = explicit or os.environ.get("NEWS_SEARCH_PROVIDER", "").strip().lower()
    if not candidate:
        return DEFAULT_PROVIDER
    if candidate in PROVIDER_DEFAULT_CAPS:
        return candidate  # type: ignore[return-value]
    logger.warning(
        "未知の NEWS_SEARCH_PROVIDER=%r。デフォルト %s にフォールバック。",
        candidate,
        DEFAULT_PROVIDER,
    )
    return DEFAULT_PROVIDER


# -----------------------------------------------------------------------------
# Brave Search 実装（デフォルト）
# -----------------------------------------------------------------------------

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/news/search"


def _search_brave(
    *,
    query: str,
    max_results: int,
    api_key: str,
) -> list[SearchHit]:
    """Brave News Search API を呼び出す。

    Brave Search の `news` エンドポイントは記事のみを返す。
    本ツールは「直近24時間以内（1日以内）」のニュースのみを対象とするため、
    `freshness=pd`（past day = 過去24時間）を固定で指定する。

    Args:
        query: 検索キーワード。
        max_results: 取得件数（1〜20）。
        api_key: Brave API Subscription Token。

    Raises:
        NewsSearchError: HTTP / 接続エラー時。
    """
    params = {
        "q": query,
        "count": str(max(1, min(max_results, 20))),
        "freshness": "pd",  # past day = 直近24時間以内に限定
        "country": "JP",
        "search_lang": "jp",
        "safesearch": "moderate",
    }
    url = f"{_BRAVE_ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_excerpt = e.read().decode(errors="replace")[:500]
        raise NewsSearchError(
            f"Brave HTTP error: status={e.code}, body={body_excerpt}",
            provider="brave",
            status_code=e.code,
        ) from e
    except urllib.error.URLError as e:
        raise NewsSearchError(f"Brave URL error: {e.reason}", provider="brave") from e

    return [
        SearchHit(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=(item.get("description") or "")[:1500],
            # page_age は ISO8601（例: "2026-06-12T08:30:00"）で精度が高い。
            # 取得できない記事は相対表現の age（"1 hour ago"）にフォールバック。
            published_at=item.get("page_age") or item.get("age"),
        )
        for item in data.get("results", [])
    ]


# -----------------------------------------------------------------------------
# Tavily 実装
# -----------------------------------------------------------------------------

_TAVILY_ENDPOINT = "https://api.tavily.com/search"


def _search_tavily(
    *,
    query: str,
    max_results: int,
    api_key: str,
) -> list[SearchHit]:
    """Tavily Search API を呼び出す。

    Tavily は LLM agent 向けに設計された API で、コンテンツを LLM 用に要約済み。
    ニュース系クエリは `topic="news"` を指定すると鮮度が改善する。
    Brave と揃え、直近24時間以内（`days=1`）のニュースのみを対象とする。

    Raises:
        NewsSearchError: HTTP エラー / 接続エラー時。
    """
    payload = {
        "api_key": api_key,
        "query": query,
        "topic": "news",
        "search_depth": "basic",
        "max_results": max_results,
        "days": 1,  # 直近24時間以内（1日）に限定
        "include_answer": False,
        "include_raw_content": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _TAVILY_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_excerpt = e.read().decode(errors="replace")[:500]
        raise NewsSearchError(
            f"Tavily HTTP error: status={e.code}, body={body_excerpt}",
            provider="tavily",
            status_code=e.code,
        ) from e
    except urllib.error.URLError as e:
        raise NewsSearchError(f"Tavily URL error: {e.reason}", provider="tavily") from e

    return [
        SearchHit(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", "")[:1500],
            published_at=item.get("published_date"),
        )
        for item in data.get("results", [])
    ]


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def search_news(
    *,
    query: str,
    max_results: int = 5,
    provider: SearchProvider | None = None,
    api_key: str | None = None,
) -> list[SearchHit]:
    """指定キーワードで実ニュースを検索する。

    対象は「直近24時間以内（1日以内）」のニュースに固定する
    （Brave は `freshness=pd`、Tavily は `days=1`）。

    プロバイダは引数 > 環境変数 `NEWS_SEARCH_PROVIDER` > `DEFAULT_PROVIDER` の順で決定。
    API キーは引数 > 環境変数 `NEWS_SEARCH_API_KEY` から取得。
    Lambda 上では handler が Parameter Store ロード時に環境変数化する想定。

    Args:
        query: 検索キーワード（例: "中古住宅 リフォーム 補助金 2026"）。
        max_results: 取得する最大件数。Bedrock の context 圧迫を避け 5 程度に抑える。
        provider: "brave" or "tavily"。None の場合は環境変数 / デフォルト。
        api_key: 該当プロバイダの API キー。None の場合は環境変数。

    Returns:
        SearchHit のリスト。

    Raises:
        NewsSearchError: API キー未設定 / API エラー時。
    """
    chosen_provider = resolve_provider(provider)
    chosen_key = api_key or os.environ.get("NEWS_SEARCH_API_KEY", "")
    if not chosen_key:
        raise NewsSearchError(
            f"API キー未設定（provider={chosen_provider}）。環境変数 NEWS_SEARCH_API_KEY を確認。",
            provider=chosen_provider,
        )

    logger.info("news_search start: provider=%s, query=%s", chosen_provider, query)
    if chosen_provider == "brave":
        hits = _search_brave(query=query, max_results=max_results, api_key=chosen_key)
    elif chosen_provider == "tavily":
        hits = _search_tavily(query=query, max_results=max_results, api_key=chosen_key)
    else:  # pragma: no cover — resolve_provider が必ず既知の値を返すはず
        raise NewsSearchError(
            f"未知のプロバイダ: {chosen_provider}", provider=chosen_provider
        )
    logger.info("news_search done: provider=%s, hits=%d", chosen_provider, len(hits))
    return hits
