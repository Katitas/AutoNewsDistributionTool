import boto3
import pytest
from moto import mock_aws

from src.services.parameter_store import load_config


PATH = "/kati/auto_news_distribute/test"


def _put(client, name: str, value: str, *, secure: bool = False) -> None:
    client.put_parameter(
        Name=f"{PATH}/{name}",
        Value=value,
        Type="SecureString" if secure else "String",
        Overwrite=True,
    )


def _put_required_minimum(client) -> None:
    """全テスト共通の必須パラメータ（Bedrock / prompt / news-search-api-key）を投入する。

    各テストが実質的に検証したい個別ケースに集中できるよう共通化。
    """
    _put(client, "bedrock-model-id", "model-id")
    _put(client, "prompt", "プロンプト本文")
    _put(client, "news-search-api-key", "tvly-test-key", secure=True)


@mock_aws
class TestLoadConfig:
    """Parameter Store からの設定読み込み挙動を網羅的に検証する。"""

    def _client(self):
        return boto3.client("ssm", region_name="ap-northeast-1")

    def test_full_config_loaded(self) -> None:
        client = self._client()
        _put(client, "bedrock-model-id", "apac.anthropic.claude-opus-4-7")
        _put(client, "prompt", "あなたは不動産リサーチャーです。")
        _put(client, "recipient-emails", "a@example.com, b@example.com")
        _put(client, "sender-email", "news@example.com")
        _put(client, "slack-webhook-url", "https://hooks.slack.com/services/T/B/X", secure=True)
        _put(client, "news-search-provider", "brave")
        _put(client, "news-search-api-key", "bsa-test-key", secure=True)

        config = load_config(PATH)

        assert config.bedrock_model_id == "apac.anthropic.claude-opus-4-7"
        assert config.prompt.startswith("あなたは")
        assert config.recipient_emails == ["a@example.com", "b@example.com"]
        assert config.sender_email == "news@example.com"
        assert config.slack_webhook_url.startswith("https://hooks.slack.com/")
        assert config.email_enabled is True
        assert config.slack_enabled is True
        assert config.news_search_provider == "brave"
        assert config.news_search_api_key == "bsa-test-key"

    def test_news_search_provider_unset_is_empty(self) -> None:
        """news-search-provider 未設定時は空文字（news_search 側のデフォルト brave が適用される）。"""
        client = self._client()
        _put_required_minimum(client)
        _put(client, "slack-webhook-url", "https://hooks.slack.com/X")

        config = load_config(PATH)
        assert config.news_search_provider == ""

    def test_email_only(self) -> None:
        client = self._client()
        _put_required_minimum(client)
        _put(client, "recipient-emails", "a@example.com")
        _put(client, "sender-email", "news@example.com")

        config = load_config(PATH)
        assert config.email_enabled is True
        assert config.slack_enabled is False

    def test_slack_only(self) -> None:
        client = self._client()
        _put_required_minimum(client)
        _put(client, "slack-webhook-url", "https://hooks.slack.com/services/X")

        config = load_config(PATH)
        assert config.email_enabled is False
        assert config.slack_enabled is True
        assert config.recipient_emails == []

    def test_both_channels_empty_raises(self) -> None:
        client = self._client()
        _put_required_minimum(client)

        with pytest.raises(RuntimeError, match="両方が空"):
            load_config(PATH)

    def test_missing_bedrock_model_id_raises(self) -> None:
        client = self._client()
        _put(client, "prompt", "プロンプト本文")
        _put(client, "news-search-api-key", "tvly-test-key", secure=True)
        _put(client, "slack-webhook-url", "https://hooks.slack.com/X")

        with pytest.raises(RuntimeError, match="bedrock-model-id"):
            load_config(PATH)

    def test_missing_prompt_raises(self) -> None:
        client = self._client()
        _put(client, "bedrock-model-id", "model-id")
        _put(client, "news-search-api-key", "tvly-test-key", secure=True)
        _put(client, "slack-webhook-url", "https://hooks.slack.com/X")

        with pytest.raises(RuntimeError, match="prompt"):
            load_config(PATH)

    def test_email_set_but_sender_missing_raises(self) -> None:
        client = self._client()
        _put_required_minimum(client)
        _put(client, "recipient-emails", "a@example.com")

        with pytest.raises(RuntimeError, match="sender-email"):
            load_config(PATH)

    def test_missing_news_search_api_key_raises(self) -> None:
        """news-search-api-key 未設定はエラー（agentic loop に必須）。"""
        client = self._client()
        _put(client, "bedrock-model-id", "model-id")
        _put(client, "prompt", "プロンプト本文")
        _put(client, "slack-webhook-url", "https://hooks.slack.com/X")

        with pytest.raises(RuntimeError, match="news-search-api-key"):
            load_config(PATH)

    def test_news_search_max_per_invocation_unset_is_none(self) -> None:
        """news-search-max-per-invocation 未設定時は None（bedrock_clientのデフォルト適用）。"""
        client = self._client()
        _put_required_minimum(client)
        _put(client, "slack-webhook-url", "https://hooks.slack.com/X")

        config = load_config(PATH)
        assert config.news_search_max_per_invocation is None

    def test_news_search_max_per_invocation_parsed(self) -> None:
        """news-search-max-per-invocation を整数として読み込む（有料プラン上限引き上げ用）。"""
        client = self._client()
        _put_required_minimum(client)
        _put(client, "slack-webhook-url", "https://hooks.slack.com/X")
        _put(client, "news-search-max-per-invocation", "100")

        config = load_config(PATH)
        assert config.news_search_max_per_invocation == 100

    def test_news_search_max_per_invocation_invalid_raises(self) -> None:
        """整数として解釈できない値はエラー（タイポ早期発見）。"""
        client = self._client()
        _put_required_minimum(client)
        _put(client, "slack-webhook-url", "https://hooks.slack.com/X")
        _put(client, "news-search-max-per-invocation", "twenty-five")

        with pytest.raises(RuntimeError, match="news-search-max-per-invocation"):
            load_config(PATH)
