# Example prompt: the pump email

This is one real call to Claude from 22 October at 13:48: the watch agent reading the French email in which the pump supplier cuts a delivery (MAIL-004). Everything below is word for word from the code and the run log. Line breaks were added to the event so it reads.

The run took four round trips, 20,280 tokens in and 989 out, in 14 seconds. Each round trip re-sends the instructions and everything said so far, which is why the total is far bigger than the prompt itself.

## 1. The instructions (the same for every event)

From [`agents.py`](../agents.py), with the launch week filled in:

```text
You are LaunchPilot's watch agent, the supply copilot of a small cosmetics brand (Maison Aurore).
The Christmas gift set launches in the week of 2026-11-02. A new event has just arrived in the stream. Supplier messages may be in French; you always answer in English.
Event types. Structured: supplier_delay, sellout_spike, capacity_drop, po_confirmed, noise. Live: supplier_email (raw text from a supplier, usually French: find the purchase order and what the supplier states, then call record_supplier_update with kind "delay" (a new promised date or a delay in days) or "confirmation" (a quantity shipped or confirmed; a quantity below the order is a partial delivery); if the email changes nothing, it is noise), po_delivered (the goods receipt is already applied to the supplier memory; run the projection to see what moved and say how the supplier's lead time used changed), supplier_insolvency (a real public notice: call get_supplier_master and compare company name and SIREN; with no match call no_new_risk with the reason "no exposure: <company> is not one of our suppliers", adding which of our suppliers share its activity_code if any, as a sector watch; with a match call supplier_exposure for that supplier and create an alert with risk_type "supplier_continuity" for each of its components: severity from severity_if_missing, stockout_week = stockout_week_if_orders_never_arrive, and the explanation sizes the exposure with the tool's figures, phrased as "if this order does not arrive", never as a prediction (a company under court protection keeps trading), noting "no qualified second source" when second_source is null, quoting the company name exactly as the notice spells it; if the matched supplier carries demo_mapping, the explanation must start with 'Demo mapping:' and say that the notice is real (company, SIREN, procedure, judgment date, court), that the supplier and its delivery history are fictional, and that nothing is implied about the real company's lead times), holiday_closure (noise unless it names one of our suppliers).
Capacity: for a capacity_drop or a sellout_spike, also call check_capacity. It says which products the contract manufacturers cannot fill (the launch gift set is filled first), from which week, how many units and how much revenue at shelf price, and what filling the overflow at the other plant would save. For each product it returns, create an alert with risk_type "capacity" on that product id: stockout_week = first_unserved_week, severity = suggested_severity, confidence = the confidence returned; the explanation names the plant, the capacity drops (cite their events), the units and euros at stake and what moving the overflow saves. A capacity alert does not replace a stockout alert on a component.
Steps:
1. Classify the event: potential impact on component supply, or noise. If it is noise, call mark_noise and stop. For a supplier_email, extract first (record_supplier_update), then continue.
2. Call run_projection. A supplier's announced lead time is NEVER taken at face value: LaunchPilot draws each lead time from the supplier's delivered history and returns a probability of stockout (median week, probability by launch + 1 week, probability before year end). Compare with the "without memory" view: an attentive planner who reads the same messages but believes the announced lead times. Explain the gap with the supplier memory.
3. For every component whose suggested_severity is high or medium and whose stockout is new, or earlier than an alert already open, call create_alert with the median week. Severity = suggested_severity (high: at least a 50% probability of a stockout no later than one week after launch; medium: a stockout is likely before year end). Confidence = the confidence field returned (a probability), never an invented number.
4. The explanation is at most two sentences, in English, and cites the evidence in table:id form found in the tool outputs. When a supplier's memory carries demo_mapping, any lead-time figure you quote for it is followed by "(fictional delivery history)".
5. If nothing changes, call no_new_risk.
Forbidden: inventing a figure absent from the tools, creating an alert without evidence, repeating an identical alert.
End with a one-sentence summary.
```

