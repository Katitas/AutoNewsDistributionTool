"""ニュース記事 URL の既知の不具合を分配前に補正するユーティリティ。

外部検索 API / モデルが返す `source_url` の中には、そのままでは
アクセスできない（リダイレクトで壊れる・正規ホストでない）ものがある。
分配（SES / Slack）前にホスト名を書き換えることで、配信物のリンク切れを防ぐ。

書き換え対象は `_HOST_REWRITES` に明示列挙したホストのみ。
未知ホストは一切いじらない（過剰な正規化で正常 URL を壊さないため）。
"""

from __future__ import annotations

import logging
import urllib.parse

from src.models.news import NewsDigest

logger = logging.getLogger(__name__)

# 既知の「そのままだとアクセスできない」ホストの書き換え表。
# key: 検索結果に現れる誤ったホスト名（小文字）。value: 正しいホスト名。
# スキーム・パス・クエリ・フラグメントは保持し、ホスト名のみ差し替える。
#
#   housenews.jp → www.housenews.jp（www 無しはアクセス不可。docs/issues #15）
#   dreamnews.jp → www.dreamnews.jp（www 無しはアクセス不可。2026-06-30 確認）
_HOST_REWRITES: dict[str, str] = {
    "housenews.jp": "www.housenews.jp",
    "dreamnews.jp": "www.dreamnews.jp",
}


def normalize_url(url: str) -> str:
    """既知の失効ホストを正しいホストに書き換えた URL を返す。

    対象外（未知ホスト・既に正しいホスト）の場合は入力をそのまま返す。

    Args:
        url: 補正対象の絶対 URL。

    Returns:
        ホスト名を補正した URL。対象外なら入力と同一。
    """
    parsed = urllib.parse.urlsplit(url)
    # netloc は "host"、"host:port"、"user@host" を含みうるが、本表は素のホスト名のみ対象。
    new_host = _HOST_REWRITES.get(parsed.netloc.lower())
    if new_host is None or new_host == parsed.netloc:
        return url
    return urllib.parse.urlunsplit(parsed._replace(netloc=new_host))


def apply_url_rewrites(digest: NewsDigest) -> NewsDigest:
    """NewsDigest 内の全 `source_url` に `normalize_url` を適用した新しい digest を返す。

    どの URL も変化しなければ入力をそのまま返す（不要なオブジェクト生成を避ける）。

    Args:
        digest: Bedrock から取得したニュース。

    Returns:
        URL 補正後の NewsDigest（補正不要なら入力と同一インスタンス）。
    """
    new_items = []
    changed = False
    for item in digest.items:
        new_url = normalize_url(item.source_url)
        if new_url != item.source_url:
            changed = True
            logger.info("url rewrite: %s -> %s", item.source_url, new_url)
            new_items.append(item.model_copy(update={"source_url": new_url}))
        else:
            new_items.append(item)
    if not changed:
        return digest
    return digest.model_copy(update={"items": new_items})
