import sys
sys.path.insert(0, r"D:\HMS (1)\HMS_backend")
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES["default"]["CLIENT"]["host"])
db = client[settings.DATABASES["default"]["NAME"]]
stock_col = db["hospital_pharmacystock"]

doc = stock_col.find_one({"id": 82891})
print("Doc by id 82891:", doc)
if not doc:
    docs = list(stock_col.find({"item_id": 985, "outlet_code": "OLET001"}))
    print(f"Total docs for item 985 in OLET001: {len(docs)}")
    for d in docs:
        print("id:", d.get("id"), "batch:", d.get("batch_number"), "grn:", d.get("grn_number"), "total_stock:", d.get("total_stock"))
