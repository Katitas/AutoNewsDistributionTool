import os

import pytest

from src.models.news import NewsDigest, NewsItem


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """moto 用ダミー認証情報。本物の認証情報をテストで使わないための保険。"""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")


def _make_item(
    *,
    title: str = "AI住宅査定サービス、中古戸建分野で精度95%超に到達",
    summary: str | None = None,
    category: str = "PropTech",
    katitas_relevance: str = "買取査定の一次スクリーニングに活用できる可能性があります。営業所別の査定品質ばらつき解消に有効です。",
    source_url: str = "https://example.com/news/proptech/article-001",
) -> NewsItem:
    return NewsItem(
        title=title,
        summary=summary or ("国内主要PropTech3社が中古戸建向けAI査定サービスを公開した。" * 6),
        category=category,
        katitas_relevance=katitas_relevance,
        source_url=source_url,
    )


@pytest.fixture
def sample_digest() -> NewsDigest:
    """5件のサンプル NewsDigest（カテゴリ重複あり: PropTech×2, 法規制×2, マーケット×1）。"""
    return NewsDigest(
        items=[
            _make_item(category="PropTech", title="PropTech ニュース 1", source_url="https://example.com/news/p1"),
            _make_item(category="PropTech", title="PropTech ニュース 2", source_url="https://example.com/news/p2"),
            _make_item(category="法規制・政策", title="法規制 ニュース 1", source_url="https://example.com/news/l1"),
            _make_item(category="法規制・政策", title="法規制 ニュース 2", source_url="https://example.com/news/l2"),
            _make_item(category="マーケット・価格動向", title="マーケット ニュース 1", source_url="https://example.com/news/m1"),
        ]
    )
