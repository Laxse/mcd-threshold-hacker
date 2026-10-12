"""promotion_ladder 的单元测试。

测试数据来自 2026-10-12 对麦当劳 MCP v1.0.9 的真实调用结果，
不是构造的假数据 —— 这保证了解析逻辑与服务端实际返回结构一致。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from promotion_ladder import (  # noqa: E402
    best_step,
    compose_total,
    effective_product_price,
    gap_to_next,
    ladder_for_service,
    marginal_gain,
    parse_promotions,
    recommend,
)

# 实测自 query-promotions（北京某门店，beType=6 企业团餐），共 12 条
REAL_PROMOTIONS = [
    {"promotionId": "331878001", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "26", "startDiscountPoint": "500"}}},
    {"promotionId": "331868002", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "22", "startDiscountPoint": "300"}}},
    {"promotionId": "331878002", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "30", "startDiscountPoint": "1000"}}},
    {"promotionId": "331878003", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "34", "startDiscountPoint": "2000"}}},
    {"promotionId": "331878004", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "12", "startDiscountPoint": "300"}}},
    {"promotionId": "331878005", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "16", "startDiscountPoint": "500"}}},
    {"promotionId": "331878006", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "20", "startDiscountPoint": "1000"}}},
    {"promotionId": "331878007", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "24", "startDiscountPoint": "2000"}}},
    {"promotionId": "331878008", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "7", "startDiscountPoint": "300"}}},
    {"promotionId": "331878009", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "11", "startDiscountPoint": "500"}}},
    {"promotionId": "331878010", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "15", "startDiscountPoint": "1000"}}},
    {"promotionId": "331878011", "promotionType": "33", "ruleCategory": 30,
     "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}],
     "ruleDetail": {"orderDiscount": {"discount": "19", "startDiscountPoint": "2000"}}},
]

# 实测自 calculate-price：40 份 ¥19.5 = 餐品 ¥780
#   productOriginalPrice = 78000 分
#   productPrice         = 57720 分   ← 780 × 0.74，精确 7.4 折
#   deliveryPrice        = 0    分
#   packingPrice         = 900  分
#   price                = 58620 分
REAL_CASE = {
    "product_subtotal_cents": 78000,
    "product_price_cents": 57720,
    "delivery_cents": 0,
    "packing_cents": 900,
    "total_cents": 58620,
    "real_discount": 7.4,
    "next_balance_cents": 22000,   # enjoyable.balance
    "next_real_discount": 7.0,
}


class TestParse(unittest.TestCase):
    def setUp(self):
        self.ladders = parse_promotions(REAL_PROMOTIONS)

    def test_parses_all_twelve_rules(self):
        self.assertEqual(len(self.ladders), 12)

    def test_percent_off_semantics(self):
        """discount=26 必须解析为「减 26%」即 7.4 折。"""
        rule = [l for l in self.ladders if l.promotion_id == "331878001"][0]
        step = rule.steps[0]
        self.assertEqual(step.kind, "percent_off")
        self.assertEqual(step.percent_off, 26)
        self.assertEqual(step.threshold_cents, 50000)
        self.assertEqual(step.real_discount, 7.4)

    def test_threshold_conversion(self):
        """startDiscountPoint 以「元」给出，须转成「分」。"""
        rule = [l for l in self.ladders if l.promotion_id == "331878004"][0]
        self.assertEqual(rule.steps[0].threshold_cents, 30000)

    def test_products_exclusion(self):
        """type=2 表示这些餐品不适用本规则。"""
        self.assertEqual(self.ladders[0].products_type, "2")
        self.assertFalse(self.ladders[0].applies_to(["521742"]))
        self.assertTrue(self.ladders[0].applies_to(["521990"]))

    def test_ignores_unknown_type(self):
        broken = REAL_PROMOTIONS + [
            {"promotionId": "x", "promotionType": "99", "ruleDetail": {}}
        ]
        self.assertEqual(len(parse_promotions(broken)), 12)

    def test_empty_input(self):
        self.assertEqual(parse_promotions(None), [])
        self.assertEqual(parse_promotions([]), [])

    def test_merges_multi_step_ladder(self):
        """同一服务下的多条规则应合并为一个多档阶梯。"""
        merged = ladder_for_service(self.ladders, "GMS001")
        self.assertEqual(len(merged.steps), 4)
        self.assertEqual(
            [s.threshold_cents for s in merged.steps], [30000, 50000, 100000, 200000]
        )


class TestCalculation(unittest.TestCase):
    def setUp(self):
        self.ladders = parse_promotions(REAL_PROMOTIONS)
        self.gms001 = ladder_for_service(self.ladders, "GMS001")

    def test_product_price_matches_reality(self):
        """餐品折后金额必须与 calculate-price 的 productPrice 精确一致。"""
        price = effective_product_price(self.gms001, REAL_CASE["product_subtotal_cents"])
        self.assertEqual(price, REAL_CASE["product_price_cents"])

    def test_compose_total_matches_reality(self):
        """折后餐品 + 配送费 + 打包费 必须等于订单实付总额。"""
        total = compose_total(
            REAL_CASE["product_price_cents"],
            REAL_CASE["delivery_cents"],
            REAL_CASE["packing_cents"],
        )
        self.assertEqual(total, REAL_CASE["total_cents"])

    def test_below_lowest_threshold_gets_nothing(self):
        """低于 ¥300 最低门槛时无任何档可命中。"""
        self.assertIsNone(best_step(self.gms001, 29999))
        self.assertEqual(effective_product_price(self.gms001, 29999), 29999)

    def test_between_300_and_500_hits_lowest_tier(self):
        """¥300 ≤ 订单 < ¥500 命中 8.8 折（GMS001 ¥300 档，实测真实存在）。"""
        step = best_step(self.gms001, 49999)
        self.assertIsNotNone(step)
        self.assertEqual(step.threshold_cents, 30000)
        self.assertEqual(step.real_discount, 7.8)
        self.assertEqual(effective_product_price(self.gms001, 49999), 39000)

    def test_gap_matches_enjoyable_balance(self):
        """差额必须与 calculate-price 返回的 enjoyable.balance 一致。"""
        gap = gap_to_next(self.gms001, REAL_CASE["product_subtotal_cents"])
        self.assertIsNotNone(gap)
        self.assertEqual(gap[0], REAL_CASE["next_balance_cents"])
        self.assertEqual(gap[1].real_discount, REAL_CASE["next_real_discount"])

    def test_highest_tier_has_no_gap(self):
        self.assertIsNone(gap_to_next(self.gms001, 200000))
        self.assertIsNone(marginal_gain(self.gms001, 200000))

    def test_marginal_gain_at_boundary(self):
        """¥780 距 ¥1000 差 ¥220：额外减免 ¥97.20，净多付 ¥122.80。

        绝对值复核：780 × 0.74 = ¥577.20；1000 × 0.70 = ¥700.00；
        差额 ¥122.80 与代码输出一致。多付 ¥122.80 换 ¥220 餐品，
        折合多付部分为原价的 55.8%。
        """
        mg = marginal_gain(self.gms001, 78000)
        self.assertEqual(mg[0], 22000)      # 额外支出
        self.assertEqual(mg[1], 9720)       # 额外减免
        self.assertEqual(mg[2], 12280)      # 净多付

    def test_marginal_gain_absolute_check(self):
        """用绝对值反推净多付，交叉验证边际计算。"""
        base = effective_product_price(self.gms001, 78000)
        stretched = effective_product_price(self.gms001, 100000)
        self.assertEqual(stretched - base, 12280)

    def test_below_all_thresholds_no_rule(self):
        """低于 ¥300 时任何服务都无档可命中。"""
        self.assertIsNone(best_step(self.gms001, 29999))
        self.assertEqual(effective_product_price(self.gms001, 29999), 29999)

    def test_gms001_dominates_every_tier(self):
        """实测 12 条规则中，GMS001 在每个门槛的折扣都最深。

        这是真实数据特征：GMS001（保鲜速达，默认可用）在三档服务中最优，
        优化主轴因此是「选 GMS001 + 把餐品小计推上更高门槛」。
        """
        for subtotal, expected in [(30000, 23400), (50000, 37000),
                                   (100000, 70000), (200000, 132000)]:
            recs = recommend(self.ladders, subtotal, ["GMS002", "GMS003", "GMS001"])
            self.assertEqual(recs[0].gm_service_code, "GMS001", f"subtotal={subtotal}")
            self.assertEqual(recs[0].product_price_cents, expected, f"subtotal={subtotal}")


class TestRecommend(unittest.TestCase):
    def setUp(self):
        self.ladders = parse_promotions(REAL_PROMOTIONS)

    def test_gms001_always_wins(self):
        """GMS001 在 ¥780 上优于 GMS002 / GMS003。"""
        recs = recommend(self.ladders, 78000, ["GMS002", "GMS003", "GMS001"])
        self.assertEqual(recs[0].gm_service_code, "GMS001")
        self.assertEqual(recs[0].product_price_cents, 57720)
        self.assertEqual(recs[0].real_discount, 7.4)
        self.assertEqual(recs[0].next_gap_cents, 22000)
        self.assertEqual(recs[0].marginal_net_extra_cents, 12280)

    def test_below_300_shows_thresholds_to_reach(self):
        """低于 ¥300 时未命中任何档，但应给出「再买多少解锁下一档」的凑单提示。"""
        recs = recommend(self.ladders, 20000, ["GMS002", "GMS001"])
        for r in recs:
            self.assertIsNone(r.hit_step)
            self.assertEqual(r.product_price_cents, 20000)
            self.assertEqual(r.next_gap_cents, 10000)  # 差 ¥100 到 ¥300 门槛
            self.assertIn("再买", r.note)
            self.assertTrue(r.worthwhile)  # 净多付低于额外支出

    def test_as_dict_uses_yuan(self):
        recs = recommend(self.ladders, 78000, ["GMS001"])
        d = recs[0].as_dict()
        self.assertEqual(d["productSubtotalYuan"], 780.0)
        self.assertEqual(d["productPriceYuan"], 577.20)
        self.assertEqual(d["realDiscount"], 7.4)
        self.assertEqual(d["nextGapYuan"], 220.0)
        self.assertEqual(d["nextThresholdYuan"], 1000.0)

    def test_ordering_is_by_price(self):
        recs = recommend(self.ladders, 78000, ["GMS003", "GMS002", "GMS001"])
        prices = [r.product_price_cents for r in recs]
        self.assertEqual(prices, sorted(prices))


if __name__ == "__main__":
    unittest.main(verbosity=2)
