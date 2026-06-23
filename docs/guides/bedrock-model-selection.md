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
| Foundation Model ID | `anthropic.claude-opus-4-8` | × Tokyo ではエラー（on-demand 非対応） |
| Inference Profile ID（Japan） | `jp.anthropic.claude-opus-4-8` | ◯ 推奨（東京/大阪に限定ルーティング） |
| Inference Profile ID（APAC） | `apac.anthropic.claude-opus-4-7-20260101-v1:0` | ◯（APAC 広域にルーティング） |
| Inference Profile ID（US） | `us.anthropic.claude-opus-4-7-20260101-v1:0` | △ レイテンシ大 |

> プレフィックスは `jp.`（日本国内 = 東京/大阪）と `apac.`（APAC 広域）が存在する。
> どちらが利用可能かは `aws bedrock list-inference-profiles` の `inferenceProfileId` で確認すること。
> バージョン日付サフィックスの有無もモデルにより異なるため、取得した ID をそのまま使う。

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

> **重要（2026 仕様変更）**: 旧「Model access」ページは**廃止**された（"Model access page has been retired"）。
> 現在は **初回 invoke 時に自動有効化** される方式に変わっている。ただし以下2点の前提がある。

### 1. Anthropic モデルの use case details 提出（初回のみ）

Anthropic 系モデルは初回利用時に**用途説明（use case details）の提出**を求められる場合がある。
Bedrock コンソール → Model catalog → 対象モデル → Playground を開くと表単が出るので記入・提出する。

### 2. Marketplace 配信モデルの账号级有効化（初回1回）

Marketplace 経由で配信されるモデルは、「**AWS Marketplace 権限を持つユーザーが1回 invoke**」すると
**账号级で全ユーザー（Lambda 実行ロール含む）に有効化**される。

- **正しい手順**: 管理者（人間の SSO PowerUser 等、Marketplace 権限あり）が Playground または CLI で
  対象モデルを1回呼ぶ。これで账号级に有効化され、以後 Lambda の `bedrock:Converse` が通る。
- ⚠️ **アンチパターン**: この問題を消すために Lambda 実行ロールへ `aws-marketplace:Subscribe` /
  `ViewSubscriptions` を付与してはいけない。启用は管理者の一次性操作であり、
  運行時ロールに恒久的な Marketplace 権限を持たせるのは過剰権限。

```powershell
# 管理者プロファイルで1回呼んで账号级有効化（例）
aws bedrock-runtime converse `
  --model-id jp.anthropic.claude-opus-4-8 `
  --messages '[{"role":"user","content":[{"text":"test"}]}]' `
  --region ap-northeast-1 --profile <admin-poweruser>
```

> **注意**: STG/Prod が別 AWS アカウントの場合は **両方で別々に** 上記の初回有効化が必要。

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
    - !Sub arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:inference-profile/jp.anthropic.claude-*
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
