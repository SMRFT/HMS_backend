import sys
sys.path.insert(0, r"D:\HMS (1)\HMS_backend")
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES["default"]["CLIENT"]["host"])
db = client[settings.DATABASES["default"]["NAME"]]
col = db["hospital_pharmacystock"]

blocked_count = col.count_documents({"blocked_quantity": {"$gt": 0}})
sold_count = col.count_documents({"sold_quantity": {"$gt": 0}})
sales_return_count = col.count_documents({"sales_return_quantity": {"$gt": 0}})

print(f"Stocks with blocked_quantity > 0: {blocked_count}")
print(f"Stocks with sold_quantity > 0: {sold_count}")
print(f"Stocks with sales_return_quantity > 0: {sales_return_count}")

# Check sample with blocked_quantity > 0
sample_blocked = col.find_one({"blocked_quantity": {"$gt": 0}})
if sample_blocked:
    print("Sample blocked stock:")
    print("item_id:", sample_blocked.get("item_id"), "batch:", sample_blocked.get("batch_number"), "blocked:", sample_blocked.get("blocked_quantity"), "sold:", sample_blocked.get("sold_quantity"), "total:", sample_blocked.get("total_stock"))
