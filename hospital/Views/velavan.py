from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.core.paginator import Paginator
import json
from ..models import VelavanInvoice,VelavanVendors,VelavanItems
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
from django.conf import settings
import logging
from decimal import Decimal
from bson.decimal128 import Decimal128
import os
from dotenv import load_dotenv
logger = logging.getLogger(__name__)
import certifi
import re
from datetime import datetime
import traceback
from bson.objectid import ObjectId
from datetime import date, datetime
from django.shortcuts import get_object_or_404



client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_vendors(request):
    try:
        vendors_collection = db['hospital_velavan_vendors']

        vendors_collection.update_many(
            {"is_active": {"$exists": False}},
            {"$set": {"is_active": True}}
        )

        def convert_decimal128(obj):
            if isinstance(obj, list):
                return [convert_decimal128(o) for o in obj]
            elif isinstance(obj, dict):
                return {k: convert_decimal128(v) for k, v in obj.items()}
            elif isinstance(obj, Decimal128):
                return float(obj.to_decimal())
            else:
                return obj

        vendors = list(vendors_collection.find({"is_active": True}))
        active_vendors = convert_decimal128(vendors)

        for vendor in active_vendors:
            vendor["id"] = str(vendor["_id"])
            del vendor["_id"]

        return Response(active_vendors, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": "Server error occurred", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def velavan_get_vendors(request):
    try:
        vendors_collection = db["hospital_velavan_vendors"]
        vendors_cursor = vendors_collection.find({
            "$or": [
                {"is_active": True},
                {"is_active": {"$exists": False}}
            ]
        })

        vendors = []
        for vendor in vendors_cursor:
            vendor_data = {}
            for key, value in vendor.items():
                if isinstance(value, ObjectId):
                    vendor_data[key] = str(value)
                elif isinstance(value, Decimal128):
                    vendor_data[key] = float(value.to_decimal())
                elif isinstance(value, datetime):
                    vendor_data[key] = value.isoformat()
                else:
                    vendor_data[key] = value
            vendors.append(vendor_data)

        return Response({"status": "success", "data": vendors}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def velavan_create_vendor(request):
    try:
        data = request.data
        name = data.get("name")
        gstin = data.get("gstin")

        user_id = data.get('auth-user-id', 'system')
        outlet_code = data.get('outlet_code','OLET005')
        branch_code = data.get('auth-branch-code', 'SHB001')        
        hospital_code = data.get('auth-hospital-code', 'SH001')

        if not name:
            return Response(
                {"success": False, "message": "Vendor Name is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not gstin:
            return Response(
                {"success": False, "message": "GSTIN is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        vendors_collection = db["hospital_velavan_vendors"]
        existing = vendors_collection.find_one({
            "name": name,
            "gstin": gstin,
            "is_active": True
        })

        if existing:
            return Response(
                {"success": False, "message": "Vendor with same name and GSTIN already exists"},
                status=status.HTTP_400_BAD_REQUEST
            )

        all_vendor_ids = vendors_collection.distinct("vendor_id")
        max_id = 0
        for vid in all_vendor_ids:
            try:
                numeric_id = int(vid)
                if numeric_id > max_id:
                    max_id = numeric_id
            except (ValueError, TypeError):
                continue
        new_vendor_id = str(max_id + 1)

        now = datetime.now()
        vendor_doc = {
            "vendor_id":        new_vendor_id,
            "name":             name,
            "addressLine1":     data.get("addressLine1", ""),
            "addressLine2":     data.get("addressLine2", ""),
            "city":             data.get("city", ""),
            "state":            data.get("state", ""),
            "pincode":          data.get("pincode", ""),
            "contactPerson":    data.get("contactPerson", ""),
            "phone":            data.get("phone", ""),
            "email":            data.get("email", ""),
            "kgstTinNumber":    data.get("kgstTinNumber", ""),
            "gstin":            gstin,
            "payment":          data.get("payment", ""),
            "tdsPercent":       data.get("tdsPercent", None),
            "is_active":        True,
            "created_by":       user_id,
            "created_date":     now,
            "lastmodified_by":  user_id,
            "lastmodified_date": now,
            "branch_code":      branch_code,
            "outlet_code":  outlet_code,
            "hospital_code":    hospital_code,
        }

        result = vendors_collection.insert_one(vendor_doc)

        return Response(
            {
                "success": True,
                "message": "Vendor created successfully",
                "data": {
                    "id": str(result.inserted_id),
                    "vendor_id": new_vendor_id,
                    "name": name,
                    "gstin": gstin,
                }
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def velavan_update_vendor(request, vendor_id):
    try:
        vendors_collection = db["hospital_velavan_vendors"]

        data = request.data.copy()

        fields_to_remove = ["_id"]
        auth_fields = [key for key in data.keys() if key.startswith("auth-")]
        fields_to_remove.extend(auth_fields)
        for field in fields_to_remove:
            data.pop(field, None)

        data["lastmodified_by"] = request.data.get("auth-user-id")
        data["lastmodified_date"] = datetime.now()

        result = vendors_collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {"$set": data}
        )

        if result.matched_count == 0:
            return Response(
                {"status": "error", "message": "Vendor not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        updated_vendor = vendors_collection.find_one({"_id": ObjectId(vendor_id)})

        for key, value in updated_vendor.items():
            if isinstance(value, ObjectId):
                updated_vendor[key] = str(value)
            elif isinstance(value, Decimal128):
                updated_vendor[key] = float(value.to_decimal())
            elif isinstance(value, datetime):
                updated_vendor[key] = value.isoformat()

        return Response(
            {"status": "success", "data": updated_vendor},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def velavan_delete_vendor(request, vendor_id):
    try:
        vendors_collection = db["hospital_velavan_vendors"]

        result = vendors_collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {"$set": {
                "is_active": False,
                "deleted_by": request.data.get("auth-user-id"),
                "deleted_date": datetime.now()
            }}
        )

        if result.matched_count == 0:
            return Response(
                {"status": "error", "message": "Vendor not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {"status": "success", "message": "Vendor deleted successfully"},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_items(request):
    try:
        items_collection = db["hospital_velavan_items"]

        items_collection.update_many(
            {"is_active": {"$exists": False}},
            {"$set": {"is_active": True}}
        )

        active_items = list(items_collection.find(
            {"is_active": True},
            {"_id": 1, "itemName": 1, "hsn": 1}
        ))

        for item in active_items:
            item["id"] = str(item["_id"])
            del item["_id"]

        return Response(active_items, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": "Server error occurred", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def velavan_get_items(request):
 
    items = db['hospital_velavan_items'].find(
        {"is_active": True},
        {"_id": 1, "itemName": 1, "hsn": 1}
    )
 
    data = [
        {
            "id": str(item["_id"]),
            "itemName": item.get("itemName", ""),
            "hsn": item.get("hsn", ""),
        }
        for item in items
    ]
 
    client.close()
    return Response({"status": "success", "data": data}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def velavan_create_item(request):
    try:
        item_name = request.data.get("itemName")
        hsn = request.data.get("hsn")
        data = request.data
        user_id = data.get('auth-user-id', 'system')
        outlet_code = data.get('outlet_code','OLET005')
        branch_code = data.get('auth-branch-code', 'SHB001')        
        hospital_code = data.get('auth-hospital-code', 'SH001')
        

        if not item_name:
            return Response(
                {"success": False, "message": "Item Name is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        existing_item = VelavanItems.objects.filter(
            itemName=item_name,
            hsn=hsn,
            is_active=True
        ).first()

        if existing_item:
            return Response(
                {
                    "success": False,
                    "message": "Item with same name and HSN already exists"
                },
                status=status.HTTP_400_BAD_REQUEST
            )
    
        item = VelavanItems.objects.create(
            itemName=item_name,
            hsn=hsn,
            created_by=user_id,
            branch_code=branch_code,
            outlet_code=outlet_code,
            hospital_code=hospital_code
        )

        return Response(
            {
                "success": True,
                "message": "Item created successfully",
                "data": {
                    "id": str(item.id),
                    "itemName": item.itemName,
                    "hsn": item.hsn
                }
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
def velavan_update_item(request, item_id):
    try:       
        items_collection = db["hospital_velavan_items"]
        
        data = request.data.copy()
        
        fields_to_remove = ["_id"]
        auth_fields = [key for key in data.keys() if key.startswith("auth-")]
        fields_to_remove.extend(auth_fields)
        
        for field in fields_to_remove:
            data.pop(field, None)
        
        data["lastmodified_by"] = request.data.get("auth-user-id")
        data["lastmodified_date"] = datetime.now()

        result = items_collection.update_one(
            {"_id": ObjectId(item_id)}, 
            {"$set": data}
        )
        
        if result.matched_count == 0:
            return Response(
                {"status": "error", "message": "Item not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        updated_item = items_collection.find_one({"_id": ObjectId(item_id)})
        
        for key, value in updated_item.items():
            if isinstance(value, ObjectId):
                updated_item[key] = str(value)
            elif isinstance(value, Decimal128):
                updated_item[key] = float(value.to_decimal())
            elif isinstance(value, datetime):
                updated_item[key] = value.isoformat()

        return Response(
            {"status": "success", "data": updated_item}, 
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {"status": "error", "message": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def velavan_delete_item(request, item_id):
    try:
        items_collection = db["hospital_velavan_items"]

        result = items_collection.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {
                "is_active": False,
                "lastmodified_by": request.data.get("auth-user-id"),
                "lastmodified_date": datetime.now()
            }}
        )

        if result.matched_count == 0:
            return Response(
                {"status": "error", "message": "Item not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {"status": "success", "message": "Item deleted successfully"},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_velavan_in(request):
    try:
        data = request.data
        summary = data.get('summary', {})
        outlet_code = data.get('outlet_code','OLET005')
        branch_code = data.get('auth-branch-code', 'SHB001')        
        hospital_code = data.get('auth-hospital-code', 'SH001')

        def to_decimal(val, default=0):
            try:
                return float(val) if val not in (None, '') else default
            except (ValueError, TypeError):
                return default

        def to_date(val):
            if not val:
                return None
            if isinstance(val, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', val):
                return val
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                return None

        def sanitize_value(v):
            try:
                from bson import ObjectId as BsonObjectId
                if isinstance(v, BsonObjectId):
                    return str(v)
            except ImportError:
                pass
            if isinstance(v, Decimal):
                return float(v)
            from datetime import date, datetime as dt
            if isinstance(v, (date, dt)):
                return v.isoformat()
            if isinstance(v, dict):
                return {k2: sanitize_value(v2) for k2, v2 in v.items()}
            if isinstance(v, list):
                return [sanitize_value(i) for i in v]
            try:
                json.dumps(v)
                return v
            except (TypeError, ValueError):
                return str(v)

        def sanitize_items(items):
            return [
                {k: sanitize_value(v) for k, v in item.items()}
                for item in items
            ]

        employee_id = data.get('auth-user-id') or 'Anonymous'
        total_amount = to_decimal(summary.get('totalAmount'))
        clean_items = sanitize_items(data.get('items', []))

        invoice = VelavanInvoice(
            vendor_id               = data.get('vendor_id') or '',
            date                    = to_date(data.get('date')),
            invoice_no              = data.get('invoiceNo') or '',
            invoice_date            = to_date(data.get('invoiceDate')),
            payment_mode            = data.get('paymentMode') or '',
            ip_number               = data.get('ipNumber') or '',
            patient_name            = data.get('patientName') or '',
            surgeon_id            = data.get('surgeonName') or '',
            items                   = clean_items,
            non_taxable_amount      = to_decimal(summary.get('nonTaxableAmount')),
            taxable_amount          = to_decimal(summary.get('taxableAmount')),
            tax_paid_to_supplier    = to_decimal(summary.get('taxPaidToSupplier')),
            local_tax               = to_decimal(summary.get('localTax')),
            remarks                 = summary.get('remarks') or '',
            cgst                    = to_decimal(summary.get('cgst')),
            sgst                    = to_decimal(summary.get('sgst')),
            igst                    = to_decimal(summary.get('igst')),
            cess                    = to_decimal(summary.get('cess')),
            central_sales_tax       = to_decimal(summary.get('centralSalesTax')),
            round_amount            = to_decimal(summary.get('roundAmount')),
            total_amount            = total_amount,
            total_discount          = to_decimal(summary.get('totalDiscount')),
            net_invoice_amount      = to_decimal(summary.get('netInvoiceAmount')),
            quotation_rate          = to_decimal(summary.get('quotationRate')),
            created_by              = employee_id,
            branch_code             = branch_code,
            hospital_code           = hospital_code,
            outlet_code             = outlet_code,
        )

        invoice.save()

        return JsonResponse({
            'success':    True,
            'status':     'success',
            'message':    'VelavanInvoice created successfully',
            'grn_number': str(invoice.grn_number),
            'id':         str(invoice.pk),
        }, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'status':  'error',
            'message': str(e),
        }, status=500)
    

def convert_decimal128_to_float(value):
    """Convert Decimal128 or other numeric types to float safely"""
    if value is None:
        return 0.0
    
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    elif isinstance(value, Decimal):
        return float(value)
    elif isinstance(value, (int, float)):
        return float(value)
    elif isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    else:
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
@csrf_exempt
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_velavan_invoices(request):
    try:
        logger.debug(f"Request headers: {request.headers}")
        logger.debug(f"Request user: {request.user}, Query params: {request.GET}")

        # ── MongoDB connections ──
        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db    = mongo_client['Global']
        profile_collection = global_db['backend_diagnostics_profile']

        hms_client  = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db_name = os.getenv('HMS_DB_NAME', 'hms')
        hms_db      = hms_client[hms_db_name]

        invoice_collection = hms_db['hospital_velavaninvoice']  # ✅ correct collection name

        from_date_str = request.GET.get('from_date', None)
        to_date_str   = request.GET.get('to_date', None)

        # ── Build PyMongo filter ──
        mongo_filter = {}
        if from_date_str:
            try:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
                mongo_filter.setdefault('invoice_date', {})['$gte'] = from_date
            except ValueError:
                logger.warning(f"Invalid from_date format: {from_date_str}")

        if to_date_str:
            try:
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                mongo_filter.setdefault('invoice_date', {})['$lte'] = to_date
            except ValueError:
                logger.warning(f"Invalid to_date format: {to_date_str}")

        # ── Pagination ──
        try:
            page      = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 10))
            if page < 1:      page = 1
            if page_size < 1: page_size = 10
        except ValueError:
            page, page_size = 1, 10

        total_records = invoice_collection.count_documents(mongo_filter)
        total_pages   = (total_records + page_size - 1) // page_size
        skip          = (page - 1) * page_size

        # ── Fetch raw docs directly from PyMongo ──
        raw_docs = list(
            invoice_collection.find(mongo_filter)
            .sort('created_date', -1)
            .skip(skip)
            .limit(page_size)
        )

        logger.debug(f"Fetched {len(raw_docs)} raw docs from hospital_velavaninvoice")

        # ── Pre-fetch all vendor details ──
        vendor_ids = list(set(
            str(doc.get('vendor_id'))
            for doc in raw_docs
            if doc.get('vendor_id')
        ))
        vendor_map = {}
        for vid in vendor_ids:
            try:
                vendor = VelavanVendors.objects.get(vendor_id=vid)
                vendor_map[vid] = {
                    'vendor':  vendor.name,
                    'phone':   vendor.phone or '',
                    'gstin':   vendor.gstin or '',
                    'address': f"{vendor.addressLine1}, {vendor.addressLine2}, {vendor.city}, {vendor.state}".strip(', '),
                    'email':   vendor.email or ''
                }
            except VelavanVendors.DoesNotExist:
                logger.warning(f"Vendor {vid} not found")
                vendor_map[vid] = {'vendor': '', 'phone': '', 'gstin': '', 'address': '', 'email': ''}

        # ── Pre-fetch all surgeon names in one Global DB query ──
        surgeon_ids = list(set(
            str(doc.get('surgeon_id'))
            for doc in raw_docs
            if doc.get('surgeon_id')
        ))
        logger.debug(f"Unique surgeon_ids on this page: {surgeon_ids}")

        surgeon_name_map = {}
        if surgeon_ids:
            try:
                profiles = profile_collection.find(
                    {'employeeId': {'$in': surgeon_ids}},
                    {'employeeId': 1, 'employeeName': 1, '_id': 0}
                )
                for profile in profiles:
                    surgeon_name_map[profile['employeeId']] = profile.get('employeeName', '')
                logger.debug(f"Resolved surgeon_name_map: {surgeon_name_map}")
            except Exception as e:
                logger.warning(f"Could not fetch surgeon profiles: {e}")

        # ── Build response ──
        response_data = []
        for doc in raw_docs:
            try:
                grn_number   = doc.get('grn_number')
                vendor_id    = str(doc.get('vendor_id', ''))
                surgeon_id   = doc.get('surgeon_id')
                surgeon_name = surgeon_name_map.get(str(surgeon_id), '') if surgeon_id else ''

                vendor_details = vendor_map.get(vendor_id, {
                    'vendor': '', 'phone': '', 'gstin': '', 'address': '', 'email': ''
                })

                # ── Parse items ──
                raw_items = doc.get('items', [])
                if isinstance(raw_items, str):
                    try:
                        items = json.loads(raw_items)
                        if not isinstance(items, list):
                            items = []
                    except json.JSONDecodeError:
                        items = []
                elif isinstance(raw_items, list):
                    items = raw_items
                else:
                    items = []

                for item in items:
                    numeric_item_fields = [
                        'itemValue', 'packingPrice', 'unitPrice', 'cgstAmt', 'sgstAmt',
                        'purchaseCost', 'mrp', 'tax', 'cgstPercent', 'sgstPercent'
                    ]
                    for field in numeric_item_fields:
                        if field in item:
                            item[field] = convert_decimal128_to_float(item[field])

                total_amount_paid = convert_decimal128_to_float(doc.get('total_amount_paid', 0))
                total_amount      = convert_decimal128_to_float(doc.get('total_amount', 0))
                pending_amount    = max(0.0, total_amount - total_amount_paid)

                item_data = {
                    'id':              str(doc.get('_id')),
                    'grn_number':      grn_number,
                    'vendor_id':       doc.get('vendor_id'),
                    'vendor':          vendor_details['vendor'],
                    'phone':           vendor_details['phone'],
                    'gstin':           vendor_details['gstin'],
                    'address':         vendor_details['address'],
                    'pending_amount':  pending_amount,
                    'invoice_no':      doc.get('invoice_no'),
                    'payment_mode':    doc.get('payment_mode'),
                    'remarks':         doc.get('remarks') or '',
                    'created_by':      doc.get('created_by'),
                    'ip_number':       doc.get('ip_number'),
                    'patient_name':    doc.get('patient_name'),
                    'surgeon_id':      surgeon_id,
                    'surgeon_name':    surgeon_name,
                    'items':           items,
                    'lastmodified_by': doc.get('lastmodified_by'),
                }

                # ── Date fields ──
                date_fields = ['date', 'invoice_date', 'due_date', 'created_date', 'lastmodified_date']
                for field in date_fields:
                    value = doc.get(field)
                    item_data[field] = value.isoformat() if hasattr(value, 'isoformat') else str(value) if value else None

                # ── Numeric fields ──
                numeric_fields = [
                    'non_taxable_amount', 'taxable_amount', 'tax_paid_to_supplier',
                    'local_tax', 'cgst', 'sgst', 'igst', 'cess', 'central_sales_tax',
                    'round_amount', 'total_amount', 'tax_on_free_items', 'total_discount',
                    'net_invoice_amount', 'quotation_rate', 'courier_transport_charge'
                ]
                for field in numeric_fields:
                    item_data[field] = convert_decimal128_to_float(doc.get(field))

                response_data.append(item_data)

            except Exception as item_error:
                logger.error(f"Error processing doc {doc.get('grn_number')}: {str(item_error)}\n{traceback.format_exc()}")
                response_data.append({
                    'id':           str(doc.get('_id')),
                    'grn_number':   doc.get('grn_number'),
                    'vendor_id':    doc.get('vendor_id'),
                    'vendor':       '',
                    'surgeon_id':   doc.get('surgeon_id'),
                    'surgeon_name': '',
                    'items':        [],
                    'error':        f'Processing failed: {str(item_error)}'
                })

        return Response({
            'status': 'success',
            'data': response_data,
            'pagination': {
                'current_page':  page,
                'total_pages':   total_pages,
                'total_records': total_records,
                'has_next':      page < total_pages,
                'has_previous':  page > 1,
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in list_velavan_invoices: {str(e)}\n{traceback.format_exc()}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        try:
            mongo_client.close()
        except Exception:
            pass
        try:
            hms_client.close()
        except Exception:
            pass


# Recursive cleaner to convert Decimal128 & ObjectId to JSON-safe types
def clean_mongo_document(doc):
    if isinstance(doc, dict):
        return {k: clean_mongo_document(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [clean_mongo_document(i) for i in doc]
    elif isinstance(doc, Decimal128):
        return float(doc.to_decimal())
    elif isinstance(doc, ObjectId):
        return str(doc)
    return doc

def convert_decimal128_to_float(value):
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    try:
        return float(value)
    except Exception:
        return value
    
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_previous_purchases(request):
    hsn = request.GET.get('hsn')
    item_name = request.GET.get('item_name')

    if not hsn or not item_name:
        return Response({'status': 'error', 'message': 'HSN and Item Name are required'}, status=400)

    try:       
        purchases_collection = db["hospital_velavaninvoice"]
        vendors_collection   = db["hospital_velavan_vendors"]

        documents = purchases_collection.find({})
        matched_purchases = []

        for doc in documents:
            items = doc.get('items', [])
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except json.JSONDecodeError as e:
                    print(f"Error parsing items for GRN {doc.get('grn_number')}: {e}")
                    continue
            elif not isinstance(items, list):
                continue

            payment_details = doc.get('payment_details', {})
            if isinstance(payment_details, str):
                try:
                    payment_details = json.loads(payment_details)
                except json.JSONDecodeError:
                    payment_details = {}
            if not isinstance(payment_details, dict):
                payment_details = {}
            else:
                for field in ['amount_paid', 'pending_amount']:
                    if field in payment_details:
                        payment_details[field] = convert_decimal128_to_float(payment_details[field])

            for item in items:
                mongo_name = " ".join(item.get('name', '').strip().split())
                input_name = " ".join(item_name.strip().split())

                if str(item.get('hsn', '')).strip() == str(hsn).strip() and mongo_name.lower() == input_name.lower():
                    doc['matched_item']    = item
                    doc['payment_details'] = payment_details

                    vendor_name = None
                    vendor_id   = doc.get('vendor_id')
                    if vendor_id:
                        vendor_doc = vendors_collection.find_one({
                            "$or": [
                                {"vendor_id": str(vendor_id).strip()},
                                {"vendor_id": int(vendor_id)}
                            ]
                        })
                        if vendor_doc:
                            vendor_name = vendor_doc.get('name')
                    doc['vendor_name'] = vendor_name

                    matched_purchases.append(clean_mongo_document(doc))
                    break

        return Response({'status': 'success', 'data': matched_purchases}, status=200)

    except Exception as e:
        print(f"Error in get_previous_purchases: {e}")
        return Response({'status': 'error', 'message': str(e)}, status=500)


def normalize_dates(data):
    """Convert date/datetime objects into ISO strings recursively"""
    for key, value in data.items():
        if isinstance(value, date) and not isinstance(value, datetime):
            data[key] = value.isoformat()
        elif isinstance(value, datetime):
            data[key] = value.isoformat()
        elif isinstance(value, dict):
            normalize_dates(value)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                if isinstance(v, (date, datetime)):
                    data[key][i] = v.isoformat()
                elif isinstance(v, dict):
                    normalize_dates(v)
    return data


def parse_date_field(value):
    """Parse a date string or date/datetime object into a datetime object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        value = value.strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
            try:
                return datetime.strptime(value[:len(fmt)], fmt)
            except ValueError:
                continue
    logger.warning(f"Could not parse date value: {value!r}")
    return None

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_velavan_invoice(request, grn_number):
    try:
        collection = db["hospital_velavaninvoice"]

        document = collection.find_one({"grn_number": grn_number})
        if not document:
            logger.warning(f"No record found for GRN {grn_number}")
            return Response({
                'status': 'error',
                'message': f'No record found for GRN {grn_number}'
            }, status=status.HTTP_404_NOT_FOUND)

        data    = request.data
        summary = data.get('summary', {})

        parsed_date         = parse_date_field(data.get('date'))
        parsed_invoice_date = parse_date_field(data.get('invoiceDate'))
        parsed_due_date     = parse_date_field(data.get('dueDate'))

        # ✅ Always store items as a parsed list (not a JSON string)
        raw_items = data.get('items', [])
        if isinstance(raw_items, str):
            try:
                items_to_store = json.loads(raw_items)
                if not isinstance(items_to_store, list):
                    items_to_store = []
            except json.JSONDecodeError:
                items_to_store = []
        elif isinstance(raw_items, list):
            items_to_store = raw_items
        else:
            items_to_store = []

        update_data = {
            'purchase_category': data.get('purchaseCategory'),
            'vendor_id':         data.get('vendor_id'),
            'date':              parsed_date,
            'invoice_no':        data.get('invoiceNo'),
            'invoice_date':      parsed_invoice_date,
            'due_date':          parsed_due_date,
            'payment_mode':      data.get('paymentMode'),
            'ip_number':         data.get('ipNumber'),
            'patient_name':      data.get('patientName'),
            'surgeon_name':      data.get('surgeonName'),
            # ✅ Store as list, not json.dumps() string
            'items':             items_to_store,
            'lastmodified_date': timezone.now(),
            'lastmodified_by':   request.headers.get('auth-user-id', 'system'),
            'remarks':           summary.get('remarks', document.get('remarks', '')),
        }

        # Remove None values
        update_data = {k: v for k, v in update_data.items() if v is not None}

        summary_mapping = {
            'non_taxable_amount':       'nonTaxableAmount',
            'taxable_amount':           'taxableAmount',
            'tax_paid_to_supplier':     'taxPaidToSupplier',
            'local_tax':                'localTax',
            'cgst':                     'cgst',
            'sgst':                     'sgst',
            'igst':                     'igst',
            'cess':                     'cess',
            'central_sales_tax':        'centralSalesTax',
            'round_amount':             'roundAmount',
            'total_amount':             'totalAmount',
            'tax_on_free_items':        'taxOnFreeItems',
            'total_discount':           'totalDiscount',
            'net_invoice_amount':       'netInvoiceAmount',
            'quotation_rate':           'quotationRate',
            'courier_transport_charge': 'courierTransportCharge',
        }

        for backend_field, frontend_field in summary_mapping.items():
            raw   = summary.get(frontend_field, document.get(backend_field, 0))
            value = convert_decimal128_to_float(raw)
            update_data[backend_field] = Decimal128(str(value))

        result = collection.update_one(
            {"grn_number": grn_number},
            {"$set": update_data}
        )

        if result.matched_count == 1:
            updated_doc = collection.find_one({"grn_number": grn_number})
            cleaned_doc = clean_mongo_document(updated_doc)

            # ✅ Also parse items in the response so the caller gets a list
            if isinstance(cleaned_doc.get('items'), str):
                try:
                    cleaned_doc['items'] = json.loads(cleaned_doc['items'])
                except (json.JSONDecodeError, TypeError):
                    cleaned_doc['items'] = []

            return Response({
                'status': 'success',
                'message': f'Record {grn_number} updated successfully',
                'data': cleaned_doc
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'status': 'error',
                'message': f'No record matched for GRN {grn_number}'
            }, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        logger.error(f"Error updating GRN {grn_number}: {str(e)}\n{traceback.format_exc()}")
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)