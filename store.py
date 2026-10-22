"""
Couche de stockage de LaunchPilot.
- PgStore  : Aiven for PostgreSQL (si DATABASE_URL est défini). Crée le schéma et charge les CSV au premier lancement.
- MemStore : repli en mémoire (démo sans base).
Les deux exposent la même interface, utilisée par les agents et l'interface.
"""
import json, os, csv
from datetime import datetime

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HERE = os.path.dirname(os.path.abspath(__file__))
BASE_TABLES = ["suppliers", "components", "products", "bom", "subcontractors",
               "sales_history", "forecasts", "inventory", "purchase_orders"]


def _jsonable(x):
    if isinstance(x, (datetime,)):
        return x.isoformat()
    return x


class MemStore:
    kind = "mémoire (sans base)"

    def __init__(self):
        self.reset()

    def reset(self):
        self.events, self.alerts, self.scenarios, self.decisions, self.runs = [], [], [], [], []

    # événements
    def add_event(self, e):
        if not any(x["event_id"] == e["event_id"] for x in self.events):
            self.events.append(dict(e, processed=False))

    def list_events(self):
        return list(self.events)

    def mark_processed(self, event_id):
        for e in self.events:
            if e["event_id"] == event_id:
                e["processed"] = True

    # alertes
    def add_alert(self, a):
        a = dict(a, alert_id=len(self.alerts) + 1, created_at=datetime.now().isoformat(timespec="seconds"))
        self.alerts.append(a)
        return a["alert_id"]

    def list_alerts(self):
        return list(reversed(self.alerts))

    # scénarios
    def add_scenario(self, s):
        s = dict(s, scenario_id=len(self.scenarios) + 1)
        self.scenarios.append(s)
        return s["scenario_id"]

    def list_scenarios(self, alert_id):
        return [s for s in self.scenarios if s["alert_id"] == alert_id]

    # décisions
    def add_decision(self, d):
        self.decisions.append(dict(d, decided_at=datetime.now().isoformat(timespec="seconds")))

    def list_decisions(self):
        return list(reversed(self.decisions))

    # traces
    def log_run(self, r):
        self.runs.append(r)

    def list_runs(self):
        return list(self.runs)

    def supplier_memory_sql(self):
        return None


