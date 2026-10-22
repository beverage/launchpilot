# LaunchPilot

LaunchPilot spots a product-launch stockout weeks before it happens, by learning how late each supplier really delivers and watching the outside world for signals that move delivery dates.

Built at the Accel AI Innovate hackathon, Paris, 22 October 2026. Deployed on Aiven Runtime, with data in Aiven for PostgreSQL and Aiven for Apache Kafka. The application started from Imène Mekideche's kit, [ImeneMEKIDECHE/launchPilot](https://github.com/ImeneMEKIDECHE/launchPilot), merged here with its history.

## Layout

| Path | What it holds |
| --- | --- |
| `app.py` | Streamlit demo: Launch, Supplier memory, Proof and Agent traces tabs |
| `api.py`, `api.dockerfile` | HTTP API for the web frontend built in Lovable: the same store, tools and agents as `app.py`, served as JSON under `/api` |
| `agents.py` | The watch and arbitration agents: Claude tool-use loops with a rules fallback |
| `tools.py` | What the agents may call: projection, supplier memory, open orders, scenario costing |
| `projection.py` | Deterministic stock projection, naive and learned modes, what-if simulations |
| `store.py`, `schema.sql` | Aiven for PostgreSQL store with auto-bootstrap, or an in-memory fallback; tables and the `supplier_reliability` view |
| `generate_data.py`, `evaluate.py`, `data/` | Seeded synthetic world (fictional brand Maison Aurore) and the proof script |
| `worker.py`, `generate_corpora.py` | Consumer of live events (supplier emails, goods receipts, BODACC notices) and the generator of the email and delivery corpora replayed through Kafka |
| `streams/` | Pollers that turn outside data streams into events (supplier insolvencies, holidays, and more) |
| `docs/` | Kickoff findings: [evaluation of the evidence](docs/EVALUATION.md), [input streams and the events contract](docs/INPUT-STREAMS.md), [build plan](docs/PLAN.md), and the [sweep script](docs/evaluation/sweep.py) that reproduces the numbers |

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The web frontend's API: `uvicorn api:app --reload --port 8000`, then open `http://localhost:8000/docs` for the endpoints. `CORS_ORIGINS` adds allowed origins beyond Lovable's domains and localhost.

- With no configuration the app runs on in-memory data with rules-only agents, so the demo never breaks.
- `DATABASE_URL` (an Aiven for PostgreSQL service URI): the app creates the tables and loads the data on first start; events, alerts, scenarios, decisions and agent traces live there.
- `ANTHROPIC_API_KEY`: the watch and arbitration agents run live with Claude tool use. Optional `CLAUDE_MODEL` (default `claude-sonnet-5-5`) and `ANTHROPIC_BASE_URL` to route through a gateway.
- Demo journey: Reset, fast-forward to EV-019 (a partial pump delivery), the pump alert turns critical, Propose solutions, choose a scenario, then the memory and proof tabs. Say what is live and what is recorded.

## What the proof says

The baseline is honest: a planner who reads every message (new promised dates, confirmed quantities, sell-out spikes) but believes the announced lead times. LaunchPilot reads the same messages and adds the supplier memory, drawing each lead time from the supplier's delivered history and alerting when a stockout is at least 50% likely.

| Over 30 synthetic worlds (`python3 evaluate.py`) | Planner without memory | LaunchPilot |
| --- | --- | --- |
| Stockouts dated within one week of the truth | 92 / 120 | 118 / 120 |
| Final dates wrong by more than one week | 28 | 2 |
| False alarms | 0 | 0 |

In the demo scenario the launch-week pump stockout (week of 9 November) is first dated 46 days ahead as a watch alert, then raised to critical on 1 October, 39 days ahead, with a 91% probability; the planner without memory places it on 21 December. Doing nothing puts 571 k€ of revenue at risk; the best costed option, allocating the remaining pumps to the gift set first, cuts it to 437 k€, and the agent shows that a rush order from the backup supplier would land the week the delayed order arrives anyway, so it is not worth placing. Deliveries land on French working days and count for their whole week. All of this is a recorded scenario on synthetic data, and the app says so on screen. Method and caveats: [docs/EVALUATION.md](docs/EVALUATION.md).

## Working in this repo

- Work on short branches; merge to `main` only when the demo journey still runs.
- Secrets live in `.env.local`, which is gitignored. Never commit keys.
- Log every call in [DECISIONS.md](DECISIONS.md) with `scripts/decide "decision · why · who"`; who is doing what lives in the [plan's task board](docs/PLAN.md#workstreams). Agents follow [AGENTS.md](AGENTS.md).
