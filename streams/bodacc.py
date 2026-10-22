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
from datetime import date, datetime

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


_registry_cache = {}

# INSEE headcount bands (tranche_effectif_salarie)
HEADCOUNT = {"00": "0", "01": "1-2", "02": "3-5", "03": "6-9", "11": "10-19", "12": "20-49", "21": "50-99",
             "22": "100-199", "31": "200-249", "32": "250-499", "41": "500-999", "42": "1,000-1,999",
             "51": "2,000-4,999", "52": "5,000-9,999", "53": "10,000+"}
SIZE = {"PME": "SME", "ETI": "Mid-size", "GE": "Large"}


def registry_record(siren):
    """The company's record in the French company registry, or None."""
    if siren not in _registry_cache:
        data = get_json(REGISTRY, {"q": siren, "per_page": 1})
        hits = [r for r in data.get("results", []) if r.get("siren") == siren]
        _registry_cache[siren] = hits[0] if hits else None
        time.sleep(0.15)  # the registry allows a few requests per second
    return _registry_cache[siren]


def registry_activity(siren):
    record = registry_record(siren)
    return record.get("activite_principale") if record else None


# BODACC notice families, in English for the front ends
FAMILY_LABELS = {
    "collective": "Insolvency proceedings",
    "conciliation": "Conciliation",
    "retablissement_professionnel": "Professional recovery",
    "vente": "Business sale or transfer",
    "radiation": "Deregistration",
    "modification": "Company changes",
    "dpc": "Accounts filed",
    "immatriculation": "Registration",
    "creation": "Creation",
}


def bodacc_history(siren, limit=40):
    """The company's BODACC notices, newest first: date, family and link only. The free text
    is left out because it names directors, administrators and addresses."""
    data = get_json(BODACC, {"where": f'registre="{siren}"', "order_by": "dateparution desc", "limit": limit})
    history = []
    for r in data.get("results", []):
        entry = {"date": r.get("dateparution"), "family": r.get("familleavis"),
                 "label": FAMILY_LABELS.get(r.get("familleavis"), r.get("familleavis_lib")),
                 "notice_url": r.get("url_complete")}
        if r.get("familleavis") == "dpc":
            depot = parse_json_field(r.get("depot"))
            if depot.get("dateCloture"):
                entry["accounts_period_end"] = depot["dateCloture"]
        history.append(entry)
    return history


def warning_signs(card, history):
    """Short factual lines a supply manager would want before an insolvency, derived only from the data."""
    signs = []
    if card and card.get("net_result_eur") is not None and card["net_result_eur"] < 0:
        loss = -card["net_result_eur"] / 1e6
        revenue = (card.get("revenue_eur") or 0) / 1e6
        signs.append(f"Latest published accounts ({card.get('accounts_year')}) show a net loss of €{loss:.1f}M"
                     + (f" on €{revenue:.1f}M revenue" if revenue else ""))
    for h in history:
        if h["family"] in ("vente", "radiation", "conciliation"):
            signs.append(f"{h['label']} on {h['date']}")
    accounts = [h for h in history if h["family"] == "dpc"]
    if accounts:
        last = accounts[0]
        line = f"Last accounts filed on {last['date']}"
        if last.get("accounts_period_end"):
            end, filed = date.fromisoformat(last["accounts_period_end"]), date.fromisoformat(last["date"])
            months = (filed.year - end.year) * 12 + filed.month - end.month
            line += f", for the financial year ending {last['accounts_period_end']} ({months} months after the year end)"
            if (date.today() - end).days > 21 * 30:
                line += "; no accounts published for any later financial year"
        signs.append(line)
    earlier = [h for h in history if h["family"] == "collective"][1:]
    if earlier:
        signs.append(f"{len(earlier)} earlier insolvency notice(s), the first on {earlier[-1]['date']}")
    return signs


def company_card(record):
    """What a front end needs to present the company. Deliberately no directors or other
    named people; the head-office address is left out if the company restricts publication."""
    if not record:
        return None
    siege = record.get("siege") or {}
    public = record.get("statut_diffusion", "O") == "O"
    finances = record.get("finances") or {}
    latest = max(finances) if finances else None
    return {
        "legal_name": record.get("nom_complet"),
        "siren": record.get("siren"),
        "activity_code": record.get("activite_principale"),
        "activity_label": SECTOR.get(record.get("activite_principale")),
        "size": SIZE.get(record.get("categorie_entreprise"), record.get("categorie_entreprise")),
        "headcount": HEADCOUNT.get(record.get("tranche_effectif_salarie") or ""),
        "headcount_year": record.get("annee_tranche_effectif_salarie"),
        "founded": record.get("date_creation"),
        "status": {"A": "active", "C": "ceased"}.get(record.get("etat_administratif"), record.get("etat_administratif")),
        "head_office_city": siege.get("libelle_commune") if public else None,
        "head_office_postcode": siege.get("code_postal") if public else None,
        "head_office_department": siege.get("departement"),
        "open_sites": record.get("nombre_etablissements_ouverts"),
        "revenue_eur": (finances.get(latest) or {}).get("ca") if latest else None,
        "net_result_eur": (finances.get(latest) or {}).get("resultat_net") if latest else None,
        "accounts_year": latest,
        "registry_url": f"https://annuaire-entreprises.data.gouv.fr/entreprise/{record.get('siren')}",
        "source": "API Recherche d'entreprises",
    }


def full_company_card(siren):
    """The registry card plus the company's BODACC history and the warning signs drawn from both."""
    card = company_card(registry_record(siren))
    if card is None:
        return None
    history = bodacc_history(siren)
    card["bodacc_history"] = history
    card["warning_signs"] = warning_signs(card, history)
    return card


def parse_json_field(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value or {}


def to_event(notice, activity_code, company=None):
    judgment = parse_json_field(notice.get("jugement"))
    siren = (notice.get("registre") or [""])[0]
    # The judgment type only: the free-text complement names court-appointed people and addresses,
    # which a public demo shouldn't display
    procedure = judgment.get("nature") or notice.get("familleavis_lib")
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
            "procedure": procedure,
            "procedure_family": judgment.get("famille") or notice.get("familleavis_lib"),
            "court": notice.get("tribunal"),
            "judgment_date": judgment.get("date"),
            "publication_date": published,
            "city": notice.get("ville"),
            "region": notice.get("region_nom_officiel"),
            "notice_url": notice.get("url_complete"),
            "source": "BODACC",
            "company": company,
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
            yield to_event(notice, code, full_company_card(siren))
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
