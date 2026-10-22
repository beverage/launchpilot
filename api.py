"""
LaunchPilot HTTP API for the web frontend (built in Lovable).
Wraps the same store, tools and agents as app.py, which stays the fallback demo.

Run locally: uvicorn api:app --reload --port 8000
Variables: DATABASE_URL and ANTHROPIC_API_KEY as for app.py (both optional),
CORS_ORIGINS (comma-separated extra origins, for example the deployed frontend).
Lovable preview and published domains and localhost are always allowed.
"""
import json, os, re, threading
from datetime import date

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import tools as T
import agents as A
from projection import project
from store import PgStore, get_store

store, store_err = get_store()
ALL = T.all_events()
LOCK = threading.Lock()      # one agent run at a time: a double click must not process an event twice
RUNS = []                    # this process's agent runs, with tool calls (the store keeps a summary)
RECO = {}                    # alert_id -> the arbitration agent's recommendation

app = FastAPI(title="LaunchPilot API", version="0.1.0")
LOVABLE_AND_LOCAL = r"https://([a-z0-9-]+\.)*(lovable\.app|lovableproject\.com|lovable\.dev)|http://(localhost|127\.0\.0\.1)(:\d+)?"
app.add_middleware(CORSMiddleware, allow_origin_regex=LOVABLE_AND_LOCAL,
                   allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")


# ---------------- helpers ----------------

def _seen():
    ids = {e["event_id"] for e in store.list_events()}
    return [e for e in ALL if e["event_id"] in ids]


def _now(seen):
    return date.fromisoformat(seen[-1]["ts"][:10]) if seen else T.SIM_TODAY


def _mode(m):
    return "live" if m == "live" else "rules"


def _live(requested):
    return A.claude_available() if requested is None else bool(requested) and A.claude_available()


def _summary(e):
    p, t = e.get("payload", {}), e["event_type"]
    sup = lambda k: T.SUP.get(p.get(k), {}).get("name", p.get(k))
    try:
        if t == "supplier_delay":
            return f"{sup('supplier_id')} pushes {p['po_id']} back {p['announced_delay_days']} days"
        if t == "sellout_spike":
            return f"{T.PROD[p['product_id']]['name']}: sales x{p['observed_vs_forecast']} vs forecast"
        if t == "capacity_drop":
            return f"{p['subcontractor_id']}: capacity -{int(float(p['capacity_drop_rate']) * 100)}%"
        if t == "po_confirmed":
            return f"{p['po_id']} confirmed: {p['confirmed_qty']} units"
        if t == "po_delivered":
            return f"{p['po_id']} delivered: {p['delivered_qty']} units on {p['actual_date']}"
        if t == "supplier_email":
            return f"Email from {p.get('from')}: {p.get('subject')}"
        if t == "supplier_insolvency":
            return f"{p.get('company_name')}: {p.get('procedure')}"
        if t == "holiday_closure":
            return f"{p.get('name')} ({p.get('country')}, {p.get('date')})"
        if t == "noise":
            return p.get("note", "")
    except (KeyError, TypeError, ValueError):
        pass
    return json.dumps(p, ensure_ascii=False)[:160]


def _event(e):
    return {"event_id": e["event_id"], "ts": e["ts"], "event_type": e["event_type"], "summary": _summary(e),
            "payload": e.get("payload", {}), "origin": "recorded" if e["event_id"].startswith("EV-") else "live"}


def _run(r):
    return {"agent": r["agent"], "mode": _mode(r.get("mode")), "input": r.get("input"), "output": r.get("output"),
            "tool_calls": r.get("tool_calls", []), "latency_ms": r.get("latency_ms", 0),
            "tokens_in": r.get("tokens_in", 0), "tokens_out": r.get("tokens_out", 0),
            "alerts_created": r.get("alerts_created", [])}


def _process(event, live, seen):
    store.add_event(event)
    run = (A.watch_live if live else A.watch_rules)(store, event, seen + [event])
    store.mark_processed(event["event_id"])
    RUNS.append(run)
    return run


def _latest_alerts():
    out, items = [], set()
    for a in store.list_alerts():                  # newest first: keep the latest alert per component
        if a["item_id"] not in items:
            out.append(a)
            items.add(a["item_id"])
    out.sort(key=lambda a: (a["severity"] != "high", a["predicted_stockout_week"] or "9999"))
    return out


def _alert(a):
    scen = store.list_scenarios(a["alert_id"])
    return {"alert_id": a["alert_id"], "component_id": a["item_id"], "component_name": T.comp_label(a["item_id"]),
            "severity": a["severity"], "predicted_stockout_week": a["predicted_stockout_week"],
            "confidence": a.get("confidence"), "explanation": a["explanation"], "evidence": a.get("evidence", []),
            "trigger_event_id": a.get("trigger_event_id"), "created_at": a.get("created_at"),
            "source": a["source"], "mode": "live" if "live" in (a["source"] or "") else "rules",
            "can_arbitrate": a["severity"] == "high" and not scen,
            "recommendation": RECO.get(a["alert_id"]),
            "scenarios": [{"scenario_id": s["scenario_id"], "label": s["label"], "cost_eur": s["cost_eur"],
                           "lost_revenue_eur": s["lost_revenue_eur"], "stock_value_eur": s["stock_value_eur"],
                           "total_impact_eur": s["cost_eur"] + s["lost_revenue_eur"], "description": s.get("description"),
                           "evidence_rows": s.get("evidence_rows") or []} for s in scen]}


def _state():
    seen = _seen()
    now = _now(seen)
    proj = T.run_projection(seen)
    risk = max([T.cost_scenario(seen, now, r["component_id"], "do_nothing")["lost_revenue_eur"]
                for r in proj if r["stockout_week_launchpilot"]] or [0])
    nxt = ALL[len(seen)] if len(seen) < len(ALL) else None
    return {
        "sim_date": now.isoformat(), "launch_week": T.LAUNCH_WEEK.isoformat(), "window_end": T.WINDOW_END.isoformat(),
        "launch_product": {"product_id": T.LAUNCH_PRODUCT, "name": T.PROD[T.LAUNCH_PRODUCT]["name"]},
        "events_processed": len(seen), "events_total": len(ALL),
        "next_event": _event(nxt) if nxt else None,
        "data": {"store": "postgres" if isinstance(store, PgStore) else "memory", "label": store.kind, "error": store_err,
                 "dataset": "synthetic, recorded scenario"},
        "agents": {"live_available": A.claude_available(), "model": A.MODEL},
        "kpis": {"critical_alerts": sum(1 for a in _latest_alerts() if a["severity"] == "high"),
                 "revenue_at_risk_eur": risk},
        "components": [{"component_id": r["component_id"], "name": r["name"], "supplier_id": r["supplier_id"],
                        "supplier_name": T.SUP[r["supplier_id"]]["name"],
                        "stockout_week_launchpilot": r["stockout_week_launchpilot"],
                        "stockout_week_baseline": r["stockout_week_naive_excel"],
                        "min_projected_stock": r["min_projected_stock"],
                        "severity": r["suggested_severity"] if r["stockout_week_launchpilot"] else "covered",
                        "evidence": r["evidence"]} for r in proj],
    }


# ---------------- routes ----------------

class RunBody(BaseModel):
    live: bool | None = None          # default: live when an API key is configured


class FastForwardBody(RunBody):
    until: str = "EV-019"


class DecisionBody(BaseModel):
    alert_id: int
    scenario_id: int
    decided_by: str = "Claire (demo)"
    comment: str | None = None


@app.get("/health")
@api.get("/health")
def health():
    return {"ok": True, "store": "postgres" if isinstance(store, PgStore) else "memory", "live_agents": A.claude_available()}


@api.get("/state")
def state():
    return _state()


@api.get("/projection/{component_id}")
def projection(component_id: str):
    if component_id not in T.COMP:
        raise HTTPException(404, f"unknown component {component_id}")
    seen = _seen()
    lp = dict(project(T.DB, seen, "learned")[component_id]["series"])
    base = dict(project(T.DB, seen, "naive")[component_id]["series"])
    return {"component_id": component_id, "name": T.comp_label(component_id), "launch_week": T.LAUNCH_WEEK.isoformat(),
            "series": [{"week": w, "launchpilot": lp.get(w), "baseline": base.get(w)} for w in sorted(set(lp) | set(base))]}


@api.get("/events")
def events(limit: int = 50):
    return [_event(e) for e in sorted(store.list_events(), key=lambda e: (e["ts"], e["event_id"]), reverse=True)[:limit]]


@api.post("/events/next")
def next_event(body: RunBody = RunBody()):
    with LOCK:
        seen = _seen()
        if len(seen) >= len(ALL):
            raise HTTPException(409, "the recorded scenario is finished; reset to replay it")
        run = _process(ALL[len(seen)], _live(body.live), seen)
    return {"event": _event(ALL[len(seen)]), "run": _run(run), "state": _state()}


@api.post("/fast-forward")
def fast_forward(body: FastForwardBody = FastForwardBody()):
    ids = [e["event_id"] for e in ALL]
    if body.until not in ids:
        raise HTTPException(404, f"unknown event {body.until}")
    with LOCK:
        seen = _seen()
        stop = ids.index(body.until)
        if len(seen) > stop:
            raise HTTPException(409, f"{body.until} is already processed")
        for e in ALL[len(seen):stop]:              # replay up to the target in rules mode
            _process(e, False, seen)
            seen.append(e)
        run = _process(ALL[stop], _live(body.live), seen)   # the target event live when possible
    return {"event": _event(ALL[stop]), "run": _run(run), "state": _state()}


@api.post("/reset")
def reset():
    with LOCK:
        store.reset()
        RUNS.clear()
        RECO.clear()
    return _state()


@api.get("/alerts")
def alerts():
    return [_alert(a) for a in _latest_alerts()]


@api.post("/alerts/{alert_id}/arbitrate")
def arbitrate(alert_id: int, body: RunBody = RunBody()):
    a = next((x for x in store.list_alerts() if x["alert_id"] == alert_id), None)
    if not a:
        raise HTTPException(404, f"unknown alert {alert_id}")
    with LOCK:
        if store.list_scenarios(alert_id):
            raise HTTPException(409, "scenarios already exist for this alert")
        seen = _seen()
        run = (A.arbitrate_live if _live(body.live) else A.arbitrate_rules)(store, a, seen, _now(seen))
        RUNS.append(run)
        RECO[alert_id] = run["output"]
    return {"alert": _alert(a), "run": _run(run)}


@api.post("/decisions")
def decide(body: DecisionBody):
    if not any(s["scenario_id"] == body.scenario_id for s in store.list_scenarios(body.alert_id)):
        raise HTTPException(404, "unknown scenario for this alert")
    label = next(s["label"] for s in store.list_scenarios(body.alert_id) if s["scenario_id"] == body.scenario_id)
    store.add_decision({"alert_id": body.alert_id, "scenario_id": body.scenario_id,
                        "decided_by": body.decided_by, "comment": body.comment or label})
    return decisions()


@api.get("/decisions")
def decisions():
    return [{"alert_id": d["alert_id"], "scenario_id": d["scenario_id"], "label": d.get("label") or d.get("comment"),
             "decided_by": d.get("decided_by"), "decided_at": d.get("decided_at")} for d in store.list_decisions()]


@api.get("/suppliers")
def suppliers():
    sql = store.supplier_memory_sql()
    return {"source": "sql_view" if sql else "computed",
            "suppliers": [{k: m[k] for k in ["supplier_id", "name", "announced_days", "real_mean_days", "std_days",
                                             "prudent_days", "deliveries", "late_deliveries", "evidence"]}
                          for m in T.get_supplier_memory()],
            "sql_rows": [{k: (float(v) if hasattr(v, "is_finite") else v) for k, v in r.items()} for r in sql or []]}


@api.get("/proof")
def proof():
    path = os.path.join(T.DATA, "evaluation.json")
    if not os.path.exists(path):
        raise HTTPException(404, "no evaluation yet: run python3 evaluate.py")
    ev = json.load(open(path, encoding="utf-8"))
    return {"evaluation": ev, "component_names": {c: T.comp_label(c) for c in ev.get("real_stockouts", {})}}


@api.get("/runs")
def runs():
    return [_run(r) for r in reversed(RUNS)]


app.include_router(api)
