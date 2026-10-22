# Input streams and the events contract

LaunchPilot is judged as an event-driven agent whose data layer does real work. This note ranks the streams worth adding today, records what the kit's recorded stream already carries, and fixes the contract between producers (pollers, replay) and the consumer (the watch agent), so the two can be built in parallel.

## Ranked shortlist

| # | Stream | Form | Why | Effort |
| --- | --- | --- | --- | --- |
| 1 | Supplier messages | Emails or portal notes as free text, in French; the agent extracts the order, the new date and the quantity | The real channel at an SMB, and the one place the language model is indispensable | 1 to 2 h (producer + prompt) |
| 2 | Deliveries (`po_delivered`) | Structured: order, actual date, quantity | Updates the supplier memory during the demo, so the learning is visible, which the challenge brief rewards | 1 h |
| 3 | Supplier health, real and live | Collective procedures from BODACC and legal status from the French company registry | The only genuinely live public data in the demo, and the best answer to "it is all synthetic" | 1 to 2 h |
| 4 | Sell-out | Weekly units per channel (e-shop, selective retail, pharmacy), no "spike" label | Detecting the deviation from forecast becomes the agent's work instead of label reading | 1 h |
| 5 | Order confirmations, shipping notices, partial shipments | Structured, already in the kit | Keep | 0 |
| 6 | Public holidays and plant closures | Dates from a holidays API, or a known supplier closure | Only if the projection uses them: French suppliers close in August and at Christmas, which shifts lead times | 1 h |
| 7 | Contract-manufacturer capacity | Already generated | Only if the engine uses it; otherwise drop the event type | 1 h or delete |

Dropped: weather (decorative for packaging supply), transport tracking and commodity indices (no time). News search credits from a sponsor can add context to an alert later; optional.

## What the recorded stream already carries

`data/events.jsonl` holds 35 events from 8 September to 22 October 2026: 20 disruptions and 15 noise. Types and payload keys:

- `supplier_delay` (6): `po_id`, `supplier_id`, `component_id`, `new_promised_date`, `announced_delay_days`
- `sellout_spike` (6): `product_id`, `channel`, `observed_vs_forecast`, `weeks_affected`
- `capacity_drop` (4): `subcontractor_id`, `capacity_drop_rate`, `weeks_affected` (not used by the projection yet)
- `po_confirmed` (4): `po_id`, `component_id`, `confirmed_date`, `confirmed_qty` (a quantity below the order is a partial delivery; EV-019 is the demo's turning point)
- `noise` (15): `note`

The recorded event ids are `EV-001` to `EV-035`.

## The events contract

Producers and the consumer share one table in Aiven for PostgreSQL:

```sql
CREATE TABLE IF NOT EXISTS events (
  event_id   TEXT PRIMARY KEY,
  ts         TIMESTAMP NOT NULL,
  event_type TEXT NOT NULL,
  payload    JSONB NOT NULL,
  processed  BOOLEAN DEFAULT FALSE
);
```

Rules:

- **Ids carry a prefix per producer** so the demo's reset can clear the recorded scenario without touching live rows: `EV-` recorded scenario, `MAIL-` supplier messages, `DLV-` deliveries, `BOD-` BODACC notices, `HOL-` holidays, `SELL-` sell-out. Ids must be stable across polls (derive them from the source's own id) so re-polling is idempotent with `ON CONFLICT DO NOTHING`.
- **Timestamps** are ISO 8601 without a timezone, Paris local time, like the recorded ones, and never in the future. The demo's clock is the timestamp of the latest event the app has seen; the recorded story runs from 7 September to 22 October 2026 with the launch on 2 November, so real events dated today fit inside it.
- **`processed`** is written by the consumer only. Producers insert `FALSE`.
- **The demo clock** is the latest `ts` among processed events, recorded or live. Unprocessed rows never move it. The consumer processes rows in `ts` order and only those due at the current clock, so a live row dated today is analysed when the replay reaches today, as the last beat of the story. Until the consumer worker exists, the app ignores rows whose id does not start with `EV-` for both the clock and the alerts, so producers may write to the table at any time without disturbing the recorded demo.
- **Payload** is a JSON object with the keys below. Anything the agent needs to cite must be in the payload or in a row it can name (`table:id`).
- Reset in the app deletes only `EV-%` events, the derived rows and the agent outputs; live rows survive and are re-queued; deliveries applied to purchase orders are reverted.
- **Emails that mirror a recorded event** carry `payload.mirrors` (the `EV-` id). The agent never sees that key. When the live agent extracts the email it writes a derived structured row (`MAIL-00x/derived`, type `supplier_delay` or `po_confirmed`, `payload.derived_from` and `mirrors`); the recorded twin is then stored as `superseded` and skipped, so the news is applied once. If the twin was already applied, the derived row is the one marked `superseded`.
- **Goods receipts** (`po_delivered`) mark the order delivered in `purchase_orders` (`actual_date`, `delivered_qty`), which feeds the `supplier_reliability` view and makes the order a fixed arrival in the projection.
- **One app owns the dataset.** Only the main app may create the schema and (re)load `data/` into the database. Any other process that opens the same database (an API, a worker) must set `LAUNCHPILOT_BOOTSTRAP=0` (or call `get_store(bootstrap=False)`), otherwise two apps built from different `data/` flip the shared database between dataset versions on every start and reset the demo.
- **The consumer** (`worker.py`) runs inside the app: before each recorded event, and on the "Analyse live events due now" button, it drains unprocessed live rows dated on or before the demo clock, oldest first. Rules mode leaves emails for the live agent, still applies deliveries, and does a name/SIREN exposure check on insolvency notices.
- **Corpora:** `python3 generate_corpora.py` writes `data/emails.jsonl` (5 French supplier emails, 4 mirroring EV-001, EV-002, EV-005 and EV-019, 1 noise) and `data/deliveries.jsonl` (the 6 open orders that truly arrive before 22 October, PO-0063 partial), each line already in the Kafka message shape.

