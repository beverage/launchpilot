"""Copies events from the lp.* Kafka topics into the events table.

Each message's value is {"event_id", "ts", "event_type", "payload"}. Inserts use
ON CONFLICT DO NOTHING, and offsets are committed only after the insert, so a
restart replays at worst a few messages and never loses one.
"""
import json
import time

from ingest.sink import ensure_events_table, insert_event, kafka_config, pg_connect

# Every lp.* topic except the smoke-test one
TOPIC_PATTERN = r"^lp\.(?!smoke$).+"
GROUP_ID = "launchpilot-bridge"


def run(stop_after_idle_s=None, log=print, stats=None):
    """Bridges until stopped. With stop_after_idle_s, returns once no message
    has arrived for that long (used by tests and one-shot runs). Counts go into
    `stats` when given, so a caller can report them."""
    from kafka import KafkaConsumer

    config = kafka_config()
    if not config:
        raise RuntimeError("Kafka isn't configured (KAFKA_BOOTSTRAP_SERVERS is unset)")
    conn = pg_connect()
    ensure_events_table(conn)
    consumer = KafkaConsumer(
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda b: json.loads(b),
        **config,
    )
    consumer.subscribe(pattern=TOPIC_PATTERN)
    if stats is None:
        stats = {}
    stats.setdefault("seen", 0)
    stats.setdefault("inserted", 0)
    last_message = time.time()
    try:
        while True:
            batches = consumer.poll(timeout_ms=1000)
            for records in batches.values():
                for record in records:
                    event = record.value
                    if not all(k in event for k in ("event_id", "ts", "event_type", "payload")):
                        log(f"skipping malformed message on {record.topic} at offset {record.offset}")
                        continue
                    stats["seen"] += 1
                    if insert_event(conn, event):
                        stats["inserted"] += 1
                        log(f"{record.topic}: {event['event_id']} -> events")
            if batches:
                consumer.commit()
                last_message = time.time()
            elif stop_after_idle_s is not None and time.time() - last_message > stop_after_idle_s:
                return stats
    finally:
        consumer.close()
        conn.close()


if __name__ == "__main__":
    run()
