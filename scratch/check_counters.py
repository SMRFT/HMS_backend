import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

uri = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(uri)
mongo_db = client["HMS"]

counters = mongo_db["counters"]
for c in counters.find():
    print(c)
