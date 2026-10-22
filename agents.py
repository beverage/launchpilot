"""
LaunchPilot's agents.

- Watch agent        : reacts to each event in the stream, projects stock with the supplier memory, writes sourced alerts.
- Arbitration agent  : faced with an alert, costs several scenarios in euros and recommends one.

Each agent exists in two versions:
- "live"  : a Claude tool-use loop (needs ANTHROPIC_API_KEY).
- "rules" : deterministic, fast and free (fast-forward, or a demo without a key).
The UI always shows which version produced each result. Supplier messages may arrive in French; the agents answer in English.
"""
import json, os, time
from datetime import date, timedelta
import tools as T

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-sonnet-5-5"
SOURCE_LIVE, SOURCE_RULES = "Claude agent (live)", "rules (fast-forward)"


def claude_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic
    # ANTHROPIC_BASE_URL is read by the SDK automatically (useful to route through a gateway).
    return anthropic.Anthropic()


def _loop(system, user, tool_specs, handlers, store, agent_name, max_turns=10):
    """Generic agentic loop: Claude calls tools until it answers in text."""
    client = _client()
    messages = [{"role": "user", "content": user}]
    calls, t0, tin, tout, final = [], time.time(), 0, 0, ""
    for _ in range(max_turns):
        resp = client.messages.create(model=MODEL, max_tokens=1500, system=system, tools=tool_specs, messages=messages)
        tin += resp.usage.input_tokens
        tout += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        final = "".join(b.text for b in resp.content if b.type == "text")
        if not uses:
            break
        results = []
        for u in uses:
            try:
                out = handlers[u.name](**u.input)
            except Exception as ex:
                out = {"error": str(ex)}
            calls.append({"tool": u.name, "input": u.input, "output": out})
            results.append({"type": "tool_result", "tool_use_id": u.id,
                            "content": json.dumps(out, ensure_ascii=False, default=str)[:6000]})
        messages.append({"role": "user", "content": results})
    run = {"agent": agent_name, "input": user, "tool_calls": calls, "output": final,
           "latency_ms": int((time.time() - t0) * 1000), "tokens_in": tin, "tokens_out": tout, "mode": "live"}
    store.log_run(run)
    return run


# ======================= WATCH AGENT =======================

WATCH_SYSTEM = """You are LaunchPilot's watch agent, the supply copilot of a small cosmetics brand (Maison Aurore).
The Christmas gift set launches in the week of {launch}. A new event has just arrived in the stream. Supplier messages may be in French; you always answer in English.
Event types. Structured: supplier_delay, sellout_spike, capacity_drop, po_confirmed, noise. Live: supplier_email (raw text from a supplier, usually French: find the purchase order and what the supplier states, then call record_supplier_update with kind "delay" (a new promised date or a delay in days) or "confirmation" (a quantity shipped or confirmed; a quantity below the order is a partial delivery); if the email changes nothing, it is noise), po_delivered (the goods receipt is already applied to the supplier memory; run the projection to see what moved and say how the supplier's lead time used changed), supplier_insolvency (a real public notice: call get_supplier_master and compare company name and SIREN; with no match call no_new_risk with the reason "no exposure: <company> is not one of our suppliers", adding which of our suppliers share its activity_code if any, as a sector watch; with a match call supplier_exposure for that supplier and create an alert with risk_type "supplier_continuity" for each of its components: severity from severity_if_missing, stockout_week = stockout_week_if_orders_never_arrive, and the explanation sizes the exposure with the tool's figures, phrased as "if this order does not arrive", never as a prediction (a company under court protection keeps trading), noting "no qualified second source" when second_source is null, quoting the company name exactly as the notice spells it; if the matched supplier carries demo_mapping, the explanation must start with 'Demo mapping:' and say that the notice is real (company, SIREN, procedure, judgment date, court), that the supplier and its delivery history are fictional, and that nothing is implied about the real company's lead times), holiday_closure (noise unless it names one of our suppliers).
Capacity: for a capacity_drop or a sellout_spike, also call check_capacity. It says which products the contract manufacturers cannot fill (the launch gift set is filled first), from which week, how many units and how much revenue at shelf price, and what filling the overflow at the other plant would save. For each product it returns, create an alert with risk_type "capacity" on that product id: stockout_week = first_unserved_week, severity = suggested_severity, confidence = the confidence returned; the explanation names the plant, the capacity drops (cite their events), the units and euros at stake and what moving the overflow saves. A capacity alert does not replace a stockout alert on a component.
Steps:
1. Classify the event: potential impact on component supply, or noise. If it is noise, call mark_noise and stop. For a supplier_email, extract first (record_supplier_update), then continue.
2. Call run_projection. A supplier's announced lead time is NEVER taken at face value: LaunchPilot draws each lead time from the supplier's delivered history and returns a probability of stockout (median week, probability by launch + 1 week, probability before year end). Compare with the "without memory" view: an attentive planner who reads the same messages but believes the announced lead times. Explain the gap with the supplier memory.
3. For every component whose suggested_severity is high or medium and whose stockout is new, or earlier than an alert already open, call create_alert with the median week. Severity = suggested_severity (high: at least a 50% probability of a stockout no later than one week after launch; medium: a stockout is likely before year end). Confidence = the confidence field returned (a probability), never an invented number.
4. The explanation is at most two sentences, in English, and cites the evidence in table:id form found in the tool outputs. When a supplier's memory carries demo_mapping, any lead-time figure you quote for it is followed by "(fictional delivery history)".
5. If nothing changes, call no_new_risk.
Forbidden: inventing a figure absent from the tools, creating an alert without evidence, repeating an identical alert.
End with a one-sentence summary."""

