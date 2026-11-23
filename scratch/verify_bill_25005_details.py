import sys
sys.path.insert(0, r'D:\HMS (1)\HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from django.conf import settings
from pymongo import MongoClient
from bson import ObjectId

client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
db = client[settings.DATABASES['default']['NAME']]

bill = db['hospital_pharmacybilling'].find_one({'_id': ObjectId('6aff0da86697998c1dc6d0ca')})

meds = bill.get('medicine_particulars', [])
print("Number of medicines:", len(meds))

total_gross = 0.0
total_item_discount = 0.0
total_net = 0.0
total_cgst = 0.0
total_sgst = 0.0

for idx, m in enumerate(meds):
    qty = float(m.get('qty', 0))
    price = float(m.get('price', 0))
    mrp = float(m.get('mrp', 0))
    cp = float(m.get('calculated_price', 0))
    disc = float(m.get('discount_amount', 0))
    tot = float(m.get('total', 0))
    cgst = float(m.get('CGST_Amt', 0))
    sgst = float(m.get('SGST_Amt', 0))
    
    total_gross += cp
    total_item_discount += disc
    total_net += tot
    total_cgst += cgst
    total_sgst += sgst

rounded_net = round(total_net)
round_off = round(rounded_net - total_net, 2)

print(f"Total Gross (calculated_price sum): {total_gross:.2f}")
print(f"Total Item Discount: {total_item_discount:.2f}")
print(f"Total Net (sum of total): {total_net:.2f}")
print(f"Total CGST: {total_cgst:.2f}")
print(f"Total SGST: {total_sgst:.2f}")
print(f"Rounded Net: {rounded_net}")
print(f"Round Off: {round_off}")

# Check SQL PharmacyBilling
from hospital.models import PharmacyBilling
sql_pb = PharmacyBilling.objects.filter(Bill_id=25005).first()
if sql_pb:
    print(f"\nSQL PharmacyBilling found:")
    print(f"  Bill_id: {sql_pb.Bill_id}")
    print(f"  total_amount: {sql_pb.total_amount}")
    print(f"  net_amount: {sql_pb.net_amount}")
    print(f"  bill_no: {sql_pb.bill_no}")
else:
    print("\nSQL PharmacyBilling record not found for Bill_id 25005")
