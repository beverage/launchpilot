# Kickoff evaluation: does the evidence hold?

22 October 2026, written 10:25, updated 10:50 after the team brief, section 8 added at 10:45 after Imène asked whether the test data is big enough, updated at 12:35 and 13:00 after the C5 generator fixes, and reviewed at 13:27. Based on the starter kit at [ImeneMEKIDECHE/launchPilot](https://github.com/ImeneMEKIDECHE/launchPilot) (commit `36e494b`) and on tests run locally against regenerated copies of its data. The kit's files were not modified. The numbers reproduce with [`evaluation/sweep.py`](evaluation/sweep.py); the run behind this note is [`evaluation/sweep-2026-10-22.txt`](evaluation/sweep-2026-10-22.txt).

## Update 11:30: fixes 1 to 3 applied (task A5)

- **Fair baseline in the engine.** `projection.py` has a native `literal` mode (reads every message, believes announced lead times); it replaces the "classic spreadsheet" line on the chart, in the components table, in the tool outputs and in the agent prompts. The old `naive` mode is kept for comparison only.
- **Calibrated memory.** The deterministic learned mode uses the median real lead time instead of mean + 1 sd, and `project_prob()` draws each lead time from the supplier's delivered history (200 draws) to give a probability of stockout per week, a median week and a p10 to p90 stock band. Alerts fire at a 50% probability; the alert's confidence is that probability.
- **Scenario retuned.** The second pump order is 30,000 units placed on 4 September with a 14-day announced delay: on paper it lands on 30 October, before launch; the supplier's real lead time pushes it to late November. The launch-week crunch is now a pure lead-time effect, so a planner who reads the messages misses it and the memory catches it in most seeds (18 of 21), not 2 of 21.
- **New metric and numbers** (`python3 evaluate.py`, 30 seeds, `data/evaluation.json`): dated within one week, 112 of 120 for LaunchPilot against 97 of 120 for the planner without memory; final dates wrong by more than one week, 8 against 23; false alarms, 0 and 0. Demo seed: the pump is first dated 46 days ahead (watch, median week 16 November), then flagged critical at EV-019 on 1 October, 39 days before the true week of 9 November, with an 85% probability (82% before each supplier got its own random stream in A3); the baseline says 21 December. Arbitration at that point: 571 k€ at risk doing nothing, 194 k€ with the best option.
- **Still open from the list below:** raw inputs (fix 4, task A2), live memory (fix 5, task A3), tools on PostgreSQL and a stream instead of a button (fix 6), unused tables (fix 7), labels and language (fix 8, task B1). The sections below describe the kit as it was at kickoff.

## Summary

- **Keep the idea.** Real user (the supply lead of an independent cosmetics brand before a Christmas launch), real pain (packaging suppliers announce six weeks and deliver eight or nine, minimum order quantities are high, the launch date is fixed), and a complete kit: generator, deterministic projection engine, two tool-using Claude agents, PostgreSQL store, Streamlit demo, evaluation script. The recorded demo narrative works end to end, and the live agents work against the real Claude API.
- **Fix the proof before anything else.** The kit's "classic spreadsheet" baseline ignores sell-out spikes and partial-delivery confirmations. A planner who simply reads every message, with no supplier memory, detects 82 of 84 stockouts across 21 seeds (98%). LaunchPilot's learned mode detects 73 (87%), because its memory is miscalibrated and predicts stockouts four weeks early in 11 of 84 cases. One judge question ("what does the spreadsheet do with the sell-out spike?") exposes this.
- **Make the data load-bearing.** The agents compute on CSV copies loaded at import; PostgreSQL mirrors them and stores outputs; the event "stream" is a button; sales history, subcontractors and the four capacity events are unused. "Data at the core" is a judging criterion and the sponsor prize depends on it.
- **Give the model real work.** Events arrive pre-labelled with exactly the fields the engine needs, so the watch agent's triage step reads a label. Raw inputs (supplier emails, weekly sell-out numbers) make the agent necessary rather than decorative.
- **Fix the data's coherence before its volume.** The roughly 1,000 sales rows are not what limits the proof: the engine never reads them, and every seed has the same four stockouts. The datasets do not balance: the history receives 400,000 pumps, sales use 117,000, and 11,000 are in stock. Section 8 proposes one simulated ledger that every table derives from, widened around the demo story. Fixed at 12:30 for the cartons, the 30 ml bottle and the 50 ml jar; the pumps followed with a lower minimum order (decided 12:46), and the gift box's history moved to past seasons' boxes, whose sales are not modelled (section 8, update 12:35).

## 1. Seed sweep: the baseline is a strawman

Method: regenerate seeds 1 to 20 plus 42 with `generate_data.py`, replay the 35 events, and score three planners with the kit's own criterion (a stockout counts as detected when it is predicted within one week of its true date at some point during the replay).

| Planner | What it believes | Detected | False alarms | Final date wrong by 4 weeks |
| --- | --- | --- | --- | --- |
| naive (kit baseline) | promised dates and forecast v1; ignores spikes and confirmations | 21 / 84 (25%) | 0 | 0 |
| literal (fair baseline) | every message at face value; no supplier memory | 82 / 84 (98%) | 0 | 2, late |
| learned (LaunchPilot) | memory: mean + 1 sd lead time, amplified announced delays | 73 / 84 (87%) | 0 | 11, early |

- The kit's README numbers reproduce: seed 42 gives 1/4 against 4/4, and the 11-draw claim (84% against 25%) matches 87% against 25% over 21 seeds. Seed 42 regenerates byte-identical to the committed `data/`.
- **Seed 42 is an outlier.** In 19 of 21 seeds the pump truly runs out in the week of 7 December, and the learned mode says 9 November, four weeks early, in each of them. Only seeds 16 and 42 have the 9 November truth that makes the demo dramatic. In seed 42 the fair baseline puts the pump stockout on 7 December, four weeks late, so memory is decisive there. That is the exception, not the rule.
- **Why:** prudent lead time = mean + 1 standard deviation, plus announced delays multiplied by the real/announced ratio. Against a truth drawn around the mean, that is systematically pessimistic: the signed error of the final date averages −0.5 weeks for the learned mode and +0.1 weeks for the literal planner.
- **Zero false alarms is structural.** The same four components run out in every seed (gift box, 30 ml bottle, 50 ml jar, pump) and the two cartons never do; only timing varies between seeds. The task is "when", not "whether", so the metric should be timing error and lead time, with "detected" kept only as the one-week convention.

## 2. The recorded demo holds together (rules mode, no API calls)

Replaying the 35 events through the rules-only agents produces 9 alerts: two medium alerts after the first sell-out spike, four after the second, then the pump goes critical at EV-019 (1 October, partial delivery of 12,000 of 20,000) with stockout week 9 November, 39 days ahead. Arbitration: doing nothing puts 742 k€ of revenue at risk; the best option, an urgent order from the backup pump supplier plus allocating pumps to the gift box first, cuts it to 194 k€ with 11 days of safety margin; reordering from the main supplier leaves 0 days of margin. All of this matches the kit's README.

## 3. The live agents work (Claude Sonnet 5.5, in-memory store, tested 10:40)

- Noise event: classified as noise in 4 s, no projection run.
- First supplier delay: no new alert, correctly, because the open pump alert already covered the projected week. The explanation cites the supplier memory.
- Partial delivery (EV-019): high alert for 9 November with confidence 0.8, citing the partial quantity and the supplier memory, in 9.8 s.
- Arbitration: priced all six scenario kinds, read the memory of both pump suppliers, saved the top three scenarios in the right order and recommended the 194 k€ option, in 13.8 s.
- Cost: 3.5k to 14.6k tokens per step, about 0.15 $ for the four runs.
- Catch: the agent repeats the "naive spreadsheet" framing because the tool output fields are named that way. Changing the baseline means changing tool outputs and prompts too.

## 4. Where the data is decorative today

- `tools.py` loads the CSVs at import and the projection runs on them. PostgreSQL holds mirrors plus agent outputs, and the `supplier_reliability` view is used for display only.
- Events are replayed from a file by a button. The Kafka path exists only in `replay_events.py`.
- `sales_history` (937 rows), `subcontractors` and the four `capacity_drop` events are not used by the engine; the UI admits the capacity gap.
- Events are pre-labelled JSON (`supplier_delay` carries `announced_delay_days`, `sellout_spike` carries `observed_vs_forecast`), so triage is label reading.

## 5. Scorecard against the judging criteria

| Criterion | Today | After the fixes below |
| --- | --- | --- |
| Customer problem and value | Strong: clear user, real pain, a buyer in every brand above a few M€. Objection to prepare: "we have an ERP and Excel". Answer: it reads the mailbox and the sell-out, and prices the arbitration in euros. | Same, plus the moat: brands share the same packaging suppliers, so supplier memory compounds across customers. |
| Agent capability | Medium: two tool-using agents with guardrails, deterministic tools, explanations that cite rows. Inputs are pre-labelled, so reasoning is thin. | Raw inputs force extraction and judgement; the agent's own accuracy becomes measurable. |
| Data at the core | Weak: agents run on CSVs, PostgreSQL mirrors, a button instead of a stream, half the tables unused. | Tools query PostgreSQL, events flow through Kafka or a polled table, memory updates live. |
| Evidence it works | Weak: strawman baseline, structural zero false alarms, the demo seed is 2 of 21. | Fair baseline, timing-error metric over 50 seeds, calibrated probabilities, agent metrics (noise precision, extraction accuracy, latency, cost). |
| Execution and pitch | Medium: complete flow, French Streamlit, no pitch slide yet, no live-versus-recorded labels. | Labels, one slide, language decided. |
| Sponsor prize | PostgreSQL only. | PostgreSQL views as the memory, Kafka as the stream, both visible in the demo. |

Competition a jury may name: Flowlity and Pelico (French mid-market planning), Prewave and Everstream (supplier risk, enterprise), Odoo MRP. Our wedge: SMB beauty launches, onboarding from a mailbox and a spreadsheet, arbitration in euros, cross-brand supplier memory. Check the names before the pitch.

## 6. Proposed fixes to the generator and the proof

1. **Make lead-time slippage the cause.** Tune the open pump orders so that, taken literally (promised dates, spikes, partial delivery), stock holds until late December, while real arrivals (order date plus real lead time) open a gap at or before launch week. Then the fair baseline misses it and memory catches it in most seeds, not 2 of 21.
2. **Change the metric.** Timing error in weeks and lead time in days per stockout, against the fair baseline, over 50 seeds.
3. **Calibrate.** Replace mean + 1 sd with the empirical lead-time distribution (sample the historical deliveries, a few hundred Monte Carlo runs) and output a probability of stockout per week. Alert when the probability crosses 50%, severity from probability and proximity to launch. This removes the four-week pessimism and gives "confidence" a meaning.
4. **Raw inputs** for supplier messages and sell-out; keep labels only in the ground truth, and score the agent on noise precision and recall, extraction accuracy and citation validity.
5. **Live memory:** delivery events update `supplier_reliability` during the demo, shown on the memory tab as the pump supplier's prudent lead time moving.
6. **Tools on PostgreSQL**, events through Kafka (`replay_events.py` already produces to a topic) or a polled table processed by a worker, not a button.
7. **Use or drop** sales history, subcontractors and capacity events.
8. **UI:** a live-versus-recorded label on every result (the challenge brief asks for it) and a decision on language.

## 7. Data realism notes

- Hero SKUs sell about 3.5k to 4.6k units a month at 42 to 55 €, which reads like an 8 to 10 M€ brand. A 20k-unit gift set at 89 € is a big launch for it, plausible at Christmas.
- Forecast v1 is flat, times 1.25 in November and December. Sales history has mild seasonality but feeds nothing.
- The five suppliers and their announced-versus-real lead times (42 against 60 days for the pump supplier, 35 against 47 for the gift-box maker) encode the industry pattern the founder describes. Say on stage that the world is synthetic and why it is shaped this way.
- The simulated clock runs from 7 September to a launch on 2 November 2026 with a horizon to 28 December. Real-time events dated today (22 October) fit inside that story.

## 8. Test data: is there enough, and does it hold together?

The question was whether about 1,000 sales rows, and the other datasets, are enough. There are no invoices in the kit: the 1,000 are `sales_history`, weekly totals per product and channel. Numbers below are for seed 42; the balance reproduces with [`evaluation/balance.py`](evaluation/balance.py).

### Update 12:35: what landed, and what is left

Applied on `main` in `3f5cbca` (task C5). Lead times, the supplier memory and the proof do not move: `evaluate.py` still gives 112 of 120 against 97 of 120, and 8 against 23 wrong dates.

- **Activity codes.** `suppliers.activity_code` is 23.13Z for the glassmaker, 22.29A for both pump makers and 17.21B for the carton and gift-box makers, with no SIREN. The exposure check on BODACC notices names same-sector suppliers as a watch. At 12:39 the team took the demo mapping: Coffrets Prestige carries the SIREN of a real cardboard-box maker in receivership, with a label saying the notice is real and the supplier fictional (DECISIONS.md).
- **Balance for the cartons, the 30 ml bottle and the 50 ml jar.** Delivered quantities are recomputed after every random draw; opening stock is now 6 to 8 weeks of use, down from 20 to 71.
- **Two supplier emails reworded.** MAIL-003 is dated 18 September, before the receipt it announces; MAIL-004 confirms a partial quantity without a shipment date.

Left, and why:

- **Pumps cannot balance on quantities alone.** Fourteen deliveries at Pompes Atlas's 20,000 minimum and six at the backup's 5,000 make at least 310,000 pumps received against 117,000 used. Each fix costs something: a lower minimum changes the main-supplier rush order and the "minimum orders are high" story; fewer historical deliveries move the memory and every proof number; history-only demand would have to outsell today's whole range. Alex chose at 12:46 to lower Pompes Atlas's minimum order from 20,000 to 6,000, the highest round value that balances (about five weeks of opening stock); it is applied in the generator under C5. Lead times and the proof do not move; the minimum order is read only by the costed rush order from Pompes Atlas, whose figures change.
- **Gift box, partly fixed at 12:58.** The 14 past deliveries from Coffrets Prestige were all recorded as the 2026 Christmas box, from June 2025 onwards. They are now boxes for four past seasonal sets, by delivery date: summer 2025, Christmas 2025, Mother's Day 2026 and summer 2026. The 2026 box has no history, which is right for a new launch item, and nothing in the proof moves because the memory reads only delivery dates per supplier. What is left: those past sets have no sales in the history, so their 51,000 boxes are received and never used; `balance.py` lists them as "past season, not modelled". The full fix, after the hackathon, adds the past sets as products with history-only sales from their own random stream and zero forecasts (the projection reads a forecast for every product in the bill of materials), and rebalances the box quantities; it also gives the 2026 launch forecast a precedent the agent can cite.
- **Calendar.** Deferred with the holiday stream (decision at 10:41); it would move every proof number.
- **Random streams.** The probabilistic projection has one stream per supplier since A3 (decision at 12:11). The generator still has one, which matters only once the world is widened.
- **Wider world and two years of history:** after the freeze. Invoice-level rows are dropped (review below).

Review at 13:27 (Alex, for Imène's review): the roughly 1,000 rows meant the sales history, so no invoice-level data is needed; 6,000 is a realistic minimum order for an airless-pump maker; the four past seasonal sets match how such brands run them; MAIL-004's French is approved.

The rest of this section describes the data as it was at 10:45.

### What the generator produces

| Dataset | Rows | Read by the engine | Gap |
| --- | --- | --- | --- |
| `sales_history` | 936: 78 weeks × 4 products × 3 channels, 243k units | No | Weekly totals, not invoices; no sales of a previous gift set |
| `purchase_orders` | 70: 62 delivered, 8 open | Yes; the delivered rows are the supplier memory | 14 lead-time samples per supplier, 6 for the backup pump supplier; quantities drawn at random |
| `events.jsonl` | 35: 20 disruptions, 15 noise | Yes | Scripted and pre-labelled (section 4) |
| `forecasts` | 100: 20 weeks × 5 products | Yes | Flat, times 1.25 in November and December; not fitted to the history |
| `suppliers`, `components`, `products`, `bom` | 5, 6, 5, 14 | Yes | Small for the brand's size (section 7); no activity code or location to join real streams on |
| `inventory` | 11, one snapshot | Yes | |
| `subcontractors` | 2 | No | |
| `ground_truth.json` | 4 stockouts | Evaluation only | The same four components in every seed (section 1) |

### Findings

- **Volume is not what limits the proof.** The engine never reads the sales history, and every seed produces the same four stockouts. More rows per seed change nothing. More seeds, with different components failing and some worlds with none, would make false alarms measurable.
- **The datasets do not balance.** Opening stock is what the world must have held when the history starts: stock today minus everything received plus everything used.

  | Component | Received | Used by sales | Stock on 7 Sep | Opening stock | Weeks of use |
  | --- | --- | --- | --- | --- | --- |
  | `CMP-POM-01` pump | 400,000 | 116,951 | 11,000 | −272,049 | impossible |
  | `CMP-COF-NOEL` gift box 2026 | 51,000 | 0 | 0 | −51,000 | impossible |
  | `CMP-ETU-01` serum carton | 35,000 | 116,951 | 24,000 | 105,951 | 71 |
  | `CMP-FLA-30` 30 ml bottle | 60,000 | 116,951 | 32,000 | 88,951 | 59 |
  | `CMP-ETU-02` cream carton | 65,000 | 125,994 | 22,000 | 82,994 | 51 |
  | `CMP-FLA-50` 50 ml jar | 120,000 | 125,994 | 26,000 | 31,994 | 20 |

  Historical order quantities are the minimum order times one or two, drawn without reference to use, and the 2026 gift box is delivered from April 2025 onwards with nothing to put in it. One `SUM` in PostgreSQL shows this, and the agents cite these rows.
- **No calendar.** Lead times are drawn the same way in August and at Christmas as in March. Once `holiday_closure` events are live, the supplier memory and the stream contradict each other.
- **Nothing to join real data on.** Suppliers have no activity code, département or SIREN, so the BODACC category watch can match on text only.
- **One random stream.** Every draw comes from one generator, so any draw added before the open orders shifts all later ones: seed 42's story (the partial delivery on 1 October, EV-019) and the README numbers move with any change to the generator.

### Where more volume does help

- **Supplier memory.** With 14 samples, the 90th-percentile lead time is the second-worst delivery. Two years of history gives about 25 deliveries per supplier and two Christmas seasons, enough for the Monte Carlo calibration in section 6.
- **Agent scoring.** Extraction accuracy needs 100 to 200 labelled supplier emails, rendered from the ground truth.
- **The data layer.** PostgreSQL views and Kafka over tens of thousands of rows read as a data layer rather than a mirror of six CSV files.

### Proposed generator changes

1. **One ledger, many views.** Simulate week by week: demand, component use through the bill of materials, stock, a reorder rule (minimum order, prudent lead time), orders, and deliveries drawn from each supplier's real behaviour and the holiday calendar. Every table is derived from that ledger, so the balance closes by construction.
2. **Keep the demo story.** The pump and gift-set storyline stays a fixed overlay. New data draws from its own random stream (`random.Random(f"{seed}:bg")`), and the existing draws stay in place, so seed 42's lead-time samples do not change. Land this with fix 1 of section 6, so that seed 42 changes once and the README numbers are updated once.
3. **Last year's gift set.** A 2025 gift set with November and December 2025 sales owns the historical gift-box orders, and gives the 2026 forecast a precedent to check against.
4. **Invoices, if wanted.** Split the weekly totals top-down into order lines: invoices to retailers and pharmacies, and e-shop orders. The weekly sums do not change, so the projection and the evaluation are unaffected. At this brand's size that is tens of thousands of e-shop orders a year plus a few thousand B2B invoices (a rough estimate).
5. **Wider world.** A larger catalogue around the demo story (for example 20 suppliers, 60 components, 40 products) and 104 weeks of history.

### Consistency with the real streams

- The generator and the `holiday_closure` producer use the same French holiday source, plus an August closure.
- Suppliers get an activity code (for example 23.13Z glass containers, 22.22Z plastic packaging, 17.21B cartons) and a département, so the BODACC category watch can match on them. `siren` stays empty unless the team takes the demo mapping (PLAN.md, open decisions).
- Synthetic live events take their values from the generator's truth and never invent their own. This is already the rule for `supplier_email` and `po_delivered` (INPUT-STREAMS.md); `sellout_weekly` should follow it, from the same demand multipliers as the ground truth. Otherwise the stream and the projection disagree.
- The simulated clock does not move: 7 September to 22 October, launch on 2 November.

### Priority for today

| Priority | Change | Effort |
| --- | --- | --- |
| Must | Close the balance, add the calendar, split the random streams; together with fix 1 of section 6 | about 1 h |
| Should | Wider catalogue, two years of history, activity codes and départements | 1 to 2 h |
| If time | Invoice-level rows; 100 or more rendered supplier emails for extraction scoring | about 1 h each |
| Skip | More rows of the current shape | |
