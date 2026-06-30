# 发现的问题

## ⚠️ 已知限制（不修复 / wontfix）

- **#15b** nikkei 记事 URL 经 Slack 点击后 code 变小写导致 404 — **Slack 平台行为，不修复（2026-06-15 判定）**
  - 现象: 在 Slack 中 hover / 直接点击链接 → `article/` 后的 code 变小写 → 404；**右键复制链接则得到正确大写 URL**
  - 根因判定: 右键复制正确 ⇒ **后端发送的 URL 是正确的**；破坏发生在 **Slack 客户端的链接渲染/跳转层**（点击经 Slack 重定向时被小写化）。我们用的是 Slack 显式语法 `<url|label>`（`src/services/slack_client.py:99`），未对 URL 做任何处理。**非后端代码可可靠修复**
  - 规避方法: 接收者「右键复制链接」后在浏览器打开，而非直接点击；或从邮件（SES HTML）端打开
  - 备注: 若日后改主意，`src/services/url_normalizer.py` 的 `_HOST_REWRITES`（#15a）可作为后端缓解基础设施（如赌「裸域 `nikkei.com` 重定向才是小写化环节」，加 `"nikkei.com": "www.nikkei.com"`）

## ✅ 已解决（2026-06-30）

- [x] **#15c** dreamnews.jp URL 缺 `www` 导致失效 → host 重写表に追加
  - 现象: `https://dreamnews.jp/...` 无法访问，实际网页确认后需 `https://www.dreamnews.jp/...`
  - 解决: `src/services/url_normalizer.py` 的 `_HOST_REWRITES` 追加 `"dreamnews.jp": "www.dreamnews.jp"`（#15a と同一機構、host のみ書き換え・scheme/path/query 保持）
  - 影响文件: `src/services/url_normalizer.py`, `tests/test_url_normalizer.py`（dreamnews 书き换え用例 +1）
  - 测试: 91 passed（回归无）
  - ⚠️ 需重新部署 prod（代码变更）: `cd infra && sam build && sam deploy --config-env prod`

## ✅ 已解决（2026-06-24）

- [x] **#17** prod Lambda `BedrockToolUseError: NewsDigest 検証失敗`（summary < 60 字 → 单件违反导致全滞）
  - 现象: `items.23.summary String should have at least 60 characters`（input `'世界的な金利上昇...新聞が報じた。'`）→ submit 验证失败 → 即 raise → **当日新闻分发整体异常终止（0 件）**
  - 根因①（约束矛盾）: `summary` 的 `min_length=60` 与「2〜3行で簡潔に」的指示矛盾。模型写得简洁正确时反被弹回。30 件中只要 1 件低于 60 字即失败
  - 根因②（脆弱性）: `bedrock_client.py:run_news_agent` 中 submit 验证失败 **即 raise**，无重试反馈。任一字段（summary/relevance 字数、各分类件数）违反都会让整日批处理归零
  - 解决（3 层防御：预防 + 保证 + 歯止め）:
    - **① 预防（prompt）**: `docs/design/prompt.txt` 把 summary 约束从「字数」改为「**必ず2〜3文**」主轴（LLM 无法精确数字数，但能可靠遵守句数；2〜3 文自然超过 40 字）
    - **② 保证（schema）**: `src/models/news.py` `summary.min_length` 60 → **40**（最后的砦，与简洁指示一致）
    - **③ 自己修复 + 歯止め（bedrock_client）**: submit 验证失败时不立即 raise，而是把验证错误以 `toolResult(status=error)` + 修正提示返回模型促其重新 submit；但新增 `_MAX_SUBMIT_ATTEMPTS=3` 上限，**连续失败达到 3 次即 raise**，防止结构性无法满足时无限重生成 30 件(≒11K token) 导致 timeout / 成本暴走（1 submit≒200s，3 次仍在 900s 内）
  - 影响文件: `src/models/news.py`, `docs/design/prompt.txt`, `src/services/bedrock_client.py`, `tests/test_bedrock_client.py`
  - 测试: 79 passed（更新「持续失败→3 次封顶 raise」用例 + 新增「首次失败→二次成功回复」用例）
  - ⚠️ **需重新部署 prod（代码变更）+ 重新投入 Parameter Store prompt**: `cd infra && sam build && sam deploy --config-env prod` 且 `aws ssm put-parameter --name /kati/auto_news_distribute/prod/prompt --value (Get-Content docs/design/prompt.txt -Raw) --type String --overwrite --region ap-northeast-1`

