"""テスト用 NewsDigest / NewsItem ファクトリ。

NewsDigest は「全カテゴリ各 ITEMS_PER_CATEGORY 件・計 TOTAL_ITEMS 件」を強制するため、
テストでは常にバランスの取れた完全な digest を組み立てる必要がある。
本モジュールはそのボイラープレートを一元化する。
"""

from src.models.news import (
    CATEGORIES,
    ITEMS_PER_CATEGORY,
    TOTAL_ITEMS,
    NewsDigest,
    NewsItem,
)

_DEFAULT_SUMMARY = "国内主要PropTech3社が中古戸建向けAI査定サービスを公開した。" * 6
_DEFAULT_RELEVANCE = (
    "買取査定の一次スクリーニングに活用できる可能性があります。"
    "営業所別の査定品質ばらつき解消に有効です。"
)


def make_item(
    *,
    title: str = "AI住宅査定サービス、中古戸建分野で精度95%超に到達",
    summary: str | None = None,
    category: str = "PropTech",
    katitas_relevance: str = _DEFAULT_RELEVANCE,
    source_url: str = "https://example.com/news/proptech/article-001",
) -> NewsItem:
    """各フィールドの min_length 制約を満たす単一 NewsItem を作る。"""
    return NewsItem(
        title=title,
        summary=summary or _DEFAULT_SUMMARY,
        category=category,
        katitas_relevance=katitas_relevance,
        source_url=source_url,
    )


def make_balanced_items(
    *,
    title_prefix: str = "ニュース",
    title: str | None = None,
    url_prefix: str = "https://example.com/news",
    summary: str | None = None,
    source_urls: list[str] | None = None,
) -> list[NewsItem]:
    """CATEGORIES 順に各カテゴリ ITEMS_PER_CATEGORY 件、計 TOTAL_ITEMS 件を生成する。

    Args:
        title_prefix: タイトルの接頭辞（`{prefix} {idx}` で連番化）。
        title: 指定時は全件で同一タイトルを使う（エスケープ検証など用途別）。
        url_prefix: source_urls 未指定／不足分の URL 接頭辞。
        summary: 全件共通の summary（None なら既定値）。
        source_urls: 先頭から順に割り当てる URL。不足分は url_prefix で補完する。
    """
    items: list[NewsItem] = []
    for idx in range(TOTAL_ITEMS):
        category = CATEGORIES[idx // ITEMS_PER_CATEGORY]
        if source_urls is not None and idx < len(source_urls):
            url = source_urls[idx]
        else:
            url = f"{url_prefix}/{idx}"
        items.append(
            make_item(
                title=title if title is not None else f"{title_prefix} {idx}",
                summary=summary,
                category=category,
                source_url=url,
            )
        )
    return items


def make_digest(**kwargs) -> NewsDigest:
    """検証を通過する完全な NewsDigest（計 TOTAL_ITEMS 件）を作る。"""
    return NewsDigest(items=make_balanced_items(**kwargs))
