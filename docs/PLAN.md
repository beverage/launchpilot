# Build plan for 22 October (proposal, 11:00)

Reconciles the team brief's task split with the kickoff evaluation ([EVALUATION.md](EVALUATION.md)) and the stream shortlist ([INPUT-STREAMS.md](INPUT-STREAMS.md)). Everything below is a proposal for the team to amend.

## Decisions so far

Moved to [DECISIONS.md](../DECISIONS.md) at 10:36: one line per call with its why, append-only. Log new ones with `scripts/decide "decision · why · who"`.

## Workstreams

This table is the task board. Status starts with one of `todo`, `doing`, `review` (with the PR link), `done` or `cut`, followed by a few words if useful. Claim a task before starting it (your name in Owner, `doing`). Change this table on `main` in its own small commit, never on a feature branch: the rows sit next to each other, so two branches editing them conflict, and a docs-only commit cannot break the journey. A cut also gets a line in DECISIONS.md. New work gets a row with the next number in its workstream.

| Id | Task | Done when | Priority | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| A0 | Port the kit: history preserved, idempotent schema, reset that spares live events, committed `__pycache__` removed | App runs locally against Aiven PostgreSQL and the journey works | Must | Alex (kickoff session) | done, merged to main 10:41; journey verified against accel-pg with live Claude |
| C0 | Deploy on Alex's Aiven Runtime from this repo | Public URL runs the journey | Must | streams side | done 10:47: https://01a162c8-8edd-75e2-a292-0b513a77405a-8080.eur-1.aiven.app (from `main`; redeploy with `scripts/runtime.py redeploy launchpilot`) |
| A1 | Live Claude on the deployed app | Traces tab shows a live run with tool calls | Must | Alex (kickoff session) | done 10:58, live run on the Runtime URL (3.6 s, mark_noise tool call) |
| A5 | Honest proof: fair baseline, timing metric, calibrated probability, proof tab and README updated | Proof tab shows the fair comparison; README numbers replaced | Must | Alex (kickoff session) | done 11:25, merged to main (a772041); 30-seed proof 112/120 vs 97/120, demo pump 39 d ahead at 82 % |
| A2 | Free-text supplier email event | An email event in the stream produces a cited alert live | Must | Alex (kickoff session) consumer + generator, streams side producer | done: merged 12:16 and deployed; the Streamlit app's worker analyses the MAIL- rows; the web front end too since the API deploy at 14:02 (`web/api` d75c94e, not yet merged into main) |
| A3 | Memory that learns live (`po_delivered`) | Supplier memory tab changes during the demo | Must | Alex (kickoff session) consumer + generator, streams side producer | done: merged 12:16 and deployed; the Streamlit app's worker applies the DLV- receipts; the web front end too since the API deploy at 14:02 (`web/api` d75c94e, not yet merged into main) |
| B1 | English UI and agents (hybrid: supplier emails and BODACC notices stay French, the agent explains in English) | No French UI or agent text on screen; glossary reviewed by Imène | Must | Alex (kickoff session) | done: merged 11:41 and deployed (English UI live); glossary in docs/GLOSSARY.md for Imène's review |
| B2 | Hero moments: announced-versus-actual chart, red pump alert, scenario cards | A first-time viewer gets it in 10 seconds | Must | designer, else app side | from the brief |
| C4 | Real supplier-health stream from BODACC | A real notice appears as an event and the agent reports exposure | Should | streams side (producer), app side (consumer) | done 13:20: verified on the deployed app (Reset, fast-forward to EV-019, fast-forward to today): all 9 real BODACC notices analysed; CM INDUSTRIE (SIREN 706820123, receivership) matched to Coffrets Prestige via the labelled demo mapping raises a medium supplier_continuity alert on the Christmas gift box, its text opening "Demo mapping:"; company cards and the `supplier_health` view feed the web front end |
| C5 | Test data that holds together: review section 8 of EVALUATION.md (volume, balance, calendar, join keys, random streams), then the generator changes it proposes | Imène approves or amends section 8, and its Must items have an owner | Should | Alex (kickoff session) for the Must items; review Imène | done 13:27: activity codes, carton/bottle/jar and pump rebalance (Pompes Atlas MOQ 20,000 to 6,000 per Alex), two email fixes, past-season gift boxes, labelled SIREN mapping, all on main; section 8 review closed (DECISIONS.md 13:27); after the hackathon: past gift sets with real sales, calendar, wider world |
| C3 | Cost and latency per processed event on the proof tab | Numbers on screen | Should | Alex (kickoff session) | done: merged 13:13, live since the 13:28 deploy; proof tab reads agent_runs live (median latency and estimated cost per live watch step and arbitration, cost per analysed event, per-agent table) |
| B3 | Proof chart | One glanceable exhibit, fair comparison | Should | Alex (kickoff session) | done: merged 13:25, live since the 13:28 deploy: at-a-glance exhibit at the top of the proof tab (dated stockouts 97 vs 112 of 120; 571 k€ vs 194 k€ at the hero moment) |
| C1 | Route Claude through the sponsor's AI gateway | A live run goes through the gateway | Should | streams side | done 11:40: the deployed app's Claude calls go through our LiteLLM gateway on Runtime (`launchpilot-gateway`), switched at 11:34; a live two-turn watch-agent run (4,509 in, 266 out tokens, $0.012) is in the gateway's spend log under key `launchpilot-app`. Aiven AI Gateway still requested; switching to it is the same two env vars |
| C2 | Event stream on Aiven Kafka instead of table replay | Events consumed from a topic | Nice | streams side | done 12:30: three live streams flow through Aiven Kafka (`lp.supplier_insolvency`, `lp.supplier_email`, `lp.po_delivered`), bridged into `events` by the ingest app on Runtime: 9 BOD-, 5 MAIL- and 6 DLV- rows, payloads identical to the sources. The recorded EV- scenario stays on the app's own replay |
| A6 | Launch exposure on a supplier notice: a what-if drops the supplier's open orders and sizes the extra shortfall and lost revenue, cited by the continuity alert, live and in rules mode | The CM INDUSTRIE alert says "12,000 of the 21,000 launch boxes are still on order; if this order does not arrive, the gift box runs out the week of 16 November instead of 14 December" | Should | Alex (kickoff session) | doing 14:15, branch app/a6-launch-exposure |
| A4 | Capacity drops into the projection | A capacity event can trigger an alert | Nice | app side | from the brief |
| D1 | Pitch slide: who, why now, proof, first users | Slide final | Must | Imène | from the brief |
| D2 | Three-minute script and judge Q&A prep | Timed rehearsal under 3:00 | Must | Imène | from the brief |
| D3 | Demo video: required by the form, not a backup (one end-to-end journey, MP4, three minutes at most; shot list in [SUBMISSION.md](SUBMISSION.md)) | MP4 uploaded to the form | Must | Imène | from the brief |
| D4 | Submission form text fields: name, one-line pitch, data layer in action, GitHub and demo links | Fields filled on the form | Must | Alex | doing: drafts in [SUBMISSION.md](SUBMISSION.md) |
| D5 | Evidence upload: screenshot of the proof exhibit (B3) and the cost and latency panel (C3) on the deployed build | Image uploaded to the form | Must | Alex | todo: unblocked, B3 and C3 are live since the 13:28 deploy |