## ✅ 已解决（2026-06-23）

- [x] **#16** prod Lambda 调用超时 `Sandbox.Timedout: Task timed out after 300.00 seconds`
  - 现象: prod 手动 invoke → 300 秒后被 Lambda runtime 强制 kill（错误 `errorType: Sandbox.Timedout`）
  - 根因: 每日新闻数 5 → 30 后，agentic loop（`bedrock_client.py:run_news_agent`）**完全逐次执行**，检索 20〜25 ターン（每ターン Converse 5〜15s + 检索 API 1〜3s）+ submit 生成 ~11K tokens，壁时计时间超过 `template.yaml` 的 `Timeout: 300`
  - 次因（联动）: boto3 client 未设 `read_timeout`（botocore 默认 60s），即使 Lambda 上限拉高，单次长 Converse 仍会在 60s 被中断 → 必须与 Lambda Timeout 同时调整
  - 解决:
    - `infra/template.yaml`: `Globals.Function.Timeout` 300 → **900**（CFn 最大值）
    - `src/services/bedrock_client.py`: boto3 `Config` 增加 `connect_timeout=10, read_timeout=870`，`retries.max_attempts` 3 → **2**（长 Converse 重试会二重消耗壁时计时间）
  - 影响文件: `infra/template.yaml`, `src/services/bedrock_client.py`
  - 测试: 78 passed（既存断言不涉及 timeout，无回归）
  - ⚠️ **需重新部署 prod（IaC + 代码变更）**: `cd infra && sam build && sam deploy --config-env prod`
  - ⚠️ 部署后须更新 `.claude/rules/infra-environment.md` 的 Lambda Timeout（现记载 300s 前提）→ 900s
  - 备注（未做的进一步优化，留作 backlog）: ③ 收紧 `_MAX_AGENT_TURNS` / 检索枠以压低壁时计上振；或将 submit 改为按分类分批 / ConverseStream 流式以规避单次长生成

## ✅ 已确认无需改动

- [x] **#2-confirm** Parameter Store「取全量数据是否有必要」
  - 结论: **当前实现已是按 path 取数**，非全量扫描。`src/services/parameter_store.py:78` 为 `get_parameters_by_path(Path=/kati/auto_news_distribute/{env}, Recursive=False)`，只取该路径下直接子参数，甚至比「`/kati/auto_news_distribute` 前缀」要求更精确（按环境隔离）
  - 处置: 无需代码改动

## ✅ 已解决（2026-06-15）

- [x] **#15a** housenews.jp URL 缺 `www` 导致失效 → 分发前 host 规范化
  - 现象: `https://housenews.jp/...` 无法访问，需 `https://www.housenews.jp/...`
  - 解决: 新增 `src/services/url_normalizer.py`，含「已知失效 host 重写表」`_HOST_REWRITES = {"housenews.jp": "www.housenews.jp"}`，仅替换 host（保留 scheme/path/query），未知 host 不动
  - 集成: `distribute_news.py` 在 `run_news_agent` 拿到 digest 后、分发前调用 `apply_url_rewrites(digest)`，SES / Slack 两渠道同时生效
  - 影响文件: `src/services/url_normalizer.py`（新增）, `src/handlers/distribute_news.py`, `tests/test_url_normalizer.py`（新增）, `.claude/rules/project-structure.md`
  - 测试: 77 passed（新增 6 个 url_normalizer 用例）
  - 设计取舍: 仅书写明确列举的 host，**不做激进正规化**（避免误改正常 URL）。nikkei 大小写问题（#15b）根因未定，故暂不入表
  - ⚠️ 需重新部署 prod（代码变更）

