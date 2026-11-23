import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]
salesreturn_col = mongo_db["hospital_salesreturn"]

ret_102 = salesreturn_col.find_one({"return_bill_no": "262702000102"})
print("Return bill 262702000102:")
print(ret_102)
