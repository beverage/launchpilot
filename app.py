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
    return get_store()


store, store_err = _store()
ALL = T.all_events()
if "log" not in st.session_state:
    st.session_state.log = []          # traces of the latest runs (Agent traces tab)
if "reco" not in st.session_state:
    st.session_state.reco = {}         # alert_id -> recommendation text

seen_ids = [e["event_id"] for e in store.list_events()]
seen = [e for e in ALL if e["event_id"] in seen_ids]
now = date.fromisoformat(seen[-1]["ts"][:10]) if seen else T.SIM_TODAY
live_ok = A.claude_available()


def process(event, live):
    store.add_event(event)
    s = seen + [event]
    run = (A.watch_live if live else A.watch_rules)(store, event, s)
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
    k2.metric(S["events_processed"], f"{len(seen)} / {len(ALL)}")
    k3.metric(S["critical_alerts"], len(high))
    k4.metric(S["revenue_at_risk"], eur(risk))

    c1, c2, c3, c4 = st.columns([1.2, 1.4, 1.4, 1])
    use_live = c1.toggle(S["toggle_live"], value=live_ok, disabled=not live_ok, help=S["toggle_help"])
    nxt = ALL[len(seen)] if len(seen) < len(ALL) else None
    if c2.button(S["next_event"], disabled=nxt is None, width="stretch"):
        with st.spinner(S["spinner_watch"].format(event=nxt["event_id"])):
            process(nxt, use_live)
        st.rerun()
    if c3.button(S["fast_forward"], width="stretch", disabled="EV-019" in seen_ids):
        stop = [e["event_id"] for e in ALL].index("EV-019")
        for e in ALL[len(seen):stop]:
            process(e, False)           # fast-forward in rules mode
            seen.append(e)
        with st.spinner(S["spinner_watch"].format(event="EV-019")):
            process(ALL[stop], use_live)  # the key moment live when possible
        st.rerun()
    if c4.button(S["reset"], width="stretch"):
        store.reset()
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
        if not seen:
            st.info(S["feed_empty"])
        for e in reversed(seen[-6:]):
            p = e["payload"]
            det = {"supplier_delay": lambda: S["feed_delay"].format(supplier=T.SUP[p["supplier_id"]]["name"], po=p["po_id"], days=p["announced_delay_days"]),
                   "sellout_spike": lambda: S["feed_spike"].format(product=T.PROD[p["product_id"]]["name"], factor=p["observed_vs_forecast"]),
                   "capacity_drop": lambda: S["feed_capacity"].format(plant=p["subcontractor_id"], pct=int(p["capacity_drop_rate"] * 100)),
                   "po_confirmed": lambda: S["feed_confirmed"].format(po=p["po_id"], qty=p["confirmed_qty"]),
                   "noise": lambda: p.get("note", "")}[e["event_type"]]()
            st.markdown(f"`{e['ts'][:10]}` **{EVENT_KIND[e['event_type']]}** — {det}")

        st.subheader(S["alerts_title"])
        alerts, _seen_items = [], set()
        for x in store.list_alerts():          # only the latest alert per component
            if x["item_id"] not in _seen_items:
                alerts.append(x); _seen_items.add(x["item_id"])
        alerts.sort(key=lambda x: (x["severity"] != "high", x["predicted_stockout_week"] or "9999"))
        if not alerts:
            st.caption(S["alerts_empty"])
        for a in alerts[:6]:
            icon, lab = SEV.get(a["severity"], ("⚪", a["severity"]))
            with st.container(border=True):
                st.markdown(S["alert_line"].format(icon=icon, label=lab, component=T.comp_label(a["item_id"]), week=a["predicted_stockout_week"]))
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
