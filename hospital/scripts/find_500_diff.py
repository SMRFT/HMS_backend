import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

shifts_003 = [
    '2627/01/000006', '2627/01/000007', '2627/01/000008',
    '2627/01/000009', '2627/01/000010', '2627/01/000011', '2627/01/000012'
]

# For each of the 7 shifts, compare the sum of cashcountercollection docs with the shift's recorded cash_amount + credit_amount
from hospital.Views.cashcounter import calculate_shift_collection

for s_no in shifts_003:
    shift_doc = db.hospital_cashcountershiftdetails.find_one({'shiftno': s_no})
    s_cash = float(str(shift_doc.get('collected_Amount', 0)))
    s_credit = float(str(shift_doc.get('CreditAmount', 0)))
    s_tot = s_cash + s_credit
    
    ccc_docs = list(db.hospital_cashcountercollection.find({'shift_no': s_no}))
    ccc_tot = sum(float(str(d.get('collected_amount', 0))) for d in ccc_docs)
    
    calc_res = calculate_shift_collection(s_no)
    calc_tot = calc_res.get('total_collection', 0) + calc_res.get('total_credit', 0)
    
    diff = ccc_tot - s_tot
    print(f"Shift {s_no}:")
    print(f"   ShiftDoc: Cash={s_cash:.2f}, Credit={s_credit:.2f}, Total={s_tot:.2f}")
    print(f"   CCC Docs ({len(ccc_docs)} docs): Total={ccc_tot:.2f} (Diff: {diff:+.2f})")
    print(f"   Calc Shift Collection: Total={calc_tot:.2f}")
    if diff != 0:
        print("   --- Details of CCC docs for this shift ---")
        for d in ccc_docs:
            print(f"       Bill {d.get('bill_no') or d.get('bill_number')}: amt={d.get('collected_amount')}, cat={d.get('billing_category')}, mode={d.get('payment_mode')}")

