import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient
from bson import ObjectId

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]
billing_col = mongo_db["hospital_pharmacybilling"]

doc = billing_col.find_one({"_id": ObjectId("6afef55b36c64ea53d065839")})
print("Full document 6afef55b36c64ea53d065839:")
for k, v in doc.items():
    print(f"  {k}: {repr(v)}")
