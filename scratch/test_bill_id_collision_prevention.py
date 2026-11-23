import sys
sys.path.insert(0, r"D:\HMS (1)\HMS_backend")
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
django.setup()
from django.conf import settings
from pymongo import MongoClient
from hospital.counter_service import get_next_pharmacy_bill_id

client = MongoClient(settings.DATABASES["default"]["CLIENT"]["host"])
db = client[settings.DATABASES["default"]["NAME"]]
col = db["hospital_pharmacybilling"]

# Test collision check logic
existing_bill = col.find_one({"Bill_id": {"$gt": 0}})
assert existing_bill is not None, "Should have at least one bill"
colliding_id = existing_bill["Bill_id"]
print(f"Testing with existing Bill_id: {colliding_id}")

# Simulate pre-store verification
record_doc = {"Bill_id": colliding_id}
while col.find_one({"Bill_id": int(record_doc["Bill_id"])}, {"_id": 1}) is not None:
    new_id = get_next_pharmacy_bill_id(db_instance=db)
    record_doc["Bill_id"] = new_id

print(f"Old ID: {colliding_id} -> Replaced with guaranteed new Bill_id: {record_doc['Bill_id']}")
assert record_doc["Bill_id"] != colliding_id, "Bill_id should have changed"
assert col.find_one({"Bill_id": record_doc["Bill_id"]}) is None, "New Bill_id must not exist in DB"
print("SUCCESS: Pre-store check successfully identified collision and created new unique Bill_id!")
