"""
LaunchPilot — générateur de données synthétiques (marque fictive Maison Aurore).

Produit dans ./data :
  - CSV des tables de base et transactionnelles (suppliers, components, products, bom,
    subcontractors, sales_history, forecasts, inventory, purchase_orders)
  - events.jsonl        : le flux d'événements à rejouer pendant la démo (20 perturbations + bruit)
  - ground_truth.json   : vérité terrain pour mesurer baseline vs agents
  - true_arrivals.json  : dates d'arrivée "réelles" des commandes ouvertes (cachées aux agents)

Principe de la vérité terrain :
  - chaque fournisseur a un délai ANNONCÉ et un comportement RÉEL (moyenne + bruit) ;
  - l'historique des livraisons révèle ce comportement à qui sait le lire ;
  - la baseline fait confiance aux dates promises ; la réalité suit le comportement réel ;
  - une rupture "vraie" = stock projeté < 0 avec arrivées réelles + demande réelle (pics inclus).

Usage : python generate_data.py [--seed 42]
Aucune dépendance externe (stdlib uniquement).
"""
import csv, json, random, argparse, os
from datetime import date, timedelta, datetime

p = argparse.ArgumentParser()
p.add_argument("--seed", type=int, default=42)
p.add_argument("--out", default="data")
args = p.parse_args()
rng = random.Random(args.seed)
os.makedirs(args.out, exist_ok=True)

SIM_TODAY = date(2026, 9, 7)          # lundi S37 : "aujourd'hui" dans la démo
LAUNCH_WEEK = date(2026, 11, 2)       # lundi S45 : mise en marché du coffret
HORIZON_WEEKS = 20
HISTORY_WEEKS = 78
WINDOW_END = date(2026, 12, 28)      # fin de la fenêtre de Noël suivie

def monday(d): return d - timedelta(days=d.weekday())
def weeks(start, n): return [start + timedelta(weeks=i) for i in range(n)]
FUTURE = weeks(SIM_TODAY, HORIZON_WEEKS)
PAST = weeks(SIM_TODAY - timedelta(weeks=HISTORY_WEEKS), HISTORY_WEEKS)

# ---------------- Données de base ----------------
# real_mu / real_sd = comportement réel (jours), caché sauf via l'historique
SUPPLIERS = [
  # id, name, category, announced, moq, cost, real_mu, real_sd
  ("SUP-FLA", "Verrerie Lumière",   "flacon",  42, 10000, 0.42, 45, 4),
  ("SUP-POM", "Pompes Atlas",       "pompe",   42, 20000, 0.18, 61, 7),   # la star : annonce 6 sem., livre ~8,7
  ("SUP-POM-B","Dosage Riviera",    "pompe",   49,  5000, 0.26, 50, 3),   # alternative fiable mais plus chère
  ("SUP-ETU", "Cartonnages de Seine","etui",   28,  5000, 0.09, 29, 3),
  ("SUP-COF", "Coffrets Prestige",  "coffret", 35,  3000, 1.35, 44, 6),   # dérive modérée
]
COMPONENTS = [
  ("CMP-FLA-30", "Flacon verre 30 ml",   "flacon",  "SUP-FLA", None),
  ("CMP-FLA-50", "Pot verre 50 ml",      "flacon",  "SUP-FLA", None),
  ("CMP-POM-01", "Pompe airless 30 ml",  "pompe",   "SUP-POM", "SUP-POM-B"),
  ("CMP-ETU-01", "Étui carton sérum",    "etui",    "SUP-ETU", None),
  ("CMP-ETU-02", "Étui carton crème",    "etui",    "SUP-ETU", None),
  ("CMP-COF-NOEL","Coffret Noël 2026",   "coffret", "SUP-COF", None),
]
PRODUCTS = [
  # id, name, family, price, margin, is_launch, base weekly demand, bom
  ("PRD-SER-ECL", "Sérum Éclat 30 ml",      "soin",  49.0, 0.68, False, 900,
     {"CMP-FLA-30":1, "CMP-POM-01":1, "CMP-ETU-01":1}),
  ("PRD-SER-NUI", "Sérum Nuit 30 ml",       "soin",  55.0, 0.70, False, 600,
     {"CMP-FLA-30":1, "CMP-POM-01":1, "CMP-ETU-01":1}),
  ("PRD-CRE-HYD", "Crème Hydra 50 ml",      "soin",  42.0, 0.65, False, 1100,
     {"CMP-FLA-50":1, "CMP-ETU-02":1}),
  ("PRD-CRE-RIC", "Crème Riche 50 ml",      "soin",  46.0, 0.66, False, 500,
     {"CMP-FLA-50":1, "CMP-ETU-02":1}),
  ("PRD-COF-NOEL","Coffret Rituel Noël",    "coffret",89.0, 0.62, True,  0,
     {"CMP-FLA-30":1, "CMP-POM-01":1, "CMP-FLA-50":1, "CMP-COF-NOEL":1}),
]
CHANNELS = {"eshop":0.35, "distributeur_selectif":0.45, "pharmacie":0.20}
SUBCONTRACTORS = [("FAC-01", "Laboratoire Val de Loire", 9000), ("FAC-02", "Cosmétiques Normandie", 3000)]

