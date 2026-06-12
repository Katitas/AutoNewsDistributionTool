# Brave Search API（AWS Marketplace）订阅文件 总结

> **本文档是 `offer-cnu6wrvwefrcu.pdf` 的内容总结。**
> 该 PDF 是在 AWS Marketplace 订阅 Brave Search API 之前需要确认/同意的法律文件集（全 32 页）。
> PDF 生成时间：2026-06-12 2:14 UTC ／ 本总结作成日：2026-06-12

---

## 概要（TL;DR）

订阅 **Brave Search API（Pro 版）** 前必须同意的法律文件集，由 **4 部分**组成：

1. 订阅与计费概要（オファー概要）
2. AWS Marketplace 标准合同（Standard Contract）
3. 数据处理附录（Data Processing Addendum / DPA）
4. 针对 Brave Search API 的专门修正案（Amendment）

**核心要点**：按量计费（$0.005/请求）、可随时取消、Brave 可自由使用搜索查询数据（视为 System Data 而非个人数据）、检索结果禁止落库，且 Buyer（购买者）承担 AI/算法使用相关的赔偿责任。

---

## 1. 订阅与计费概要（PDF 第 1–2 页）

| 项目 | 内容 |
|------|------|
| 产品 | Brave Search API（卖方：Brave） |
| Offer ID | ofer-cnu6wrvwefrcu |
| Offer 类型 | パブリックオファー（公开 Offer） |
| 产品 ID | prod-eerurqrrqwhwk |
| 购买者 AWS 账户 | 654654327567 |
| 计费方式 | **按使用量计费、无终止日期、可随时取消** |
| 单价 | **$0.005/请求**（计费维度：Data for AI、CPM 5美元、50 QPS、月查询数无上限） |
| 货币 | 美元（USD $） |
| 税 | 消费税 10.00%（见积税额・请求先可能变更） |
| 账单发行方 | Amazon Web Services Japan G.K. |

> 注：50 QPS 与「月查询数无上限」是产品规格上限；实际成本按每请求 $0.005 累计。
> CLAUDE.md `deploy-workflow.md` 中提到的检索上限（brave 默认 50/次）是应用侧预算保护，与本合同独立。

---

## 2. AWS Marketplace 标准合同（PDF 第 3–21 页 / 2023 Update）

SaaS 服务订阅通用法律框架，关键条款：

- **许可与限制（§2）**：非独占、不可转让许可；仅限内部业务/产品使用；**禁止**复制、转售、逆向工程、作为独立产品对第三方提供。
- **可接受使用（§7.1）**：禁止传输违法内容、钓鱼/垃圾信息/DoS 攻击、对 Brave 系统做渗透测试。
- **数据归属（§7.2）**：Buyer Data 归 Buyer 所有；Brave 仅为提供服务而处理。
- **责任上限（§8）**：双方责任上限 = 事件发生前 12 个月已付费用；安全事故特例为该金额的 **3 倍**（后被修正案改回 1 倍，见第 4 节）。
- **赔偿（§9）／保险（§11）**：标准赔偿与保险义务条款。
- **适用法律（§12.1）**：纽约州法律、纽约市州法院与联邦法院管辖。
- **终止（§10）**：重大违约 30 天未补救可终止；终止后 45 天内可取回/删除数据。

---

## 3. 数据处理附录 / DPA（PDF 第 22–25 页）

- Brave 作为 **Processor（处理者）**，Buyer 作为 **Controller（控制者）**。
- 符合 GDPR、CCPA；禁止出售个人数据、禁止超出指示处理。
- 涵盖子处理者、国际数据传输、数据泄露通知、审计权（§16）等标准条款。

---

## 4. ⚠️ Brave Search API 专门修正案（PDF 第 28–32 页）— **最重要**

修正案**覆盖**标准合同，是与本产品最相关的实际约束：

| 修正条款 | 实质影响 |
|---------|---------|
| **§7.1.1(e)** | **禁止存储、归档或建立 Search Results 数据库**（除非 Product Listing 允许）→ 不能将检索结果落库长期保存 |
| **§7.2.5（新增）** | **搜索查询数据 = System Data，既非个人数据也非 Buyer Data**。Brave 有权收集、存储、保留、处理和使用搜索查询 |
| **§9.2（Buyer 赔偿大幅扩大）** | Buyer 需为以下情形赔偿 Brave：滥用产品/检索结果、引用检索结果中的第三方内容、其用户行为，**以及 AI/自动化算法决策相关的违法行为** |
| **§9.5 / §9.6.1** | 缩小 Brave 的安全赔偿范围；使用旧版本导致的侵权 Brave 不担责 |
| **§8.4.2** | 安全事故责任上限从「3 倍」**降回 1 倍** 12 个月费用 |
| **§10.2** | **Brave 可提前 60 天书面通知单方终止**服务 |
| **§16（DPA 审计权）** | **整条删除** → Buyer 失去对 Brave 的数据处理审计权 |

---

## 5. 订阅前需特别留意的 3 点（与本项目相关）

1. **检索结果不能落库**（§7.1.1e）
   本项目（AutoNewsDistributionTool）的 agentic loop 若缓存检索结果用于摘要，需确认仅临时使用、不持久化成数据库。

2. **搜索查询会被 Brave 自由使用**（§7.2.5）
   发送给 Brave 的查询词不受个人数据保护，避免在查询中带入敏感信息。

3. **Buyer 承担 AI 使用的法律责任**（§9.2h）
   本系统用 Bedrock 做 AI 摘要，若涉及算法决策合规问题，赔偿责任在 Buyer 方。

---

## 关联文档

- 检索 Provider 设置・预算保护：[../guides/news-search-provider.md](../guides/news-search-provider.md)
- API キー投入手順：`.claude/rules/deploy-workflow.md`（手順 5）
- 原始文件：`offer-cnu6wrvwefrcu.pdf`（同目录）
