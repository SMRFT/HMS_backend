import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

shift_no = '2627/01/000007'
print("Checking Shift 7:", shift_no)
# Check billing
b = list(db.hospital_billing.find({'shiftno': shift_no}))
print("Billing:", len(b), [(x.get('billno') or x.get('bill_no'), x.get('total_fees')) for x in b])
# Check invest
inv = list(db.hospital_investbilling.find({'shiftno': shift_no}))
print("Invest:", len(inv), [(x.get('investBillNo'), x.get('finalPrice')) for x in inv])
# Check discharge
dis = list(db.hospital_dischargebilling.find({'shiftno': shift_no}))
print("Discharge:", len(dis), [(x.get('bill_number'), x.get('net_amount')) for x in dis])
# Check admissions
adms = list(db.hospital_admission.find({'advance_payments.shiftno': shift_no}))
print("Admissions:", len(adms))
for a in adms:
    for p in a.get('advance_payments', []):
        if p.get('shiftno') == shift_no:
            print("  Adv payment:", p.get('bill_no'), p.get('advance_amount'))
# Check CCC
ccc = list(db.hospital_cashcountercollection.find({'shift_no': shift_no}))
print("CCC:", len(ccc))