# Demande prévue du coffret : rampe avant/pendant Noël
def coffret_forecast(w):
    if w < LAUNCH_WEEK - timedelta(weeks=1): return 0
    if w < LAUNCH_WEEK: return 3000           # mise en place S44
    if w < date(2026, 12, 28): return 2200     # S45–S52
    return 300

def seasonal(w, base):
    m = w.month
    f = 1.25 if m in (11, 12) else (0.85 if m in (7, 8) else 1.0)
    return max(0, int(rng.gauss(base * f, base * 0.12)))

# ---------------- Historique ventes ----------------
sales = []
for w in PAST:
    for pid, _, _, _, _, launch, base, _ in PRODUCTS:
        if launch: continue
        q = seasonal(w, base)
        for ch, share in CHANNELS.items():
            sales.append((w, pid, ch, int(q * share)))

# ---------------- Prévisions ----------------
forecasts = []
for w in FUTURE:
    for pid, _, _, _, _, launch, base, _ in PRODUCTS:
        q = coffret_forecast(w) if launch else int(base * (1.25 if w.month in (11, 12) else 1.0))
        forecasts.append((w, pid, q, "v1"))
fc = {(w, pid): q for w, pid, q, _ in forecasts}

# ---------------- Commandes fournisseurs ----------------
sup = {s[0]: s for s in SUPPLIERS}
comp_supplier = {c[0]: c[3] for c in COMPONENTS}
pos, po_n = [], 0
def new_po(sid, cid, qty, odate, delivered, real_offset=None):
    global po_n
    po_n += 1
    s = sup[sid]
    promised = odate + timedelta(days=s[3])
    real = real_offset if real_offset is not None else max(s[3] - 5, int(rng.gauss(s[6], s[7])))
    actual = odate + timedelta(days=real)
    rec = {"po_id": f"PO-{po_n:04d}", "supplier_id": sid, "component_id": cid, "qty": qty,
           "order_date": odate, "promised_date": promised,
           "actual_date": actual if delivered else None,
           "status": "delivered" if delivered else "open"}
    pos.append(rec)
    return rec, actual

# historique : ~14 livraisons par fournisseur principal
for sid, _, cat, ann, moq, *_ in SUPPLIERS:
    cids = [c[0] for c in COMPONENTS if c[3] == sid or c[4] == sid]
    cids = [c for c in cids if c != "CMP-COF-NOEL"] or cids
    n = 14 if sid != "SUP-POM-B" else 6
    for i in range(n):
        od = SIM_TODAY - timedelta(days=500 - i * 32 + rng.randint(-5, 5))
        rec, actual = new_po(sid, rng.choice(cids), moq * rng.choice([1, 1, 2]), od, True)
        if actual >= SIM_TODAY:  # garder l'historique strictement passé
            pos.pop(); po_n -= 1

# commandes ouvertes pour couvrir le lancement (dates promises OK, réalité parfois non)
OPEN = [
  ("SUP-POM", "CMP-POM-01", 20000, date(2026, 8, 3)),
  ("SUP-POM", "CMP-POM-01", 20000, date(2026, 8, 31)),
  ("SUP-FLA", "CMP-FLA-30", 20000, date(2026, 8, 10)),
  ("SUP-FLA", "CMP-FLA-50", 20000, date(2026, 8, 17)),
  ("SUP-COF", "CMP-COF-NOEL", 12000, date(2026, 8, 24)),
  ("SUP-COF", "CMP-COF-NOEL", 9000, date(2026, 9, 1)),
  ("SUP-ETU", "CMP-ETU-01", 10000, date(2026, 8, 24)),
  ("SUP-ETU", "CMP-ETU-02", 10000, date(2026, 8, 24)),
]
true_arrival = {}
for sid, cid, qty, od in OPEN:
    rec, actual = new_po(sid, cid, qty, od, False)
    true_arrival[rec["po_id"]] = actual

# ---------------- Stock à date ----------------
inventory = [
  (SIM_TODAY, "CMP-FLA-30", "component", 32000),
  (SIM_TODAY, "CMP-FLA-50", "component", 26000),
  (SIM_TODAY, "CMP-POM-01", "component", 11000),
  (SIM_TODAY, "CMP-ETU-01", "component", 24000),
  (SIM_TODAY, "CMP-ETU-02", "component", 22000),
  (SIM_TODAY, "CMP-COF-NOEL", "component", 0),
] + [(SIM_TODAY, pr[0], "product", int(pr[6] * 2.5)) for pr in PRODUCTS]

