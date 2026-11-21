import os, json
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz
from datetime import datetime

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

# Sample 5 uhids
sample_uhids = ['S026/000997', 'S026/003526']
exp = db['hospital_patient'].find({'uhid': {'$in': sample_uhids}}, {'uhid': 1, 'created_date': 1}).explain()
print('Winning plan for UHID $in:')
print(json.dumps(exp.get('queryPlanner', {}).get('winningPlan', {}), indent=2, default=str))

# Explain for id $in
exp2 = db['hospital_patient'].find({'id': {'$in': [1003, 3532]}}, {'id': 1, 'created_date': 1}).explain()
print('Winning plan for ID $in:')
print(json.dumps(exp2.get('queryPlanner', {}).get('winningPlan', {}), indent=2, default=str))
