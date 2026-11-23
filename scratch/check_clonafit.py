import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]
stock_col = mongo_db["hospital_pharmacystock"]

for s in stock_col.find({"batch_number": {"$regex": "^1452008|^145Z008", "$options": "i"}}):
    print(s)
