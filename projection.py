"""
LaunchPilot — moteur de projection (l'outil que les agents appellent). Tout est déterministe et traçable.

Trois vues, mêmes données d'entrée (jamais la vérité terrain) :
  - "naive"   : l'ancienne baseline : croit les dates promises et la prévision v1, ignore les pics de ventes
                et les confirmations de commande. Conservée pour comparaison seulement.
  - "literal" : le planificateur attentif sans mémoire : lit chaque message au pied de la lettre (nouvelles dates
                promises, quantités confirmées, pics de ventes) mais croit les délais annoncés par les fournisseurs.
  - "learned" : LaunchPilot : tout ce que lit le planificateur attentif, plus la mémoire fournisseur
                (délai retenu = médiane des délais réels livrés ; retard annoncé amplifié par le ratio réel/annoncé).

project_prob() rejoue la vue "learned" en tirant chaque délai dans l'historique réel du fournisseur :
probabilité de rupture par semaine, semaine médiane de rupture, bande de stock p10 / p50 / p90.

Usage en lib :
    from projection import load, project, project_prob
    db = load("data")
    project(db, events_seen, mode="learned")  -> {component_id: {"stockout_week", "min_stock", "evidence", "series"}}
    project_prob(db, events_seen)             -> {component_id: {"p_by_week", "p_window", "median_week", "p10", "p50", "p90", ...}}
"""
import csv, json, os, random, statistics
from datetime import date, timedelta

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
    """Mémoire fournisseur = ce que la vue SQL supplier_reliability calcule, plus l'échantillon des délais réels."""
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
                                 "typical": round(statistics.median(d)) if d else ann,   # délai retenu
                                 "samples": d, "n": len(d), "ratio": real / ann, "late_po_ids": late}
    return mem

def _frame(db, window_end=None):
    """Les constantes d'une projection : semaines, stock initial, nomenclature, prévision."""
    window_end = window_end or _d(db["gt"]["window_end"])
    stock = {r["item_id"]: int(r["qty"]) for r in db["inventory"] if r["item_type"] == "component"}
    bom = {}
    for r in db["bom"]:
        bom.setdefault(r["product_id"], {})[r["component_id"]] = float(r["qty_per_unit"])
    fc = {(_d(r["week"]), r["product_id"]): int(r["qty"]) for r in db["forecasts"]}
    weeks = sorted({w for w, _ in fc if w <= window_end})
    return weeks, stock, bom, fc

def _open_orders(db, events_seen, mode, mem, lead_time, extra_pos=None, demand_scale=None, weeks=None, exclude_pos=None):
    """État des commandes ouvertes et des multiplicateurs de demande après lecture des événements.
    lead_time(supplier_id, announced) donne le délai utilisé pour une commande ouverte (vue learned)."""
    sim_today = _d(db["gt"]["sim_today"])
    open_pos = {p["po_id"]: dict(p) for p in db["purchase_orders"] if p["status"] == "open" and p["po_id"] not in (exclude_pos or ())}
    # Orders delivered since the stock snapshot are known arrivals: fixed date and quantity, no uncertainty left.
    for p in db["purchase_orders"]:
        if p["status"] == "delivered" and p.get("actual_date") and _d(p["actual_date"]) >= sim_today:
            open_pos[p["po_id"]] = dict(p, arrival=_d(p["actual_date"]), qty_eff=int(p.get("delivered_qty") or p["qty"]),
                                        evidence=[f"purchase_orders:{p['po_id']} (delivered {p['actual_date']})"], fixed=True)
    for p in open_pos.values():
        if p.get("fixed"):
            continue
        p["arrival"] = _d(p["promised_date"])
        p["qty_eff"] = int(p["qty"])
        p["evidence"] = [f"purchase_orders:{p['po_id']}"]
        if mode == "learned":
            m = mem[p["supplier_id"]]
            p["arrival"] = _d(p["order_date"]) + timedelta(days=lead_time(p["supplier_id"], m["announced"]))
            p["evidence"].append(f"supplier_reliability:{p['supplier_id']} (announced {m['announced']} d, actual {m['real_mean']} ± {m['std']} d over {m['n']} deliveries, lead time used {m['typical']} d)")
    for i, x in enumerate(extra_pos or []):
        open_pos[f"SIM-{i}"] = {"po_id": f"SIM-{i}", "component_id": x["component_id"], "qty": x["qty"],
                                "qty_eff": int(x["qty"]), "arrival": x["arrival"], "supplier_id": x.get("supplier_id", ""),
                                "evidence": [f"simulation:{x.get('label', 'simulated order')}"]}
    demand_mult = {}
    for pid, f in (demand_scale or {}).items():
        for w in weeks or []:
            demand_mult[(pid, w)] = f
    for e in events_seen:
        t, pl = e["event_type"], e["payload"]
        if t == "supplier_delay" and pl["po_id"] in open_pos and not open_pos[pl["po_id"]].get("fixed"):
            p = open_pos[pl["po_id"]]
            if mode == "learned":
                p["arrival"] += timedelta(days=round(pl["announced_delay_days"] * mem[p["supplier_id"]]["ratio"]))
            else:
                p["arrival"] = _d(pl["new_promised_date"])
            p["evidence"].append(f"events:{e['event_id']}")
        elif t == "sellout_spike" and mode != "naive":
            for w in pl["weeks_affected"]:
                k = (pl["product_id"], _d(w))
                demand_mult[k] = demand_mult.get(k, 1.0) * pl["observed_vs_forecast"]
        elif t == "po_confirmed" and pl["po_id"] in open_pos and mode != "naive" and not open_pos[pl["po_id"]].get("fixed"):
            p = open_pos[pl["po_id"]]
            p["qty_eff"] = int(pl["confirmed_qty"])
            if p["qty_eff"] < int(p["qty"]):
                p["evidence"].append(f"events:{e['event_id']} (partial delivery {p['qty_eff']}/{p['qty']})")
    return open_pos, demand_mult

