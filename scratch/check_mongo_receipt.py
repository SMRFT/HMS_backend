from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
db = client["HMS"]

print("\n--- ReceiptAndPayment ---")
doc = db["hospital_receiptandpayment"].find_one({"shiftno": {"$exists": True}})
print(doc)

client.close()
