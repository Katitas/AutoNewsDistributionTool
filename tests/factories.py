"""テスト用 NewsDigest / NewsItem ファクトリ。

NewsDigest の目標は全カテゴリ各 ITEMS_PER_CATEGORY 件・計 TARGET_TOTAL_ITEMS 件だが、
件数は可変（不足を許容）。テストでは用途に応じて make_balanced_items（完全な30件）と
make_items（カテゴリ→件数を指定した任意構成）を使い分ける。
本モジュールはそのボイラープレートを一元化する。
"""

from src.models.news import (
    CATEGORIES,
    ITEMS_PER_CATEGORY,
    TARGET_TOTAL_ITEMS,
    NewsDigest,
    NewsItem,
)

# summary は 60〜120字（2〜3行）制約。63字で範囲内に収める。
_DEFAULT_SUMMARY = (
    "国内主要PropTech3社が中古戸建向けのAI査定サービスを相次いで公開した。"
    "査定精度の向上で買取業務の効率化が期待される。"
)
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
    """CATEGORIES 順に各カテゴリ ITEMS_PER_CATEGORY 件、計 TARGET_TOTAL_ITEMS 件を生成する。

    Args:
        title_prefix: タイトルの接頭辞（`{prefix} {idx}` で連番化）。
        title: 指定時は全件で同一タイトルを使う（エスケープ検証など用途別）。
        url_prefix: source_urls 未指定／不足分の URL 接頭辞。
        summary: 全件共通の summary（None なら既定値）。
        source_urls: 先頭から順に割り当てる URL。不足分は url_prefix で補完する。
    """
    items: list[NewsItem] = []
    for idx in range(TARGET_TOTAL_ITEMS):
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


def make_items(counts: dict[str, int]) -> list[NewsItem]:
    """カテゴリ→件数の指定で任意構成の NewsItem 群を生成する（不足・偏り・超過テスト用）。"""
    items: list[NewsItem] = []
    for category, n in counts.items():
        for i in range(n):
            items.append(
                make_item(category=category, source_url=f"https://example.com/{category}/{i}")
            )
    return items


def make_digest(**kwargs) -> NewsDigest:
    """検証を通過する完全な NewsDigest（計 TARGET_TOTAL_ITEMS 件）を作る。"""
    return NewsDigest(items=make_balanced_items(**kwargs))
