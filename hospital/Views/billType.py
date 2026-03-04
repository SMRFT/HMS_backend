from rest_framework.decorators import api_view
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
def get_bill_types(request):
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']

        query = {}
        search = request.query_params.get('search', '').strip()
        if search:
            query['$or'] = [
                {'bill_name':      {'$regex': search, '$options': 'i'}},
                {'billTypeNo':     {'$regex': search, '$options': 'i'}},
                {'billing_outlet': {'$regex': search, '$options': 'i'}},
            ]

        records = [serialize_doc(r) for r in collection.find(query).sort('bill_name', 1)]
        return Response({'records': records}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_bill_types failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['POST'])
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

        if not data.get('bill_name'):
            return Response({'error': 'Bill Name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not data.get('billTypeNo'):
            return Response({'error': 'Bill Type No is required.'}, status=status.HTTP_400_BAD_REQUEST)

        bill_type_no = str(data['billTypeNo']).strip().upper()

        # NOTE: billTypeNo is NOT unique — multiple bill_type records can share the same billTypeNo
        # Uniqueness is guaranteed by the auto-generated bill_type integer only

        auto_bill_type = get_next_bill_type(collection)

        doc = {
            'bill_type':         auto_bill_type,
            'bill_name':         str(data.get('bill_name', '')).strip(),
            'billing_outlet':    str(data.get('billing_outlet', '')).strip(),
            'payment_mode':      str(data.get('payment_mode', 'both')),
            'centralCash':       bool(data.get('centralCash', False)),
            'is_allowAdvance':   bool(data.get('is_allowAdvance', False)),
            'is_active':         bool(data.get('is_active', True)),
            'is_allowDiscount':  bool(data.get('is_allowDiscount', False)),
            'sales_return':      bool(data.get('sales_return', False)),
            'GST_export':        bool(data.get('GST_export', False)),
            'IP_billType':       bool(data.get('IP_billType', False)),
            'ward_request':      bool(data.get('ward_request', False)),
            'med_wise_discount': bool(data.get('med_wise_discount', False)),
            'med_dispatch':      bool(data.get('med_dispatch', False)),
            'department_code':   str(data.get('department_code', '')).strip(),
            'billTypeNo':        bill_type_no,
            'accounts_head':     str(data.get('accounts_head', '')).strip(),
            'created_at':        datetime.utcnow(),
        }

        result = collection.insert_one(doc)
        return Response(
            {
                'message':   'Created successfully',
                '_id':       str(result.inserted_id),
                'bill_type': auto_bill_type,   # ← returned so frontend can patch prices
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
def update_bill_type(request, bill_type_no):
    """Update bill type fields. bill_type integer is immutable. billTypeNo can be updated."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']
        data = request.data

        allowed_keys = [
            'bill_name', 'billing_outlet', 'payment_mode',
            'centralCash', 'is_allowAdvance', 'is_active', 'is_allowDiscount',
            'sales_return', 'GST_export', 'IP_billType', 'ward_request',
            'med_wise_discount', 'med_dispatch', 'department_code', 'accounts_head',
            'billTypeNo',   # allowed to update
        ]

        update_fields = {k: data[k] for k in allowed_keys if k in data}

        # If billTypeNo is being changed, normalise it (no uniqueness check — billTypeNo is non-unique)
        new_bill_type_no = update_fields.get('billTypeNo', '').strip().upper()
        if new_bill_type_no:
            update_fields['billTypeNo'] = new_bill_type_no

        update_fields['last_modified'] = datetime.utcnow()

        result = collection.update_one(
            {'billTypeNo': bill_type_no},
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
def delete_bill_type(request, bill_type_no):
    """Soft delete."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_billtype']

        result = collection.update_one(
            {'billTypeNo': bill_type_no},
            {'$set': {'is_active': False, 'deleted_at': datetime.utcnow()}}
        )

        if result.matched_count == 0:
            return Response({'error': 'Record not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({'message': 'Soft deleted successfully'}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("delete_bill_type failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PATCH'])
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
                    {'$set': {'Items': old_items, 'last_modified': datetime.utcnow()}}
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
            grouped.setdefault(inv_bill_type_no, {})[item_name] = str(price_value).strip()

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
                    if price_val == "":
                        item.pop(bill_type, None)
                    else:
                        item[bill_type] = price_val
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