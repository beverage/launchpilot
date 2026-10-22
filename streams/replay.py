"""Replays a recorded stream (JSON Lines) into the event pipeline, one event at a time.

Each line is already an event: {"event_id", "ts", "event_type", "payload"}, with
payload keys as in docs/INPUT-STREAMS.md. The payload passes through unchanged.
Events go out in ts order, through the same sink as the live streams (Kafka
topic lp.<event_type>, or the events table directly without Kafka).

  python -m streams.replay data/emails.jsonl --dry-run
  python -m streams.replay data/emails.jsonl data/deliveries.jsonl --interval 5
  python -m streams.replay data/emails.jsonl --until MAIL-004
"""
import argparse
import json
import sys
import time
from datetime import datetime

REQUIRED = ("event_id", "ts", "event_type", "payload")


def load(paths):
    events = []
    for path in paths:
        with open(path) as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                event = json.loads(line)
                missing = [k for k in REQUIRED if k not in event]
                if missing:
                    raise ValueError(f"{path}:{n} is missing {', '.join(missing)}")
                events.append(event)
    return sorted(events, key=lambda e: e["ts"])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", help="JSON Lines files of events")
    p.add_argument("--interval", type=float, default=3.0, help="seconds between events (default 3)")
    p.add_argument("--until", help="stop after the event with this id")
    p.add_argument("--dry-run", action="store_true", help="print the events instead of emitting them")
    args = p.parse_args()

    events = load(args.files)
    if args.until and args.until not in {e["event_id"] for e in events}:
        sys.exit(f"--until {args.until}: no such event_id in {', '.join(args.files)}")

    sink = None
    if not args.dry_run:
        from ingest.sink import Sink

        sink = Sink()
    try:
        for i, event in enumerate(events):
            if args.dry_run:
                print(json.dumps(event, ensure_ascii=False))
            else:
                # The sink clamps future timestamps to now, as the contract requires
                sink.emit(event["event_id"], event["event_type"], event["payload"], datetime.fromisoformat(event["ts"]))
                print(f"{event['ts']}  {event['event_id']}  {event['event_type']}", flush=True)
            if event["event_id"] == args.until:
                break
            if sink and i < len(events) - 1:
                time.sleep(args.interval)
    finally:
        if sink:
            sink.close()


if __name__ == "__main__":
    main()
