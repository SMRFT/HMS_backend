from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from datetime import datetime
import os
import logging
import json

logger = logging.getLogger(__name__)


def get_hms_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client, client['HMS']


def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc


def generate_next_item_id(existing_items):
    """Return max item_id + 1, or 1 if no items exist yet."""
    existing_ids = [
        i.get('item_id', 0)
        for i in existing_items
        if isinstance(i.get('item_id'), int)
    ]
    return max(existing_ids, default=0) + 1


# ─────────────────────────────────────────────
# LIST
# ─────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_investigation_prices(request):
    """List all investigation price records."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        branch_code   = request.data.get('auth-branch-code',   'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        query = {}
        if hospital_code:
            query['hospital_code'] = hospital_code
        if branch_code:
            query['branch_code'] = branch_code

        search = request.query_params.get('search', '').strip()
        if search:
            query['$or'] = [
                {'BillType':   {'$regex': search, '$options': 'i'}},
                {'billTypeNo': {'$regex': search, '$options': 'i'}},
            ]

        records = [
            serialize_doc(r)
            for r in collection.find(query).sort('BillType', 1)
        ]
        return Response({'records': records}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_investigation_prices failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ─────────────────────────────────────────────
# CREATE  (auto-assigns item_id to every item)
# ─────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_investigation_price(request):
    """Create a new investigation price record."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        created_by    = request.data.get('auth-user-id',       'system')
        branch_code   = request.data.get('auth-branch-code',   'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')
        data          = dict(request.data)

        # Validation
        errors = {}
        if not str(data.get('BillType',   '')).strip():
            errors['BillType']   = 'Bill Type is required.'
        if not str(data.get('billTypeNo', '')).strip():
            errors['billTypeNo'] = 'Bill Type No is required.'
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        bill_type_no = data['billTypeNo'].strip().upper()
        if collection.find_one({'billTypeNo': bill_type_no}):
            return Response(
                {'billTypeNo': 'Bill Type No already exists.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        raw_items = data.get('Items', [])
        if isinstance(raw_items, str):
            raw_items = json.loads(raw_items)

        # ✅ Auto-assign item_id sequentially starting from 1
        # Preserve all price keys sent alongside itemName
        items = []
        for idx, i in enumerate(raw_items, start=1):
            if not (isinstance(i, dict) and str(i.get('itemName', '')).strip()):
                continue
            item = {k: v for k, v in i.items()}  # preserve all keys (price keys etc.)
            item['itemName'] = str(i['itemName']).strip()
            item['item_id']  = idx                # always overwrite with sequential id
            items.append(item)

        doc = {
            'BillType':      data['BillType'].strip(),
            'billTypeNo':    bill_type_no,
            'is_active':     bool(data.get('is_active', True)),
            'Items':         items,
            'created_date':  datetime.utcnow(),
            'created_by':    created_by,
            'branch_code':   branch_code,
            'hospital_code': hospital_code,
        }

        result = collection.insert_one(doc)
        return Response(
            {'message': 'Created successfully', '_id': str(result.inserted_id)},
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger.exception("create_investigation_price failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ─────────────────────────────────────────────
# UPDATE FULL RECORD
# ─────────────────────────────────────────────
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_investigation_price(request, bill_type_no):
    """
    Update a bill-type record by billTypeNo.
    PATCH /investigation-prices/<bill_type_no>/update/

    For Items:
      - Existing items (have item_id): merged with their full stored document
        so price keys like "9", "58" etc. are NEVER wiped.
      - New items (no item_id): assigned the next available item_id.
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        data         = dict(request.data)
        current_user = request.data.get('auth-user-id', 'system')
        update       = {}

        if 'BillType' in data:
            if not str(data['BillType']).strip():
                return Response(
                    {'BillType': 'Bill Type cannot be blank.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            update['BillType'] = data['BillType'].strip()

        if 'billTypeNo' in data:
            new_no = str(data['billTypeNo']).strip().upper()
            if not new_no:
                return Response(
                    {'billTypeNo': 'Bill Type No cannot be blank.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if new_no != bill_type_no and collection.find_one({'billTypeNo': new_no}):
                return Response(
                    {'billTypeNo': 'Bill Type No already exists.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            update['billTypeNo'] = new_no

        if 'is_active' in data:
            update['is_active'] = bool(data['is_active'])

        if 'Items' in data:
            raw_items = data['Items']
            if isinstance(raw_items, str):
                raw_items = json.loads(raw_items)

            # ✅ Fetch the full existing document to preserve price keys
            existing_doc   = collection.find_one({'billTypeNo': bill_type_no}) or {}
            existing_items = existing_doc.get('Items', [])

            # Build a lookup: item_id → full stored item (with all price keys)
            existing_by_id = {
                i['item_id']: i
                for i in existing_items
                if isinstance(i.get('item_id'), int)
            }
            next_id = generate_next_item_id(existing_items)

            items = []
            for i in raw_items:
                if not (isinstance(i, dict) and str(i.get('itemName', '')).strip()):
                    continue

                item_id = i.get('item_id')

                if isinstance(item_id, int) and item_id in existing_by_id:
                    # ✅ EXISTING item — start from the full stored document
                    # (all price keys intact), then overlay only fields sent from frontend
                    merged = {**existing_by_id[item_id]}   # full original: "9", "58", etc.
                    for k, v in i.items():
                        if k != 'item_id':                 # item_id is never overwritten
                            merged[k] = v
                    merged['item_id']  = item_id
                    merged['itemName'] = str(merged['itemName']).strip()
                    items.append(merged)

                else:
                    # ✅ NEW item — no item_id yet, assign next available
                    item             = {k: v for k, v in i.items() if k != 'item_id'}
                    item['itemName'] = str(i['itemName']).strip()
                    item['item_id']  = next_id
                    next_id         += 1
                    items.append(item)

            update['Items'] = items

        update['last_modified']   = datetime.utcnow()
        update['lastmodified_by'] = current_user

        result = collection.update_one(
            {'billTypeNo': bill_type_no},
            {'$set': update}
        )
        if result.matched_count == 0:
            return Response({'error': 'Record not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({'message': 'Updated successfully'}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("update_investigation_price failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ─────────────────────────────────────────────
# UPDATE SINGLE ITEM by item_id
# ─────────────────────────────────────────────
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_investigation_item(request, bill_type_no, item_id):
    """
    Update a single item inside a bill-type record by its item_id.
    PATCH /investigation-prices/<bill_type_no>/items/<item_id>/update/

    Body: { "itemName": "New Name", "9": "1500", ... }
    Merges into the existing item — price keys not sent are preserved.
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']
        current_user = request.data.get('auth-user-id', 'system')

        doc = collection.find_one({'billTypeNo': bill_type_no})
        if not doc:
            return Response({'error': 'Record not found.'}, status=status.HTTP_404_NOT_FOUND)

        items     = doc.get('Items', [])
        item_id_i = int(item_id)

        # Find the target item index
        target_idx = next(
            (idx for idx, i in enumerate(items) if i.get('item_id') == item_id_i),
            None
        )
        if target_idx is None:
            return Response(
                {'error': f'Item with item_id {item_id} not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # ✅ Strip auth headers from payload before merging
        incoming = {
            k: v
            for k, v in request.data.items()
            if not k.startswith('auth-')
        }

        # ✅ Merge: existing item first (preserves all price keys),
        #    then overlay only the fields explicitly sent
        updated_item             = {**items[target_idx], **incoming}
        updated_item['item_id']  = item_id_i   # item_id is never overwritten
        if 'itemName' in updated_item:
            updated_item['itemName'] = str(updated_item['itemName']).strip()

        items[target_idx] = updated_item

        collection.update_one(
            {'billTypeNo': bill_type_no},
            {
                '$set': {
                    'Items':           items,
                    'last_modified':   datetime.utcnow(),
                    'lastmodified_by': current_user,
                }
            }
        )

        return Response(
            {'message': f'Item {item_id} updated successfully.'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.exception("update_investigation_item failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ─────────────────────────────────────────────
# DELETE SINGLE ITEM by item_id
# ─────────────────────────────────────────────
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def delete_investigation_item(request, bill_type_no, item_id):
    """
    Remove a single item from a bill-type record by its item_id.
    PATCH /investigation-prices/<bill_type_no>/items/<item_id>/delete/
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']
        current_user = request.data.get('auth-user-id', 'system')

        doc = collection.find_one({'billTypeNo': bill_type_no})
        if not doc:
            return Response({'error': 'Record not found.'}, status=status.HTTP_404_NOT_FOUND)

        item_id_i    = int(item_id)
        original_len = len(doc.get('Items', []))

        # ✅ Filter out the item with the matching item_id
        updated_items = [
            i for i in doc.get('Items', [])
            if i.get('item_id') != item_id_i
        ]

        if len(updated_items) == original_len:
            return Response(
                {'error': f'Item with item_id {item_id} not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        collection.update_one(
            {'billTypeNo': bill_type_no},
            {
                '$set': {
                    'Items':           updated_items,
                    'last_modified':   datetime.utcnow(),
                    'lastmodified_by': current_user,
                }
            }
        )

        return Response(
            {'message': f'Item {item_id} deleted successfully.'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.exception("delete_investigation_item failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ─────────────────────────────────────────────
# SOFT-DELETE FULL RECORD
# ─────────────────────────────────────────────
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def delete_investigation_price(request, bill_type_no):
    """Soft-delete a bill-type record. PATCH /investigation-prices/<bill_type_no>/delete/"""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']
        current_user = request.data.get('auth-user-id', 'system')

        result = collection.update_one(
            {'billTypeNo': bill_type_no},
            {
                '$set': {
                    'is_active':    False,
                    'deleted_date': datetime.utcnow(),
                    'deleted_by':   current_user,
                }
            }
        )

        if result.matched_count == 0:
            return Response({'error': 'Record not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({'message': 'Deleted successfully'}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("delete_investigation_price failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()