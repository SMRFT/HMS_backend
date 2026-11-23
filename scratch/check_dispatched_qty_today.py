import os, datetime
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]
billing_col = mongo_db["hospital_pharmacybilling"]

start = datetime.datetime(2026, 11, 23, 0, 0, 0)
cursor = billing_col.find({
    "$or": [
        {"created_date": {"$gte": start}},
        {"bill_date": {"$gte": start}}
    ]
})

missing_count = 0
total_count = 0
missing_bills = []

for b in cursor:
    total_count += 1
    items = b.get("medicine_particulars", [])
    has_missing = any(item.get("dispatched_qty") is None for item in items)
    if has_missing:
        missing_count += 1
        missing_bills.append({
            "bill_no": b.get("bill_no"),
            "Bill_id": b.get("Bill_id"),
            "billing_status": b.get("billing_status"),
            "is_ward_request": b.get("is_ward_request"),
            "billing_mode": b.get("billing_mode")
        })

print(f"Today's total bills: {total_count}, Bills with missing dispatched_qty: {missing_count}")
for mb in missing_bills[:10]:
    print(mb)
