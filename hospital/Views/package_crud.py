from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from pyauth.auth import HasRoleAndDataPermission
from datetime import datetime
from bson import ObjectId
import os
import json
import logging

logger = logging.getLogger(__name__)


def get_hms_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client, client['HMS']


# ── Helper: serialize ObjectId ────────────────────────────────────────────────
def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc


# ════════════════════════════════════════════════════════════════════════════
#  GET  /packages/               → list all active packages
#  POST /packages/create/        → create a new package
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def get_packages(request):
    """
    Return all active packages.
    Optional query params:
        ?department=<name>
        ?search=<term>        (searches packageName, department)
        ?is_active=true|false  (default: true only)
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_package']

        query = {"is_active": True}

        # Filter: department
        department = request.query_params.get('department', '').strip()
        if department:
            query['department'] = {'$regex': department, '$options': 'i'}

        # Filter: free-text search
        search = request.query_params.get('search', '').strip()
        if search:
            query['$or'] = [
                {'packageName': {'$regex': search, '$options': 'i'}},
                {'department':  {'$regex': search, '$options': 'i'}},
            ]

        packages = [serialize_doc(p) for p in collection.find(query, {"_id": 1, "packageNo": 1,
            "packageName": 1, "department": 1, "department_code": 1,
            "totalPrice": 1, "is_active": 1, "items": 1,
            "created_date": 1, "lastmodified_date": 1})]

        return Response(packages, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_packages failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['POST'])
# @permission_classes([HasRoleAndDataPermission])
def create_package(request):
    """
    Create a new package.
    Payload mirrors the JSON schema:
        packageName, items, department, department_code, totalPrice, is_active
    Auto-generates packageNo (max existing + 1).
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_package']

        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        created_by = data.pop('auth-user-id', 'system')

        # Strip all auth-* keys
        data = {k: v for k, v in data.items() if not k.startswith('auth-')}

        # Validate required fields
        errors = {}
        if not data.get('packageName', '').strip():
            errors['packageName'] = 'Package name is required.'
        if not data.get('items') or not isinstance(data.get('items'), list) or len(data['items']) == 0:
            errors['items'] = 'At least one item is required.'
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        # Auto-increment packageNo
        last = collection.find_one({}, sort=[("packageNo", -1)])
        next_no = (last['packageNo'] + 1) if last and last.get('packageNo') else 1

        # Sanitize items
        sanitized_items = _sanitize_items(data.get('items', []))

        doc = {
            "packageNo":       next_no,
            "packageName":     data.get('packageName', '').strip(),
            "items":           sanitized_items,
            "department":      data.get('department', '').strip(),
            "department_code": data.get('department_code', '').strip(),
            "totalPrice":      str(data.get('totalPrice', '0.00')),
            "is_active":       bool(data.get('is_active', True)),
            "created_by":      created_by,
            "created_date":    datetime.utcnow(),
            "lastmodified_by": created_by,
            "lastmodified_date": datetime.utcnow(),
        }

        result = collection.insert_one(doc)

        return Response(
            {"message": "Package created successfully", "packageNo": next_no, "_id": str(result.inserted_id)},
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger.exception("create_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ════════════════════════════════════════════════════════════════════════════
#  GET    /packages/<packageNo>/   → retrieve single package
#  PATCH  /packages/<packageNo>/   → update package
#  PATCH  /packages/<packageNo>/delete/  → soft delete
# ════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def get_package(request, package_no):
    """Retrieve a single package by packageNo."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_package']

        doc = collection.find_one({"packageNo": int(package_no), "is_active": True})
        if not doc:
            return Response({"error": "Package not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(serialize_doc(doc), status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PATCH'])
# @permission_classes([HasRoleAndDataPermission])
def update_package(request, package_no):
    """
    Update an existing package by packageNo.
    Partial update — only provided fields are changed.
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_package']

        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        modified_by = data.pop('auth-user-id', 'system')

        # Strip immutable / auth keys
        exclude = {'_id', 'packageNo', 'created_by', 'created_date',
                   *[k for k in data.keys() if k.startswith('auth-')]}
        data = {k: v for k, v in data.items() if k not in exclude}

        # Validate items if provided
        if 'items' in data:
            if not isinstance(data['items'], list) or len(data['items']) == 0:
                return Response({"items": "At least one item is required."}, status=status.HTTP_400_BAD_REQUEST)
            data['items'] = _sanitize_items(data['items'])

        if 'totalPrice' in data:
            data['totalPrice'] = str(data['totalPrice'])

        if 'packageName' in data and not str(data['packageName']).strip():
            return Response({"packageName": "Package name cannot be blank."}, status=status.HTTP_400_BAD_REQUEST)

        data['lastmodified_by']   = modified_by
        data['lastmodified_date'] = datetime.utcnow()

        result = collection.update_one(
            {"packageNo": int(package_no), "is_active": True},
            {"$set": data}
        )

        if result.matched_count == 0:
            return Response({"error": "Package not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"message": "Package updated successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("update_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['PATCH'])
# @permission_classes([HasRoleAndDataPermission])
def delete_package(request, package_no):
    """Soft-delete a package (sets is_active=False)."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_package']

        deleted_by = request.data.get('auth-user-id', 'system')

        result = collection.update_one(
            {"packageNo": int(package_no), "is_active": True},
            {"$set": {
                "is_active":    False,
                "deleted_by":   deleted_by,
                "deleted_date": datetime.utcnow(),
            }}
        )

        if result.matched_count == 0:
            return Response({"error": "Package not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"message": "Package deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("delete_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ════════════════════════════════════════════════════════════════════════════
#  Helper
# ════════════════════════════════════════════════════════════════════════════

def _sanitize_items(raw_items):
    """Ensure each item has the expected fields and correct types."""
    clean = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        # Cast test_id to int32, fallback to None if empty or invalid
        raw_test_id = item.get('test_id')
        try:
            test_id = int(raw_test_id) if raw_test_id not in (None, '', 'null') else None
        except (ValueError, TypeError):
            test_id = None

        clean.append({
            "itemName":   str(item.get('itemName', '')).strip(),
            "price":      str(item.get('price', '0')),
            "quantity":   int(item.get('quantity', 1)),
            "billTypeNo": str(item.get('billTypeNo', '')).strip(),
            "test_id":    test_id,   # stored as int32 (or None)
        })
    return clean

@api_view(['GET'])
def get_bill_types(request):
    """
    Return all active bill types from hospital_investigationprice.
    GET /investigation-prices/
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db['hospital_investigationprice']

        bill_types = []
        for doc in collection.find({"is_active": True}, {
            "_id": 0,
            "BillType": 1,
            "billTypeNo": 1,
            "Items": 1,
        }):
            bill_types.append({
                "billTypeNo": doc.get("billTypeNo", ""),
                "BillType":   doc.get("BillType", ""),
                "Items": [
                    {
                        "itemName":  item.get("itemName", ""),
                        # test_id may be stored as a key like "9", "39" etc.
                        # We'll pass all numeric keys as potential prices/test ids
                        "extraKeys": {k: v for k, v in item.items() if k != "itemName"},
                    }
                    for item in doc.get("Items", [])
                    if isinstance(item, dict)
                ],
            })

        return Response({"billTypes": bill_types}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_bill_types failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()

@api_view(['GET'])
def get_lab_items(request):
    
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['Diagnostics']
        collection = db['core_testdetails']

        items = []
        for test in collection.find(
            {"is_active": True},
            {"test_id": 1, "test_name": 1, "SH_Rate": 1, "_id": 0}
        ):
            price = test.get('SH_Rate')
            if price is None or str(price).strip().lower() in ('none', ''):
                price = "0"
            items.append({
                "itemName": test.get('test_name', ''),
                "price":    str(price),
                "test_id":  test.get('test_id', ''),
            })

        return Response({"items": items}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_lab_items failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()

@api_view(['GET'])
def get_departments(request):
   
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['Global']
        collection = db['backend_diagnostics_Departments']

        departments = []
        for doc in collection.find(
            {"is_active": True},
            {"_id": 0, "department_code": 1, "department_name": 1}
        ):
            departments.append({
                "department_code": doc.get("department_code", ""),
                "department_name": doc.get("department_name", ""),
            })

        return Response({"departments": departments}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_departments failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()