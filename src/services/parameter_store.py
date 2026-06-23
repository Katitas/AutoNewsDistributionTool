import logging
import os
import re
from dataclasses import dataclass

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

_PARAM_RECIPIENT_EMAILS = "recipient-emails"
_PARAM_SENDER_EMAIL = "sender-email"
_PARAM_BEDROCK_MODEL_ID = "bedrock-model-id"
_PARAM_SLACK_WEBHOOK_URL = "slack-webhook-url"
_PARAM_PROMPT = "prompt"
_PARAM_NEWS_SEARCH_PROVIDER = "news-search-provider"
_PARAM_NEWS_SEARCH_API_KEY = "news-search-api-key"
_PARAM_NEWS_SEARCH_MAX_PER_INVOCATION = "news-search-max-per-invocation"


@dataclass(frozen=True)
class AppConfig:
    bedrock_model_id: str
    prompt: str
    recipient_emails: list[str]
    sender_email: str
    # Slack Incoming Webhook URL のリスト。複数チャネルへ同報するため、
    # Parameter Store の値をカンマ / セミコロン区切りでパースした結果を保持する。
    slack_webhook_urls: list[str]
    # ニュース検索プロバイダ。"brave"（デフォルト）または "tavily"。
    # 空文字なら news_search.DEFAULT_PROVIDER（brave）が使われる。
    news_search_provider: str
    news_search_api_key: str
    # invocation あたりの検索 API 呼び出し上限。
    # None の場合は news_search.PROVIDER_DEFAULT_CAPS のプロバイダ別デフォルトが使われる。
    #   Brave  → 50（無料 2000/月 ÷ 30日 + 25%バッファ）
    #   Tavily → 25（無料 1000/月 ÷ 30日 + 25%バッファ）
    # 有料化時は上限引き上げ可能。
    news_search_max_per_invocation: int | None

    @property
    def email_enabled(self) -> bool:
        return bool(self.recipient_emails)

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_webhook_urls)


def load_config(parameter_path: str | None = None) -> AppConfig:
    """Parameter Store から設定を一括取得する。

    `get_parameters_by_path` の1回のAPI呼び出し（+ ページネーション）で全パラメータを
    取得することで、コールドスタート時のレイテンシを最小化する。

    必須: bedrock-model-id, prompt
    任意: recipient-emails / sender-email / slack-webhook-url
        （ただし recipient-emails と slack-webhook-url の両方が空はエラー）

    Args:
        parameter_path: パラメータの親パス（例: /kati/auto_news_distribute/stg）。
            None の場合は環境変数 `PARAMETER_PATH` から取得。

    Returns:
        AppConfig（凍結済み dataclass）。`email_enabled` / `slack_enabled` で配信可否を判定可能。

    Raises:
        RuntimeError: 必須パラメータ欠落 or 両配信チャネル無効時。
        KeyError: parameter_path 未指定かつ環境変数 PARAMETER_PATH 未設定時。
    """
    path = parameter_path or os.environ["PARAMETER_PATH"]
    path = path.rstrip("/")

    client = boto3.client(
        "ssm",
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )

    raw: dict[str, str] = {}
    paginator = client.get_paginator("get_parameters_by_path")
    for page in paginator.paginate(Path=path, Recursive=False, WithDecryption=True):
        for param in page["Parameters"]:
            key = param["Name"].rsplit("/", 1)[-1]
            raw[key] = param["Value"]

    bedrock_model_id = raw.get(_PARAM_BEDROCK_MODEL_ID, "").strip()
    if not bedrock_model_id:
        raise RuntimeError(f"必須パラメータ {_PARAM_BEDROCK_MODEL_ID} が未設定: path={path}")

    prompt = raw.get(_PARAM_PROMPT, "")
    if not prompt.strip():
        raise RuntimeError(f"必須パラメータ {_PARAM_PROMPT} が未設定または空: path={path}")

    recipients_raw = raw.get(_PARAM_RECIPIENT_EMAILS, "")
    recipient_emails = [e.strip() for e in recipients_raw.split(",") if e.strip()]

    sender_email = raw.get(_PARAM_SENDER_EMAIL, "").strip()
    if recipient_emails and not sender_email:
        raise RuntimeError(
            f"recipient-emails が設定されているが {_PARAM_SENDER_EMAIL} が空: path={path}"
        )

    # 複数チャネルへ同報するため、カンマ / セミコロン区切りで複数 Webhook URL を許容する。
    slack_raw = raw.get(_PARAM_SLACK_WEBHOOK_URL, "")
    slack_webhook_urls = [u.strip() for u in re.split(r"[,;]", slack_raw) if u.strip()]

    if not recipient_emails and not slack_webhook_urls:
        raise RuntimeError(
            "recipient-emails と slack-webhook-url の両方が空です。"
            "少なくとも片方の通知チャネルを設定してください。"
        )

    # ニュース検索プロバイダ（任意。未設定時は news_search.DEFAULT_PROVIDER = brave）。
    news_search_provider = raw.get(_PARAM_NEWS_SEARCH_PROVIDER, "").strip().lower()

    # ニュース検索 API キーは agentic loop 化に伴い必須化。
    news_search_api_key = raw.get(_PARAM_NEWS_SEARCH_API_KEY, "").strip()
    if not news_search_api_key:
        raise RuntimeError(
            f"必須パラメータ {_PARAM_NEWS_SEARCH_API_KEY} が未設定: path={path}。"
            f"Brave / Tavily の Web Search API キーを SecureString として登録してください。"
        )

    # 1起動あたりの search API 呼び出し上限。任意。未設定時は bedrock_client のデフォルト。
    max_per_inv_raw = raw.get(_PARAM_NEWS_SEARCH_MAX_PER_INVOCATION, "").strip()
    news_search_max_per_invocation: int | None
    if max_per_inv_raw:
        try:
            news_search_max_per_invocation = max(1, int(max_per_inv_raw))
        except ValueError:
            raise RuntimeError(
                f"{_PARAM_NEWS_SEARCH_MAX_PER_INVOCATION} は整数で指定してください: 値={max_per_inv_raw!r}"
            ) from None
    else:
        news_search_max_per_invocation = None

    config = AppConfig(
        bedrock_model_id=bedrock_model_id,
        prompt=prompt,
        recipient_emails=recipient_emails,
        sender_email=sender_email,
        slack_webhook_urls=slack_webhook_urls,
        news_search_provider=news_search_provider,
        news_search_api_key=news_search_api_key,
        news_search_max_per_invocation=news_search_max_per_invocation,
    )
    logger.info(
        "config loaded: model=%s, prompt_chars=%d, email_enabled=%s (recipients=%d), "
        "slack_enabled=%s (webhooks=%d)",
        config.bedrock_model_id,
        len(config.prompt),
        config.email_enabled,
        len(config.recipient_emails),
        config.slack_enabled,
        len(config.slack_webhook_urls),
    )
    return config
