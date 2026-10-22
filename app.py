"""
LaunchPilot — demo UI (Streamlit).
Run locally: streamlit run app.py
Environment: DATABASE_URL (Aiven PostgreSQL, optional), ANTHROPIC_API_KEY (live agents, optional), CLAUDE_MODEL (optional).
"""
import json, os
from datetime import date
import pandas as pd
import altair as alt
import streamlit as st

import tools as T
import agents as A
import worker as W
from store import get_store
from strings import EN as S

st.set_page_config(page_title="LaunchPilot", page_icon="🚀", layout="wide")

GREY, BLUE, RED, AMBER, GREEN = "#8A8F98", "#2F6FDE", "#C62828", "#B26A00", "#2E7D32"
EVENT_KIND, SEV = S["event_kind"], S["severity"]


def eur(x):
    return f"{x:,.0f} €".replace(",", " ")


# ---------------- state ----------------
@st.cache_resource
def _store():
    s, err = get_store()
    T.sync_deliveries(s)          # deliveries applied by another process live in the database
    return s, err


store, store_err = _store()
ALL = T.all_events()
if "log" not in st.session_state:
    st.session_state.log = []          # traces of the latest runs (Agent traces tab)
if "reco" not in st.session_state:
    st.session_state.reco = {}         # alert_id -> recommendation text

rows_all = store.list_events()
processed_ids = {e["event_id"] for e in rows_all if e["processed"]}
recorded_done = [e for e in ALL if e["event_id"] in processed_ids]          # progress through the recorded scenario
seen = T.events_seen(store)                                                 # what the engine knows: recorded + derived from emails
clock = max([e["ts"] for e in rows_all if e["processed"]] or [T.SIM_TODAY.isoformat()])
now = date.fromisoformat(clock[:10])
live_ok = A.claude_available()
due_now = store.list_unprocessed(clock)


