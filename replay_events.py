"""
Rejoue data/events.jsonl comme un flux "live" pour la démo.
- Toujours : insère chaque événement dans la table PostgreSQL `events` (processed = false).
- Si KAFKA_BOOTSTRAP est défini : publie aussi sur le topic `launch-events` (Aiven for Apache Kafka, SSL).

Usage :
  DATABASE_URL=... python replay_events.py --speed 2        # 1 événement toutes les 2 s
  DATABASE_URL=... python replay_events.py --until EV-019   # s'arrête après cet événement (moment fort de la démo)
Variables Kafka (optionnelles) : KAFKA_BOOTSTRAP, KAFKA_CA, KAFKA_CERT, KAFKA_KEY (chemins des fichiers Aiven).
"""
import json, os, time, argparse
import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--speed", type=float, default=2.0)
ap.add_argument("--until", default=None)
ap.add_argument("--data", default="data")
a = ap.parse_args()

producer = None
if os.environ.get("KAFKA_BOOTSTRAP"):
    from kafka import KafkaProducer   # pip install kafka-python
    producer = KafkaProducer(bootstrap_servers=os.environ["KAFKA_BOOTSTRAP"], security_protocol="SSL",
                             ssl_cafile=os.environ["KAFKA_CA"], ssl_certfile=os.environ["KAFKA_CERT"],
                             ssl_keyfile=os.environ["KAFKA_KEY"],
                             value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode())

events = [json.loads(l) for l in open(os.path.join(a.data, "events.jsonl"), encoding="utf-8")]
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    cur = conn.cursor()
    for e in events:
        cur.execute("INSERT INTO events (event_id, ts, event_type, payload) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (e["event_id"], e["ts"], e["event_type"], json.dumps(e["payload"], ensure_ascii=False)))
        if producer: producer.send("launch-events", e)
        print(f"{e['ts']}  {e['event_id']}  {e['event_type']}")
        if a.until and e["event_id"] == a.until: break
        time.sleep(a.speed)
if producer: producer.flush()
