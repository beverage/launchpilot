"""
LaunchPilot — interface de démo (Streamlit).
Lancement local : streamlit run app.py
Variables : DATABASE_URL (Aiven PostgreSQL, optionnel), ANTHROPIC_API_KEY (agents live, optionnel), CLAUDE_MODEL (optionnel).
"""
import json, os
from datetime import date
import pandas as pd
import altair as alt
import streamlit as st

import tools as T
import agents as A
from store import get_store

st.set_page_config(page_title="LaunchPilot", page_icon="🚀", layout="wide")

GREY, BLUE, RED, AMBER, GREEN = "#8A8F98", "#2F6FDE", "#C62828", "#B26A00", "#2E7D32"
EVENT_ICON = {"supplier_delay": "🚚 Retard fournisseur", "sellout_spike": "📈 Pic de ventes",
              "capacity_drop": "🏭 Capacité façonnier", "po_confirmed": "✅ Confirmation commande", "noise": "· Info"}
SEV = {"high": ("🔴", "Critique"), "medium": ("🟠", "À surveiller"), "low": ("🟢", "Faible")}


# ---------------- état ----------------
@st.cache_resource
def _store():
    return get_store()


store, store_err = _store()
ALL = T.all_events()
if "log" not in st.session_state:
    st.session_state.log = []          # traces des derniers runs (pour l'onglet Traces)
if "reco" not in st.session_state:
    st.session_state.reco = {}         # alert_id -> texte de recommandation

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


# ---------------- en-tête ----------------
st.title("🚀 LaunchPilot")
st.markdown("**Le copilote qui voit venir la rupture d'un lancement avant qu'elle n'arrive.** "
            "Démo : Claire, responsable supply de *Maison Aurore* (marque cosmétique fictive), prépare son coffret de Noël.")
b1, b2, b3 = st.columns(3)
b1.markdown(f"**Données** : {'🟢 ' + store.kind if not store_err else '🟠 ' + store.kind}")
b2.markdown(f"**Agents** : {'🟢 Claude live (' + A.MODEL + ')' if live_ok else '🟠 règles déterministes (pas de clé API)'}")
b3.markdown("**Jeu de données** : synthétique, scénario enregistré")
if store_err:
    st.warning(store_err)

tab_launch, tab_mem, tab_proof, tab_trace = st.tabs(["Lancement", "Mémoire fournisseur", "Preuve", "Traces des agents"])

