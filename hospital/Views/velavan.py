from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.core.paginator import Paginator
import json
from django.db.models import Q
from ..models import VelavanInvoice, VelavanVendors, VelavanItems, VelavanSalesBill, VelavanSalesReturn, VelavanPurchaseReturn, VelavanCustomers
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
import certifi, copy
import re
from datetime import datetime
import traceback
from bson.objectid import ObjectId
from datetime import date, datetime
from django.shortcuts import get_object_or_404
from ..models import ImplantRequest, Patient, InsuranceProvider



client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']


def normalize_items_payload(raw_items):
    """
    Coerce whatever shape `items` arrives in (JSON body, multipart form,
    or an already-stringified value) into a guaranteed Python list of
    dicts. Handles single- and double-encoded JSON strings, which is
    the root cause of items occasionally being stored as a JSON string
    instead of a native array.
    """
    value = raw_items

    # Unwrap up to 2 levels of JSON-string encoding.
    for _ in range(2):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return []
        else:
            break

    if not isinstance(value, list):
        return []

    # Each item itself might also have arrived as a JSON string.
    normalized = []
    for item in value:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if isinstance(item, dict):
            normalized.append(item)

    return normalized

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_ip_patient(request, ipNumber):
    try:
        ip_number = (ipNumber or "").strip()
        if not ip_number:
            return Response(
                {"success": False, "error": "ip_number is required"},
                status=400,
            )

        # ── Step 1: ip_number -> ImplantRequest (uhid, surgeon_id) ────────────
        # Model's default ordering is ["-created_date"], so the first active
        # match is the most recent request for this IP number.
        candidates = ImplantRequest.objects.filter(
            inpatient_number=ip_number
        )

        implant_req = next(
            (rec for rec in candidates if rec.is_active),
            None,
        )

        if not implant_req or not implant_req.uhid:
            return Response(
                {"success": False, "error": "No implant request found for this IP number"},
                status=404,
            )

        uhid       = implant_req.uhid
        surgeon_id = implant_req.surgeon_id or ""

        # ── Step 2: uhid -> Patient ────────────────────────────────────────────
        patient = Patient.objects.filter(uhid=uhid).first()
        if not patient:
            return Response(
                {"success": False, "error": "Patient not found for this UHID"},
                status=404,
            )

        company_name = None
        if patient.company_code:
            insurer = InsuranceProvider.objects.filter(
                company_code=patient.company_code
            ).first()
            company_name = insurer.company_name if insurer else None

        # ── Step 3: surgeon_id -> backend_diagnostics_profile (employeeName) ──
        surgeon_name = ""
        if surgeon_id:
            mongo_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            global_db    = mongo_client[os.getenv("GLOBAL_DB_NAME", "Global")]
            collection   = global_db["backend_diagnostics_profile"]

            doc = collection.find_one(
                {"employeeId": str(surgeon_id)},
                {"employeeName": 1, "_id": 0},
            )
            surgeon_name = doc.get("employeeName", "") if doc else ""
            mongo_client.close()

        data = {
            "uhid": uhid,
            "salutation": patient.salutation or "",
            "firstName": patient.firstName or "",
            "lastName": patient.lastName or "",
            "gender": patient.gender or "",
            "customer_type": patient.customer_type or "",
            "company_name": company_name,
            "surgeon_id": surgeon_id,
            "surgeon_name": surgeon_name,
        }

        return Response({"success": True, "data": data})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


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
        outlet_code = data.get('auth-outlet-code','system')
        branch_code = data.get('auth-branch-code', 'system')        
        hospital_code = data.get('auth-hospital-code', 'system')

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
            "msme":             data.get("msme", ""),
            "pan":              data.get("pan", ""),
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
            {"_id": 1, "item_id": 1, "itemName": 1, "hsn": 1, "category": 1}
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
        {"_id": 1, "item_id": 1, "itemName": 1, "hsn": 1, "category": 1}
    )

    data = []
    for item in items:
        raw_item_id = item.get("item_id")
        try:
            item_id_val = int(raw_item_id) if raw_item_id not in (None, "") else None
        except (ValueError, TypeError):
            item_id_val = None

        data.append({
            "id": str(item["_id"]),
            "item_id": item_id_val,
            "itemName": item.get("itemName", ""),
            "hsn": item.get("hsn", ""),
            "category": item.get("category", ""),
        })

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
        outlet_code = data.get('auth-outlet-code', 'system')
        branch_code = data.get('auth-branch-code', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')

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

        # ── Generate next item_id as an integer ──
        items_collection = db["hospital_velavan_items"]
        all_item_ids = items_collection.distinct("item_id")
        max_id = 0
        for iid in all_item_ids:
            try:
                numeric_id = int(iid)
                if numeric_id > max_id:
                    max_id = numeric_id
            except (ValueError, TypeError):
                continue
        new_item_id = max_id + 1  # int, not str

        item = VelavanItems.objects.create(
            item_id=new_item_id,
            itemName=item_name,
            hsn=hsn,
            category=request.data.get("category", ""),
            created_by=user_id,
            branch_code=branch_code,
            outlet_code=outlet_code,
            hospital_code=hospital_code
        )

        # ── Strip djongo's redundant "id" field from the stored document ──
        # djongo persists its ORM-facing AutoField as a literal "id" key
        # inside the Mongo document, duplicating "_id". Match on item_id
        # (guaranteed unique, just assigned above) rather than item.pk,
        # since djongo's pk representation for this model is ambiguous
        # (could be the ObjectId or something else depending on config).
        try:
            items_collection.update_one(
                {"item_id": new_item_id},
                {"$unset": {"id": ""}}
            )
        except Exception as strip_err:
            logger.error(f"Failed to strip 'id' field for item_id {new_item_id}: {strip_err}")

        return Response(
            {
                "success": True,
                "message": "Item created successfully",
                "data": {
                    "item_id": item.item_id,
                    "itemName": item.itemName,
                    "hsn": item.hsn,
                    "category": item.category,
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
        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            return Response(
                {"status": "error", "message": "Invalid item_id"},
                status=status.HTTP_400_BAD_REQUEST
            )

        items_collection = db["hospital_velavan_items"]

        data = request.data.copy()

        # never let item_id, _id, or the djongo-internal "id" be overwritten
        fields_to_remove = ["_id", "id", "item_id"]
        auth_fields = [key for key in data.keys() if key.startswith("auth-")]
        fields_to_remove.extend(auth_fields)

        for field in fields_to_remove:
            data.pop(field, None)

        data["lastmodified_by"] = request.data.get("auth-user-id")
        data["lastmodified_date"] = datetime.now()

        result = items_collection.update_one(
            {"item_id": item_id_int},
            {"$set": data}
        )

        if result.matched_count == 0:
            return Response(
                {"status": "error", "message": "Item not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        updated_item = items_collection.find_one({"item_id": item_id_int})

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
        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            return Response(
                {"status": "error", "message": "Invalid item_id"},
                status=status.HTTP_400_BAD_REQUEST
            )

        items_collection = db["hospital_velavan_items"]

        result = items_collection.update_one(
            {"item_id": item_id_int},
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
        outlet_code = data.get('auth-outlet-code','system')
        branch_code = data.get('auth-branch-code', 'system')        
        hospital_code = data.get('auth-hospital-code', 'system')

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

        # ── Normalize items to a guaranteed native list BEFORE sanitizing ──
        # This is the fix: regardless of whether `items` arrives as a
        # list, a JSON-encoded string, or a double-encoded string, this
        # always returns a real list of dicts. Prevents items being
        # stored as a JSON string in Mongo.
        normalized_items = normalize_items_payload(data.get('items', []))
        clean_items = sanitize_items(normalized_items)

        # ── Duplicate check ──────────────────────────────────────────────
        vendor_id   = data.get('vendor_id') or ''
        invoice_no  = data.get('invoiceNo') 

        if vendor_id and invoice_no :
            exists = VelavanInvoice.objects.filter(
                vendor_id    = vendor_id,
                invoice_no   = invoice_no,
            ).exists()
            if exists:
                return JsonResponse({
                    'success': False,
                    'status':  'duplicate',
                    'message': f'Invoice "{invoice_no}" from vendor "{vendor_id}" already exists.',
                }, status=409)
        # ─────────────────────────────────────────────────────────────────

        invoice = VelavanInvoice(
            vendor_id               = data.get('vendor_id') or '',
            date                    = to_date(data.get('date')),
            invoice_no              = data.get('invoiceNo') or '',
            invoice_date            = to_date(data.get('invoiceDate')),
            payment_mode            = data.get('paymentMode') or '',
            ip_number               = data.get('ipNumber') or '',
            patient_name            = data.get('patientName') or '',
            surgeon_id            = data.get('surgeon_id') or data.get('surgeonName') or '',
            customer_type           = data.get('customerType') or '',
            company_name            = data.get('companyName') or '',
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

        # ── Bypass djongo's broken JSONField serialization for `items` ──
        # djongo 1.3.6 has a known issue where JSONField values get
        # stored as a Python repr() string (single-quoted) instead of a
        # native BSON array, even though `clean_items` here is a proper
        # Python list. Patch the field directly via PyMongo immediately
        # after the ORM save, the same way other writes in this module
        # already do successfully (e.g. update_velavan_invoice).
        try:
            raw_collection = db["hospital_velavaninvoice"]
            raw_collection.update_one(
                {"grn_number": invoice.grn_number},
                {"$set": {"items": clean_items}}
            )
        except Exception as items_fix_err:
            logger.error(
                f"Failed to patch items via PyMongo for GRN {invoice.grn_number}: {items_fix_err}"
            )

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

        # ── Connect to Global DB for surgeon name lookup only ──
        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db    = mongo_client['Global']
        profile_collection = global_db['backend_diagnostics_profile']

        from_date_str = request.GET.get('from_date', None)
        to_date_str   = request.GET.get('to_date', None)

        queryset = VelavanInvoice.objects.all().order_by('-created_date')

        if from_date_str:
            try:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
                queryset = queryset.filter(invoice_date__gte=from_date)
            except ValueError:
                logger.warning(f"Invalid from_date format: {from_date_str}, skipping filter")

        if to_date_str:
            try:
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                queryset = queryset.filter(invoice_date__lte=to_date)
            except ValueError:
                logger.warning(f"Invalid to_date format: {to_date_str}, skipping filter")

        all_records = list(queryset)

        try:
            page      = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 10))
            if page < 1:      page = 1
            if page_size < 1: page_size = 10
        except ValueError:
            page, page_size = 1, 10

        total_records = len(all_records)
        total_pages   = (total_records + page_size - 1) // page_size
        start_index   = (page - 1) * page_size
        end_index     = start_index + page_size
        page_records  = all_records[start_index:end_index]

        # ── Pre-fetch all unique surgeon_ids on this page in one Global DB query ──
        surgeon_ids = list(set(
            str(obj.surgeon_id)
            for obj in page_records
            if obj.surgeon_id
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
            except Exception as surgeon_err:
                logger.warning(f"Could not fetch surgeon profiles: {surgeon_err}")

        # ── Pre-parse items for every record on this page once, and collect
        # every item_id referenced so item names can be resolved in a single
        # batched lookup instead of a query-per-item. ──
        items_master_collection = db["hospital_velavan_items"]
        parsed_items_by_grn = {}
        all_item_ids = set()
        for obj in page_records:
            parsed = normalize_items_payload(getattr(obj, 'items', []))
            parsed_items_by_grn[obj.grn_number] = parsed
            for item in parsed:
                iid = item.get('item_id')
                if iid not in (None, ''):
                    try:
                        all_item_ids.add(int(iid))
                    except (ValueError, TypeError):
                        pass

        item_name_map = {}
        if all_item_ids:
            try:
                for doc in items_master_collection.find(
                    {'item_id': {'$in': list(all_item_ids)}},
                    {'item_id': 1, 'itemName': 1, '_id': 0}
                ):
                    item_name_map[doc['item_id']] = doc.get('itemName', '')
            except Exception as item_lookup_err:
                logger.warning(f"Could not fetch item names: {item_lookup_err}")

        # ── Purchase return totals for the GRNs on this page ──
        grn_numbers = [obj.grn_number for obj in page_records]
        purchase_return_amount_by_grn = {}
        for pr in VelavanPurchaseReturn.objects.filter(grn_number__in=grn_numbers):
            purchase_return_amount_by_grn[pr.grn_number] = (
                purchase_return_amount_by_grn.get(pr.grn_number, 0)
                + convert_decimal128_to_float(pr.total_amount)
            )

        # ── GRNs already referenced by a sales bill — used to disable the
        # "bill this invoice" cart action so a GRN can't be billed twice. ──
        billed_grns = set(
            VelavanSalesBill.objects.filter(
                source_grn_number__in=grn_numbers
            ).values_list('source_grn_number', flat=True)
        )

        # ── GRNs with at least one stock batch that still has returnable
        # quantity (accounts for sold_quantity and any sales_return that put
        # stock back) — used to gate the Purchase Return action independent
        # of whether a sales bill exists. ──
        def get_returnable_grns(grn_numbers):
            if not grn_numbers:
                return set()
            stock_collection = db["hospital_velavan_stock"]
            returnable = set()
            for doc in stock_collection.find(
                {"grn_number": {"$in": grn_numbers}, "is_active": True},
                {"grn_number": 1, "total_quantity": 1, "sold_quantity": 1,
                "purchase_return": 1, "sales_return": 1, "_id": 0}
            ):
                total_qty       = convert_decimal128_to_float(doc.get('total_quantity', 0))
                sold_qty        = convert_decimal128_to_float(doc.get('sold_quantity', 0))
                purchase_return = convert_decimal128_to_float(doc.get('purchase_return', 0))
                sales_return    = convert_decimal128_to_float(doc.get('sales_return', 0))
                available = total_qty - sold_qty - purchase_return + sales_return
                if available > 0:
                    returnable.add(doc.get('grn_number'))
            return returnable

        returnable_grns = get_returnable_grns(grn_numbers)

        response_data = []
        for obj in page_records:
            try:
                vendor_details = {
                    'vendor': '',
                    'phone': '',
                    'gstin': '',
                    'address': '',
                    'email': ''
                }
                if obj.vendor_id:
                    try:
                        vendor = VelavanVendors.objects.get(vendor_id=obj.vendor_id)
                        vendor_details = {
                            'vendor':  vendor.name,
                            'phone':   vendor.phone or '',
                            'gstin':   vendor.gstin or '',
                            'address': f"{vendor.addressLine1}, {vendor.addressLine2}, {vendor.city}, {vendor.state}".strip(', '),
                            'email':   vendor.email or ''
                        }
                    except VelavanVendors.DoesNotExist:
                        logger.warning(f"Vendor with vendor_id {obj.vendor_id} not found")

                surgeon_id   = obj.surgeon_id
                surgeon_name = surgeon_name_map.get(str(surgeon_id), '') if surgeon_id else ''

                items = parsed_items_by_grn.get(obj.grn_number, [])
                if not items and getattr(obj, 'items', None):
                    logger.warning(f"Items field for GRN {obj.grn_number} could not be normalized to a list")

                for item in items:
                    try:
                        iid = int(item.get('item_id')) if item.get('item_id') not in (None, '') else None
                    except (ValueError, TypeError):
                        iid = None
                    if iid is not None:
                        resolved_name = item_name_map.get(iid)
                        if resolved_name:
                            item['name'] = resolved_name

                for item in items:
                    numeric_item_fields = [
                        'itemValue', 'packingPrice', 'unitPrice', 'cgstAmt', 'sgstAmt',
                        'purchaseCost', 'mrp', 'tax', 'cgstPercent', 'sgstPercent'
                    ]
                    for field in numeric_item_fields:
                        if field in item:
                            item[field] = convert_decimal128_to_float(item[field])

                total_amount_paid = convert_decimal128_to_float(getattr(obj, 'total_amount_paid', 0))
                total_amount      = convert_decimal128_to_float(getattr(obj, 'total_amount', 0))
                pending_amount    = max(0.0, total_amount - total_amount_paid)

                purchase_return_amount = purchase_return_amount_by_grn.get(obj.grn_number, 0)
                net_invoice_amount_val = convert_decimal128_to_float(getattr(obj, 'net_invoice_amount', 0)) or total_amount

                item_data = {
                    'id':              str(getattr(obj, '_id', None)),
                    'grn_number':      obj.grn_number,
                    'vendor_id':       obj.vendor_id,
                    'vendor':          vendor_details['vendor'],
                    'phone':           vendor_details['phone'],
                    'gstin':           vendor_details['gstin'],
                    'address':         vendor_details['address'],
                    'pending_amount':  pending_amount,
                    'invoice_no':      obj.invoice_no,
                    'payment_mode':    obj.payment_mode,
                    'remarks':         obj.remarks or '',
                    'created_by':      getattr(obj, 'created_by', None),
                    'ip_number':       obj.ip_number,
                    'patient_name':    obj.patient_name,
                    'surgeon_id':      surgeon_id,
                    'surgeon_name':    surgeon_name,
                    'customer_type':   obj.customer_type,
                    'company_name':    obj.company_name,
                    'items':           items,
                    'lastmodified_by': getattr(obj, 'lastmodified_by', None),
                    'is_approved':     obj.is_approved,
                    'approved_by':     obj.approved_by,
                    'purchase_return_amount': round(purchase_return_amount, 2),
                    'net_amount_after_return': round(net_invoice_amount_val - purchase_return_amount, 2),
                    'has_sales_bill':  obj.grn_number in billed_grns,
                    'has_returnable_stock': obj.grn_number in returnable_grns,
                }

                date_fields = ['date', 'invoice_date', 'due_date', 'created_date', 'lastmodified_date']
                for field in date_fields:
                    value = getattr(obj, field, None)
                    item_data[field] = value.isoformat() if hasattr(value, 'isoformat') else str(value) if value else None

                numeric_fields = [
                    'non_taxable_amount', 'taxable_amount', 'tax_paid_to_supplier',
                    'local_tax', 'cgst', 'sgst', 'igst', 'cess', 'central_sales_tax',
                    'round_amount', 'total_amount', 'tax_on_free_items', 'total_discount',
                    'net_invoice_amount', 'quotation_rate', 'courier_transport_charge'
                ]
                for field in numeric_fields:
                    value = getattr(obj, field, None)
                    item_data[field] = convert_decimal128_to_float(value)

                response_data.append(item_data)

            except Exception as item_error:
                logger.error(f"Error processing GRN {obj.grn_number}: {str(item_error)}\n{traceback.format_exc()}")
                response_data.append({
                    'id':           str(getattr(obj, '_id', None)),
                    'grn_number':   obj.grn_number,
                    'vendor_id':    obj.vendor_id,
                    'vendor':       '',
                    'surgeon_id':   obj.surgeon_id,
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
    item_id = request.GET.get('item_id')
    hsn = request.GET.get('hsn')
    item_name = request.GET.get('item_name')

    if not item_id and not (hsn and item_name):
        return Response(
            {'status': 'error', 'message': 'item_id, or both hsn and item_name, are required'},
            status=400
        )

    item_id_val = None
    if item_id:
        try:
            item_id_val = int(item_id)
        except (ValueError, TypeError):
            return Response({'status': 'error', 'message': 'item_id must be numeric'}, status=400)

    input_hsn  = str(hsn or '').strip()
    input_name = " ".join(str(item_name or '').strip().split())

    try:
        purchases_collection = db["hospital_velavaninvoice"]
        vendors_collection   = db["hospital_velavan_vendors"]
        items_collection     = db["hospital_velavan_items"]

        # ── Resolve current item name from item_id (for display on new-style
        # matches). Falls back to whatever name was passed in for legacy
        # matches, since those items only ever carry their own stored name. ──
        resolved_item_name = input_name
        if item_id_val is not None:
            item_master = items_collection.find_one(
                {"item_id": item_id_val},
                {"itemName": 1, "hsn": 1, "_id": 0}
            )
            if item_master:
                resolved_item_name = item_master.get("itemName", "") or input_name
                if not input_hsn:
                    input_hsn = item_master.get("hsn", "")

        documents = purchases_collection.find({})
        matched_purchases = []

        for doc in documents:
            items = normalize_items_payload(doc.get('items', []))
            if not items and doc.get('items'):
                print(f"Error parsing items for GRN {doc.get('grn_number')}")
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
                stored_item_id = item.get('item_id')
                try:
                    stored_item_id_val = (
                        int(stored_item_id) if stored_item_id not in (None, '') else None
                    )
                except (ValueError, TypeError):
                    stored_item_id_val = None

                matched = False

                # ── Path 1: item_id match — for invoices saved after the
                # item_id migration. ──
                if item_id_val is not None and stored_item_id_val is not None:
                    matched = stored_item_id_val == item_id_val

                # ── Path 2: hsn + name match — the original lookup, kept
                # alive for older invoices whose items never had item_id
                # written to them at all. ──
                if not matched and stored_item_id_val is None:
                    stored_hsn  = str(item.get('hsn', '')).strip()
                    stored_name = " ".join(str(item.get('name', '')).strip().split())
                    if input_hsn and input_name:
                        matched = (
                            stored_hsn == input_hsn
                            and stored_name.lower() == input_name.lower()
                        )

                if matched:
                    # Fill in a display name if this particular stored item
                    # is missing one (new-style items only carry item_id).
                    item['name'] = item.get('name') or resolved_item_name
                    if stored_item_id_val is not None:
                        item['item_id'] = stored_item_id_val
                    if not item.get('hsn') and input_hsn:
                        item['hsn'] = input_hsn

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

        return Response({
            'status': 'success',
            'data': matched_purchases,
            'item_name': resolved_item_name,
        }, status=200)

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

        # ✅ Always store items as a parsed list (not a JSON string).
        # normalize_items_payload() handles single- and double-encoded
        # JSON strings, so items can never be written back as a string.
        items_to_store = normalize_items_payload(data.get('items', []))

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
            'surgeon_id':        data.get('surgeon_id') or data.get('surgeonName', ''),
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

            # ✅ Also normalize items in the response so the caller always
            # gets a list, even for legacy records saved before this fix.
            cleaned_doc['items'] = normalize_items_payload(cleaned_doc.get('items', []))

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
    
def _next_stock_id(stock_collection):
    all_ids = stock_collection.distinct("stock_id")
    max_id = 0
    for sid in all_ids:
        try:
            numeric_id = int(sid)
            if numeric_id > max_id:
                max_id = numeric_id
        except (ValueError, TypeError):
            continue
    return max_id + 1


def push_items_to_stock(invoice_doc, approved_by):
    """
    Called once, right after an invoice is approved. Creates one
    hospital_velavan_stock document per purchased item so the batch
    becomes available for sales billing.

    itemName is intentionally NOT stored here — invoice items arrive
    without a 'name' key (Invoice.jsx strips it before submit), and even
    if they didn't, item_id is the single source of truth. Display names
    are resolved live from hospital_velavan_items wherever stock is read.
    """
    stock_collection = db["hospital_velavan_stock"]
    items = normalize_items_payload(invoice_doc.get('items', []))
    now = datetime.now()
    inserted = 0

    for item in items:
        try:
            qty = float(item.get('quantity') or 0)
        except (ValueError, TypeError):
            qty = 0
        if qty <= 0:
            continue

        stock_doc = {
            "stock_id":            _next_stock_id(stock_collection),
            "item_id":             item.get('item_id'),
            "hsn":                 item.get('hsn', ''),
            "batch_no":            item.get('batch_no', ''),
            "expiry":              item.get('expiry', ''),
            "total_quantity":      qty,
            "sold_quantity":       0,
            "purchase_return":     0,
            "sales_return":        0,
            "sellingTax":          item.get('sellingTax'),
            "sellingCgstPercent":  item.get('sellingCgstPercent'),
            "sellingCgstAmt":      item.get('sellingCgstAmt'),
            "sellingsgstPercent":  item.get('sellingsgstPercent'),
            "sellingSgstAmt":      item.get('sellingSgstAmt'),
            "sellingUnitCost":     item.get('sellingUnitCost'),
            "sellingCost":         item.get('sellingCost'),
            "unitSellingCost":     item.get('unitSellingCost'),
            "sellingCostBeforeGst": item.get('sellingCostBeforeGst'),
            "mrp":                 item.get('mrp'),
            "grn_number":          invoice_doc.get('grn_number'),
            "vendor_id":           invoice_doc.get('vendor_id'),
            "is_active":           True,
            "created_by":          approved_by,
            "created_date":        now,
        }
        stock_collection.insert_one(stock_doc)
        inserted += 1

    return inserted


@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_velavan_invoice(request, grn_number):
    try:
        collection = db["hospital_velavaninvoice"]
        document = collection.find_one({"grn_number": grn_number})
        if not document:
            return Response({'status': 'error', 'message': f'No record found for GRN {grn_number}'},
                             status=status.HTTP_404_NOT_FOUND)

        if document.get('is_approved'):
            return Response({'status': 'error', 'message': f'GRN {grn_number} is already approved'},
                             status=status.HTTP_400_BAD_REQUEST)

        approved_by = request.data.get('auth-user-id', 'system')
        result = collection.update_one(
            {"grn_number": grn_number},
            {"$set": {'is_approved': True, 'approved_by': approved_by, 'approved_at': timezone.now()}}
        )

        if result.matched_count == 1:
            updated_doc = collection.find_one({"grn_number": grn_number})

            # ── TEMP DEBUG: surface exactly what's happening ──
            stock_debug = {"attempted": False, "items_found": 0, "inserted": 0, "error": None}
            try:
                raw_items = updated_doc.get('items', [])
                logger.info(f"[STOCK DEBUG] raw items type={type(raw_items)} for GRN {grn_number}")
                parsed_items = normalize_items_payload(raw_items)
                logger.info(f"[STOCK DEBUG] parsed {len(parsed_items)} items for GRN {grn_number}: {parsed_items}")
                stock_debug["items_found"] = len(parsed_items)
                stock_debug["attempted"] = True

                inserted = push_items_to_stock(updated_doc, approved_by)  # see change below
                stock_debug["inserted"] = inserted
            except Exception as stock_err:
                stock_debug["error"] = str(stock_err)
                logger.error(f"[STOCK DEBUG] Failed to push stock for GRN {grn_number}: {stock_err}\n{traceback.format_exc()}")

            cleaned_doc = clean_mongo_document(updated_doc)
            cleaned_doc['items'] = normalize_items_payload(cleaned_doc.get('items', []))

            return Response({
                'status': 'success',
                'message': f'GRN {grn_number} approved successfully',
                'data': cleaned_doc,
                'stock_debug': stock_debug,   # ← remove once diagnosed
            }, status=status.HTTP_200_OK)
        else:
            return Response({'status': 'error', 'message': 'Update failed'},
                             status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Exception as e:
        logger.error(f"Error approving GRN {grn_number}: {str(e)}\n{traceback.format_exc()}")
        return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

def register_stock_sale(stock_id, qty_billed):
    """
    Increments sold_quantity on the exact stock batch, matched by stock_id —
    the value returned by velavan_search_stock and chosen by the user in the
    billing UI. Matching by stock_id (rather than re-deriving grn/item/batch)
    is required because billing can now happen standalone, with no source
    invoice at all.
    """
    if not stock_id:
        return
    try:
        qty_billed = float(qty_billed or 0)
    except (ValueError, TypeError):
        qty_billed = 0
    if qty_billed <= 0:
        return

    stock_collection = db["hospital_velavan_stock"]
    try:
        stock_id_val = int(stock_id)
    except (ValueError, TypeError):
        stock_id_val = stock_id

    stock_doc = stock_collection.find_one({"stock_id": stock_id_val})
    if not stock_doc:
        logger.warning(f"No stock batch found for stock_id={stock_id} during sale")
        return

    total_qty        = float(convert_decimal128_to_float(stock_doc.get('total_quantity', 0)))
    sold_qty         = float(convert_decimal128_to_float(stock_doc.get('sold_quantity', 0)))
    purchase_return  = float(convert_decimal128_to_float(stock_doc.get('purchase_return', 0)))
    sales_return     = float(convert_decimal128_to_float(stock_doc.get('sales_return', 0)))
    available = total_qty - sold_qty - purchase_return + sales_return

    if qty_billed > available:
        logger.warning(
            f"Sale quantity {qty_billed} exceeds available stock {available} "
            f"for stock_id {stock_id}"
        )

    stock_collection.update_one(
        {"_id": stock_doc["_id"]},
        {"$inc": {"sold_quantity": qty_billed}}
    )


@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_velavan_sale(request):
    try:
        data = request.data
        summary = data.get('summary', {})
        user_id = data.get('auth-user-id', 'system')
        outlet_code = data.get('auth-outlet-code', 'system')
        branch_code = data.get('auth-branch-code', 'system')        
        hospital_code = data.get('auth-hospital-code', 'system')

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
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, (date, datetime)):
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

        # ── Item name is never stored on the bill — only item_id, hsn,
        # batch_no, expiry, quantities and pricing. Display names are
        # resolved at read time (list_velavan_sales) via a lookup against
        # hospital_velavan_items, same as invoices already do. Strip any
        # 'name' / 'itemName' the client might still send, defensively. ──
        raw_items = normalize_items_payload(data.get('items', []))
        clean_items = []
        for item in raw_items:
            item = {k: sanitize_value(v) for k, v in item.items()}
            item.pop('name', None)
            item.pop('itemName', None)
            clean_items.append(item)

        if not clean_items:
            return Response(
                {"status": "error", "message": "At least one item is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Every billed line must carry a stock_id so stock deduction
        # can be matched exactly — reject early rather than silently
        # skipping deduction later. ──
        missing_stock_id = [i for i in clean_items if not i.get('stock_id')]
        if missing_stock_id:
            return Response(
                {"status": "error", "message": "Each item must reference a stock_id"},
                status=status.HTTP_400_BAD_REQUEST
            )

        source_grn = data.get('source_grn_number') or ''

        payment_mode = (data.get('paymentMode') or 'CASH').strip().upper() or 'CASH'
        payment_status = (data.get('paymentStatus') or 'PAID').strip().upper() or 'PAID'

        bill = VelavanSalesBill(
            source_grn_number = source_grn,
            customer_id        = data.get('customer_id') or '',
            bill_date         = to_date(data.get('billDate')) or timezone.now().date(),
            ip_number         = data.get('ipNumber') or '',
            patient_name      = data.get('patientName') or '',
            surgeon_id        = data.get('surgeon_id') or data.get('surgeonName') or '',
            customer_type     = data.get('customerType') or '',
            company_name      = data.get('companyName') or '',
            items             = clean_items,
            taxable_amount    = to_decimal(summary.get('taxableAmount')),
            cgst              = to_decimal(summary.get('cgst')),
            sgst              = to_decimal(summary.get('sgst')),
            round_amount      = to_decimal(summary.get('roundAmount')),
            total_amount      = to_decimal(summary.get('totalAmount')),
            remarks           = summary.get('remarks') or '',
            payment_mode      = payment_mode,
            payment_status    = payment_status,
            created_by        = user_id,
            outlet_code       = outlet_code,
            branch_code         = branch_code,
            hospital_code       = hospital_code
        )
        bill.save()

        # ── Bypass djongo JSONField serialization, same fix as invoices ──
        try:
            raw_collection = db["hospital_velavansalesbill"]
            raw_collection.update_one(
                {"bill_number": bill.bill_number},
                {"$set": {"items": clean_items}}
            )
        except Exception as items_fix_err:
            logger.error(f"Failed to patch sale items for {bill.bill_number}: {items_fix_err}")

        # ── Deduct billed quantities from stock (matched by stock_id) ──
        for item in clean_items:
            try:
                register_stock_sale(item.get('stock_id'), item.get('quantity'))
            except Exception as dec_err:
                logger.error(f"Stock deduction failed for stock_id {item.get('stock_id')}: {dec_err}")

        return JsonResponse({
            'success':     True,
            'status':      'success',
            'message':     'Sales bill created successfully',
            'bill_number': str(bill.bill_number),
        }, status=201)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'status': 'error', 'message': str(e)}, status=500)
    


@csrf_exempt
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_velavan_sales(request):
    try:
        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = mongo_client['Global']
        profile_collection = global_db['backend_diagnostics_profile']

        from_date_str = request.GET.get('from_date', None)
        to_date_str   = request.GET.get('to_date', None)

        queryset = VelavanSalesBill.objects.all().order_by('-created_date')

        if from_date_str:
            try:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
                queryset = queryset.filter(bill_date__gte=from_date)
            except ValueError:
                pass
        if to_date_str:
            try:
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                queryset = queryset.filter(bill_date__lte=to_date)
            except ValueError:
                pass

        all_records = list(queryset)

        try:
            page      = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 10))
        except ValueError:
            page, page_size = 1, 10

        total_records = len(all_records)
        total_pages   = (total_records + page_size - 1) // page_size
        start         = (page - 1) * page_size
        page_records  = all_records[start:start + page_size]

        surgeon_ids = list(set(str(o.surgeon_id) for o in page_records if o.surgeon_id))
        surgeon_name_map = {}
        if surgeon_ids:
            try:
                for p in profile_collection.find(
                    {'employeeId': {'$in': surgeon_ids}},
                    {'employeeId': 1, 'employeeName': 1, '_id': 0}
                ):
                    surgeon_name_map[p['employeeId']] = p.get('employeeName', '')
            except Exception:
                pass

        customer_ids = list(set(str(o.customer_id) for o in page_records if getattr(o, 'customer_id', None)))
        customer_map = resolve_customer_names(customer_ids)

        items_master_collection = db["hospital_velavan_items"]
        parsed_items_by_bill = {}
        all_item_ids = set()
        for obj in page_records:
            parsed = normalize_items_payload(getattr(obj, 'items', []))
            parsed_items_by_bill[obj.bill_number] = parsed
            for item in parsed:
                iid = item.get('item_id')
                if iid not in (None, ''):
                    try:
                        all_item_ids.add(int(iid))
                    except (ValueError, TypeError):
                        pass

        item_name_map = {}
        if all_item_ids:
            try:
                for doc in items_master_collection.find(
                    {'item_id': {'$in': list(all_item_ids)}},
                    {'item_id': 1, 'itemName': 1, '_id': 0}
                ):
                    item_name_map[doc['item_id']] = doc.get('itemName', '')
            except Exception as item_lookup_err:
                logger.warning(f"Could not fetch item names for sales: {item_lookup_err}")

        # ── Pull all returns for the bills on this page, keyed by bill_number,
        # aggregated by stock_id so quantities/amounts can be netted out ──
        bill_numbers = [obj.bill_number for obj in page_records]
        returns_by_bill = {}
        total_returned_amount_by_bill = {}
        returns_list_by_bill = {}
        for ret in VelavanSalesReturn.objects.filter(bill_number__in=bill_numbers):
            per_stock = returns_by_bill.setdefault(ret.bill_number, {})
            for ri in normalize_items_payload(ret.items):
                key = ri.get('stock_id')
                per_stock[key] = per_stock.get(key, 0) + float(convert_decimal128_to_float(ri.get('quantity', 0)))
            total_returned_amount_by_bill[ret.bill_number] = (
                total_returned_amount_by_bill.get(ret.bill_number, 0)
                + convert_decimal128_to_float(ret.total_amount)
            )
            returns_list_by_bill.setdefault(ret.bill_number, []).append({
                'return_number': ret.return_number,
                'return_date': ret.return_date.isoformat() if ret.return_date else None,
                'total_amount': convert_decimal128_to_float(ret.total_amount),
                'remarks': ret.remarks or '',
            })

        response_data = []
        for obj in page_records:
            items = parsed_items_by_bill.get(obj.bill_number, [])

            for item in items:
                try:
                    iid = int(item.get('item_id')) if item.get('item_id') not in (None, '') else None
                except (ValueError, TypeError):
                    iid = None
                item['name'] = item_name_map.get(iid, '') if iid is not None else ''
                for f in ['sellingCgstAmt', 'sellingSgstAmt', 'sellingCost',
                          'unitSellingCost', 'sellingCostBeforeGst', 'quantity', 'mrp']:
                    if f in item:
                        item[f] = convert_decimal128_to_float(item[f])

            # ── Snapshot the full, un-netted items exactly as billed. Used by
            # the Sales Tax Register, which must report gross sales for the
            # period regardless of any later returns — returns are tracked
            # separately in their own register (Sales Return Register) and
            # should not reduce figures here. ──
            original_items = copy.deepcopy(items)

            # ── Net returned quantities out of the displayed items ──
            returned_map = returns_by_bill.get(obj.bill_number, {})
            adjusted_items = []
            for item in items:
                key = item.get('stock_id')
                returned_qty = returned_map.get(key, 0)
                orig_qty = float(item.get('quantity') or 0)
                remaining_qty = orig_qty - returned_qty
                if remaining_qty <= 0:
                    continue  # fully returned — drop the line
                if returned_qty > 0:
                    ratio = remaining_qty / orig_qty if orig_qty > 0 else 0
                    item = {**item, 'quantity': remaining_qty}
                    for f in ['sellingCost', 'sellingCostBeforeGst', 'sellingCgstAmt', 'sellingSgstAmt']:
                        if f in item:
                            item[f] = round(float(item[f]) * ratio, 2)
                adjusted_items.append(item)

            sales_return_amount = total_returned_amount_by_bill.get(obj.bill_number, 0)
            surgeon_name = surgeon_name_map.get(str(obj.surgeon_id), '') if obj.surgeon_id else ''
            customer_info = customer_map.get(str(obj.customer_id), {}) if getattr(obj, 'customer_id', None) else {}

            item_data = {
                'id':                str(getattr(obj, '_id', None)),
                'bill_number':       obj.bill_number,
                'source_grn_number': obj.source_grn_number,
                'customer_id':       getattr(obj, 'customer_id', None),
                'customer_name':     customer_info.get('name', ''),
                'customer_phone':    customer_info.get('phone', ''),
                'customer_company':  customer_info.get('company_name', ''),
                'customer_addressLine1':  customer_info.get('addressLine1', ''),
                'customer_addressLine2':  customer_info.get('addressLine2', ''),
                'customer_city':  customer_info.get('city', ''),
                'customer_state':  customer_info.get('state', ''),
                'customer_pincode':  customer_info.get('pincode', ''),
                'customer_gstin':  customer_info.get('gstin', ''),
                'customer_pan':    customer_info.get('pan', ''),   # ← added
                'bill_date':         obj.bill_date.isoformat() if obj.bill_date else None,
                'ip_number':         obj.ip_number,
                'patient_name':      obj.patient_name,
                'surgeon_id':        obj.surgeon_id,
                'surgeon_name':      surgeon_name,
                'customer_type':     obj.customer_type,
                'company_name':      obj.company_name,
                'items':             adjusted_items,
                'original_items':    original_items,   # ← gross, un-netted — for Sales Tax Register
                'taxable_amount':    convert_decimal128_to_float(obj.taxable_amount),
                'cgst':              convert_decimal128_to_float(obj.cgst),
                'sgst':              convert_decimal128_to_float(obj.sgst),
                'round_amount':      convert_decimal128_to_float(obj.round_amount),
                'total_amount':      convert_decimal128_to_float(obj.total_amount),
                'sales_return_amount': round(sales_return_amount, 2),
                'net_total_amount':  round(convert_decimal128_to_float(obj.total_amount) - sales_return_amount, 2),
                'returns':           returns_list_by_bill.get(obj.bill_number, []),
                'remarks':           obj.remarks or '',
                'payment_mode':      getattr(obj, 'payment_mode', 'CASH') or 'CASH',
                'payment_status':    getattr(obj, 'payment_status', 'PAID') or 'PAID',
                'created_by':        getattr(obj, 'created_by', None),
                'created_date':      obj.created_date.isoformat() if getattr(obj, 'created_date', None) else None,
            }
            response_data.append(item_data)

        return Response({
            'status': 'success',
            'data': response_data,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_records': total_records,
                'has_next': page < total_pages,
                'has_previous': page > 1,
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in list_velavan_sales: {str(e)}\n{traceback.format_exc()}")
        return Response({'status': 'error', 'message': str(e)}, status=500)
    finally:
        try:
            mongo_client.close()
        except Exception:
            pass


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def velavan_get_stock(request):
    """Available stock batches for a given item (used when billing)."""
    item_id = request.GET.get('item_id')
    try:
        query = {"is_active": True, "remaining_quantity": {"$gt": 0}}
        if item_id:
            try:
                query["item_id"] = int(item_id)
            except (ValueError, TypeError):
                query["item_id"] = item_id

        stock_collection = db["hospital_velavan_stock"]
        docs = list(stock_collection.find(query))
        for d in docs:
            d["id"] = str(d["_id"])
            del d["_id"]
            for f in ['sellingCgstAmt', 'sellingSgstAmt', 'sellingCost',
                      'unitSellingCost', 'sellingCostBeforeGst', 'total_quantity',
                      'remaining_quantity', 'mrp']:
                d[f] = convert_decimal128_to_float(d.get(f, 0))

        return Response({"status": "success", "data": docs}, status=200)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=500)

def _parse_expiry_sort_key(expiry_str):
    """expiry is stored as 'MM-YYYY'; unparsable/blank values sort last."""
    m = re.match(r'^(\d{2})-(\d{4})$', str(expiry_str or '').strip())
    if m:
        mm, yyyy = int(m.group(1)), int(m.group(2))
        return (yyyy, mm)
    return (9999, 12)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def velavan_search_stock(request):
    """
    Search available stock batches for the sales billing item picker.

    Name search goes through hospital_velavan_items (the source of truth
    for item names) rather than the stock collection, since stock never
    stores itemName. item_ids matching the text search are then used to
    pull stock batches, sorted nearest-expiry-first.
    """
    query_text = request.GET.get('q', '').strip()
    item_id_param = request.GET.get('item_id')

    if not query_text and not item_id_param:
        return Response({"status": "success", "data": []}, status=200)

    try:
        items_collection = db["hospital_velavan_items"]
        stock_collection = db["hospital_velavan_stock"]

        item_id_to_name = {}
        if item_id_param:
            try:
                iid = int(item_id_param)
            except (ValueError, TypeError):
                iid = item_id_param
            master = items_collection.find_one(
                {"item_id": iid}, {"item_id": 1, "itemName": 1, "_id": 0}
            )
            if master:
                item_id_to_name[master["item_id"]] = master.get("itemName", "")
        else:
            for m in items_collection.find(
                {"itemName": {"$regex": re.escape(query_text), "$options": "i"}},
                {"item_id": 1, "itemName": 1, "_id": 0},
            ):
                item_id_to_name[m["item_id"]] = m.get("itemName", "")

        target_item_ids = list(item_id_to_name.keys())
        if not target_item_ids:
            return Response({"status": "success", "data": []}, status=200)

        docs = list(stock_collection.find({
            "is_active": True,
            "item_id": {"$in": target_item_ids},
        }))

        results = []
        for d in docs:
            total_qty       = convert_decimal128_to_float(d.get('total_quantity', 0))
            sold_qty        = convert_decimal128_to_float(d.get('sold_quantity', 0))
            purchase_return = convert_decimal128_to_float(d.get('purchase_return', 0))
            sales_return    = convert_decimal128_to_float(d.get('sales_return', 0))
            available_qty   = total_qty - sold_qty - purchase_return + sales_return

            if available_qty <= 0:
                continue

            results.append({
                "stock_id":            d.get("stock_id"),
                "item_id":             d.get("item_id"),
                "itemName":            item_id_to_name.get(d.get("item_id"), ""),  # resolved, never stored
                "hsn":                 d.get("hsn", ""),
                "batch_no":            d.get("batch_no", ""),
                "expiry":              d.get("expiry", ""),
                "available_quantity":  available_qty,
                "total_quantity":      total_qty,
                "mrp":                 convert_decimal128_to_float(d.get("mrp", 0)),
                "sellingTax":          d.get("sellingTax"),
                "sellingCgstPercent":  d.get("sellingCgstPercent"),
                "sellingsgstPercent":  d.get("sellingsgstPercent"),
                "sellingUnitCost":     convert_decimal128_to_float(d.get("sellingUnitCost", 0)),
                "unitSellingCost":     convert_decimal128_to_float(d.get("unitSellingCost", 0)),
                "grn_number":          d.get("grn_number"),
            })

        results.sort(key=lambda r: _parse_expiry_sort_key(r.get("expiry")))
        return Response({"status": "success", "data": results}, status=200)

    except Exception as e:
        logger.error(f"Error in velavan_search_stock: {str(e)}\n{traceback.format_exc()}")
        return Response({"status": "error", "message": str(e)}, status=500)
    

def resolve_item_names(item_ids):
    """
    Batched item_id -> itemName lookup against hospital_velavan_items.
    Used everywhere a stock/bill row needs a display name, since names
    are never persisted on stock or sale documents.
    """
    item_ids = {i for i in item_ids if i not in (None, '')}
    if not item_ids:
        return {}
    norm_ids = []
    for iid in item_ids:
        try:
            norm_ids.append(int(iid))
        except (ValueError, TypeError):
            norm_ids.append(iid)

    name_map = {}
    try:
        items_collection = db["hospital_velavan_items"]
        for doc in items_collection.find(
            {'item_id': {'$in': norm_ids}},
            {'item_id': 1, 'itemName': 1, '_id': 0}
        ):
            name_map[doc['item_id']] = doc.get('itemName', '')
    except Exception as e:
        logger.warning(f"resolve_item_names lookup failed: {e}")
    return name_map
    
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def velavan_stock_by_grn(request):
    grn_number = request.GET.get('grn_number', '').strip()
    if not grn_number:
        return Response({"status": "error", "message": "grn_number is required"}, status=400)

    try:
        stock_collection = db["hospital_velavan_stock"]
        docs = list(stock_collection.find({
            "grn_number": grn_number,
            "is_active": True,
        }))

        name_map = resolve_item_names([d.get("item_id") for d in docs])

        results = []
        for d in docs:
            total_qty       = convert_decimal128_to_float(d.get('total_quantity', 0))
            sold_qty        = convert_decimal128_to_float(d.get('sold_quantity', 0))
            purchase_return = convert_decimal128_to_float(d.get('purchase_return', 0))
            sales_return    = convert_decimal128_to_float(d.get('sales_return', 0))
            available_qty   = total_qty - sold_qty - purchase_return + sales_return

            if available_qty <= 0:
                continue

            iid = d.get("item_id")
            try:
                iid_key = int(iid) if iid not in (None, '') else iid
            except (ValueError, TypeError):
                iid_key = iid

            results.append({
                "stock_id":            d.get("stock_id"),
                "item_id":             d.get("item_id"),
                "itemName":            name_map.get(iid_key, ""),
                "hsn":                 d.get("hsn", ""),
                "batch_no":            d.get("batch_no", ""),
                "expiry":              d.get("expiry", ""),
                "available_quantity":  available_qty,
                "total_quantity":      total_qty,
                "mrp":                 convert_decimal128_to_float(d.get("mrp", 0)),
                "sellingTax":          d.get("sellingTax"),
                "sellingCgstPercent":  d.get("sellingCgstPercent"),
                "sellingsgstPercent":  d.get("sellingsgstPercent"),
                "sellingUnitCost":     convert_decimal128_to_float(d.get("sellingUnitCost", 0)),
                "unitSellingCost":     convert_decimal128_to_float(d.get("unitSellingCost", 0)),
                "grn_number":          d.get("grn_number"),
            })

        results.sort(key=lambda r: _parse_expiry_sort_key(r.get("expiry")))

        return Response({"status": "success", "data": results}, status=200)

    except Exception as e:
        logger.error(f"Error in velavan_stock_by_grn: {str(e)}\n{traceback.format_exc()}")
        return Response({"status": "error", "message": str(e)}, status=500)

def resolve_customer_names(customer_ids):
    """Batched customer_id -> profile lookup via the ORM, mirrors resolve_item_names."""
    customer_ids = {c for c in customer_ids if c not in (None, '')}
    if not customer_ids:
        return {}
    name_map = {}
    try:
        for c in VelavanCustomers.objects.filter(customer_id__in=list(customer_ids)):
            name_map[c.customer_id] = {
                'name': c.name or '',
                'phone': c.phone or '',
                'company_name': c.company_name or '',
                'addressLine1': c.addressLine1 or '',
                'addressLine2': c.addressLine2 or '',
                'city': c.city or '',
                'state': c.state or '',
                'pincode': c.pincode or '',
                'gstin': c.gstin or '',
                'pan': c.pan or '',   # ← added
            }
    except Exception as e:
        logger.warning(f"resolve_customer_names lookup failed: {e}")
    return name_map


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def velavan_get_customers(request):
    try:
        customers = VelavanCustomers.objects.filter(is_active__in=[True])  # ← was is_active=True

        data = []
        for c in customers:
            customer_data = {
                'customer_id':    c.customer_id,
                'name':           c.name,
                'addressLine1':   c.addressLine1,
                'addressLine2':   c.addressLine2,
                'city':           c.city,
                'state':          c.state,
                'pincode':        c.pincode,
                'phone':          c.phone,
                'email':          c.email,
                'gstin':          c.gstin,
                'pan':            c.pan,
                'msme':           c.msme,
                'customer_type':  c.customer_type,
                'company_name':   c.company_name,
                'is_active':      c.is_active,
                'created_by':     getattr(c, 'created_by', None),
                'created_date':   c.created_date.isoformat() if getattr(c, 'created_date', None) else None,
                'lastmodified_date': c.lastmodified_date.isoformat() if getattr(c, 'lastmodified_date', None) else None,
            }
            data.append(customer_data)

        return Response({"status": "success", "data": data}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in velavan_get_customers: {str(e)}\n{traceback.format_exc()}")
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def velavan_create_customer(request):
    try:
        data = request.data
        name = data.get("name")
        user_id = data.get('auth-user-id', 'system')
        outlet_code = data.get('auth-outlet-code','system')
        branch_code = data.get('auth-branch-code', 'system')        
        hospital_code = data.get('auth-hospital-code', 'system')

        if not name:
            return Response(
                {"success": False, "message": "Customer Name is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        phone = data.get("phone", "")
        if phone:
            existing = VelavanCustomers.objects.filter(
                name=name, phone=phone, is_active__in=[True]   # ← was is_active=True
            ).first()
            if existing:
                return Response(
                    {"success": False, "message": "Customer with same name and phone already exists"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        customer = VelavanCustomers(
            name           = name,
            addressLine1   = data.get("addressLine1", ""),
            addressLine2   = data.get("addressLine2", ""),
            city           = data.get("city", ""),
            state          = data.get("state", ""),
            pincode        = data.get("pincode", ""),
            phone          = data.get("phone", ""),
            email          = data.get("email", ""),
            gstin          = data.get("gstin", ""),
            pan            = data.get("pan", ""),
            msme           = data.get("msme", ""),
            customer_type  = data.get("customerType", ""),
            company_name   = data.get("companyName", ""),
            is_active      = True,
            created_by     = user_id,
            outlet_code    = outlet_code,
            branch_code    = branch_code,
            hospital_code  = hospital_code,
        )
        customer.save()

        return Response(
            {
                "success": True,
                "message": "Customer created successfully",
                "data": {
                    "id": str(customer.pk),
                    "customer_id": customer.customer_id,
                    "name": customer.name,
                }
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger.error(f"Error in velavan_create_customer: {str(e)}\n{traceback.format_exc()}")
        return Response(
            {"success": False, "error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def velavan_update_customer(request, customer_id):
    try:
        # ── Confirm the target exists first, purely for the 404 case ──
        existing = VelavanCustomers.objects.filter(customer_id=customer_id).first()
        if not existing:
            return Response(
                {"status": "error", "message": "Customer not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        data = request.data.copy()
        # never let these be overwritten via the update payload
        for field in ["_id", "customer_id", "id"]:
            data.pop(field, None)
        auth_fields = [key for key in data.keys() if key.startswith("auth-")]
        for field in auth_fields:
            data.pop(field, None)

        # accept camelCase from frontend, normalize to model field names
        if "customerType" in data:
            data["customer_type"] = data.pop("customerType")
        if "companyName" in data:
            data["company_name"] = data.pop("companyName")

        updatable_fields = {
            'name', 'addressLine1', 'addressLine2', 'city', 'state', 'pincode',
            'phone', 'email', 'gstin', 'pan', 'msme',
            'customer_type', 'company_name', 'is_active',
        }
        update_kwargs = {f: v for f, v in data.items() if f in updatable_fields}
        update_kwargs['lastmodified_by'] = request.data.get("auth-user-id")
        update_kwargs['lastmodified_date'] = timezone.now()

        # ── Update via QuerySet.update(), keyed on customer_id — NOT
        # instance.save(). save() fetches an object then relies on Django
        # matching it back to the same row by internal pk on UPDATE; if that
        # pk-match fails at the djongo SQL-to-Mongo translation layer, Django
        # silently falls back to INSERT, creating a duplicate document
        # instead of patching the original. QuerySet.update() issues a
        # single direct UPDATE matched on customer_id, sidestepping that
        # entirely — it can never insert. ──
        updated_count = VelavanCustomers.objects.filter(
            customer_id=customer_id
        ).update(**update_kwargs)

        if updated_count == 0:
            return Response(
                {"status": "error", "message": "Update failed — no matching document"},
                status=status.HTTP_404_NOT_FOUND
            )

        updated_customer = VelavanCustomers.objects.filter(customer_id=customer_id).first()

        updated_data = {
            'customer_id':   updated_customer.customer_id,
            'name':          updated_customer.name,
            'addressLine1':  updated_customer.addressLine1,
            'addressLine2':  updated_customer.addressLine2,
            'city':          updated_customer.city,
            'state':         updated_customer.state,
            'pincode':       updated_customer.pincode,
            'phone':         updated_customer.phone,
            'email':         updated_customer.email,
            'gstin':         updated_customer.gstin,
            'pan':           updated_customer.pan,
            'msme':          updated_customer.msme,
            'customer_type': updated_customer.customer_type,
            'company_name':  updated_customer.company_name,
            'is_active':     updated_customer.is_active,
        }

        return Response(
            {"status": "success", "data": updated_data},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error in velavan_update_customer: {str(e)}\n{traceback.format_exc()}")
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def velavan_delete_customer(request, customer_id):
    try:
        customers_collection = db["hospital_velavan_customers"]

        result = customers_collection.update_one(
            {"customer_id": customer_id},
            {"$set": {
                "is_active": False,
                "deleted_by": request.data.get("auth-user-id"),
                "deleted_date": datetime.now()
            }}
        )

        if result.matched_count == 0:
            return Response(
                {"status": "error", "message": "Customer not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {"status": "success", "message": "Customer deleted successfully"},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
def register_sales_return_stock(source_grn_number, item):
    """
    Increments sales_return on the exact stock batch a returned item came
    from, matched by item_id + batch_no (+ grn_number when available).
    Standalone sales without a source_grn_number fall back to item_id +
    batch_no only — best effort, logged if ambiguous.
    """
    stock_collection = db["hospital_velavan_stock"]
    try:
        qty_returned = float(item.get('quantity') or 0)
    except (ValueError, TypeError):
        qty_returned = 0
    if qty_returned <= 0:
        return

    query = {"item_id": item.get('item_id'), "batch_no": item.get('batch_no')}
    if source_grn_number:
        query["grn_number"] = source_grn_number

    matches = list(stock_collection.find(query))
    if not matches:
        logger.warning(f"No stock batch found for sales return: {query}")
        return
    if len(matches) > 1:
        logger.warning(f"Multiple stock batches matched sales return, using first: {query}")

    stock_collection.update_one(
        {"_id": matches[0]["_id"]},
        {"$inc": {"sales_return": qty_returned}}
    )
@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_velavan_sales_return(request):
    try:
        data = request.data
        summary = data.get('summary', {})
        employee_id = data.get('auth-user-id') or 'Anonymous'
        bill_number = data.get('bill_number')

        if not bill_number:
            return Response(
                {"status": "error", "message": "bill_number is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        bill = VelavanSalesBill.objects.filter(bill_number=bill_number).first()
        if not bill:
            return Response(
                {"status": "error", "message": f"Bill {bill_number} not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        remarks = data.get('remarks') or summary.get('remarks') or ''
        if not str(remarks).strip():
            return Response(
                {"status": "error", "message": "Remarks is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        def to_decimal(val, default=0):
            try:
                return float(val) if val not in (None, '') else default
            except (ValueError, TypeError):
                return default

        def sanitize_value(v):
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, (date, datetime)):
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

        raw_items = normalize_items_payload(data.get('items', []))
        clean_items = []
        for item in raw_items:
            item = {k: sanitize_value(v) for k, v in item.items()}
            item.pop('name', None)
            item.pop('itemName', None)
            clean_items.append(item)

        if not clean_items:
            return Response(
                {"status": "error", "message": "At least one item is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        missing_stock_id = [i for i in clean_items if not i.get('stock_id')]
        if missing_stock_id:
            return Response(
                {"status": "error", "message": "Each return item must reference a stock_id"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Validate returned qty doesn't exceed billed qty (net of prior returns) ──
        bill_items = normalize_items_payload(bill.items)
        already_returned = {}
        for prior in VelavanSalesReturn.objects.filter(bill_number=bill_number):
            for pi in normalize_items_payload(prior.items):
                key = pi.get('stock_id')
                already_returned[key] = already_returned.get(key, 0) + float(pi.get('quantity') or 0)

        for ret_item in clean_items:
            key = ret_item.get('stock_id')
            billed_qty = next(
                (float(bi.get('quantity') or 0) for bi in bill_items if bi.get('stock_id') == key),
                0
            )
            prior_returned = already_returned.get(key, 0)
            remaining = billed_qty - prior_returned
            requested = float(ret_item.get('quantity') or 0)
            if requested > remaining:
                return Response(
                    {"status": "error", "message": f"Return quantity {requested} exceeds remaining billed quantity {remaining} for stock_id {key}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        sales_return = VelavanSalesReturn(
            bill_number       = bill_number,
            source_grn_number = bill.source_grn_number or '',
            customer_id        = getattr(bill, 'customer_id', '') or '',
            return_date        = timezone.now().date(),
            ip_number          = bill.ip_number,
            patient_name       = bill.patient_name,
            surgeon_id          = bill.surgeon_id,
            items               = clean_items,
            taxable_amount      = to_decimal(summary.get('taxableAmount')),
            cgst                = to_decimal(summary.get('cgst')),
            sgst                = to_decimal(summary.get('sgst')),
            round_amount        = to_decimal(summary.get('roundAmount')),   # ← added
            total_amount        = to_decimal(summary.get('totalAmount')),
            remarks             = str(remarks).strip(),
            created_by          = employee_id,
        )
        sales_return.save()

        try:
            raw_collection = db["hospital_velavan_salesreturn"]
            raw_collection.update_one(
                {"return_number": sales_return.return_number},
                {"$set": {"items": clean_items}}
            )
        except Exception as items_fix_err:
            logger.error(f"Failed to patch return items for {sales_return.return_number}: {items_fix_err}")

        for item in clean_items:
            try:
                register_sales_return_stock(bill.source_grn_number, item)
            except Exception as stock_err:
                logger.error(f"Stock update failed for return item {item.get('stock_id')}: {stock_err}")

        return JsonResponse({
            'success':       True,
            'status':        'success',
            'message':       'Sales return created successfully',
            'return_number': str(sales_return.return_number),
        }, status=201)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'status': 'error', 'message': str(e)}, status=500)
    
@csrf_exempt
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_velavan_sales_returns(request):
    try:
        from_date_str = request.GET.get('from_date', None)
        to_date_str   = request.GET.get('to_date', None)

        sr_col = db["hospital_velavan_salesreturn"]
        all_records = list(sr_col.find().sort('created_date', -1))

        if from_date_str:
            try:
                from_d = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                all_records = [
                    r for r in all_records
                    if r.get('return_date') and (
                        (r.get('return_date').date() if isinstance(r.get('return_date'), datetime) else r.get('return_date')) >= from_d
                    )
                ]
            except ValueError:
                pass
        if to_date_str:
            try:
                to_d = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                all_records = [
                    r for r in all_records
                    if r.get('return_date') and (
                        (r.get('return_date').date() if isinstance(r.get('return_date'), datetime) else r.get('return_date')) <= to_d
                    )
                ]
            except ValueError:
                pass

        # Lookup bills to get bill_date and customer info
        bill_nums = [doc.get('bill_number') for doc in all_records if doc.get('bill_number')]
        bill_map = {}
        cust_ids = set()
        if bill_nums:
            for b in VelavanSalesBill.objects.filter(bill_number__in=bill_nums):
                bill_map[b.bill_number] = b
                if getattr(b, 'customer_id', None):
                    cust_ids.add(str(b.customer_id))

        for doc in all_records:
            if doc.get('customer_id'):
                cust_ids.add(str(doc.get('customer_id')))

        customer_map = {}
        if cust_ids:
            try:
                for c in VelavanCustomers.objects.filter(customer_id__in=list(cust_ids)):
                    customer_map[str(c.customer_id)] = {
                        'name': c.name,
                        'company_name': c.company_name,
                    }
            except Exception:
                pass

        all_item_ids = set()
        parsed_by_return = {}
        for doc in all_records:
            parsed = normalize_items_payload(doc.get('items', []))
            parsed_by_return[doc.get('return_number')] = parsed
            for item in parsed:
                iid = item.get('item_id')
                if iid not in (None, ''):
                    all_item_ids.add(iid)

        name_map = resolve_item_names(all_item_ids)

        response_data = []
        for doc in all_records:
            ret_num = doc.get('return_number')
            items = parsed_by_return.get(ret_num, [])
            for item in items:
                try:
                    iid = int(item.get('item_id')) if item.get('item_id') not in (None, '') else None
                except (ValueError, TypeError):
                    iid = None
                item['name'] = name_map.get(iid, '') if iid is not None else ''
                for f in ['sellingCgstAmt', 'sellingSgstAmt', 'sellingCost',
                          'unitSellingCost', 'sellingCostBeforeGst', 'quantity']:
                    if f in item:
                        item[f] = convert_decimal128_to_float(item[f])

            b_obj = bill_map.get(doc.get('bill_number'))
            cid = str(doc.get('customer_id') or (getattr(b_obj, 'customer_id', None) if b_obj else '') or '')
            c_info = customer_map.get(cid, {})
            c_name = c_info.get('name', '') or getattr(b_obj, 'patient_name', '') or doc.get('patient_name', '') or ''
            c_comp = c_info.get('company_name', '') or getattr(b_obj, 'company_name', '') or c_name or ''
            if not c_comp and c_name:
                c_comp = c_name

            ret_dt = doc.get('return_date')
            if isinstance(ret_dt, (datetime, date)):
                ret_dt_str = ret_dt.isoformat()
            else:
                ret_dt_str = str(ret_dt) if ret_dt else None

            response_data.append({
                'id':                 str(doc.get('_id')),
                'return_number':      ret_num,
                'bill_number':        doc.get('bill_number'),
                'bill_date':          b_obj.bill_date.isoformat() if b_obj and b_obj.bill_date else None,
                'customer_id':        cid,
                'customer_name':      c_name,
                'customer_company':   c_comp,
                'source_grn_number':  doc.get('source_grn_number'),
                'return_date':        ret_dt_str,
                'ip_number':          doc.get('ip_number', ''),
                'patient_name':       doc.get('patient_name', ''),
                'items':              items,
                'taxable_amount':     convert_decimal128_to_float(doc.get('taxable_amount', 0)),
                'cgst':               convert_decimal128_to_float(doc.get('cgst', 0)),
                'sgst':               convert_decimal128_to_float(doc.get('sgst', 0)),
                'round_amount':       convert_decimal128_to_float(doc.get('round_amount', 0)),
                'total_amount':       convert_decimal128_to_float(doc.get('total_amount', 0)),
                'remarks':            doc.get('remarks', '') or '',
                'created_by':         doc.get('created_by'),
            })

        return Response({'status': 'success', 'data': response_data}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in list_velavan_sales_returns: {str(e)}\n{traceback.format_exc()}")
        return Response({'status': 'error', 'message': str(e)}, status=500)
    
def register_purchase_return_stock(grn_number, item):
    """
    Increments purchase_return on the exact stock batch created when this
    GRN was approved, matched by grn_number + item_id + batch_no — all
    three are always present together on stock docs created via
    push_items_to_stock, so this match is exact (unlike sales returns,
    which sometimes lack a source GRN for standalone bills).
    """
    stock_collection = db["hospital_velavan_stock"]
    try:
        qty_returned = float(item.get('quantity') or 0)
    except (ValueError, TypeError):
        qty_returned = 0
    if qty_returned <= 0:
        return

    query = {
        "grn_number": grn_number,
        "item_id":    item.get('item_id'),
        "batch_no":   item.get('batch_no'),
    }
    matches = list(stock_collection.find(query))
    if not matches:
        logger.warning(f"No stock batch found for purchase return: {query}")
        return
    if len(matches) > 1:
        logger.warning(f"Multiple stock batches matched purchase return, using first: {query}")

    stock_collection.update_one(
        {"_id": matches[0]["_id"]},
        {"$inc": {"purchase_return": qty_returned}}
    )

@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_velavan_purchase_return(request):
    try:
        data = request.data
        summary = data.get('summary', {})
        employee_id = data.get('auth-user-id') or 'Anonymous'
        grn_number = data.get('grn_number')

        if not grn_number:
            return Response(
                {"status": "error", "message": "grn_number is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        invoices_collection = db["hospital_velavaninvoice"]
        invoice_doc = invoices_collection.find_one({"grn_number": grn_number})
        if not invoice_doc:
            return Response(
                {"status": "error", "message": f"GRN {grn_number} not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        def to_decimal(val, default=0):
            try:
                return float(val) if val not in (None, '') else default
            except (ValueError, TypeError):
                return default

        def sanitize_value(v):
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, (date, datetime)):
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

        raw_items = normalize_items_payload(data.get('items', []))
        clean_items = [
            {k: sanitize_value(v) for k, v in item.items()}
            for item in raw_items
        ]

        if not clean_items:
            return Response(
                {"status": "error", "message": "At least one item is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Validate against actual available stock (total - sold - purchase_return
        # + sales_return), not just prior purchase-return history — this correctly
        # accounts for quantity sold via sales bills and any sales returns that
        # put stock back. ──
        stock_collection = db["hospital_velavan_stock"]
        for ret_item in clean_items:
            stock_doc = stock_collection.find_one({
                "grn_number": grn_number,
                "item_id":    ret_item.get('item_id'),
                "batch_no":   ret_item.get('batch_no'),
            })
            if not stock_doc:
                return Response(
                    {"status": "error", "message": f"No stock batch found for item {ret_item.get('item_id')} batch {ret_item.get('batch_no')}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            total_qty       = convert_decimal128_to_float(stock_doc.get('total_quantity', 0))
            sold_qty        = convert_decimal128_to_float(stock_doc.get('sold_quantity', 0))
            purchase_return  = convert_decimal128_to_float(stock_doc.get('purchase_return', 0))
            sales_return     = convert_decimal128_to_float(stock_doc.get('sales_return', 0))
            available = total_qty - sold_qty - purchase_return + sales_return
            requested = float(ret_item.get('quantity') or 0)
            if requested > available:
                return Response(
                    {"status": "error", "message": f"Return quantity {requested} exceeds available stock {available} for item {ret_item.get('item_id')}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        remarks = data.get('remarks') or summary.get('remarks') or ''
        if not str(remarks).strip():
            return Response(
                {"status": "error", "message": "Remarks is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        purchase_return = VelavanPurchaseReturn(
            grn_number     = grn_number,
            vendor_id      = invoice_doc.get('vendor_id', ''),
            return_date    = timezone.now().date(),
            items          = clean_items,
            taxable_amount = to_decimal(summary.get('taxableAmount')),
            cgst           = to_decimal(summary.get('cgst')),
            sgst           = to_decimal(summary.get('sgst')),
            igst           = to_decimal(summary.get('igst')),
            round_amount   = to_decimal(summary.get('roundAmount')),
            total_amount   = to_decimal(summary.get('totalAmount')),
            remarks        = str(remarks).strip(),
            created_by     = employee_id,
        )
        purchase_return.save()

        try:
            raw_collection = db["hospital_velavan_purchasereturn"]
            raw_collection.update_one(
                {"return_number": purchase_return.return_number},
                {"$set": {"items": clean_items}}
            )
        except Exception as items_fix_err:
            logger.error(f"Failed to patch purchase return items for {purchase_return.return_number}: {items_fix_err}")

        for item in clean_items:
            try:
                register_purchase_return_stock(grn_number, item)
            except Exception as stock_err:
                logger.error(f"Stock update failed for purchase return item {item.get('item_id')}: {stock_err}")

        return JsonResponse({
            'success':       True,
            'status':        'success',
            'message':       'Purchase return created successfully',
            'return_number': str(purchase_return.return_number),
        }, status=201)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'status': 'error', 'message': str(e)}, status=500)
    
@csrf_exempt
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_velavan_purchase_returns(request):
    try:
        from_date_str = request.GET.get('from_date', None)
        to_date_str   = request.GET.get('to_date', None)

        pr_col = db["hospital_velavan_purchasereturn"]
        all_records = list(pr_col.find().sort('created_date', -1))

        if from_date_str:
            try:
                from_d = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                all_records = [
                    r for r in all_records
                    if r.get('return_date') and (
                        (r.get('return_date').date() if isinstance(r.get('return_date'), datetime) else r.get('return_date')) >= from_d
                    )
                ]
            except ValueError:
                pass
        if to_date_str:
            try:
                to_d = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                all_records = [
                    r for r in all_records
                    if r.get('return_date') and (
                        (r.get('return_date').date() if isinstance(r.get('return_date'), datetime) else r.get('return_date')) <= to_d
                    )
                ]
            except ValueError:
                pass

        # Lookup invoices to get invoice_no, invoice_date, date, vendor_id, vendor_name
        grn_nums = [doc.get('grn_number') for doc in all_records if doc.get('grn_number')]
        invoice_map = {}
        vendor_ids = set()
        if grn_nums:
            inv_col = db["hospital_velavaninvoice"]
            for inv in inv_col.find({'grn_number': {'$in': grn_nums}}):
                invoice_map[inv.get('grn_number')] = inv
                if inv.get('vendor_id'):
                    vendor_ids.add(str(inv.get('vendor_id')))

        for doc in all_records:
            if doc.get('vendor_id'):
                vendor_ids.add(str(doc.get('vendor_id')))

        vendor_map = {}
        if vendor_ids:
            try:
                v_col = db["hospital_velavan_vendors"]
                v_query_ids = list(vendor_ids) + [int(x) for x in vendor_ids if x.isdigit()]
                for v in v_col.find({'vendor_id': {'$in': v_query_ids}}):
                    vid = str(v.get('vendor_id'))
                    vendor_map[vid] = {
                        'name': v.get('name', ''),
                        'company_name': v.get('company_name', '') or v.get('name', ''),
                    }
            except Exception:
                pass

        all_item_ids = set()
        parsed_by_return = {}
        for doc in all_records:
            parsed = normalize_items_payload(doc.get('items', []))
            parsed_by_return[doc.get('return_number')] = parsed
            for item in parsed:
                iid = item.get('item_id')
                if iid not in (None, ''):
                    all_item_ids.add(iid)

        name_map = resolve_item_names(all_item_ids)

        response_data = []
        for doc in all_records:
            ret_num = doc.get('return_number')
            items = parsed_by_return.get(ret_num, [])
            for item in items:
                try:
                    iid = int(item.get('item_id')) if item.get('item_id') not in (None, '') else None
                except (ValueError, TypeError):
                    iid = None
                item['name'] = name_map.get(iid, '') if iid is not None else ''
                for f in ['cgstAmt', 'sgstAmt', 'taxableAmount', 'totalAmount', 'quantity']:
                    if f in item:
                        item[f] = convert_decimal128_to_float(item[f])

            inv_obj = invoice_map.get(doc.get('grn_number'), {})
            vid = str(doc.get('vendor_id') or inv_obj.get('vendor_id') or '')
            v_info = vendor_map.get(vid, {})
            v_name = v_info.get('name', '') or inv_obj.get('vendor', '') or ''
            v_comp = v_info.get('company_name', '') or inv_obj.get('vendor', '') or v_name or ''

            inv_dt = inv_obj.get('invoice_date')
            if isinstance(inv_dt, (datetime, date)):
                inv_dt_str = inv_dt.isoformat()
            else:
                inv_dt_str = str(inv_dt) if inv_dt else None

            grn_dt = inv_obj.get('date')
            if isinstance(grn_dt, (datetime, date)):
                grn_dt_str = grn_dt.isoformat()
            else:
                grn_dt_str = str(grn_dt) if grn_dt else None

            ret_dt = doc.get('return_date')
            if isinstance(ret_dt, (datetime, date)):
                ret_dt_str = ret_dt.isoformat()
            else:
                ret_dt_str = str(ret_dt) if ret_dt else None

            response_data.append({
                'id':             str(doc.get('_id')),
                'return_number':  ret_num,
                'grn_number':     doc.get('grn_number', ''),
                'invoice_no':     inv_obj.get('invoice_no', ''),
                'invoice_date':   inv_dt_str,
                'grn_date':       grn_dt_str,
                'vendor_id':      vid,
                'vendor_name':    v_name,
                'vendor_company': v_comp,
                'return_date':    ret_dt_str,
                'items':          items,
                'taxable_amount': convert_decimal128_to_float(doc.get('taxable_amount', 0)),
                'cgst':           convert_decimal128_to_float(doc.get('cgst', 0)),
                'sgst':           convert_decimal128_to_float(doc.get('sgst', 0)),
                'igst':           convert_decimal128_to_float(doc.get('igst', 0)),
                'round_amount':   convert_decimal128_to_float(doc.get('round_amount', 0)),
                'total_amount':   convert_decimal128_to_float(doc.get('total_amount', 0)),
                'remarks':        doc.get('remarks', '') or '',
                'created_by':     doc.get('created_by'),
            })

        return Response({'status': 'success', 'data': response_data}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in list_velavan_purchase_returns: {str(e)}\n{traceback.format_exc()}")
        return Response({'status': 'error', 'message': str(e)}, status=500)