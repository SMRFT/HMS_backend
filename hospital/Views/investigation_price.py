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


@api_view(['GET'])
def get_investigation_prices(request):
    """List all investigation price records."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        query = {}
        search = request.query_params.get('search', '').strip()
        if search:
            query['$or'] = [
                {'BillType':   {'$regex': search, '$options': 'i'}},
                {'billTypeNo': {'$regex': search, '$options': 'i'}},
            ]

        records = [serialize_doc(r) for r in collection.find(query).sort('BillType', 1)]
        return Response({'records': records}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_investigation_prices failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['POST'])
def create_investigation_price(request):
    """Create a new investigation price record. POST /investigation-prices/create/"""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        data = dict(request.data)

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
            import json
            raw_items = json.loads(raw_items)

        items = [
            {'itemName': str(i.get('itemName', '')).strip()}
            for i in raw_items
            if isinstance(i, dict) and str(i.get('itemName', '')).strip()
        ]

        doc = {
            'BillType':            data['BillType'].strip(),
            'billTypeNo':          bill_type_no,
            'is_active':           bool(data.get('is_active', True)),
            'Items':               items,
            'created_date':        datetime.utcnow(),
            'lastmodified_date':   datetime.utcnow(),
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


@api_view(['PATCH'])
def update_investigation_price(request, bill_type_no):
    """Update by billTypeNo. PATCH /investigation-prices/<bill_type_no>/update/"""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        data   = dict(request.data)
        update = {}

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
            # Check for duplicate only if billTypeNo is actually changing
            if new_no != bill_type_no:
                if collection.find_one({'billTypeNo': new_no}):
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
                import json
                raw_items = json.loads(raw_items)
            update['Items'] = [
                {'itemName': str(i.get('itemName', '')).strip()}
                for i in raw_items
                if isinstance(i, dict) and str(i.get('itemName', '')).strip()
            ]

        update['lastmodified_date'] = datetime.utcnow()

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


@api_view(['PATCH'])
def delete_investigation_price(request, bill_type_no):
    """Soft-delete. PATCH /investigation-prices/<bill_type_no>/delete/"""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        result = collection.update_one(
            {'billTypeNo': bill_type_no},
            {'$set': {'is_active': False, 'lastmodified_date': datetime.utcnow()}}
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