import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

stk = db['hospital_pharmacystock'].find_one({'item_id': 72079})
print('Stock doc for 72079:', stk)

# Look in grn
grn = db['hospital_grn'].find_one({'grn_number': stk.get('grn_number')}) if stk else None
print('GRN doc:', grn.get('grn_number') if grn else None)
if grn:
    for it in grn.get('items', []):
        if str(it.get('item_id')) == '72079' or str(it.get('batch')) == str(stk.get('batch_number')):
            print('Found in GRN:', it)

# Look in other collections
for colname in db.list_collection_names():
    if 'item' in colname.lower():
        found = db[colname].find_one({'$or': [{'item_id': 72079}, {'item_id': '72079'}, {'id': 72079}]})
        if found:
            print(f'Found 72079 in {colname}: {found.get("item_name") or found.get("itemName")}')