WATCH_TOOLS = [
    {"name": "run_projection", "description": "Projects each component's stock to the end of December: the LaunchPilot view (supplier memory, 200 draws of actual lead times: median stockout week, probability by launch + 1 week, probability before year end) and the no-memory view (announced lead times, messages read). Also returns the suggested severity, the confidence (a probability) and the evidence.",
     "input_schema": {"type": "object", "properties": {"component_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional: restrict to these components"}}}},
    {"name": "get_supplier_memory", "description": "A supplier's actual reliability learned from the delivery history (announced vs actual lead time, standard deviation, late deliveries).",
     "input_schema": {"type": "object", "properties": {"supplier_id": {"type": "string"}}}},
    {"name": "get_open_pos", "description": "Open purchase orders for a component.",
     "input_schema": {"type": "object", "properties": {"component_id": {"type": "string"}}, "required": ["component_id"]}},
    {"name": "create_alert", "description": "Creates a stockout alert.",
     "input_schema": {"type": "object", "properties": {
         "component_id": {"type": "string"}, "stockout_week": {"type": "string", "description": "YYYY-MM-DD (a Monday)"},
         "severity": {"type": "string", "enum": ["high", "medium", "low"]}, "confidence": {"type": "number"},
         "explanation": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}},
         "risk_type": {"type": "string", "enum": ["stockout_component", "supplier_continuity", "capacity"], "description": "stockout_component (default) for a projected stockout; supplier_continuity for a legal-status risk on a supplier, which does not replace or block a stockout alert on the same component; capacity for a product its contract manufacturer cannot fill (component_id is then the product id)"}},
         "required": ["component_id", "stockout_week", "severity", "confidence", "explanation", "evidence"]}},
    {"name": "record_supplier_update", "description": "Records what a supplier email states about a purchase order, as a structured event the projection understands. kind=delay needs new_promised_date (YYYY-MM-DD) or announced_delay_days; kind=confirmation needs confirmed_qty (units shipped or confirmed) and optionally confirmed_date.",
     "input_schema": {"type": "object", "properties": {
         "po_id": {"type": "string"}, "kind": {"type": "string", "enum": ["delay", "confirmation"]},
         "new_promised_date": {"type": "string"}, "announced_delay_days": {"type": "integer"},
         "confirmed_qty": {"type": "integer"}, "confirmed_date": {"type": "string"}},
         "required": ["po_id", "kind"]}},
    {"name": "get_supplier_master", "description": "Our suppliers (id, name, category, SIREN when known), to check exposure to a public notice.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "supplier_exposure", "description": "What-if for a supplier named in a public notice: its open orders never arrive (delivered ones stay in stock). Per component: open orders, units still on order vs received, stockout week as is and if the orders never arrive, extra units short, lost revenue at shelf price, second source if any, severity if missing, evidence rows.",
     "input_schema": {"type": "object", "properties": {"supplier_id": {"type": "string"}}, "required": ["supplier_id"]}},
    {"name": "check_capacity", "description": "Contract-manufacturer capacity against demand, with the capacity drops and sell-out spikes known so far. Per product its plant cannot fill: first week short, units and revenue lost at shelf price (gift set filled first), units and revenue still lost if the overflow is filled at the other plant, suggested severity, confidence, evidence.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "mark_noise", "description": "The event has no supply impact.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "no_new_risk", "description": "The event was analysed; no new alert is needed.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
]


def _existing(store, cid):
    return [a for a in store.list_alerts() if a["item_id"] == cid]


