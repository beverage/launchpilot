"""Where producers send events, and how events land in PostgreSQL.

Producers call emit(event_id, event_type, payload, ts). With Kafka configured
(KAFKA_BOOTSTRAP_SERVERS and the certificate variables), each event goes to the
topic lp.<event_type> and the bridge copies it into the events table. Without
Kafka, emit() inserts into the events table directly, so the demo never depends
on Kafka being up.

The events table and its rules are the contract in docs/INPUT-STREAMS.md.
"""
import json
import os
import re
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
TOPIC_PREFIX = "lp."

EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events (
  event_id   TEXT PRIMARY KEY,
  ts         TIMESTAMP NOT NULL,
  event_type TEXT NOT NULL,
  payload    JSONB NOT NULL,
  processed  BOOLEAN DEFAULT FALSE
)"""


def paris_now():
    """Paris local time without a timezone, as the contract asks."""
    return datetime.now(PARIS).replace(tzinfo=None, microsecond=0)


def clamp_ts(ts):
    """Events are never dated in the future."""
    now = paris_now()
    return min(ts, now) if ts else now


def _pem_file(env_name):
    f = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    f.write(os.environ[env_name])
    f.close()
    os.chmod(f.name, 0o600)
    return f.name


def kafka_config():
    """kafka-python connection settings, or None when Kafka isn't configured."""
    if not os.environ.get("KAFKA_BOOTSTRAP_SERVERS"):
        return None
    return {
        "bootstrap_servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        "security_protocol": os.environ.get("KAFKA_SECURITY_PROTOCOL", "SSL"),
        "ssl_cafile": _pem_file("KAFKA_CA_CERT"),
        "ssl_certfile": _pem_file("KAFKA_ACCESS_CERT"),
        "ssl_keyfile": _pem_file("KAFKA_ACCESS_KEY"),
    }


def pg_connect():
    """Connects to Aiven PostgreSQL. Aiven leaves the password unescaped in
    DATABASE_URL, so split it by hand: the password runs to the last "@"."""
    import psycopg

    m = re.match(r"^postgres(?:ql)?://([^:]+):(.*)@([^@/:]+):(\d+)/([^?]+)", os.environ["DATABASE_URL"])
    if not m:
        raise ValueError("DATABASE_URL is not a postgres:// URI")
    user, password, host, port, dbname = m.groups()
    ssl = {"sslmode": "require"}
    if os.environ.get("DATABASE_CA_CERT"):
        ssl = {"sslmode": "verify-full", "sslrootcert": _pem_file("DATABASE_CA_CERT")}
    return psycopg.connect(host=host, port=int(port), user=user, password=password, dbname=dbname, **ssl)


def insert_event(conn, event):
    """Inserts one event; re-polling the same source id is a no-op."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_id, ts, event_type, payload, processed) "
            "VALUES (%s, %s, %s, %s, FALSE) ON CONFLICT (event_id) DO NOTHING",
            (event["event_id"], event["ts"], event["event_type"], json.dumps(event["payload"], ensure_ascii=False)),
        )
        inserted = cur.rowcount == 1
    conn.commit()
    return inserted


def ensure_events_table(conn):
    with conn.cursor() as cur:
        cur.execute(EVENTS_DDL)
    conn.commit()


class Sink:
    def __init__(self):
        self.kafka = kafka_config()
        self._producer = None
        self._conn = None

    @property
    def mode(self):
        return "kafka" if self.kafka else "postgres"

    def emit(self, event_id, event_type, payload, ts=None):
        event = {"event_id": event_id, "event_type": event_type, "payload": payload,
                 "ts": clamp_ts(ts).isoformat(timespec="seconds")}
        if self.kafka:
            from kafka import KafkaProducer

            if self._producer is None:
                self._producer = KafkaProducer(
                    key_serializer=str.encode,
                    value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode(),
                    **self.kafka,
                )
            self._producer.send(TOPIC_PREFIX + event_type, key=event_id, value=event).get(timeout=30)
            return True
        if self._conn is None:
            self._conn = pg_connect()
            ensure_events_table(self._conn)
        return insert_event(self._conn, event)

    def close(self):
        if self._producer:
            self._producer.flush()
            self._producer.close()
        if self._conn:
            self._conn.close()