## Milestones (proposal; the brief's were 10:30, 12:30, 14:00, 15:30)

| Time | Milestone |
| --- | --- |
| 11:45 | A0 on `main`, C0 deployed, A1 green on our URL |
| 13:30 | A5, A2, A3 and B1 merged; the journey still works |
| 15:00 | Feature freeze; the deployed app runs the full journey |
| 15:00 to 15:30 | Polish only: B2, B3, C3, C4 if green; bug fixes |
| 15:30 to 16:00 | Rehearsal, backup video, slide final |

Cut order if something slips: C2, A4, C4, B3, C1.

## Demo line and rules

- Opening line that stays true on the demo seed: "Its spreadsheet says the pumps hold until December. LaunchPilot knew on 1 October they won't make launch week."
- The fair baseline is a human who reads and retypes every supplier email the day it arrives, which nobody at an SMB does. LaunchPilot does that reading, and remembers how each supplier really behaves. Say it this way; do not claim the spreadsheet sees nothing.
- Say on screen and out loud what is live (Claude agents, real streams) and what is recorded (synthetic data, fixed event stream).
- Every number on screen comes from a tool; every alert cites rows. Keep the rules fallback working when the API or the database is down.

## Open decisions

When one is settled, log it in DECISIONS.md and delete it here.

- Pitch language and presenter. The UI is French; the jury is probably English-speaking.
- Fictional suppliers only, or an optional real SIREN per supplier for the registry stream (see the mapping note in INPUT-STREAMS.md)?
- Which two new streams by 13:30? Recommendation: supplier email (A2) and deliveries (A3), with BODACC (C4) third if time allows.
- A planner's one-line quote on announced versus real lead times, for credibility on stage.
- Which front end the demo video and the demo link show: the Streamlit app or the web front end. Both write to the same shared database, so a judge who presses Reset changes what everyone sees.
