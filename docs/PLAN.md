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
| A2 | Free-text supplier email event | An email event in the stream produces a cited alert live | Must | app side (consumer), streams side (producer) | from the brief |
| A3 | Memory that learns live (`po_delivered`) | Supplier memory tab changes during the demo | Must | same | from the brief |
| B1 | English UI and agents (hybrid: supplier emails and BODACC notices stay French, the agent explains in English) | No French UI or agent text on screen; glossary reviewed by Imène | Must | Alex (kickoff session) | doing 11:45, branch ui/b1-english |
| B2 | Hero moments: announced-versus-actual chart, red pump alert, scenario cards | A first-time viewer gets it in 10 seconds | Must | designer, else app side | from the brief |
| C4 | Real supplier-health stream from BODACC | A real notice appears as an event and the agent reports exposure | Should | streams side (producer), app side (consumer) | doing: producer live on Runtime (`launchpilot-ingest`, hourly BODACC poll via Kafka into `events`, BOD- rows); waiting on the app-side consumer to report exposure |
| C5 | Test data that holds together: review section 8 of EVALUATION.md (volume, balance, calendar, join keys, random streams), then the generator changes it proposes | Imène approves or amends section 8, and its Must items have an owner | Should | Alex (Claude); review Imène | doing: section 8 merged in https://github.com/beverage/launchpilot/pull/1; Imène's review and an owner for the Must items pending |
| C3 | Cost and latency per processed event on the proof tab | Numbers on screen | Should | app side | from the brief |
| B3 | Proof chart | One glanceable exhibit, fair comparison | Should | app side | from the brief |
| C1 | Route Claude through the sponsor's AI gateway | A live run goes through the gateway | Should | streams side | doing: app switched to our LiteLLM gateway on Runtime (`launchpilot-gateway`) at 11:20, redeploying `main`; verifying a live agent run in its spend log. Aiven AI Gateway still requested |
| C2 | Event stream on Aiven Kafka instead of table replay | Events consumed from a topic | Nice | streams side | doing: `accel-kafka` live; ingest app on Runtime bridges every `lp.*` topic into `events` (https://01a162ce-0134-7612-81df-55af045f5b25-8080.eur-1.aiven.app/health); `lp.scenario` held until the worker exists |
| A4 | Capacity drops into the projection | A capacity event can trigger an alert | Nice | app side | from the brief |
| D1 | Pitch slide: who, why now, proof, first users | Slide final | Must | Imène | from the brief |
| D2 | Three-minute script and judge Q&A prep | Timed rehearsal under 3:00 | Must | Imène | from the brief |
| D3 | Backup screen recording of the demo | Video saved | Must | Imène | from the brief |

## Milestones (proposal; the brief's were 10:30, 12:30, 14:00, 15:30)

| Time | Milestone |
| --- | --- |
| 11:45 | A0 on `main`, C0 deployed, A1 green on our URL |
| 13:30 | A5, A2, A3 and B1 merged; the journey still works |
| 14:30 | Feature freeze; the deployed app runs the full journey |
| 14:30 to 15:30 | Polish only: B2, B3, C3, C4 if green; bug fixes |
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