# =================== ONGLET LANCEMENT ===================
with tab_launch:
    proj = T.run_projection(seen)
    high = [a for a in store.list_alerts() if a["severity"] == "high"]
    risk = max([T.cost_scenario(seen, now, r["component_id"], "do_nothing")["lost_revenue_eur"]
                for r in proj if r["stockout_week_launchpilot"]] or [0])
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Date simulée", now.strftime("%d/%m/%Y"))
    k2.metric("Événements traités", f"{len(seen)} / {len(ALL)}")
    k3.metric("Alertes critiques", len(high))
    k4.metric("CA à risque (composant le plus critique)", f"{risk:,.0f} €".replace(",", " "))

    c1, c2, c3, c4 = st.columns([1.2, 1.4, 1.4, 1])
    use_live = c1.toggle("Agent Claude live", value=live_ok, disabled=not live_ok,
                         help="Sans clé API, l'agent Veille tourne en version règles.")
    nxt = ALL[len(seen)] if len(seen) < len(ALL) else None
    if c2.button("▶️ Événement suivant", disabled=nxt is None, width="stretch"):
        with st.spinner(f"L'agent Veille analyse {nxt['event_id']}…"):
            process(nxt, use_live)
        st.rerun()
    if c3.button("⏩ Avance rapide jusqu'à la livraison partielle (EV-019)", width="stretch",
                 disabled="EV-019" in seen_ids):
        stop = [e["event_id"] for e in ALL].index("EV-019")
        for e in ALL[len(seen):stop]:
            process(e, False)           # avance rapide en mode règles
            seen.append(e)
        with st.spinner("L'agent Veille analyse EV-019…"):
            process(ALL[stop], use_live)  # le moment fort en live si possible
        st.rerun()
    if c4.button("↺ Réinitialiser", width="stretch"):
        store.reset()
        st.session_state.log, st.session_state.reco = [], {}
        st.rerun()

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("État des composants du coffret")
        rows = []
        for r in proj:
            wk, nv = r["stockout_week_launchpilot"], r["stockout_week_naive_excel"]
            status = (SEV[r["suggested_severity"]][0] + " " + SEV[r["suggested_severity"]][1]) if wk else "🟢 Couvert"
            rows.append({"Composant": r["name"], "Fournisseur": T.SUP[r["supplier_id"]]["name"],
                         "Rupture vue par un Excel classique": nv or "—", "Rupture vue par LaunchPilot": wk or "—",
                         "Statut": status})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        comp = st.selectbox("Projection de stock", [r["component_id"] for r in proj],
                            index=[r["component_id"] for r in proj].index("CMP-POM-01"), format_func=T.comp_label)
        from projection import project
        ln = project(T.DB, seen, "learned")[comp]["series"]
        nv = project(T.DB, seen, "naive")[comp]["series"]
        df = pd.DataFrame([{"Semaine": w, "Stock": s, "Vue": "LaunchPilot (délais réels)"} for w, s in ln] +
                          [{"Semaine": w, "Stock": s, "Vue": "Excel classique (délais annoncés)"} for w, s in nv])
        df["Semaine"] = pd.to_datetime(df["Semaine"])
        lines = alt.Chart(df).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=36)).encode(
            x=alt.X("Semaine:T", title=None), y=alt.Y("Stock:Q", title="Stock projeté (unités)"),
            color=alt.Color("Vue:N", scale=alt.Scale(range=[BLUE, GREY], domain=["LaunchPilot (délais réels)", "Excel classique (délais annoncés)"]),
                            legend=alt.Legend(orient="top", title=None, labelLimit=400)),
            tooltip=["Semaine:T", "Vue:N", alt.Tooltip("Stock:Q", format=",.0f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=RED, strokeDash=[4, 4]).encode(y="y:Q")
        launch = alt.Chart(pd.DataFrame({"x": [pd.Timestamp(T.LAUNCH_WEEK)], "t": ["Lancement"]}))
        st.altair_chart((lines + zero + launch.mark_rule(color="#444", strokeDash=[2, 2]).encode(x="x:T") +
                         launch.mark_text(align="left", dx=4, dy=-110, color="#444").encode(x="x:T", text="t:N")).properties(height=300),
                        width="stretch")

    with right:
        st.subheader("Fil d'événements")
        if not seen:
            st.info("Aucun événement pour l'instant. Clique sur « Événement suivant ».")
        for e in reversed(seen[-6:]):
            p = e["payload"]
            det = {"supplier_delay": lambda: f"{T.SUP[p['supplier_id']]['name']} décale {p['po_id']} de {p['announced_delay_days']} j",
                   "sellout_spike": lambda: f"{T.PROD[p['product_id']]['name']} : ventes ×{p['observed_vs_forecast']}",
                   "capacity_drop": lambda: f"{p['subcontractor_id']} : capacité −{int(p['capacity_drop_rate']*100)} %",
                   "po_confirmed": lambda: f"{p['po_id']} confirmée : {p['confirmed_qty']} u.",
                   "noise": lambda: p.get("note", "")}[e["event_type"]]()
            st.markdown(f"`{e['ts'][:10]}` **{EVENT_ICON[e['event_type']]}** — {det}")

        st.subheader("Alertes")
        alerts, _seen_items = [], set()
        for x in store.list_alerts():          # on n'affiche que la dernière alerte par composant
            if x["item_id"] not in _seen_items:
                alerts.append(x); _seen_items.add(x["item_id"])
        alerts.sort(key=lambda x: (x["severity"] != "high", x["predicted_stockout_week"] or "9999"))
        if not alerts:
            st.caption("Aucune alerte.")
        for a in alerts[:6]:
            icon, lab = SEV.get(a["severity"], ("⚪", a["severity"]))
            with st.container(border=True):
                st.markdown(f"{icon} **{lab} — {T.comp_label(a['item_id'])}** · rupture semaine du {a['predicted_stockout_week']}")
                st.write(a["explanation"])
                st.caption(f"Source : {a['source']} · déclenchée par {a.get('trigger_event_id')} · confiance {a.get('confidence') or '—'}")
                with st.expander("Preuves (lignes de données)"):
                    for ev in a.get("evidence", []):
                        st.markdown(f"- `{ev}`")
                if a["severity"] == "high":
                    scen = store.list_scenarios(a["alert_id"])
                    if not scen and st.button("💡 Proposer des solutions", key=f"arb{a['alert_id']}"):
                        with st.spinner("L'agent Arbitrage chiffre les scénarios…"):
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
                                m1.metric("Surcoût", f"{s['cost_eur']:,.0f} €".replace(",", " "))
                                m2.metric("CA perdu", f"{s['lost_revenue_eur']:,.0f} €".replace(",", " "))
                                m3.metric("Achat immobilisé", f"{s['stock_value_eur']:,.0f} €".replace(",", " "))
                                st.caption(s.get("description") or "")
                                if st.button("Choisir ce scénario", key=f"dec{s['scenario_id']}"):
                                    store.add_decision({"alert_id": a["alert_id"], "scenario_id": s["scenario_id"],
                                                        "decided_by": "Claire (démo)", "comment": s["label"]})
                                    st.toast("Décision journalisée")
        dec = store.list_decisions()
        if dec:
            st.subheader("Journal des décisions")
            for d in dec:
                st.markdown(f"`{d['decided_at'][:16]}` {d.get('decided_by')} → **{d.get('label') or d.get('comment')}**")

# =================== ONGLET MÉMOIRE ===================
with tab_mem:
    st.subheader("Ce que les fournisseurs annoncent vs ce qu'ils livrent vraiment")
    st.caption("Mémoire apprise sur l'historique des livraisons. C'est elle qui rend l'agent utile.")
    mem = T.get_supplier_memory()
    dm = pd.DataFrame([{"Fournisseur": m["name"], "Délai (jours)": m["announced_days"], "Mesure": "Annoncé"} for m in mem] +
                      [{"Fournisseur": m["name"], "Délai (jours)": m["real_mean_days"], "Mesure": "Réel (moyenne)"} for m in mem])
    order = [m["name"] for m in sorted(mem, key=lambda m: m["real_mean_days"] - m["announced_days"], reverse=True)]
    chart = alt.Chart(dm).mark_bar(cornerRadiusEnd=4, height=14).encode(
        y=alt.Y("Fournisseur:N", sort=order, title=None), yOffset="Mesure:N",
        x=alt.X("Délai (jours):Q"),
        color=alt.Color("Mesure:N", scale=alt.Scale(domain=["Annoncé", "Réel (moyenne)"], range=[GREY, BLUE]),
                        legend=alt.Legend(orient="top", title=None, labelLimit=400)),
        tooltip=["Fournisseur", "Mesure", "Délai (jours)"])
    labels = chart.mark_text(align="left", dx=4, color="#333").encode(text=alt.Text("Délai (jours):Q", format=".0f"))
    st.altair_chart((chart + labels).properties(height=320), width="stretch")
    sql = store.supplier_memory_sql()
    if sql:
        st.markdown("**Calculé en direct par la vue SQL `supplier_reliability` dans Aiven for PostgreSQL :**")
        st.dataframe(pd.DataFrame(sql), hide_index=True, width="stretch")
    else:
        st.dataframe(pd.DataFrame(mem).drop(columns=["evidence"]), hide_index=True, width="stretch")

# =================== ONGLET PREUVE ===================
with tab_proof:
    st.subheader("Est-ce que ça marche ? Baseline naïve vs LaunchPilot")
    st.caption("Scénario enregistré : on rejoue les 35 événements (20 perturbations, 15 bruits) et on compare à la vérité terrain du générateur. "
               "Une rupture est « détectée » si elle est annoncée à ±1 semaine de sa vraie date.")
    path = os.path.join(T.DATA, "evaluation.json")
    if os.path.exists(path):
        ev = json.load(open(path, encoding="utf-8"))
        p1, p2, p3 = st.columns(3)
        p1.metric("Ruptures détectées — Excel classique", f"{ev['naive']['detected']} / {ev['naive']['total']}")
        p2.metric("Ruptures détectées — LaunchPilot", f"{ev['learned']['detected']} / {ev['learned']['total']}")
        p3.metric("Fausses alertes (LaunchPilot)", len(ev["learned"]["false_alarms"]))
        rows = [{"Composant": T.comp_label(c), "Vraie rupture": w,
                 "Excel classique": f"{ev['naive']['per_component'][c]} j avant" if ev['naive']['per_component'].get(c) is not None else "Ratée",
                 "LaunchPilot": f"{ev['learned']['per_component'][c]} j avant" if ev['learned']['per_component'].get(c) is not None else "Ratée"}
                for c, w in ev["real_stockouts"].items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown("**Robustesse sur 11 tirages de données** : 37/44 ruptures détectées (84 %) contre 11/44 (25 %), 0 fausse alerte.")
    else:
        st.info("Lance `python3 evaluate.py` pour produire les résultats.")
    st.caption("Limites : données synthétiques ; les baisses de capacité façonnier ne sont pas encore prises en compte par le moteur de projection.")

# =================== ONGLET TRACES ===================
with tab_trace:
    st.subheader("Ce que les agents ont fait (et combien ça coûte)")
    runs = st.session_state.log
    if runs:
        live_runs = [r for r in runs if r.get("mode") == "live"]
        t1, t2, t3 = st.columns(3)
        t1.metric("Runs d'agents", len(runs))
        t2.metric("Dont Claude live", len(live_runs))
        t3.metric("Latence moyenne (live)", f"{sum(r['latency_ms'] for r in live_runs)/max(len(live_runs),1)/1000:.1f} s")
        for r in reversed(runs[-10:]):
            with st.expander(f"{r['agent']} · {r.get('mode')} · {r['latency_ms']/1000:.1f} s · {r['tokens_in']}+{r['tokens_out']} tokens"):
                st.write(r.get("output"))
                for c in r.get("tool_calls", []):
                    st.markdown(f"**{c['tool']}** `{json.dumps(c['input'], ensure_ascii=False)}`")
                    st.code(json.dumps(c["output"], ensure_ascii=False, indent=1, default=str)[:1500], language="json")
    else:
        st.caption("Aucun run pour l'instant.")
