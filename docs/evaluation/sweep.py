#!/usr/bin/env python3
"""Seed sweep for LaunchPilot's proof.

Regenerates the synthetic world for several seeds and scores three planners against the
generator's ground truth, using the kit's own criterion: a stockout counts as detected when
it is predicted within one week of its true date at some point during the event replay.

  naive    the kit's baseline: believes promised dates and forecast v1, ignores sell-out
           spikes and order confirmations
  literal  a fair baseline: takes every message at face value (new promised dates,
           confirmed quantities, sell-out spikes) but has no supplier memory
  learned  LaunchPilot: supplier memory (mean + 1 sd lead time, amplified announced
           delays) on top of everything the literal planner reads

Usage:  python3 docs/evaluation/sweep.py --repo . [--seeds 1-20,42] [--detail 42]
The repo must contain the kit's generate_data.py and projection.py. Standard library only.
"""
import argparse, importlib.util, json, os, statistics, subprocess, sys, tempfile
from datetime import date, datetime

MODES = ("naive", "literal", "learned")
PATCHES = [  # adds a "literal" mode to the kit's projection.py without touching the file
    ('elif t == "sellout_spike" and mode == "learned":',
     'elif t == "sellout_spike" and mode in ("learned", "literal"):'),
    ('elif t == "po_confirmed" and pl["po_id"] in open_pos and mode == "learned":',
     'elif t == "po_confirmed" and pl["po_id"] in open_pos and mode in ("learned", "literal"):'),
    ('            if mode == "naive":\n                p["arrival"] = _d(pl["new_promised_date"])',
     '            if mode in ("naive", "literal"):\n                p["arrival"] = _d(pl["new_promised_date"])'),
]


def parse_seeds(spec):
    seeds = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            seeds += list(range(int(a), int(b) + 1))
        else:
            seeds.append(int(part))
    return seeds


def load_projection(repo, workdir):
    src = open(os.path.join(repo, "projection.py"), encoding="utf-8").read()
    if '"literal"' not in src:
        for old, new in PATCHES:
            if src.count(old) != 1:
                sys.exit(f"projection.py no longer matches the patch for: {old[:60]!r}")
            src = src.replace(old, new)
    path = os.path.join(workdir, "projection_lit.py")
    open(path, "w", encoding="utf-8").write(src)
    spec = importlib.util.spec_from_file_location("projection_lit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def score(P, db, mode):
    truth = {k: (date.fromisoformat(v) if v else None) for k, v in db["gt"]["true_stockouts"].items()}
    sim_today = date.fromisoformat(db["gt"]["sim_today"])
    detect = {}
    for i, e in enumerate([None] + db["events"]):
        t = sim_today if e is None else datetime.fromisoformat(e["ts"]).date()
        for cid, r in P.project(db, db["events"][:i], mode=mode).items():
            if r["stockout_week"] and truth.get(cid) and cid not in detect \
                    and abs((date.fromisoformat(r["stockout_week"]) - truth[cid]).days) <= 7:
                detect[cid] = t
    final = P.project(db, db["events"], mode=mode)
    real = sorted(c for c, v in truth.items() if v)
    return {
        "real": real, "detected": len(detect), "total": len(real),
        "false": sorted(c for c, r in final.items() if r["stockout_week"] and not truth.get(c)),
        "off": sorted(c for c, r in final.items() if r["stockout_week"] and truth.get(c)
                      and abs((date.fromisoformat(r["stockout_week"]) - truth[c]).days) > 7),
        "missed": sorted(c for c in real if not final[c]["stockout_week"]),
        "lead": {c: (truth[c] - detect[c]).days for c in detect},
        "final": {c: r["stockout_week"] for c, r in final.items()},
        "errors_wk": [(date.fromisoformat(final[c]["stockout_week"]) - truth[c]).days / 7
                      for c in real if final[c]["stockout_week"]],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="folder holding generate_data.py and projection.py")
    ap.add_argument("--seeds", default="1-20,42")
    ap.add_argument("--detail", type=int, default=42, help="seed to show per-component detail for")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    work = tempfile.mkdtemp(prefix="launchpilot-sweep-")
    P = load_projection(repo, work)
    seeds = parse_seeds(a.seeds)
    rows, dbs = [], {}
    print(f"Seeds {a.seeds}: generator + projection from {repo}\n")
    for seed in seeds:
        out = os.path.join(work, f"s{seed}")
        subprocess.run([sys.executable, os.path.join(repo, "generate_data.py"), "--seed", str(seed), "--out", out],
                       check=True, capture_output=True)
        db = P.load(out)
        dbs[seed] = db
        r = {m: score(P, db, m) for m in MODES}
        rows.append(r)
        cells = " | ".join(f"{m[:3]} {r[m]['detected']}/{r[m]['total']} fa{len(r[m]['false'])} off{len(r[m]['off'])}" for m in MODES)
        print(f"seed {seed:>2} | real: {', '.join(c.replace('CMP-', '') for c in r['naive']['real']):30} | {cells}"
              f" | pump true {db['gt']['true_stockouts']['CMP-POM-01']} learned {r['learned']['final']['CMP-POM-01']}")
    print("\nTotals (detected = within one week of the true date at some point in the replay)")
    for m in MODES:
        d, t = sum(r[m]["detected"] for r in rows), sum(r[m]["total"] for r in rows)
        errs = [x for r in rows for x in r[m]["errors_wk"]]
        print(f"  {m:8} detected {d}/{t} ({100 * d / t:.0f}%) | false alarms {sum(len(r[m]['false']) for r in rows)}"
              f" | final date wrong by >1 week: {sum(len(r[m]['off']) for r in rows)}"
              f" | signed error of final date {statistics.mean(errs):+.2f} weeks (n={len(errs)})")
    truth_sets = {json.dumps(db["gt"]["true_stockouts"], sort_keys=True) for db in dbs.values()}
    pump = [db["gt"]["true_stockouts"]["CMP-POM-01"] for db in dbs.values()]
    print(f"\nVariation between seeds: {len(truth_sets)} distinct sets of true stockouts; "
          f"pump true stockout week: {dict(sorted((w, pump.count(w)) for w in set(pump)))}")
    if a.detail in dbs:
        db = dbs[a.detail]
        print(f"\nSeed {a.detail}: final prediction per component")
        for cid, tw in db["gt"]["true_stockouts"].items():
            fin = {m: P.project(db, db["events"], m)[cid]["stockout_week"] for m in MODES}
            print(f"  {cid:12} truth {str(tw):10} | " + " | ".join(f"{m} {str(fin[m]):10}" for m in MODES))
        target = db["gt"]["true_stockouts"]["CMP-POM-01"]
        if target:
            tw = date.fromisoformat(target)
            print(f"\nSeed {a.detail}: first event after which the pump's true week ({target}) is predicted within one week")
            for m in MODES:
                hit = None
                for i, e in enumerate([None] + db["events"]):
                    r = P.project(db, db["events"][:i], m)["CMP-POM-01"]
                    if r["stockout_week"] and abs((date.fromisoformat(r["stockout_week"]) - tw).days) <= 7:
                        hit = "initial state" if e is None else f"{e['event_id']} ({e['ts'][:10]})"
                        break
                print(f"  {m:8} {hit}")


if __name__ == "__main__":
    main()