- [x] **#14** Slack Webhook 支持多频道同报（逗号 / 分号分割）
  - 需求: `slack-webhook-url` 单值 → 支持多个 URL，分发到多个 Slack 频道
  - 解决:
    - `AppConfig.slack_webhook_url: str` → `slack_webhook_urls: list[str]`，`load_config` 用 `re.split(r"[,;]", ...)` 分割并去空白（`src/services/parameter_store.py`）
    - `slack_enabled` 改为基于列表非空判定
    - `distribute_news.py` 循环对每个 Webhook 调用 `send_news_by_category`，返回 `slackMessageCount`（合计消息数）+ `slackWebhookCount`（Webhook 数）
  - Parameter Store 侧无需改类型（值里放 `url1,url2` 即可，保持 SecureString）；IaC 无改动
  - 影响文件: `src/services/parameter_store.py`, `src/handlers/distribute_news.py`, `tests/test_parameter_store.py`, `tests/test_distribute_news.py`
  - 测试: 71 passed（新增 webhook 分割 + 多 webhook 分发 2 个用例）
  - ⚠️ 部分失败时（某个 Webhook 抛 SlackSendError）会中断后续发送并经 Scheduler 重试 → 已成功的 Webhook 可能重复投稿（冪等性未保证，沿用既有权衡）
  - ⚠️ 需重新部署 prod（代码变更）: `sam build && sam deploy --config-env prod`

## ✅ 已解决（2026-06-12）

- [x] **#13** prod Lambda 调用 Bedrock `Converse` 报 `AccessDeniedException`（`aws-marketplace:Subscribe` / Model 未启用）
  - 现象: 模型未在账号级启用，首次 invoke 触发自动订阅但被拒
  - 原因: ① Model access 页面已废弃，改为「首次 invoke 自动启用」；② Anthropic 模型需先提交 use case details（只能走控制台）；③ CLI 裸 converse 无法弹出该表单 + 部分身份缺 Marketplace 权限
  - 解决: 用 **AdministratorAccess 的 IAM 账号**在 Bedrock 控制台 Playground 打开 Claude Opus 4.8 → 提交 use case 表单 → 调用一次 → 账号级启用成功
  - 排查弯路: 一度误判为 SCP 全面 Deny，但「该 IAM 账号能成功订阅 Brave」反证了 marketplace 权限未被全局封 → 撤回 SCP 说，实际是控制台启用流程问题
  - 教训: Lambda role **不需要** marketplace 权限；账号级启用是管理员一次性操作；Anthropic 模型务必先走控制台提交用途表单
  - **コード/IaC 侧无改动**（既有 `bedrock:Converse` 权限即可）

- [x] **#12** prod Lambda 调用 Bedrock `Converse` 报 `ValidationException`（`temperature` is deprecated）
  - 现象: `The model returned the following errors: temperature is deprecated for this model.`
  - 原因: `bedrock_client.py:345` 的 `inferenceConfig` 传了 `temperature: 0.4`，但 Claude Opus 4.8 起该参数被废弃，显式指定即报错
  - 解决: 移除 `temperature`，`inferenceConfig` 仅保留 `maxTokens: 4096`（temperature 交由模型默认值）
  - 影响文件: `src/services/bedrock_client.py`
  - 测试: 69 passed（无测试断言 temperature，移除安全）
  - ⚠️ 需重新部署 prod（代码变更）: `sam build && sam deploy --config-env prod`

- [x] **#11** prod Lambda 调用 Bedrock `Converse` 报 `ValidationException`（on-demand throughput 不支持）
  - 现象: 模型 ID `anthropic.claude-opus-4-8`（Foundation Model ID）在东京区不支持 on-demand，要求 Inference Profile
  - 原因①（配置）: Parameter Store `bedrock-model-id` 填成了 Foundation Model ID，应为 APAC Inference Profile ID（`apac.anthropic.*`）→ 需 `aws ssm put-parameter` 修正（不需重新部署代码）
  - 原因②（IAM 遗漏）: `template.yaml` 的 `BedrockInvoke` 只授权 `arn:...:ap-northeast-1::foundation-model/*`，缺 inference-profile ARN 且 region 锁死，修原因①后会接着撞 AccessDenied
  - 补充: 本账号实际可用的是 **`jp.` 前缀**（Japan profile = `jp.anthropic.claude-opus-4-8`，东京/大阪路由），非 `apac.`。IAM 已同时授权 `jp.` 和 `apac.` 两种前缀
  - 解决: `BedrockInvoke` Resource 改为列表（`bedrock:*::foundation-model/anthropic.claude-*` + `inference-profile/jp.anthropic.claude-*` + `inference-profile/apac.anthropic.claude-*`），删除已不用的 `BedrockModelArn` 参数；与 `docs/guides/bedrock-model-selection.md` 对齐
  - 影响文件: `infra/template.yaml`, `README.md`, `docs/guides/lambda-packaging.md`
  - ⚠️ 需 ① 重新部署 prod（IAM 变更）+ ② 更新 Parameter Store `bedrock-model-id` 为正确 profile ID

