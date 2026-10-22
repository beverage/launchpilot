"""Supplier-health stream: real insolvency notices for packaging and cosmetics makers.

A category watch, not a claim about any of our suppliers. It reads collective
procedures (receivership, liquidation, safeguard) from BODACC, confirms each
company's official activity code in the French company registry, keeps the
packaging and cosmetics makers, and emits one supplier_insolvency event per
notice. The agent then checks exposure against the supplier master.

  python -m streams.bodacc --days 30 --dry-run   # print the events
  python -m streams.bodacc --days 30             # emit them through the sink

Sources (open data, no key): BODACC annonces-commerciales on Opendatasoft, and
API Recherche d'entreprises.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

BODACC = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
REGISTRY = "https://recherche-entreprises.api.gouv.fr/search"

# Words BODACC uses in the company's declared activity; the registry check below is the real filter
KEYWORDS = ["emballage", "verre", "cartonnage", "plasturgie", "conditionnement", "flaconnage",
            "fabrication cosmétique", "fabrication parfum"]

# NAF codes that supply a cosmetics launch: packaging, glass, plastics, contract packing, cosmetics makers
SECTOR = {
    "17.21A": "Corrugated board",
    "17.21B": "Cardboard boxes",
    "17.21C": "Paper packaging",
    "20.42Z": "Perfumes and toiletries",
    "22.22Z": "Plastic packaging",
    "22.29A": "Technical plastic parts",
    "22.29B": "Plastic consumer goods",
    "23.13Z": "Hollow glass",
    "25.92Z": "Light metal packaging",
    "82.92Z": "Contract packing",
}


def get_json(url, params, retries=3):
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers={"User-Agent": "launchpilot/0.1"}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    return {}


def bodacc_notices(days, page=100):
    terms = " or ".join(f'search(listepersonnes, "{k}")' for k in KEYWORDS)
    where = f'familleavis="collective" and dateparution>=now(days=-{days}) and ({terms})'
    offset = 0
    while True:
        data = get_json(BODACC, {"where": where, "order_by": "dateparution desc", "limit": page, "offset": offset})
        results = data.get("results", [])
        yield from results
        offset += page
        if len(results) < page or offset >= data.get("total_count", 0):
            return


_activity_cache = {}


def registry_activity(siren):
    if siren not in _activity_cache:
        data = get_json(REGISTRY, {"q": siren, "per_page": 1})
        hits = [r for r in data.get("results", []) if r.get("siren") == siren]
        _activity_cache[siren] = hits[0].get("activite_principale") if hits else None
        time.sleep(0.15)  # the registry allows a few requests per second
    return _activity_cache[siren]


def parse_json_field(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value or {}


def to_event(notice, activity_code):
    judgment = parse_json_field(notice.get("jugement"))
    siren = (notice.get("registre") or [""])[0]
    procedure = judgment.get("nature") or notice.get("familleavis_lib")
    detail = (judgment.get("complementJugement") or "").split(" - ")[0].strip()
    published = notice.get("dateparution")
    return {
        "event_id": f"BOD-{notice['id']}",
        "event_type": "supplier_insolvency",
        # Notices go public in the morning of their publication date
        "ts": datetime.fromisoformat(f"{published}T09:00:00"),
        "payload": {
            "siren": siren,
            "company_name": notice.get("commercant"),
            "activity_code": activity_code,
            "activity_label": SECTOR.get(activity_code),
            "procedure": f"{procedure}: {detail}" if detail and detail != procedure else procedure,
            "procedure_family": judgment.get("famille") or notice.get("familleavis_lib"),
            "court": notice.get("tribunal"),
            "judgment_date": judgment.get("date"),
            "publication_date": published,
            "city": notice.get("ville"),
            "region": notice.get("region_nom_officiel"),
            "notice_url": notice.get("url_complete"),
            "source": "BODACC",
        },
    }


def is_company(notice):
    """True for legal entities. Sole traders' notices name a private person, which a public demo shouldn't show."""
    person = parse_json_field(notice.get("listepersonnes")).get("personne", {})
    if isinstance(person, list):
        person = person[0] if person else {}
    return person.get("typePersonne") == "pm"


def poll(days=30, log=print):
    """Yields supplier_insolvency events for packaging and cosmetics companies."""
    seen = kept = 0
    for notice in bodacc_notices(days):
        seen += 1
        siren = (notice.get("registre") or [None])[0]
        if not siren or not is_company(notice):
            continue
        code = registry_activity(siren)
        if code in SECTOR:
            kept += 1
            yield to_event(notice, code)
    log(f"BODACC: {seen} keyword matches in {days} days, {kept} confirmed packaging or cosmetics makers")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--dry-run", action="store_true", help="print events instead of emitting them")
    args = p.parse_args()

    log = lambda m: print(m, file=sys.stderr)
    if args.dry_run:
        for event in poll(args.days, log):
            print(json.dumps({**event, "ts": event["ts"].isoformat()}, ensure_ascii=False))
        return
    from ingest.sink import Sink

    sink = Sink()
    sent = 0
    try:
        for event in poll(args.days, log):
            sink.emit(event["event_id"], event["event_type"], event["payload"], event["ts"])
            sent += 1
    finally:
        sink.close()
    log(f"emitted {sent} events via {sink.mode}")


if __name__ == "__main__":
    main()
