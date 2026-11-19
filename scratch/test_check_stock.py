import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

pipeline = [
    {'$match': {'outlet_code': 'OLET002', 'total_stock': {'$gt': 0}}},
    {'$group': {'_id': '$item_id'}}
]
ids = [d['_id'] for d in db['hospital_pharmacystock'].aggregate(pipeline)]
pharmacy_items = set(db['hospital_pharmacyitem'].distinct('item_id'))
missing = [i for i in ids if i not in pharmacy_items]
print(f'In OLET002 positive stock: total items={len(ids)}, missing from pharmacyitem={len(missing)}')

for m in missing[:10]:
    stk = db['hospital_pharmacystock'].find_one({'item_id': m, 'outlet_code': 'OLET002'})
    print(f'Missing item_id: {m}, stock_id: {stk.get("stock_id")}, total_stock: {stk.get("total_stock")}, batch: {stk.get("batch_number")}')