def _run(weeks, stock, bom, fc, open_pos, demand_mult):
    """Une trajectoire de stock par composant : {cid: {"series": [(week, stock)], "first_neg": week|None, "min_stock", "evidence"}}."""
    out = {}
    for cid in stock:
        s, first_neg, min_s, ev = stock[cid], None, stock[cid], {f"inventory:{cid}"}
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
        out[cid] = {"first_neg": first_neg, "min_stock": min_s, "evidence": sorted(ev), "series": series}
    return out

def project(db, events_seen, mode="learned", window_end=None, extra_pos=None, demand_scale=None, exclude_pos=None):
    """Projection déterministe. En mode learned le délai retenu est la médiane des délais réels livrés.
    extra_pos : commandes simulées [{component_id, qty, arrival(date), label}] ;
    demand_scale : {product_id: facteur} pour simuler une réduction de lancement ;
    exclude_pos : commandes ouvertes supposées ne jamais arriver (what-if fournisseur)."""
    weeks, stock, bom, fc = _frame(db, window_end)
    mem = supplier_memory(db)
    open_pos, demand_mult = _open_orders(db, events_seen, mode, mem, lambda sid, ann: mem[sid]["typical"],
                                         extra_pos, demand_scale, weeks, exclude_pos)
    out = {}
    for cid, r in _run(weeks, stock, bom, fc, open_pos, demand_mult).items():
        out[cid] = {"stockout_week": r["first_neg"].isoformat() if r["first_neg"] else None,
                    "min_stock": r["min_stock"], "evidence": r["evidence"], "series": r["series"]}
    return out

def project_prob(db, events_seen, n=200, seed=0, window_end=None, extra_pos=None, demand_scale=None):
    """Projection probabiliste : n tirages où chaque commande ouverte reçoit un délai tiré dans l'historique
    réel livré de son fournisseur (retards annoncés amplifiés comme en mode learned).
    Renvoie par composant : p_by_week {semaine: P(rupture au plus tard cette semaine)}, p_window,
    median_week (None si la rupture est improbable), p10 / p50 / p90 (bande de stock), min_stock_p50."""
    weeks, stock, bom, fc = _frame(db, window_end)
    mem = supplier_memory(db)
    # One random stream per supplier, so a new delivery at one supplier never reshuffles the draws of the others.
    rngs = {sid: random.Random(f"{seed}:{sid}") for sid in mem}
    runs = {cid: [] for cid in stock}
    for _ in range(n):
        draw = {sid: (rngs[sid].choice(m["samples"]) if m["samples"] else m["announced"]) for sid, m in mem.items()}
        open_pos, demand_mult = _open_orders(db, events_seen, "learned", mem, lambda sid, ann: draw[sid],
                                             extra_pos, demand_scale, weeks)
        for cid, r in _run(weeks, stock, bom, fc, open_pos, demand_mult).items():
            runs[cid].append(r)
    out = {}
    for cid, rs in runs.items():
        firsts = [r["first_neg"] for r in rs]
        p_by_week = {w.isoformat(): sum(1 for f in firsts if f and f <= w) / n for w in weeks}
        hit = sorted(f for f in firsts if f)
        median_week = hit[len(hit) // 2].isoformat() if len(hit) * 2 > n else None   # médiane sur tous les tirages
        levels = list(zip(*[[s for _, s in r["series"]] for r in rs]))               # par semaine, n valeurs
        q = lambda vals, p: sorted(vals)[min(n - 1, int(p * n))]
        out[cid] = {"p_by_week": p_by_week, "p_window": len(hit) / n, "median_week": median_week,
                    "p10": [(w.isoformat(), q(v, 0.10)) for w, v in zip(weeks, levels)],
                    "p50": [(w.isoformat(), q(v, 0.50)) for w, v in zip(weeks, levels)],
                    "p90": [(w.isoformat(), q(v, 0.90)) for w, v in zip(weeks, levels)],
                    "min_stock_p50": min(q(v, 0.50) for v in levels)}
    return out
