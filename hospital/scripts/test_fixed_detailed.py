import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from pymongo import MongoClient
from datetime import datetime, date, timedelta
from hospital.Views.AccountsReport.accounting_reports import fetch_detailed_billing_data

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

# IST bounds for 15/11/2026
f_d = date(2026, 11, 15)
t_d = date(2026, 11, 15)
f_dt = datetime.combine(f_d, datetime.min.time()) - timedelta(hours=5, minutes=30)
t_dt = datetime.combine(t_d, datetime.min.time()) + timedelta(days=1) - timedelta(hours=5, minutes=30, microseconds=1)

date_q = {
    'created_date': {'$gte': f_dt, '$lte': t_dt},
    '$or': [{'outlet_code': 'OLET003'}, {'outlet': 'OLET003'}]
}

ccc_records = list(db['hospital_cashcountercollection'].find(date_q))
print(f"Total raw CCC records for OLET003 on 15/11/2026 (IST bounds): {len(ccc_records)}")

# Deduplicate
seen = set()
unique_ccc = []
for r in ccc_records:
    b = str(r.get('bill_no') or r.get('bill_number') or '')
    cat = str(r.get('billing_category') or '')
    key = (cat, b)
    if b and key in seen:
        print(f"Skipping duplicate: {key}, amt={r.get('collected_amount')}")
        continue
    if b:
        seen.add(key)
    unique_ccc.append(r)

print(f"Unique CCC records: {len(unique_ccc)}")

enriched = fetch_detailed_billing_data(db, unique_ccc)
print(f"Enriched count: {len(enriched)}")

# Group by category / bill type and print totals
by_type = {}
for e in enriched:
    t = e.get('type_name') or e.get('type')
    by_type.setdefault(t, []).append(e)

tot_gross = 0
tot_cash = 0
tot_cred = 0
tot_bank = 0

print("\n--- CATEGORY BREAKDOWN ---")
for t, items in by_type.items():
    g = sum(x.get('gross', 0) for x in items)
    c = sum(x.get('cash', 0) for x in items)
    cr = sum(x.get('credit', 0) for x in items)
    b = sum(x.get('bank', 0) for x in items)
    tot_gross += g
    tot_cash += c
    tot_cred += cr
    tot_bank += b
    print(f"{t:30} ({len(items):2} bills) -> Gross: {g:10.2f} | Cash: {c:10.2f} | Credit: {cr:10.2f} | Bank: {b:10.2f}")

print("\n--- OVERALL TOTALS ---")
print(f"Gross: {tot_gross:10.2f} | Cash: {tot_cash:10.2f} | Credit: {tot_cred:10.2f} | Bank: {tot_bank:10.2f}")
print(f"Total Collection (Cash + Bank): {(tot_cash + tot_bank):10.2f}")

