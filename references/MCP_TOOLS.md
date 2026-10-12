# 麦当劳 MCP 工具参考（实测 35 个 · 2026-10-12）

> 来源：`tools/list` 实测返回（北京某门店，Bearer Token 鉴权）。
> 官方 README 仅列 33 个，**遗漏了 `query-promotions` 与 `query-survey-coupon` 两个真实存在的工具**；
> 且将 `query-party-store-date` / `query-party-store-session` 误写作 `query-partystore-*`（实测真实名**带 store**）。
> 本文件以实测名为准。

## 接入方式

- 协议：**Streamable HTTP**（POST JSON-RPC 到 `https://mcp.mcd.cn`）
- 认证：`Authorization: Bearer <token>`（token 在 `https://open.mcd.cn/mcp` 手机号登录后申请）
- 限流：600 次/分钟，超了返回 `429`
- 状态：**服务端无状态**，不返回 `Mcp-Session-Id`，单次 `tools/call` 可直接调用，无需先 `initialize` 握手（握手也成功，但非必需）
- 返回结构：`tools/call` 的文本 content 内通常形如 `## Original Response\n{...json...}`；`tools/list` 则直接返回 `{result:{tools:[...]}}`

## 能力地图（35 个，按业务域分组）

### 时间与环境
| 工具 | 说明 |
|---|---|
| `now-time-info` | 获取服务器当前时间（毫秒戳/格式化/时区）。**凡涉及日期的活动、券有效期都必须实时调它**，模型靠训练数据猜日期会翻车。 |
| `campaign-calendar` | 当月营销活动日历，含进行中/往期/未来，及用户订阅状态。 |

### 门店与地址（外送 / 团餐前置）
| 工具 | 说明 |
|---|---|
| `delivery-query-addresses` | 查询用户配送地址列表，返回 `addressId`。团餐链路第一步。 |
| `delivery-query-stores` | 按 `addressId` 查可配送门店；`beType=2` 麦乐送、`beType=6` 团餐。返回 `storeCode` + `beCode`。 |
| `delivery-create-address` | 创建配送地址（需城市/联系人/手机号等真实信息）。 |
| `query-nearby-stores` | 到店场景查门店：`beType=1` 自提（无 beCode）、`beType=5` 得来速（有 beCode）。 |
| `query-store-coupons` | 指定门店+订单类型下**可用**的优惠券（已校验下单规则）。 |

### 菜单与餐品
| 工具 | 说明 |
|---|---|
| `query-meals` | 餐品列表，到店/外送；团餐场景附搭配建议（按预算档位）。 |
| `query-meal-detail` | 单品详情，含套餐组成、特制/换品（`1.0.5` 新增能力，榜单几乎无人系统利用）。 |
| `list-nutrition-foods` | 营养成分（热量/蛋白/脂肪/钠等），用于热量套餐搭配。 |

### 团餐专属（本项目核心场景）
| 工具 | 说明 |
|---|---|
| `query-meal-assistance` | **仅 beType=6**。calculate-price 前获取门店可用助餐服务（GMS001/002/003）。GMS002/003 需提前 4h 预约（`enable=false`）。 |
| `query-promotions` | ⚠️ **官方 README 未收录的隐藏工具**。仅 beType=6 场景下，返回当前门店团餐满减/满折规则原始数据（`promotionId`/`discount`/`startDiscountPoint`/`gmServiceCode`）。本项目差异化抓手。 |

### 价格与下单
| 工具 | 说明 |
|---|---|
| `calculate-price` | 计算含优惠价格，**支持到店/外送/团餐**。关键：折扣由服务端按 `gmServiceCode` 自动匹配，**不接受 promotionId 参数**（不能指定某条规则试算）。返回 `productPrice`、配送/打包费、`enjoyed`/`enjoyable`（含 `balance` 凑单差额）。 |
| `create-order` | 创建订单（到店/外送）。 |
| `cancel-order` | 取消非商城订单（需取消原因 code）。 |
| `query-order` | 订单详情/配送进度。 |
| `order-list` | 历史订单（非商城）。 |

### 优惠券
| 工具 | 说明 |
|---|---|
| `available-coupons` | 用户**可领取**的麦麦省券列表。 |
| `query-my-coupons` | 卡包已有券（不做下单规则校验，不保证当前可用）。 |
| `auto-bind-coupons` | 一键领取当前所有可领券。 |

### 账户与积分
| 工具 | 说明 |
|---|---|
| `query-my-account` | 积分账户详情（余额/过期积分）。 |
| `query-my-prizes` | 积分抽奖获得的奖品列表（可用/已用/过期）。 |
| `query-survey-coupon` | ⚠️ 官方 README 未收录。按订单号查本人 CSAT 答卷及关联奖券核销状态。 |

### 抽奖
| 工具 | 说明 |
|---|---|
| `query-lottery-info` | 积分抽奖活动信息（不执行抽奖）。必须先展示其 `nextConsumption` 并获确认才能调 `draw-lottery`。 |
| `draw-lottery` | 参加一次抽奖。受 `drawDecision.resourceEligible` 约束。 |

### 派对 / 主题活动
| 工具 | 说明 |
|---|---|
| `query-party-city` | 派对商品可预约城市列表（需先确定 spuId）。 |
| `query-party-store` | 指定城市下支持派对的门店。 |
| `query-party-store-date` | 指定门店可预约日期（**实测名带 store**，非 `query-partystore-date`）。 |
| `query-party-store-session` | 指定门店+日期的场次列表（**实测名带 store**）。 |
| `party-order-create` | 创建派对订单（shopId=5，包场/拼团）。 |

### 麦麦商城（积分兑换）
| 工具 | 说明 |
|---|---|
| `mall-points-products` | 可兑换商品券/实物/周边/派对活动列表。 |
| `mall-product-detail` | 商品 SKU 详情（需选 SKU 后下单）。 |
| `mall-order-list` | 商城订单列表。 |
| `mall-order-detail` | 商城订单详情。 |
| `mall-create-order` | 创建积分兑换订单（shopId=2，**必须单商品逐单下单**）。 |

## 本项目用到的关键链路

```
delivery-query-addresses (addressId)
   → delivery-query-stores (addressId, beType=6) → storeCode + beCode
   → query-meal-assistance (storeCode, beCode, beType=6) → 可选 gmServiceCode
   → query-promotions (storeCode, beCode, beType=6) → 12 条规则原始数据
   → query-meals (storeCode, beCode, beType=6) → 餐品编码与价格
   → calculate-price (items, gmServiceCode) → 含优惠实付 + enjoyed/enjoyable
```

`calculate-price` 是价格唯一权威来源；本项目的 `promotion_ladder.py` 只做「规则解析 + 凑单推演」，
最终金额必须仍以 `calculate-price` 返回为准（折扣基准是餐品小计，配送/打包费另有独立规则）。
