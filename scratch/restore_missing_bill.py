import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.counter_service import get_next_sequence_value
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
hms_db = client['HMS']
billing_col = hms_db['hospital_pharmacybilling']
cc_col = hms_db['hospital_cashcountercollection']

# 1. Safety check: make sure bill_no does not already exist
existing = billing_col.find_one({"bill_no": "262702041404"})
if existing:
    print(f"Bill 262702041404 already exists with Bill_id: {existing.get('Bill_id')}!")
    sys.exit(0)

# 2. Get next unique Bill_id
new_bill_id = get_next_sequence_value("pharmacy_billing_bill_id")
print(f"Assigned new Bill_id: {new_bill_id}")

# 3. Build document
restored_bill = {
    "Bill_id": new_bill_id,
    "bill_no": "262702041404",
    "estimate_no": None,
    "created_by": "60318",
    "created_date": datetime.datetime(2026, 11, 19, 13, 10, 51),
    "bill_date": datetime.datetime(2026, 11, 19, 13, 10, 51),
    "lastmodified_by": "60318",
    "lastmodified_date": datetime.datetime(2026, 11, 19, 13, 14, 9),
    "hospital_code": "SH001",
    "branch_code": "SHB001",
    "outlet_code": "OLET002",
    "is_dispatched": True,
    "pending_returns": [],
    "is_active": True,
    "is_deleted": False,
    "uhid": "S022/007150",
    "inpatient_number": None,
    "bill_type": 42,
    "doctor_id": "60195",
    "doctor_name": "DR.R. MURUGAVEL M.S FAIGES",
    "age": None,
    "room_no": None,
    "medicine_particulars": [
        {
            "item_id": 6666,
            "item_name": "TELZOX TRIO TAP",
            "batch_number": "MT260590",
            "expiry_date": "2027-12-31",
            "hsn_code": "—",
            "qty": 15,
            "price": 16.66,
            "mrp": 16.66,
            "calculated_price": 249.90,
            "product_value": 238.00,
            "taxable_value": 238.00,
            "CGST_Percentage": 2.5,
            "SGST_Percentage": 2.5,
            "CGST_Amt": 5.95,
            "SGST_Amt": 5.95,
            "discount_type": "percent",
            "discount_value": 0.0,
            "discount_percent": "%",
            "discount_amount": 0.0,
            "discount": 0.0,
            "total": 249.90,
            "dispatched_qty": 15,
            "edit_history": []
        },
        {
            "item_id": 4913,
            "item_name": "PROLOMET XL 50MG",
            "batch_number": "GTH2803A",
            "expiry_date": "2028-07-31",
            "hsn_code": "—",
            "qty": 15,
            "price": 6.28,
            "mrp": 6.28,
            "calculated_price": 94.20,
            "product_value": 89.7143,
            "taxable_value": 89.7143,
            "CGST_Percentage": 2.5,
            "SGST_Percentage": 2.5,
            "CGST_Amt": 2.24,
            "SGST_Amt": 2.24,
            "discount_type": "percent",
            "discount_value": 0.0,
            "discount_percent": "%",
            "discount_amount": 0.0,
            "discount": 0.0,
            "total": 94.20,
            "dispatched_qty": 15,
            "edit_history": []
        },
        {
            "item_id": 8431,
            "item_name": "CLONAFIT 0.5MD",
            "batch_number": "145z008",
            "expiry_date": "2029-01-01",
            "hsn_code": "—",
            "qty": 15,
            "price": 37.06,
            "mrp": 37.06,
            "calculated_price": 555.90,
            "product_value": 529.4286,
            "taxable_value": 529.4286,
            "CGST_Percentage": 2.5,
            "SGST_Percentage": 2.5,
            "CGST_Amt": 13.24,
            "SGST_Amt": 13.24,
            "discount_type": "percent",
            "discount_value": 0.0,
            "discount_percent": "%",
            "discount_amount": 0.0,
            "discount": 0.0,
            "total": 555.90,
            "dispatched_qty": 15,
            "edit_history": []
        },
        {
            "item_id": 742,
            "item_name": "NEUROBION FORTE TAB.",
            "batch_number": "88C84301",
            "expiry_date": "2027-10-31",
            "hsn_code": "—",
            "qty": 15,
            "price": 1.58,
            "mrp": 1.58,
            "calculated_price": 23.70,
            "product_value": 22.5714,
            "taxable_value": 22.5714,
            "CGST_Percentage": 2.5,
            "SGST_Percentage": 2.5,
            "CGST_Amt": 0.56,
            "SGST_Amt": 0.56,
            "discount_type": "percent",
            "discount_value": 0.0,
            "discount_percent": "%",
            "discount_amount": 0.0,
            "discount": 0.0,
            "total": 23.70,
            "dispatched_qty": 15,
            "edit_history": []
        }
    ],
    "total_amount": 923.70,
    "total_item_discount": 0.0,
    "discount_amount": 0.0,
    "overall_discount_type": None,
    "overall_discount_value": 0.0,
    "overall_discount_amount": 0.0,
    "net_amount": 924.0,
    "round_off": 0.30,
    "shiftno": "2627/02/000029",
    "payment_mode": "Cash",
    "billing_mode": "DIRECT",
    "billed_id": "60318",
    "cashier_id": "60318",
    "counter_id": "CC0002",
    "paid_date": datetime.datetime(2026, 11, 19, 13, 14, 9),
    "payment_details": {
        "method": "Cash",
        "Paid_amount": 924.0
    },
    "billing_status": "Paid"
}

# 4. Insert into hospital_pharmacybilling
res = billing_col.insert_one(restored_bill)
print(f"Successfully inserted into hospital_pharmacybilling with _id: {res.inserted_id}")

# 5. Link hospital_cashcountercollection to the restored Bill_id
cc_res = cc_col.update_many(
    {"bill_no": "262702041404"},
    {"$set": {"Bill_id": new_bill_id}}
)
print(f"Updated hospital_cashcountercollection Bill_id to {new_bill_id} (matched {cc_res.matched_count}, modified {cc_res.modified_count})")
