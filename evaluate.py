"""
LaunchPilot — protocole de preuve : rejoue le flux d'événements et compare
la baseline naïve à la projection avec mémoire fournisseur.

Pour chaque composant réellement en rupture dans la fenêtre :
  - détecté ?            (une alerte prédit une rupture à ±1 semaine de la vraie date)
  - date de détection    (premier moment où l'alerte juste apparaît)
  - anticipation (jours) = vraie semaine de rupture - date de détection
Fausses alertes = composants signalés en rupture qui n'en ont pas dans la réalité.
Valeur à risque = demande non servie du coffret si la rupture n'est pas traitée (prix x quantité).

Usage : python evaluate.py [--data data]
"""
import argparse, json
from datetime import date, datetime, timedelta
from projection import load, project

ap = argparse.ArgumentParser(); ap.add_argument("--data", default="data"); a = ap.parse_args()
db = load(a.data)
truth = {k: (date.fromisoformat(v) if v else None) for k, v in db["gt"]["true_stockouts"].items()}
sim_today = date.fromisoformat(db["gt"]["sim_today"])

def run(mode):
    detect, alarms = {}, set()
    checkpoints = [None] + db["events"]          # état initial puis après chaque événement
    for i, e in enumerate(checkpoints):
        seen = db["events"][:i]
        t = sim_today if e is None else datetime.fromisoformat(e["ts"]).date()
        res = project(db, seen, mode=mode)
        for cid, r in res.items():
            if not r["stockout_week"]: continue
            pred = date.fromisoformat(r["stockout_week"])
            alarms.add(cid)
            if truth.get(cid) and abs((pred - truth[cid]).days) <= 7 and cid not in detect:
                detect[cid] = t
    final = project(db, db["events"], mode=mode)
    false_alarms = sorted(c for c, r in final.items() if r["stockout_week"] and not truth.get(c))
    return detect, false_alarms, final

real = sorted(c for c, v in truth.items() if v)
report = {"real_stockouts": {c: truth[c].isoformat() for c in real}}
print(f"Ruptures réelles dans la fenêtre : {len(real)} -> " + ", ".join(f"{c} ({truth[c]})" for c in real))
for mode in ["naive", "learned"]:
    detect, fa, final = run(mode)
    lead = {c: (truth[c] - detect[c]).days for c in detect}
    avg = sum(lead.values()) / len(lead) if lead else 0
    print(f"\n[{mode}] détectées {len(detect)}/{len(real)} | anticipation moyenne {avg:.0f} j | fausses alertes finales {len(fa)}")
    for c in real:
        print(f"   {c:13s} " + (f"vue le {detect[c]} -> {lead[c]} j avant" if c in detect else "RATÉE"))
    report[mode] = {"detected": len(detect), "total": len(real), "avg_anticipation_days": round(avg),
                    "per_component": {c: lead.get(c) for c in real}, "false_alarms": fa}

# focus démo : la pompe
pump = project(db, db["events"], mode="learned")["CMP-POM-01"]
report["demo_focus_pump_evidence"] = pump["evidence"]
json.dump(report, open(f"{a.data}/evaluation.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\nPreuves citées pour la pompe :"); [print("  -", x) for x in pump["evidence"]]
print(f"\nRésultats écrits dans {a.data}/evaluation.json")
