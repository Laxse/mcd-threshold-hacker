---
name: mcd-threshold-hacker
description: 麦当劳企业团餐「凑单最优解引擎」。当用户要为企业团餐 / 多人聚餐搭配麦当劳套餐、想用最少的钱拿到最深折扣、或问「满多少减多少 / 打几折 / 再买点什么更划算」时使用。基于麦当劳 MCP 的 query-promotions + calculate-price，解析 3 个助餐服务 × 4 档门槛的满折阶梯，给出实付最低方案与精准的凑单差额提示。注意：促销规则仅企业团餐场景（beType=6）可获取；麦当劳 MCP 服务端无状态，用户口味 / 预算 / 忌口等偏好必须在 Skill 侧持久化。
---

# 麦当劳团餐凑单最优解引擎

把「麦当劳企业团餐促销规则」解析成可计算、可搜索的阶梯结构，在给定餐品小计下给出
**实付最低的助餐服务方案**，并直接告诉用户「再买多少、折扣能降几折」。

## 何时使用

- 用户说「帮我们部门订麦当劳团餐」「凑个团餐」「满多少减多少」
- 用户问「怎么点最划算」「这个金额打几折」「再点些啥能更便宜」
- 用户给出人数 + 预算，希望自动搭配出人均最低的套餐组合
- 用户问「我们上次点的那个组合再订一次」（需读取历史偏好）

## 核心能力

1. **规则解析**：把 `query-promotions` 返回的 12 条原始规则（3 服务 × 4 门槛）解析为阶梯结构。
2. **最优求解**：对 GMS001 / GMS002 / GMS003 三个助餐服务分别求「餐品折后金额」，按实付升序排序。
3. **凑单提示**：直接读 `calculate-price` 返回的 `enjoyable.balance`，输出「再买 ¥X 餐品，折扣从 a 折降到 b 折」。

## MCP 工具调用顺序（beType=6 团餐链）

```
delivery-query-addresses → delivery-query-stores(beType=6)
  → query-meal-assistance → query-promotions → query-meals
  → calculate-price(gmServiceCode)  ← 金额唯一权威来源
```

- `query-promotions`：**官方 README 未收录的隐藏工具**，仅 beType=6 返回满减/满折规则。
- `calculate-price` 的折扣由服务端按 `gmServiceCode` 自动匹配，**不接受 promotionId**，不能指定某条规则试算。
- 折扣基准是**餐品小计**，不是订单总额；配送费/打包费另有独立规则，必须以 `calculate-price` 返回为准。

## 算法三层（见 `scripts/promotion_ladder.py`）

| 层 | 职责 | 输入 | 输出 |
|---|---|---|---|
| 规则解析层 | 把满折阶梯解析为可比较门槛表 | `query-promotions` 原始 JSON | `List[DiscountLadder]` |
| 组合搜索层 | 枚举服务 × 商品组合 × 券，多次算价取最小 | 餐品小计 + 助餐服务编码 | `List[Recommendation]` |
| 差额提示层 | 读 `enjoyable.balance`，输出再凑单多少降到几折 | 当前餐品小计 + 规则 | 自然语言凑单建议 |

模块是纯函数、零网络 IO、零第三方依赖，便于单测（21 个用例全绿）。

## 关键字段语义（实测）

`calculate-price` 返回结构（节选）：

```
productOriginalPrice = 78000   # 餐品原价（分）
productPrice         = 57720   # 780 × 0.74，精确命中 7.4 折
deliveryPrice        = 0       # 配送费全免
packingPrice         = 900     # 打包费独立减免
price                = 58620   # 订单实付

enjoyed:  { realDiscount: 7.4 }                 # 已享折扣
enjoyable:{ realDiscount: 7.0, balance: 22000 } # 再买 ¥220 → 7.0 折
```

`balance = 22000` 分 = **下一档门槛 − 当前餐品小计** = ¥1000 − ¥780。
服务端直接给出凑单差额，无需反推门槛 —— 这是凑单提示的数据来源。

## 用户偏好持久化（差异化核心）

麦当劳 MCP **服务端无状态**，不保存用户偏好。Skill 侧维护 `user_profile.json`
（已在 `.gitignore`，不入库）记住：团队人数、人均预算、忌口、常点组合、偏好服务等级。
下次一来直接给方案，不用从零问。结构见 `references/USER_PROFILE.md`。

## 合规与注意

- `calculate-price` 的返回是金额唯一权威来源；本引擎只做「规则解析 + 凑单推演」，宣称省钱前必须实跑验证。
- 不得拿「券面文字」当优惠，必须 `calculate-price` 实跑。
- 时间相关字段（活动有效期、预约时效）必须实时调 `now-time-info`，不能用模型记忆。
- 不得与其他品牌做对比；`draw-lottery` 仅作能力说明，勿包装成抽奖攻略。
- 用户个人信息（地址、门店编码）绝不写入仓库。
