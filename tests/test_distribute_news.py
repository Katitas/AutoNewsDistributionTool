from src.handlers import distribute_news
from src.models.news import NewsDigest
from src.services.parameter_store import AppConfig


def _make_config(
    *, email: bool = True, slack: bool = True, slack_webhook_urls: list[str] | None = None
) -> AppConfig:
    """テスト用の AppConfig を組み立てる。チャネル有効/無効を引数で切替可能。

    slack_webhook_urls を明示すると複数 Webhook ケースを再現できる。
    """
    if slack_webhook_urls is None:
        slack_webhook_urls = ["https://hooks.slack.com/X"] if slack else []
    return AppConfig(
        bedrock_model_id="test-model",
        prompt="プロンプト本文",
        recipient_emails=["a@example.com"] if email else [],
        sender_email="news@example.com" if email else "",
        slack_webhook_urls=slack_webhook_urls,
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

    def test_multiple_slack_webhooks(self, mocker, sample_digest: NewsDigest) -> None:
        """複数 Webhook 設定時は各 URL へ送信し、メッセージ数を合算する。"""
        config = _make_config(
            email=False,
            slack_webhook_urls=["https://hooks.slack.com/A", "https://hooks.slack.com/B"],
        )
        mocker.patch.object(distribute_news, "load_config", return_value=config)
        mocker.patch.object(distribute_news, "run_news_agent", return_value=sample_digest)
        send_slack = mocker.patch.object(distribute_news, "send_news_by_category", return_value=3)

        result = distribute_news.lambda_handler({}, None)

        assert send_slack.call_count == 2
        # 各 Webhook が正しい URL で呼ばれていること。
        called_urls = [c.kwargs["webhook_url"] for c in send_slack.call_args_list]
        assert called_urls == ["https://hooks.slack.com/A", "https://hooks.slack.com/B"]
        assert result["slackWebhookCount"] == 2
        assert result["slackMessageCount"] == 6  # 3 messages × 2 webhooks

    def test_partial_digest_passes_notice_to_slack(self, mocker) -> None:
        """件数不足の digest では notice が生成され、Slack 送信に渡される。"""
        from tests.factories import make_items

        partial = NewsDigest(items=make_items({"PropTech": 3, "企業動向": 2}))
        mocker.patch.object(distribute_news, "load_config", return_value=_make_config(email=False))
        mocker.patch.object(distribute_news, "run_news_agent", return_value=partial)
        send_slack = mocker.patch.object(distribute_news, "send_news_by_category", return_value=2)

        result = distribute_news.lambda_handler({}, None)

        assert result["statusCode"] == 200
        # notice（不足あり）が Slack 送信に渡されている
        notice_arg = send_slack.call_args.kwargs["notice"]
        assert notice_arg is not None
        assert "PropTech(3件)" in notice_arg