- [x] **#10** prod Lambda 调用 `GetParametersByPath` 报 `AccessDeniedException`
  - 现象: `arn:...:assumed-role/auto-news-prod-DistributeNewsFunctionRole/...` 无权对 `parameter/kati/auto_news_distribute/prod` 执行 `ssm:GetParametersByPath`
  - 原因: IAM 策略只授权了 `.../${Environment}/*`，但 `GetParametersByPath` 鉴权检查的是**查询路径本体**（`.../prod`，末尾无 `/*`），两者不匹配
  - 解决: `template.yaml` 的 `ParameterStoreRead` Resource 改为列表，同时授权路径本体和 `/*` 配下
  - 影响文件: `infra/template.yaml`
  - ⚠️ 需重新部署 prod 后生效（`sam build && sam deploy --config-env prod`）

## ✅ 已解决（2026-05-06）

- [x] **#1** 实际调用的获取新闻的tool function(submit_news_digest)没有定义和编写
  - 解决: `submit_news_digest` 是终端工具（Bedrock 输出 → Pydantic 验证 → 返回），新增了 `search_real_news` 实搜索工具，由 `bedrock_client.py:run_news_agent()` 内部 dispatch 处理
  - 影响文件: `src/services/bedrock_client.py`, `src/services/news_search.py`
- [x] **#2** bedrock_client.py中BedrockToolUseError没有实装
  - 解决: 添加 `stop_reason` / `content_blocks` / `validation_errors` 字段保存调试信息
  - 影响文件: `src/services/bedrock_client.py`
- [x] **#3** slack_client.py中SlackSendError没有实装
  - 解决: 添加 `category` / `status_code` / `response_body` 字段
  - 影响文件: `src/services/slack_client.py`
- [x] **#4** 实际代码和测试代码的function没有写注释
  - 解决: 主要 service 函数和测试类全部添加 Google Style docstring
  - 影响文件: `src/services/*.py`, `src/handlers/*.py`, `tests/*.py`
- [x] **#5** 需求变更: bedrock 自主决定关键词调用 search 工具，结果分发为 SES 用 HTML JSON 和 Slack 用 Block Kit JSON
  - 解决: 实现 Agentic Tool Use Loop（多轮 search → submit），SES/Slack 格式分发已通过既存的 `html_renderer.py` / `slack_client.py` 实现
  - Tavily 1000/月无料枠保护: 1 invocation 上限 25 次（30日 = 750 次/月，25% 缓冲）
  - 影响文件: `src/services/bedrock_client.py`, `src/services/news_search.py`, `docs/design/prompt.txt`
- [x] **#6** bedrock_model_id能填什么没有指引
  - 解决: 创建 `docs/guides/bedrock-model-selection.md`，列出 APAC inference profile ID 和 CLI 查询命令
- [x] **#7** 部署时怎么指定aws环境没有指引
  - 解决: `.claude/rules/deploy-workflow.md` 增加「AWS アカウント / リージョンの指定方法」章节，覆盖 SSO / Profile / 防呆检查
- [x] **#8** 这个项目使用aws服务所有的成本都需要通过赋予一个tag来在aws上进行统计和查看
  - 解决: `template.yaml` 增加 `ProjectTag` / `CostCenterTag` 参数，`samconfig.toml` 通过 `tags = ...` 让 CFn 自动传播到所有支持 Tag 的资源；LogGroup / SQS / SNS 显式 Tags 标注
  - ⚠️ 待用户确认: 标签命名是否符合 katitas 组织标准（默认 Project / CostCenter / Environment / ManagedBy）
- [x] **#9** template.yaml中没有关于SESIdentity之类的设置
  - 解决: 新增 `AWS::SES::EmailIdentity` 资源 + `SenderEmailAddress` 参数，IAM 的 SES Resource 收紧到该 identity ARN（`ses:FromAddress` Condition）
  - 影响文件: `infra/template.yaml`

---

## 🔧 残课题（部署/运维侧）

- [ ] Tavily API 密钥获取 → Parameter Store 投入（`/kati/auto_news_distribute/{env}/news-search-api-key`）
- [ ] 标签命名（`samconfig.toml` 的 `tags = ...`）调整为 katitas 组织标准
- [ ] STG 部署后手动 invoke 验证 agentic loop 实际行为
- [ ] SES Email Identity 验证邮件点击确认（部署后 AWS 自动发送）
