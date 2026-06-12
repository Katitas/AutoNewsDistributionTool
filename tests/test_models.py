import pytest
from pydantic import ValidationError

from src.models.news import NewsDigest, NewsItem


def _valid_item_kwargs() -> dict:
    return {
        "title": "テストニュース",
        "summary": "あ" * 250,
        "category": "PropTech",
        "katitas_relevance": "業務に役立つ示唆。" * 5,
        "source_url": "https://example.com/article/1",
    }


class TestNewsItem:
    def test_valid(self) -> None:
        item = NewsItem(**_valid_item_kwargs())
        assert item.category == "PropTech"

    def test_summary_too_short_rejected(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["summary"] = "短い要約"
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_summary_too_long_rejected(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["summary"] = "あ" * 801
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_invalid_category_rejected(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["category"] = "スポーツ"  # 旧カテゴリ
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_source_url_required(self) -> None:
        kwargs = _valid_item_kwargs()
        del kwargs["source_url"]
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_katitas_relevance_required(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["katitas_relevance"] = "短い"
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)


class TestNewsDigest:
    def test_must_be_exactly_5_items(self) -> None:
        items = [NewsItem(**_valid_item_kwargs()) for _ in range(4)]
        with pytest.raises(ValidationError):
            NewsDigest(items=items)

    def test_more_than_5_rejected(self) -> None:
        items = [NewsItem(**_valid_item_kwargs()) for _ in range(6)]
        with pytest.raises(ValidationError):
            NewsDigest(items=items)

    def test_exactly_5_accepted(self) -> None:
        items = [NewsItem(**_valid_item_kwargs()) for _ in range(5)]
        digest = NewsDigest(items=items)
        assert len(digest.items) == 5
