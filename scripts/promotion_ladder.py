"""
麦当劳团餐促销阶梯解析与凑单最优解计算。

本模块是 mcd-threshold-hacker 的算法核心，职责单一：
把麦当劳 MCP `query-promotions` 返回的原始规则 JSON 解析为可比较、可搜索的
阶梯结构，并在此基础上给出「实付最低方案」与「凑单差额提示」。

设计约束
--------
1. 纯标准库实现，零第三方依赖，Python >= 3.9。
2. 不做任何网络 IO —— 输入均为 MCP 工具的原始返回（dict），便于单测。
3. 金额一律使用「分」为单位的整数，避免浮点误差。
4. 不包含任何真实 Token、地址、门店编码等个人信息。

实测依据（2026-10-12，麦当劳 MCP v1.0.9）
------------------------------------------

【1】query-promotions 返回 12 条规则，构成「3 个助餐服务 × 4 档门槛」矩阵
    （2026-10-12 实测，某北京门店，beType=6 企业团餐）：

    门槛        GMS001 保鲜速达   GMS002 专人分餐   GMS003 专人摆台
    ¥300        7.8 折(减22%)     8.8 折(减12%)    9.3 折(减7%)
    ¥500        7.4 折(减26%)     8.4 折(减16%)    8.9 折(减11%)
    ¥1000       7.0 折(减30%)     8.0 折(减20%)    8.5 折(减15%)
    ¥2000       6.6 折(减34%)     7.6 折(减24%)    8.1 折(减19%)

    GMS001 在每一档都最优（折扣最深），且默认可用（无需预约）；
    GMS002 / GMS003 需提前 4 小时预约（query-meal-assistance 返回 enable=false）。
    因此优化主轴是「选 GMS001 + 把餐品小计推上更高门槛」。

    字段语义：
      promotionType : "31" = 满额减（固定减免），"33" = 订单折扣（百分比减免）
      ruleCategory  : 30 = 满折/折扣，40 = 满减
      discount      : 百分比数值，"26" 表示减 26%，即 7.4 折
      startDiscountPoint : 触发门槛，单位「元」
      gmServiceCode : 规则绑定的助餐服务编码
      products[].type : 1 包含适用 / 2 不包含 / 3 全部

【2】折扣基准是「餐品小计」，不是订单总额。

    实测 ¥780 餐品 + ¥6 配送费 + ¥32 打包费 = ¥818 的订单：
      productOriginalPrice = 78000 分
      productPrice         = 57720 分   ← 780 × 0.74，精确命中 7.4 折
      deliveryPrice        = 0    分   ← 配送费全免
      packingPrice         = 900  分   ← 打包费独立减免
      price                = 58620 分

    因此 effective_price() 只对餐品小计生效；配送费与打包费另有规则，
    必须由 calculate-price 的返回值给出，本模块不做臆测。

【3】enjoyable.balance 的准确语义。

    实测返回 {"realDiscount": 7.0, "balance": 22000}：
      balance = 下一档门槛 − 当前餐品小计 = ¥1000 − ¥780 = ¥220
    即「再买 ¥220 餐品，折扣从 7.4 折降到 7.0 折」。
    这是服务端直接给出的凑单差额，无需自行反推门槛 —— 凑单提示的数据来源。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "DiscountStep",
    "DiscountLadder",
    "PromotionRuleError",
    "parse_promotions",
    "ladder_for_service",
    "best_step",
    "effective_product_price",
    "gap_to_next",
    "marginal_gain",
    "compose_total",
    "recommend",
    "Recommendation",
]

_CENTS_PER_YUAN = 100


class PromotionRuleError(ValueError):
    """促销规则结构无法解析时抛出。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscountStep:
    """阶梯中的一档。

    threshold_cents : 触发门槛（分），以「餐品小计」为比较基准
    kind            : "percent_off" 按餐品小计百分比减免 / "fixed_reduce" 固定金额减免
    percent_off     : kind == "percent_off" 时的减免百分比，26 表示减 26%
    reduce_cents    : kind == "fixed_reduce" 时的固定减免金额（分）
    """

    threshold_cents: int
    kind: str
    percent_off: Optional[int] = None
    reduce_cents: Optional[int] = None

    def discount_amount(self, product_subtotal_cents: int) -> int:
        """给定餐品小计，返回本档对餐品的减免金额（分）。"""
        if self.kind == "percent_off":
            if self.percent_off is None:
                raise PromotionRuleError("percent_off 档缺少 percent_off")
            return product_subtotal_cents * self.percent_off // 100
        if self.reduce_cents is None:
            raise PromotionRuleError("fixed_reduce 档缺少 reduce_cents")
        return self.reduce_cents

    @property
    def real_discount(self) -> Optional[float]:
        """折后系数，7.4 表示 7.4 折。仅 percent_off 档有意义。"""
        if self.kind != "percent_off" or self.percent_off is None:
            return None
        return round(10 - self.percent_off / 10, 2)


