from typing import Literal

from pydantic import BaseModel, Field


NewsCategory = Literal[
    "PropTech",
    "企業動向",
    "法規制・政策",
    "マーケット・価格動向",
    "海外不動産",
    "リフォーム関連",
]


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
        min_length=5,
        max_length=5,
        description="本日の不動産ニュース。実需中古住宅事業に関連するもの5件。マンション・投資用は除外。",
    )
