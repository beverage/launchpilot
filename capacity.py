"""
Contract-manufacturer capacity: can the plants fill what the forecast asks for?

Each product is filled by one contract manufacturer (products.filled_by). A plant's weekly output is its capacity cut by
the capacity drops known so far; finished-goods stock buffers a short week and is rebuilt to its starting level when
there is room. Within a plant the launch gift set is filled first, then the other products pro rata to what they need.
Demand is the forecast times the sell-out spikes known so far, as in the component projection. This is a separate lens
from the component projection: it assumes the components are there and asks whether the filling lines keep up.
Deterministic, standard library only.
"""
import csv, os
from datetime import date


def _d(s):
    return date.fromisoformat(s) if s else None


def load_plants(data_dir):
    with open(os.path.join(data_dir, "subcontractors.csv"), encoding="utf-8") as f:
        return {r["subcontractor_id"]: {"name": r["name"], "capacity": int(r["weekly_capacity_units"])} for r in csv.DictReader(f)}


def _known(events_seen):
    """Demand multipliers and capacity drops read from the events seen so far, with the event ids that carry them."""
    mult, drops = {}, {}
    for e in events_seen:
        t, pl = e["event_type"], e["payload"]
        if t == "sellout_spike":
            for w in pl["weeks_affected"]:
                k = (pl["product_id"], _d(w))
                mult[k] = mult.get(k, 1.0) * pl["observed_vs_forecast"]
        elif t == "capacity_drop":
            for w in pl["weeks_affected"]:
                drops.setdefault((pl["subcontractor_id"], _d(w)), []).append((float(pl["capacity_drop_rate"]), e["event_id"]))
    return mult, drops


def simulate(db, plants, events_seen, launch_product, window_end, overflow=False):
    """Weekly fill per plant and finished-goods stock per product.
    overflow=True lets a short plant's non-launch products be filled with another plant's spare capacity (the what-if).
    Returns {product_id: {...}} and the weekly plant log."""
    filled_by = {p["product_id"]: p.get("filled_by") or "" for p in db["products"]}
    price = {p["product_id"]: float(p["price_eur"]) for p in db["products"]}
    stock0 = {r["item_id"]: int(r["qty"]) for r in db["inventory"] if r["item_type"] == "product"}
    fc = {(_d(r["week"]), r["product_id"]): int(r["qty"]) for r in db["forecasts"]}
    weeks = sorted({w for w, _ in fc if w <= window_end})
    mult, drops = _known(events_seen)
    stock = dict(stock0)
    res = {pid: {"first_unserved_week": None, "units_unserved": 0, "plant": filled_by[pid], "drop_events": set()} for pid in filled_by}
    log = []
    for w in weeks:
        cap, drop_ev = {}, {}
        for fid, pl in plants.items():
            c = float(pl["capacity"])
            for rate, eid in drops.get((fid, w), []):
                c *= 1 - rate
                drop_ev.setdefault(fid, []).append(eid)
            cap[fid] = int(c)
        demand = {pid: int(fc.get((w, pid), 0) * mult.get((pid, w), 1.0)) for pid in filled_by}
        need = {pid: max(0, demand[pid] + stock0.get(pid, 0) - stock.get(pid, 0)) for pid in filled_by}   # serve the week, rebuild stock
        made = {pid: 0 for pid in filled_by}
        left = {}
        for fid in plants:
            mine = [p for p in filled_by if filled_by[p] == fid]
            c = cap[fid]
            for pid in sorted(mine, key=lambda p: p != launch_product):              # the launch product first
                if pid == launch_product:
                    made[pid] = min(c, need[pid]); c -= made[pid]
            rest = [p for p in mine if p != launch_product]
            tot = sum(need[p] for p in rest)
            for pid in rest:
                made[pid] = min(need[pid], int(c * need[pid] / tot)) if tot else 0
            left[fid] = cap[fid] - sum(made[p] for p in mine)
        if overflow:
            for fid in plants:
                for pid in [p for p in filled_by if filled_by[p] == fid and p != launch_product and made[p] < need[p]]:
                    for other in plants:
                        if other == fid or left.get(other, 0) <= 0:
                            continue
                        moved = min(need[pid] - made[pid], left[other])
                        made[pid] += moved; left[other] -= moved
        for pid in filled_by:
            s = stock.get(pid, 0) + made[pid] - demand[pid]
            if s < 0:
                r = res[pid]
                r["units_unserved"] += -s
                if r["first_unserved_week"] is None:
                    r["first_unserved_week"] = w
                s = 0
            stock[pid] = s
            if filled_by[pid] in drop_ev:
                res[pid]["drop_events"].update(drop_ev[filled_by[pid]])
        log.append({"week": w.isoformat(), "capacity": cap, "demand": demand, "made": made, "spare": left})
    for pid, r in res.items():
        r["lost_revenue_eur"] = round(r["units_unserved"] * price[pid])
        r["first_unserved_week"] = r["first_unserved_week"].isoformat() if r["first_unserved_week"] else None
        r["drop_events"] = sorted(r["drop_events"])
    return res, log
