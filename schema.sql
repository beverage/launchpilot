-- LaunchPilot — schéma PostgreSQL (Aiven for PostgreSQL)
-- Marque fictive : Maison Aurore. Données 100 % synthétiques.

-- ========== Données de base ==========
CREATE TABLE suppliers (
  supplier_id      TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  category         TEXT NOT NULL,          -- flacon, pompe, etui, coffret, formule
  announced_lead_time_days INT NOT NULL,   -- délai annoncé (contractuel)
  moq              INT NOT NULL,           -- minimum de commande (unités)
  unit_cost_eur    NUMERIC(10,3) NOT NULL
);

CREATE TABLE components (
  component_id     TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  category         TEXT NOT NULL,
  main_supplier_id TEXT REFERENCES suppliers(supplier_id),
  alt_supplier_id  TEXT REFERENCES suppliers(supplier_id)
);

CREATE TABLE products (
  product_id       TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  family           TEXT NOT NULL,          -- soin, parfum, maquillage, coffret
  price_eur        NUMERIC(10,2) NOT NULL,
  margin_rate      NUMERIC(4,3) NOT NULL,
  is_launch        BOOLEAN DEFAULT FALSE,  -- produit du lancement suivi
  launch_week      INT                     -- semaine ISO de mise en marché
);

CREATE TABLE bom (                         -- nomenclature : produit fini -> composants
  product_id       TEXT REFERENCES products(product_id),
  component_id     TEXT REFERENCES components(component_id),
  qty_per_unit     NUMERIC(6,2) NOT NULL,
  PRIMARY KEY (product_id, component_id)
);

CREATE TABLE subcontractors (              -- façonniers
  subcontractor_id TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  weekly_capacity_units INT NOT NULL
);

-- ========== Données transactionnelles ==========
CREATE TABLE sales_history (               -- ventes hebdo par canal
  week             DATE NOT NULL,          -- lundi de la semaine
  product_id       TEXT REFERENCES products(product_id),
  channel          TEXT NOT NULL,          -- eshop, distributeur_selectif, pharmacie
  qty              INT NOT NULL,
  PRIMARY KEY (week, product_id, channel)
);

CREATE TABLE forecasts (
  week             DATE NOT NULL,
  product_id       TEXT REFERENCES products(product_id),
  qty              INT NOT NULL,
  version          TEXT NOT NULL DEFAULT 'v1',
  PRIMARY KEY (week, product_id, version)
);

CREATE TABLE inventory (                   -- photo de stock à date
  snapshot_date    DATE NOT NULL,
  item_id          TEXT NOT NULL,          -- product_id ou component_id
  item_type        TEXT NOT NULL,          -- product / component
  qty              INT NOT NULL,
  PRIMARY KEY (snapshot_date, item_id)
);

CREATE TABLE purchase_orders (             -- commandes packaging (historique + en cours)
  po_id            TEXT PRIMARY KEY,
  supplier_id      TEXT REFERENCES suppliers(supplier_id),
  component_id     TEXT REFERENCES components(component_id),
  qty              INT NOT NULL,
  order_date       DATE NOT NULL,
  promised_date    DATE NOT NULL,
  actual_date      DATE,                   -- NULL = pas encore livrée
  status           TEXT NOT NULL           -- delivered / open
);

-- ========== Flux & mémoire ==========
CREATE TABLE events (                      -- miroir du flux Kafka (et repli)
  event_id         TEXT PRIMARY KEY,
  ts               TIMESTAMP NOT NULL,
  event_type       TEXT NOT NULL,          -- supplier_delay, sellout_spike, capacity_drop, po_confirmed, noise
  payload          JSONB NOT NULL,
  processed        BOOLEAN DEFAULT FALSE
);

-- Mémoire fournisseur : fiabilité réelle apprise de l'historique
CREATE OR REPLACE VIEW supplier_reliability AS
SELECT
  s.supplier_id,
  s.name,
  s.announced_lead_time_days,
  COUNT(*)                                                     AS n_deliveries,
  ROUND(AVG(po.actual_date - po.order_date)::numeric, 1)       AS real_lead_time_days,
  ROUND(STDDEV(po.actual_date - po.order_date)::numeric, 1)    AS lead_time_stddev,
  ROUND(AVG(CASE WHEN po.actual_date > po.promised_date THEN 1 ELSE 0 END)::numeric, 2) AS late_rate
FROM suppliers s
JOIN purchase_orders po ON po.supplier_id = s.supplier_id
WHERE po.status = 'delivered'
GROUP BY s.supplier_id, s.name, s.announced_lead_time_days;

-- ========== Sorties des agents ==========
CREATE TABLE alerts (
  alert_id         SERIAL PRIMARY KEY,
  created_at       TIMESTAMP DEFAULT NOW(),
  source           TEXT NOT NULL,          -- baseline / agent
  trigger_event_id TEXT,
  item_id          TEXT NOT NULL,
  risk_type        TEXT NOT NULL,          -- stockout_component, capacity, demand_surge
  predicted_stockout_week DATE,
  severity         TEXT NOT NULL,          -- low / medium / high
  confidence       NUMERIC(3,2),
  explanation      TEXT
);

CREATE TABLE scenarios (
  scenario_id      SERIAL PRIMARY KEY,
  alert_id         INT REFERENCES alerts(alert_id),
  label            TEXT NOT NULL,
  cost_eur         NUMERIC(12,2),
  lost_revenue_eur NUMERIC(12,2),
  stock_value_eur  NUMERIC(12,2),
  description      TEXT,
  evidence_rows    JSONB                   -- ex. [{"table":"purchase_orders","id":"PO-0042"}]
);

CREATE TABLE decisions (
  decision_id      SERIAL PRIMARY KEY,
  decided_at       TIMESTAMP DEFAULT NOW(),
  alert_id         INT REFERENCES alerts(alert_id),
  scenario_id      INT REFERENCES scenarios(scenario_id),
  decided_by       TEXT,
  comment          TEXT
);

-- Traces d'agents (utile pour la preuve et le debug)
CREATE TABLE agent_runs (
  run_id           SERIAL PRIMARY KEY,
  started_at       TIMESTAMP DEFAULT NOW(),
  agent            TEXT NOT NULL,
  input            JSONB,
  tool_calls       JSONB,
  output           JSONB,
  latency_ms       INT,
  tokens_in        INT,
  tokens_out       INT
);
