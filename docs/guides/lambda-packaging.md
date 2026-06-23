# Lambda パッケージング & ローカル開発手順（SAM CLI）

AWS SAM CLI を使ってビルド・ローカルテスト・デプロイを行う。
S3 バケットは SAM が自動管理（`resolve_s3 = true`）するため手動管理は不要。

---

## 前提

- Python 3.13（Lambda ランタイムと一致）
- AWS SAM CLI（`sam --version` で 1.130 以降推奨。`ScheduleV2` event source 対応版）
- Docker Desktop（`sam local invoke` 用、ローカル実行不要なら省略可）
- AWS CLI 認証済み（IAM 適切な権限）

---

## ディレクトリ構造

```
AutoNewsDistributionTool/
├── src/                          # Lambda ソースコード
├── tests/                        # pytest テスト
├── requirements.txt              # SAM が依存解決に使う
├── infra/
│   ├── template.yaml             # SAM テンプレート (Transform: AWS::Serverless-2016-10-31)
│   ├── samconfig.toml            # 環境別パラメータ
│   ├── events/                   # ローカル invoke 用イベント
│   │   ├── scheduled.json        # 実本番と同じ空ペイロード
│   │   └── manual-test.json      # 手動テスト識別子付き
│   └── .aws-sam/                 # ビルドアーティファクト (gitignore済)
└── ...
```

---

## ローカル開発フロー

すべてのコマンドは **`infra/` ディレクトリ** で実行する（`samconfig.toml` がここにあるため SAM CLI が自動検出）。

```bash
cd infra
```

### 1. テンプレート検証

```bash
sam validate --lint
```

CFn 構文 + ベストプラクティスを確認。

### 2. ビルド

```bash
sam build
```

これだけで以下が自動実行される：
- arm64 wheel で `requirements.txt` の依存をインストール（`BuildMethod: python3.13`）
- `src/` 配下を `.aws-sam/build/DistributeNewsFunction/` にコピー
- 並列ビルド + キャッシュ有効

ビルド成果物の確認：
```bash
ls -la .aws-sam/build/DistributeNewsFunction/
```

### 3. ローカル実行（オプション、要 Docker）

```bash
# 実本番と同じ空ペイロードで実行
sam local invoke DistributeNewsFunction --event events/scheduled.json

# 手動テスト識別子付きペイロードで実行
sam local invoke DistributeNewsFunction --event events/manual-test.json

# 環境変数を上書き（例: STG の Parameter Store path を指定）
sam local invoke DistributeNewsFunction \
  --event events/scheduled.json \
  --parameter-overrides Environment=stg
```

⚠️ **注意**: ローカル実行でも実 AWS（Parameter Store / Bedrock / SES / Slack）を呼び出します。STG リソースに対してテストするのが安全。

### 4. デプロイ（STG）

```bash
sam deploy --config-env stg
```

初回のみ確認プロンプトが出る場合あり。samconfig.toml の値を使うため引数指定は最小。

### 5. デプロイ（本番）

```bash
sam deploy --config-env prod
```

`confirm_changeset = true` のため変更セットを目視確認してから `y` で実行。

---

## デプロイ後の動作確認

```bash
# 手動でLambdaを起動
aws lambda invoke \
  --function-name auto-news-distribute-stg \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json

cat /tmp/response.json
```

CloudWatch Logs を tail：
```bash
sam logs --stack-name auto-news-stg --tail
```

---

## サイズ目安

| 内訳 | サイズ |
|------|--------|
| pydantic + pydantic-core (arm64 wheel) | 約 6 MB |
| jinja2 + markupsafe | 約 0.3 MB |
| boto3/botocore | 約 12 MB（Lambda ランタイム同梱と重複するが、許容範囲） |
| アプリコード + テンプレート | 約 60 KB |
| **合計** | **約 18 MB** |

50MB の Lambda zip 上限まで余裕あり。

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| `sam build` が `manylinux2014_aarch64` wheel を取得できない | pip がアーキテクチャ判定に失敗 | `sam build --use-container` でビルドコンテナ内で実行 |
| `ImportError: pydantic_core` | x86_64 wheel が混入 | `.aws-sam/` 削除して `sam build --use-container` |
| `Task timed out after 300s` | Bedrock 応答遅い | `Globals.Function.Timeout` を延長（最大 900s） |
| `AccessDeniedException` (Bedrock) | Inference Profile / Foundation Model の IAM 不足 | `template.yaml` の `BedrockInvoke`（profile + foundation-model 両方許可）を確認 |
| `ValidationException: ... on-demand throughput isn't supported` | `bedrock-model-id` が Foundation Model ID | APAC Inference Profile ID（`apac.anthropic.*`）に変更 |
| `MessageRejected` (SES) | 送信元未検証 | SES コンソールで identity verify |
| Slack `invalid_token` | Webhook URL が古い/無効 | Slack 側で再生成、Parameter Store 更新 |
| `sam local invoke` で Docker error | Docker Desktop 起動忘れ | Docker を起動してから再実行 |

---

## ビルドコンテナを使う場合

CI 環境やローカル環境で arm64 wheel 取得に問題がある場合、SAM が公式提供する Lambda 互換ビルドコンテナを使う：

```bash
sam build --use-container
```

これにより Amazon Linux 2 ベースのコンテナ内でビルドされ、確実に Lambda 互換のバイナリが得られる。

---

## GitHub Actions での利用例（将来）

```yaml
- uses: aws-actions/setup-sam@v2
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::ACCOUNT:role/github-actions-deploy
    aws-region: ap-northeast-1
- run: sam build --use-container
  working-directory: infra
- run: sam deploy --config-env stg --no-confirm-changeset
  working-directory: infra
```

OIDC 連携で IAM ロールを assume すれば、長期 access key を GitHub に保存せずに済む。
