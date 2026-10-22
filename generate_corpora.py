"""
LaunchPilot — live-stream corpora derived from the recorded scenario, for the Kafka replay producer.

  data/emails.jsonl      supplier emails in French (raw text, the agent must extract the facts). Four mirror a recorded
                         structured event (payload.mirrors = its id, used by the worker to avoid applying both); one is noise.
  data/deliveries.jsonl  goods receipts for the open orders that truly arrive before 22 October (from true_arrivals.json).

Each line is a Kafka message: {"event_id", "ts", "event_type", "payload"}; ts is Paris local time without offset.
Usage: python3 generate_corpora.py [--data data]   (run after generate_data.py)
"""
import argparse, csv, json, os
from datetime import date, datetime, timedelta

ap = argparse.ArgumentParser(); ap.add_argument("--data", default="data"); a = ap.parse_args()
D = a.data
events = {e["event_id"]: e for e in (json.loads(l) for l in open(os.path.join(D, "events.jsonl"), encoding="utf-8"))}
pos = {p["po_id"]: p for p in csv.DictReader(open(os.path.join(D, "purchase_orders.csv"), encoding="utf-8"))}
true_arrival = json.load(open(os.path.join(D, "true_arrivals.json"), encoding="utf-8"))
TO = "claire.martin@maisonaurore.example"
FR = lambda d: date.fromisoformat(d).strftime("%d/%m")

def mail(i, ts, from_name, from_email, subject, body, mirrors=None, supplier_id=None):
    p = {"from_name": from_name, "from_email": from_email, "to_email": TO, "subject": subject, "body": body,
         "received_at": ts, "language": "fr"}
    if supplier_id: p["supplier_id"] = supplier_id
    if mirrors: p["mirrors"] = mirrors
    return {"event_id": f"MAIL-{i:03d}", "ts": ts, "event_type": "supplier_email", "payload": p}

e1, e2, e5, e19 = events["EV-001"], events["EV-002"], events["EV-005"], events["EV-019"]
emails = [
    mail(1, e1["ts"], "Sandrine Lefèvre", "s.lefevre@pompes-atlas.example",
         "Commande PO-0063 – décalage de livraison",
         f"Bonjour Claire,\n\nSuite à un incident sur notre ligne d'injection, nous devons décaler la livraison de votre commande "
         f"PO-0063 (20 000 pompes airless 30 ml). La mise à disposition initialement prévue le {FR(pos['PO-0063']['promised_date'])} "
         f"est reportée au {FR(e1['payload']['new_promised_date'])}, soit une dizaine de jours. Nous faisons le maximum pour tenir cette nouvelle date.\n\n"
         "Avec toutes nos excuses pour la gêne occasionnée,\nSandrine Lefèvre\nADV – Pompes Atlas", mirrors="EV-001", supplier_id="SUP-POM"),
    mail(2, e2["ts"], "Sandrine Lefèvre", "s.lefevre@pompes-atlas.example",
         "Re: PO-0064 – confirmation et nouveau planning",
         f"Bonjour Claire,\n\nNous accusons réception de votre commande PO-0064 (30 000 pompes airless 30 ml). Compte tenu de la charge "
         f"actuelle de l'atelier, la date de mise à disposition passe du {FR(pos['PO-0064']['promised_date'])} au {FR(e2['payload']['new_promised_date'])}, "
         "soit deux semaines de plus que prévu. Le planning est confirmé de notre côté.\n\nCordialement,\nSandrine Lefèvre\nADV – Pompes Atlas",
         mirrors="EV-002", supplier_id="SUP-POM"),
    mail(3, "2026-09-18T11:00:00", "Marc Dubois", "m.dubois@cartonnages-seine.example",   # before EV-005 (26 Sep): the email is the first word of the delay
         "PO-0069 – petit décalage d'expédition",
         f"Bonjour,\n\nPetit décalage sur votre commande d'étuis PO-0069 : l'expédition partira le {FR(e5['payload']['new_promised_date'])} "
         f"au lieu du {FR(pos['PO-0069']['promised_date'])}, trois jours de retard dus à un contrôle qualité supplémentaire sur le vernis. Rien d'autre à signaler.\n\n"
         "Bien à vous,\nMarc Dubois – Cartonnages de Seine", mirrors="EV-005", supplier_id="SUP-ETU"),
    mail(4, e19["ts"], "Sandrine Lefèvre", "s.lefevre@pompes-atlas.example",
         "Livraison partielle – commande PO-0063",
         "Bonjour Claire,\n\nSuite à une rupture de matière chez notre fournisseur de ressorts, nous ne pourrons vous livrer que 12 000 pompes airless 30 ml "
         "sur les 20 000 de la commande PO-0063. Le solde de 8 000 pièces reste bloqué ; nous reviendrons vers vous avec une date dès que possible. "
         "Le transporteur vous communiquera le créneau de livraison des 12 000 pièces.\n\nCordialement,\nSandrine Lefèvre\nADV – Pompes Atlas",
         mirrors="EV-019", supplier_id="SUP-POM"),
    mail(5, "2026-10-06T14:30:00", "Isabelle Garnier", "i.garnier@verrerie-lumiere.example",
         "Changement d'interlocuteur commercial",
         "Bonjour Claire,\n\nÀ compter du 1er novembre, votre interlocuteur commercial chez Verrerie Lumière sera Julien Moreau, qui reprend mon portefeuille. "
         "Vos commandes en cours ne sont pas affectées et les dates convenues restent inchangées.\n\nBien cordialement,\nIsabelle Garnier",
         supplier_id="SUP-FLA"),
]
emails.sort(key=lambda m: m["ts"])
with open(os.path.join(D, "emails.jsonl"), "w", encoding="utf-8") as f:
    for m in emails:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")

TODAY = date(2026, 10, 22)
partial = {e["payload"]["po_id"]: e["payload"]["confirmed_qty"] for e in events.values()
           if e["event_type"] == "po_confirmed" and e["payload"]["confirmed_qty"] < int(pos[e["payload"]["po_id"]]["qty"])}
deliveries = []
for po_id, arr in sorted(true_arrival.items(), key=lambda kv: kv[1]):
    d = date.fromisoformat(arr)
    if d > TODAY:
        continue
    p = pos[po_id]
    qty = partial.get(po_id, int(p["qty"]))
    deliveries.append({"event_id": f"DLV-{po_id}-{d.strftime('%Y%m%d')}", "ts": f"{arr}T09:30:00", "event_type": "po_delivered",
                       "payload": {"po_id": po_id, "supplier_id": p["supplier_id"], "component_id": p["component_id"],
                                   "delivered_at": arr, "quantity_delivered": qty, "quantity_ordered": int(p["qty"]),
                                   "partial": qty < int(p["qty"]), "delivery_note_ref": f"BL-{d.strftime('%Y%m%d')}-{po_id[-3:]}"}})
with open(os.path.join(D, "deliveries.jsonl"), "w", encoding="utf-8") as f:
    for r in deliveries:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"{len(emails)} emails -> {D}/emails.jsonl ; {len(deliveries)} deliveries -> {D}/deliveries.jsonl")
for r in deliveries:
    print("  ", r["event_id"], r["payload"]["quantity_delivered"], "/", r["payload"]["quantity_ordered"])
