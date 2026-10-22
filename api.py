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
from store import MemStore, PgStore
from strings import EN as S



class SharedPgStore(PgStore):
    """The Streamlit app (launchpilot) owns the schema and the master data in accel-pg. The API only connects:
    no schema, no CSV reload and no reset at start-up, so restarting it never touches the shared demo.
    (PgStore's bootstrap reloads the tables whenever data/ differs, so two apps on different commits would fight.)"""

    def __init__(self, url):
        self.url = url
        self._connect()


def _open_store():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return MemStore(), None
    try:
        return SharedPgStore(url), None
    except Exception as ex:  # never block the frontend
        return MemStore(), f"PostgreSQL connection failed, running in memory: {ex}"


store, store_err = _open_store()
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


def _store_kind():
    return "postgres" if isinstance(store, PgStore) else "memory"


def _live(requested):
    return A.claude_available() if requested is None else bool(requested) and A.claude_available()


# Labels for the stream event types strings.py doesn't cover yet; strings.py wins when it has one
STREAM_KINDS = {"supplier_insolvency": "🏛️ Supplier insolvency (BODACC)", "po_delivered": "📦 Delivery",
                "supplier_email": "✉️ Supplier email", "holiday_closure": "📅 Holiday closure",
                "sellout_weekly": "📊 Weekly sell-out"}
REAL_DATA_PREFIXES = ("BOD-", "HOL-")   # public data; MAIL-, DLV- and SELL- are synthetic, streamed live


def _summary(e):
    p, t = e.get("payload", {}), e["event_type"]
    sup = lambda k: T.SUP.get(p.get(k), {}).get("name", p.get(k))
    try:
        if t == "supplier_delay":       # same wording as app.py, from strings.py
            return S["feed_delay"].format(supplier=sup("supplier_id"), po=p["po_id"], days=p["announced_delay_days"])
        if t == "sellout_spike":
            return S["feed_spike"].format(product=T.PROD[p["product_id"]]["name"], factor=p["observed_vs_forecast"])
        if t == "capacity_drop":
            return S["feed_capacity"].format(plant=p["subcontractor_id"], pct=int(float(p["capacity_drop_rate"]) * 100))
        if t == "po_confirmed":
            return S["feed_confirmed"].format(po=p["po_id"], qty=p["confirmed_qty"])
        if t == "po_delivered":
            partial = str(p.get("partial")).lower() == "true"
            return (f"{p['po_id']} delivered: {p['quantity_delivered']} of {p['quantity_ordered']} units on {p['delivered_at']}"
                    + (" (partial)" if partial else ""))
        if t == "supplier_email":
            return f"Email from {p.get('from_name')} ({sup('supplier_id')}): {p.get('subject')}"
        if t == "supplier_insolvency":   # the judgment type only: the full text names people (liquidators, directors)
            where = ", ".join(x for x in (p.get("activity_label"), p.get("city")) if x)
            return f"{p.get('company_name')}{f' ({where})' if where else ''}: {str(p.get('procedure', '')).split(':')[0]}"
        if t == "sellout_weekly":
            return f"{T.PROD.get(p.get('product_id'), {}).get('name', p.get('product_id'))}, {p.get('channel')}: {p.get('units')} units against {p.get('forecast_units')} forecast"
        if t == "holiday_closure":
            return f"{p.get('name')} ({p.get('country')}, {p.get('date')})"
        if t == "noise":
            return p.get("note", "")
    except (KeyError, TypeError, ValueError):
        pass
    return json.dumps(p, ensure_ascii=False)[:160]


def _event(e):
    return {"event_id": e["event_id"], "ts": e["ts"], "event_type": e["event_type"],
            "kind_label": S["event_kind"].get(e["event_type"]) or STREAM_KINDS.get(e["event_type"], e["event_type"]),
            "summary": _summary(e),
            "payload": e.get("payload", {}), "origin": "recorded" if e["event_id"].startswith("EV-") else "live",
            "real_data": e["event_id"].startswith(REAL_DATA_PREFIXES)}


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
        "data": {"store": _store_kind(), "label": S["store_pg"] if _store_kind() == "postgres" else S["store_memory"],
                 "error": store_err, "dataset": S["dataset_value"]},
        "agents": {"live_available": A.claude_available(), "model": A.MODEL},
        "kpis": {"critical_alerts": sum(1 for a in _latest_alerts() if a["severity"] == "high"),
                 "revenue_at_risk_eur": risk},
        "components": [{"component_id": r["component_id"], "name": r["name"], "supplier_id": r["supplier_id"],
                        "supplier_name": T.SUP[r["supplier_id"]]["name"],
                        "stockout_week_launchpilot": r["stockout_week_launchpilot"],
                        "stockout_week_without_memory": r["stockout_week_without_memory"],
                        "p_stockout_by_launch_plus_1wk": r["p_stockout_by_launch_plus_1wk"],
                        "p_stockout_before_end_of_year": r["p_stockout_before_end_of_year"],
                        "confidence": r["confidence"], "min_projected_stock_p50": r["min_projected_stock_p50"],
                        "severity": r["suggested_severity"] or "covered", "evidence": r["evidence"]} for r in proj],
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
    return {"ok": True, "store": _store_kind(), "live_agents": A.claude_available()}


@api.get("/state")
def state():
    return _state()


@api.get("/projection/{component_id}")
def projection(component_id: str):
    if component_id not in T.COMP:
        raise HTTPException(404, f"unknown component {component_id}")
    cs = {k: dict(v) for k, v in T.chart_series(_seen(), component_id).items()}   # p10, p50, p90, without_memory
    weeks = sorted(set().union(*cs.values()))
    return {"component_id": component_id, "name": T.comp_label(component_id), "launch_week": T.LAUNCH_WEEK.isoformat(),
            "series": [{"week": w, **{k: v.get(w) for k, v in cs.items()}} for w in weeks]}


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
                                             "typical_days", "deliveries", "late_deliveries", "evidence"]}
                          for m in T.get_supplier_memory()],
            "sql_rows": [{k: (float(v) if hasattr(v, "is_finite") else v) for k, v in r.items()} for r in sql or []]}


@api.get("/proof")
def proof():
    path = os.path.join(T.DATA, "evaluation.json")
    if not os.path.exists(path):
        raise HTTPException(404, "no evaluation yet: run python3 evaluate.py")
    ev = json.load(open(path, encoding="utf-8"))
    return {"evaluation": ev, "component_names": {c: T.comp_label(c) for c in ev.get("demo_seed", {}).get("per_component", {})}}


@api.get("/supplier-health")
def supplier_health(include_unreached: bool = False):
    """Real BODACC notices with their registry card and our exposure, from the supplier_health view (streams side).
    By default only the notices the demo clock has reached; include_unreached=true lists every notice received."""
    if not isinstance(store, PgStore):
        return {"source": "unavailable", "error": "needs Aiven for PostgreSQL", "notices": []}
    try:
        rows = store._q("SELECT * FROM supplier_health" + ("" if include_unreached else " WHERE reached_by_demo")
                        + " ORDER BY published_at DESC")
    except Exception as ex:                       # the view lives on main's schema; never break the page over it
        return {"source": "unavailable", "error": str(ex)[:200], "notices": []}
    return {"source": "sql_view", "error": None, "notices": rows or []}


@api.get("/runs")
def runs():
    return [_run(r) for r in reversed(RUNS)]


app.include_router(api)
