import os, time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

sample_uhids = [d['uhid'] for d in db['hospital_patient'].find({}, {'uhid': 1}).limit(500)]
print(f'Got {len(sample_uhids)} sample uhids', flush=True)

# Test WITH explicit hint('uhid_1')
for n in [100, 200, 500]:
    t0 = time.time()
    res = list(db['hospital_patient'].find({'uhid': {'$in': sample_uhids[:n]}}, {'uhid': 1, 'created_date': 1}).hint('uhid_1'))
    print(f'WITH HINT uhid_1 ({n}): returned {len(res)} in {time.time()-t0:.3f}s', flush=True)
