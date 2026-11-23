import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]

bill_no = "262702041404"
uhid = "S022/007150"

print(f"--- Searching MongoDB HMS for bill_no: {bill_no} ---")
for col_name in mongo_db.list_collection_names():
    col = mongo_db[col_name]
    # Check if bill_no exists
    found = col.find_one({
        "$or": [
            {"bill_no": bill_no},
            {"billno": bill_no},
            {"Bill_no": bill_no},
            {"bill_number": bill_no},
            {"billNumber": bill_no},
            {"BillNo": bill_no}
        ]
    })
    if found:
        print(f"FOUND in collection: {col_name}! _id: {found.get('_id')}")

print(f"\n--- Searching MongoDB HMS for UHID: {uhid} ---")
billing_col = mongo_db["hospital_pharmacybilling"]
for b in billing_col.find({"uhid": uhid}):
    print(f"Bill for UHID {uhid}: bill_no={b.get('bill_no')}, Bill_id={b.get('Bill_id')}, date={b.get('created_date')}, total={b.get('total_amount')}, net={b.get('net_amount')}")

# Also search Global DB
global_db = client["Global"]
print(f"\n--- Searching Global DB ---")
for col_name in global_db.list_collection_names():
    col = global_db[col_name]
    found = col.find_one({"$or": [{"bill_no": bill_no}, {"billno": bill_no}]})
    if found:
        print(f"FOUND in Global DB: {col_name}!")
