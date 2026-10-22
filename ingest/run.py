"""The ingest service, deployed as its own Aiven Runtime app.

Runs two loops and a health endpoint:
- the bridge, copying every lp.* Kafka topic into the events table;
- the BODACC watch, polling real insolvency notices every BODACC_EVERY_MIN minutes.

GET /health returns what it has done, for the smoke test and for a glance on stage.
"""
import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ingest import bridge
from ingest.sink import Sink, paris_now, pg_connect
from ingest.views import ensure_views
from streams import bodacc

PORT = int(os.environ.get("PORT", 8080))
BODACC_EVERY_MIN = int(os.environ.get("BODACC_EVERY_MIN", 60))
BODACC_DAYS = int(os.environ.get("BODACC_DAYS", 30))

state = {
    "started": paris_now().isoformat(),
    "bridge": {"seen": 0, "inserted": 0},
    "bodacc": {"last_poll": None, "emitted_last_poll": 0, "emitted_total": 0},
    "errors": [],
}


def log(message):
    print(f"{paris_now().isoformat()} {message}", flush=True)


def record_error(where):
    state["errors"] = (state["errors"] + [f"{paris_now().isoformat()} {where}: {traceback.format_exc(limit=1).strip().splitlines()[-1]}"])[-5:]
    log(f"error in {where}:\n{traceback.format_exc()}")


def bridge_loop():
    while True:
        try:
            bridge.run(log=log, stats=state["bridge"])
        except Exception:
            record_error("bridge")
            time.sleep(10)


def refresh_views():
    """Recreates the read-only views for the front ends; logs instead of failing."""
    try:
        conn = pg_connect()
        try:
            ensure_views(conn)
        finally:
            conn.close()
    except Exception:
        record_error("views")


def bodacc_loop():
    while True:
        sink = Sink()
        try:
            sent = 0
            for event in bodacc.poll(BODACC_DAYS, log):
                sink.emit(event["event_id"], event["event_type"], event["payload"], event["ts"])
                sent += 1
            state["bodacc"].update(last_poll=paris_now().isoformat(), emitted_last_poll=sent)
            state["bodacc"]["emitted_total"] += sent
        except Exception:
            record_error("bodacc")
        finally:
            sink.close()
        refresh_views()
        time.sleep(BODACC_EVERY_MIN * 60)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"ok": True, "sink": Sink().mode, **state}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the logs for the loops


def main():
    refresh_views()
    if os.environ.get("KAFKA_BOOTSTRAP_SERVERS"):
        threading.Thread(target=bridge_loop, daemon=True).start()
    threading.Thread(target=bodacc_loop, daemon=True).start()
    log(f"ingest listening on :{PORT}; BODACC every {BODACC_EVERY_MIN} min over {BODACC_DAYS} days")
    ThreadingHTTPServer(("0.0.0.0", PORT), Health).serve_forever()


if __name__ == "__main__":
    main()
