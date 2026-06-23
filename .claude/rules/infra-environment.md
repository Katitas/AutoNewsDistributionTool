# インフラ環境情報

環境のリソース一覧と設定情報。

<!-- このファイルは環境変更のたびに更新する。更新漏れは誤った方針決定の原因となる。 -->

**最終更新**: 2026-06-12
**環境**: AWS (Lambda / EventBridge / Bedrock / SES / Slack)
**アカウント**: 654654327567（prod） / リージョン: ap-northeast-1

---

## クイックリファレンス（よく使う値）

<!-- Claudeや開発者が頻繁に参照するIDやエンドポイントをここに集約する -->

| 項目 | 値 |
|------|-----|
| CFn スタック名（prod） | `auto-news-prod` |
| Lambda 関数名（prod） | `auto-news-distribute-prod` |
| EventBridge Scheduler 名（prod） | `auto-news-daily-prod` |
| Parameter Store パス（prod） | `/kati/auto_news_distribute/prod` |
| Bedrock モデル（prod） | `jp.anthropic.claude-opus-4-8`（Japan Inference Profile） |
| Lambda ロググループ | `/aws/lambda/auto-news-distribute-prod` |

---

## リソース一覧

### コンピュート（Lambda）

| 関数名 | 用途 | メモリ | 最終更新 |
|--------|------|--------|----------|
| `auto-news-distribute-prod` | Bedrock でニュース生成 → SES/Slack 配信 | 512MB | 2026-06-12 |

- ランタイム: python3.13 / arm64 / Timeout 300s
- ハンドラー: `src.handlers.distribute_news.lambda_handler`
- 環境変数: `PARAMETER_PATH=/kati/auto_news_distribute/prod`, `LOG_LEVEL=INFO`
- ロググループ保持: 90日

### イベントトリガー（EventBridge）

| ルール名 | スケジュール | ターゲット | 最終更新 |
|----------|-------------|------------|----------|
| `auto-news-daily-prod` | `cron(0 23 * * ? *)` UTC（= JST 08:00） | `auto-news-distribute-prod` | 2026-06-12 |

- リトライ: 最大5回 / MaximumEventAgeInSeconds 21600
- 失敗時: ScheduleDLQ（SQS）へ送付
- 緊急停止: `aws scheduler update-schedule --name auto-news-daily-prod --state DISABLED --region ap-northeast-1`

### AI/ML（Bedrock）

| モデル | 用途 | 備考 |
|--------|------|------|
| `jp.anthropic.claude-opus-4-8` | ニュース生成・要約（Tool Use） | Japan Inference Profile（東京/大阪ルーティング）。リージョン: ap-northeast-1 |

- **注意**: Foundation Model ID（`anthropic.claude-opus-4-8`）では on-demand 非対応 → 必ず `jp.` / `apac.` プレフィックスの Inference Profile ID を使う
- IAM は `BedrockInvoke` で foundation-model（`anthropic.claude-*`）+ inference-profile（`jp.` / `apac.` の `anthropic.claude-*`）の両方を許可

### メール配信（SES）

| 項目 | 値 | 備考 |
|------|-----|------|
| 送信元アドレス | `news@katitas.jp`（`SenderEmailAddress` パラメータ） | SES Email Identity を CFn が作成。検証状態は要確認（未検証なら送信不可） |
| 実送信フラグ | Parameter Store `recipient-emails` の有無で判定 | 現状メール配信は未使用（recipient-emails 未設定ならスキップ） |

### Slack 通知

| 項目 | 値 | 備考 |
|------|-----|------|
| Webhook URL | Parameter Store: `/kati/auto_news_distribute/prod/slack-webhook-url` | SecureString |

---

## 既知の制約・注意点

<!-- 運用で発見した制約や注意事項を随時追記 -->

1. **Bedrock Claude 4 系は東京単独リージョンに Foundation Model 非デプロイ** → Inference Profile（`jp.` / `apac.`）経由必須。本アカウントは `jp.` プレフィックスが利用可能。
2. **Parameter Store `GetParametersByPath` の IAM** はパス本体（末尾 `/*` なし）と `/*` 配下の両方を許可する必要がある。
3. **STG 環境は未デプロイ**（現状 prod のみで運用）。STG なしの本番直デプロイは `docs/issues/high/list.md` に既知課題として記録あり。

---

## 環境間の差異

| 項目 | 本番 | STG | 備考 |
|------|------|------|------|
| スタック | `auto-news-prod`（デプロイ済み） | `auto-news-stg`（未デプロイ） | STG は samconfig 定義のみ |
| Parameter Store パス | `/kati/auto_news_distribute/prod` | `/kati/auto_news_distribute/stg` | 環境別に別パス |

---

## 手動変更履歴

<!-- IaCで管理されていない手動変更を必ず記録する -->

| 日付 | 変更内容 | 理由 | IaC反映要否 |
|------|----------|------|------------|
| 2026-06-12 | Parameter Store `bedrock-model-id` = `jp.anthropic.claude-opus-4-8` を投入 | Foundation Model ID では on-demand 非対応のため Inference Profile ID に修正 | 不要（Parameter Store は意図的に IaC 管理外） |
