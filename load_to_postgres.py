"""
Charge schema.sql + les CSV de ./data dans Aiven for PostgreSQL.
Usage : DATABASE_URL="postgres://avnadmin:...@host:port/defaultdb?sslmode=require" python load_to_postgres.py [--reset]
"""
import csv, os, sys, argparse
import psycopg

ap = argparse.ArgumentParser(); ap.add_argument("--reset", action="store_true"); ap.add_argument("--data", default="data")
a = ap.parse_args()
url = os.environ.get("DATABASE_URL") or sys.exit("DATABASE_URL manquant")

TABLES = ["suppliers", "components", "products", "bom", "subcontractors",
          "sales_history", "forecasts", "inventory", "purchase_orders"]

with psycopg.connect(url, autocommit=True) as conn:
    cur = conn.cursor()
    if a.reset:
        cur.execute("DROP VIEW IF EXISTS supplier_reliability CASCADE")
        for t in ["agent_runs", "decisions", "scenarios", "alerts", "events"] + TABLES[::-1]:
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    cur.execute(open("schema.sql", encoding="utf-8").read())
    for t in TABLES:
        path = os.path.join(a.data, f"{t}.csv")
        with open(path, encoding="utf-8") as f:
            header = next(csv.reader(f))
        with cur.copy(f"COPY {t} ({','.join(header)}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')") as cp:
            cp.write(open(path, "rb").read())
        cur.execute(f"SELECT COUNT(*) FROM {t}"); print(f"{t:16s} {cur.fetchone()[0]:5d} lignes")
    cur.execute("SELECT name, announced_lead_time_days, real_lead_time_days, lead_time_stddev, late_rate FROM supplier_reliability ORDER BY late_rate DESC")
    print("\nMémoire fournisseur (vue supplier_reliability) :")
    for r in cur.fetchall(): print("  ", r)
