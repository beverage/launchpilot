"""
LaunchPilot — protocole de preuve (scénario enregistré, données synthétiques).

Baseline honnête = planificateur attentif sans mémoire : il lit chaque message (nouvelles dates promises,
quantités confirmées, pics de ventes) mais croit les délais annoncés par les fournisseurs.
LaunchPilot = la même lecture, plus la mémoire fournisseur (délai retenu = médiane des délais réels livrés).

Pour N mondes synthétiques (graines 1..N, mêmes règles, tirages différents) on rejoue les 35 événements :
  - datée      : la rupture est annoncée à ±1 semaine de sa vraie date à un moment du rejeu
  - avance     : jours entre la première datation juste et la vraie rupture
  - erreur     : écart (semaines) entre la date finale annoncée et la vraie date
  - fausse alerte : rupture annoncée à la fin pour un composant qui n'en a pas en réalité
Puis le détail du scénario de la démo (le dossier data/, graine 42), avec la probabilité finale de LaunchPilot.

Usage : python evaluate.py [--seeds 30] [--data data]
"""
import argparse, json, os, statistics, subprocess, sys, tempfile
from datetime import date, datetime, timedelta
from projection import load, project, project_prob

HERE = os.path.dirname(os.path.abspath(__file__))
MODES = ("without_memory", "launchpilot")
DRAWS = 60   # tirages par point de contrôle pour la vue LaunchPilot (200 dans l'application)


def predict(db, seen, mode, draws=DRAWS):
    """Semaine de rupture annoncée par composant, ou None. LaunchPilot annonce comme l'application alerte :
    semaine médiane des tirages, seulement si la rupture est probable (≥ 50 %) avant fin décembre."""
    if mode == "without_memory":
        return {c: r["stockout_week"] for c, r in project(db, seen, mode="literal").items()}
    return {c: (r["median_week"] if r["p_window"] >= 0.5 else None) for c, r in project_prob(db, seen, n=draws).items()}


def score(db, mode, draws=DRAWS):
    truth = {k: (date.fromisoformat(v) if v else None) for k, v in db["gt"]["true_stockouts"].items()}
    sim_today = date.fromisoformat(db["gt"]["sim_today"])
    detect = {}
    for i, e in enumerate([None] + db["events"]):
        t = sim_today if e is None else datetime.fromisoformat(e["ts"]).date()
        for cid, wk in predict(db, db["events"][:i], mode, draws).items():
            if wk and truth.get(cid) and cid not in detect and abs((date.fromisoformat(wk) - truth[cid]).days) <= 7:
                detect[cid] = t
    final = predict(db, db["events"], mode, draws)
    real = [c for c, v in truth.items() if v]
    return {"real": real, "detected": len(detect), "total": len(real),
            "lead": {c: (truth[c] - detect[c]).days for c in detect},
            "false_alarms": [c for c, wk in final.items() if wk and not truth.get(c)],
            "errors_wk": {c: (date.fromisoformat(final[c]) - truth[c]).days / 7 if final[c] else None for c in real},
            "final": final}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30, help="nombre de mondes synthétiques (graines 1..N)")
    ap.add_argument("--data", default=os.path.join(HERE, "data"))
    a = ap.parse_args()
    work = tempfile.mkdtemp(prefix="launchpilot-eval-")
    agg = {k: {"detected": 0, "total": 0, "lead": [], "false_alarms": 0, "wrong": 0, "abs_err": []} for k in MODES}
    for seed in range(1, a.seeds + 1):
        out = os.path.join(work, f"s{seed}")
        subprocess.run([sys.executable, os.path.join(HERE, "generate_data.py"), "--seed", str(seed), "--out", out],
                       check=True, capture_output=True)
        db = load(out)
        for k in MODES:
            r = score(db, k)
            g = agg[k]
            g["detected"] += r["detected"]; g["total"] += r["total"]
            g["lead"] += list(r["lead"].values()); g["false_alarms"] += len(r["false_alarms"])
            errs = [e for e in r["errors_wk"].values() if e is not None]
            g["wrong"] += sum(1 for e in errs if abs(e) > 1) + sum(1 for e in r["errors_wk"].values() if e is None)
            g["abs_err"] += [abs(e) for e in errs]
    report = {"protocol": "Replay of the 35 events over N synthetic worlds; a stockout is dated when it is announced within one week of its true date; "
                          "baseline = attentive planner without memory (reads every message, believes announced lead times); "
                          "LaunchPilot = the same reading plus the supplier memory (lead times drawn from delivered history; announces the median week when a stockout is at least 50% likely).",
              "seeds": a.seeds, "recorded_not_live": True}
    for k, g in agg.items():
        report[k] = {"detected": g["detected"], "total": g["total"],
                     "mean_lead_days": round(statistics.mean(g["lead"])) if g["lead"] else 0,
                     "false_alarms": g["false_alarms"], "wrong_by_more_than_1wk": g["wrong"],
                     "median_abs_error_weeks": round(statistics.median(g["abs_err"]), 1) if g["abs_err"] else None}
        print(f"[{k:15}] dated {g['detected']}/{g['total']} | mean lead {report[k]['mean_lead_days']} d | "
              f"wrong dates (> 1 wk) {g['wrong']} | false alarms {g['false_alarms']} | median error {report[k]['median_abs_error_weeks']} wk")

    # le scénario de la démo : le dossier data/ tel qu'il est commité
    db = load(a.data)
    seed = 42
    truth = db["gt"]["true_stockouts"]
    r = {k: score(db, k, draws=200) for k in MODES}
    prob = project_prob(db, db["events"])
    launch1 = (date.fromisoformat(db["gt"]["launch_week"]) + timedelta(weeks=1)).isoformat()
    per = {}
    for c in truth:
        per[c] = {"truth": truth[c], "without_memory": r["without_memory"]["final"][c], "launchpilot": r["launchpilot"]["final"][c],
                  "lead_days_without_memory": r["without_memory"]["lead"].get(c), "lead_days_launchpilot": r["launchpilot"]["lead"].get(c),
                  "p_by_launch_plus_1wk": round(prob[c]["p_by_week"][launch1], 2), "p_before_end_of_year": round(prob[c]["p_window"], 2)}
    report["demo_seed"] = {"seed": seed, "per_component": per}
    pump = project(db, db["events"], mode="learned")["CMP-POM-01"]
    report["demo_focus_pump_evidence"] = pump["evidence"]
    print("\nDemo scenario:")
    for c, x in per.items():
        if x["truth"]:
            print(f"  {c:13} true {x['truth']} | without memory {str(x['without_memory']):10} ({x['lead_days_without_memory']} d ahead) | "
                  f"LaunchPilot {str(x['launchpilot']):10} ({x['lead_days_launchpilot']} d ahead) | P(≤ launch+1 wk) {x['p_by_launch_plus_1wk']:.0%}")
    with open(os.path.join(a.data, "evaluation.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nResults written to {os.path.join(a.data, 'evaluation.json')}")


if __name__ == "__main__":
    main()
