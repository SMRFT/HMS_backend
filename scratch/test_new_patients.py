import os, time
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz
from datetime import datetime

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

ist = pytz.timezone('Asia/Kolkata')
s = ist.localize(datetime(2026, 11, 21, 0, 0, 0))

t0 = time.time()
new_pts = list(db['hospital_patient'].find({'created_date': {'$gte': s}}, {'uhid': 1, 'id': 1, 'created_date': 1}))
print(f'New patients created today: {len(new_pts)} in {time.time()-t0:.3f}s', flush=True)
