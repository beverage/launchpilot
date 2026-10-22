# Submission

The organisers' form has eight fields, six of them required. Answers can be changed until the deadline, so submit early and update. Drafts below are paste-ready; owners and status live on the [task board](PLAN.md#workstreams) (D1 to D5).

| Field | Required | What the form asks | Source | Board |
| --- | --- | --- | --- | --- |
| Project name | yes | Text | "LaunchPilot" | D4 |
| One-line pitch | yes | Text | Draft below | D4 |
| 3 minute demo | yes | MP4 upload: a working product solving the customer problem in one end-to-end user journey | Recorded on the deployed app after the freeze | D3 |
| The data layer in action | yes | Text: what data the agent uses, where it lives, how it flows | Draft below | D4 |
| Evidence it works | yes | Upload: a before-and-after, a benchmark, or a comparison against a no-data or naive baseline | The proof exhibit (B3) and the cost and latency panel (C3) | D5 |
| One pitch slide | yes | Link to one slide, open to anyone with the link (Google Slides). For a top-8 team this slide is the only thing shown on stage | Who, why now, first users, plus the product, the data layer and the proof | D1 |
| GitHub repo | no | Link to a public repo | https://github.com/beverage/launchpilot (front end: https://github.com/beverage/launchpilot-web) | D4 |
| Demo link | no | Link | The deployed app on Aiven Runtime | D4 |

## One-line pitch

Pick one:

- LaunchPilot warns an independent cosmetics brand weeks before a launch stockout, by learning how late each supplier really delivers and reading the supplier emails and public notices nobody has time to read.
- An agent that dates a product-launch stockout weeks ahead, because it remembers how late each supplier really delivers.

## The data layer in action

> LaunchPilot's agents fail without the data: with announced lead times alone, they place the launch-week pump stockout on 21 December instead of 9 November.
>
> **What the agents use.** A brand's planning data (suppliers, components, bills of materials, 78 weeks of sales by channel, forecasts, stock, 70 purchase orders with promised and actual dates) and three live streams: free-text supplier emails in French, goods receipts, and real insolvency notices from BODACC, the French official gazette, enriched with company-registry cards.
>
> **Where it lives.** Everything sits in Aiven for PostgreSQL. The streams flow through Aiven for Apache Kafka, one topic per event type (`lp.supplier_email`, `lp.po_delivered`, `lp.supplier_insolvency`); an ingest app on Aiven Runtime polls BODACC and bridges every topic into an `events` table. Five apps run on Aiven Runtime: the agent app, the ingest bridge, the HTTP API, the web front end, and a LiteLLM gateway through which every Claude call passes and is costed.
>
> **How it flows.** A worker drains due events in time order. The watch agent (Claude with tool use) reads each one and calls tools that query PostgreSQL: the stock projection, the supplier memory, open orders, scenario costing. Every alert cites the rows it rests on. A goods receipt marks its order delivered, which updates the `supplier_reliability` view: the supplier memory learns during the demo, and the next projection draws lead times from the new history. The arbitration agent costs the options in euros, and every run, tool call, token count and latency lands in `agent_runs`, which the proof tab reads live.

The data is synthetic (a fictional brand, Maison Aurore) except the BODACC notices and company cards, which are real; the app says so on screen.

## Evidence it works

Upload a screenshot of the proof tab's exhibit (B3), taken on the deployed build, plus the cost and latency panel (C3) if it fits. The numbers, from `python3 evaluate.py` (30 synthetic worlds, 120 stockouts):

| | Planner without memory (reads every message, believes announced lead times) | LaunchPilot (same reading plus supplier memory) |
| --- | --- | --- |
| Stockouts dated within one week of the truth | 97 / 120 | 112 / 120 |
| Final dates wrong by more than a week | 23 | 8 |
| False alarms | 0 | 0 |

Demo world: the pump stockout is dated 46 days ahead and raised to critical on 1 October at 85 %; the planner without memory places it on 21 December. Doing nothing puts 571 k€ of revenue at risk; the best costed option cuts it to 194 k€. Say that the comparison is against an attentive planner, not a strawman spreadsheet.

## The demo video (three minutes, MP4)

One end-to-end journey on the deployed app, recorded after the 15:00 freeze and after the redeploy that carries B3 and C3. A shot list that fits:

1. 0:00 The user and the stake: Claire, supply manager at an independent French cosmetics brand, Christmas launch on 2 November; her spreadsheet says the pumps hold until December.
2. 0:20 Reset, play the recorded events; a French supplier email arrives and the agent extracts the new date, citing it.
3. 0:50 EV-019, the partial pump delivery: the pump alert turns critical, launch week, 85 %, with its evidence rows.
4. 1:20 Propose solutions: costed options in euros; choose one.
5. 1:50 Supplier memory: a live goods receipt moves the supplier's real lead time on screen.
6. 2:15 Fast-forward to today: a real BODACC notice hits the gift-box supplier (label it as a demo mapping).
7. 2:35 Proof: 112 vs 97 of 120 against the planner without memory; cost and latency per event.
8. 2:55 What is live (Claude agents, Kafka streams, BODACC) and what is recorded (synthetic data, fixed scenario).

## The pitch slide

The form says this slide is the only thing shown on stage, so it carries the whole story: who it is for (Claire, supply manager at an independent French cosmetics brand of 10 to 50 M€, below the size planning tools target), why now, how we reach the first users, a product screenshot (the critical pump alert), the data flow in one line (streams → Kafka → PostgreSQL → agents with tools → cited alert), and the proof number. Share it as "Anyone with the link can view" and test the link from a private window.

## Before submitting

- The demo link points at a shared database: anyone who presses Reset changes what the others see. Decide whether to submit it, and when.
- Open the GitHub link logged out and check the README numbers match the proof tab.
- Test every link from a private window.
