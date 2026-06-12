# Bedrock モデル選定ガイド

Parameter Store `/kati/auto_news_distribute/{env}/bedrock-model-id` に投入する **モデル ID / Inference Profile ID** の選び方を整理する。

---

## 結論（TL;DR）

- **本番推奨**: `apac.anthropic.claude-opus-4-7-20260101-v1:0`（Cross-Region Inference Profile / APAC）
- **STG 推奨（コスト最適）**: `apac.anthropic.claude-sonnet-4-6-20251015-v1:0`
- **動作確認用（最安）**: `apac.anthropic.claude-haiku-4-5-20251001-v1:0`

> 上記 ID はすべて **Inference Profile ID** であり、Foundation Model ID（地域単独）ではない点に注意。

---

## なぜ Inference Profile を使うのか

Bedrock の Claude 4 系（Opus/Sonnet/Haiku）は東京単独リージョンには **Foundation Model としてはデプロイされていない**。
代わりに Anthropic が提供する **Cross-Region Inference Profile** 経由でアクセスする必要があり、これは APAC 内（東京・大阪・ソウル・シンガポール・シドニー等）の複数リージョンに自動ルーティングしてくれる仕組み。

| 区分 | 例 | 利用可否（Tokyo） |
|------|-----|--------------------|
| Foundation Model ID | `anthropic.claude-opus-4-7-20260101-v1:0` | × Tokyo ではエラー |
| Inference Profile ID（APAC） | `apac.anthropic.claude-opus-4-7-20260101-v1:0` | ◯ 推奨 |
| Inference Profile ID（US） | `us.anthropic.claude-opus-4-7-20260101-v1:0` | △ レイテンシ大 |

---

## モデル比較

| モデル | 推奨用途 | 強み | コスト目安（per 1M tokens, in/out） |
|--------|----------|------|--------------------------------------|
| **Claude Opus 4.7** | 本番（高品質要約） | 推論力・出力品質最高、Tool Use 安定 | $15 / $75 |
| **Claude Sonnet 4.6** | STG / 通常運用 | コスパ良好、Tool Use 利用可 | $3 / $15 |
| **Claude Haiku 4.5** | 動作確認・回帰テスト | 最も安く高速 | $0.8 / $4 |

> 価格は2026年5月時点の参考値。最新は[公式料金ページ](https://aws.amazon.com/bedrock/pricing/)を必ず確認。

ニュース要約は **summary 200〜800文字 × 5件 + Tool Use** という比較的高い品質要件のため、本番は Opus 推奨。Sonnet でも実用品質は保てるが、`katitas_relevance` の業務洞察精度に差が出やすい。

---

## ID の確認方法（CLI）

```bash
# APAC リージョンで利用可能な Inference Profile を一覧
aws bedrock list-inference-profiles \
  --region ap-northeast-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'anthropic')].[inferenceProfileId,inferenceProfileName]" \
  --output table
```

このコマンドで返ってくる `inferenceProfileId` をそのまま Parameter Store に投入する。

---

## モデルアクセス有効化（必須）

初回利用時はリージョンごとに「モデルアクセス」のオプトインが必要：

1. AWS コンソール → Bedrock → Model access
2. `Anthropic Claude Opus 4.7` 等を選択 → "Request model access"
3. 数分以内に Approved になる（カチタス AWS アカウントは個人情報なし用途のため通常即時承認）

> **注意**: STG/Prod それぞれの AWS アカウントが分かれている場合は **両方で別々に** 有効化が必要。

---

## Parameter Store への投入例

```bash
ENV=stg

aws ssm put-parameter \
  --name /kati/auto_news_distribute/${ENV}/bedrock-model-id \
  --value "apac.anthropic.claude-sonnet-4-6-20251015-v1:0" \
  --type String --overwrite \
  --region ap-northeast-1
```

---

## IAM Policy の Resource 指定

`infra/template.yaml` の `BedrockInvoke` ポリシーは **Inference Profile ARN + 配下の Foundation Model ARN** の両方を許可する必要がある（Bedrock の内部ルーティング仕様）。

```yaml
- Sid: BedrockInvoke
  Effect: Allow
  Action: [bedrock:InvokeModel, bedrock:Converse]
  Resource:
    - !Sub arn:aws:bedrock:*::foundation-model/anthropic.claude-*
    - !Sub arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:inference-profile/apac.anthropic.claude-*
```

> 1つだけ指定すると `AccessDeniedException: ... not authorized to perform: bedrock:InvokeModel on resource ...` で失敗する。

---

## モデル変更時の運用フロー

1. STG の Parameter Store を新モデルに切替
2. 手動 invoke で配信物の品質確認（特に `katitas_relevance` の的確さ）
3. 1〜2日 STG で日次配信を観察
4. 問題なければ Prod に同じ ID を投入

---

## 関連ドキュメント

- [.claude/rules/deploy-workflow.md](../../.claude/rules/deploy-workflow.md) — 全体のデプロイ手順
- [docs/guides/prompt-management.md](./prompt-management.md) — プロンプト変更運用
