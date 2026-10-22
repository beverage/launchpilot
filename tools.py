"""
Outils métier de LaunchPilot : ce que les agents ont le droit d'appeler.
Tous les calculs sont déterministes (projection.py) ; les agents décident quoi calculer et expliquent.
"""
from datetime import date, timedelta
from projection import load, project, project_prob, supplier_memory, _d, monday, working_day, set_holidays
import capacity as CAP
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB = load(DATA)
MEM = supplier_memory(DB)
SUP = {s["supplier_id"]: s for s in DB["suppliers"]}
COMP = {c["component_id"]: c for c in DB["components"]}
PROD = {p["product_id"]: p for p in DB["products"]}
BOM = {}
for r in DB["bom"]:
    BOM.setdefault(r["product_id"], {})[r["component_id"]] = float(r["qty_per_unit"])
LAUNCH_WEEK = _d(DB["gt"]["launch_week"])
WINDOW_END = _d(DB["gt"]["window_end"])
SIM_TODAY = _d(DB["gt"]["sim_today"])
LAUNCH_PRODUCT = next(p["product_id"] for p in DB["products"] if p["is_launch"] == "True")
PLANTS = CAP.load_plants(DATA)


def all_events():
    return DB["events"]


def comp_label(cid):
    """A component's name; a capacity alert is about a product, so fall back to product names."""
    return COMP[cid]["name"] if cid in COMP else PROD[cid]["name"] if cid in PROD else cid


def supplier_of(cid):
    return COMP[cid]["main_supplier_id"]


# ---------- outils exposés aux agents ----------

def get_supplier_memory(supplier_id=None):
    ids = [supplier_id] if supplier_id else list(MEM)
    out = []
    for sid in ids:
        if sid not in MEM:
            continue
        m = MEM[sid]
        out.append({"supplier_id": sid, "name": SUP[sid]["name"], "announced_days": m["announced"],
                    "real_mean_days": m["real_mean"], "std_days": m["std"], "typical_days": m["typical"],
                    "deliveries": m["n"], "late_deliveries": len(m["late_po_ids"]),
                    "evidence": f"supplier_reliability:{sid}",
                    **({"demo_mapping": "this supplier carries a real company's SIREN for the demo; its delivery history is fictional, "
                                        "say so whenever you quote its lead times"} if SUP[sid].get("siren") else {})})
    return out


def get_open_pos(component_id):
    return [{k: p[k] for k in ["po_id", "supplier_id", "qty", "order_date", "promised_date"]}
            for p in DB["purchase_orders"] if p["status"] == "open" and p["component_id"] == component_id]


LAUNCH_PLUS_1 = (LAUNCH_WEEK + timedelta(weeks=1)).isoformat()


def run_projection(events_seen, component_ids=None):
    """Vue LaunchPilot (mémoire fournisseur, probabiliste) et vue sans mémoire : le planificateur attentif
    qui lit tous les messages mais croit les délais annoncés."""
    learned = project(DB, events_seen, "learned")
    literal = project(DB, events_seen, "literal")
    prob = project_prob(DB, events_seen)
    ids = component_ids or list(learned)
    out = []
    for cid in ids:
        if cid not in learned:
            continue
        l, b, p = learned[cid], literal[cid], prob[cid]
        p_launch = p["p_by_week"][LAUNCH_PLUS_1]
        sev = "high" if p_launch >= 0.5 else ("medium" if p["p_window"] >= 0.5 else None)
        out.append({"component_id": cid, "name": comp_label(cid), "supplier_id": supplier_of(cid),
                    "stockout_week_launchpilot": p["median_week"],
                    "p_stockout_by_launch_plus_1wk": round(p_launch, 2),
                    "p_stockout_before_end_of_year": round(p["p_window"], 2),
                    "stockout_week_without_memory": b["stockout_week"],
                    "min_projected_stock_p50": p["min_stock_p50"], "suggested_severity": sev,
                    "confidence": round(p_launch if sev == "high" else p["p_window"], 2),
                    "evidence": [e for e in l["evidence"] if not e.startswith("events:sellout_spike PRD-SER") or cid in ("CMP-POM-01", "CMP-FLA-30", "CMP-ETU-01")][:12]})
    return out


def chart_series(events_seen, component_id):
    """Pour le graphique : bande p10 / p50 / p90 de LaunchPilot et trajectoire du planificateur sans mémoire."""
    p = project_prob(DB, events_seen)[component_id]
    return {"p10": p["p10"], "p50": p["p50"], "p90": p["p90"],
            "without_memory": project(DB, events_seen, "literal")[component_id]["series"]}


