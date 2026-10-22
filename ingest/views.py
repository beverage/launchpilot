"""Read-only views over the events table, for the front ends.

supplier_health: one row per supplier_insolvency notice, with the company card,
whether the demo clock has reached it, the supplier it matches (by SIREN, if any),
the alert it raised and the agent's latest verdict on it.

  python -m ingest.views        # create or replace the views now

The ingest service also recreates them at start-up and after each BODACC poll,
so they survive schema changes on the app side.
"""
from ingest.sink import pg_connect

# to_jsonb(s)->>'siren' rather than s.siren, so the view still builds if the column is ever missing
SUPPLIER_HEALTH = """
CREATE OR REPLACE VIEW supplier_health AS
SELECT
  e.event_id,
  e.ts                                   AS published_at,
  e.processed                            AS reached_by_demo,
  e.payload->>'siren'                    AS siren,
  e.payload->>'company_name'             AS company_name,
  e.payload->>'activity_code'            AS activity_code,
  e.payload->>'activity_label'           AS activity_label,
  e.payload->>'procedure'                AS procedure,
  e.payload->>'procedure_family'         AS procedure_family,
  e.payload->>'court'                    AS court,
  NULLIF(e.payload->>'judgment_date', '')::date AS judgment_date,
  e.payload->>'city'                     AS city,
  e.payload->>'region'                   AS region,
  e.payload->>'notice_url'               AS notice_url,
  e.payload->'company'                   AS company,
  s.supplier_id                          AS matched_supplier_id,
  s.name                                 AS matched_supplier_name,
  (s.supplier_id IS NOT NULL)            AS exposed,
  CASE WHEN s.supplier_id IS NOT NULL THEN
    'Demo mapping: this BODACC notice is real; ' || s.name || ' and its delivery history are fictional, and nothing is implied about '
    || (e.payload->>'company_name') || '''s lead times.'
  END                                    AS mapping_note,
  a.alert_id, a.severity                 AS alert_severity, a.explanation AS alert_explanation,
  r.output                               AS agent_verdict
FROM events e
LEFT JOIN suppliers s
  ON to_jsonb(s)->>'siren' IS NOT NULL AND to_jsonb(s)->>'siren' = e.payload->>'siren'
LEFT JOIN LATERAL (
  SELECT alert_id, severity, explanation FROM alerts
  WHERE trigger_event_id = e.event_id ORDER BY alert_id DESC LIMIT 1
) a ON true
LEFT JOIN LATERAL (
  SELECT output FROM agent_runs
  WHERE agent_runs.input::text LIKE '%' || e.event_id || '%' ORDER BY run_id DESC LIMIT 1
) r ON true
WHERE e.event_type = 'supplier_insolvency'
"""


def ensure_views(conn):
    with conn.cursor() as cur:
        cur.execute(SUPPLIER_HEALTH)
    conn.commit()


if __name__ == "__main__":
    c = pg_connect()
    ensure_views(c)
    print("supplier_health created or replaced")
