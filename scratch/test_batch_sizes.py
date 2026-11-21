import os, time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

# Fetch 100 uhids from hospital_patient directly
sample_uhids = [d['uhid'] for d in db['hospital_patient'].find({}, {'uhid': 1}).limit(200)]
print(f'Got {len(sample_uhids)} sample uhids', flush=True)

for n in [10, 50, 100, 200]:
    t0 = time.time()
    res = list(db['hospital_patient'].find({'uhid': {'$in': sample_uhids[:n]}}, {'uhid': 1, 'created_date': 1}))
    print(f'$in with {n} uhids: returned {len(res)} in {time.time()-t0:.3f}s', flush=True)
