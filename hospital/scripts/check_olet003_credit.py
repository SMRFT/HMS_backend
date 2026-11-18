import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

# Calculate shift credit breakdown for OLET003
shifts_003 = [
    '2627/01/000006', '2627/01/000007', '2627/01/000008',
    '2627/01/000009', '2627/01/000010', '2627/01/000011', '2627/01/000012'
]

from hospital.Views.cashcounter import parse_payment_split

def to_float(val):
    if val is None: return 0.0
    try: return float(val)
    except: return 0.0

print("=== ALL CREDIT BILLS IN OLET003 ON 15/11/2026 ===")
credit_bills = []
for s_no in shifts_003:
    # 1. Billing
    for b in db.hospital_billing.find({'shiftno': s_no, 'payment_status': {'$in': ['Paid', 'Billing']}}):
        fee = to_float(b.get('total_fees', 0))
        c, cr = parse_payment_split(b, fee)
        if cr > 0:
            credit_bills.append((b.get('bill_number') or b.get('bill_no'), cr, 'Billing', s_no))
            
    # 2. Invest
    for inv in db.hospital_investbilling.find({'shiftno': s_no, 'paymentStatus': 'Paid'}):
        amt = to_float(inv.get('finalPrice') or inv.get('total') or 0)
        c, cr = parse_payment_split(inv, amt)
        if cr > 0:
            credit_bills.append((inv.get('investBillNo'), cr, 'Invest', s_no))
            
    # 3. Discharge
    for dis in db.hospital_dischargebilling.find({'shiftno': s_no, 'status': 'Paid'}):
        amt = to_float(dis.get('net_amount', 0))
        c, cr = parse_payment_split(dis, amt)
        if cr > 0:
            credit_bills.append((dis.get('bill_no'), cr, 'Discharge', s_no))
            
    # 4. IP Advance from admissions
    for adm in db.hospital_admission.find({'advance_payments.shiftno': s_no}):
        for p in adm.get('advance_payments', []):
            if p.get('shiftno') == s_no and str(p.get('status', '')).lower() == 'paid':
                amt = to_float(p.get('advance_amount', 0))
                c, cr = parse_payment_split(p, amt)
                if cr > 0:
                    credit_bills.append((p.get('bill_no'), cr, 'Advance', s_no))

tot_cr = sum(x[1] for x in credit_bills)
print(f"Total credit bills in OLET003: {len(credit_bills)}, Total Amt: {tot_cr:.2f}")
for b, amt, cat, s in credit_bills:
    print(f"  {b:15} | ₹{amt:8.2f} | {cat:10} | Shift: {s}")
