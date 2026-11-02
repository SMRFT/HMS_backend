from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)


def get_hms_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client, client['HMS']


def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc


def get_next_bill_type(collection):
    """Auto-increment: MAX(bill_type) + 1. Starts at 1 if empty."""
    pipeline = [{"$group": {"_id": None, "max_bill_type": {"$max": "$bill_type"}}}]
    result = list(collection.aggregate(pipeline))
    if result and result[0].get("max_bill_type") is not None:
        return int(result[0]["max_bill_type"]) + 1
    return 1


# ═══════════════════════════════════════════════════════════════════════
# BILL TYPE MASTER
# ═══════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_bill_types(request):
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']

        # ✅ Get auth codes
        branch_code = request.data.get('auth-branch-code', '')
        hospital_code = request.data.get('auth-hospital-code', '')

        # ✅ Base query (exclude soft deleted)
        query = {'deleted_at': {'$exists': False}}

        # ✅ Apply hospital + branch filter if valid
        if hospital_code and hospital_code != 'system':
            query["hospital_code"] = hospital_code
        if branch_code and branch_code != 'system':
            query["branch_code"] = branch_code

        # 🔍 Search filter
        search = request.query_params.get('search', '').strip()
        if search:
            query['$or'] = [
                {'bill_name':  {'$regex': search, '$options': 'i'}},
                {'billTypeNo': {'$regex': search, '$options': 'i'}},
            ]

        records = [
            serialize_doc(r)
            for r in collection.find(query).sort('bill_name', 1)
        ]

        return Response({'records': records}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_bill_types failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        if client:
            client.close()


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_bill_type(request):
    """
    Create a new bill type.
    bill_type integer is AUTO-GENERATED — never accepted from frontend.
    Returns the generated bill_type in the response so the frontend
    can immediately patch investigation prices.
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']
        data = request.data
        created_by = request.data.get('auth-user-id', "system")
        branch_code = request.data.get('auth-branch-code', "system")
        hospital_code = request.data.get('auth-hospital-code', "system")

        if not data.get('bill_name'):
            return Response({'error': 'Bill Name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not data.get('billTypeNo'):
            return Response({'error': 'Bill Type No is required.'}, status=status.HTTP_400_BAD_REQUEST)

        bill_type_no = str(data['billTypeNo']).strip().upper()

        auto_bill_type = get_next_bill_type(collection)

        ward_med = bool(data.get('ward_medicine', False))
        ward_lab = bool(data.get('ward_lab', False))
        ward_rad = bool(data.get('ward_radiology', False))
        ward_req = bool(data.get('ward_request', False)) or ward_med or ward_lab or ward_rad

        doc = {
            'bill_type':         auto_bill_type,
            'bill_name':         str(data.get('bill_name', '')).strip(),
            'payment_mode':      str(data.get('payment_mode', 'both')),
            'centralCash':       bool(data.get('centralCash', False)),
            'is_allowAdvance':   bool(data.get('is_allowAdvance', False)),
            'is_active':         bool(data.get('is_active', True)),
            'is_allowDiscount':  bool(data.get('is_allowDiscount', False)),
            'sales_return':      bool(data.get('sales_return', False)),
            'GST_export':        bool(data.get('GST_export', False)),
            'IP_billType':       bool(data.get('IP_billType', False)),
            'ward_request':      ward_req,
            'ward_medicine':     ward_med,
            'ward_lab':          ward_lab,
            'ward_radiology':    ward_rad,
            'med_wise_discount': bool(data.get('med_wise_discount', False)),
            'med_dispatch':      bool(data.get('med_dispatch', False)),
            'outlet_code':       str(data.get('outlet_code', '')).strip(),
            'billTypeNo':        bill_type_no,
            'created_at':        datetime.utcnow(),
            'created_by':        created_by,
            'branch_code':       branch_code,
            'hospital_code':     hospital_code,
        }

        result = collection.insert_one(doc)
        return Response(
            {
                'message':   'Created successfully',
                '_id':       str(result.inserted_id),
                'bill_type': auto_bill_type,
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger.exception("create_bill_type failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_bill_type(request, bill_type_int):
    """Update bill type fields. Identified by bill_type integer (immutable unique key)."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']
        data = request.data
        lastmodified_by = request.data.get('auth-user-id', "system")

        allowed_keys = [
            'bill_name', 'payment_mode',
            'centralCash', 'is_allowAdvance', 'is_active', 'is_allowDiscount',
            'sales_return', 'GST_export', 'IP_billType', 'ward_request',
            'ward_medicine', 'ward_lab', 'ward_radiology',
            'med_wise_discount', 'med_dispatch', 'outlet_code', 'billTypeNo',
        ]

        update_fields = {k: data[k] for k in allowed_keys if k in data}

        # Auto-sync ward_request if any module is true
        if any(k in update_fields for k in ['ward_medicine', 'ward_lab', 'ward_radiology']):
            if update_fields.get('ward_medicine') or update_fields.get('ward_lab') or update_fields.get('ward_radiology'):
                update_fields['ward_request'] = True

        new_bill_type_no = update_fields.get('billTypeNo', '').strip().upper()
        if new_bill_type_no:
            update_fields['billTypeNo'] = new_bill_type_no

        update_fields['lastmodified_date'] = datetime.utcnow()
        update_fields['lastmodified_by'] = lastmodified_by

        result = collection.update_one(
            {'bill_type': int(bill_type_int)},
            {'$set': update_fields}
        )

        if result.matched_count == 0:
            return Response({'error': 'Record not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({'message': 'Updated successfully'}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("update_bill_type failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def delete_bill_type(request, bill_type_int):
    """Soft delete. Identified by bill_type integer."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']
        lastmodified_by = request.data.get('auth-user-id', "system")

        result = collection.update_one(
            {'bill_type': int(bill_type_int)},
            {
                '$set': {
                    'deleted_at':        datetime.utcnow(),
                    'lastmodified_date': datetime.utcnow(),
                    'lastmodified_by':   lastmodified_by,
                    'is_active':         False,
                }
            }
        )

        if result.matched_count == 0:
            return Response({'error': 'Record not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({'message': 'Deleted successfully'}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("delete_bill_type failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def patch_bill_type_prices(request):
    """
    Called after creating or editing a Bill Type.

    Payload:
    {
        "bill_type": "57",
        "prices": { "CT01:CT Brain": "900", "CT01:CT Abdomen": "1200" },
        "old_inv_billTypeNo": "USG01"   // optional — sent when category changed on edit
    }

    - If old_inv_billTypeNo is provided and differs from the new category,
      removes the bill_type key from ALL items in that old category.
    - Then patches the new prices into the new category's items.
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']
        lastmodified_by = request.data.get('auth-user-id', "system")

        bill_type         = str(request.data.get('bill_type', '')).strip()
        prices            = request.data.get('prices', {})
        old_inv_cat_no    = str(request.data.get('old_inv_billTypeNo', '')).strip()

        if not bill_type:
            return Response({'error': 'bill_type is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Step 1: Remove bill_type key from old category if category changed ──
        if old_inv_cat_no:
            old_doc = collection.find_one({'billTypeNo': old_inv_cat_no})
            if old_doc:
                old_items = old_doc.get('Items', [])
                for item in old_items:
                    item.pop(bill_type, None)   # remove e.g. "57" key entirely
                collection.update_one(
                    {'billTypeNo': old_inv_cat_no},
                    {'$set': {'Items': old_items, 'last_modified_date': datetime.utcnow(), 'lastmodified_by': lastmodified_by}}
                )

        # ── Step 2: Patch new prices into the new category ──
        if not prices:
            return Response({'message': 'Old prices cleared. No new prices to set.'}, status=status.HTTP_200_OK)

        # Group by invBillTypeNo
        grouped = {}
        for composite_key, price_value in prices.items():
            if ':' not in composite_key:
                continue
            inv_bill_type_no, item_name = composite_key.split(':', 1)
            grouped.setdefault(inv_bill_type_no, {})[item_name] = price_value

        updated_count = 0
        for inv_bill_type_no, item_price_map in grouped.items():
            doc = collection.find_one({'billTypeNo': inv_bill_type_no})
            if not doc:
                continue

            items = doc.get('Items', [])
            changed = False
            for item in items:
                item_name = item.get('itemName', '')
                if item_name in item_price_map:
                    price_val = item_price_map[item_name]
                    if isinstance(price_val, dict):
                        p_str = str(price_val.get('price', '')).strip()
                        n_str = str(price_val.get('nabh_code', '')).strip()
                        if not p_str and not n_str:
                            item.pop(bill_type, None)
                        else:
                            item[bill_type] = {'price': p_str, 'nabh_code': n_str}
                    else:
                        price_str = str(price_val).strip()
                        if price_str == "":
                            item.pop(bill_type, None)
                        else:
                            item[bill_type] = {'price': price_str, 'nabh_code': ''}
                    changed = True

            if changed:
                collection.update_one(
                    {'billTypeNo': inv_bill_type_no},
                    {'$set': {'Items': items, 'last_modified': datetime.utcnow()}}
                )
                updated_count += 1

        return Response(
            {'message': f'Prices patched successfully across {updated_count} categories.'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.exception("patch_bill_type_prices failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def bulk_update_ward_billtype_config(request):
    """
    Bulk update ward request visibility flags for multiple bill types.
    Payload:
    {
        "updates": [
            { "bill_type": 16, "ward_medicine": false, "ward_lab": true, "ward_radiology": false },
            ...
        ]
    }
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']
        updates = request.data.get('updates', [])
        if not isinstance(updates, list) or len(updates) == 0:
            return Response({'error': 'Updates list is required.'}, status=status.HTTP_400_BAD_REQUEST)

        lastmodified_by = request.data.get('auth-user-id', "system")
        updated_count = 0

        for item in updates:
            bt = item.get('bill_type')
            if bt is None:
                continue
            try:
                bt_int = int(bt)
            except (ValueError, TypeError):
                continue

            w_med = bool(item.get('ward_medicine', False))
            w_lab = bool(item.get('ward_lab', False))
            w_rad = bool(item.get('ward_radiology', False))
            w_req = w_med or w_lab or w_rad or bool(item.get('ward_request', False))

            set_fields = {
                'ward_medicine': w_med,
                'ward_lab': w_lab,
                'ward_radiology': w_rad,
                'ward_request': w_req,
                'lastmodified_date': datetime.utcnow(),
                'lastmodified_by': lastmodified_by,
            }

            res = collection.update_one({'bill_type': bt_int}, {'$set': set_fields})
            if res.matched_count > 0:
                updated_count += 1

        return Response(
            {
                'message': f'Successfully updated ward configuration for {updated_count} bill types.',
                'updated_count': updated_count
            },
            status=status.HTTP_200_OK
        )
    except Exception as e:
        logger.exception("bulk_update_ward_billtype_config failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()
