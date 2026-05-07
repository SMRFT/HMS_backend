from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
db = client["HMS"]

print("\n--- CashCounter ---")
doc = db["hospital_cashcounter"].find_one({"counter_id": "CC0001"})
if doc:
    for key, val in doc.items():
        print(f"{key}: {val}")
else:
    print("No document found for CC0001")

client.close()
