from src.handlers import distribute_news
from src.models.news import NewsDigest
from src.services.parameter_store import AppConfig


def _make_config(*, email: bool = True, slack: bool = True) -> AppConfig:
    """テスト用の AppConfig を組み立てる。チャネル有効/無効を引数で切替可能。"""
    return AppConfig(
        bedrock_model_id="test-model",
        prompt="プロンプト本文",
        recipient_emails=["a@example.com"] if email else [],
        sender_email="news@example.com" if email else "",
        slack_webhook_url="https://hooks.slack.com/X" if slack else "",
        news_search_provider="brave",
        news_search_api_key="bsa-test-key",
        news_search_max_per_invocation=None,
    )


class TestLambdaHandler:
    """`distribute_news.lambda_handler` の主要分岐（email/slackの有効・無効）を検証する。"""

    def test_both_channels_invoked(self, mocker, sample_digest: NewsDigest) -> None:
        """email と slack の両方が有効なら両チャネルに送信される。"""
        mocker.patch.object(distribute_news, "load_config", return_value=_make_config())
        mocker.patch.object(distribute_news, "run_news_agent", return_value=sample_digest)
        send_email = mocker.patch.object(distribute_news, "send_html_email", return_value="ses-msg-id")
        mocker.patch.object(distribute_news, "render_news_email", return_value="<html></html>")
        send_slack = mocker.patch.object(distribute_news, "send_news_by_category", return_value=3)

        result = distribute_news.lambda_handler({}, None)

        assert result["statusCode"] == 200
        assert result["sesMessageId"] == "ses-msg-id"
        assert result["slackMessageCount"] == 3
        send_email.assert_called_once()
        send_slack.assert_called_once()

    def test_email_only(self, mocker, sample_digest: NewsDigest) -> None:
        """slack 無効時は send_news_by_category を呼ばずに完了する。"""
        mocker.patch.object(distribute_news, "load_config", return_value=_make_config(slack=False))
        mocker.patch.object(distribute_news, "run_news_agent", return_value=sample_digest)
        send_email = mocker.patch.object(distribute_news, "send_html_email", return_value="msg-id")
        mocker.patch.object(distribute_news, "render_news_email", return_value="<html></html>")
        send_slack = mocker.patch.object(distribute_news, "send_news_by_category")

        result = distribute_news.lambda_handler({}, None)

        send_email.assert_called_once()
        send_slack.assert_not_called()
        assert result["slackMessageCount"] == 0

    def test_slack_only(self, mocker, sample_digest: NewsDigest) -> None:
        """email 無効時は HTML レンダリングと send_html_email がスキップされる。"""
        mocker.patch.object(distribute_news, "load_config", return_value=_make_config(email=False))
        mocker.patch.object(distribute_news, "run_news_agent", return_value=sample_digest)
        send_email = mocker.patch.object(distribute_news, "send_html_email")
        render = mocker.patch.object(distribute_news, "render_news_email")
        send_slack = mocker.patch.object(distribute_news, "send_news_by_category", return_value=3)

        result = distribute_news.lambda_handler({}, None)

        send_email.assert_not_called()
        render.assert_not_called()  # email無効ならHTMLレンダリングもスキップ
        send_slack.assert_called_once()
        assert result["sesMessageId"] is None
