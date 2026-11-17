import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from pymongo import MongoClient
from datetime import datetime, date
import pytz

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

# Compare the exact bills fetched in DateWiseCollectionSummary for 15/11/2026
# Case A: Naive UTC (f_dt = 2026-11-15 00:00:00, t_dt = 2026-11-15 23:59:59)
f_dt_naive = datetime(2026, 11, 15, 0, 0, 0)
t_dt_naive = datetime(2026, 11, 15, 23, 59, 59, 999999)

# Case B: IST-to-UTC (f_dt = 2026-11-14 18:30:00, t_dt = 2026-11-15 18:29:59.999999)
f_dt_ist = datetime(2026, 11, 14, 18, 30, 0)
t_dt_ist = datetime(2026, 11, 15, 18, 29, 59, 999999)

for label, f_dt, t_dt in [("NAIVE UTC (PDF)", f_dt_naive, t_dt_naive), ("IST BOUNDS (CORRECT)", f_dt_ist, t_dt_ist)]:
    date_q = {"created_date": {"$gte": f_dt, "$lte": t_dt}}
    # filter for OLET003 or All
    for scope in ["OLET003", "ALL"]:
        q = dict(date_q)
        if scope == "OLET003":
            q["$or"] = [{"outlet_code": "OLET003"}, {"outlet": "OLET003"}]
        docs = list(db["hospital_cashcountercollection"].find(q))
        tot = sum(float(str(d.get("collected_amount") or 0)) for d in docs)
        print(f"[{label}] Scope: {scope} -> Count: {len(docs)}, Total Collected: {tot:.2f}")