def _consumers(cid):
    return [pid for pid, b in BOM.items() if cid in b]


def _window_demand(pid, scale=1.0):
    return sum(int(r["qty"]) * scale for r in DB["forecasts"]
               if r["product_id"] == pid and _d(r["week"]) <= WINDOW_END)


def _avg_price(pids):
    w = {p: max(_window_demand(p), 1) for p in pids}
    return sum(float(PROD[p]["price_eur"]) * w[p] for p in pids) / sum(w.values())


def unserved_units(component_id, series):
    """Lost sales (no backorders): stock never goes below 0, unserved demand is lost."""
    stock0 = next(int(r["qty"]) for r in DB["inventory"] if r["item_id"] == component_id)
    prev_b, level, lost = stock0, stock0, 0
    for _, b in series:
        level += b - prev_b
        prev_b = b
        if level < 0:
            lost += -level
            level = 0
    return lost


def cost_scenario(events_seen, now, component_id, kind, qty=None, reduction_pct=None):
    """kind : do_nothing | order_main_supplier | order_alt_supplier | prioritize_launch | reduce_launch | order_alt_and_prioritize
    cost_eur = surcoût vs la situation normale ; stock_value_eur = achat immobilisé ; lost_revenue_eur = CA perdu.
    For a product (a capacity alert), kind is do_nothing or move_filling."""
    if component_id in PROD:
        return capacity_scenario(events_seen, component_id, kind)
    base = project(DB, events_seen, "learned")[component_id]
    shortage = unserved_units(component_id, base["series"])
    cons = _consumers(component_id)
    avg_price = _avg_price(cons)
    ev = ["inventory:" + component_id] + [e for e in base["evidence"] if e.startswith(("purchase_orders", "supplier_reliability", "events:EV"))][:6]
    res = {"component_id": component_id, "kind": kind, "shortage_units_before": shortage,
           "cost_eur": 0.0, "lost_revenue_eur": 0.0, "stock_value_eur": 0.0, "evidence_rows": ev}

    if kind == "do_nothing":
        res.update(label="Do nothing", lost_revenue_eur=round(shortage * avg_price),
                   detail=f"{shortage} units not served, valued at the average price of {avg_price:.0f} €")
    elif kind in ("order_main_supplier", "order_alt_supplier"):
        sid = COMP[component_id]["main_supplier_id"] if kind == "order_main_supplier" else COMP[component_id]["alt_supplier_id"]
        if not sid:
            return {"error": "no alternative supplier for this component"}
        s, m = SUP[sid], MEM[sid]
        q = int(qty or max(shortage, int(s["moq"])))
        q = max(q, int(s["moq"]))
        arrival = working_day(now + timedelta(days=m["typical"]))
        sim = project(DB, events_seen, "learned", extra_pos=[{"component_id": component_id, "qty": q, "arrival": arrival,
                                                             "supplier_id": sid, "label": f"rush order from {s['name']}"}])[component_id]
        left = unserved_units(component_id, sim["series"])
        purchase = q * float(s["unit_cost_eur"])
        main_cost = float(SUP[COMP[component_id]["main_supplier_id"]]["unit_cost_eur"])
        cost = q * max(0.0, float(s["unit_cost_eur"]) - main_cost)   # surcoût vs fournisseur habituel
        nxt_neg = next((w for w, b in base["series"] if b < 0 and _d(w) >= monday(arrival)), None)
        margin = max(0, (_d(nxt_neg) - arrival).days) if nxt_neg else None   # 0 = la commande arrive la semaine même où le stock casse
        res.update(label=f"Rush order from {s['name']}", supplier_id=sid, qty=q, safety_margin_days=margin,
                   arrival_realistic=arrival.isoformat(), announced_arrival=working_day(now + timedelta(days=m["announced"])).isoformat(),
                   cost_eur=round(cost), stock_value_eur=round(purchase), lost_revenue_eur=round(left * avg_price),
                   shortage_units_after=left, new_stockout_week=sim["stockout_week"],
                   detail=f"{q} units × {float(s['unit_cost_eur']):.2f} € (MOQ {s['moq']}), realistic arrival {arrival} (lead time used {m['typical']} d = median actual, announced {m['announced']} d)"
                          + (f", safety margin before the next stockout: {margin} d" if margin is not None else "")
                          + f". Does not cover the gap of {left} units before it arrives." * (left > 0))
        res["evidence_rows"].append(f"supplier_reliability:{sid}")
    elif kind == "prioritize_launch":
        others = [p for p in cons if p != LAUNCH_PRODUCT]
        if LAUNCH_PRODUCT not in cons or not others:
            return {"error": "the component is not shared with the launch product"}
        p_other = _avg_price(others)
        cap = sum(_window_demand(p) for p in others)
        lost_units = min(shortage, cap)
        res.update(label="Prioritise the launch gift set", lost_revenue_eur=round(lost_units * p_other),
                   detail=f"The {shortage} missing units are taken from {', '.join(PROD[p]['name'] for p in others)} "
                          f"(average price {p_other:.0f} €) instead of the gift set ({float(PROD[LAUNCH_PRODUCT]['price_eur']):.0f} €). The launch is protected.")
    elif kind == "order_alt_and_prioritize":
        o = cost_scenario(events_seen, now, component_id, "order_alt_supplier", qty)
        if "error" in o:
            return o
        others = [p for p in cons if p != LAUNCH_PRODUCT]
        p_other = _avg_price(others) if others else avg_price
        left = o["shortage_units_after"]
        res.update(label=f"Rush order from {SUP[o['supplier_id']]['name']} + gift set first meanwhile",
                   supplier_id=o["supplier_id"], qty=o["qty"], cost_eur=o["cost_eur"], stock_value_eur=o["stock_value_eur"],
                   lost_revenue_eur=round(left * p_other), shortage_units_after=left, safety_margin_days=o.get("safety_margin_days"),
                   detail=f"The order (realistic arrival {o['arrival_realistic']}) secures December. The gap of {left} units "
                          f"before it arrives is taken from the serums ({p_other:.0f} €): the gift set ships on time.")
        res["evidence_rows"] = o["evidence_rows"]
    elif kind == "reduce_launch":
        pct = float(reduction_pct or 20) / 100
        sim = project(DB, events_seen, "learned", demand_scale={LAUNCH_PRODUCT: 1 - pct})[component_id]
        left = unserved_units(component_id, sim["series"])
        launch_units = _window_demand(LAUNCH_PRODUCT) * pct
        price_launch = float(PROD[LAUNCH_PRODUCT]["price_eur"])
        res.update(label=f"Scale the launch down by {int(pct*100)}%",
                   lost_revenue_eur=round(launch_units * price_launch + left * avg_price),
                   shortage_units_after=left, new_stockout_week=sim["stockout_week"],
                   detail=f"{int(launch_units)} fewer gift sets ({price_launch:.0f} €), {left} units still missing")
    else:
        return {"error": f"unknown scenario kind: {kind}"}
    res["total_impact_eur"] = round(res["cost_eur"] + res["lost_revenue_eur"])
    return res