@dataclass
class DiscountLadder:
    """一条促销规则对应的阶梯（可能含多个档位）。"""

    promotion_id: str
    gm_service_code: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    products_type: str = "3"
    product_codes: Tuple[str, ...] = ()
    steps: List[DiscountStep] = field(default_factory=list)

    def sort_steps(self) -> None:
        self.steps.sort(key=lambda s: s.threshold_cents)

    def applies_to(self, product_codes: Sequence[str]) -> bool:
        """判断给定餐品编码集合是否落入本规则适用范围。

        product_codes 为空表示「尚未选定餐品」，此时不做排除判断，视为适用 ——
        否则在凑单推演阶段（还没有购物车）会漏掉所有带 products 排除项的规则。
        """
        if self.products_type == "3" or not self.product_codes:
            return True
        if not product_codes:
            return True
        code_set = set(product_codes)
        if self.products_type == "1":
            return bool(code_set & set(self.product_codes))
        # type == "2" 表示这些餐品「不适用」；全部餐品都被排除时才不适用
        return not code_set.issubset(set(self.product_codes))


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def _to_cents(value) -> int:
    """把「元」字符串/数字转成「分」整数。"""
    if value is None:
        raise PromotionRuleError("金额字段缺失")
    if isinstance(value, int):
        return value * _CENTS_PER_YUAN
    text = str(value).strip()
    if not text:
        raise PromotionRuleError("金额字段为空")
    if re.fullmatch(r"-?\d+", text):
        return int(text) * _CENTS_PER_YUAN
    match = re.fullmatch(r"(-?\d+)\.(\d{1,2})", text)
    if match:
        yuan, frac = match.groups()
        return int(yuan) * _CENTS_PER_YUAN + int(frac.ljust(2, "0"))
    raise PromotionRuleError(f"无法解析金额: {value!r}")


def _parse_products(products) -> Tuple[str, Tuple[str, ...]]:
    if not products:
        return "3", ()
    types = {str(p.get("type", "3")) for p in products if isinstance(p, dict)}
    codes = tuple(
        str(p.get("productCode"))
        for p in products
        if isinstance(p, dict) and p.get("productCode") is not None
    )
    ptype = types.pop() if len(types) == 1 else "3"
    return ptype, codes


def _parse_one(raw: dict) -> DiscountLadder:
    if not isinstance(raw, dict):
        raise PromotionRuleError(f"规则不是对象: {raw!r}")

    promotion_id = str(raw.get("promotionId") or "")
    if not promotion_id:
        raise PromotionRuleError("规则缺少 promotionId")

    gm_service = raw.get("gmServiceCode")
    gm_service = str(gm_service) if gm_service not in (None, "") else None

    ptype, codes = _parse_products(raw.get("products"))
    ladder = DiscountLadder(
        promotion_id=promotion_id,
        gm_service_code=gm_service,
        start_time=raw.get("startTime"),
        end_time=raw.get("endTime"),
        products_type=ptype,
        product_codes=codes,
    )

    rule_detail = raw.get("ruleDetail") or {}
    promotion_type = str(raw.get("promotionType") or "")

    if promotion_type == "33":
        order_discount = rule_detail.get("orderDiscount") or {}
        if not order_discount:
            raise PromotionRuleError(f"promotionType=33 缺少 ruleDetail.orderDiscount: {promotion_id}")
        percent = order_discount.get("discount")
        if percent is None:
            raise PromotionRuleError(f"orderDiscount 缺少 discount: {promotion_id}")
        ladder.steps.append(
            DiscountStep(
                threshold_cents=_to_cents(order_discount.get("startDiscountPoint", 0)),
                kind="percent_off",
                percent_off=int(str(percent).strip()),
            )
        )
    elif promotion_type == "31":
        order_reduce = rule_detail.get("orderReduce") or {}
        reduce_info = order_reduce.get("reduceInfo") or []
        if not reduce_info:
            raise PromotionRuleError(f"promotionType=31 缺少 reduceInfo: {promotion_id}")
        for item in reduce_info:
            if not isinstance(item, dict):
                continue
            ladder.steps.append(
                DiscountStep(
                    threshold_cents=_to_cents(item.get("startDiscountPoint", 0)),
                    kind="fixed_reduce",
                    reduce_cents=_to_cents(item.get("reduceAmount", 0)),
                )
            )
    else:
        raise PromotionRuleError(f"未支持的 promotionType={promotion_type}: {promotion_id}")

    ladder.sort_steps()
    return ladder


