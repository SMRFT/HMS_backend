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
            try:
                tot = int(float(str(it.get("total_quantity") or 0)))
            except Exception:
                tot = 0
            try:
                appr = int(float(str(it.get("approved_quantity") or 0)))
            except Exception:
                appr = 0
            avail = max(0, tot - appr)

            formatted.append({
                "item_id": it.get("item_id"),
                "itemName": it.get("itemName") or "",
                "name": it.get("itemName") or "",
                "hsn": it.get("hsn") or "-",
                "department": it.get("department") or "DEPT027",
                "unit_price": it.get("unit_price") or 0,
                "total_quantity": tot,
                "approved_quantity": appr,
                "available_stock": avail,
                "stock": avail
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
        patient_name = str(request.data.get("patient_name") or "").strip()
        uhid = str(request.data.get("uhid") or "").strip()
        department = request.data.get("department") or "DEPT027"

        # Auto-resolve uhid and patient_name from Admission & Patient if not provided
        if (not uhid or not patient_name) and ipnumber:
            try:
                from hospital.models import Admission, Patient
                adm = Admission.objects.filter(ipNumber=ipnumber).first()
                if adm:
                    if not uhid and adm.uhid:
                        uhid = str(adm.uhid).strip()
                    if not patient_name and adm.uhid:
                        pat = Patient.objects.filter(uhid=adm.uhid).first()
                        if pat:
                            patient_name = f"{pat.firstName or ''} {pat.lastName or ''}".strip()
            except Exception:
                pass

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

        is_approved_val = request.data.get("is_approved")
        if is_approved_val is None:
            is_approved_val = True
        else:
            is_approved_val = bool(is_approved_val)

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
            "patient_name": patient_name,
            "uhid": uhid,
            "is_active": True,
            "date": parsed_date,
            "items": clean_items,
            "department": department,
            "is_approved": is_approved_val,
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
            search_str = str(search).strip()
            # Find matching IPs from Patient/Admission if user searched by patient name or UHID
            matching_ips = set()
            try:
                from hospital.models import Admission, Patient
                from django.db.models import Q
                p_q = Q(firstName__icontains=search_str) | Q(lastName__icontains=search_str) | Q(uhid__icontains=search_str)
                matched_uhids = list(Patient.objects.filter(p_q).values_list("uhid", flat=True)[:500])
                if matched_uhids:
                    adm_ips = list(Admission.objects.filter(uhid__in=matched_uhids).values_list("ipNumber", flat=True)[:500])
                    matching_ips.update(adm_ips)
            except Exception:
                pass

            or_conds = [
                {"intent_id": {"$regex": search_str, "$options": "i"}},
                {"ipnumber": {"$regex": search_str, "$options": "i"}},
                {"uhid": {"$regex": search_str, "$options": "i"}},
                {"patient_name": {"$regex": search_str, "$options": "i"}},
                {"items.name": {"$regex": search_str, "$options": "i"}}
            ]
            if matching_ips:
                or_conds.append({"ipnumber": {"$in": list(matching_ips)}})

            query["$or"] = or_conds

        col = hms_db["hospital_cathlabintent"]
        docs = list(col.find(query).sort("created_date", -1))

        # Dynamic enrichment of patient_name and uhid for docs (especially legacy records)
        ip_set = {str(d.get("ipnumber", "")).strip() for d in docs if str(d.get("ipnumber", "")).strip()}
        ip_to_uhid = {}
        uhid_to_name = {}

        if ip_set:
            try:
                from hospital.models import Admission, Patient
                admissions = Admission.objects.filter(ipNumber__in=list(ip_set)).values("ipNumber", "uhid")
                uhid_set = set()
                for adm in admissions:
                    ip = adm.get("ipNumber")
                    u = adm.get("uhid")
                    if ip and u:
                        ip_to_uhid[ip] = u
                        uhid_set.add(u)

                for d in docs:
                    if d.get("uhid"):
                        uhid_set.add(str(d.get("uhid")).strip())

                if uhid_set:
                    patients = Patient.objects.filter(uhid__in=list(uhid_set)).values("uhid", "firstName", "lastName")
                    for p in patients:
                        full_name = f"{p.get('firstName') or ''} {p.get('lastName') or ''}".strip()
                        uhid_to_name[p.get("uhid")] = full_name
            except Exception:
                pass

        formatted = []
        for d in docs:
            d["_id"] = str(d["_id"])
            if isinstance(d.get("date"), (datetime, date)):
                d["date"] = d["date"].isoformat()
            if isinstance(d.get("created_date"), (datetime, date)):
                d["created_date"] = d["created_date"].isoformat()

            # Ensure patient_name and uhid are populated
            ip = str(d.get("ipnumber") or "").strip()
            resolved_uhid = d.get("uhid") or ip_to_uhid.get(ip, "")
            resolved_pname = d.get("patient_name") or uhid_to_name.get(resolved_uhid, "")

            d["uhid"] = resolved_uhid
            d["patient_name"] = resolved_pname

            formatted.append(d)

        if search:
            s_lower = str(search).strip().lower()
            formatted = [
                d for d in formatted
                if s_lower in str(d.get("intent_id", "")).lower()
                or s_lower in str(d.get("ipnumber", "")).lower()
                or s_lower in str(d.get("uhid", "")).lower()
                or s_lower in str(d.get("patient_name", "")).lower()
                or any(s_lower in str(it.get("name", "")).lower() for it in d.get("items", []))
            ]

        return Response(clean_mongo_value({"status": "success", "count": len(formatted), "data": formatted}), status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT', 'POST'])
@permission_classes([AllowAny])
def update_cathlab_intent(request, pk=None):
    """
    Update an existing Cath Lab Intent requisition.
    Only allowed before is_billed == True and is_approved == True.
    """
    try:
        intent_pk = pk or request.data.get("intent_id")
        if not intent_pk:
            return Response({"error": "Intent ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        employee_id, branch_code, outlet_code, hospital_code = extract_auth_info_from_token(request)

        col = hms_db["hospital_cathlabintent"]
        or_conds = [{"intent_id": str(intent_pk).strip()}]
        if ObjectId.is_valid(str(intent_pk).strip()):
            or_conds.append({"_id": ObjectId(str(intent_pk).strip())})

        doc = col.find_one({"$or": or_conds, "is_active": True})
        if not doc:
            return Response({"error": "Cath Lab requisition not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)

        # Restrict editing only if already billed
        if doc.get("is_billed") is True:
            return Response(
                {"error": "Cannot edit requisition: It has already been billed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        raw_date = request.data.get("date")
        if raw_date:
            try:
                parsed_date = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d")
            except Exception:
                parsed_date = doc.get("date")
        else:
            parsed_date = doc.get("date")

        ipnumber = str(request.data.get("ipnumber") or "").strip()
        patient_name = str(request.data.get("patient_name") or "").strip()
        uhid = str(request.data.get("uhid") or "").strip()
        department = request.data.get("department") or doc.get("department", "DEPT027")

        # If not provided, resolve from Admission/Patient or preserve existing
        if not patient_name or not uhid:
            if ipnumber:
                try:
                    from hospital.models import Admission, Patient
                    adm = Admission.objects.filter(ipNumber=ipnumber).first()
                    if adm:
                        if not uhid and adm.uhid:
                            uhid = str(adm.uhid).strip()
                        if not patient_name and adm.uhid:
                            pat = Patient.objects.filter(uhid=adm.uhid).first()
                            if pat:
                                patient_name = f"{pat.firstName or ''} {pat.lastName or ''}".strip()
                except Exception:
                    pass
            if not patient_name:
                patient_name = doc.get("patient_name", "")
            if not uhid:
                uhid = doc.get("uhid", "")

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
                "status": it.get("status") or "Pending",
                "approved_quantity": int(it.get("approved_quantity") or 0)
            })

        now_dt = timezone.now()
        update_fields = {
            "date": parsed_date,
            "ipnumber": ipnumber,
            "patient_name": patient_name,
            "uhid": uhid,
            "department": department,
            "items": clean_items,
            "lastmodified_by": str(employee_id),
            "lastmodified_date": now_dt
        }

        col.update_one({"_id": doc["_id"]}, {"$set": update_fields})

        try:
            cathlabIntent.objects.filter(intent_id=doc.get("intent_id")).update(
                date=parsed_date.date() if isinstance(parsed_date, datetime) else parsed_date,
                ipnumber=ipnumber,
                patient_name=patient_name,
                uhid=uhid,
                items=clean_items,
                lastmodified_by=str(employee_id),
                lastmodified_date=now_dt
            )
        except Exception:
            pass

        return Response(clean_mongo_value({
            "status": "success",
            "message": "Cath Lab Intent requisition updated successfully",
            "intent_id": doc.get("intent_id")
        }), status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST', 'DELETE'])
@permission_classes([AllowAny])
def delete_cathlab_intent(request, pk=None):
    """
    Soft-delete a Cath Lab Intent requisition by setting is_active = False.
    Only allowed before is_billed == True and is_approved == True.
    """
    try:
        intent_pk = pk or request.data.get("intent_id")
        if not intent_pk:
            return Response({"error": "Intent ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        employee_id, _, _, _ = extract_auth_info_from_token(request)

        col = hms_db["hospital_cathlabintent"]
        or_conds = [{"intent_id": str(intent_pk).strip()}]
        if ObjectId.is_valid(str(intent_pk).strip()):
            or_conds.append({"_id": ObjectId(str(intent_pk).strip())})

        doc = col.find_one({"$or": or_conds, "is_active": True})
        if not doc:
            return Response({"error": "Cath Lab requisition not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)

        # Restrict deletion only if already billed
        if doc.get("is_billed") is True:
            return Response(
                {"error": "Cannot delete requisition: It has already been billed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        now_dt = timezone.now()
        col.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "is_active": False,
                "lastmodified_by": str(employee_id),
                "lastmodified_date": now_dt
            }}
        )

        try:
            cathlabIntent.objects.filter(intent_id=doc.get("intent_id")).update(
                is_active=False,
                lastmodified_by=str(employee_id),
                lastmodified_date=now_dt
            )
        except Exception:
            pass

        return Response(clean_mongo_value({
            "status": "success",
            "message": "Cath Lab Intent requisition deleted successfully",
            "intent_id": doc.get("intent_id")
        }), status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def get_cathlab_stock_report(request):
    """
    Returns Cath Lab department items with their current stocks, batches,
    GRN dates for each batch, and MRP.
    """
    try:
        items_col = hms_db["hospital_itemmaster"]
        grn_col = hms_db["hospital_storesgrn"]

        # Fetch all active Cath Lab items
        items = list(items_col.find(
            {
                "is_active": True,
                "$or": [
                    {"department": "DEPT027"},
                    {"department": {"$regex": "^cath", "$options": "i"}},
                    {"department_name": {"$regex": "^cath", "$options": "i"}}
                ]
            },
            {
                "item_id": 1,
                "itemName": 1,
                "total_quantity": 1,
                "approved_quantity": 1,
                "unit_price": 1,
                "hsn": 1,
                "department": 1,
                "department_name": 1
            }
        ).sort("itemName", 1))

        item_map = {str(it.get("item_id", "")).strip(): it for it in items if it.get("item_id")}
        all_item_ids = list(item_map.keys())

        # Fetch GRNs containing these items
        grns = list(grn_col.find(
            {
                "items.item_id": {"$in": all_item_ids},
                "is_cancelled": {"$ne": True}
            },
            {
                "grn_number": 1,
                "date": 1,
                "items": 1
            }
        ).sort("date", -1))

        # Group batches by item_id
        item_batches = {}
        for g in grns:
            grn_no = g.get("grn_number") or ""
            grn_date = g.get("date")
            formatted_date = (
                grn_date.strftime("%Y-%m-%d")
                if hasattr(grn_date, "strftime")
                else str(grn_date)[:10] if grn_date else ""
            )

            for gi in (g.get("items") or []):
                iid = str(gi.get("item_id", "")).strip()
                if iid in item_map:
                    b_val = str(gi.get("batch") or "").strip()
                    mrp_val = gi.get("mrp")
                    if mrp_val is None or mrp_val == "":
                        mrp_val = gi.get("unitPrice") or 0
                    p_rate = gi.get("unitPrice") or gi.get("purchaseRate") or 0
                    p_cost = gi.get("purchaseCost") or 0
                    qty_val = gi.get("quantity") or 0

                    if iid not in item_batches:
                        item_batches[iid] = []

                    # Keep unique batches (most recent GRN date first)
                    existing = next((b for b in item_batches[iid] if b["batch"] == b_val), None)
                    if not existing and b_val:
                        item_batches[iid].append({
                            "batch": b_val,
                            "grn_number": grn_no,
                            "grn_date": formatted_date,
                            "mrp": float(str(mrp_val)) if mrp_val else 0,
                            "purchase_rate": float(str(p_rate)) if p_rate else 0,
                            "purchase_cost": float(str(p_cost)) if p_cost else 0,
                            "quantity": float(str(qty_val)) if qty_val else 0,
                            "expiry": gi.get("expiry") or ""
                        })

        # Build clean item-wise report rows with multiple batches
        report_data = []
        for iid, it in item_map.items():
            tot_stock = it.get("total_quantity", 0) or 0
            appr_stock = it.get("approved_quantity", 0) or 0
            avail_stock = max(0, tot_stock - appr_stock)
            item_name = it.get("itemName") or ""
            hsn = it.get("hsn") or "-"
            unit_price = it.get("unit_price") or 0

            batches = item_batches.get(iid, [])
            latest_b = batches[0] if batches else None
            
            top_mrp = latest_b["mrp"] if (latest_b and latest_b.get("mrp")) else (float(str(unit_price)) if unit_price else 0)
            top_prate = latest_b["purchase_rate"] if (latest_b and latest_b.get("purchase_rate")) else 0
            top_batch = latest_b["batch"] if latest_b else "-"
            top_grn_no = latest_b["grn_number"] if latest_b else "-"
            top_grn_date = latest_b["grn_date"] if latest_b else "-"

            report_data.append({
                "item_id": iid,
                "item_name": item_name,
                "hsn": hsn,
                "stock": avail_stock,
                "total_stock": tot_stock,
                "approved_stock": appr_stock,
                "batch": top_batch,
                "grn_number": top_grn_no,
                "grn_date": top_grn_date,
                "mrp": top_mrp,
                "purchase_rate": top_prate,
                "expiry": latest_b.get("expiry") if latest_b else "-",
                "has_batch": bool(batches),
                "batches": batches,
                "batch_count": len(batches)
            })

        # Optional filters
        search = (request.data.get("search") or request.GET.get("search") or "").strip().lower()
        in_stock_only = request.data.get("in_stock_only") or request.GET.get("in_stock_only")
        if isinstance(in_stock_only, str):
            in_stock_only = in_stock_only.lower() in ["true", "1", "yes"]

        filtered = report_data
        if in_stock_only:
            filtered = [r for r in filtered if r["stock"] > 0]

        if search:
            filtered = [
                r for r in filtered
                if search in r["item_name"].lower()
                or search in r["item_id"].lower()
                or search in str(r["batch"]).lower()
                or search in str(r["grn_number"]).lower()
            ]

        return Response(clean_mongo_value({
            "status": "success",
            "count": len(filtered),
            "total_items": len(item_map),
            "data": filtered
        }), status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