SEV_RANK = {"low": 0, "medium": 1, "high": 2}


def _should_alert(store, cid, week, risk_type="stockout_component", trigger=None, severity=None):
    """Each risk type dedups only against itself: a stockout alert moves only to an earlier week; a supplier-continuity
    alert is raised once per notice; a capacity alert is raised again only when it gets earlier or more severe."""
    ex = [a for a in _existing(store, cid) if (a.get("risk_type") or "stockout_component") == risk_type]
    if not ex:
        return True
    if risk_type == "capacity":
        last = ex[0]
        return (SEV_RANK.get(severity, 0) > SEV_RANK.get(last["severity"], 0)
                or bool(week and last["predicted_stockout_week"] and week < last["predicted_stockout_week"]))
    if risk_type != "stockout_component":
        return not any(a.get("trigger_event_id") == trigger for a in ex)
    last = ex[0]["predicted_stockout_week"]
    return bool(week and last and week < last)


def watch_live(store, event, events_seen):
    created = []

    def create_alert(component_id, stockout_week, severity, confidence, explanation, evidence, risk_type="stockout_component"):
        if component_id not in T.COMP and not (risk_type == "capacity" and component_id in T.PROD):
            return {"error": "unknown component (a capacity alert takes a product id)"}
        if not _should_alert(store, component_id, stockout_week, risk_type, event["event_id"], severity):
            return {"status": "ignored: an identical or more severe alert of this risk type is already open"}
        aid = store.add_alert({"source": SOURCE_LIVE, "trigger_event_id": event["event_id"], "item_id": component_id, "risk_type": risk_type,
                               "predicted_stockout_week": stockout_week or None, "severity": severity, "confidence": confidence,
                               "explanation": explanation, "evidence": evidence})
        created.append(aid)
        return {"status": "created", "alert_id": aid}

    def record_supplier_update(po_id, kind, new_promised_date=None, announced_delay_days=None, confirmed_qty=None, confirmed_date=None):
        po = next((x for x in T.DB["purchase_orders"] if x["po_id"] == po_id), None)
        if not po:
            return {"error": f"unknown purchase order {po_id}"}
        if kind == "delay":
            if not new_promised_date and announced_delay_days is None:
                return {"error": "give new_promised_date or announced_delay_days"}
            base = T._d(po["promised_date"])
            if announced_delay_days is None:
                announced_delay_days = (T._d(new_promised_date) - base).days
            if not new_promised_date:
                new_promised_date = (base + timedelta(days=int(announced_delay_days))).isoformat()
            etype, payload = "supplier_delay", {"po_id": po_id, "supplier_id": po["supplier_id"], "component_id": po["component_id"],
                                                "new_promised_date": new_promised_date, "announced_delay_days": int(announced_delay_days)}
        elif kind == "confirmation":
            if confirmed_qty is None:
                return {"error": "give confirmed_qty"}
            etype, payload = "po_confirmed", {"po_id": po_id, "component_id": po["component_id"],
                                              "confirmed_date": confirmed_date or po["promised_date"], "confirmed_qty": int(confirmed_qty)}
        else:
            return {"error": "kind must be delay or confirmation"}
        mirrors = event["payload"].get("mirrors")
        duplicate = bool(mirrors and any(e["event_id"] == mirrors for e in store.list_events()))   # structured twin already applied
        payload.update({"derived_from": event["event_id"]}, **({"mirrors": mirrors} if mirrors else {}), **({"superseded": True} if duplicate else {}))
        derived = {"event_id": f"{event['event_id']}/derived", "ts": event["ts"], "event_type": etype, "payload": payload}
        store.add_event(derived, processed=True)
        if not duplicate:
            events_seen.append(derived)          # the projection in this run sees it
        return {"status": "recorded", "derived_event": derived, "already_known_from_structured_feed": duplicate}

    handlers = {
        "run_projection": lambda component_ids=None: T.run_projection(events_seen, component_ids),
        "get_supplier_memory": lambda supplier_id=None: T.get_supplier_memory(supplier_id),
        "get_open_pos": lambda component_id: T.get_open_pos(component_id),
        "record_supplier_update": record_supplier_update,
        "get_supplier_master": lambda: T.get_supplier_master(),
        "supplier_exposure": lambda supplier_id: T.supplier_exposure(events_seen, supplier_id),
        "check_capacity": lambda: T.capacity_check(events_seen),
        "create_alert": create_alert,
        "mark_noise": lambda reason: {"status": "ok"},
        "no_new_risk": lambda reason: {"status": "ok"},
    }
    existing = [{"component": a["item_id"], "stockout_week": a["predicted_stockout_week"], "severity": a["severity"]}
                for a in store.list_alerts()]
    shown = dict(event, payload={k: v for k, v in event["payload"].items() if k != "mirrors"})   # the agent never sees the hint
    user = (f"Simulated date: {event['ts'][:10]}.\nEvent: {json.dumps(shown, ensure_ascii=False)}\n"
            f"Alerts already open: {json.dumps(existing, ensure_ascii=False)}")
    run = _loop(WATCH_SYSTEM.format(launch=T.LAUNCH_WEEK), user, WATCH_TOOLS, handlers, store, "watch")
    run["alerts_created"] = created
    return run


