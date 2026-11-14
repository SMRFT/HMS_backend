import json
from datetime import datetime, date
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.db import connection
from bson import Decimal128, ObjectId
from decimal import Decimal

from .models import cathlabIntent, ItemMaster
from .serializer import CathLabIntentSerializer
from ..dbcollection import hms_db, department_collection


def clean_mongo_value(val):
    """
    Recursively convert MongoDB types (Decimal128, Decimal, ObjectId, datetime)
    into standard JSON-serializable Python types.
    """
    if isinstance(val, (Decimal128, Decimal)):
        f = float(str(val))
        return int(f) if f.is_integer() else f
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, dict):
        return {k: clean_mongo_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [clean_mongo_value(v) for v in val]
    return val


def extract_auth_info_from_token(request):
    """
    Extracts employee_id, branch_code, outlet_code, hospital_code from
    the request's Authorization JWT token and request headers/data.
    """
    token_emp_id = None
    token_branch = None
    token_outlet = None
    token_hospital = None

    auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION") or ""
    if auth_header:
        token_str = str(auth_header).replace("Bearer ", "").replace("bearer ", "").strip()
        if token_str:
            try:
                import jwt
                payload = jwt.decode(token_str, options={"verify_signature": False})
                token_emp_id = (
                    payload.get("aud")
                    or payload.get("employee_id")
                    or payload.get("employeeId")
                    or payload.get("sub")
                    or payload.get("user_id")
                    or payload.get("userId")
                )
                token_branch = payload.get("branch_code") or payload.get("branch")
                token_outlet = payload.get("outlet_code") or payload.get("outlet")
                token_hospital = payload.get("hospital_code") or payload.get("hospital")
            except Exception:
                pass

    emp_id = (
        token_emp_id
        or request.data.get("auth-user-id")
        or request.data.get("created_by")
        or request.data.get("employee_id")
        or request.headers.get("Auth-User-Id")
        or request.headers.get("Employee-Id")
        or "system"
    )

    branch_code = (
        request.headers.get("Branch-Code")
        or token_branch
        or request.data.get("auth-branch-code")
        or request.data.get("branch_code")
        or "SHB001"
    )

    outlet_code = (
        request.headers.get("Outlet-Code")
        or token_outlet
        or request.data.get("auth-outlet-code")
        or request.data.get("outlet_code")
        or "OLET003"
    )

    hospital_code = (
        request.headers.get("Hospital-Code")
        or token_hospital
        or request.data.get("auth-hospital-code")
        or request.data.get("hospital_code")
        or None
    )

    return str(emp_id).strip(), str(branch_code).strip(), str(outlet_code).strip(), hospital_code


def get_financial_year_string():
    now = datetime.now()
    if now.month >= 4:
        return f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"
    else:
        return f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"


def generate_cathlab_intent_id():
    """
    Generates unique custom ID SINT<FY><5-digit sequence>
    Checking across both hospital_cathlabintent and hospital_storesintent
    """
    fy_str = get_financial_year_string()
    base_prefix = f"SINT{fy_str}"
    max_seq = 0
    try:
        col1 = hms_db["hospital_cathlabintent"]
        col2 = hms_db["hospital_storesintent"]
        for col in [col1, col2]:
            docs = list(col.find(
                {"intent_id": {"$regex": f"^{base_prefix}"}},
                {"intent_id": 1}
            ).sort("intent_id", -1).limit(5))
            for doc in docs:
                val = str(doc.get("intent_id", ""))
                rem = val[len(base_prefix):]
                if rem.isdigit():
                    max_seq = max(max_seq, int(rem))
    except Exception:
        pass

    new_sequence = max_seq + 1
    new_id = f"{base_prefix}{str(new_sequence).zfill(5)}"
    try:
        col1 = hms_db["hospital_cathlabintent"]
        col2 = hms_db["hospital_storesintent"]
        while col1.find_one({"intent_id": new_id}) or col2.find_one({"intent_id": new_id}):
            new_sequence += 1
            new_id = f"{base_prefix}{str(new_sequence).zfill(5)}"
    except Exception:
        pass

    return new_id


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def get_cathlab_items(request):
    """
    Fetches items from hospital_itemmaster where department in ['DEPT027', 'Cath lab']
    and is_active == True.
    """
    try:
        item_collection = hms_db["hospital_itemmaster"]
        query = {
            "is_active": True,
            "$or": [
                {"department": "DEPT027"},
                {"department": {"$regex": "^cath", "$options": "i"}},
                {"department_name": {"$regex": "^cath", "$options": "i"}}
            ]
        }
        items = list(item_collection.find(
            query,
            {
                "item_id": 1,
                "itemName": 1,
                "hsn": 1,
                "department": 1,
                "group": 1,
                "category": 1,
                "unit_price": 1,
                "total_quantity": 1,
                "approved_quantity": 1
            }
        ).sort("itemName", 1))

        formatted = []
        for it in items:
            formatted.append({
                "item_id": it.get("item_id"),
                "itemName": it.get("itemName") or "",
                "name": it.get("itemName") or "",
                "hsn": it.get("hsn") or "-",
                "department": it.get("department") or "DEPT027",
                "unit_price": it.get("unit_price") or 0,
                "available_stock": it.get("total_quantity", 0) - it.get("approved_quantity", 0)
            })

        return Response(clean_mongo_value({"status": "success", "count": len(formatted), "data": formatted}), status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_cathlab_item_batches(request, item_id):
    """
    Fetches available batches and MRP from hospital_storesgrn for the specified item_id.
    """
    try:
        grn_collection = hms_db["hospital_storesgrn"]
        grns = list(grn_collection.find(
            {
                "items.item_id": str(item_id).strip(),
                "is_cancelled": {"$ne": True}
            },
            {
                "grn_number": 1,
                "date": 1,
                "items": 1
            }
        ).sort("date", -1))

        batch_map = {}
        for grn in grns:
            for it in (grn.get("items") or []):
                if str(it.get("item_id", "")).strip() == str(item_id).strip():
                    b_val = str(it.get("batch") or "").strip()
                    if not b_val:
                        continue
                    mrp_val = it.get("mrp")
                    if mrp_val is None or mrp_val == "":
                        mrp_val = it.get("unitPrice") or 0
                    if b_val not in batch_map:
                        batch_map[b_val] = {
                            "batch": b_val,
                            "mrp": mrp_val,
                            "expiry": it.get("expiry") or "",
                            "grn_number": grn.get("grn_number") or "",
                            "quantity": it.get("quantity") or 0
                        }

        batches = list(batch_map.values())
        return Response(clean_mongo_value({"status": "success", "count": len(batches), "data": batches}), status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def create_cathlab_intent(request):
    """
    Creates a new Cath Lab Intent requisition in hospital_cathlabintent
    with exact schema:
    {
      _id: ObjectId(...),
      created_by: '60018',
      created_date: ISODate(...),
      lastmodified_by: null,
      lastmodified_date: null,
      branch_code: 'SHB001',
      outlet_code: 'OLET003',
      hospital_code: null,
      intent_id: 'SINT262707000',
      ipnumber: '',
      is_active: true,
      date: ISODate(...),
      items: [
        {
          item_id: 'ITM26270071903',
          name: 'CD MT BOX',
          hsn: '-',
          batch: '',
          mrp: '',
          quantity: 1,
          status: 'Pending',
          approved_quantity: 0
        }
      ],
      department: 'DEPT027',
      is_approved: false,
      is_billed: false
    }
    """
    try:
        employee_id, branch_code, outlet_code, hospital_code = extract_auth_info_from_token(request)

        raw_date = request.data.get("date")
        if raw_date:
            try:
                parsed_date = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d")
            except Exception:
                parsed_date = timezone.now()
        else:
            parsed_date = timezone.now()

        ipnumber = str(request.data.get("ipnumber") or "").strip()
        department = request.data.get("department") or "DEPT027"

        raw_items = request.data.get("items") or []
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = []

        if not raw_items:
            return Response({"error": "Items list cannot be empty"}, status=status.HTTP_400_BAD_REQUEST)

        clean_items = []
        for it in raw_items:
            qty = int(it.get("quantity") or 1)
            clean_items.append({
                "item_id": str(it.get("item_id", "")),
                "name": str(it.get("name") or it.get("itemName") or ""),
                "hsn": str(it.get("hsn") or "-"),
                "batch": str(it.get("batch") or ""),
                "mrp": it.get("mrp") if it.get("mrp") is not None else "",
                "quantity": qty,
                "status": "Pending",
                "approved_quantity": 0
            })

        intent_id = generate_cathlab_intent_id()
        now_dt = timezone.now()

        doc = {
            "created_by": str(employee_id),
            "created_date": now_dt,
            "lastmodified_by": None,
            "lastmodified_date": None,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "hospital_code": hospital_code,
            "intent_id": intent_id,
            "ipnumber": ipnumber,
            "is_active": True,
            "date": parsed_date,
            "items": clean_items,
            "department": department,
            "is_approved": False,
            "is_billed": False,
            "is_hod_approved": True,
            "hod_status": "Approved"
        }

        col = hms_db["hospital_cathlabintent"]
        result = col.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        doc["date"] = doc["date"].isoformat() if hasattr(doc["date"], "isoformat") else str(doc["date"])
        doc["created_date"] = doc["created_date"].isoformat() if hasattr(doc["created_date"], "isoformat") else str(doc["created_date"])

        return Response(clean_mongo_value({
            "message": "Cath Lab Intent requisition created successfully",
            "intent_id": intent_id,
            "data": doc
        }), status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def get_cathlab_intents(request):
    """
    List Cath Lab Intents with optional date and search filters.
    """
    try:
        from_date = request.data.get("from_date") or request.GET.get("from_date")
        to_date = request.data.get("to_date") or request.GET.get("to_date")
        ipnumber = request.data.get("ipnumber") or request.GET.get("ipnumber")
        search = request.data.get("search") or request.GET.get("search")

        query = {"is_active": True}

        if from_date or to_date:
            query["date"] = {}
            if from_date:
                query["date"]["$gte"] = datetime.strptime(str(from_date)[:10], "%Y-%m-%d")
            if to_date:
                query["date"]["$lte"] = datetime.strptime(str(to_date)[:10], "%Y-%m-%d") + timezone.timedelta(days=1)

        if ipnumber:
            query["ipnumber"] = {"$regex": str(ipnumber).strip(), "$options": "i"}

        if search:
            query["$or"] = [
                {"intent_id": {"$regex": str(search).strip(), "$options": "i"}},
                {"ipnumber": {"$regex": str(search).strip(), "$options": "i"}},
                {"items.name": {"$regex": str(search).strip(), "$options": "i"}}
            ]

        col = hms_db["hospital_cathlabintent"]
        docs = list(col.find(query).sort("created_date", -1))

        formatted = []
        for d in docs:
            d["_id"] = str(d["_id"])
            if isinstance(d.get("date"), (datetime, date)):
                d["date"] = d["date"].isoformat()
            if isinstance(d.get("created_date"), (datetime, date)):
                d["created_date"] = d["created_date"].isoformat()
            formatted.append(d)

        return Response(clean_mongo_value({"status": "success", "count": len(formatted), "data": formatted}), status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

