# LaunchPilot

LaunchPilot spots a product-launch stockout weeks before it happens, by learning how late each supplier really delivers and watching the outside world for signals that move delivery dates.

Built at the Accel AI Innovate hackathon, Paris, 22 October 2026. Deployed on Aiven Runtime, with data in Aiven for PostgreSQL and Aiven for Apache Kafka.

## Layout

| Path | What it holds |
| --- | --- |
| `streams/` | Pollers that turn outside data streams into events (supplier insolvencies, holidays, and more) |
| app, agents, projection | Coming next |
| `docs/` | Kickoff findings: [evaluation of the evidence](docs/EVALUATION.md), [input streams and the events contract](docs/INPUT-STREAMS.md), [build plan](docs/PLAN.md), and the [sweep script](docs/evaluation/sweep.py) that reproduces the numbers |

## Working in this repo

- Work on short branches; merge to `main` only when the demo journey still runs.
- Secrets live in `.env.local`, which is gitignored. Never commit keys.
