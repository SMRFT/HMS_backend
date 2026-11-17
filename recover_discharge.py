from pymongo import MongoClient
from bson import Timestamp, ObjectId
import time, json, copy

uri = 'mongodb://mongoAdmin:Shinovatest%402026@docker285276-env-4077430.in1.cloudlets.co.in:27017/admin?authSource=admin&directConnection=true'
client = MongoClient(uri, serverSelectionTimeoutMS=10000)
local = client['local']
oplog = local['oplog.rs']

TARGET_ID = ObjectId('6afc33e40ee940f6eef2a7bf')

# Get ALL oplog entries for this document (by _id)
all_ops = list(oplog.find({
    'ns': 'HMS.hospital_dischargebilling',
    '$or': [
        {'o._id': TARGET_ID},      # insert
        {'o2._id': TARGET_ID},     # update/delete
        {'o._id': str(TARGET_ID)}, # just in case
    ]
}).sort('ts', 1))

print(f"Total ops for _id {TARGET_ID}: {len(all_ops)}")
for op in all_ops:
    print(f"  OP={op['op']} TS={op['ts']}")

# The first 'i' op = full original document
insert_op = next((o for o in all_ops if o['op'] == 'i'), None)
if not insert_op:
    print("ERROR: No insert op found!")
    exit(1)

doc = dict(insert_op['o'])
print(f"\nInserted document ip_number: {doc.get('ip_number')}")
print(f"Keys: {list(doc.keys())}")

# Apply all update ops in order to reconstruct final state
def apply_diff(doc, diff):
    """Apply MongoDB v2 diff format to a document."""
    doc = dict(doc)
    if 'u' in diff:  # update fields
        for k, v in diff['u'].items():
            doc[k] = v
    if 'i' in diff:  # insert new fields
        for k, v in diff['i'].items():
            doc[k] = v
    if 'd' in diff:  # delete fields
        for k in diff['d']:
            doc.pop(k, None)
    return doc

for op in all_ops:
    if op['op'] == 'u':
        o = op['o']
        if '$v' in o and o.get('$v') == 2:
            diff = o.get('diff', {})
            doc = apply_diff(doc, diff)
        elif '$set' in o:
            for k, v in o['$set'].items():
                doc[k] = v
        elif '$unset' in o:
            for k in o['$unset']:
                doc.pop(k, None)

print(f"\nReconstructed doc ip_number: {doc.get('ip_number')}")
print(f"Status: {doc.get('status')}")
print(f"Bill no: {doc.get('bill_no','(estimate)')}")

# Save the reconstructed document to a JSON file for review
import bson
def default_serializer(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, (bson.int64.Int64,)):
        return int(obj)
    import datetime
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    from bson import Timestamp as BsonTs
    if isinstance(obj, BsonTs):
        return {'$timestamp': {'t': obj.time, 'i': obj.inc}}
    raise TypeError(f"Not serializable: {type(obj)}")

with open('recovered_S026_008275.json', 'w') as f:
    json.dump(doc, f, indent=2, default=default_serializer)

print("\nSaved to recovered_S026_008275.json")
print("Run restore_discharge.py to insert it back.")
