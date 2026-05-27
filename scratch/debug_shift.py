import os
from pymongo import MongoClient
from datetime import datetime

# Load env variables manually from .env
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
db = client["HMS"]

from_date = datetime.strptime("2026-05-01", "%Y-%m-%d").replace(hour=0, minute=0, second=0)
to_date = datetime.strptime("2026-05-26", "%Y-%m-%d").replace(hour=23, minute=59, second=59)

q = {"created_date": {"$gte": from_date, "$lte": to_date}}
ccc_docs = list(db["hospital_cashcountercollection"].find(q))
print(f"Total CCC docs for date range: {len(ccc_docs)}")
print("Sample shiftno values:", list(set([d.get("shift_no") for d in ccc_docs[:20]])))
print("Billing categories:", list(set([d.get("billing_category") for d in ccc_docs])))
client.close()
