import os
import time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
db = MongoClient(os.getenv('GLOBAL_DB_HOST'))['HMS']

# Aggregate available stock in OLET002
pipeline = [
    {'$match': {'outlet_code': 'OLET002'}},
    {'$project': {
        'item_id': 1,
        'batch_number': 1,
        'expiry_date': 1,
        'mrp': 1,
        'Selling_Price': 1,
        'grn_number': 1,
        'total_stock': {'$ifNull': ['$total_stock', 0]},
        'sold_quantity': {'$ifNull': ['$sold_quantity', 0]},
        'transferred_out_quantity': {'$ifNull': ['$transferred_out_quantity', 0]},
        'grn_return_quantity': {'$ifNull': ['$grn_return_quantity', 0]},
        'blocked_quantity': {'$ifNull': ['$blocked_quantity', 0]},
        'sales_return_quantity': {'$ifNull': ['$sales_return_quantity', 0]}
    }},
    {'$addFields': {
        'avail_stock': {
            '$subtract': [
                '$total_stock',
                {
                    '$subtract': [
                        {
                            '$add': [
                                '$sold_quantity',
                                '$transferred_out_quantity',
                                '$grn_return_quantity',
                                '$blocked_quantity'
                            ]
                        },
                        '$sales_return_quantity'
                    ]
                }
            ]
        }
    }},
    {'$match': {'avail_stock': {'$gt': 0}}}
]

t0 = time.time()
positive_stocks = list(db['hospital_pharmacystock'].aggregate(pipeline))
print(f'Positive stock records in OLET002: {len(positive_stocks)} (took {time.time()-t0:.2f}s)')

item_ids = list({s['item_id'] for s in positive_stocks})
print(f'Distinct item_ids in positive stock: {len(item_ids)}')

# Match with hospital_pharmacyitem
pharmacy_items = {
    it['item_id']: it 
    for it in db['hospital_pharmacyitem'].find(
        {'item_id': {'$in': item_ids}},
        {'item_id': 1, 'item_name': 1, 'category': 1, 'is_active': 1, 'is_blocked': 1}
    )
}

matched_active = []
unmatched = []
inactive_or_blocked = []

for s in positive_stocks:
    iid = s['item_id']
    if iid not in pharmacy_items:
        unmatched.append(iid)
    else:
        it = pharmacy_items[iid]
        if not it.get('is_active', True) or it.get('is_blocked', False):
            inactive_or_blocked.append(it)
        else:
            matched_active.append((s, it))

print(f'Stocks strictly matched and active: {len(matched_active)}')
print(f'Stocks missing from hospital_pharmacyitem: {len(unmatched)} (unique ids: {len(set(unmatched))})')
print(f'Stocks inactive or blocked in hospital_pharmacyitem: {len(inactive_or_blocked)} (unique ids: {len(set(x["item_id"] for x in inactive_or_blocked))})')

print('\nSample inactive/blocked items that were previously shown:')
for it in inactive_or_blocked[:5]:
    print(f"  Item ID: {it.get('item_id')}, Name: {it.get('item_name')}, is_active: {it.get('is_active')}, is_blocked: {it.get('is_blocked')}")

print('\nSample missing items that were previously shown as "Item <id>":')
for mid in list(set(unmatched))[:5]:
    print(f"  Item ID: {mid} -> shown as 'Item {mid}'")
