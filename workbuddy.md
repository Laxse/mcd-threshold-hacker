# workbuddy.md · 开发上下文导出

> 本文件为麦当劳程序员节创意开发大赛「WorkBuddy 专项奖励」所需材料：
> 记录本项目在 WorkBuddy 中以 Agent 模式从分析、实测、可行性评估到落地开发的完整上下文。
> 配合本仓库代码、README、SKILL.md、CONTEST_DECLARATION.md 一同提交。

---

## 1. 任务起点

- 用户请求：分析 `M-China/mcd-developer-innovation-challenge` 比赛，并了解麦当劳 MCP 的用法。
- 关键结论（先给结论再展开）：
  **比赛只按 GitHub 公开 Star 排名，不评审代码。** 策略必须围绕「选题差异化 + 可传播性」而非功能堆砌。

## 2. 比赛规则要点（决定策略）

| 维度 | 事实 |
|---|---|
| 排名依据 | GitHub 公开 Star 总数，定榜时间 2026-10-26 00:00 |
| 项目创建时间 | 必须落在 2025-12-25 ~ 2026-10-25（新仓库） |
| 同账号多项目 | 仅 Star 最高者进榜（一人一个有效参赛项目） |
| Star = 0 | 不进排行榜 |
| 专项奖励 | 提交本文件 `workbuddy.md` + 进榜 → 3000 WorkBuddy 积分 |

## 3. MCP 接入实测（用户提供 Token 后）

- 协议：Streamable HTTP，地址 `https://mcp.mcd.cn`，认证 `Authorization: Bearer <token>`。
- `tools/list` 实测返回 **35 个工具**（官方 README 仅列 33 个）。
- **勘误（对参赛有决定性影响）**：
  - `query-promotions`：官方 README **完全未收录**，实测真实存在，且仅 `beType=6` 企业团餐场景返回满减/满折规则。
  - `query-survey-coupon`：同样未收录。
  - `query-party-store-date` / `query-party-store-session`：官方写作 `query-partystore-*`（缺 store），**实测真实名带 store**。
- 服务端**无状态**，不返回 `Mcp-Session-Id`，单次 `tools/call` 可直接调用。

## 4. 可行性评估（创意 1：促销规则叠加引擎）

全链路用真实 Token 跑通：地址 → 门店 → 助餐服务 → 52 个餐品 → 促销规则 → 算价验证。

三个决定性发现：

1. `query-promotions` 仅限企业团餐（beType=6）。个人 Token 即可跑通，无需企业资质。
2. `calculate-price` **不接受 promotionId**，折扣由服务端按 `gmServiceCode` 自动匹配。
3. 折扣深度与助餐服务等级绑定；实测 ¥780 订单：`enjoyable.balance = 22000` 分（¥220），
   即「再买 ¥220 餐品，折扣从 7.4 折降到 7.0 折」—— 服务端直接给出凑单差额。

实测价格构成（¥780 餐品 + ¥6 配送 + ¥32 打包 = ¥818）：

```
productPrice = 57720 分   ← 780 × 0.74，精确命中 7.4 折（折扣基准是餐品小计）
deliveryPrice = 0         ← 配送费全免
packingPrice  = 900 分
price         = 58620 分
```

## 5. 用户决策与落地

- 用户确认方案 A：**团餐凑单引擎**（B 端蓝海，差异化最强）。
- 命名策略：对外称「凑单最优解引擎」，把技术亮点放前、团餐作为实现场景，兼顾稀缺性与传播力。
- 初始化仓库 `mcd-threshold-hacker`，全程在 WorkBuddy 内开发与单测。

## 6. 算法开发（scripts/promotion_ladder.py）

三层结构：规则解析 → 组合搜索 → 差额提示。纯标准库、零网络 IO、零第三方依赖，便于单测。

- 初版用单阶梯模型，单测发现与实际价格不符 → 实测取全量 12 条规则，确认是「3 服务 × 4 门槛」矩阵。
- 修正折扣基准为「餐品小计」（非订单总额）。
- 修正 `applies_to` 在餐品为空时的误判。
- 修正 `marginal_gain` 语义：返回（额外支出, 额外减免, 净多付），并区分「净多付为正」与「净省（白加餐）」两种表述。
- 最终 **21 个单测全部通过**，测试数据全部来自真实 MCP 返回（非构造假数据）。

## 7. 交付物清单

| 文件 | 作用 |
|---|---|
| `SKILL.md` | WorkBuddy 技能定义（核心交付物） |
| `README.md` | 项目介绍 / 安装 / 演示 / 规则矩阵 |
| `workbuddy.md` | 本文件（专项奖励必备） |
| `CONTEST_DECLARATION.md` | 参赛声明（原样复制） |
| `mcp-config.example.json` | MCP 接入示例（占位符，无真实 Token） |
| `scripts/promotion_ladder.py` | 算法核心 |
| `scripts/mcp_client.py` | 麦当劳 MCP 客户端 |
| `scripts/demo.py` | 脱机/实时演示 |
| `scripts/tests/test_promotion_ladder.py` | 21 个单测 |
| `references/MCP_TOOLS.md` | 35 工具参考（实测名 + 隐藏工具勘误） |
| `references/USER_PROFILE.md` | 用户偏好持久化方案（差异化核心） |

## 8. 合规自检

- ✅ 未将真实 Token / 地址 / 门店编码写入仓库（见 `.gitignore`）。
- ✅ 配置文件仅用 `${MCD_MCP_TOKEN}` 占位符。
- ✅ 金额一律以 `calculate-price` 实时返回为准，未将券面文字当优惠。
- ✅ 未与其他品牌做对比。

---

*以上上下文由 WorkBuddy Agent 模式在开发过程中持续记录并导出。*
