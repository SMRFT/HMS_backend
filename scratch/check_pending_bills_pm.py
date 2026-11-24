import sys
sys.path.insert(0, r"D:\HMS (1)\HMS_backend")
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
django.setup()
from django.conf import settings
from pymongo import MongoClient

client = MongoClient(settings.DATABASES["default"]["CLIENT"]["host"])
print("Databases:", client.list_database_names())
print("Current default NAME:", settings.DATABASES["default"]["NAME"])
for dbname in client.list_database_names():
    cols = client[dbname].list_collection_names()
    for c in cols:
        if "pharmacybilling" in c:
            print(f"{dbname}.{c} count: {client[dbname][c].count_documents({})}")
