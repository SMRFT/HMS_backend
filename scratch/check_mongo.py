from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
db = client["HMS"]

print("--- Billing ---")
doc = db["hospital_billing"].find_one({"shiftno": {"$exists": True}})
print(doc)

print("\n--- InvestBilling ---")
doc = db["hospital_investbilling"].find_one({"shiftno": {"$exists": True}})
print(doc)

print("\n--- DischargeBilling ---")
doc = db["hospital_dischargebilling"].find_one({"shiftno": {"$exists": True}})
print(doc)

client.close()
