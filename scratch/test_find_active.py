import os, time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['Global']
user_collection = db['backend_diagnostics_user']

t0 = time.time()
active_users = list(user_collection.find({"is_active": True}, {"employeeId": 1, "_id": 0}))
print(f'Fetched all {len(active_users)} active users in {time.time()-t0:.3f}s', flush=True)

# Now check membership in memory in Python
query_eids = {'50697', '50199', '50203'}
active_emp_ids = set(str(u.get("employeeId") or "").strip() for u in active_users)
matched = [eid for eid in query_eids if eid in active_emp_ids]
print('Matched:', matched, flush=True)
