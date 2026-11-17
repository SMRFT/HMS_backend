import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

# The 17 bills identified from Paytm transactions:
paytm_matched_bills = [
    ('2627023284', 350.0),
    ('262733000001', 1600.0),
    ('262738000002', 200.0),
    ('2627003029', 15000.0),
    ('2627023286', 550.0),
    ('262738000003', 5000.0),
    ('262733000002', 1600.0),
    ('2627023291', 500.0),
    ('2627003031', 19500.0),
    ('262738000005', 200.0),
    ('262745000001', 8500.0),
    ('2627023293', 400.0),
    ('2627003033', 20000.0),
    ('262733000003', 1710.0),
    ('2627023294', 400.0),
    ('262733000006', 390.0),
    ('2627023295', 400.0),
]

tot_paytm = sum(b[1] for b in paytm_matched_bills)
print(f"Total Paytm Matched: {tot_paytm:.2f}")

# Check how each bill is stored in its source collection:
print("\nBill details in source collections:")
for b_no, amt in paytm_matched_bills:
    # check hospital_billing
    b = db.hospital_billing.find_one({'$or': [{'billno': b_no}, {'bill_no': b_no}, {'bill_number': b_no}]})
    inv = db.hospital_investbilling.find_one({'investBillNo': b_no})
    adm = db.hospital_admission.find_one({'advance_payments.bill_no': b_no})
    ccc = db.hospital_cashcountercollection.find_one({'$or': [{'bill_no': b_no}, {'bill_number': b_no}]})
    
    source = 'Unknown'
    pm = 'N/A'
    pd = 'N/A'
    shift = 'N/A'
    
    if b:
        source = 'Billing'
        pm = b.get('payment_mode') or b.get('payment_method')
        pd = b.get('payment_details')
        shift = b.get('shiftno')
    elif inv:
        source = 'Invest'
        pm = inv.get('payment_method') or inv.get('payment_mode')
        pd = inv.get('payment_details')
        shift = inv.get('shiftno')
    elif adm:
        source = 'Admission Adv'
        for p in adm.get('advance_payments', []):
            if p.get('bill_no') == b_no:
                pm = p.get('payment_mode') or p.get('payment_method')
                pd = p.get('payment_details')
                shift = p.get('shiftno')
    elif ccc:
        source = 'CCC Only'
        pm = ccc.get('payment_mode')
        shift = ccc.get('shift_no')
        
    print(f"Bill {b_no:12} | ₹{amt:8.2f} | Source: {source:13} | Shift: {shift} | Mode: {pm} | Details: {pd}")

