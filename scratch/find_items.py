import os
from dotenv import load_dotenv
load_dotenv(override=True)
from pymongo import MongoClient

c = MongoClient(os.getenv('GLOBAL_DB_HOST'))
for db_name in ['HMS', 'Global']:
    for col in c[db_name].list_collection_names():
        if 'item' in col.lower() or 'pharmacy' in col.lower():
            print(f'{db_name}.{col}')

# Check hospital_pharmacyitem in HMS
item_col = c['HMS']['hospital_pharmacyitem']
for iid in [6666, 4913, 8431, 742]:
    doc = item_col.find_one({'item_id': iid})
    if not doc:
        doc = item_col.find_one({'id': iid})
    if doc:
        print(f"Item {iid}: name={doc.get('item_name')}, hsn={doc.get('hsn_code')}")