# ---------- live events: deliveries, derived events, the merged view the engine reads ----------

ENGINE_TYPES = {"supplier_delay", "sellout_spike", "capacity_drop", "po_confirmed", "noise"}
OPEN_IDS = [p["po_id"] for p in DB["purchase_orders"] if p["status"] == "open"]   # as shipped in data/


def refresh_memory():
    MEM.clear()
    MEM.update(supplier_memory(DB))


def apply_delivery(po_id, delivered_at, quantity_delivered):
    """Marks an order delivered in the in-memory data (status, actual date, delivered quantity) and refreshes the
    supplier memory. Returns the supplier's memory before and after, so the agent and the UI can show the learning."""
    p = next((x for x in DB["purchase_orders"] if x["po_id"] == po_id), None)
    if not p:
        return {"error": f"unknown purchase order {po_id}"}
    sid = p["supplier_id"]
    before = dict(MEM[sid])
    p["status"], p["actual_date"], p["delivered_qty"] = "delivered", delivered_at, int(quantity_delivered)
    refresh_memory()
    after = MEM[sid]
    return {"po_id": po_id, "supplier_id": sid, "supplier": SUP[sid]["name"],
            "lead_time_days": (_d(delivered_at) - _d(p["order_date"])).days, "announced_days": after["announced"],
            "typical_before": before["typical"], "typical_after": after["typical"], "deliveries_now": after["n"],
            "partial": int(quantity_delivered) < int(p["qty"]),
            "evidence": [f"purchase_orders:{po_id}", f"supplier_reliability:{sid}"]}


def reset_deliveries():
    """Back to the shipped data: orders that were open in data/ are open again."""
    for p in DB["purchase_orders"]:
        if p["po_id"] in OPEN_IDS:
            p["status"], p["actual_date"] = "open", ""
            p.pop("delivered_qty", None)
    refresh_memory()


def sync_deliveries(store):
    """At start-up: re-apply the deliveries recorded in the database (another process may have applied them)."""
    reset_deliveries()
    for u in store.delivered_updates():
        apply_delivery(u["po_id"], u["actual_date"], u["delivered_qty"])