def watch_rules(store, event, events_seen):
    """Deterministic version of the watch agent (fast-forward)."""
    created = []
    if event["event_type"] != "noise":
        for r in T.run_projection(events_seen):
            wk = r["stockout_week_launchpilot"]
            if not wk or not r["suggested_severity"] or not _should_alert(store, r["component_id"], wk):
                continue
            m = T.get_supplier_memory(r["supplier_id"])[0]
            without = r["stockout_week_without_memory"]
            txt = (f"{r['name']} is likely to run out in the week of {wk} ({r['p_stockout_by_launch_plus_1wk']:.0%} probability by launch + 1 week, "
                   f"{r['p_stockout_before_end_of_year']:.0%} before year end)"
                   + ("; without supplier memory, a planner reading the same messages sees no stockout." if not without
                      else "; a planner without memory sees it too, memory changes nothing here." if without == wk
                      else f"; without supplier memory, it would only show on {without}.")
                   + f" {m['name']} announces {m['announced_days']} days but delivers in {m['real_mean_days']} days on average over {m['deliveries']} deliveries (lead time used: {m['typical_days']} days"
                   + ("; fictional delivery history, see the demo mapping" if m.get("demo_mapping") else "") + ").")
            aid = store.add_alert({"source": SOURCE_RULES, "trigger_event_id": event["event_id"],
                                   "item_id": r["component_id"], "predicted_stockout_week": wk,
                                   "severity": r["suggested_severity"], "confidence": r["confidence"], "explanation": txt,
                                   "evidence": r["evidence"]})
            created.append(aid)
    if event["event_type"] in ("capacity_drop", "sellout_spike"):
        for c in T.capacity_check(events_seen):
            wk, sev = c["first_unserved_week"], c["suggested_severity"]
            if not _should_alert(store, c["product_id"], wk, "capacity", event["event_id"], sev):
                continue
            drops = ", ".join(e for e in c["evidence"] if e.startswith("events:"))
            n = lambda x: f"{x:,}".replace(",", " ")
            txt = (f"{c['name']} cannot be filled at {c['plant_name']} from the week of {wk}: {n(c['units_unserved'])} units short, "
                   f"{n(c['lost_revenue_eur'])} € at shelf price, because the plant's capacity drops ({drops}) leave too little once the launch gift set is filled first. "
                   f"Filling the overflow at {', '.join(c['overflow_plants'])} would leave {n(c['units_unserved_if_moved'])} short "
                   f"({n(c['lost_revenue_eur_if_moved'])} €).")
            aid = store.add_alert({"source": SOURCE_RULES, "trigger_event_id": event["event_id"], "item_id": c["product_id"],
                                   "risk_type": "capacity", "predicted_stockout_week": wk, "severity": sev,
                                   "confidence": c["confidence"], "explanation": txt, "evidence": c["evidence"]})
            created.append(aid)
    run = {"agent": "watch", "mode": "rules", "input": event["event_id"], "tool_calls": [], "output": f"{len(created)} alert(s)",
           "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "alerts_created": created}
    store.log_run(run)
    return run


# ======================= ARBITRATION AGENT =======================

ARB_SYSTEM = """You are LaunchPilot's arbitration agent, working for Claire, supply manager at Maison Aurore (a small cosmetics brand).
A stockout alert has just been raised. Goal: offer her 3 scenarios costed in euros, then recommend one. Answer in English.
Method:
1. Call cost_scenario with kind="do_nothing" to know the revenue at risk.
2. Evaluate at least: order_alt_supplier, order_main_supplier, prioritize_launch, order_alt_and_prioritize, reduce_launch. For a capacity alert (the item is a product its contract manufacturer cannot fill) the kinds are do_nothing and move_filling only. Watch the safety margin (safety_margin_days): an order that lands the very week the stock breaks, from an unreliable supplier, is risky. The lead times used are the ACTUAL lead times learned, not the announced ones.
3. Think about combinations (for example a rush order plus allocating the gift set first while waiting) and explain them.
4. Call save_scenario for the 3 scenarios you keep (best first), each with a two-sentence description that quotes the tools' figures.
5. End with your recommendation in at most 3 sentences: what you would do, why, and the question Claire has to settle. Give your confidence level.
Direct tone, short sentences. Never invent a figure."""

ARB_TOOLS = [
    {"name": "cost_scenario", "description": "Costs a scenario for a component. kind: do_nothing | order_main_supplier | order_alt_supplier | prioritize_launch | reduce_launch | order_alt_and_prioritize. Returns extra cost, lost revenue, cash tied up in stock, total impact, new stockout week, evidence.",
     "input_schema": {"type": "object", "properties": {
         "component_id": {"type": "string"}, "kind": {"type": "string"},
         "qty": {"type": "integer", "description": "Optional, quantity to order"},
         "reduction_pct": {"type": "number", "description": "Optional, % by which to scale the launch down"}},
         "required": ["component_id", "kind"]}},
    {"name": "get_supplier_memory", "description": "A supplier's actual reliability.",
     "input_schema": {"type": "object", "properties": {"supplier_id": {"type": "string"}}}},
    {"name": "save_scenario", "description": "Saves a scenario proposed to Claire.",
     "input_schema": {"type": "object", "properties": {
         "label": {"type": "string"}, "kind": {"type": "string"}, "description": {"type": "string"},
         "qty": {"type": "integer"}, "reduction_pct": {"type": "number"}},
         "required": ["label", "kind", "description"]}},
]


def _save(store, alert, s, cost, description):
    return store.add_scenario({"alert_id": alert["alert_id"], "label": s, "cost_eur": cost.get("cost_eur", 0),
                               "lost_revenue_eur": cost.get("lost_revenue_eur", 0), "stock_value_eur": cost.get("stock_value_eur", 0),
                               "description": description, "evidence_rows": cost.get("evidence_rows", [])})


def arbitrate_live(store, alert, events_seen, now):
    cid = alert["item_id"]

    def save_scenario(label, kind, description, qty=None, reduction_pct=None):
        c = T.cost_scenario(events_seen, now, cid, kind, qty, reduction_pct)
        if "error" in c:
            return c
        return {"status": "saved", "scenario_id": _save(store, alert, label, c, description)}

    handlers = {
        "cost_scenario": lambda component_id, kind, qty=None, reduction_pct=None: T.cost_scenario(events_seen, now, component_id, kind, qty, reduction_pct),
        "get_supplier_memory": lambda supplier_id=None: T.get_supplier_memory(supplier_id),
        "save_scenario": save_scenario,
    }
    item = (f"Component: {T.comp_label(cid)}, main supplier {T.supplier_of(cid)}, alternative {T.COMP[cid]['alt_supplier_id'] or 'none'}."
            if cid in T.COMP else f"Product: {T.comp_label(cid)} (capacity alert: kinds do_nothing and move_filling).")
    user = (f"Simulated date: {now}. Alert: {json.dumps({k: alert[k] for k in ['alert_id', 'item_id', 'predicted_stockout_week', 'severity', 'explanation']}, ensure_ascii=False)}\n"
            + item)
    return _loop(ARB_SYSTEM, user, ARB_TOOLS, handlers, store, "arbitration")


def arbitrate_rules(store, alert, events_seen, now):
    cid = alert["item_id"]
    kinds = (["order_alt_and_prioritize", "order_alt_supplier", "prioritize_launch", "reduce_launch", "order_main_supplier"]
             if cid in T.COMP else ["move_filling"])
    res = [T.cost_scenario(events_seen, now, cid, k) for k in kinds]
    res = [r for r in res if "error" not in r]
    res.sort(key=lambda r: (r["total_impact_eur"], -(r.get("safety_margin_days") or 0)))
    for r in res[:3]:
        _save(store, alert, r["label"], r, r["detail"])
    base = T.cost_scenario(events_seen, now, cid, "do_nothing")
    best = res[0] if res else None
    out = (f"Revenue at risk if nothing is done: {base['lost_revenue_eur']:,.0f} €. ".replace(",", " ")
           + (f"Cheapest option: {best['label']} (impact {best['total_impact_eur']:,.0f} €).".replace(",", " ") if best else ""))
    run = {"agent": "arbitration", "mode": "rules", "input": alert["alert_id"], "tool_calls": [], "output": out,
           "latency_ms": 0, "tokens_in": 0, "tokens_out": 0}
    store.log_run(run)
    return run
