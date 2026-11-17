import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
from pymongo import MongoClient
from datetime import datetime, date
import pytz

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

col = db['hospital_cashcountercollection']

shifts_003 = [
    '2627/01/000006', '2627/01/000007', '2627/01/000008',
    '2627/01/000009', '2627/01/000010', '2627/01/000011', '2627/01/000012'
]

docs = list(col.find({'shift_no': {'$in': shifts_003}}))

print(f"Total docs: {len(docs)}")

# Let's check how payment mode is stored in these 39 docs, or in their underlying billing docs
from hospital.Views.cashcounter import parse_payment_split

tot_cash = 0
tot_credit = 0

for d in docs:
    b_no = d.get('bill_no') or d.get('bill_number')
    cat = d.get('billing_category')
    amt = float(str(d.get('collected_amount', 0)))
    mode = d.get('payment_mode')
    
    # Check underlying document
    underlying = None
    if cat == 'Billing':
        underlying = db.hospital_billing.find_one({'$or': [{'billno': b_no}, {'bill_no': b_no}]})
    elif cat == 'Investigation':
        underlying = db.hospital_investbilling.find_one({'billno': b_no})
    elif cat in ['Discharge', 'DischargeBills']:
        underlying = db.hospital_dischargebilling.find_one({'bill_number': b_no})
    elif cat in ['IPAdvance Payment', 'IPAdvance', 'advance', 'Advance']:
        # check admission
        underlying = db.hospital_admission.find_one({'advance_payments.bill_no': b_no})
    
    c_amt, cr_amt = 0, 0
    if underlying:
        # get payment details
        c_amt, cr_amt = parse_payment_split(underlying, amt)
    else:
        # fallback to doc
        c_amt, cr_amt = parse_payment_split(d, amt)
        
    tot_cash += c_amt
    tot_credit += cr_amt
    print(f"Bill {b_no} ({cat}): Amt={amt:.2f} -> Cash={c_amt:.2f}, Credit={cr_amt:.2f} | doc mode={mode}, under_mode={underlying.get('payment_mode') or underlying.get('payment_method') if underlying else 'N/A'}")

print(f"\nCalculated Totals from docs: Cash={tot_cash:.2f}, Credit={tot_credit:.2f}, Total={(tot_cash+tot_credit):.2f}")

# Compare with shift recorded totals
shifts = list(db.hospital_cashcountershiftdetails.find({'shiftno': {'$in': shifts_003}}))
shift_cash = sum(float(str(s.get('collected_Amount', 0))) for s in shifts)
shift_credit = sum(float(str(s.get('CreditAmount', 0))) for s in shifts)
print(f"Shift Recorded Totals: Cash={shift_cash:.2f}, Credit={shift_credit:.2f}, Total={(shift_cash+shift_credit):.2f}")
