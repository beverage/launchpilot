#!/usr/bin/env python3
"""Material balance of LaunchPilot's synthetic data, per component.

  received   units on delivered purchase orders
  consumed   units the sales history needs through the bill of materials
  stock      the inventory snapshot on the demo's "today"
  opening    stock - received + consumed: the stock the world must have started with

In a coherent world the opening stock is positive and a few months of use at most. A
negative opening stock means the history received more than it used and the surplus vanished.
Components with deliveries but no stock row (past seasons' gift boxes) are listed too, so a gap
that the snapshot does not cover stays visible.

Usage:  python3 docs/evaluation/balance.py --data data
Standard library only.
"""
import argparse, csv, os
from collections import Counter, defaultdict

p = argparse.ArgumentParser()
p.add_argument("--data", default="data")
args = p.parse_args()
rd = lambda n: list(csv.DictReader(open(os.path.join(args.data, n), encoding="utf-8")))

bom = defaultdict(dict)
for r in rd("bom.csv"):
    bom[r["product_id"]][r["component_id"]] = float(r["qty_per_unit"])
sales = rd("sales_history.csv")
weeks = sorted({r["week"] for r in sales})
consumed = Counter()
for r in sales:
    for cid, k in bom[r["product_id"]].items():
        consumed[cid] += int(r["qty"]) * k
received = Counter()
for r in rd("purchase_orders.csv"):
    if r["status"] == "delivered":
        received[r["component_id"]] += int(r["qty"])
inv = {r["item_id"]: (r["snapshot_date"], int(r["qty"])) for r in rd("inventory.csv") if r["item_type"] == "component"}

print(f"Sales history {weeks[0]} to {weeks[-1]} ({len(weeks)} weeks); stock snapshot {next(iter(inv.values()))[0]}")
print(f"{'component':15} {'received':>9} {'consumed':>9} {'stock':>7} {'opening':>9}  weeks of use at opening")
ids = [r["component_id"] for r in rd("components.csv")]
for cid in ids + sorted((set(inv) | set(received) | set(consumed)) - set(ids)):
    per_week = consumed[cid] / len(weeks)
    if cid not in inv:
        note = "no stock row" + ("; no sales in the history (past season, not modelled)" if not consumed[cid] else "")
        print(f"{cid:15} {received[cid]:9d} {int(consumed[cid]):9d} {'-':>7} {'-':>9}  {note}")
        continue
    stock = inv[cid][1]
    opening = stock - received[cid] + int(consumed[cid])
    if opening < 0:
        cover = "impossible: negative"
    else:
        cover = f"{opening / per_week:.0f}" if per_week else "no use"
    print(f"{cid:15} {received[cid]:9d} {int(consumed[cid]):9d} {stock:7d} {opening:9d}  {cover}")
