import json
import logging
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

from src.models.news import NewsDigest, NewsItem

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SEC = 10
_CATEGORY_EMOJI: dict[str, str] = {
    "PropTech": "🤖",
    "企業動向": "🏢",
    "法規制・政策": "⚖️",
    "マーケット・価格動向": "📈",
    "海外不動産": "🌏",
    "リフォーム関連": "🔨",
}


class SlackSendError(RuntimeError):
    """Slack Webhook への投稿に失敗した場合に投げる。

    Slack はカテゴリ単位で複数メッセージを送るため、どのカテゴリで失敗したかと
    HTTP ステータス・レスポンス本文を保持する。CloudWatch Logs から障害発生時に
    再現性を高める目的。

    Attributes:
        message: ヒューマンリーダブルな説明。
        category: 送信を試みた Slack メッセージのカテゴリ名（NewsItem.category）。送信前段階の失敗時は None。
        status_code: HTTP ステータスコード（urllib.error.HTTPError 由来）。URL/接続エラー時は None。
        response_body: Slack 側の応答本文（"invalid_token" / "no_service" 等のヒントを含む）。
    """

    def __init__(
        self,
        message: str,
        *,
        category: str | None = None,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.status_code = status_code
        self.response_body = response_body


def _group_by_category(digest: NewsDigest) -> "OrderedDict[str, list[NewsItem]]":
    """ニュースをカテゴリ別にグルーピングする（出現順を維持）。"""
    grouped: OrderedDict[str, list[NewsItem]] = OrderedDict()
    for item in digest.items:
        grouped.setdefault(item.category, []).append(item)
    return grouped


def _escape_mrkdwn(text: str) -> str:
    """Slack mrkdwn の特殊文字（< > &）をエスケープする。

    Slack の mrkdwn は `<URL|label>` 構文をリンクとして解釈するため、
    ニュース本文に生の `<` `>` が含まれるとパースが壊れる。
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_blocks(category: str, items: list[NewsItem], date: str) -> list[dict[str, Any]]:
    """1カテゴリ分の Slack Block Kit ブロック配列を組み立てる。

    Args:
        category: カテゴリ名（NewsCategory）。先頭ヘッダーに絵文字付きで表示。
        items: そのカテゴリに属するニュース一覧（順序は元のNewsDigest順を維持）。
        date: 配信対象日（YYYY-MM-DD）。ヘッダーに表示。

    Returns:
        Slack の `blocks` プロパティに渡せる dict のリスト。
        構造: header → (section + context + divider) × items（最後の divider は省略）。
    """
    emoji = _CATEGORY_EMOJI.get(category, "📰")
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {category}  ・  {date}", "emoji": True},
        }
    ]
    for idx, item in enumerate(items):
        title_safe = _escape_mrkdwn(item.title)
        summary_safe = _escape_mrkdwn(item.summary)
        relevance_safe = _escape_mrkdwn(item.katitas_relevance)

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*<{item.source_url}|{title_safe}>*\n"
                        f"{summary_safe}\n\n"
                        f"<{item.source_url}|📰 原文を読む →>"
                    ),
                },
            }
        )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"💡 *カチタス業務へのヒント*\n{relevance_safe}",
                    }
                ],
            }
        )
        if idx < len(items) - 1:
            blocks.append({"type": "divider"})
    return blocks


def _post(webhook_url: str, payload: dict[str, Any], *, category: str | None = None) -> None:
    """Slack Incoming Webhook に1メッセージを POST する。

    Args:
        webhook_url: Slack Incoming Webhook URL（Parameter Store から取得した値）。
        payload: Slack Block Kit JSON ペイロード（blocks + text フォールバック）。
        category: 失敗時の SlackSendError に紐付けるカテゴリ名（任意）。

    Raises:
        SlackSendError: HTTP エラー / 接続エラー / "ok" 以外のレスポンス時。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            status = resp.status
            response_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise SlackSendError(
            f"Slack webhook HTTP error: status={e.code}, body={body_text}",
            category=category,
            status_code=e.code,
            response_body=body_text,
        ) from e
    except urllib.error.URLError as e:
        raise SlackSendError(
            f"Slack webhook URL error: {e.reason}",
            category=category,
        ) from e

    if status != 200 or response_body.strip() != "ok":
        raise SlackSendError(
            f"Slack webhook unexpected response: status={status}, body={response_body!r}",
            category=category,
            status_code=status,
            response_body=response_body,
        )


def send_news_by_category(
    *, webhook_url: str, digest: NewsDigest, date: str, notice: str | None = None
) -> int:
    """ニュースをカテゴリ別に各1メッセージとして Slack に送信する。

    notice が与えられた場合、カテゴリ別送信の前に不足通知を1メッセージ投稿する。

    Returns:
        送信したメッセージ数（notice ありなら +1）。

    Raises:
        SlackSendError: いずれかの送信が失敗した時点で即座に投げる。
    """
    sent_count = 0
    if notice:
        notice_payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"⚠️ {_escape_mrkdwn(notice)}"},
                }
            ],
            "text": notice,
        }
        _post(webhook_url, notice_payload, category=None)
        sent_count += 1
        logger.info("slack notice sent")

    grouped = _group_by_category(digest)
    for category, items in grouped.items():
        payload = {
            "blocks": _build_blocks(category, items, date),
            "text": f"{category} - {date} の不動産ニュース {len(items)}件",
        }
        _post(webhook_url, payload, category=category)
        sent_count += 1
        logger.info("slack send: category=%s, items=%d", category, len(items))
    logger.info("slack send total: messages=%d, categories=%d", sent_count, len(grouped))
    return sent_count