def process(event, live, live_rows=None, selective=False):
    """Analyse one recorded event, after draining the live rows due by then (an email may carry the same news first).
    live_rows overrides the mode for the live rows; selective keeps the agent for emails and matching notices only."""
    for r in W.drain(store, event["ts"], live if live_rows is None else live_rows, selective=selective):
        st.session_state.log.append(r)
    twin = store.superseded_by(event["event_id"])
    if twin:
        store.add_event(dict(event, payload={**event["payload"], "superseded": True}), processed=True)
        run = {"agent": "watch", "mode": "rules", "input": event["event_id"], "tool_calls": [], "output": S["superseded_note"].format(twin=twin),
               "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "alerts_created": []}
        store.log_run(run)
    else:
        store.add_event(event)
        run = (A.watch_live if live else A.watch_rules)(store, event, T.events_seen(store) + [event])
        store.mark_processed(event["event_id"])
    st.session_state.log.append(run)
    return run


# ---------------- header ----------------
st.title(S["title"])
st.markdown(S["tagline"])
b1, b2, b3 = st.columns(3)
store_label = S["store_pg"] if store.kind == "pg" else S["store_memory"]
b1.markdown(f"**{S['hdr_data']}**: {'🟢 ' + store_label if not store_err else '🟠 ' + store_label}")
b2.markdown(f"**{S['hdr_agents']}**: {'🟢 ' + S['agents_live'].format(model=A.MODEL) if live_ok else '🟠 ' + S['agents_rules']}")
b3.markdown(f"**{S['hdr_dataset']}**: {S['dataset_value']}")
if store_err:
    st.warning(store_err)

tab_launch, tab_mem, tab_proof, tab_trace = st.tabs([S["tab_launch"], S["tab_memory"], S["tab_proof"], S["tab_traces"]])

# =================== LAUNCH TAB ===================
with tab_launch:
    proj = T.run_projection(seen)
    high = [a for a in store.list_alerts() if a["severity"] == "high"]
    risk = max([T.cost_scenario(seen, now, r["component_id"], "do_nothing")["lost_revenue_eur"]
                for r in proj if r["stockout_week_launchpilot"]] or [0])
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(S["sim_date"], now.strftime("%d/%m/%Y"))
    k2.metric(S["events_processed"], f"{len(recorded_done)} / {len(ALL)}")
    k3.metric(S["critical_alerts"], len(high))
    k4.metric(S["revenue_at_risk"], eur(risk))

    c1, c2, c3, c6, c4, c5 = st.columns([1.0, 1.0, 1.4, 1.2, 1.3, 0.7])
    use_live = c1.toggle(S["toggle_live"], value=live_ok, disabled=not live_ok, help=S["toggle_help"])
    nxt = ALL[len(recorded_done)] if len(recorded_done) < len(ALL) else None
    if c2.button(S["next_event"], disabled=nxt is None, width="stretch"):
        with st.spinner(S["spinner_watch"].format(event=nxt["event_id"])):
            process(nxt, use_live)
        st.rerun()
    if c3.button(S["fast_forward"], width="stretch", disabled="EV-019" in processed_ids):
        stop = [e["event_id"] for e in ALL].index("EV-019")
        for e in ALL[len(recorded_done):stop]:
            process(e, False)           # fast-forward in rules mode
        with st.spinner(S["spinner_watch"].format(event="EV-019")):
            process(ALL[stop], use_live)  # the key moment live when possible
        st.rerun()
    if c6.button(S["fast_forward_today"], width="stretch", disabled=len(recorded_done) >= len(ALL), help=S["fast_forward_today_help"]):
        with st.spinner(S["spinner_today"]):
            for e in ALL[len(recorded_done):]:
                process(e, False, live_rows=use_live, selective=True)   # recorded story in rules mode; live rows selectively live
            for r in W.drain(store, ALL[-1]["ts"], use_live, selective=True):
                st.session_state.log.append(r)
        st.rerun()
    if c4.button(S["live_due"].format(n=len(due_now)), width="stretch", disabled=not due_now, help=S["live_due_help"]):
        with st.spinner(S["spinner_live"].format(n=len(due_now))):
            for r in W.drain(store, clock, use_live):
                st.session_state.log.append(r)
        st.rerun()
    if c5.button(S["reset"], width="stretch"):
        store.reset()
        T.reset_deliveries()
        st.session_state.log, st.session_state.reco = [], {}
        st.rerun()

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader(S["components_title"])
        rows = []
        for r in proj:
            wk, nv, sev = r["stockout_week_launchpilot"], r["stockout_week_without_memory"], r["suggested_severity"]
            status = (SEV[sev][0] + " " + SEV[sev][1]) if sev else S["covered"]
            rows.append({S["col_component"]: r["name"], S["col_supplier"]: T.SUP[r["supplier_id"]]["name"],
                         S["col_without_memory"]: nv or "—", S["col_launchpilot"]: wk or "—",
                         S["col_p_launch"]: f"{r['p_stockout_by_launch_plus_1wk']:.0%}", S["col_status"]: status})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        comp = st.selectbox(S["projection_select"], [r["component_id"] for r in proj],
                            index=[r["component_id"] for r in proj].index("CMP-POM-01"), format_func=T.comp_label)
        cs = T.chart_series(seen, comp)
        LP, NM = S["legend_lp"], S["legend_nm"]
        df = pd.DataFrame([{"Week": w, "Stock": s, "View": LP} for w, s in cs["p50"]] +
                          [{"Week": w, "Stock": s, "View": NM} for w, s in cs["without_memory"]])
        df["Week"] = pd.to_datetime(df["Week"])
        band = pd.DataFrame([{"Week": w, "p10": lo, "p90": hi} for (w, lo), (_, hi) in zip(cs["p10"], cs["p90"])])
        band["Week"] = pd.to_datetime(band["Week"])
        area = alt.Chart(band).mark_area(opacity=0.18, color=BLUE).encode(x="Week:T", y="p10:Q", y2="p90:Q")
        lines = alt.Chart(df).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=36)).encode(
            x=alt.X("Week:T", title=None), y=alt.Y("Stock:Q", title=S["y_axis"]),
            color=alt.Color("View:N", scale=alt.Scale(range=[BLUE, GREY], domain=[LP, NM]),
                            legend=alt.Legend(orient="top", title=None, labelLimit=400)),
            tooltip=["Week:T", "View:N", alt.Tooltip("Stock:Q", format=",.0f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=RED, strokeDash=[4, 4]).encode(y="y:Q")
        launch = alt.Chart(pd.DataFrame({"x": [pd.Timestamp(T.LAUNCH_WEEK)], "t": [S["launch_label"]]}))
        st.altair_chart((area + lines + zero + launch.mark_rule(color="#444", strokeDash=[2, 2]).encode(x="x:T") +
                         launch.mark_text(align="left", dx=4, dy=-110, color="#444").encode(x="x:T", text="t:N")).properties(height=300),
                        width="stretch")
        st.caption(S["chart_caption"])

    with right:
        st.subheader(S["feed_title"])
        feed = sorted([e for e in rows_all if e["processed"] and not e["event_id"].endswith("/derived")], key=lambda e: (e["ts"], e["event_id"]))
        if not feed:
            st.info(S["feed_empty"])
        for e in reversed(feed[-8:]):
            p = e["payload"]
            det = {"supplier_delay": lambda: S["feed_delay"].format(supplier=T.SUP[p["supplier_id"]]["name"], po=p["po_id"], days=p["announced_delay_days"]),
                   "sellout_spike": lambda: S["feed_spike"].format(product=T.PROD[p["product_id"]]["name"], factor=p["observed_vs_forecast"]),
                   "capacity_drop": lambda: S["feed_capacity"].format(plant=p["subcontractor_id"], pct=int(p["capacity_drop_rate"] * 100)),
                   "po_confirmed": lambda: S["feed_confirmed"].format(po=p["po_id"], qty=p["confirmed_qty"]),
                   "noise": lambda: p.get("note", ""),
                   "supplier_email": lambda: S["feed_email"].format(from_name=p.get("from_name", ""), subject=p.get("subject", "")),
                   "po_delivered": lambda: S["feed_delivery"].format(po=p["po_id"], qty=p["quantity_delivered"], partial=S["feed_partial"] if p.get("partial") else ""),
                   "supplier_insolvency": lambda: S["feed_insolvency"].format(company=p.get("company_name", ""), procedure=p.get("procedure", "")),
                   }.get(e["event_type"], lambda: S["feed_other"].format(kind=e["event_type"]))()
            st.markdown(f"`{e['ts'][:10]}` **{EVENT_KIND.get(e['event_type'], '•')}** — {det}")

        st.subheader(S["alerts_title"])
        alerts, _seen_items = [], set()
        for x in store.list_alerts():          # the latest alert per component and risk type (stockout, supplier continuity)
            key = (x["item_id"], x.get("risk_type") or "stockout_component")
            if key not in _seen_items:
                alerts.append(x); _seen_items.add(key)
        alerts.sort(key=lambda x: (x["severity"] != "high", x["predicted_stockout_week"] or "9999"))
        if not alerts:
            st.caption(S["alerts_empty"])
        for a in alerts[:6]:
            icon, lab = SEV.get(a["severity"], ("⚪", a["severity"]))
            with st.container(border=True):
                st.markdown(S["alert_line"].format(icon=icon, label=lab, component=T.comp_label(a["item_id"]), week=a["predicted_stockout_week"] or S["no_week"]))
                st.write(a["explanation"])
                st.caption(S["alert_source"].format(source=a["source"], event=a.get("trigger_event_id"), confidence=a.get("confidence") or "—"))
                with st.expander(S["evidence"]):
                    for ev in a.get("evidence", []):
                        st.markdown(f"- `{ev}`")
                if a["severity"] == "high":
                    scen = store.list_scenarios(a["alert_id"])
                    if not scen and st.button(S["propose"], key=f"arb{a['alert_id']}"):
                        with st.spinner(S["spinner_arb"]):
                            run = (A.arbitrate_live if use_live else A.arbitrate_rules)(store, a, seen, now)
                        st.session_state.log.append(run)
                        st.session_state.reco[a["alert_id"]] = run["output"]
                        st.rerun()
                    if scen:
                        if a["alert_id"] in st.session_state.reco:
                            st.success(st.session_state.reco[a["alert_id"]])
                        for s in scen:
                            with st.container(border=True):
                                st.markdown(f"**{s['label']}**")
                                m1, m2, m3 = st.columns(3)
                                m1.metric(S["extra_cost"], eur(s["cost_eur"]))
                                m2.metric(S["lost_revenue"], eur(s["lost_revenue_eur"]))
                                m3.metric(S["cash_tied"], eur(s["stock_value_eur"]))
                                st.caption(s.get("description") or "")
                                if st.button(S["choose"], key=f"dec{s['scenario_id']}"):
                                    store.add_decision({"alert_id": a["alert_id"], "scenario_id": s["scenario_id"],
                                                        "decided_by": S["decided_by"], "comment": s["label"]})
                                    st.toast(S["decision_logged"])
        dec = store.list_decisions()
        if dec:
            st.subheader(S["decisions_title"])
            for d in dec:
                st.markdown(f"`{d['decided_at'][:16]}` {d.get('decided_by')} → **{d.get('label') or d.get('comment')}**")

# =================== MEMORY TAB ===================
with tab_mem:
    st.subheader(S["memory_title"])
    st.caption(S["memory_caption"])
    mem = T.get_supplier_memory()
    SUPP, DAYS, MEAS = S["mem_supplier"], S["mem_days"], S["mem_measure"]
    dm = pd.DataFrame([{SUPP: m["name"], DAYS: m["announced_days"], MEAS: S["mem_announced"]} for m in mem] +
                      [{SUPP: m["name"], DAYS: m["real_mean_days"], MEAS: S["mem_actual"]} for m in mem])
    order = [m["name"] for m in sorted(mem, key=lambda m: m["real_mean_days"] - m["announced_days"], reverse=True)]
    chart = alt.Chart(dm).mark_bar(cornerRadiusEnd=4, height=14).encode(
        y=alt.Y(f"{SUPP}:N", sort=order, title=None), yOffset=f"{MEAS}:N",
        x=alt.X(f"{DAYS}:Q"),
        color=alt.Color(f"{MEAS}:N", scale=alt.Scale(domain=[S["mem_announced"], S["mem_actual"]], range=[GREY, BLUE]),
                        legend=alt.Legend(orient="top", title=None, labelLimit=400)),
        tooltip=[SUPP, MEAS, DAYS])
    labels = chart.mark_text(align="left", dx=4, color="#333").encode(text=alt.Text(f"{DAYS}:Q", format=".0f"))
    st.altair_chart((chart + labels).properties(height=320), width="stretch")
    for m in T.demo_mappings():
        st.caption(S["demo_mapping_caption"].format(supplier=m["name"], siren=T.siren_pretty(m["siren"])))
    sql = store.supplier_memory_sql()
    if sql:
        st.markdown(S["memory_sql"])
        st.dataframe(pd.DataFrame(sql), hide_index=True, width="stretch")
    else:
        st.dataframe(pd.DataFrame(mem).drop(columns=["evidence"]), hide_index=True, width="stretch")

# =================== PROOF TAB ===================
with tab_proof:
    st.subheader(S["proof_title"])
    st.caption(S["proof_caption"])
    path = os.path.join(T.DATA, "evaluation.json")
    if os.path.exists(path):
        ev = json.load(open(path, encoding="utf-8"))
        wm, lp = ev["without_memory"], ev["launchpilot"]
        p1, p2, p3, p4 = st.columns(4)
        p1.metric(S["proof_dated_nm"], f"{wm['detected']} / {wm['total']}")
        p2.metric(S["proof_dated_lp"], f"{lp['detected']} / {lp['total']}")
        p3.metric(S["proof_wrong"], lp["wrong_by_more_than_1wk"],
                  delta=S["proof_wrong_delta"].format(delta=lp["wrong_by_more_than_1wk"] - wm["wrong_by_more_than_1wk"]), delta_color="inverse")
        p4.metric(S["proof_false"], lp["false_alarms"])
        st.caption(S["proof_seeds"].format(seeds=ev["seeds"], lead_lp=lp["mean_lead_days"], lead_nm=wm["mean_lead_days"]))
        demo = ev["demo_seed"]
        st.markdown(S["proof_demo"].format(seed=demo["seed"]))
        ahead = lambda d: S["proof_days_ahead"].format(days=d) if d is not None else S["proof_missed"]
        rows = [{S["col_component"]: T.comp_label(c), S["proof_col_truth"]: r["truth"],
                 S["proof_col_nm"]: ahead(r.get("lead_days_without_memory")), S["proof_col_lp"]: ahead(r.get("lead_days_launchpilot")),
                 S["proof_col_p"]: f"{r['p_by_launch_plus_1wk']:.0%}"}
                for c, r in demo["per_component"].items() if r["truth"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info(S["proof_missing"])
    st.caption(S["proof_limits"])

    # ---- cost and latency per processed event (C3), read live from the database ----
    st.subheader(S["cost_title"])
    stats = store.run_stats()
    rows = stats["rows"]
    usd = lambda x: "—" if x is None else (f"{x*100:.1f} ¢" if x < 0.1 else f"{x:.2f} $")
    live_rows = [r for r in rows if r["live"]]
    live_runs = sum(r["runs"] for r in live_rows)
    total_cost = sum((T.cost_usd(r["sum_in"], r["sum_out"], A.MODEL) or 0) for r in live_rows)
    by_agent = {r["agent"]: r for r in live_rows}
    m1, m2, m3 = st.columns(3)
    for col, key, label in ((m1, "watch", S["cost_live_watch"]), (m2, "arbitration", S["cost_live_arb"])):
        r = by_agent.get(key)
        col.metric(label, S["cost_value"].format(sec=r["p50_ms"] / 1000, usd=usd(T.cost_usd(r["avg_in"], r["avg_out"], A.MODEL))) if r else S["cost_none"])
    m3.metric(S["cost_per_event"], usd(total_cost / stats["events_analysed"]) if stats["events_analysed"] else "—")
    price = T.PRICE_PER_MTOK.get(A.MODEL, (None, None))
    st.caption(S["cost_caption"].format(events=stats["events_analysed"], runs=sum(r["runs"] for r in rows), live=live_runs,
                                        model=A.MODEL, p_in=price[0], p_out=price[1]))
    if rows:
        table = [{S["cost_col_agent"]: S.get(f"cost_agent_{r['agent']}", r["agent"]),
                  S["cost_col_mode"]: S["cost_mode_live"] if r["live"] else S["cost_mode_rules"], S["cost_col_runs"]: r["runs"],
                  S["cost_col_p50"]: f"{r['p50_ms'] / 1000:.1f} s", S["cost_col_max"]: f"{r['max_ms'] / 1000:.1f} s",
                  S["cost_col_tokens"]: f"{r['avg_in']:,.0f} + {r['avg_out']:,.0f}".replace(",", " ") if r["live"] else "0",
                  S["cost_col_cost"]: usd(T.cost_usd(r["avg_in"], r["avg_out"], A.MODEL)) if r["live"] else "0",
                  S["cost_col_total"]: usd(T.cost_usd(r["sum_in"], r["sum_out"], A.MODEL)) if r["live"] else "0"} for r in rows]
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")

# =================== TRACES TAB ===================
with tab_trace:
    st.subheader(S["traces_title"])
    runs = st.session_state.log
    if runs:
        live_runs = [r for r in runs if r.get("mode") == "live"]
        t1, t2, t3 = st.columns(3)
        t1.metric(S["traces_runs"], len(runs))
        t2.metric(S["traces_live"], len(live_runs))
        t3.metric(S["traces_latency"], f"{sum(r['latency_ms'] for r in live_runs)/max(len(live_runs),1)/1000:.1f} s")
        for r in reversed(runs[-10:]):
            with st.expander(S["traces_row"].format(agent=r["agent"], mode=r.get("mode"), latency=r["latency_ms"] / 1000, tin=r["tokens_in"], tout=r["tokens_out"])):
                st.write(r.get("output"))
                for c in r.get("tool_calls", []):
                    st.markdown(f"**{c['tool']}** `{json.dumps(c['input'], ensure_ascii=False)}`")
                    st.code(json.dumps(c["output"], ensure_ascii=False, indent=1, default=str)[:1500], language="json")
    else:
        st.caption(S["traces_empty"])
