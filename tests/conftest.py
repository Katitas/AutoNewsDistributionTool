import os

import pytest

from src.models.news import NewsDigest
from tests.factories import make_digest


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """moto 用ダミー認証情報。本物の認証情報をテストで使わないための保険。"""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")


@pytest.fixture
def sample_digest() -> NewsDigest:
    """検証を通過する完全な NewsDigest（全6カテゴリ各5件・計30件）。

    CATEGORIES 順に各カテゴリ5件ずつ連番タイトルで生成される。
    """
    return make_digest()
