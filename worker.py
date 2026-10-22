"""
LaunchPilot — the consumer of live events.

Live rows (ids that do not start with EV-) arrive in the events table from the Kafka bridge: supplier emails, goods receipts,
BODACC insolvency notices, holiday closures. drain() analyses the ones due at the demo clock, oldest first, and marks them
processed. The demo clock is the latest processed timestamp, so a live row dated today is analysed when the replay reaches today.

In rules mode (no API key) emails are left for the live agent, deliveries still update the memory, and insolvency notices get a
name-based exposure check.
"""
import tools as T
import agents as A
from strings import EN as S


def drain(store, clock_ts, live, limit=50):
    runs = []
    for row in store.list_unprocessed(clock_ts)[:limit]:
        runs.append(process_live(store, row, live))
    return runs


def process_live(store, row, live):
    t, pl = row["event_type"], row["payload"]
    seen = T.events_seen(store)
    if t == "po_delivered":
        delta = T.apply_delivery(pl["po_id"], pl["delivered_at"], pl["quantity_delivered"])
        if "error" not in delta:
            store.mark_delivered(pl["po_id"], pl["delivered_at"], int(pl["quantity_delivered"]))
        run = (A.watch_live if live else A.watch_rules)(store, row, seen)
        run["delivery"] = delta
        if not live and "error" not in delta:
            run["output"] = (f"{delta['supplier']}: {delta['lead_time_days']} days on {pl['po_id']}; lead time used "
                             f"{delta['typical_before']} -> {delta['typical_after']} days over {delta['deliveries_now']} deliveries. " + run["output"])
    elif t == "supplier_email":
        run = A.watch_live(store, row, seen) if live else _note(store, row, "supplier email left for the live agent: rules cannot read free text")
    elif t == "supplier_insolvency":
        if live:
            run = A.watch_live(store, row, seen)
        else:
            master = T.get_supplier_master()
            name = (pl.get("company_name") or "").strip().lower()
            hit = next((s for s in master if (pl.get("siren") and pl.get("siren") == s["siren"]) or name == s["name"].lower()
                        or pl.get("supplier_id") == s["supplier_id"]), None)
            same_sector = [s["name"] for s in master if pl.get("activity_code") and s["activity_code"] == pl.get("activity_code")]
            if hit:
                label = S["demo_mapping_label"].format(company=pl.get("company_name"), siren=T.siren_pretty(pl.get("siren")), procedure=pl.get("procedure"),
                                                       judgment_date=pl.get("judgment_date"), court=pl.get("court"), supplier=hit["name"]) if hit["siren"] else ""
                proj = {r["component_id"]: r for r in T.run_projection(seen)}
                created = []
                for cid in T.components_of(hit["supplier_id"]):
                    if any(a["trigger_event_id"] == row["event_id"] and a["item_id"] == cid for a in store.list_alerts()):
                        continue
                    created.append(store.add_alert({"source": A.SOURCE_RULES, "trigger_event_id": row["event_id"], "item_id": cid, "risk_type": "supplier_status",
                                                    "predicted_stockout_week": proj.get(cid, {}).get("stockout_week_launchpilot"), "severity": "medium", "confidence": None,
                                                    "explanation": (S["status_alert"].format(supplier=hit["name"], procedure=pl.get("procedure"), judgment_date=pl.get("judgment_date"), component=T.comp_label(cid)) + " " + label).strip(),
                                                    "evidence": [f"events:{row['event_id']}", f"suppliers:{hit['supplier_id']}"] + ([pl["notice_url"]] if pl.get("notice_url") else [])}))
                run = _note(store, row, f"EXPOSURE: {pl.get('company_name')} ({pl.get('procedure')}) matches {hit['name']}; {len(created)} status alert(s). {label}")
                run["alerts_created"] = created
            else:
                run = _note(store, row, f"no direct exposure: {pl.get('company_name')} ({pl.get('procedure')}) is not one of our suppliers"
                                        + (f"; same sector ({pl.get('activity_code')}) as {', '.join(same_sector)}, worth a check" if same_sector else ""))
    else:
        run = _note(store, row, f"{t}: no effect on the projection yet")
    store.mark_processed(row["event_id"])
    run["event_id"] = row["event_id"]
    return run


def _note(store, row, text):
    run = {"agent": "watch", "mode": "rules", "input": row["event_id"], "tool_calls": [], "output": text,
           "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "alerts_created": []}
    store.log_run(run)
    return run
