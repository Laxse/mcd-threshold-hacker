#!/usr/bin/env python3
"""
mcd-threshold-hacker 演示脚本。

脱机模式（默认）：使用 2026-10-12 实测的真实促销规则，无需 Token 即可看到算法效果。
实时模式（--live，需设置环境变量 MCD_MCP_TOKEN）：从真实 MCP 拉取当前门店的促销规则跑一遍。

用法
----
    python demo.py                  # 用内置 ¥780 餐品小计演示
    python demo.py --subtotal 780   # 指定餐品小计（元）
    MCD_MCP_TOKEN=xxx python demo.py --live

本脚本仅依赖标准库 + 同目录的 promotion_ladder.py，无需安装任何第三方包。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from promotion_ladder import parse_promotions, recommend  # noqa: E402

# 2026-10-12 实测自 query-promotions（北京某门店 beType=6 企业团餐），共 12 条规则。
# 与 tests/test_promotion_ladder.py 中的 REAL_PROMOTIONS 同源，保证演示与单测一致。
REAL_PROMOTIONS = [
    {"promotionId": "331868002", "promotionType": "33", "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "22", "startDiscountPoint": "300"}}},
    {"promotionId": "331878001", "promotionType": "33", "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "26", "startDiscountPoint": "500"}}},
    {"promotionId": "331878002", "promotionType": "33", "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "30", "startDiscountPoint": "1000"}}},
    {"promotionId": "331878003", "promotionType": "33", "gmServiceCode": "GMS001", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "34", "startDiscountPoint": "2000"}}},
    {"promotionId": "331878004", "promotionType": "33", "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "12", "startDiscountPoint": "300"}}},
    {"promotionId": "331878005", "promotionType": "33", "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "16", "startDiscountPoint": "500"}}},
    {"promotionId": "331878006", "promotionType": "33", "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "20", "startDiscountPoint": "1000"}}},
    {"promotionId": "331878007", "promotionType": "33", "gmServiceCode": "GMS002", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "24", "startDiscountPoint": "2000"}}},
    {"promotionId": "331878008", "promotionType": "33", "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "7", "startDiscountPoint": "300"}}},
    {"promotionId": "331878009", "promotionType": "33", "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "11", "startDiscountPoint": "500"}}},
    {"promotionId": "331878010", "promotionType": "33", "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "15", "startDiscountPoint": "1000"}}},
    {"promotionId": "331878011", "promotionType": "33", "gmServiceCode": "GMS003", "products": [{"type": "2", "productCode": "521742"}], "ruleDetail": {"orderDiscount": {"discount": "19", "startDiscountPoint": "2000"}}},
]


def fmt(cents: int) -> str:
    return f"¥{cents / 100:.2f}"


def _print_report(recs, subtotal_cents: int, source: str) -> None:
    print(f"\n{'=' * 64}")
    print(f"  餐品小计 {fmt(subtotal_cents)} 的凑单最优解  [{source}]")
    print(f"{'=' * 64}")
    print(f"{'助餐服务':<11}{'命中门槛':<11}{'餐品折后':<13}{'实际折扣':<10}{'再凑单'}")
    print("-" * 64)
    for r in recs:
        hit = f"¥{r.hit_step.threshold_cents / 100:.0f}" if r.hit_step else "未达¥300"
        rd = f"{r.real_discount}折" if r.real_discount else "—"
        if r.next_gap_cents:
            gap = f"再买{fmt(r.next_gap_cents)}→{r.next_step.real_discount}折"
        else:
            gap = "已封顶"
        print(f"{r.gm_service_code or '默认':<11}{hit:<11}{fmt(r.product_price_cents):<13}{rd:<10}{gap}")
    print("-" * 64)
    best = recs[0]
    best_rd = f"{best.real_discount}折" if best.real_discount else "无折扣"
    print(f"★ 最优：{best.gm_service_code}，餐品折后 {fmt(best.product_price_cents)}（{best_rd}）")
    if best.next_gap_cents:
        if best.real_discount:
            tip = f"折扣从 {best.real_discount}折 降到 {best.next_step.real_discount}折"
        else:
            tip = f"即可解锁 {best.next_step.real_discount}折"
        print(f"  凑单提示：再买 {fmt(best.next_gap_cents)} 餐品，{tip}")
        print(f"  明细：{best.note}")


def offline(subtotal_cents: int) -> None:
    ladders = parse_promotions(REAL_PROMOTIONS)
    recs = recommend(ladders, subtotal_cents, ["GMS001", "GMS002", "GMS003"])
    _print_report(recs, subtotal_cents, "脱机·真实规则")


def _first(data: object, *keys: str):
    """从多种可能的返回结构中取出第一个列表元素。"""
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list) and v:
                return v[0]
        # 也可能 data 本身就是 {field: [...]} 或直接是列表包装
        for v in data.values():
            if isinstance(v, list) and v:
                return v[0]
    return None


def live(subtotal_cents: int) -> None:
    token = os.environ.get("MCD_MCP_TOKEN")
    if not token:
        print("[live] 未设置 MCD_MCP_TOKEN，回退到脱机演示。\n")
        return offline(subtotal_cents)
    try:
        from mcp_client import McdMcpClient  # 延迟导入，脱机演示不依赖
    except ImportError:
        print("[live] 缺少 mcp_client，回退到脱机演示。\n")
        return offline(subtotal_cents)

    client = McdMcpClient(token=token)
    addrs = client.extract_json(client.call_tool("delivery-query-addresses"))
    addr = _first(addrs, "data", "addressList", "list")
    if not addr or "addressId" not in addr:
        print("[live] 无法解析配送地址，回退脱机演示。\n")
        return offline(subtotal_cents)
    aid = addr["addressId"]

    stores = client.extract_json(client.call_tool("delivery-query-stores", {"addressId": aid, "beType": 6}))
    store = _first(stores, "data", "storeList", "list")
    sc = store.get("storeCode")
    bc = store.get("beCode")
    if not sc or not bc:
        print("[live] 无法解析团餐门店，回退脱机演示。\n")
        return offline(subtotal_cents)

    promo = client.extract_json(
        client.call_tool("query-promotions", {"storeCode": sc, "beCode": bc, "beType": 6, "orderType": 2})
    )
    ladders = parse_promotions(promo.get("data")) if isinstance(promo, dict) else parse_promotions(promo)
    recs = recommend(ladders, subtotal_cents, ["GMS001", "GMS002", "GMS003"])
    _print_report(recs, subtotal_cents, f"实时·门店{sc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="mcd-threshold-hacker 演示")
    ap.add_argument("--subtotal", type=float, default=780.0, help="餐品小计（元），默认 780")
    ap.add_argument("--live", action="store_true", help="实时从 MCP 拉取（需 MCD_MCP_TOKEN）")
    args = ap.parse_args()
    cents = int(round(args.subtotal * 100))
    if args.live:
        live(cents)
    else:
        offline(cents)


if __name__ == "__main__":
    main()
