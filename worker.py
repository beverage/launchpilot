"""
LaunchPilot — the consumer of live events.

Live rows (ids that do not start with EV-) arrive in the events table from the Kafka bridge: supplier emails, goods receipts,
BODACC insolvency notices, holiday closures, retailer order books. drain() analyses the ones due at the demo clock, oldest first, and marks them
processed. The demo clock is the latest processed timestamp, so a live row dated today is analysed when the replay reaches today.

In rules mode (no API key) emails are left for the live agent, deliveries still update the memory, and insolvency notices get a
name-based exposure check.
"""
import tools as T
import agents as A
from strings import EN as S


def drain(store, clock_ts, live, limit=50, selective=False):
    """selective=True keeps the live agent for the rows where it adds something (supplier emails, insolvency notices that
    match one of our suppliers) and uses rules for the rest, so a long fast-forward stays quick."""
    runs = []
    for row in store.list_unprocessed(clock_ts)[:limit]:
        use_live = live and (not selective or row["event_type"] == "supplier_email"
                             or (row["event_type"] == "supplier_insolvency" and matches_supplier(row["payload"])))
        runs.append(process_live(store, row, use_live))
    return runs


def matches_supplier(pl):
    name = (pl.get("company_name") or "").strip().lower()
    return any((pl.get("siren") and pl.get("siren") == s["siren"]) or name == s["name"].lower() or pl.get("supplier_id") == s["supplier_id"]
               for s in T.get_supplier_master())


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
                exposure = {x["component_id"]: x for x in T.supplier_exposure(seen, hit["supplier_id"])}
                created = []
                for cid in T.components_of(hit["supplier_id"]):
                    if any(a["trigger_event_id"] == row["event_id"] and a["item_id"] == cid for a in store.list_alerts()):
                        continue
                    x = exposure.get(cid)
                    text = S["status_alert"].format(supplier=hit["name"], procedure=pl.get("procedure"), judgment_date=pl.get("judgment_date"), component=T.comp_label(cid))
                    week, severity, evidence = proj.get(cid, {}).get("stockout_week_launchpilot"), "medium", []
                    if x:
                        fmt = lambda n: f"{n:,}".replace(",", " ")
                        lost = f"{x['lost_revenue_eur_if_missing'] / 1e6:.2f} M€" if x["lost_revenue_eur_if_missing"] >= 1e6 else f"{x['lost_revenue_eur_if_missing'] / 1e3:,.0f} k€".replace(",", " ")
                        orders = ", ".join(f"{o['po_id']} {fmt(o['qty'])} units promised {o['promised_date']}" for o in x["open_orders"])
                        text += " " + (S["exposure_text"].format(open_qty=fmt(x["open_qty"]), total=fmt(x["open_qty"] + x["received_since_snapshot_qty"]), component=x["name"], supplier=hit["name"], orders=orders,
                                                              week_without=x["stockout_week_if_orders_never_arrive"], week_as_is=x["stockout_week_as_is"], extra=fmt(x["extra_units_short"]), lost=lost)
                                       if x["stockout_week_as_is"] and x["stockout_week_if_orders_never_arrive"] else
                                       S["exposure_no_stockout"].format(component=x["name"], week_without=x["stockout_week_if_orders_never_arrive"], extra=fmt(x["extra_units_short"]), lost=lost))
                        if not x["second_source"]:
                            text += " " + S["exposure_no_second_source"]
                        week, severity, evidence = x["stockout_week_if_orders_never_arrive"] or week, x["severity_if_missing"] or "medium", x["evidence"]
                    created.append(store.add_alert({"source": A.SOURCE_RULES, "trigger_event_id": row["event_id"], "item_id": cid, "risk_type": "supplier_continuity",
                                                    "predicted_stockout_week": week, "severity": severity, "confidence": None,
                                                    "explanation": (text + " " + label).strip(),
                                                    "evidence": [f"events:{row['event_id']}", f"suppliers:{hit['supplier_id']}"] + evidence + ([pl["notice_url"]] if pl.get("notice_url") else [])}))
                run = _note(store, row, f"EXPOSURE: {pl.get('company_name')} ({pl.get('procedure')}) matches {hit['name']}; {len(created)} status alert(s). {label}")
                run["alerts_created"] = created
            else:
                run = _note(store, row, f"no direct exposure: {pl.get('company_name')} ({pl.get('procedure')}) is not one of our suppliers"
                                        + (f"; same sector ({pl.get('activity_code')}) as {', '.join(same_sector)}, worth a check" if same_sector else ""))
    elif t == "channel_orders":
        ch = T.orders_to_demand_change(pl)
        if "error" in ch:
            run = _note(store, row, f"order book not read: {ch['error']}")
        else:
            mirrors = pl.get("mirrors")
            duplicate = bool(mirrors and any(e["event_id"] == mirrors for e in store.list_events()))   # structured twin already applied
            derived = {"event_id": f"{row['event_id']}/derived", "ts": row["ts"], "event_type": "sellout_spike",
                       "payload": {"product_id": ch["product_id"], "channel": ch["channel"], "observed_vs_forecast": ch["observed_vs_forecast"],
                                   "weeks_affected": ch["weeks_affected"], "derived_from": row["event_id"],
                                   **({"mirrors": mirrors} if mirrors else {}), **({"superseded": True} if duplicate else {})}}
            store.add_event(derived, processed=True)
            head = (f"Order book: {ch['expected_units']} units of {T.comp_label(ch['product_id'])} expected against {ch['forecast_units']} "
                    f"forecast over {len(ch['weeks_affected'])} weeks (x{ch['observed_vs_forecast']}). ")
            if duplicate:
                run = _note(store, row, head + f"Already applied from the structured feed ({mirrors}).")
            else:
                run = (A.watch_live if live else A.watch_rules)(store, derived, T.events_seen(store))
                run["output"] = head + run["output"]
    elif t == "holiday_closure":
        n = T.sync_holidays(store)
        run = _note(store, row, f"calendar updated: {pl.get('name', 'closure')} on {pl.get('start_date') or pl.get('date')} ({pl.get('kind', 'public_holiday')}); {n} live holiday dates in the delivery calendar")
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
