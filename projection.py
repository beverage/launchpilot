"""
LaunchPilot — moteur de projection déterministe (l'outil que les agents appellent).

Deux modes, mêmes données d'entrée (jamais la vérité terrain) :
  - "naive"   : croit les dates promises (y compris les nouvelles dates annoncées) et la prévision v1.
  - "learned" : utilise la mémoire fournisseur (délai prudent = moyenne réelle + 1 écart-type, appris sur l'historique livré),
                amplifie les retards annoncés des fournisseurs peu fiables,
                applique les pics de sell-out et les livraisons partielles vus dans le flux.

Usage en lib :
    from projection import load, project
    db = load("data")
    project(db, events_seen, mode="learned")  -> {component_id: {"stockout_week": ..., "min_stock": ..., "evidence": [...]}}
"""
import csv, json, os
from datetime import date, timedelta, datetime

def _d(s): return date.fromisoformat(s) if s else None
def monday(d): return d - timedelta(days=d.weekday())

def load(path="data"):
    rd = lambda n: list(csv.DictReader(open(os.path.join(path, n), encoding="utf-8")))
    db = {n[:-4]: rd(n) for n in ["suppliers.csv", "components.csv", "products.csv", "bom.csv",
                                  "forecasts.csv", "inventory.csv", "purchase_orders.csv"]}
    db["events"] = [json.loads(l) for l in open(os.path.join(path, "events.jsonl"), encoding="utf-8")]
    db["gt"] = json.load(open(os.path.join(path, "ground_truth.json"), encoding="utf-8"))
    return db

def supplier_memory(db):
    """Mémoire fournisseur = ce que la vue SQL supplier_reliability calcule."""
    mem = {}
    for s in db["suppliers"]:
        d = [(_d(p["actual_date"]) - _d(p["order_date"])).days for p in db["purchase_orders"]
             if p["supplier_id"] == s["supplier_id"] and p["status"] == "delivered"]
        ann = int(s["announced_lead_time_days"])
        real = sum(d) / len(d) if d else ann
        sd = (sum((x - real) ** 2 for x in d) / (len(d) - 1)) ** 0.5 if len(d) > 1 else 0
        late = [p["po_id"] for p in db["purchase_orders"] if p["supplier_id"] == s["supplier_id"]
                and p["status"] == "delivered" and _d(p["actual_date"]) > _d(p["promised_date"])]
        mem[s["supplier_id"]] = {"announced": ann, "real_mean": round(real, 1), "std": round(sd, 1),
                                 "prudent": round(real + sd), "n": len(d),
                                 "ratio": real / ann, "late_po_ids": late}
    return mem

def project(db, events_seen, mode="learned", window_end=None, extra_pos=None, demand_scale=None):
    """extra_pos : commandes simulées [{component_id, qty, arrival(date), label}] ;
    demand_scale : {product_id: facteur} pour simuler une réduction de lancement."""
    sim_today = _d(db["gt"]["sim_today"])
    window_end = window_end or _d(db["gt"]["window_end"])
    mem = supplier_memory(db)
    stock = {r["item_id"]: int(r["qty"]) for r in db["inventory"] if r["item_type"] == "component"}
    bom = {}
    for r in db["bom"]:
        bom.setdefault(r["product_id"], {})[r["component_id"]] = float(r["qty_per_unit"])
    fc = {(_d(r["week"]), r["product_id"]): int(r["qty"]) for r in db["forecasts"]}
    weeks = sorted({w for w, _ in fc if w <= window_end})

    # état des commandes ouvertes
    open_pos = {p["po_id"]: dict(p) for p in db["purchase_orders"] if p["status"] == "open"}
    for p in open_pos.values():
        p["arrival"] = _d(p["promised_date"])
        p["qty_eff"] = int(p["qty"])
        p["evidence"] = [f"purchase_orders:{p['po_id']}"]
        if mode == "learned":
            m = mem[p["supplier_id"]]
            p["arrival"] = _d(p["order_date"]) + timedelta(days=m["prudent"])
            p["evidence"].append(f"supplier_reliability:{p['supplier_id']} (annoncé {m['announced']} j, réel {m['real_mean']} ± {m['std']} j sur {m['n']} livraisons, délai prudent {m['prudent']} j)")
    for i, x in enumerate(extra_pos or []):
        open_pos[f"SIM-{i}"] = {"po_id": f"SIM-{i}", "component_id": x["component_id"], "qty": x["qty"],
                                "qty_eff": int(x["qty"]), "arrival": x["arrival"], "supplier_id": x.get("supplier_id", ""),
                                "evidence": [f"simulation:{x.get('label', 'commande simulée')}"]}
    demand_mult = {}
    for pid, f in (demand_scale or {}).items():
        for w in weeks:
            demand_mult[(pid, w)] = f
    for e in events_seen:
        t, pl = e["event_type"], e["payload"]
        if t == "supplier_delay" and pl["po_id"] in open_pos:
            p = open_pos[pl["po_id"]]
            if mode == "naive":
                p["arrival"] = _d(pl["new_promised_date"])
            else:
                p["arrival"] += timedelta(days=round(pl["announced_delay_days"] * mem[p["supplier_id"]]["ratio"]))
            p["evidence"].append(f"events:{e['event_id']}")
        elif t == "sellout_spike" and mode == "learned":
            for w in pl["weeks_affected"]:
                k = (pl["product_id"], _d(w))
                demand_mult[k] = demand_mult.get(k, 1.0) * pl["observed_vs_forecast"]
        elif t == "po_confirmed" and pl["po_id"] in open_pos and mode == "learned":
            p = open_pos[pl["po_id"]]
            p["qty_eff"] = int(pl["confirmed_qty"])
            if p["qty_eff"] < int(p["qty"]):
                p["evidence"].append(f"events:{e['event_id']} (livraison partielle {p['qty_eff']}/{p['qty']})")

    out = {}
    for cid in stock:
        s, first_neg, min_s, ev = stock[cid], None, stock[cid], set([f"inventory:{cid}"])
        series = []
        for w in weeks:
            for p in open_pos.values():
                arr = monday(p["arrival"])
                if p["component_id"] == cid and (arr == w or (w == weeks[0] and arr < w)):
                    s += p["qty_eff"]; ev.update(p["evidence"])
            for pid, b in bom.items():
                if cid in b:
                    mult = demand_mult.get((pid, w), 1.0)
                    s -= int(fc[(w, pid)] * mult * b[cid])
                    if mult != 1.0: ev.add(f"events:sellout_spike {pid} x{mult:.2f}")
            series.append((w.isoformat(), s))
            min_s = min(min_s, s)
            if s < 0 and first_neg is None:
                first_neg = w
        out[cid] = {"stockout_week": first_neg.isoformat() if first_neg else None,
                    "min_stock": min_s, "evidence": sorted(ev), "series": series}
    return out
