# Kickoff evaluation: does the evidence hold?

22 October 2026, written 10:25 and updated 10:50 after the team brief. Based on the starter kit at [ImeneMEKIDECHE/launchPilot](https://github.com/ImeneMEKIDECHE/launchPilot) (commit `36e494b`) and on tests run locally against regenerated copies of its data. The kit's files were not modified. The numbers reproduce with [`evaluation/sweep.py`](evaluation/sweep.py); the run behind this note is [`evaluation/sweep-2026-10-22.txt`](evaluation/sweep-2026-10-22.txt).

## Summary

- **Keep the idea.** Real user (the supply lead of an independent cosmetics brand before a Christmas launch), real pain (packaging suppliers announce six weeks and deliver eight or nine, minimum order quantities are high, the launch date is fixed), and a complete kit: generator, deterministic projection engine, two tool-using Claude agents, PostgreSQL store, Streamlit demo, evaluation script. The recorded demo narrative works end to end, and the live agents work against the real Claude API.
- **Fix the proof before anything else.** The kit's "classic spreadsheet" baseline ignores sell-out spikes and partial-delivery confirmations. A planner who simply reads every message, with no supplier memory, detects 82 of 84 stockouts across 21 seeds (98%). LaunchPilot's learned mode detects 73 (87%), because its memory is miscalibrated and predicts stockouts four weeks early in 11 of 84 cases. One judge question ("what does the spreadsheet do with the sell-out spike?") exposes this.
- **Make the data load-bearing.** The agents compute on CSV copies loaded at import; PostgreSQL mirrors them and stores outputs; the event "stream" is a button; sales history, subcontractors and the four capacity events are unused. "Data at the core" is a judging criterion and the sponsor prize depends on it.
- **Give the model real work.** Events arrive pre-labelled with exactly the fields the engine needs, so the watch agent's triage step reads a label. Raw inputs (supplier emails, weekly sell-out numbers) make the agent necessary rather than decorative.

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
