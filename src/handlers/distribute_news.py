import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from src.models.news import NewsDigest
from src.services.bedrock_client import run_news_agent
from src.services.html_renderer import render_news_email
from src.services.parameter_store import AppConfig, load_config
from src.services.ses_client import send_html_email
from src.services.slack_client import send_news_by_category
from src.services.url_normalizer import apply_url_rewrites

logger = logging.getLogger()
logger.setLevel(logging.INFO)

JST = timezone(timedelta(hours=9))
AWS_REGION = "ap-northeast-1"


def _today_jst() -> str:
    """JST タイムゾーンで本日の日付を YYYY-MM-DD 文字列で返す。"""
    return datetime.now(JST).strftime("%Y-%m-%d")


def _send_email(config: AppConfig, digest: NewsDigest, today: str) -> str:
    """SES 経由で HTML メールを送信し、SES MessageId を返す。

    Args:
        config: Parameter Store 由来の設定（sender_email / recipient_emails 必須）。
        digest: Bedrock から取得したニュース。
        today: 件名と本文に埋め込む日付。

    Returns:
        SES MessageId。
    """
    html_body = render_news_email(digest=digest, date=today)
    subject = f"[カチタス Daily News] {today} 本日の不動産ニュース"
    return send_html_email(
        sender=config.sender_email,
        recipients=config.recipient_emails,
        subject=subject,
        html_body=html_body,
        region_name=AWS_REGION,
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda エントリポイント。EventBridge Scheduler から毎朝 JST 08:00 に呼ばれる。

    処理フロー:
        1. Parameter Store から設定取得
        2. Bedrock で本日のニュース計30件（全6カテゴリ各5件）を取得
        3. email_enabled なら SES 送信、slack_enabled なら Slack 送信
        4. 失敗時は例外を上げ、Scheduler のリトライ→DLQ→アラートに連鎖させる

    Args:
        event: EventBridge Scheduler ペイロード（実装上は未使用、ログ目的のみ）。
        context: Lambda runtime context（未使用、署名互換性のみ）。

    Returns:
        statusCode / 配信結果サマリ dict。Lambda の戻り値はログにのみ残る。
    """
    today = _today_jst()
    logger.info("invocation start: today=%s, event=%s", today, event)

    config = load_config()

    # news_search クライアントは環境変数経由で provider と API キーを参照する設計。
    # Lambda 実行コンテキスト内のみで有効（プロセスごとに新規化）。
    # provider が空なら news_search 側のデフォルト（brave）が使われる。
    if config.news_search_provider:
        os.environ["NEWS_SEARCH_PROVIDER"] = config.news_search_provider
    os.environ["NEWS_SEARCH_API_KEY"] = config.news_search_api_key

    digest = run_news_agent(
        model_id=config.bedrock_model_id,
        prompt=config.prompt,
        today=today,
        region_name=AWS_REGION,
        max_searches_per_invocation=config.news_search_max_per_invocation,
    )
    # 既知の失効ホスト（例: housenews.jp → www.housenews.jp）を分配前に補正する。
    digest = apply_url_rewrites(digest)
    logger.info("digest fetched: items=%d", len(digest.items))

    result: dict[str, Any] = {"statusCode": 200, "date": today}

    if config.email_enabled:
        result["sesMessageId"] = _send_email(config, digest, today)
        result["recipientCount"] = len(config.recipient_emails)
    else:
        logger.info("email skipped: recipient_emails が空")
        result["sesMessageId"] = None

    if config.slack_enabled:
        # 複数 Webhook（複数チャネル）へ同報する。
        # NOTE: いずれかの Webhook で SlackSendError が出ると以降は送らず例外を上げる。
        # Scheduler のリトライで再実行されると、成功済み Webhook には重複投稿されうる
        # （冪等性は未保証。現状要件では許容範囲）。
        slack_total = 0
        webhook_count = len(config.slack_webhook_urls)
        for idx, webhook_url in enumerate(config.slack_webhook_urls, start=1):
            slack_total += send_news_by_category(
                webhook_url=webhook_url,
                digest=digest,
                date=today,
            )
            logger.info("slack webhook done: %d/%d", idx, webhook_count)
        result["slackMessageCount"] = slack_total
        result["slackWebhookCount"] = webhook_count
    else:
        logger.info("slack skipped: slack-webhook-url が空")
        result["slackMessageCount"] = 0
        result["slackWebhookCount"] = 0

    logger.info("invocation success: %s", result)
    return result