def events_seen(store):
    """What the projection engine should know: processed structured events, recorded or derived from supplier emails,
    in time order, minus rows superseded by a derived twin."""
    rows = [e for e in store.list_events()
            if e["processed"] and e["event_type"] in ENGINE_TYPES and not e["payload"].get("superseded")]
    return sorted(({"event_id": e["event_id"], "ts": e["ts"], "event_type": e["event_type"], "payload": e["payload"]} for e in rows),
                  key=lambda e: (e["ts"], e["event_id"]))


def get_supplier_master():
    """Our suppliers, for exposure checks against public notices."""
    return [{"supplier_id": s["supplier_id"], "name": s["name"], "category": s["category"],
             "activity_code": s.get("activity_code") or None, "siren": s.get("siren") or None,
             **({"demo_mapping": "this fictional supplier carries a real company's SIREN for the demo; an alert on a matching notice must "
                                 "start with 'Demo mapping:' and say the notice is real, the supplier and its delivery history fictional, "
                                 "and that nothing is implied about the real company's lead times"} if s.get("siren") else {})}
            for s in DB["suppliers"]]


def siren_pretty(siren):
    return f"{siren[:3]} {siren[3:6]} {siren[6:]}" if siren and len(siren) == 9 else (siren or "")


def demo_mappings():
    """Fictional suppliers mapped to a real SIREN for the demo (see the decision log)."""
    return [{"supplier_id": s["supplier_id"], "name": s["name"], "siren": s["siren"]} for s in DB["suppliers"] if s.get("siren")]


def components_of(supplier_id):
    """A supplier's components that matter today: with stock on hand or an open order (past-season boxes are excluded)."""
    active = {r["item_id"] for r in DB["inventory"]} | {p["po_id"] and p["component_id"] for p in DB["purchase_orders"] if p["status"] == "open"}
    return [c["component_id"] for c in DB["components"]
            if supplier_id in (c["main_supplier_id"], c["alt_supplier_id"]) and c["component_id"] in active]


# Anthropic list prices, USD per million tokens (input, output), as published on 6 October 2026. An estimate only:
# the gateway's spend log is the authoritative figure when the app runs through it.
PRICE_PER_MTOK = {"claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00), "claude-haiku-5-5": (0.10, 0.50),
                  "claude-fable-5-1": (10.00, 50.00)}


def cost_usd(tokens_in, tokens_out, model):
    """Estimated cost of a run at list price, or None when the model's price is unknown."""
    price = PRICE_PER_MTOK.get(model)
    if not price:
        return None
    return (tokens_in or 0) / 1e6 * price[0] + (tokens_out or 0) / 1e6 * price[1]


def supplier_exposure(events_seen, supplier_id):
    """What-if for a public notice on a supplier: its open orders never arrive (delivered ones stay, they are in stock).
    Per component: stockout week as is and if the orders never arrive, extra units short, lost revenue at shelf price."""
    open_pos = [p for p in DB["purchase_orders"] if p["status"] == "open" and p["supplier_id"] == supplier_id]
    out = []
    for cid in components_of(supplier_id):
        pos_c = [p for p in open_pos if p["component_id"] == cid]
        if not pos_c:
            continue
        base = project(DB, events_seen, "learned")[cid]
        without = project(DB, events_seen, "learned", exclude_pos=[p["po_id"] for p in pos_c])[cid]
        extra = unserved_units(cid, without["series"]) - unserved_units(cid, base["series"])
        price = _avg_price(_consumers(cid))
        received = sum(int(p.get("delivered_qty") or p["qty"]) for p in DB["purchase_orders"]
                       if p["component_id"] == cid and p["status"] == "delivered" and p.get("actual_date") and _d(p["actual_date"]) >= SIM_TODAY)
        wk = without["stockout_week"]
        out.append({"component_id": cid, "name": comp_label(cid), "supplier": SUP[supplier_id]["name"],
                    "open_orders": [{"po_id": p["po_id"], "qty": int(p["qty"]), "promised_date": p["promised_date"]} for p in pos_c],
                    "open_qty": sum(int(p["qty"]) for p in pos_c), "received_since_snapshot_qty": received,
                    "stockout_week_as_is": base["stockout_week"], "stockout_week_if_orders_never_arrive": wk,
                    "extra_units_short": extra, "lost_revenue_eur_if_missing": round(extra * price),
                    "second_source": SUP[COMP[cid]["alt_supplier_id"]]["name"] if COMP[cid]["alt_supplier_id"] else None,
                    "severity_if_missing": "high" if wk and _d(wk) <= LAUNCH_WEEK + timedelta(weeks=1) else ("medium" if wk else None),
                    "evidence": [f"inventory:{cid}"] + [f"purchase_orders:{p['po_id']}" for p in pos_c]})
    return out