Proposed new event types:

| event_type | Payload keys | Producer | Consumer behaviour |
| --- | --- | --- | --- |
| `supplier_email` | `from_name`, `from_email`, `to_email`, `subject`, `body`, `received_at`, `language`, optional `supplier_id` | generated by the kit's generator into `data/emails.jsonl`, published by the replay producer | the agent extracts order, new date and quantity, then projects and alerts with the email cited |
| `po_delivered` | `po_id`, `supplier_id`, `component_id`, `delivered_at`, `quantity_delivered`, `quantity_ordered`, `partial`, `delivery_note_ref` | generated into `data/deliveries.jsonl` from the generator's true arrivals, published by the replay producer | marks the order delivered in `purchase_orders`; `supplier_reliability` recomputes; the next projection uses it |
| `supplier_insolvency` | `siren`, `company_name`, `activity_code`, `procedure`, `court`, `judgment_date`, `publication_date`, `notice_url`, `source`; optional `activity_label`, `procedure_family`, `city`, `region`, `supplier_id` | BODACC poller (category watch) | the agent checks exposure against the supplier master and the open orders; no match means "no exposure, monitoring" |
| `holiday_closure` | `country`, `date`, `name`, `source`, optional `supplier_id` | holidays poller | the projection shifts open-order arrivals that fall in a closure window |
| `sellout_weekly` | `week`, `product_id`, `channel`, `units`, `forecast_units` | replay or shop export | the agent or the engine detects the deviation and scales the forecast for the affected weeks |

## Mapping real public data to a fictional brand

The five suppliers are fictional and have no SIREN. Do not attach a real company's insolvency notice to a fictional "unreliable" supplier: the reliability numbers are synthetic and the pairing would read as a claim about a real business.

Safer options, in order:

1. **Category watch.** The BODACC poller follows collective procedures for real packaging-sector companies (glass, plastics, cartons). The agent reports exposure against our supplier master and open orders. With no match it says so and keeps monitoring. Everything shown is a real public notice, nothing is implied about any company's lead times.
2. **Optional mapping for the demo.** Add a nullable `siren` column to `suppliers` and map one fictional supplier to a real company with a recent notice, with an on-screen label "mapping for demo purposes". Only if the team wants a direct hit on stage.

## Sources and verification

- **BODACC** (DILA), dataset `annonces-commerciales` on `bodacc-datadila.opendatasoft.com`, open licence, published five times a week. Filter `familleavis="collective"` for collective procedures; the SIREN is in `registre`; useful fields: `dateparution`, `familleavis_lib`, `typeavis_lib`, `commercant`, `tribunal`, `jugement`, `url_complete`. Verified 21 October: HTTP 200 in about 0.5 s, no key, about 4,900 collective-procedure notices in the previous seven days.
- **API Recherche d'entreprises** (`recherche-entreprises.api.gouv.fr/search?q=...`): legal status, directors, head office, activity code; open, no key, daily updates. Verified 21 October.
- **Public holidays:** Nager.Date, no key.
- **Weather** (Open-Meteo) was considered and dropped.