def parse_promotions(raw_rules) -> List[DiscountLadder]:
    """把 query-promotions 的 data 数组解析为阶梯列表，跳过无法解析的规则。"""
    if raw_rules is None:
        return []
    if isinstance(raw_rules, dict):
        raw_rules = raw_rules.get("data") or []
    ladders: List[DiscountLadder] = []
    for raw in raw_rules:
        try:
            ladders.append(_parse_one(raw))
        except PromotionRuleError:
            continue
    return ladders


def ladder_for_service(
    ladders: Sequence[DiscountLadder],
    gm_service_code: Optional[str],
    product_codes: Sequence[str] = (),
) -> Optional[DiscountLadder]:
    """给定助餐服务与餐品编码，返回该服务下最优的一条规则。

    同一服务下可能有多档规则（如 GMS001 有 ¥500/¥1000/¥2000 三条），
    这里合并为一条多档阶梯，档位由 best_step 按餐品小计动态选取。
    """
    matched = [
        l
        for l in ladders
        if l.gm_service_code == gm_service_code and l.applies_to(product_codes)
    ]
    if not matched:
        return None
    merged = DiscountLadder(
        promotion_id="|".join(l.promotion_id for l in matched),
        gm_service_code=gm_service_code,
        start_time=None,
        end_time=None,
        products_type=matched[0].products_type,
        product_codes=matched[0].product_codes,
        steps=[s for l in matched for s in l.steps],
    )
    merged.sort_steps()
    return merged


# ---------------------------------------------------------------------------
# 计算
# ---------------------------------------------------------------------------


def best_step(
    ladder: Optional[DiscountLadder], product_subtotal_cents: int
) -> Optional[DiscountStep]:
    """返回餐品小计命中的最高档位；未达门槛返回 None。"""
    if not ladder:
        return None
    hit = None
    for step in ladder.steps:
        if product_subtotal_cents >= step.threshold_cents:
            if hit is None or step.threshold_cents > hit.threshold_cents:
                hit = step
    return hit


def effective_product_price(
    ladder: Optional[DiscountLadder], product_subtotal_cents: int
) -> int:
    """估算「餐品折后金额」（分）。

    不含配送费与打包费 —— 这两项另有规则，必须取 calculate-price 的返回值。
    无命中规则时等于餐品小计原价。
    """
    step = best_step(ladder, product_subtotal_cents)
    if step is None:
        return product_subtotal_cents
    return max(0, product_subtotal_cents - step.discount_amount(product_subtotal_cents))


def gap_to_next(
    ladder: Optional[DiscountLadder], product_subtotal_cents: int
) -> Optional[Tuple[int, DiscountStep]]:
    """返回（距离下一档还差多少分, 下一档）。已在最高档返回 None。"""
    if not ladder:
        return None
    upcoming = [s for s in ladder.steps if s.threshold_cents > product_subtotal_cents]
    if not upcoming:
        return None
    nxt = min(upcoming, key=lambda s: s.threshold_cents)
    return nxt.threshold_cents - product_subtotal_cents, nxt


def marginal_gain(
    ladder: Optional[DiscountLadder], product_subtotal_cents: int
) -> Optional[Tuple[int, int, int]]:
    """凑单到下一档的边际收益。

    返回 (额外支出分, 额外减免分, 净多付分)。

    「净多付」是关键：为拿到更深的折扣而多买的餐品，实际只多花了这么多钱。
    实测 ¥780 餐品距 ¥1000 差 ¥220：
      额外支出 = ¥220（多买的餐品原价）
      额外减免 = ¥202.80（折扣从 7.4 折加深到 7.0 折）
      净多付   = ¥17.20
    即：多拿 ¥220 的餐品，只多付 ¥17.20 —— 对「本来就要多吃」的用户是明显划算，
    对「吃不完」的用户则不建议。worthwhile 只回答「是否产生了净节省」，
    是否真的要多买，必须由用户按食量决定，Skill 不得替用户决定。
    """
    if not ladder:
        return None
    gap = gap_to_next(ladder, product_subtotal_cents)
    if gap is None:
        return None
    extra_spend, nxt = gap
    current = best_step(ladder, product_subtotal_cents)
    target = product_subtotal_cents + extra_spend
    current_discount = current.discount_amount(product_subtotal_cents) if current else 0
    next_discount = nxt.discount_amount(target)
    extra_saving = next_discount - current_discount
    return extra_spend, extra_saving, max(0, extra_spend - extra_saving)


def compose_total(
    product_price_cents: int,
    delivery_price_cents: int = 0,
    packing_price_cents: int = 0,
) -> int:
    """把折后餐品金额与配送费、打包费合成订单实付总额（分）。"""
    return product_price_cents + delivery_price_cents + packing_price_cents


# ---------------------------------------------------------------------------
# 推荐
# ---------------------------------------------------------------------------