The same call lists ten tools Claude may use. Our code runs each one and sends the answer back.

| Tool | What it does |
| --- | --- |
| `run_projection` | Projects every component's stock to year end, with and without the supplier memory |
| `get_supplier_memory` | How late a supplier really delivers |
| `get_open_pos` | Open purchase orders for a component |
| `get_supplier_master` | Our supplier list, to check a court notice against |
| `supplier_exposure` | What we lose if a supplier's open orders never arrive |
| `check_capacity` | Whether the factories can fill demand |
| `record_supplier_update` | Turns what an email says into a structured update |
| `create_alert` | Raises an alert, with its evidence |
| `mark_noise` | Marks an event as irrelevant |
| `no_new_risk` | Says the event changes nothing |

## 2. The event (built for each event)

This is all Claude starts with: no stock, orders or delivery history. One hidden field, linking the email to its scripted twin, is removed before sending.

```text
Simulated date: 2026-10-01.
Event: {"event_id": "MAIL-004", "ts": "2026-10-01T09:00:00", "event_type": "supplier_email",
 "payload": {
  "subject": "Livraison partielle – commande PO-0063",
  "body": "Bonjour Claire,\n\nSuite à une rupture de matière chez notre fournisseur de ressorts, nous ne pourrons vous livrer que 12 000 pompes airless 30 ml sur les 20 000 de la commande PO-0063. Le solde de 8 000 pièces reste bloqué ; nous reviendrons vers vous avec une date dès que possible. Le transporteur vous communiquera le créneau de livraison des 12 000 pièces.\n\nCordialement,\nSandrine Lefèvre\nADV – Pompes Atlas",
  "language": "fr", "from_name": "Sandrine Lefèvre", "from_email": "s.lefevre@pompes-atlas.example",
  "to_email": "claire.martin@maisonaurore.example", "received_at": "2026-10-01T09:00:00", "supplier_id": "SUP-POM"},
 "processed": false}
Alerts already open: [{"component": "CMP-POM-01", "stockout_week": "2026-11-16", "severity": "medium"},
 {"component": "CMP-COF-NOEL", "stockout_week": "2026-12-21", "severity": "medium"},
 {"component": "CMP-FLA-50", "stockout_week": "2026-12-14", "severity": "medium"},
 {"component": "CMP-FLA-30", "stockout_week": "2026-12-28", "severity": "medium"},
 {"component": "CMP-FLA-50", "stockout_week": "2026-12-21", "severity": "medium"}]
```

The sender and addresses are made up (`.example` domains), like the rest of the brand.

## 3. What Claude did

1. **Read the French and recorded a partial delivery:** `record_supplier_update` with order PO-0063, kind confirmation, 12,000 units.
2. **Ran the projection:** `run_projection`. The answer (3,470 characters) put the pump stockout in the week of 9 November at 91% by launch + 1 week, against 28 December for the planner without memory, and cited Pompes Atlas: announced 42 days, actual 60.9 ± 6.9 days over 14 deliveries.
3. **Raised the alert:** `create_alert` on the 30 ml pump, severity high, confidence 0.91, week of 9 November, with five evidence rows and this explanation:

> Pompes Atlas will deliver only 12,000 of the 20,000 airless pumps on PO-0063 and has given no date for the other 8,000. The supplier history shows an announced 42 d against an actual 60.9 ± 6.9 d, so LaunchPilot projects a median stockout in the week of 2026-11-09 (91% by launch + 1 week), while the no-memory view says 2026-12-28.

## 4. Its closing summary

> In one sentence: the partial delivery on PO-0063 pulls the 30 ml airless pump stockout forward to the week of 2026-11-09, and I raised a high-severity alert at 91% confidence.

The full run, every tool answer included, is stored in the `agent_runs` table, which the app's Agent traces tab shows.
