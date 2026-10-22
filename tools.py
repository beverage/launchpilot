"""
Outils métier de LaunchPilot : ce que les agents ont le droit d'appeler.
Tous les calculs sont déterministes (projection.py) ; les agents décident quoi calculer et expliquent.
"""
from datetime import date, timedelta
from projection import load, project, supplier_memory, _d, monday
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


def all_events():
    return DB["events"]


def comp_label(cid):
    return COMP[cid]["name"]


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
                    "real_mean_days": m["real_mean"], "std_days": m["std"], "prudent_days": m["prudent"],
                    "deliveries": m["n"], "late_deliveries": len(m["late_po_ids"]),
                    "evidence": f"supplier_reliability:{sid}"})
    return out


def get_open_pos(component_id):
    return [{k: p[k] for k in ["po_id", "supplier_id", "qty", "order_date", "promised_date"]}
            for p in DB["purchase_orders"] if p["status"] == "open" and p["component_id"] == component_id]


def run_projection(events_seen, component_ids=None):
    learned = project(DB, events_seen, "learned")
    naive = project(DB, events_seen, "naive")
    ids = component_ids or list(learned)
    out = []
    for cid in ids:
        if cid not in learned:
            continue
        l, n = learned[cid], naive[cid]
        wk = l["stockout_week"]
        sev = None
        if wk:
            sev = "high" if _d(wk) <= LAUNCH_WEEK + timedelta(weeks=1) else "medium"
        out.append({"component_id": cid, "name": comp_label(cid), "supplier_id": supplier_of(cid),
                    "stockout_week_launchpilot": wk, "stockout_week_naive_excel": n["stockout_week"],
                    "min_projected_stock": l["min_stock"], "suggested_severity": sev,
                    "evidence": [e for e in l["evidence"] if not e.startswith("events:sellout_spike PRD-SER") or cid in ("CMP-POM-01", "CMP-FLA-30", "CMP-ETU-01")][:12]})
    return out


def _consumers(cid):
    return [pid for pid, b in BOM.items() if cid in b]


def _window_demand(pid, scale=1.0):
    return sum(int(r["qty"]) * scale for r in DB["forecasts"]
               if r["product_id"] == pid and _d(r["week"]) <= WINDOW_END)


def _avg_price(pids):
    w = {p: max(_window_demand(p), 1) for p in pids}
    return sum(float(PROD[p]["price_eur"]) * w[p] for p in pids) / sum(w.values())


