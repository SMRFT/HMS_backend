import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]

stock_col = mongo_db["hospital_pharmacystock"]
item_col = mongo_db["inventory_pharmacy_item"]

items_info = [
    {"batch": "MT260590", "name": "TELZOX TRIO TAP"},
    {"batch": "GTH2803A", "name": "PROLOMET XL 50MG"},
    {"batch": "145z008", "name": "CLONAFIT 0.5MD"},
    {"batch": "88C84301", "name": "NEUROBION FORTE TAB."}
]

for info in items_info:
    s = stock_col.find_one({"batch_number": {"$regex": f"^{info['batch']}$", "$options": "i"}, "outlet_code": "OLET002"})
    if not s:
        s = stock_col.find_one({"batch_number": {"$regex": f"^{info['batch']}$", "$options": "i"}})
    item_id = s.get("item_id") if s else None
    item_doc = item_col.find_one({"item_id": item_id}) if item_id else None
    print(f"Batch: {info['batch']}")
    print(f"  Stock item_id: {item_id}, batch in stock: {s.get('batch_number') if s else None}")
    if item_doc:
        print(f"  Item name: {item_doc.get('item_name')}, HSN: {item_doc.get('hsn_code')}, id: {item_doc.get('item_id')}")
    else:
        print(f"  Item doc not found for item_id {item_id}")
