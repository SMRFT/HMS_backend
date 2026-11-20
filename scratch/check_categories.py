import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

pipeline = [
    {'$match': {'is_active': True, 'is_blocked': False}},
    {'$group': {'_id': '$category', 'count': {'$sum': 1}}}
]
res = list(db['hospital_pharmacyitem'].aggregate(pipeline))
cats = {c.get('category_id') or c.get('id'): c.get('category_name') for c in db['hospital_pharmacycategory'].find()}
for r in sorted(res, key=lambda x: x['count'], reverse=True):
    cid = r['_id']
    cname = cats.get(cid) or cats.get(str(cid)) or 'Unknown'
    print(f'Category {cid} ({cname}): {r["count"]} active items')
