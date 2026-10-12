# MCP 集成说明（MCP_INTEGRATION.md）

本文档说明本项目中**实际使用的麦当劳 MCP Server、调用的 Tool、调用流程及其业务价值**，供核验与复用。

## 1. 接入的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp`（麦当劳官方 MCP Server） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | **Streamable HTTP**（POST JSON-RPC，非 SSE） |
| 认证方式 | `Authorization: Bearer <token>`（token 在 `https://open.mcd.cn/mcp` 手机号登录后申请） |
| 限流 | 600 次/分钟，超出返回 `429` |
| 会话状态 | **服务端无状态**，不返回 `Mcp-Session-Id`，单次 `tools/call` 可直接调用，无需先 `initialize` 握手（握手可成功但非必需） |
| 返回结构 | `tools/call` 的文本 content 通常形如 `## Original Response\n{...json...}`；`tools/list` 直接返回 `{result:{tools:[...]}}` |

接入配置示例见根目录 `mcp-config.example.json`（仅含 `${MCD_MCP_TOKEN}` 环境变量占位符，无真实凭证）。

## 2. 实际调用的 Tool 清单

本项目核心场景为**企业团餐（beType=6）**，实测共调用以下工具（名称以 `tools/list` 实测为准；官方 README 存在遗漏与拼写错误，详见第 4 节）：

| Tool | 场景 | 作用 | 关键入参 | 关键返回 |
|---|---|---|---|---|
| `delivery-query-addresses` | 团餐前置 | 获取用户配送地址列表 | 无 | `addressId` |
| `delivery-query-stores` | 团餐前置 | 按地址查可配送门店 | `addressId`, `beType=6` | `storeCode`, `beCode` |
| `query-meal-assistance` | 团餐 | 获取门店可用助餐服务等级 | `storeCode`, `beCode`, `beType=6` | `gmServiceCode`（GMS001/002/003，其中 GMS002/003 需提前 4h 预约） |
| `query-promotions` | 团餐 | 返回当前门店团餐满减/满折规则原始数据 | `storeCode`, `beCode`, `beType=6` | `promotionId` / `discount` / `startDiscountPoint` / `gmServiceCode`（构成「3 服务 × 4 门槛」的 12 条规则矩阵） |
| `query-meals` | 团餐 | 餐品列表与价格 | `storeCode`, `beCode`, `beType=6` | 餐品 `productCode`、原价、折扣类型 |
| `calculate-price` | 通用 | 计算含优惠价格（权威金额来源） | `items`, `gmServiceCode`, `beType=6` | `productPrice`、配送/打包费、`enjoyed`（已享优惠）、`enjoyable`（可享优惠，含 `balance` 凑单差额） |
| `now-time-info` | 通用 | 获取服务器当前时间 | 无 | 毫秒戳 / 格式化时间 / 时区（凡涉日期的优惠有效期判断均实时调用） |

> 说明：`calculate-price` 的折扣由服务端按 `gmServiceCode` 自动匹配，**不接受 `promotionId` 参数**——因此优化策略是「枚举助餐服务等级 × 商品组合，多次算价取最小」，而非指定某条规则试算。

## 3. 调用流程（团餐凑单求解链路）

```
delivery-query-addresses            → addressId
  → delivery-query-stores(beType=6) → storeCode + beCode
  → query-meal-assistance           → 可选 gmServiceCode（GMS001 默认可用）
  → query-promotions                → 12 条满减/满折规则原始数据
  → query-meals                     → 餐品编码与价格
  → calculate-price(items, gmServiceCode)
        → 含优惠实付 + enjoyed/enjoyable（含 balance 凑单差额）
```

业务价值落地：

1. **规则解析层** —— 把 `query-promotions` 返回的满减/满折阶梯解析为可比较的「门槛 → 实际折扣」表。
2. **组合搜索层** —— 枚举助餐服务等级（GMS001/002/003）× 商品组合，反复调用 `calculate-price` 取餐品折后金额最小者。
3. **差额提示层** —— 直接读取 `calculate-price` 返回的 `enjoyable.balance`（再买多少金额可解锁下一档折扣），输出「再买 ¥X 餐品，折扣从 N 折降到 M 折」。

其中 `enjoyable.balance` 是整条链路的算法基石：服务端直接吐出「凑单到下一档所需差额」，项目无需反推门槛即可给出可执行的凑单建议。

## 4. 与官方文档的差异（实测勘误）

官方 `mcd-mcp-server` README 存在偏差，本项目以实测名为准：

- 官方 README 列 33 个 Tool，**实测 `tools/list` 返回 35 个**；
- 官方**完全遗漏** `query-promotions`（门店促销规则，含 `promotionId`）与 `query-survey-coupon`（问卷券）——二者真实存在且本项目核心依赖前者；
- 官方将 `query-party-store-date` / `query-party-store-session` 误写作 `query-partystore-*`，**实测真实名带 `store`**。

## 5. 代码中的集成入口

- `scripts/mcp_client.py` —— 麦当劳 MCP Streamable HTTP 客户端（含 `429` 退避、SSE 文本解析），封装上述 Tool 调用。
- `scripts/demo.py --live` —— 走真实 MCP 端到端演示（需环境变量 `MCD_MCP_TOKEN`）。
- `scripts/promotion_ladder.py` —— 纯算法层（标准库、零网络 IO），对 `query-promotions` / `calculate-price` 的返回做规则解析与凑单推演。
- `references/MCP_TOOLS.md` —— 全部 35 个 Tool 的实测参考（含分组能力地图）。

## 6. 合规与隐私

- 配置文件仅使用 `${MCD_MCP_TOKEN}` 占位符，仓库内不含任何真实 Token、密钥或个人配送地址 / 门店编码。
- 所有金额、规则、库存状态以 `calculate-price` 及官方实时返回为准，项目输出仅供参考。
