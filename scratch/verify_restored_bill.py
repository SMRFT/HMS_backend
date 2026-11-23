import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
hms_db = client['HMS']
doc = hms_db['hospital_pharmacybilling'].find_one({"bill_no": "262702041404"})
print("Found bill in hospital_pharmacybilling:")
for k, v in doc.items():
    print(f"  {k}: {repr(v)}")
