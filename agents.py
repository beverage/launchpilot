"""
Les agents de LaunchPilot.

- Agent Veille    : réagit à chaque événement du flux, projette le stock avec la mémoire fournisseur, crée des alertes sourcées.
- Agent Arbitrage : face à une alerte, chiffre plusieurs scénarios en euros et recommande.

Chaque agent existe en deux versions :
- "live"   : boucle Claude avec outils (tool use) — nécessite ANTHROPIC_API_KEY.
- "règles" : version déterministe, rapide et gratuite (avance rapide, ou démo sans clé).
L'interface affiche toujours quelle version a produit chaque résultat.
"""
import json, os, time
from datetime import date
import tools as T

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-sonnet-5-5"


def claude_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic
    # ANTHROPIC_BASE_URL est lu automatiquement par le SDK (utile pour passer par l'AI Gateway d'Aiven).
    return anthropic.Anthropic()


def _loop(system, user, tool_specs, handlers, store, agent_name, max_turns=10):
    """Boucle agentique générique : Claude appelle des outils jusqu'à répondre en texte."""
    client = _client()
    messages = [{"role": "user", "content": user}]
    calls, t0, tin, tout, final = [], time.time(), 0, 0, ""
    for _ in range(max_turns):
        resp = client.messages.create(model=MODEL, max_tokens=1500, system=system, tools=tool_specs, messages=messages)
        tin += resp.usage.input_tokens
        tout += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        final = "".join(b.text for b in resp.content if b.type == "text")
        if not uses:
            break
        results = []
        for u in uses:
            try:
                out = handlers[u.name](**u.input)
            except Exception as ex:
                out = {"error": str(ex)}
            calls.append({"tool": u.name, "input": u.input, "output": out})
            results.append({"type": "tool_result", "tool_use_id": u.id,
                            "content": json.dumps(out, ensure_ascii=False, default=str)[:6000]})
        messages.append({"role": "user", "content": results})
    run = {"agent": agent_name, "input": user, "tool_calls": calls, "output": final,
           "latency_ms": int((time.time() - t0) * 1000), "tokens_in": tin, "tokens_out": tout, "mode": "live"}
    store.log_run(run)
    return run


# ======================= AGENT VEILLE =======================

WATCH_SYSTEM = """Tu es l'agent de veille de LaunchPilot, copilote supply d'une marque cosmétique PME (Maison Aurore).
Le coffret de Noël est mis en marché la semaine du {launch}. Un nouvel événement vient d'arriver dans le flux.
Étapes :
1. Classe l'événement : impact potentiel sur l'approvisionnement des composants, ou bruit. Si c'est du bruit, appelle mark_noise et arrête.
2. Appelle run_projection. Le délai annoncé par un fournisseur ne fait JAMAIS foi : la projection LaunchPilot utilise la mémoire fournisseur (délais réels appris). Compare avec la vue « Excel naïf » pour expliquer l'écart.
3. Pour chaque composant dont la rupture LaunchPilot est nouvelle, ou plus tôt qu'une alerte déjà existante, appelle create_alert. Gravité high si rupture au plus tard une semaine après le lancement, sinon medium. Confiance entre 0 et 1.
4. L'explication fait 2 phrases maximum, en français, et cite les preuves au format table:id présentes dans les sorties d'outils.
5. Si rien ne change, appelle no_new_risk.
Interdits : inventer un chiffre absent des outils, créer une alerte sans preuve, répéter une alerte identique.
Termine par une phrase de synthèse."""

WATCH_TOOLS = [
    {"name": "run_projection", "description": "Projette le stock de chaque composant jusqu'à fin décembre, en mode LaunchPilot (mémoire fournisseur) et en mode Excel naïf. Renvoie semaine de rupture, stock mini, gravité suggérée, preuves.",
     "input_schema": {"type": "object", "properties": {"component_ids": {"type": "array", "items": {"type": "string"}, "description": "Optionnel : limiter à ces composants"}}}},
    {"name": "get_supplier_memory", "description": "Fiabilité réelle d'un fournisseur apprise sur l'historique des livraisons (délai annoncé vs réel, écart-type, retards).",
     "input_schema": {"type": "object", "properties": {"supplier_id": {"type": "string"}}}},
    {"name": "get_open_pos", "description": "Commandes fournisseur ouvertes pour un composant.",
     "input_schema": {"type": "object", "properties": {"component_id": {"type": "string"}}, "required": ["component_id"]}},
    {"name": "create_alert", "description": "Crée une alerte de rupture.",
     "input_schema": {"type": "object", "properties": {
         "component_id": {"type": "string"}, "stockout_week": {"type": "string", "description": "AAAA-MM-JJ (lundi)"},
         "severity": {"type": "string", "enum": ["high", "medium", "low"]}, "confidence": {"type": "number"},
         "explanation": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}},
         "required": ["component_id", "stockout_week", "severity", "confidence", "explanation", "evidence"]}},
    {"name": "mark_noise", "description": "L'événement n'a pas d'impact supply.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "no_new_risk", "description": "L'événement a été analysé, aucune alerte nouvelle n'est nécessaire.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
]


