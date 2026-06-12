import logging

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)


def send_html_email(
    *,
    sender: str,
    recipients: list[str],
    subject: str,
    html_body: str,
    region_name: str = "ap-northeast-1",
) -> str:
    """SES v2 で複数の受信者に HTML メールを送信する（BCC運用）。

    プライバシー保護のため、To には送信元自身を入れ、受信者は BccAddresses に格納する。
    これにより受信者全員が他の受信者のメールアドレスを目にすることを防げる。

    Args:
        sender: 送信元アドレス（SES Identity verified 必須）。To にも入る。
        recipients: 受信者アドレスのリスト（BCC として送信）。空はエラー。
        subject: メール件名。
        html_body: メール本文（HTML）。
        region_name: SES を呼び出すリージョン。

    Returns:
        SES の MessageId（送信ログ追跡用）。

    Raises:
        ValueError: recipients が空の場合。
        botocore.exceptions.ClientError: 送信元未検証 / バウンス率超過 / 一日上限超過 等。
    """
    if not recipients:
        raise ValueError("recipients が空です")

    client = boto3.client(
        "sesv2",
        region_name=region_name,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )

    response = client.send_email(
        FromEmailAddress=sender,
        Destination={
            "ToAddresses": [sender],
            "BccAddresses": recipients,
        },
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            }
        },
    )
    message_id = response["MessageId"]
    logger.info("ses send: message_id=%s, bcc_count=%d", message_id, len(recipients))
    return message_id
