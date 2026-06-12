# プロンプト管理ガイド

Bedrock に送信するプロンプトは Parameter Store で管理する。
コード変更なしに本番のプロンプトを差し替え可能。

---

## ファイル配置

| 役割 | 場所 |
|------|------|
| 正本（Git管理） | `docs/design/prompt.txt` |
| 実行時の読込元 | Parameter Store `/kati/auto_news_distribute/{env}/prompt` |

`docs/design/prompt.txt` は純粋にプロンプト本文のみを含む。コメントや注記は一切書かない（そのまま Bedrock に送信される内容のため）。

---

## 更新フロー

1. `docs/design/prompt.txt` を編集してコミット
2. レビュー
3. Parameter Store に反映（環境ごとに実行）：

```bash
# STG 環境
aws ssm put-parameter \
  --name /kati/auto_news_distribute/stg/prompt \
  --value "$(cat docs/design/prompt.txt)" \
  --type String \
  --overwrite \
  --region ap-northeast-1

# 本番環境（STG検証後）
aws ssm put-parameter \
  --name /kati/auto_news_distribute/prod/prompt \
  --value "$(cat docs/design/prompt.txt)" \
  --type String \
  --overwrite \
  --region ap-northeast-1
```

4. Lambda を手動トリガーして動作確認

---

## 制約

- **サイズ上限**: Standard parameter は **4KB**（UTF-8バイト数）。超える場合は Advanced（8KB、有料）に変更が必要。
- **改行コード**: `\n` のまま格納される。Windows (`\r\n`) で保存しないこと。
- **特殊文字**: `$`, `` ` ``, `"` を含む場合、シェルエスケープが必要なケースあり。

---

## プロンプト変更時の注意

プロンプトでカテゴリ名や項目（title/summary/category/katitas_relevance）を変更する場合：

- `src/models/news.py` の `NewsCategory` Literal や `NewsItem` フィールドも**同時に**更新する
- スキーマ不一致は Bedrock Tool Use で実行時エラーとなる
- ローカルテスト（`pytest`）で必ず確認してから本番に反映する

---

## 関連

- `src/services/bedrock_client.py` - Tool Use でスキーマ強制
- `src/services/parameter_store.py` - prompt の読み込み実装
- `.claude/rules/deploy-workflow.md` - デプロイ全般
