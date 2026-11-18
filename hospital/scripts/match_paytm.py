import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
import csv
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

# Load Paytm CSV
paytm_txns = []
with open(r'd:\SMRFT\Projects\HMS\paytm report 15.11.26 Rec.csv', 'r', encoding='utf-8', errors='ignore') as f:
    reader = csv.DictReader(f)
    for r in reader:
        status = r.get('status', '').replace("'", "").strip()
        if status != 'SUCCESS':
            continue
        amt = float(r.get('amount', '0').replace("'", "").strip() or 0)
        t_date = r.get('transaction_date', '').replace("'", "").strip()
        p_mode = r.get('payment_mode', '').replace("'", "").strip()
        order_id = r.get('order_id', '').replace("'", "").strip()
        rrn = r.get('rrncode', '').replace("'", "").strip()
        paytm_txns.append({
            'date': t_date, 'mode': p_mode, 'amount': amt, 'order_id': order_id, 'rrn': rrn
        })

print(f"Total Paytm successful transactions: {len(paytm_txns)}, Total Amount: {sum(t['amount'] for t in paytm_txns):.2f}")

# Look at Credit / Bank collections for 15/11/2026 across OLET003 and OLET002
# From hospital_cashcountershiftdetails:
shifts = list(db.hospital_cashcountershiftdetails.find({
    '$or': [
        {'date': django.utils.timezone.datetime(2026, 11, 15, 0, 0)},
        {'shiftno': {'$regex': '^2627/01/00000[6-9]|^2627/01/00001[0-2]|^2627/02/00001[2-4]'}}
    ]
}))

print("\n--- SHIFT CREDIT TOTALS ---")
tot_shift_credit = 0
for s in shifts:
    c = float(str(s.get('CreditAmount', 0)))
    tot_shift_credit += c
    print(f"Shift {s.get('shiftno')} ({s.get('outlet_code')}): Credit={c:.2f}")
print(f"Total Shift Credit: {tot_shift_credit:.2f}")

# Now find all non-cash bills on 15/11/2026 in OLET003 and OLET002
# Check Paytm vs OLET003:
# OLET003 shift credit = 62,050.00
# Wait! In Paytm:
# Total = 76,300.00
# Let's see: 76,300 - 62,050 = 14,250.00!
# What about OLET002 (Pharmacy)? OLET002 had credit = 18,482.00!
# Did Paytm machine capture transactions from BOTH OLET003 and OLET002?
# Let's match each Paytm amount with hospital bills!
print("\n--- MATCHING PAYTM TRANSACTIONS WITH BILLS ---")
paytm_sorted = sorted(paytm_txns, key=lambda x: x['date'])
from datetime import datetime
from bson.decimal128 import Decimal128
for pt in paytm_sorted:
    amt = pt['amount']
    docs = list(db.hospital_cashcountercollection.find({
        'collected_amount': Decimal128(f"{amt:.2f}"),
        'created_date': {'$gte': datetime(2026, 11, 14, 18, 30), '$lte': datetime(2026, 11, 15, 18, 30)}
    }))
    b_nos = [d.get('bill_no') or d.get('bill_number') for d in docs]
    cats = [d.get('billing_category') for d in docs]
    outlets = [d.get('outlet_code') or d.get('outlet') for d in docs]
    print(f"Paytm: {pt['date']} | {pt['mode']:12} | ₹{amt:8.2f} -> Matched bills: {list(zip(b_nos, cats, outlets))}")