def sync_holidays(store):
    """Public holidays from live HOL- rows (holiday_closure, kind public_holiday) extend the built-in French calendar."""
    dates = set()
    for e in store.list_events():
        if e["event_type"] == "holiday_closure" and e["payload"].get("kind", "public_holiday") == "public_holiday":
            start, end = e["payload"].get("start_date") or e["payload"].get("date"), e["payload"].get("end_date") or e["payload"].get("date")
            if start:
                d, last = _d(start), _d(end or start)
                while d <= last:
                    dates.add(d); d += timedelta(days=1)
    set_holidays(dates)
    return len(dates)


# ---------- contract-manufacturer capacity (capacity.py) ----------

CAPACITY_HIGH_UNITS = 1000   # a capacity shortfall is high when at least this many units go unfilled by launch + 1 week


def capacity_check(events_seen):
    """Can the contract manufacturers fill what the forecast asks for, given the capacity drops and sell-out spikes known
    so far? Per product that goes short: its plant, the first week its finished stock cannot cover demand, units and
    revenue lost at shelf price (the launch gift set is filled first), and the what-if of filling the overflow at
    another plant's spare capacity. Assumes the components are there; the component projection answers that."""
    base, _ = CAP.simulate(DB, PLANTS, events_seen, LAUNCH_PRODUCT, WINDOW_END)
    moved, _ = CAP.simulate(DB, PLANTS, events_seen, LAUNCH_PRODUCT, WINDOW_END, overflow=True)
    out = []
    for pid, r in base.items():
        if not r["units_unserved"]:
            continue
        wk, m = r["first_unserved_week"], moved[pid]
        high = r["units_unserved"] >= CAPACITY_HIGH_UNITS and _d(wk) <= LAUNCH_WEEK + timedelta(weeks=1)
        out.append({"product_id": pid, "name": PROD[pid]["name"], "plant": r["plant"], "plant_name": PLANTS[r["plant"]]["name"],
                    "capacity_per_week": PLANTS[r["plant"]]["capacity"], "first_unserved_week": wk,
                    "units_unserved": r["units_unserved"], "lost_revenue_eur": r["lost_revenue_eur"],
                    "overflow_plants": [PLANTS[f]["name"] for f in PLANTS if f != r["plant"]],
                    "units_unserved_if_moved": m["units_unserved"], "lost_revenue_eur_if_moved": m["lost_revenue_eur"],
                    "suggested_severity": "high" if high else "medium",
                    "confidence": 1.0, "confidence_note": "deterministic: the known capacity drops against the forecast",
                    "evidence": [f"subcontractors:{r['plant']}", f"inventory:{pid}"] + [f"events:{e}" for e in r["drop_events"]]})
    return out


def capacity_scenario(events_seen, product_id, kind):
    """Costed options for a capacity alert, in the same shape as cost_scenario. Transfer costs are not modelled."""
    c = next((x for x in capacity_check(events_seen) if x["product_id"] == product_id), None)
    if not c:
        return {"error": f"no capacity shortfall for {product_id}"}
    res = {"component_id": product_id, "kind": kind, "cost_eur": 0.0, "stock_value_eur": 0.0,
           "shortage_units_before": c["units_unserved"], "evidence_rows": c["evidence"]}
    if kind == "do_nothing":
        res.update(label="Do nothing", lost_revenue_eur=c["lost_revenue_eur"], shortage_units_after=c["units_unserved"],
                   detail=f"{c['units_unserved']} units of {c['name']} cannot be filled at {c['plant_name']} from the week of "
                          f"{c['first_unserved_week']} (the gift set is filled first), at {float(PROD[product_id]['price_eur']):.0f} € each")
    elif kind == "move_filling":
        after = c["units_unserved_if_moved"]
        res.update(label=f"Fill the overflow at {', '.join(c['overflow_plants'])}", lost_revenue_eur=c["lost_revenue_eur_if_moved"],
                   shortage_units_after=after,
                   detail=f"Spare capacity at {', '.join(c['overflow_plants'])} fills {c['units_unserved'] - after} of the "
                          f"{c['units_unserved']} units in the short weeks; {after} still short. Transfer costs are not modelled.")
    else:
        return {"error": "a capacity alert takes kind do_nothing or move_filling"}
    res["total_impact_eur"] = round(res["cost_eur"] + res["lost_revenue_eur"])
    return res
