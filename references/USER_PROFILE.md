# 用户偏好持久化（本项目的差异化核心）

## 为什么需要它

麦当劳 MCP **服务端无状态**：它不保存用户的口味、预算、忌口、团餐人数、常点门店。
每次 `tools/call` 都是独立请求。这意味着——

> **「用户偏好」是 Skill 侧必须自己维护的资产，正是普通「调 API」项目做不到、而我们能做到的差异点。**

官方 README 把 MCP 当「数据源」用；本 Skill 把它当「计算引擎」，
而把「记忆」留在 Skill 这边：记住某团队每月团餐 80 人、人均预算 ¥35、忌香菜、
上次点的组合、偏好的助餐服务等级。下次一来直接给方案，不用从零问。

## 数据结构（Skill 本地维护，不入库）

```json
{
  "version": 1,
  "updatedAt": "2026-10-12T10:30:00+08:00",
  "team": {
    "defaultHeadcount": 80,
    "perCapitaBudgetYuan": 35,
    "preferredService": "GMS001",
    "advanceBookingHours": 0
  },
  "preferences": {
    "avoidItems": ["521742"],
    "favoriteCategories": ["汉堡", "小食"],
    "spiceLevel": "normal"
  },
  "history": [
    {
      "date": "2026-09-15",
      "headcount": 80,
      "subtotalYuan": 2860,
      "hitService": "GMS001",
      "realDiscount": 7.0,
      "items": [{"productCode": "521990", "quantity": 140}]
    }
  ]
}
```

## 使用约定

1. 该文件**默认不写入仓库**（`user_profile.json` 已在 `.gitignore`），避免泄露他人信息。
2. 首次使用时由 Skill 引导用户填写少量必填项（人数、预算、忌口），其余可后续补全。
3. 每次成功下单/凑单后，把本次结果追加进 `history`，用于「复购推荐」与「趋势分析」。
4. 读取偏好后再调用 MCP：例如 `advanceBookingHours >= 4` 时主动建议选 GMS002/GMS003 解锁更深折扣。

## 与算法的衔接

`promotion_ladder.recommend()` 是纯函数（输入规则 + 餐品小计 → 输出各服务最优解）。
用户偏好在它**之前**决定「推多少餐品、选哪档服务试探、是否允许预约」，
在它**之后**决定「推荐结果里挑哪个、是否提示复购」。
偏好层与算法层解耦，便于单测与替换。
