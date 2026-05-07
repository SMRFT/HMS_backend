from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
db = client["HMS"]

print("\n--- ReceiptAndPayment ---")
doc = db["hospital_receiptandpayment"].find_one({"description": {"$exists": True}})
if doc:
    print(f"Voucher: {doc.get('voucher_no')}")
    print(f"Description: {doc.get('description')}")
    print(f"Type of Description: {type(doc.get('description'))}")
else:
    print("No document found with description")

client.close()
