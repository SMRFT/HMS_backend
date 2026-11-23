import os, datetime
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]

bill_no = "262702041404"

# 1. Search every single collection in HMS for string "262702041404"
print("=== Exhaustive search for '262702041404' ===")
for col_name in sorted(mongo_db.list_collection_names()):
    col = mongo_db[col_name]
    try:
        # Search by string representation or regex in any field
        count = col.count_documents({
            "$or": [
                {"bill_no": bill_no},
                {"bill_number": bill_no},
                {"Bill_no": bill_no},
                {"billno": bill_no},
                {"BillNo": bill_no},
                {"reference_bill_no": bill_no},
                {"invoice_no": bill_no}
            ]
        })
        if count > 0:
            print(f"Collection '{col_name}' has {count} matching documents!")
            for d in col.find({"$or": [{"bill_no": bill_no}, {"bill_number": bill_no}]}):
                print(f"  _id: {d.get('_id')}, keys: {list(d.keys())[:10]}")
    except Exception as e:
        pass

# 2. Check pharmacy bills created on 2026-11-19 between 18:35 and 18:50 IST (13:05 to 13:20 UTC)
print("\n=== Pharmacy bills created around 2026-11-19 13:05 - 13:25 UTC ===")
billing_col = mongo_db["hospital_pharmacybilling"]
start_utc = datetime.datetime(2026, 11, 19, 13, 0, 0)
end_utc = datetime.datetime(2026, 11, 19, 13, 30, 0)
for b in billing_col.find({"created_date": {"$gte": start_utc, "$lte": end_utc}}):
    print(f"Bill_id: {b.get('Bill_id')}, bill_no: {b.get('bill_no')}, uhid: {b.get('uhid')}, total: {b.get('total_amount')}, net: {b.get('net_amount')}, outlet: {b.get('outlet_code')}, date: {b.get('created_date')}")

# 3. Check bills near bill_no 262702041404
print("\n=== Bills near bill_no 262702041404 ===")
for b in billing_col.find({"bill_no": {"$regex": "^2627020414"}}).sort("bill_no", 1):
    print(f"bill_no: {b.get('bill_no')}, Bill_id: {b.get('Bill_id')}, uhid: {b.get('uhid')}, net: {b.get('net_amount')}, date: {b.get('created_date')}")
