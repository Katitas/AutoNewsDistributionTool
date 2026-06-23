import pytest
from pydantic import ValidationError

from src.models.news import (
    CATEGORIES,
    ITEMS_PER_CATEGORY,
    TOTAL_ITEMS,
    NewsDigest,
    NewsItem,
)
from tests.factories import make_balanced_items


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
    def test_balanced_digest_accepted(self) -> None:
        """全カテゴリ各 ITEMS_PER_CATEGORY 件・計 TOTAL_ITEMS 件は受理される。"""
        digest = NewsDigest(items=make_balanced_items())
        assert len(digest.items) == TOTAL_ITEMS == ITEMS_PER_CATEGORY * len(CATEGORIES)

    def test_fewer_than_total_rejected(self) -> None:
        """総件数が TOTAL_ITEMS 未満は min_length で弾かれる。"""
        items = make_balanced_items()[:-1]
        with pytest.raises(ValidationError):
            NewsDigest(items=items)

    def test_more_than_total_rejected(self) -> None:
        """総件数が TOTAL_ITEMS 超過は max_length で弾かれる。"""
        items = make_balanced_items()
        items.append(items[0])
        with pytest.raises(ValidationError):
            NewsDigest(items=items)

    def test_unbalanced_category_rejected(self) -> None:
        """総件数 TOTAL_ITEMS でもカテゴリが偏っていれば model_validator で弾かれる。"""
        # 全件を単一カテゴリにすると総件数は合うがカテゴリ均衡が崩れる。
        kwargs = _valid_item_kwargs()  # category=PropTech 固定
        items = [NewsItem(**kwargs) for _ in range(TOTAL_ITEMS)]
        with pytest.raises(ValidationError, match="各カテゴリ"):
            NewsDigest(items=items)