class PgStore(MemStore):
    kind = "Aiven for PostgreSQL"

    def __init__(self, url):
        self.url = url
        self._connect()
        self._bootstrap()

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        self.conn = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def _q(self, sql, params=None, fetch=True):
        import psycopg
        for attempt in (1, 2):           # reconnexion automatique si la connexion a expiré
            try:
                with self.conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall() if fetch and cur.description else None
            except psycopg.OperationalError:
                if attempt == 2:
                    raise
                self._connect()

    def _bootstrap(self):
        exists = self._q("SELECT to_regclass('public.suppliers') AS t")[0]["t"]
        if not exists:
            self._q(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read(), fetch=False)
        if self._q("SELECT COUNT(*) AS n FROM suppliers")[0]["n"] == 0:
            with self.conn.cursor() as cur:
                for t in BASE_TABLES:
                    path = os.path.join(DATA, f"{t}.csv")
                    with open(path, encoding="utf-8") as f:
                        header = next(csv.reader(f))
                    with cur.copy(f"COPY {t} ({','.join(header)}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')") as cp:
                        cp.write(open(path, "rb").read())

    def reset(self):
        self._q("TRUNCATE decisions, scenarios, alerts, events, agent_runs RESTART IDENTITY CASCADE", fetch=False)

    def add_event(self, e):
        self._q("INSERT INTO events (event_id, ts, event_type, payload) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (e["event_id"], e["ts"], e["event_type"], json.dumps(e["payload"], ensure_ascii=False)), fetch=False)

    def list_events(self):
        rows = self._q("SELECT event_id, ts, event_type, payload, processed FROM events ORDER BY ts, event_id")
        return [dict(r, ts=r["ts"].isoformat()) for r in rows]

    def mark_processed(self, event_id):
        self._q("UPDATE events SET processed = TRUE WHERE event_id = %s", (event_id,), fetch=False)

    def add_alert(self, a):
        r = self._q("""INSERT INTO alerts (source, trigger_event_id, item_id, risk_type, predicted_stockout_week,
                       severity, confidence, explanation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING alert_id""",
                    (a["source"], a.get("trigger_event_id"), a["item_id"], a.get("risk_type", "stockout_component"),
                     a.get("predicted_stockout_week"), a["severity"], a.get("confidence"),
                     json.dumps({"text": a["explanation"], "evidence": a.get("evidence", [])}, ensure_ascii=False)))
        return r[0]["alert_id"]

    def list_alerts(self):
        out = []
        for r in self._q("SELECT * FROM alerts ORDER BY alert_id DESC"):
            try:
                ex = json.loads(r["explanation"])
            except Exception:
                ex = {"text": r["explanation"], "evidence": []}
            out.append(dict(r, explanation=ex["text"], evidence=ex.get("evidence", []),
                            created_at=r["created_at"].isoformat(timespec="seconds"),
                            predicted_stockout_week=r["predicted_stockout_week"].isoformat() if r["predicted_stockout_week"] else None,
                            confidence=float(r["confidence"]) if r["confidence"] is not None else None))
        return out

    def add_scenario(self, s):
        r = self._q("""INSERT INTO scenarios (alert_id, label, cost_eur, lost_revenue_eur, stock_value_eur, description, evidence_rows)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING scenario_id""",
                    (s["alert_id"], s["label"], s.get("cost_eur"), s.get("lost_revenue_eur"), s.get("stock_value_eur"),
                     s.get("description"), json.dumps(s.get("evidence_rows", []), ensure_ascii=False)))
        return r[0]["scenario_id"]

    def list_scenarios(self, alert_id):
        rows = self._q("SELECT * FROM scenarios WHERE alert_id = %s ORDER BY scenario_id", (alert_id,))
        return [dict(r, cost_eur=float(r["cost_eur"] or 0), lost_revenue_eur=float(r["lost_revenue_eur"] or 0),
                     stock_value_eur=float(r["stock_value_eur"] or 0)) for r in rows]

    def add_decision(self, d):
        self._q("INSERT INTO decisions (alert_id, scenario_id, decided_by, comment) VALUES (%s,%s,%s,%s)",
                (d["alert_id"], d["scenario_id"], d.get("decided_by"), d.get("comment")), fetch=False)

    def list_decisions(self):
        rows = self._q("""SELECT d.*, s.label FROM decisions d LEFT JOIN scenarios s ON s.scenario_id = d.scenario_id
                          ORDER BY d.decision_id DESC""")
        return [dict(r, decided_at=r["decided_at"].isoformat(timespec="seconds")) for r in rows]

    def log_run(self, r):
        self._q("""INSERT INTO agent_runs (agent, input, tool_calls, output, latency_ms, tokens_in, tokens_out)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (r["agent"], json.dumps(r.get("input"), ensure_ascii=False, default=str),
                 json.dumps(r.get("tool_calls"), ensure_ascii=False, default=str),
                 json.dumps(r.get("output"), ensure_ascii=False, default=str),
                 r.get("latency_ms"), r.get("tokens_in"), r.get("tokens_out")), fetch=False)

    def list_runs(self):
        return self._q("SELECT agent, latency_ms, tokens_in, tokens_out, started_at FROM agent_runs ORDER BY run_id")

    def supplier_memory_sql(self):
        """La mémoire fournisseur telle que calculée par la vue SQL (preuve que la donnée vit dans Aiven)."""
        return self._q("""SELECT supplier_id, name, announced_lead_time_days AS annonce_j, real_lead_time_days AS reel_j,
                          lead_time_stddev AS ecart_type_j, late_rate AS taux_retard, n_deliveries AS livraisons
                          FROM supplier_reliability ORDER BY late_rate DESC, real_lead_time_days DESC""")


def get_store():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        try:
            return PgStore(url), None
        except Exception as ex:  # on ne bloque jamais la démo
            return MemStore(), f"Connexion PostgreSQL impossible : {ex}"
    return MemStore(), None
