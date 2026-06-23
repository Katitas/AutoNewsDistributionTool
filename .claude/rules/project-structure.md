# プロジェクト構造マップ

<!-- /init-project 実行時に自動生成されます。以降、Claude Codeとの対話で育ててください。 -->

## 命名規則

コードベース全体で統一された命名パターンを定義する。
Claudeがファイルを探索・新規作成する際の判断基準となる。

| 種別 | パターン | 例 |
|------|----------|-----|
| Lambdaハンドラー | `{動詞}_{対象}.py` | `fetch_news.py`, `send_email.py` |
| テストファイル | `test_{対象}.py` | `test_fetch_news.py` |
| CloudFormationテンプレート | `{対象}-stack.yaml` | `lambda-stack.yaml` |
| 設計書 | `NN_{トピック}.md` | `01_アーキテクチャ設計.md` |

---

## ディレクトリ構造

```
AutoNewsDistributionTool/
├── src/
│   ├── handlers/        # Lambdaハンドラー（1ファイル=1機能）
│   │   ├── fetch_news.py    # Bedrockからニュース取得・要約
│   │   └── send_email.py    # SESでメール送信
│   └── utils/           # 共通ユーティリティ
├── tests/               # pytestテストコード
├── infra/               # CloudFormationテンプレート
│   └── template.yaml    # Lambda/EventBridge/SES スタック定義
├── docs/                # ドキュメント
└── requirements.txt     # Python依存パッケージ
```

---

## 主要ファイル

| ファイル | 用途 |
|----------|------|
| `src/handlers/fetch_news.py` | Bedrockニュース取得・要約ハンドラー |
| `src/handlers/send_email.py` | SESメール送信ハンドラー |
| `src/services/url_normalizer.py` | 配信前の記事 URL 補正（既知失効ホストの書き換え。例: housenews.jp→www.housenews.jp） |
| `infra/template.yaml` | CloudFormation メインスタック定義 |
| `requirements.txt` | Python依存パッケージ |

---

## 設定ファイル

| 用途 | 場所 |
|------|------|
| CloudFormationスタック定義 | `infra/template.yaml` |
| Python依存パッケージ | `requirements.txt` |
| テスト設定 | `pytest.ini` または `pyproject.toml` |

---

## ソースコードと設計書の対応表

コードのどの部分がどの設計書に対応するかを明示する。
この表を維持することで、設計書と実装の乖離を早期に発見できる。

| ソースコードの範囲 | 対応する設計書 | 備考 |
|-------------------|--------------|------|
<!-- 例:
| src/handlers/fetch_news.py | docs/design/01_ニュース取得設計.md | Bedrock呼び出し仕様 |
| src/handlers/send_email.py | docs/design/02_メール配信設計.md | SES送信仕様 |
| infra/template.yaml | docs/design/10_インフラ設計.md | EventBridge、Lambda設定 |
-->

---

## 注記

- 主要ファイルのみ記載。新規ファイルは命名規則に従って探索すること
- このファイルはプロジェクトの成長に合わせて随時更新する
- **新しいディレクトリやファイルパターンが増えたら、必ずここに追記する**