@dataclass
class Recommendation:
    """一次凑单优化的结论。"""

    gm_service_code: Optional[str]
    promotion_ids: Optional[str]
    product_subtotal_cents: int
    product_price_cents: int
    product_discount_cents: int
    real_discount: Optional[float]
    hit_step: Optional[DiscountStep]
    next_gap_cents: Optional[int]
    next_step: Optional[DiscountStep]
    marginal_extra_spend_cents: Optional[int]
    marginal_extra_saving_cents: Optional[int]
    marginal_net_extra_cents: Optional[int]
    worthwhile: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "gmServiceCode": self.gm_service_code,
            "promotionIds": self.promotion_ids,
            "productSubtotalYuan": round(self.product_subtotal_cents / 100, 2),
            "productPriceYuan": round(self.product_price_cents / 100, 2),
            "productDiscountYuan": round(self.product_discount_cents / 100, 2),
            "realDiscount": self.real_discount,
            "hitThresholdYuan": (
                round(self.hit_step.threshold_cents / 100, 2) if self.hit_step else None
            ),
            "nextGapYuan": (
                round(self.next_gap_cents / 100, 2) if self.next_gap_cents is not None else None
            ),
            "nextThresholdYuan": (
                round(self.next_step.threshold_cents / 100, 2) if self.next_step else None
            ),
            "marginalExtraSpendYuan": (
                round(self.marginal_extra_spend_cents / 100, 2)
                if self.marginal_extra_spend_cents is not None
                else None
            ),
            "marginalExtraSavingYuan": (
                round(self.marginal_extra_saving_cents / 100, 2)
                if self.marginal_extra_saving_cents is not None
                else None
            ),
            "marginalNetExtraYuan": (
                round(self.marginal_net_extra_cents / 100, 2)
                if self.marginal_net_extra_cents is not None
                else None
            ),
            "worthwhile": self.worthwhile,
            "note": self.note,
        }


def recommend(
    ladders: Sequence[DiscountLadder],
    product_subtotal_cents: int,
    gm_service_codes: Sequence[Optional[str]],
    product_codes: Sequence[str] = (),
) -> List[Recommendation]:
    """对每个候选助餐服务给出优化结论，按餐品折后金额升序返回。"""
    results: List[Recommendation] = []
    for service in gm_service_codes:
        ladder = ladder_for_service(ladders, service, product_codes)
        step = best_step(ladder, product_subtotal_cents)
        product_price = effective_product_price(ladder, product_subtotal_cents)
        gap = gap_to_next(ladder, product_subtotal_cents)
        mg = marginal_gain(ladder, product_subtotal_cents)

        worthwhile = False
        note = ""
        if mg is not None:
            extra_spend, extra_saving, net_extra = mg
            # worthwhile 只表示「净多付低于额外支出」，即多买的餐品享受到了折扣加深。
            # 是否真要多买，必须由用户按实际食量决定，Skill 不得替用户决定。
            worthwhile = net_extra < extra_spend
            if extra_saving >= extra_spend:
                # 凑单的小额支出被折扣减免反超：多买反而净省（等于白加餐）
                note = (
                    f"再买 ¥{extra_spend / 100:.2f} 餐品即可多省 ¥{extra_saving / 100:.2f}，"
                    f"净省 ¥{(extra_saving - extra_spend) / 100:.2f}（等于白加餐）"
                )
            else:
                ratio = net_extra / extra_spend * 100
                note = (
                    f"再买 ¥{extra_spend / 100:.2f} 餐品可多省 ¥{extra_saving / 100:.2f}，"
                    f"净多付 ¥{net_extra / 100:.2f}，折合多付部分仅 {ratio:.1f}% 原价"
                )
                if worthwhile:
                    note += "（吃得多才划算；吃不完则不建议）"
        elif step is None and ladder is not None:
            note = "未达该服务的最低门槛"
        elif ladder is None:
            note = "该助餐服务下无可用促销规则"

        results.append(
            Recommendation(
                gm_service_code=service,
                promotion_ids=ladder.promotion_id if ladder else None,
                product_subtotal_cents=product_subtotal_cents,
                product_price_cents=product_price,
                product_discount_cents=max(0, product_subtotal_cents - product_price),
                real_discount=step.real_discount if step else None,
                hit_step=step,
                next_gap_cents=gap[0] if gap else None,
                next_step=gap[1] if gap else None,
                marginal_extra_spend_cents=mg[0] if mg else None,
                marginal_extra_saving_cents=mg[1] if mg else None,
                marginal_net_extra_cents=mg[2] if mg else None,
                worthwhile=worthwhile,
                note=note,
            )
        )
    results.sort(key=lambda r: (r.product_price_cents, -(r.next_gap_cents or 0)))
    return results