# ---------------- Flux d'événements (20 perturbations + bruit) ----------------
open_pos = [p_ for p_ in pos if p_["status"] == "open"]
po_by = lambda cid: [p_ for p_ in open_pos if p_["component_id"] == cid]
events, eid = [], 0
def ev(day_offset, etype, payload, disruption=True):
    global eid
    eid += 1
    ts = datetime.combine(SIM_TODAY + timedelta(days=day_offset), datetime.min.time()) + timedelta(hours=rng.randint(8, 17))
    events.append({"event_id": f"EV-{eid:03d}", "ts": ts.isoformat(), "event_type": etype,
                   "payload": payload, "is_disruption": disruption})
    return events[-1]

demand_mult = {}      # (pid, week) -> multiplicateur réel
DISRUPTIONS = []
# 1-6 : retards fournisseurs (le fournisseur annonce un nouveau délai ; la réalité peut être pire)
for i, (cid, extra_announced) in enumerate([("CMP-POM-01", 10), ("CMP-POM-01", 7), ("CMP-COF-NOEL", 12),
                                            ("CMP-FLA-30", 5), ("CMP-ETU-01", 3), ("CMP-COF-NOEL", 6)]):
    po = po_by(cid)[i % len(po_by(cid))]
    sid = po["supplier_id"]; s = sup[sid]
    slip_real = int(extra_announced * (s[6] / s[3]))          # les mauvais fournisseurs glissent plus que prévu
    true_arrival[po["po_id"]] += timedelta(days=slip_real)
    new_promised = po["promised_date"] + timedelta(days=extra_announced)
    e = ev(3 + i * 4, "supplier_delay", {"po_id": po["po_id"], "supplier_id": sid, "component_id": cid,
           "new_promised_date": new_promised.isoformat(), "announced_delay_days": extra_announced})
    DISRUPTIONS.append(e)
# 7-12 : pics de sell-out
for i, (pid, mult, wk_from, n_wk) in enumerate([("PRD-SER-ECL", 1.4, 6, 4), ("PRD-COF-NOEL", 1.3, 8, 3),
        ("PRD-CRE-HYD", 1.2, 5, 3), ("PRD-SER-NUI", 1.5, 7, 2), ("PRD-CRE-RIC", 1.1, 4, 2), ("PRD-COF-NOEL", 1.25, 10, 3)]):
    for k in range(n_wk):
        w = SIM_TODAY + timedelta(weeks=wk_from + k)
        demand_mult[(pid, w)] = demand_mult.get((pid, w), 1.0) * mult
    e = ev(2 + i * 5, "sellout_spike", {"product_id": pid, "channel": "distributeur_selectif",
           "observed_vs_forecast": round(mult, 2),
           "weeks_affected": [(SIM_TODAY + timedelta(weeks=wk_from + k)).isoformat() for k in range(n_wk)]})
    DISRUPTIONS.append(e)
# 13-16 : baisses de capacité façonnier
for i, (fac, drop, wk_from, n_wk) in enumerate([("FAC-01", 0.4, 7, 2), ("FAC-02", 0.5, 3, 1), ("FAC-01", 0.15, 4, 1), ("FAC-01", 0.3, 9, 1)]):
    e = ev(5 + i * 6, "capacity_drop", {"subcontractor_id": fac, "capacity_drop_rate": drop,
           "weeks_affected": [(SIM_TODAY + timedelta(weeks=wk_from + k)).isoformat() for k in range(n_wk)]})
    DISRUPTIONS.append(e)
# 17-20 : confirmations / annulations qui changent la donne
for i, cid in enumerate(["CMP-FLA-50", "CMP-ETU-02", "CMP-POM-01", "CMP-FLA-30"]):
    po = po_by(cid)[0]
    e = ev(10 + i * 7, "po_confirmed", {"po_id": po["po_id"], "component_id": cid,
           "confirmed_date": po["promised_date"].isoformat(), "confirmed_qty": po["qty"] if i != 2 else int(po["qty"] * 0.6)})
    if i == 2:  # livraison partielle de pompes
        po["_partial"] = 0.6
    DISRUPTIONS.append(e)
# bruit : événements sans impact
for i in range(15):
    ev(rng.randint(0, 50), "noise", {"note": rng.choice(["changement d'interlocuteur fournisseur",
        "mise à jour fiche article", "relance qualité", "inventaire tournant OK", "visite façonnier"])}, disruption=False)
events.sort(key=lambda e: e["ts"])

# ---------------- Vérité terrain : projection avec réalité ----------------
bom = {pr[0]: pr[7] for pr in PRODUCTS}
stock0 = {i[1]: i[3] for i in inventory if i[2] == "component"}

