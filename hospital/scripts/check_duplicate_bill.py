import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

col = db['hospital_cashcountercollection']

docs = list(col.find({'$or': [{'bill_no': '262733000004'}, {'bill_number': '262733000004'}]}))
print(f"Found {len(docs)} docs for 262733000004:")
for d in docs:
    print(d)

# Also check hospital_investbilling for 262733000004
inv = db.hospital_investbilling.find_one({'billno': '262733000004'})
print("\nhospital_investbilling for 262733000004:")
print(inv)

