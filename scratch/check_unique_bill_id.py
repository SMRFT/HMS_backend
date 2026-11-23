import sys
sys.path.insert(0, r"D:\HMS (1)\HMS_backend")
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES["default"]["CLIENT"]["host"])
db = client[settings.DATABASES["default"]["NAME"]]
col = db["hospital_pharmacybilling"]

types = list(col.aggregate([
    {"$project": {"type": {"$type": "$Bill_id"}}},
    {"$group": {"_id": "$type", "count": {"$sum": 1}}}
]))
print("Bill_id types:")
for t in types:
    print(t)
