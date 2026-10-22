# LaunchPilot

LaunchPilot spots a product-launch stockout weeks before it happens, by learning how late each supplier really delivers and watching the outside world for signals that move delivery dates.

Built at the Accel AI Innovate hackathon, Paris, 22 October 2026. Deployed on Aiven Runtime, with data in Aiven for PostgreSQL and Aiven for Apache Kafka. The application started from Imène Mekideche's kit, [ImeneMEKIDECHE/launchPilot](https://github.com/ImeneMEKIDECHE/launchPilot), merged here with its history.

## Layout

| Path | What it holds |
| --- | --- |
| `app.py` | Streamlit demo: Launch, Supplier memory, Proof and Agent traces tabs |
| `agents.py` | The watch and arbitration agents: Claude tool-use loops with a rules fallback |
| `tools.py` | What the agents may call: projection, supplier memory, open orders, scenario costing |
| `projection.py` | Deterministic stock projection, naive and learned modes, what-if simulations |
| `store.py`, `schema.sql` | Aiven for PostgreSQL store with auto-bootstrap, or an in-memory fallback; tables and the `supplier_reliability` view |
| `generate_data.py`, `evaluate.py`, `data/` | Seeded synthetic world (fictional brand Maison Aurore) and the proof script |
| `streams/` | Pollers that turn outside data streams into events (supplier insolvencies, holidays, and more) |
| `docs/` | Kickoff findings: [evaluation of the evidence](docs/EVALUATION.md), [input streams and the events contract](docs/INPUT-STREAMS.md), [build plan](docs/PLAN.md), and the [sweep script](docs/evaluation/sweep.py) that reproduces the numbers |

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

- With no configuration the app runs on in-memory data with rules-only agents, so the demo never breaks.
- `DATABASE_URL` (an Aiven for PostgreSQL service URI): the app creates the tables and loads the data on first start; events, alerts, scenarios, decisions and agent traces live there.
- `ANTHROPIC_API_KEY`: the watch and arbitration agents run live with Claude tool use. Optional `CLAUDE_MODEL` (default `claude-sonnet-5-5`) and `ANTHROPIC_BASE_URL` to route through a gateway.
- Demo journey: Reset, fast-forward to EV-019 (a partial pump delivery), the pump alert turns critical, Propose solutions, choose a scenario, then the memory and proof tabs. Say what is live and what is recorded.

## Working in this repo

- Work on short branches; merge to `main` only when the demo journey still runs.
- Secrets live in `.env.local`, which is gitignored. Never commit keys.