def _existing(store, cid):
    return [a for a in store.list_alerts() if a["item_id"] == cid]


def _should_alert(store, cid, week):
    ex = _existing(store, cid)
    if not ex:
        return True
    last = ex[0]["predicted_stockout_week"]
    return bool(week and last and week < last)


def watch_live(store, event, events_seen):
    created = []

    def create_alert(component_id, stockout_week, severity, confidence, explanation, evidence):
        if component_id not in T.COMP:
            return {"error": "composant inconnu"}
        if not _should_alert(store, component_id, stockout_week):
            return {"status": "ignorée : une alerte identique ou plus grave existe déjà"}
        aid = store.add_alert({"source": "agent Claude (live)", "trigger_event_id": event["event_id"], "item_id": component_id,
                               "predicted_stockout_week": stockout_week, "severity": severity, "confidence": confidence,
                               "explanation": explanation, "evidence": evidence})
        created.append(aid)
        return {"status": "créée", "alert_id": aid}

    handlers = {
        "run_projection": lambda component_ids=None: T.run_projection(events_seen, component_ids),
        "get_supplier_memory": lambda supplier_id=None: T.get_supplier_memory(supplier_id),
        "get_open_pos": lambda component_id: T.get_open_pos(component_id),
        "create_alert": create_alert,
        "mark_noise": lambda reason: {"status": "ok"},
        "no_new_risk": lambda reason: {"status": "ok"},
    }
    existing = [{"component": a["item_id"], "stockout_week": a["predicted_stockout_week"], "severity": a["severity"]}
                for a in store.list_alerts()]
    user = (f"Date simulée : {event['ts'][:10]}.\nÉvénement : {json.dumps(event, ensure_ascii=False)}\n"
            f"Alertes déjà ouvertes : {json.dumps(existing, ensure_ascii=False)}")
    run = _loop(WATCH_SYSTEM.format(launch=T.LAUNCH_WEEK), user, WATCH_TOOLS, handlers, store, "veille")
    run["alerts_created"] = created
    return run