def project(use_true=True, events_subset=None):
    """Retourne {component: première semaine de stock négatif ou None}."""
    res = {}
    for cid in stock0:
        s = stock0[cid]; first_neg = None
        for w in [w_ for w_ in FUTURE if w_ <= WINDOW_END]:
            for po in open_pos:
                if po["component_id"] != cid: continue
                arr = true_arrival[po["po_id"]] if use_true else po["promised_date"]
                if monday(arr) == w:
                    s += int(po["qty"] * (po.get("_partial", 1.0) if use_true else 1.0))
            for pid, b in bom.items():
                if cid in b:
                    mult = demand_mult.get((pid, w), 1.0) if use_true else 1.0
                    s -= int(fc[(w, pid)] * mult * b[cid])
            if s < 0 and first_neg is None:
                first_neg = w
        res[cid] = first_neg
    return res

truth = project(use_true=True)
naive = project(use_true=False)
gt = {
  "sim_today": SIM_TODAY.isoformat(),
  "launch_week": LAUNCH_WEEK.isoformat(),
  "window_end": WINDOW_END.isoformat(),
  "true_stockouts": {k: (v.isoformat() if v else None) for k, v in truth.items()},
  "naive_view_stockouts": {k: (v.isoformat() if v else None) for k, v in naive.items()},
  "disruption_event_ids": [e["event_id"] for e in DISRUPTIONS],
  "noise_event_ids": [e["event_id"] for e in events if not e["is_disruption"]],
  "notes": "true_stockouts = ce qui arrive vraiment (délais réels, pics, livraisons partielles). "
           "naive_view_stockouts = ce que voit une règle qui croit les dates promises et la prévision v1.",
}

# ---------------- Écriture ----------------
def write(name, header, rows):
    with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)

write("suppliers.csv", ["supplier_id","name","category","announced_lead_time_days","moq","unit_cost_eur"],
      [s[:6] for s in SUPPLIERS])
write("components.csv", ["component_id","name","category","main_supplier_id","alt_supplier_id"], COMPONENTS)
write("products.csv", ["product_id","name","family","price_eur","margin_rate","is_launch","launch_week"],
      [(p_[0], p_[1], p_[2], p_[3], p_[4], p_[5], 45 if p_[5] else "") for p_ in PRODUCTS])
write("bom.csv", ["product_id","component_id","qty_per_unit"],
      [(pid, c, q) for pid, b in bom.items() for c, q in b.items()])
write("subcontractors.csv", ["subcontractor_id","name","weekly_capacity_units"], SUBCONTRACTORS)
write("sales_history.csv", ["week","product_id","channel","qty"], sales)
write("forecasts.csv", ["week","product_id","qty","version"], forecasts)
write("inventory.csv", ["snapshot_date","item_id","item_type","qty"], inventory)
write("purchase_orders.csv", ["po_id","supplier_id","component_id","qty","order_date","promised_date","actual_date","status"],
      [(p_["po_id"], p_["supplier_id"], p_["component_id"], p_["qty"], p_["order_date"], p_["promised_date"],
        p_["actual_date"] or "", p_["status"]) for p_ in pos])
with open(os.path.join(args.out, "events.jsonl"), "w", encoding="utf-8") as f:
    for e in events:
        e2 = {k: v for k, v in e.items() if k != "is_disruption"}   # le flux ne révèle pas la vérité
        f.write(json.dumps(e2, ensure_ascii=False) + "\n")
with open(os.path.join(args.out, "ground_truth.json"), "w", encoding="utf-8") as f:
    json.dump(gt, f, ensure_ascii=False, indent=2)
with open(os.path.join(args.out, "true_arrivals.json"), "w", encoding="utf-8") as f:
    json.dump({k: v.isoformat() for k, v in true_arrival.items()}, f, indent=2)

# ---------------- Résumé ----------------
print(f"Seed {args.seed} — {len(sales)} lignes ventes, {len(forecasts)} prévisions, {len(pos)} commandes "
      f"({len(open_pos)} ouvertes), {len(events)} événements ({len(DISRUPTIONS)} perturbations).")
print("Fiabilité réelle (historique livré) :")
for sid, name, _, ann, *_ in SUPPLIERS:
    d = [(p_["actual_date"] - p_["order_date"]).days for p_ in pos if p_["supplier_id"] == sid and p_["status"] == "delivered"]
    if d: print(f"  {name:22s} annoncé {ann:3d} j | réel moyen {sum(d)/len(d):5.1f} j sur {len(d)} livraisons")
print("Ruptures composants avant fin d'horizon :")
for c in stock0:
    print(f"  {c:13s} vue naïve: {gt['naive_view_stockouts'][c] or '—':10s} | réalité: {gt['true_stockouts'][c] or '—'}")
