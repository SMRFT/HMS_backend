import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]

billing_col = mongo_db["hospital_pharmacybilling"]
salesreturn_col = mongo_db["hospital_salesreturn"]

ret_94 = salesreturn_col.find_one({"return_bill_no": "262702000094"})
print("Return bill 262702000094:")
print(ret_94)

bill_1643 = billing_col.find_one({"bill_no": "262702041643"})
print("\nOriginal Bill 262702041643:")
print(bill_1643)

bill_1844 = billing_col.find_one({"bill_no": "262702041844"})
print("\nBill 262702041844:")
print(bill_1844)
