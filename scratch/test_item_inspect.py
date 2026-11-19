import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

item_15963_stocks = list(db['hospital_pharmacystock'].find({'item_id': 15963}))
print('15963 stocks count:', len(item_15963_stocks))
for s in item_15963_stocks:
    print('outlet_code:', s.get('outlet_code'), 'batch:', s.get('batch_number'), 'total_stock:', s.get('total_stock'))

item_10421_stocks = list(db['hospital_pharmacystock'].find({'item_id': 10421}))
print('10421 stocks count:', len(item_10421_stocks))
for s in item_10421_stocks:
    print('outlet_code:', s.get('outlet_code'), 'batch:', s.get('batch_number'), 'total_stock:', s.get('total_stock'))