def watch_rules(store, event, events_seen):
    """Version déterministe de l'agent Veille (avance rapide)."""
    created = []
    if event["event_type"] != "noise":
        for r in T.run_projection(events_seen):
            wk = r["stockout_week_launchpilot"]
            if not wk or not _should_alert(store, r["component_id"], wk):
                continue
            m = T.get_supplier_memory(r["supplier_id"])[0]
            naive = r["stockout_week_naive_excel"]
            txt = (f"Rupture de {r['name']} prévue semaine du {wk}"
                   + (f" (l'Excel naïf ne la voit pas)." if not naive else f" (l'Excel naïf la voit le {naive}).")
                   + f" {m['name']} annonce {m['announced_days']} j mais livre en {m['real_mean_days']} j en moyenne sur {m['deliveries']} livraisons.")
            aid = store.add_alert({"source": "règles (avance rapide)", "trigger_event_id": event["event_id"],
                                   "item_id": r["component_id"], "predicted_stockout_week": wk,
                                   "severity": r["suggested_severity"], "confidence": 0.7, "explanation": txt,
                                   "evidence": r["evidence"]})
            created.append(aid)
    run = {"agent": "veille", "mode": "règles", "input": event["event_id"], "tool_calls": [], "output": f"{len(created)} alerte(s)",
           "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "alerts_created": created}
    store.log_run(run)
    return run


# ======================= AGENT ARBITRAGE =======================

ARB_SYSTEM = """Tu es l'agent d'arbitrage de LaunchPilot, pour Claire, responsable supply de Maison Aurore (marque cosmétique PME).
Une alerte de rupture vient d'être levée. Objectif : lui proposer 3 scénarios chiffrés en euros, puis recommander.
Méthode :
1. Appelle cost_scenario avec kind="do_nothing" pour connaître la valeur à risque.
2. Évalue au moins : order_alt_supplier, order_main_supplier, prioritize_launch, order_alt_and_prioritize, reduce_launch. Regarde la marge de sécurité (safety_margin_days) : une commande qui arrive pile au moment de la rupture chez un fournisseur peu fiable est risquée. Les délais utilisés sont les délais RÉELS appris, pas les délais annoncés.
3. Pense aux combinaisons (ex. commande urgente + allocation prioritaire au coffret en attendant) et explique-les.
4. Appelle save_scenario pour les 3 scénarios retenus (le meilleur en premier), avec une description de 2 phrases qui cite les chiffres des outils.
5. Termine par ta recommandation en 3 phrases maximum : ce que tu ferais, pourquoi, et la question que Claire doit trancher. Donne ton niveau de confiance.
Ton direct, phrases courtes, en français. N'invente aucun chiffre."""

ARB_TOOLS = [
    {"name": "cost_scenario", "description": "Chiffre un scénario pour un composant. kind : do_nothing | order_main_supplier | order_alt_supplier | prioritize_launch | reduce_launch | order_alt_and_prioritize. Renvoie surcoût, CA perdu, achat immobilisé, impact total, nouvelle date de rupture, preuves.",
     "input_schema": {"type": "object", "properties": {
         "component_id": {"type": "string"}, "kind": {"type": "string"},
         "qty": {"type": "integer", "description": "Optionnel, quantité à commander"},
         "reduction_pct": {"type": "number", "description": "Optionnel, % de réduction du lancement"}},
         "required": ["component_id", "kind"]}},
    {"name": "get_supplier_memory", "description": "Fiabilité réelle d'un fournisseur.",
     "input_schema": {"type": "object", "properties": {"supplier_id": {"type": "string"}}}},
    {"name": "save_scenario", "description": "Enregistre un scénario proposé à Claire.",
     "input_schema": {"type": "object", "properties": {
         "label": {"type": "string"}, "kind": {"type": "string"}, "description": {"type": "string"},
         "qty": {"type": "integer"}, "reduction_pct": {"type": "number"}},
         "required": ["label", "kind", "description"]}},
]


def _save(store, alert, s, cost, description):
    return store.add_scenario({"alert_id": alert["alert_id"], "label": s, "cost_eur": cost.get("cost_eur", 0),
                               "lost_revenue_eur": cost.get("lost_revenue_eur", 0), "stock_value_eur": cost.get("stock_value_eur", 0),
                               "description": description, "evidence_rows": cost.get("evidence_rows", [])})


def arbitrate_live(store, alert, events_seen, now):
    cid = alert["item_id"]

    def save_scenario(label, kind, description, qty=None, reduction_pct=None):
        c = T.cost_scenario(events_seen, now, cid, kind, qty, reduction_pct)
        if "error" in c:
            return c
        return {"status": "enregistré", "scenario_id": _save(store, alert, label, c, description)}

    handlers = {
        "cost_scenario": lambda component_id, kind, qty=None, reduction_pct=None: T.cost_scenario(events_seen, now, component_id, kind, qty, reduction_pct),
        "get_supplier_memory": lambda supplier_id=None: T.get_supplier_memory(supplier_id),
        "save_scenario": save_scenario,
    }
    user = (f"Date simulée : {now}. Alerte : {json.dumps({k: alert[k] for k in ['alert_id', 'item_id', 'predicted_stockout_week', 'severity', 'explanation']}, ensure_ascii=False)}\n"
            f"Composant : {T.comp_label(cid)}, fournisseur principal {T.supplier_of(cid)}, alternatif {T.COMP[cid]['alt_supplier_id'] or 'aucun'}.")
    return _loop(ARB_SYSTEM, user, ARB_TOOLS, handlers, store, "arbitrage")


def arbitrate_rules(store, alert, events_seen, now):
    cid = alert["item_id"]
    kinds = ["order_alt_and_prioritize", "order_alt_supplier", "prioritize_launch", "reduce_launch", "order_main_supplier"]
    res = [T.cost_scenario(events_seen, now, cid, k) for k in kinds]
    res = [r for r in res if "error" not in r]
    res.sort(key=lambda r: (r["total_impact_eur"], -(r.get("safety_margin_days") or 0)))
    for r in res[:3]:
        _save(store, alert, r["label"], r, r["detail"])
    base = T.cost_scenario(events_seen, now, cid, "do_nothing")
    best = res[0] if res else None
    out = (f"Valeur à risque si on ne fait rien : {base['lost_revenue_eur']:,.0f} €. ".replace(",", " ")
           + (f"Option la moins coûteuse : {best['label']} (impact {best['total_impact_eur']:,.0f} €).".replace(",", " ") if best else ""))
    run = {"agent": "arbitrage", "mode": "règles", "input": alert["alert_id"], "tool_calls": [], "output": out,
           "latency_ms": 0, "tokens_in": 0, "tokens_out": 0}
    store.log_run(run)
    return run
