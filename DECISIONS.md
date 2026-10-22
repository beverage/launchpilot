# DECISIONS.md: why LaunchPilot is the way it is

Append-only, newest at the bottom. One line per decision: `HH:MM · decision · why · who`.
Never edit or delete a line. To reverse a decision, add a new line that says so and names the time of the line it replaces.
Fastest way to add one: `scripts/decide "Cut C2 · the consumer is not ready by 13:30 · Imène"`, or `/decide` in Claude Code.

What belongs here: any call someone could otherwise undo or re-argue, such as scope, a cut, the demo story, data, a model, a dependency or a workaround. Who is doing what, and how far along it is, belongs in the workstreams table of [docs/PLAN.md](docs/PLAN.md).

## From the team brief (Imène, before the build)

- brief · User: Claire, supply manager at an independent French cosmetics brand (€10–50M revenue) launching a Christmas gift box; demo brand Maison Aurore, synthetic data · suppliers announce lead times they don't keep, MOQs are high, and planning tools target companies above ~$50M · Imène
- brief · Supplier memory is a SQL view in PostgreSQL (`supplier_reliability`: mean, standard deviation and late rate over delivered POs) · the gap between announced and actual lead times is the whole insight, so it lives in the data · Imène
- brief · Maths are deterministic tools; agents decide what to compute, triage noise and explain, and every alert cites its rows · no number on screen that a tool didn't compute · Imène
- brief · Without an API key the agents fall back to rules · nothing breaks the demo when the API or the database is down · Imène
- brief · Say on screen and out loud what runs live and what is recorded · we built the synthetic world ourselves, and a judge will ask · Imène

## Today

The first three lines were logged at 10:36 from docs/PLAN.md, where they were written at 10:33.

- 10:33 · One shared public repo (beverage/launchpilot) on Alex's Aiven project: PostgreSQL, Runtime, and Kafka if used; Imène's kit (ImeneMEKIDECHE/launchPilot) is the source of the port and stays deployed as the fallback demo · WHY: to add · Alex
- 10:33 · Port the kit as-is first, with its commit history, then improve it on branches · `main` must run the demo journey from the first commit · Alex
- 10:33 · Split the work by folder: `streams/`, `ingest/` and the Runtime deploy on the streams side; app, agents, projection, generator, evaluation and `schema.sql` on the app side; Imène owns the pitch (slide, script, backup video) · several people and agent sessions work at once, and nobody should step on anyone's files · Alex
- 10:36 · Decisions go in this file, one line each, append-only; the workstreams table in docs/PLAN.md is the task board, its status kept current on `main`; no GitHub Issues · the same one-line log carried two earlier one-day hackathons; the plan already splits the work into ids with owners, and the team and several agent sessions need one place in the repo that says who has what · Alex
- 10:41 · Why the 10:33 shared repo, whose line has no why: public, and new rather than Imène's · public because the hackathon requires it; new because all the plumbing is already set up in Alex's environment · Alex
- 10:41 · Port Imène's kit with its git history as the base of the rebuild; schema.sql made idempotent and the demo reset limited to EV- rows · the app and the stream producers share the events table in accel-pg, and the journey must survive a reset · Claude (kickoff session)
- 10:41 · docs/INPUT-STREAMS.md is the single source of truth for event payload keys, id prefixes and the demo-clock rule · two sessions build producers and consumers in parallel and cannot afford two key sets · Claude (kickoff session)
- 10:41 · Weather dropped as an input stream; public holidays only once the projection uses closures · decorative data costs points on the data-at-the-core criterion · Claude (both sessions)
- 10:48 · Event streams flow through Aiven Kafka: free accel-kafka in do-fra, one topic per event type (lp.<event_type>), client-certificate auth; a bridge copies every lp.* topic into the events table · the judges reward multiple data streams and the Aiven prize names Kafka, while the app keeps reading one table · Alex (approved Kafka), Claude (prep session)
- 10:48 · Producers fall back to inserting into events directly when Kafka is not configured · the demo must never depend on Kafka being up · Claude (prep session)
- 10:48 · BODACC stream is a category watch over packaging and cosmetics companies, activity codes confirmed in the company registry, legal entities only · it implies nothing about a real company's lead times, and a public demo should not spotlight a private person's insolvency · Claude (prep session)
- 10:48 · Ingest runs as its own Runtime app with its own Dockerfile (ingest/Dockerfile): bridge plus hourly BODACC poll, /health for status · keeps the app container untouched · Claude (both sessions)
- 10:49 · LaunchPilot deploys to Runtime as app launchpilot (startup-50-1024, aws-eu-central-1) from the public repo without a GitHub connection; the Postgres CA goes in base64 as PROJECT_CA_CERT · no GitHub account is connected to Runtime and public repos build without one; Runtime rejects newlines in variable values · Claude (prep session)
- 10:55 · A5 honest proof before A2 and A3 · the kit's spreadsheet baseline is a strawman (a planner who reads every message scores 98% with no memory, the memory 87% and four weeks early), and the agent prompts and tool outputs repeat that framing, so the later tasks build on whatever A5 settles · Alex
- 11:02 · C1: ask Aiven for AI Gateway access, and in parallel build a backup gateway: LiteLLM from Aiven's official template (Aiven-Labs/aiven-runtime-litellm) on Runtime, with a free Valkey and a separate litellm database in accel-pg; the app switches only after a test call passes, decided at 12:30 · the AI Gateway needs approval we may not get in time, and a gateway we run on Aiven keeps most of the sponsor-prize story and logs cost per call for C3 · Alex
- 11:05 · Demo scenario retuned: the second pump order is 30,000 units placed on 4 September with a 14-day announced delay, so on paper it lands before launch while the supplier's real lead time pushes it past launch week · the launch-week crunch must come from lead-time slippage, not under-ordering, otherwise a planner who reads the messages catches it without any memory · Claude (kickoff session, under A5)
- 11:05 · Supplier memory uses the median real lead time and 200 draws from delivered history; alerts fire at a 50 % probability and the alert's confidence is that probability · mean + 1 sd predicted stockouts four weeks early in most seeds, and a probability gives the agent a confidence that means something · Claude (kickoff session, under A5)
- 11:05 · The proof's baseline is the planner without memory (reads every message, believes announced lead times), scored on dating within one week, wrong dates and false alarms over 30 seeds; headline numbers become 112/120 vs 97/120 dated and 8 vs 23 wrong dates, demo 571 k€ at risk vs 194 k€ best option, pump flagged 39 days ahead at 82 % · the spreadsheet baseline was a strawman and the pitch must not depend on it · Claude (kickoff session, under A5)