def unserved_units(component_id, series):
    """Ventes perdues (pas de report) : le stock ne descend jamais sous 0, la demande non servie est perdue."""
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
    cost_eur = surcoût vs la situation normale ; stock_value_eur = achat immobilisé ; lost_revenue_eur = CA perdu."""
    base = project(DB, events_seen, "learned")[component_id]
    shortage = unserved_units(component_id, base["series"])
    cons = _consumers(component_id)
    avg_price = _avg_price(cons)
    ev = ["inventory:" + component_id] + [e for e in base["evidence"] if e.startswith(("purchase_orders", "supplier_reliability", "events:EV"))][:6]
    res = {"component_id": component_id, "kind": kind, "shortage_units_before": shortage,
           "cost_eur": 0.0, "lost_revenue_eur": 0.0, "stock_value_eur": 0.0, "evidence_rows": ev}

    if kind == "do_nothing":
        res.update(label="Ne rien faire", lost_revenue_eur=round(shortage * avg_price),
                   detail=f"{shortage} unités non servies valorisées au prix moyen {avg_price:.0f} €")
    elif kind in ("order_main_supplier", "order_alt_supplier"):
        sid = COMP[component_id]["main_supplier_id"] if kind == "order_main_supplier" else COMP[component_id]["alt_supplier_id"]
        if not sid:
            return {"error": "pas de fournisseur alternatif pour ce composant"}
        s, m = SUP[sid], MEM[sid]
        q = int(qty or max(shortage, int(s["moq"])))
        q = max(q, int(s["moq"]))
        arrival = now + timedelta(days=m["prudent"])
        sim = project(DB, events_seen, "learned", extra_pos=[{"component_id": component_id, "qty": q, "arrival": arrival,
                                                             "supplier_id": sid, "label": f"commande urgente {s['name']}"}])[component_id]
        left = unserved_units(component_id, sim["series"])
        purchase = q * float(s["unit_cost_eur"])
        main_cost = float(SUP[COMP[component_id]["main_supplier_id"]]["unit_cost_eur"])
        cost = q * max(0.0, float(s["unit_cost_eur"]) - main_cost)   # surcoût vs fournisseur habituel
        nxt_neg = next((w for w, b in base["series"] if b < 0 and _d(w) >= monday(arrival)), None)
        margin = (_d(nxt_neg) - arrival).days if nxt_neg else None
        res.update(label=f"Commande urgente chez {s['name']}", supplier_id=sid, qty=q, safety_margin_days=margin,
                   arrival_realistic=arrival.isoformat(), announced_arrival=(now + timedelta(days=m["announced"])).isoformat(),
                   cost_eur=round(cost), stock_value_eur=round(purchase), lost_revenue_eur=round(left * avg_price),
                   shortage_units_after=left, new_stockout_week=sim["stockout_week"],
                   detail=f"{q} u. × {float(s['unit_cost_eur']):.2f} € (MOQ {s['moq']}), arrivée réaliste {arrival} (délai prudent {m['prudent']} j, annoncé {m['announced']} j)"
                          + (f", marge avant la rupture suivante : {margin} j" if margin is not None else "")
                          + f". Ne couvre pas le trou de {left} unités avant l'arrivée." * (left > 0))
        res["evidence_rows"].append(f"supplier_reliability:{sid}")
    elif kind == "prioritize_launch":
        others = [p for p in cons if p != LAUNCH_PRODUCT]
        if LAUNCH_PRODUCT not in cons or not others:
            return {"error": "le composant n'est pas partagé avec le produit lancé"}
        p_other = _avg_price(others)
        cap = sum(_window_demand(p) for p in others)
        lost_units = min(shortage, cap)
        res.update(label="Allouer en priorité au coffret de lancement", lost_revenue_eur=round(lost_units * p_other),
                   detail=f"Les {shortage} unités manquantes sont prises sur {', '.join(PROD[p]['name'] for p in others)} "
                          f"(prix moyen {p_other:.0f} €) au lieu du coffret (89 €). Le lancement est protégé.")
    elif kind == "order_alt_and_prioritize":
        o = cost_scenario(events_seen, now, component_id, "order_alt_supplier", qty)
        if "error" in o:
            return o
        others = [p for p in cons if p != LAUNCH_PRODUCT]
        p_other = _avg_price(others) if others else avg_price
        left = o["shortage_units_after"]
        res.update(label=f"Commande urgente {SUP[o['supplier_id']]['name']} + coffret prioritaire en attendant",
                   supplier_id=o["supplier_id"], qty=o["qty"], cost_eur=o["cost_eur"], stock_value_eur=o["stock_value_eur"],
                   lost_revenue_eur=round(left * p_other), shortage_units_after=left, safety_margin_days=o.get("safety_margin_days"),
                   detail=f"La commande (arrivée réaliste {o['arrival_realistic']}) sécurise décembre. Le trou de {left} unités "
                          f"avant son arrivée est pris sur les sérums ({p_other:.0f} €) : le coffret sort à l'heure.")
        res["evidence_rows"] = o["evidence_rows"]
    elif kind == "reduce_launch":
        pct = float(reduction_pct or 20) / 100
        sim = project(DB, events_seen, "learned", demand_scale={LAUNCH_PRODUCT: 1 - pct})[component_id]
        left = unserved_units(component_id, sim["series"])
        launch_units = _window_demand(LAUNCH_PRODUCT) * pct
        price_launch = float(PROD[LAUNCH_PRODUCT]["price_eur"])
        res.update(label=f"Réduire le lancement de {int(pct*100)} %",
                   lost_revenue_eur=round(launch_units * price_launch + left * avg_price),
                   shortage_units_after=left, new_stockout_week=sim["stockout_week"],
                   detail=f"{int(launch_units)} coffrets en moins ({price_launch:.0f} €), reste {left} unités manquantes")
    else:
        return {"error": f"type de scénario inconnu : {kind}"}
    res["total_impact_eur"] = round(res["cost_eur"] + res["lost_revenue_eur"])
    return res
