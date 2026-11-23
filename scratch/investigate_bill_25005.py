import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

bill = db['hospital_pharmacybilling'].find_one({'Bill_id': 25005})
if not bill:
    bill = db['hospital_pharmacybilling'].find_one({'bill_no': '262701037554'})

print("=== Found Bill 25005 ===")
print("bill_no:", bill.get('bill_no'))
print("uhid:", bill.get('uhid'))
print("inpatient_number:", bill.get('inpatient_number'))
print("billing_mode:", bill.get('billing_mode'))
print("billing_status:", bill.get('billing_status'))
print("payment_mode:", bill.get('payment_mode'))
print("total_amount in doc:", bill.get('total_amount'))
print("net_amount in doc:", bill.get('net_amount'))
print("discount_amount in doc:", bill.get('discount_amount'))
print("overall_discount_amount:", bill.get('overall_discount_amount'))

meds = bill.get('medicine_particulars', [])
print("Number of medicines:", len(meds))

calc_gross = 0.0
calc_net = 0.0
calc_cgst = 0.0
calc_sgst = 0.0
calc_taxable = 0.0

for idx, m in enumerate(meds):
    t = float(m.get('total') or 0.0)
    q = float(m.get('qty') or 0.0)
    mrp = float(m.get('mrp') or 0.0)
    cp = float(m.get('calculated_price') or 0.0)
    cgst = float(m.get('CGST_Amt') or 0.0)
    sgst = float(m.get('SGST_Amt') or 0.0)
    taxable = float(m.get('taxable_value') or 0.0)
    is_del = m.get('is_deleted', False) or m.get('deleted_is', False)
    
    if not is_del:
        calc_gross += cp
        calc_net += t
        calc_cgst += cgst
        calc_sgst += sgst
        calc_taxable += taxable

print(f"\nCalculated Sum of Active Items:")
print(f"  Sum of calculated_price (Gross): {calc_gross:.2f}")
print(f"  Sum of item total: {calc_net:.2f}")
print(f"  Sum of CGST: {calc_cgst:.2f}")
print(f"  Sum of SGST: {calc_sgst:.2f}")
print(f"  Rounded Net: {round(calc_net)}")

# Check collections for this bill_no or Bill_id
collections_to_check = [
    'hospital_cashcountercollection',
    'hospital_patientdue',
    'hospital_ipsettlement',
    'hospital_ipbilling',
    'hospital_patientdetails',
    'hospital_ipadmission',
    'hospital_pharmacystock'
]

print("\n=== Checking other collections for bill_no 262701037554 ===")
for col_name in db.list_collection_names():
    col = db[col_name]
    # Check if this collection has documents matching bill_no or Bill_id
    doc_count = col.count_documents({'$or': [
        {'bill_no': '262701037554'},
        {'bill_number': '262701037554'},
        {'Bill_id': 25005},
        {'bill_id': 25005}
    ]})
    if doc_count > 0:
        print(f"Found {doc_count} doc(s) in collection '{col_name}':")
        for d in col.find({'$or': [
            {'bill_no': '262701037554'},
            {'bill_number': '262701037554'},
            {'Bill_id': 25005},
            {'bill_id': 25005}
        ]}):
            d_clean = {k: str(v) for k, v in d.items() if k not in ['medicine_particulars', 'items']}
            print(f"  {d_clean}")
