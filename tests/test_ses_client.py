import boto3
import pytest
from moto import mock_aws

from src.services.ses_client import send_html_email


@mock_aws
class TestSendHtmlEmail:
    def _verify_email(self, address: str) -> None:
        client = boto3.client("sesv2", region_name="ap-northeast-1")
        client.create_email_identity(EmailIdentity=address)

    def test_send_to_multiple_recipients_via_bcc(self) -> None:
        self._verify_email("news@example.com")

        message_id = send_html_email(
            sender="news@example.com",
            recipients=["a@example.com", "b@example.com", "c@example.com"],
            subject="テスト件名",
            html_body="<html><body>本文</body></html>",
        )

        assert message_id  # 何らかのIDが返る

    def test_empty_recipients_raises(self) -> None:
        with pytest.raises(ValueError, match="recipients が空"):
            send_html_email(
                sender="news@example.com",
                recipients=[],
                subject="件名",
                html_body="<html></html>",
            )
