from collections import Counter
from typing import Literal, get_args

from pydantic import BaseModel, Field, model_validator


NewsCategory = Literal[
    "PropTech",
    "企業動向",
    "法規制・政策",
    "マーケット・価格動向",
    "海外不動産",
    "リフォーム関連",
]

# 1カテゴリあたりの配信件数。全カテゴリ均等に ITEMS_PER_CATEGORY 件ずつ選ぶ。
ITEMS_PER_CATEGORY = 5
# 対象カテゴリ一覧（NewsCategory Literal から動的取得。分類の増減はここに追従する）。
CATEGORIES: tuple[str, ...] = get_args(NewsCategory)
# 1日あたりの総件数 = カテゴリ数 × 各カテゴリ件数（現状 6 × 5 = 30）。
TOTAL_ITEMS = ITEMS_PER_CATEGORY * len(CATEGORIES)


class NewsItem(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="ニュース見出し。事実を端的に伝える。煽り表現は避ける。",
    )
    summary: str = Field(
        ...,
        min_length=200,
        max_length=800,
        description=(
            "ニュース本文の詳細な要約。可能な限り詳しく記述する。"
            "背景・経緯・関与する企業や機関・影響範囲・今後の見通し・"
            "関連する数値や日付などを含めて、読者が原文を読まずとも本質を把握できるレベルの情報量を目指す。"
        ),
    )
    category: NewsCategory = Field(
        ...,
        description="ニュースのカテゴリ。",
    )
    katitas_relevance: str = Field(
        ...,
        min_length=40,
        max_length=300,
        description="カチタスの業務プロセス（中古住宅再生事業、実需向け戸建て）に役立つかのコメント・サジェスチョン。",
    )
    source_url: str = Field(
        ...,
        min_length=8,
        max_length=2000,
        description=(
            "ニュースの原文記事のURL。http:// または https:// で始まる絶対URL。"
            "**そのニュースを報じている個別記事ページのURLでなければならない。**"
            "トップページ・カテゴリ一覧ページ・タグページ・検索結果ページ・"
            "組織のコーポレートサイトなど、当該ニュースを直接報じていないページのURLは禁止。"
            "URL は捏造してはならない。記事URLを特定できないニュースはそもそも選ばないこと。"
        ),
    )


class NewsDigest(BaseModel):
    items: list[NewsItem] = Field(
        ...,
        min_length=TOTAL_ITEMS,
        max_length=TOTAL_ITEMS,
        description=(
            f"本日の不動産ニュース。実需中古住宅事業に関連するもの、"
            f"全{len(CATEGORIES)}カテゴリ各{ITEMS_PER_CATEGORY}件ずつ計{TOTAL_ITEMS}件。"
            f"マンション・投資用は除外。"
        ),
    )

    @model_validator(mode="after")
    def _validate_per_category_balance(self) -> "NewsDigest":
        """各カテゴリがちょうど ITEMS_PER_CATEGORY 件であることを強制する。

        Field の min/max_length は総件数しか縛れないため、カテゴリ偏り
        （例: 30件すべて PropTech）を防ぐにはモデルレベルの検証が必要。
        違反時は ValueError を送出し、Bedrock 側に submit のやり直しを促す。
        """
        counts = Counter(item.category for item in self.items)
        unbalanced = {
            category: counts.get(category, 0)
            for category in CATEGORIES
            if counts.get(category, 0) != ITEMS_PER_CATEGORY
        }
        if unbalanced:
            raise ValueError(
                f"各カテゴリちょうど {ITEMS_PER_CATEGORY} 件が必須（{len(CATEGORIES)}カテゴリ計 {TOTAL_ITEMS} 件）。"
                f"件数が不正なカテゴリ: {unbalanced}"
            )
        return self
