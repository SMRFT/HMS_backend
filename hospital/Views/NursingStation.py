from rest_framework.decorators import api_view

from rest_framework.response import Response

from rest_framework import status

import os

import re

from datetime import datetime, timedelta

from ..models import Admission, PharmacyBilling, PharmacyItem, PharmacyStock, WardReturnDetails

from ..serializers import AdmissionSerializer, WardReturnDetailsSerializer

from django.conf import settings

from django.db import DatabaseError

from django.http import JsonResponse

from pymongo import MongoClient

from datetime import datetime

from django.utils import timezone

# Auth/permissions

from pyauth.auth import HasRoleAndDataPermission, HasRolePermission

from rest_framework.decorators import api_view, permission_classes

import traceback

import pytz

from rest_framework.decorators import api_view

from rest_framework.response import Response

from datetime import datetime, timedelta

import pytz

import traceback

from pymongo import MongoClient, ReturnDocument

import os

MONGO_URI = os.getenv("GLOBAL_DB_HOST")

client = MongoClient(MONGO_URI)

mongo_db = client["HMS"]

global_db = client["Global"]

profile_collection = global_db["backend_diagnostics_profile"]

room_collection = mongo_db["hospital_room"]

from .dbcollection import get_patient_name_by_uhid, get_patient_details_by_uhid, get_employee_name_by_id, get_doctor_name_by_id

@api_view(["GET"])

# @permission_classes([HasRoleAndDataPermission])

def get_admission_list(request):

    try:

        from_date = request.GET.get("from_date")

        to_date = request.GET.get("to_date")

        query = {"is_admitted": True, "is_cancelled": {"$ne": True}, "is_discharged": {"$ne": True}}

        if from_date and to_date:

            ist = pytz.timezone("Asia/Kolkata")

            start_ist = ist.localize(datetime.strptime(from_date, "%Y-%m-%d"))

            end_ist = ist.localize(datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1))

            start_utc = start_ist.astimezone(pytz.UTC)

            end_utc = end_ist.astimezone(pytz.UTC)

            query["admissionDateTime"] = {"$gte": start_utc, "$lt": end_utc}

            

        raw_admissions = list(mongo_db["hospital_admission"].find(query).sort("admissionDateTime", -1))

        

        # Serialize BSON properly

        data = serialize_doc(raw_admissions)

        

        uhid_set = set()

        doc_query_ids = set()

        room_no_set = set()

        # Phase 1: Pre-process items and extract active room shifting

        for item in data:

            if "_id" in item:

                item["id"] = item["_id"]

            if item.get("uhid") and not item.get("patient_details"):

                uhid_set.add(item.get("uhid"))

            for doctor_field in ["admittingDoctor", "consultingDoctor"]:

                d_id = item.get(doctor_field)

                if d_id:

                    s_id = str(d_id).strip()

                    doc_query_ids.add(s_id)

                    if s_id.isdigit():

                        try:

                            doc_query_ids.add(int(s_id))

                        except ValueError:

                            pass

            room_no = item.get("roomNo")

            for field in ["roomShiftingDetails", "roomShitingDetails", "room_details"]:

                shifting = item.get(field, [])

                if shifting and isinstance(shifting, list):

                    active_shift = next((s for s in shifting if s.get("is_roomActive")), None)

                    if active_shift:

                        item["roomNo"] = active_shift.get("newRoomNo", active_shift.get("roomNo", ""))

                        item["bedNo"] = active_shift.get("newBedNo", active_shift.get("bedNo", ""))

                        room_no = item["roomNo"]

                        break

            if room_no:

                room_no_set.add(str(room_no).strip())

        # Phase 2: Batch fetch patient details

        patient_map = {}

        if uhid_set:

            pts = list(mongo_db.hospital_patient.find({"uhid": {"$in": list(uhid_set)}}))

            for p in pts:

                patient_map[p.get("uhid")] = serialize_doc(p)

        # Phase 3: Batch fetch doctor names

        doc_name_map = {}

        if doc_query_ids:

            docs = list(profile_collection.find(

                {"$or": [{"employeeId": {"$in": list(doc_query_ids)}}, {"employeeName": {"$in": list(doc_query_ids)}}]},

                {"employeeName": 1, "employeeId": 1, "_id": 0}

            ))

            for d in docs:

                emp_name = d.get("employeeName")

                emp_id = d.get("employeeId")

                if emp_name:

                    if emp_id is not None:

                        doc_name_map[str(emp_id).strip()] = emp_name

                    doc_name_map[emp_name.strip()] = emp_name

        # Phase 4: Batch fetch room details

        room_map = {}

        if room_no_set:

            rooms = list(room_collection.find(

                {"room_number": {"$in": list(room_no_set)}},

                {"_id": 0, "room_number": 1, "room_category": 1, "block": 1, "nursing_station": 1}

            ))

            for r in rooms:

                room_map[str(r.get("room_number")).strip()] = r

        # Phase 5: Fetch master mappings for block, category, ward IDs

        block_map = {b.get("block_name"): str(b.get("block_id")) for b in mongo_db.hospital_block.find({}, {"block_name": 1, "block_id": 1}) if b.get("block_name")}

        cat_map = {c.get("category_name"): str(c.get("room_category_id")) for c in mongo_db.hospital_roomcategory.find({}, {"category_name": 1, "room_category_id": 1}) if c.get("category_name")}

        ward_map = {w.get("ward_name"): str(w.get("_id")) for w in mongo_db.hospital_Wards.find({}, {"ward_name": 1, "_id": 1}) if w.get("ward_name")}

        # Phase 6: Populate item fields without nested queries

        for item in data:

            p_details = item.get("patient_details", {})

            if not p_details and item.get("uhid"):

                p_details = patient_map.get(item.get("uhid"), {})

                if p_details:

                    item["patient_details"] = p_details

            if p_details:

                fname = p_details.get("firstName", "")

                lname = p_details.get("lastName", "")

                item["patient_name"] = f"{fname} {lname}".strip()

            else:

                item["patient_name"] = ""

            for doctor_field in ["admittingDoctor", "consultingDoctor"]:

                doctor_id = item.get(doctor_field)

                if doctor_id:

                    s_id = str(doctor_id).strip()

                    if s_id in doc_name_map:

                        item[doctor_field] = doc_name_map[s_id]

            room_no = str(item.get("roomNo") or "").strip()

            if room_no and room_no in room_map:

                r = room_map[room_no]

                r_cat = r.get("room_category")

                b_name = r.get("block")

                s_name = r.get("nursing_station")

                item["room_category"] = r_cat

                item["block"] = b_name

                item["nursing_station"] = s_name

                if b_name and b_name in block_map:

                    item["block_id"] = block_map[b_name]

                if r_cat and r_cat in cat_map:

                    item["room_category_id"] = cat_map[r_cat]

                if s_name and s_name in ward_map:

                    item["nursing_station_id"] = ward_map[s_name]

            else:

                item["room_category"] = item.get("room_category")

                item["block"] = item.get("block")

                item["nursing_station"] = item.get("nursing_station")

        # Phase 7: Batch compute pending request flags for admitted patients
        active_ips = [it.get("ipNumber") for it in data if it.get("ipNumber") and not it.get("is_discharged")]
        if active_ips:
            try:
                pending_inv = list(mongo_db["hospital_investbilling"].find(
                    {
                        "ipNumber": {"$in": active_ips},
                        "is_ward_request": True,
                        "status": {"$nin": ["Cancelled", "Completed", "Result Entered", "Outsourced", "Printed", "Dispatched", "cancelled", "completed", "outsourced", "printed", "dispatched"]},
                        "is_active": True
                    },
                    {"ipNumber": 1, "ward_request_type": 1, "item": 1, "status": 1, "_id": 0}
                ))
                pending_pharm = list(mongo_db["hospital_pharmacybilling"].find(
                    {
                        "$or": [{"inpatient_number": {"$in": active_ips}}, {"ipNumber": {"$in": active_ips}}],
                        "is_ward_request": True,
                        "is_deleted": {"$ne": True},
                        "billing_status": {"$in": ["Pending", "Draft", "Processing"]}
                    },
                    {"inpatient_number": 1, "ipNumber": 1, "_id": 0}
                ))
                pending_diet = list(mongo_db["hospital_patientdietorder"].find(
                    {
                        "$or": [{"inpatient_number": {"$in": active_ips}}, {"ipNumber": {"$in": active_ips}}],
                        "status": {"$in": ["Ordered", "Received"]}
                    },
                    {"inpatient_number": 1, "ipNumber": 1, "_id": 0}
                ))
                pending_laundry = list(mongo_db["hospital_laundrywardrequest"].find(
                    {
                        "$or": [{"inpatient_number": {"$in": active_ips}}, {"ipNumber": {"$in": active_ips}}],
                        "status": "Pending"
                    },
                    {"inpatient_number": 1, "ipNumber": 1, "_id": 0}
                ))
                pending_implants = list(mongo_db["hospital_implant_request"].find(
                    {
                        "$or": [{"inpatient_number": {"$in": active_ips}}, {"ipNumber": {"$in": active_ips}}],
                        "is_active": True
                    },
                    {"inpatient_number": 1, "ipNumber": 1, "_id": 0}
                ))
                pending_map = {}
                for p_doc in pending_inv:
                    p_ip = p_doc.get("ipNumber")
                    w_type = p_doc.get("ward_request_type", "LAB")
                    doc_st = str(p_doc.get("status") or "").strip().lower()
                    raw_items = p_doc.get("item", [])
                    if isinstance(raw_items, list) and raw_items:
                        has_pending = any(
                            isinstance(it, dict) and str(it.get("status") or doc_st).strip().lower() not in ["cancelled", "completed", "result entered", "outsourced", "printed", "dispatched"] and not it.get("cancelled")
                            for it in raw_items
                        )
                        if not has_pending:
                            continue
                    k = "radiology" if w_type == "RADIOLOGY" else "lab"
                    pending_map.setdefault(p_ip, {}).setdefault(k, 0)
                    pending_map[p_ip][k] += 1
                for p_doc in pending_pharm:
                    p_ip = p_doc.get("inpatient_number") or p_doc.get("ipNumber")
                    pending_map.setdefault(p_ip, {}).setdefault("pharmacy", 0)
                    pending_map[p_ip]["pharmacy"] += 1
                for p_doc in pending_diet:
                    p_ip = p_doc.get("inpatient_number") or p_doc.get("ipNumber")
                    pending_map.setdefault(p_ip, {}).setdefault("diet", 0)
                    pending_map[p_ip]["diet"] += 1
                for p_doc in pending_laundry:
                    p_ip = p_doc.get("inpatient_number") or p_doc.get("ipNumber")
                    pending_map.setdefault(p_ip, {}).setdefault("laundry", 0)
                    pending_map[p_ip]["laundry"] += 1
                for p_doc in pending_implants:
                    p_ip = p_doc.get("inpatient_number") or p_doc.get("ipNumber")
                    pending_map.setdefault(p_ip, {}).setdefault("implant", 0)
                    pending_map[p_ip]["implant"] += 1
                for item in data:
                    p_ip = item.get("ipNumber")
                    c_dict = pending_map.get(p_ip, {})
                    item["pending_counts"] = c_dict
                    item["pending_total"] = sum(c_dict.values())
            except Exception as e_pend:
                print(f"Error computing pending counts: {e_pend}")

        return Response({

            "success": True,

            "count": len(data),

            "data": data

        })

    except Exception as e:

        print("ERROR OCCURRED:", e)

        print(traceback.format_exc())

        return Response({

            "success": False,

            "error": str(e)

        }, status=500)

    

    

from rest_framework.decorators import api_view

from rest_framework.response import Response

from rest_framework import status

from pymongo import MongoClient

import os

# MongoDB Configuration

MONGO_URI = os.getenv("GLOBAL_DB_HOST")

DB_NAME = "HMS"

COLLECTION_NAME = "hospital_nursingstation"

client = MongoClient(MONGO_URI)

mongo_db = client[DB_NAME]

collection = mongo_db[COLLECTION_NAME]

@api_view(["GET"])

# @permission_classes([HasRoleAndDataPermission])

def get_wards_list(request):

    try:

        # ✅ Fetch only active wards

        wards_cursor = collection.find(

            {"is_active": True},      # filter

            {"_id": 1, "ward_name": 1, "ward_id": 1}  # projection (include _id, ward_id, ward_name)

        ).sort("ward_id", 1)

        wards = []

        for d in wards_cursor:

            w_id = d.get("ward_id")
            w_name = d.get("ward_name", "")
            wards.append({

                "id": str(d["_id"]),

                "ward_id": w_id,

                "ward_name": w_name,

                "nursing_station_id": str(w_id) if w_id is not None else str(d["_id"]),

                "nursing_station_name": w_name

            })

        return Response({

            "success": True,

            "data": wards

        }, status=status.HTTP_200_OK)

    except Exception as e:

        return Response({

            "success": False,

            "error": str(e)

        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET"])

def get_location_mapping(request):

    """

    Returns a complete mapping of all rooms to their blocks, categories, and nursing stations.

    Includes room_status and bed_status / is_blocked for room & bed status rendering.

    """

    try:

        rooms = list(mongo_db["hospital_room"].find(

            {"is_active": True},

            {"room_number": 1, "room_category": 1, "block": 1, "nursing_station": 1, "beds": 1, "capacity": 1, "room_status": 1, "status": 1, "is_blocked": 1}

        ))

        

        # Pre-fetch ID mappings to avoid repeated lookups

        blocks_map = {b.get("block_name"): str(b.get("block_id")) for b in mongo_db["hospital_block"].find({}, {"block_name": 1, "block_id": 1}) if b.get("block_name")}

        cats_map = {c.get("category_name"): str(c.get("room_category_id")) for c in mongo_db["hospital_roomcategory"].find({}, {"category_name": 1, "room_category_id": 1}) if c.get("category_name")}

        wards_map = {w.get("ward_name"): str(w.get("_id")) for w in mongo_db["hospital_Wards"].find({}, {"ward_name": 1}) if w.get("ward_name")}

        enriched = []

        for r in rooms:

            b_name = r.get("block")

            c_name = r.get("room_category")

            s_name = r.get("nursing_station")

            r_status = r.get("room_status") or r.get("status") or ""

            r_blocked = bool(r.get("is_blocked") or str(r_status).strip().lower() == "blocked")

            beds_list = r.get("beds", [])

            processed_beds = []

            if isinstance(beds_list, list):

                for bed in beds_list:

                    if isinstance(bed, dict):

                        b_status = bed.get("bed_status") or bed.get("status") or ""

                        b_blocked = bool(bed.get("is_blocked") or str(b_status).strip().lower() == "blocked" or r_blocked)

                        processed_beds.append({

                            "bed_no": bed.get("bed_number") or bed.get("bed_no") or bed.get("bedNumber"),

                            "bed_number": bed.get("bed_number") or bed.get("bed_no") or bed.get("bedNumber"),

                            "bed_status": b_status,

                            "status": b_status,

                            "is_blocked": b_blocked

                        })

                    else:

                        processed_beds.append({

                            "bed_no": str(bed),

                            "bed_number": str(bed),

                            "is_blocked": r_blocked

                        })

            enriched.append({

                "room_no": r.get("room_number"),

                "room_number": r.get("room_number"),

                "block": b_name,

                "block_id": blocks_map.get(b_name),

                "category": c_name,

                "room_category": c_name,

                "room_category_id": cats_map.get(c_name),

                "nursing_station": s_name,

                "nursing_station_id": wards_map.get(s_name),

                "beds": processed_beds if processed_beds else beds_list,

                "capacity": r.get("capacity", 0),

                "room_status": r_status,

                "status": r_status,

                "is_blocked": r_blocked

            })

            

        return Response({"success": True, "data": enriched})

    except Exception as e:

        print("ERROR IN GET_LOCATION_MAPPING:", e)

        return Response({"success": False, "error": str(e)}, status=500)

MONGO_URI = os.getenv("GLOBAL_DB_HOST")

client = MongoClient(MONGO_URI)

mongo_db = client["HMS"]

@api_view(["GET"])

# @permission_classes([HasRoleAndDataPermission])

def get_LabBillType_list(request):

    try:

        collection = mongo_db["hospital_billtype"]

        # Fetch all active bill types intended for ward requests

        billtypes_cursor = collection.find(

            {

                "ward_request": True,

                "is_active": True

            },

            {

                "_id": 0

            }

        )

        

        billtypes = list(billtypes_cursor)

        if not billtypes:

            return Response({

                "success": False,

                "message": "No Lab Bill Types found for ward requests"

            })

        return Response({

            "success": True,

            "data": billtypes

        })

    except Exception as e:

        return Response({

            "success": False,

            "error": str(e)

        })

from rest_framework.response import Response

from rest_framework.decorators import api_view

from ..models import Admission

from ..serializers import AdmissionSerializer

@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def uhidadmissionstatus(request):

    uhid = request.GET.get("uhid")

    admission = mongo_db["hospital_admission"].find_one({"uhid": uhid})

    if not admission:

        return Response({

            "success": True,

            "admitted": False,

            "data": []

        })

    admitted = False

    # ✅ Updated condition including is_admitted

    if (

        admission.get("is_admitted") is True and

        admission.get("is_cancelled") is not True and

        admission.get("is_discharged") is not True

    ):

        admitted = True

    formatted_data = serialize_doc(admission)

    if "_id" in formatted_data:

        formatted_data["id"] = formatted_data["_id"]

    return Response({

        "success": True,

        "admitted": admitted,

        "data": formatted_data

    })

def serialize_doc(doc):

    """Recursively convert MongoDB types to JSON-serializable types."""

    from bson import Decimal128, ObjectId

    import json

    if isinstance(doc, dict):

        return {k: serialize_doc(v) for k, v in doc.items()}

    elif isinstance(doc, list):

        return [serialize_doc(i) for i in doc]

    elif isinstance(doc, Decimal128):

        return float(doc.to_decimal())

    elif isinstance(doc, ObjectId):

        return str(doc)

    elif isinstance(doc, datetime):

        return doc.isoformat()

    return doc


def compute_investbill_rollup_status(items):
    """
    Computes parent investbill status based on individual item statuses:
    - If all items are 'Cancelled': 'Cancelled'
    - Active items = [it for it in items if it.get("status") != "Cancelled"]
    - If active items exist:
        - If all active items in ['Completed', 'Result Entered']: 'Result Entered'
        - If any active item is 'Completed' or 'Result Entered' and some are 'Result Pending': 'Partially Completed'
        - If all active items are 'Result Pending': 'Result Pending'
    - If no items at all: 'Result Pending'
    """
    if not items:
        return "Result Pending"
    statuses = [it.get("status") or "Result Pending" for it in items if isinstance(it, dict)]
    if not statuses:
        return "Result Pending"
    if all(s == "Cancelled" for s in statuses):
        return "Cancelled"
    active_statuses = [s for s in statuses if s != "Cancelled"]
    if not active_statuses:
        return "Cancelled"
    if all(s in ["Completed", "Result Entered"] for s in active_statuses):
        return "Result Entered"
    if any(s in ["Completed", "Result Entered"] for s in active_statuses):
        return "Partially Completed"
    return "Result Pending"


@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def get_lab_ward_requests(request):

    try:

        uhid = request.GET.get("uhid")

        ip_number = request.GET.get("ipNumber")

        query = {

            "is_active": True,

            "is_ward_request": True,

            "ward_request_type": "LAB"

        }

        if uhid:

            query["uhid"] = uhid

        if ip_number:

            query["ipNumber"] = ip_number

        # Fetch from the centralized investbilling collection

        ward_req_collection = mongo_db["hospital_investbilling"]

        requests_data = list(ward_req_collection.find(query).sort("created_date", -1))

        # Enrich and format for the frontend component

        # Build doctor mapping (employeeId -> employeeName)
        doc_map = {}
        try:
            from pymongo import MongoClient
            import os
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
            for d in g_client["Global"]["backend_diagnostics_profile"].find({}, {"employeeId": 1, "employeeName": 1}):
                if d.get("employeeId") and d.get("employeeName"):
                    doc_map[str(d["employeeId"]).strip()] = str(d["employeeName"]).strip()
        except Exception:
            pass

        formatted_data = []

        for doc in requests_data:

            import json

            # Parse 'item' field back to list

            item_data = doc.get("item", "[]")

            if isinstance(item_data, str):

                try:

                    items = json.loads(item_data)

                except json.JSONDecodeError:

                    items = []

            else:

                items = item_data

            

            # Map tests for the frontend structure

            tests = []

            for itm in items:
                it_st = itm.get("status") or doc.get("status") or "Result Pending"
                if it_st == "Cancelled":
                    continue

                tests.append({
                    "test_id": itm.get("test_id", ""),
                    "name": itm.get("itemName", ""),
                    "billTypeNo": itm.get("billTypeNo", ""),
                    "nabh_code": itm.get("nabh_code", ""),
                    "price": itm.get("price", 0),
                    "quantity": itm.get("quantity", 1),
                    "collectionTime": itm.get("collectionTime", ""),
                    "status": it_st
                })
            
            formatted_doc = {
                "id": str(doc.get("_id")),
                "status": doc.get("status", "Result Pending"),
                "cancelReason": doc.get("cancel_reason", ""),
                "reqDate": doc.get("created_date").strftime("%d/%m/%Y") if doc.get("created_date") else "",
                "reqTime": doc.get("created_date").strftime("%I:%M %p") if doc.get("created_date") else "",
                "userName": doc.get("created_by", ""),
                "billNo": doc.get("investBillNo", ""),
                "billType": (items[0].get("billTypeNo") if items and isinstance(items[0], dict) else "") or doc.get("billTypeName", "") or doc.get("billTypeNo", "") or str(doc.get("bill_type", "")),
                "billTypeNo": doc.get("billTypeNo", ""),
                

                "wardName": doc.get("wardName", ""),

                "doctorName": doc_map.get(str(doc.get("doctor") or "").strip(), doc.get("doctorName") or doc.get("doctor", "")),
                "doctor": str(doc.get("doctor") or "").strip(),

                "tests": tests

            }

            formatted_data.append(formatted_doc)

        return Response({

            "success": True,

            "data": serialize_doc(formatted_data)

        })

    except Exception as e:

        print(traceback.format_exc())

        return Response({

            "success": False,

            "error": str(e)

        }, status=500)

@api_view(["POST"])

@permission_classes([HasRoleAndDataPermission])

def save_lab_ward_request(request):
    try:
        import json
        from pymongo import ReturnDocument
        data = request.data

        current_user = data.get("auth-user-id", "system")
        branch_code = data.get("auth-branch-code", "system")
        outlet_code = (
            request.data.get("auth-outlet-code") or
            request.headers.get("Outlet-Code") or "system"
        )
        hospital_code = data.get("auth-hospital-code", "system")

        uhid = str(data.get("uhid") or "").strip()
        ip_number = str(data.get("ipNumber") or data.get("ip_number") or "").strip()

        # Lookup Admission & Patient
        adm_doc = None
        if ip_number:
            adm_doc = mongo_db["hospital_admission"].find_one({"ipNumber": ip_number, "is_admitted": True, "is_cancelled": {"$ne": True}})
            if not adm_doc:
                adm_doc = mongo_db["hospital_admission"].find_one({"ipNumber": ip_number})
        if not adm_doc and uhid:
            adm_doc = mongo_db["hospital_admission"].find_one({"uhid": uhid, "is_admitted": True, "is_cancelled": {"$ne": True}})
            if not adm_doc:
                adm_doc = mongo_db["hospital_admission"].find_one({"uhid": uhid})

        pt_doc = None
        if uhid:
            pt_doc = mongo_db["hospital_patient"].find_one({"uhid": uhid})

        # Resolve Doctor ID (employeeId)
        raw_doctor = data.get("doctor") or ""
        doctor_id = str(raw_doctor).strip()
        if doctor_id:
            try:
                from pymongo import MongoClient
                import os
                g_client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
                doc_profile = g_client["Global"]["backend_diagnostics_profile"].find_one({
                    "$or": [{"employeeName": doctor_id}, {"employeeId": doctor_id}]
                })
                if doc_profile and doc_profile.get("employeeId"):
                    doctor_id = str(doc_profile.get("employeeId")).strip()
            except Exception as e:
                print("Doctor lookup error in save_lab_ward_request:", e)

        # Resolve Room No
        raw_r = str(data.get("roomNo") or data.get("room_no") or "").strip()
        if raw_r in ["", "-", "None", "null"]:
            raw_r = str(data.get("wardName") or data.get("ward_name") or "").strip()
        if raw_r in ["-", "None", "null"]:
            raw_r = ""
        room_no = raw_r

        if not room_no and adm_doc:
            for field in ["roomShiftingDetails", "roomShitingDetails", "room_details"]:
                shifting = adm_doc.get(field, [])
                if shifting and isinstance(shifting, list):
                    active_shift = next((s for s in shifting if s.get("is_roomActive")), None)
                    if not active_shift and shifting:
                        active_shift = shifting[-1]
                    if active_shift and isinstance(active_shift, dict):
                        found_room = active_shift.get("newRoomNo") or active_shift.get("roomNo") or active_shift.get("roomNumber") or active_shift.get("room_number")
                        if found_room:
                            room_no = str(found_room).strip()
                            break
            if not room_no:
                room_no = str(adm_doc.get("roomNo") or adm_doc.get("room_no") or adm_doc.get("ward_name") or adm_doc.get("wardName") or "").strip()
        if room_no in ["-", "None", "null"]:
            room_no = ""

        # Resolve Age & Age Type
        age = str(data.get("age") or "").strip()
        age_type = str(data.get("age_type") or "Y").strip()
        if not age:
            if pt_doc and pt_doc.get("age"):
                age = str(pt_doc.get("age"))
                age_type = str(pt_doc.get("age_type") or "Y")
            elif adm_doc and adm_doc.get("age"):
                age = str(adm_doc.get("age"))
                age_type = str(adm_doc.get("age_type") or "Y")

        # Resolve bill_type (int) and billTypeNo (str)
        raw_bt = data.get("bill_type")
        bill_type_no = str(data.get("billTypeNo") or "LAB01").strip()
        try:
            bill_type_val = int(raw_bt) if raw_bt is not None else 16
        except (ValueError, TypeError):
            bill_type_val = raw_bt or 16

        # Robust Item Fetching
        raw_tests = data.get("item") or data.get("selectedTests") or data.get("items") or []
        if isinstance(raw_tests, str):
            try:
                raw_tests = json.loads(raw_tests)
            except Exception:
                raw_tests = []
        if not isinstance(raw_tests, list):
            raw_tests = []

        # Auto-enrich NABH code
        nabh_records = list(mongo_db["hospital_lab_nabh_rate"].find({}, {"_id": 0, "test_id": 1, "nabh_code": 1}))
        nabh_map = {str(r.get("test_id", "")).strip(): str(r.get("nabh_code", "")).strip() for r in nabh_records if r.get("test_id") is not None}

        enriched_tests = []
        total_price = 0
        for t in raw_tests:
            if not isinstance(t, dict):
                continue
            item_btn = str(t.get("billTypeNo") or bill_type_no or "LAB01").strip()
            t_id_raw = str(t.get("test_id") or "").strip()
            item_nabh = str(t.get("nabh_code") or "").strip()
            if not item_nabh and t_id_raw in nabh_map:
                item_nabh = nabh_map[t_id_raw]

            p_val = float(t.get("price", 0) or 0)
            total_price += p_val

            t_id_final = int(t_id_raw) if t_id_raw.isdigit() else (t.get("test_id") or "")
            enriched_tests.append({
                "itemName": str(t.get("itemName") or t.get("name") or "").strip(),
                "price": str(t.get("price", "0")),
                "quantity": int(t.get("quantity") or 1),
                "billTypeNo": item_btn,
                "nabh_code": item_nabh,
                "test_id": t_id_final,
                "status": "Result Pending"
            })

        total_float = float(total_price)
        total_int = int(total_float) if total_float.is_integer() else round(total_float, 2)

        # Financial Year & Bill Number Generation
        today = datetime.now()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        prefix_key = f"{financial_year}/{bill_type_val}"
        prefix = f"{prefix_key}/"
        counters_collection = mongo_db["counters"]
        counter = counters_collection.find_one_and_update(
            {"_id": prefix_key},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        next_number = counter["seq"]
        invest_bill_no = f"{prefix}{next_number:06d}"

        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        request_doc = {
            "uhid": uhid,
            "ipNumber": ip_number,
            "doctor": doctor_id,
            "bill_type": bill_type_val,
            "billTypeNo": bill_type_no,
            "referredBy": doctor_id,
            "discountPercent": 0,
            "discount": 0,
            "discountRemarks": "",
            "total": total_int,
            "finalPrice": total_int,
            "paymentMethod": "Credit",
            "paymentStatus": "Pending",
            "item": enriched_tests,
            "is_emergency": bool(data.get("is_emergency", False)),
            "roomNo": room_no,
            "age": age,
            "age_type": age_type,
            "investBillDate": now_ist,
            "investBillNo": invest_bill_no,
            "created_by": str(current_user),
            "branch_code": str(branch_code),
            "outlet_code": str(outlet_code),
            "hospital_code": str(hospital_code),
            "created_date": now_ist,
            "lastmodified_by": None,
            "lastmodified_date": now_ist,
            "is_active": True,
            "is_ward_request": True,
            "ward_request_type": "LAB",
            "status": "Result Pending"
        }

        collection = mongo_db["hospital_investbilling"]
        result = collection.insert_one(request_doc)

        return Response({
            "success": True,
            "message": "Lab Ward Request saved successfully",
            "data": {
                "id": str(result.inserted_id),
                "investBillNo": invest_bill_no
            }
        })
    except Exception as e:
        print("Error saving lab ward request:", e)
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

@permission_classes([HasRoleAndDataPermission])

def cancel_lab_ward_request(request):

    try:

        data = request.data

        request_id = data.get("id")

        if not request_id:

            return Response({"success": False, "error": "Request ID is required"}, status=400)

        cancel_reason = str(data.get("cancel_reason") or data.get("reason") or "").strip()

        if not cancel_reason:

            return Response({"success": False, "error": "Cancellation reason is required"}, status=400)

        from bson import ObjectId

        collection = mongo_db["hospital_investbilling"]

        cancelled_by = str(getattr(request.user, "username", None) or getattr(request.user, "user_id", None) or data.get("user") or "system")

        result = collection.update_one(

            {"_id": ObjectId(request_id), "is_ward_request": True},

            {"$set": {
                "is_active": False,
                "status": "Cancelled",
                "cancel_reason": cancel_reason,
                "cancelled_by": cancelled_by,
                "cancelled_date": datetime.now()
            }}

        )

        if result.modified_count > 0:

            return Response({"success": True, "message": "Request cancelled successfully"})

        else:

            return Response({"success": False, "error": "Request not found or already cancelled"}, status=404)

            

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def cancel_individual_ward_request_item(request):
    try:
        from bson import ObjectId
        import json
        data = request.data
        bill_id = data.get("id") or data.get("bill_id")
        test_id = data.get("test_id")
        test_name = (data.get("test_name") or data.get("name") or data.get("itemName") or "").strip()
        cancel_reason = str(data.get("cancel_reason") or data.get("reason") or "").strip()

        if not bill_id:
            return Response({"success": False, "error": "Bill ID (id) is required"}, status=400)
        if not cancel_reason:
            return Response({"success": False, "error": "Cancellation reason is required"}, status=400)
        if test_id is None and not test_name:
            return Response({"success": False, "error": "test_id or test_name is required"}, status=400)

        collection = mongo_db["hospital_investbilling"]
        doc = collection.find_one({"_id": ObjectId(bill_id)})
        if not doc:
            return Response({"success": False, "error": "Invest billing request not found"}, status=404)

        raw_items = doc.get("item", [])
        if isinstance(raw_items, str):
            try:
                items = json.loads(raw_items)
            except Exception:
                items = []
        elif isinstance(raw_items, list):
            items = list(raw_items)
        else:
            items = []

        matched_idx = -1
        t_id_str = str(test_id).strip() if test_id is not None else ""
        for idx, itm in enumerate(items):
            if not isinstance(itm, dict):
                continue
            curr_id = str(itm.get("test_id") or itm.get("item_id") or "").strip()
            curr_name = str(itm.get("itemName") or itm.get("name") or "").strip()
            if t_id_str and curr_id == t_id_str:
                matched_idx = idx
                break
            if test_name and curr_name.lower() == test_name.lower():
                matched_idx = idx
                break

        if matched_idx == -1:
            return Response({"success": False, "error": "Test item not found in this request"}, status=404)

        target_item = items[matched_idx]
        if target_item.get("status") == "Cancelled" or target_item.get("cancelled"):
            return Response({"success": False, "error": "This test is already cancelled"}, status=400)

        current_user = str(getattr(request.user, "username", None) or getattr(request.user, "user_id", None) or data.get("user") or data.get("auth-user-id") or "system")
        now_dt = datetime.now()

        # Update item
        target_item["status"] = "Cancelled"
        target_item["cancelled"] = True
        target_item["cancel_reason"] = cancel_reason
        target_item["cancelled_by"] = current_user
        target_item["cancelled_date"] = now_dt
        target_item["status_updated_at"] = now_dt
        target_item["status_updated_by"] = current_user
        items[matched_idx] = target_item

        # Recalculate bill total (excluding cancelled items)
        new_total = sum(float(it.get("price", 0) or 0) * int(it.get("quantity", 1) or 1) for it in items if it.get("status") != "Cancelled")
        new_total_val = int(new_total) if float(new_total).is_integer() else round(float(new_total), 2)

        # Rollup parent bill status
        new_bill_status = compute_investbill_rollup_status(items)
        is_active_val = False if new_bill_status == "Cancelled" else doc.get("is_active", True)

        collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "item": items,
                "total": new_total_val,
                "finalPrice": new_total_val,
                "total_amount": new_total_val,
                "status": new_bill_status,
                "is_active": is_active_val,
                "lastmodified_by": current_user,
                "lastmodified_date": now_dt
            }}
        )

        return Response({
            "success": True,
            "message": f"Test '{target_item.get('itemName') or test_name}' cancelled successfully",
            "bill_status": new_bill_status,
            "total": new_total_val,
            "item": target_item
        })
    except Exception as e:
        print(f"Error in cancel_individual_ward_request_item: {e}\n{traceback.format_exc()}")
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def update_ward_request_item_status(request):
    try:
        from bson import ObjectId
        import json
        data = request.data
        bill_id = data.get("id") or data.get("bill_id")
        test_id = data.get("test_id")
        test_name = (data.get("test_name") or data.get("name") or data.get("itemName") or "").strip()
        new_status = str(data.get("status") or "").strip()

        if not bill_id:
            return Response({"success": False, "error": "Bill ID (id) is required"}, status=400)
        if not new_status:
            return Response({"success": False, "error": "Status is required"}, status=400)

        collection = mongo_db["hospital_investbilling"]
        doc = collection.find_one({"_id": ObjectId(bill_id)})
        if not doc:
            return Response({"success": False, "error": "Invest billing request not found"}, status=404)

        raw_items = doc.get("item", [])
        if isinstance(raw_items, str):
            try:
                items = json.loads(raw_items)
            except Exception:
                items = []
        elif isinstance(raw_items, list):
            items = list(raw_items)
        else:
            items = []

        matched_idx = -1
        t_id_str = str(test_id).strip() if test_id is not None else ""
        for idx, itm in enumerate(items):
            if not isinstance(itm, dict):
                continue
            curr_id = str(itm.get("test_id") or itm.get("item_id") or "").strip()
            curr_name = str(itm.get("itemName") or itm.get("name") or "").strip()
            if t_id_str and curr_id == t_id_str:
                matched_idx = idx
                break
            if test_name and curr_name.lower() == test_name.lower():
                matched_idx = idx
                break

        if matched_idx == -1:
            return Response({"success": False, "error": "Test item not found in this request"}, status=404)

        current_user = str(getattr(request.user, "username", None) or getattr(request.user, "user_id", None) or data.get("user") or data.get("auth-user-id") or "system")
        now_dt = datetime.now()

        target_item = items[matched_idx]
        target_item["status"] = new_status
        for k in ["cancelled", "cancel_reason", "cancelled_by", "cancelled_date", "status_updated_at", "status_updated_by"]:
            target_item.pop(k, None)

        items[matched_idx] = target_item

        new_total = sum(float(it.get("price", 0) or 0) * int(it.get("quantity", 1) or 1) for it in items if it.get("status") != "Cancelled")
        new_total_val = int(new_total) if float(new_total).is_integer() else round(float(new_total), 2)
        new_bill_status = compute_investbill_rollup_status(items)
        is_active_val = False if new_bill_status == "Cancelled" else doc.get("is_active", True)

        collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "item": items,
                "total": new_total_val,
                "finalPrice": new_total_val,
                "total_amount": new_total_val,
                "status": new_bill_status,
                "is_active": is_active_val,
                "lastmodified_by": current_user,
                "lastmodified_date": now_dt
            }}
        )

        return Response({
            "success": True,
            "message": f"Test status updated to '{new_status}'",
            "bill_status": new_bill_status,
            "item": target_item
        })
    except Exception as e:
        print(f"Error in update_ward_request_item_status: {e}\n{traceback.format_exc()}")
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def remove_individual_test_from_lab_ward_request(request):
    """
    Physically removes an individual test from a Lab Ward Request bill BEFORE status is changed.
    Only allowed when status is 'Result Pending' or 'Pending'.
    """
    try:
        import json
        from decimal import Decimal
        from bson import ObjectId, Decimal128

        data = request.data
        request_id = data.get("id") or data.get("bill_id")
        test_id = data.get("test_id")
        test_name = (data.get("test_name") or data.get("name") or data.get("itemName") or "").strip()

        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
        if test_id is None and not test_name:
            return Response({"success": False, "error": "test_id or test_name is required"}, status=400)

        collection = mongo_db["hospital_investbilling"]
        doc = collection.find_one({"_id": ObjectId(request_id), "is_ward_request": True})
        if not doc:
            return Response({"success": False, "error": "Request not found"}, status=404)

        # Parse items
        item_data = doc.get("item", "[]")
        items = json.loads(item_data) if isinstance(item_data, str) else list(item_data or [])

        # Step: Guard status & remove item
        new_items = []
        found = False
        for itm in items:
            is_match = False
            if test_id and str(itm.get("test_id")) == str(test_id):
                is_match = True
            elif not test_id and test_name and (itm.get("itemName") == test_name or itm.get("test_name") == test_name):
                is_match = True

            if is_match and not found:
                item_status = itm.get("status") or doc.get("status") or "Result Pending"
                if item_status not in ["Result Pending", "Pending", ""]:
                    return Response({
                        "success": False,
                        "error": f"Cannot remove test. Status has already been updated to '{item_status}'."
                    }, status=400)
                found = True
                continue  # Physically remove this test

            new_items.append(itm)

        if not found:
            return Response({"success": False, "error": "Test item not found in this request"}, status=404)

        # Recalculate bill total
        new_total = sum(float(t.get("price", 0)) for t in new_items)
        dec_total = Decimal128(Decimal(str(new_total)))
        update_fields = {
            "item": new_items,
            "total": dec_total,
            "finalPrice": dec_total,
            "total_amount": new_total,
            "last_modified_date": timezone.now()
        }

        if len(new_items) == 0:
            update_fields["is_active"] = False
            update_fields["status"] = "Cancelled"

        collection.update_one({"_id": ObjectId(request_id)}, {"$set": update_fields})
        return Response({"success": True, "message": "Test removed successfully", "remaining_count": len(new_items)})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def get_medicine_ward_requests(request):

    try:

        uhid = request.query_params.get("uhid")

        ip_number = request.query_params.get("ipNumber")

        outlet_code = request.query_params.get("outlet_code")

        if not uhid:

            return Response({"success": False, "error": "UHID is required"}, status=400)

        # Build query
        query_params = {"uhid": uhid, "is_ward_request": True}

        if ip_number and str(ip_number).strip() not in ["-", "null", "undefined", ""]:
            clean_ip = str(ip_number).strip()
            query_params["$or"] = [
                {"inpatient_number": clean_ip},
                {"ipNumber": clean_ip},
            ]

        if outlet_code:
            query_params["outlet_code"] = outlet_code

        # Fetch billing records using PyMongo for maximum speed & compound index support

        raw_cursor = mongo_db["hospital_pharmacybilling"].find(query_params).sort("bill_date", -1)

        requests_data = [serialize_doc(d) for d in raw_cursor]

        # --- Batch-load item names ---

        all_item_ids = set()

        all_bill_types = set()

        for doc in requests_data:

            bt_val = doc.get("bill_type")

            if bt_val is not None:

                try:

                    all_bill_types.add(int(bt_val))

                except (ValueError, TypeError):

                    all_bill_types.add(str(bt_val))

            for itm in (doc.get("medicine_particulars") or []):

                if isinstance(itm, dict) and itm.get("item_id"):

                    try:

                        all_item_ids.add(int(itm["item_id"]))

                    except (ValueError, TypeError):

                        pass

        item_name_map = {}

        if all_item_ids:

            for itm in mongo_db["hospital_pharmacyitem"].find(

                {"item_id": {"$in": list(all_item_ids)}},

                {"item_id": 1, "item_name": 1, "_id": 0}

            ):

                item_name_map[itm.get("item_id")] = itm.get("item_name", "")

        bill_name_map = {}

        if all_bill_types:

            for bt in mongo_db["hospital_billtype"].find(

                {"bill_type": {"$in": list(all_bill_types)}},

                {"bill_type": 1, "bill_name": 1, "_id": 0}

            ):

                bill_name_map[bt.get("bill_type")] = bt.get("bill_name", "")

                bill_name_map[str(bt.get("bill_type"))] = bt.get("bill_name", "")

        # Build doctor mapping (employeeId -> employeeName)
        doc_map = {}
        try:
            from pymongo import MongoClient
            import os
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
            for d in g_client["Global"]["backend_diagnostics_profile"].find({}, {"employeeId": 1, "employeeName": 1}):
                if d.get("employeeId") and d.get("employeeName"):
                    doc_map[str(d["employeeId"]).strip()] = str(d["employeeName"]).strip()
        except Exception:
            pass

        formatted_data = []

        for doc in requests_data:

            import json

            raw_st = str(doc.get("billing_status") or doc.get("status") or "Pending").strip()
            if doc.get("is_dispatched") and raw_st in ["Pending", "Processing", "Draft", ""]:
                raw_st = "Billed"
            elif raw_st in ["Completed", "Paid"]:
                raw_st = "Billed"

            items = doc.get("medicine_particulars", [])

            if isinstance(items, str):

                try:

                    items = json.loads(items)

                except Exception:

                    items = []

            medicines = []

            for itm in (items or []):

                if isinstance(itm, str):

                    try:

                        itm = json.loads(itm)

                    except Exception:

                        continue

                if not isinstance(itm, dict):

                    continue

                try:

                    item_id_int = int(itm.get("item_id", 0))

                except (ValueError, TypeError):

                    item_id_int = 0

                medicines.append({

                    "item_id": itm.get("item_id", ""),

                    "item_name": item_name_map.get(item_id_int, itm.get("item_name", itm.get("itemName", ""))),

                    "name": item_name_map.get(item_id_int, itm.get("item_name", itm.get("itemName", ""))),

                    "batch_number": itm.get("batch_number", ""),

                    "quantity": itm.get("quantity", itm.get("qty", 0)),

                    "dosage": itm.get("dosage", ""),

                    "noOfDays": itm.get("noOfDays", ""),

                    "dose": itm.get("dose", ""),

                    "doseunit": itm.get("doseunit", ""),

                    "route": itm.get("route", ""),

                    "price": itm.get("price", itm.get("mrp", 0)),

                    "instruction": itm.get("instruction", ""),

                    "is_deleted": itm.get("is_deleted", False),

                    "edit_history": itm.get("edit_history", []),

                    "status": itm.get("status") or raw_st,

                })

            _raw_dt = doc.get("ward_request_date") or doc.get("bill_date") or doc.get("created_date")

            _req_date = ""

            _req_time = ""

            if _raw_dt:

                _dt_obj = None

                if isinstance(_raw_dt, str):

                    try:

                        _dt_obj = datetime.fromisoformat(_raw_dt.replace("Z", "+00:00"))

                    except Exception:

                        _req_date = _raw_dt[:10] if len(_raw_dt) >= 10 else _raw_dt

                elif hasattr(_raw_dt, "astimezone") or isinstance(_raw_dt, datetime):

                    _dt_obj = _raw_dt

                if _dt_obj:

                    try:

                        if not _dt_obj.tzinfo:

                            _dt_obj = pytz.UTC.localize(_dt_obj)

                        kolkata_tz = pytz.timezone("Asia/Kolkata")

                        _dt_ist = _dt_obj.astimezone(kolkata_tz)

                        _req_date = _dt_ist.strftime("%d-%m-%Y")

                        _req_time = _dt_ist.strftime("%I:%M %p")

                    except Exception:

                        _req_date = str(_raw_dt)[:10]

            raw_doc_id = doc.get("doctor_id") or doc.get("doctor") or ""

            resolved_doctor_name = get_doctor_name_by_id(raw_doc_id) or str(raw_doc_id)

            raw_bt = doc.get("bill_type")

            resolved_bill_name = bill_name_map.get(raw_bt) or bill_name_map.get(str(raw_bt)) or doc.get("bill_type_no") or ""

            formatted_data.append({

                "id": str(doc.get("_id")),

                "Bill_id": doc.get("Bill_id"),

                "bill_no": doc.get("bill_no", "") or str(doc.get("Bill_id") or ""),

                "reqId": str(doc.get("Bill_id") or doc.get("_id")),

                "uhid": doc.get("uhid", ""),

                "ipNumber": doc.get("inpatient_number", ""),

                "billType": doc.get("bill_type", ""),

                "billTypeNo": doc.get("bill_type_no", ""),

                "billName": resolved_bill_name,

                "reqDate": _req_date,

                "reqTime": _req_time,

                "status": raw_st,

                "doctor": resolved_doctor_name,

                "doctorId": str(raw_doc_id),

                "doctorName": resolved_doctor_name,

                "outlet_code": doc.get("outlet_code", ""),

                "isDischarge": doc.get("billing_mode") == "DISCHARGE MEDICINE",

                "medicines": medicines,

                "total_amount": doc.get("total_amount", 0),

                "pending_returns": doc.get("pending_returns", []),

            })

        return Response({"success": True, "data": formatted_data})

    except Exception as e:

        import traceback

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["PATCH"])

@permission_classes([HasRoleAndDataPermission])

def update_medicine_ward_request(request):

    """

    Patch individual medicines inside an existing ward request.

    Supports:

      - Soft-deleting a medicine (is_deleted: true)

      - Changing qty / dosage with an audit trail in edit_history

    """

    import traceback

    try:

        data = request.data

        bill_id = data.get("Bill_id") or data.get("id") or data.get("reqId")

        updated_medicines = data.get("medicine_particulars", [])

        changed_by = data.get("auth-user-id", "system")

        if not bill_id:

            return Response({"success": False, "error": "Bill_id is required"}, status=400)

        bill = None

        try:

            if str(bill_id).isdigit():

                bill = PharmacyBilling.objects.filter(Bill_id=int(bill_id)).first()

            if not bill:

                bill = PharmacyBilling.objects.filter(Bill_id=str(bill_id)).first()

        except Exception:

            bill = None

        if not bill:

            from bson import ObjectId

            queries = []

            if str(bill_id).isdigit():

                queries.append({"Bill_id": int(bill_id)})

                queries.append({"Bill_id": str(bill_id)})

            if ObjectId.is_valid(str(bill_id)):

                queries.append({"_id": ObjectId(bill_id)})

            queries.append({"bill_no": str(bill_id)})

            query = {"$or": queries} if len(queries) > 1 else queries[0]

            doc = mongo_db["hospital_pharmacybilling"].find_one(query)

            if doc and doc.get("Bill_id") is not None:

                try:

                    bill = PharmacyBilling.objects.filter(Bill_id=doc.get("Bill_id")).first()

                except Exception:

                    pass

        if not bill:

            return Response({"success": False, "error": "Ward request not found"}, status=404)

        if bill.billing_status in ["Billed", "Cancelled"]:

            return Response(

                {"success": False, "error": f"Cannot edit a {bill.billing_status} request"},

                status=400,

            )

        existing = list(bill.medicine_particulars or [])

        # Build a lookup map keyed by (item_id, batch_number)

        existing_map = {}

        for idx, itm in enumerate(existing):

            if not isinstance(itm, dict):

                continue

            key = (str(itm.get("item_id", "")), str(itm.get("batch_number", "")))

            existing_map[key] = (idx, itm)

        changed_at = timezone.now().isoformat()

        for incoming in updated_medicines:

            if not isinstance(incoming, dict):

                continue

            key = (str(incoming.get("item_id", "")), str(incoming.get("batch_number", "")))

            if key not in existing_map:

                continue

            idx, current = existing_map[key]

            audit_entry = {}

            # --- Handle soft delete ---

            if incoming.get("is_deleted") and not current.get("is_deleted"):

                current["is_deleted"] = True

                audit_entry = {

                    "changed_by": changed_by,

                    "changed_at": changed_at,

                    "action": "deleted",

                }

            else:

                # --- Handle qty change ---

                old_qty = current.get("quantity", current.get("qty", 0))

                new_qty = incoming.get("quantity", old_qty)

                # --- Handle dosage change ---

                old_dosage = current.get("dosage", "")

                new_dosage = incoming.get("dosage", old_dosage)

                qty_changed = str(old_qty) != str(new_qty)

                dosage_changed = old_dosage != new_dosage

                if qty_changed or dosage_changed:

                    audit_entry = {

                        "changed_by": changed_by,

                        "changed_at": changed_at,

                        "action": "edited",

                    }

                    if qty_changed:

                        audit_entry["old_qty"] = old_qty

                        audit_entry["new_qty"] = new_qty

                        current["quantity"] = new_qty

                    if dosage_changed:

                        audit_entry["old_dosage"] = old_dosage

                        audit_entry["new_dosage"] = new_dosage

                        current["dosage"] = new_dosage

            if audit_entry:

                eh = current.get("edit_history", [])

                if not isinstance(eh, list):

                    eh = []

                eh.append(audit_entry)

                current["edit_history"] = eh

            existing[idx] = current

        bill.medicine_particulars = existing

        # Recalculate totals from non-deleted items

        new_total = sum(

            float(itm.get("quantity", itm.get("qty", 0))) * float(itm.get("price", 0))

            for itm in existing

            if isinstance(itm, dict) and not itm.get("is_deleted")

        )

        bill.total_amount = round(new_total, 2)

        bill.net_amount = round(new_total, 2)

        bill.lastmodified_by = changed_by

        bill.save()

        return Response({"success": True, "message": "Ward request updated successfully"})

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

@permission_classes([HasRoleAndDataPermission])

def save_medicine_ward_request(request):

    try:

        data = request.data

        print(data)

        current_user = data.get('auth-user-id', "system")

        branch_code = data.get('auth-branch-code', 'system')

        hospital_code = data.get('auth-hospital-code', 'system')

        outlet_code = data.get('outlet_code', 'system')

        

        medicine_particulars = data.get("medicine_particulars", [])

        total_amount = round(float(data.get("total_amount") or 0), 2)

        

        # --- Doctor & Patient Settings ---

        doctor_id = str(data.get("doctor_id") or data.get("doctorId") or data.get("doctor") or "").strip()
        if doctor_id and not doctor_id.isdigit():
            try:
                g_client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
                doc_profile = g_client["Global"]["backend_diagnostics_profile"].find_one({
                    "$or": [{"employeeName": doctor_id}, {"employeeId": doctor_id}]
                })
                if doc_profile and doc_profile.get("employeeId"):
                    doctor_id = str(doc_profile.get("employeeId")).strip()
            except Exception as e:
                print("Doctor lookup error in save_medicine_ward_request:", e)

        # Resolve Room No
        raw_r = str(data.get("roomNo") or data.get("room_no") or "").strip()
        if raw_r in ["", "-", "None", "null"]:
            raw_r = str(data.get("wardName") or data.get("ward_name") or "").strip()
        if raw_r in ["-", "None", "null"]:
            raw_r = ""
        room_no = raw_r

        patient_name = data.get("patient_name", "").strip()

        if not patient_name:

            # Fallback to Admission via PyMongo

            admission = mongo_db["hospital_admission"].find_one({"uhid": data.get("uhid"), "is_admitted": True, "is_cancelled": {"$ne": True}, "is_discharged": {"$ne": True}})

            if admission and "patient_details" in admission:

                fname = admission["patient_details"].get("firstName", "")

                lname = admission["patient_details"].get("lastName", "")

                patient_name = f"{fname} {lname}".strip()

        # Strip item names from particulars before saving as per user request

        cleaned_particulars = []

        for item in (medicine_particulars or []):

            cleaned_item = {

                "item_id": item.get("item_id"),

                "qty": item.get("quantity", item.get("qty", 0)),

                "dosage": item.get("dosage", ""),

                "noOfDays": item.get("noOfDays", ""),

                "dose": item.get("dose", ""),

                "doseunit": item.get("doseunit", ""),

                "batch_number": item.get("batch_number", ""),

                "instruction": item.get("instruction", "")

            }

            cleaned_particulars.append(cleaned_item)

        # Create Bill via Django Model (Handles auto-increment and defaults)

        bill = PharmacyBilling(

            uhid=data.get("uhid"),

            inpatient_number=data.get("ipNumber"),

            bill_type=data.get("bill_type"),

            # bill_type_no=data.get("billTypeNo"),

            doctor_id=doctor_id,

            medicine_particulars=cleaned_particulars,

            total_amount=total_amount,

            net_amount=total_amount,

            billing_status="Pending",

            billing_mode="DISCHARGE MEDICINE" if data.get("is_discharge") else "WARD REQUEST",

            payment_details={},

            outlet_code=outlet_code,

            hospital_code=hospital_code,

            branch_code=branch_code,

            created_by=current_user,

            is_ward_request=True,

            room_no=room_no,

            ward_request_date=timezone.now() if 'timezone' in globals() else datetime.now()

        )

        bill.save()

        

        return Response({

            "success": True,

            "message": "Medicine ward request saved successfully",

            "id": bill.Bill_id

        })

        

    except Exception as e:

        import traceback

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET", "POST"])

# @permission_classes([HasRoleAndDataPermission])

def dosage_master_view(request):

    dosage_col = mongo_db["hospital_dosage"]

    try:

        if request.method == "GET":

            dosages = list(dosage_col.find({}, {"_id": 0}))

            return Response({"success": True, "data": dosages})

            

        elif request.method == "POST":

            data = request.data

            dosage_name = data.get("dosage_name")

            if not dosage_name:

                return Response({"success": False, "message": "Dosage name is required"}, status=400)

            

            # Simple check/upsert

            dosage_col.update_one(

                {"dosage_name": dosage_name},

                {"$set": {"dosage_name": dosage_name, "created_at": datetime.now()}},

                upsert=True

            )

            return Response({"success": True, "message": "Dosage saved successfully"})

    except Exception as e:

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

# @permission_classes([HasRoleAndDataPermission])

def cancel_medicine_ward_request(request):

    try:

        from bson import ObjectId

        data = request.data

        request_id = data.get("id") or data.get("Bill_id") or data.get("reqId")

        if not request_id:

            return Response({"success": False, "error": "Request ID is required"}, status=400)

        cancel_reason = str(data.get("cancel_reason") or data.get("reason") or "").strip()

        if not cancel_reason:

            return Response({"success": False, "error": "Cancellation reason is required"}, status=400)

        cancelled_by = str(getattr(request.user, "username", None) or getattr(request.user, "user_id", None) or data.get("user") or "system")

        queries = []

        if str(request_id).isdigit():

            queries.append({"Bill_id": int(request_id)})

            queries.append({"Bill_id": str(request_id)})

        if ObjectId.is_valid(str(request_id)):

            queries.append({"_id": ObjectId(request_id)})

        queries.append({"bill_no": str(request_id)})

        queries.append({"_id": str(request_id)})

        query = {"$or": queries} if len(queries) > 1 else queries[0]

        update_payload = {
            "billing_status": "Cancelled",
            "is_deleted": True,
            "cancel_reason": cancel_reason,
            "cancelled_by": cancelled_by,
            "cancelled_date": datetime.now(),
            "lastmodified_date": datetime.now()
        }

        # Primary collection: hospital_pharmacybilling

        collection = mongo_db["hospital_pharmacybilling"]

        result = collection.update_one(

            query,

            {"$set": update_payload}

        )

        # Fallback collection if not found in primary

        if result.matched_count == 0:

            collection2 = mongo_db["hospital_oppharmacybill"]

            result = collection2.update_one(

                query,

                {"$set": update_payload}

            )

        if result.matched_count > 0:

            return Response({"success": True, "message": "Medicine ward request cancelled successfully"})

        else:

            return Response({"success": False, "error": "Request not found"}, status=404)

            

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

# @permission_classes([HasRoleAndDataPermission])

def remove_individual_medicine_from_ward_request(request):

    try:

        from bson import ObjectId

        data = request.data

        request_id = data.get("id") or data.get("Bill_id") or data.get("reqId")

        item_id = data.get("item_id")

        item_name = data.get("item_name")

        batch_number = data.get("batch_number")

        

        if not request_id:

            return Response({"success": False, "error": "Request ID is required"}, status=400)

            

        queries = []

        if str(request_id).isdigit():

            queries.append({"Bill_id": int(request_id)})

            queries.append({"Bill_id": str(request_id)})

        if ObjectId.is_valid(str(request_id)):

            queries.append({"_id": ObjectId(request_id)})

        queries.append({"bill_no": str(request_id)})

        queries.append({"_id": str(request_id)})

        query = {"$or": queries} if len(queries) > 1 else queries[0]

        collection = mongo_db["hospital_pharmacybilling"]

        doc = collection.find_one(query)

        if not doc:

            collection = mongo_db["hospital_oppharmacybill"]

            doc = collection.find_one(query)

            

        if not doc:

            return Response({"success": False, "error": "Request not found"}, status=404)

            

        items = doc.get("medicine_particulars", [])

        if isinstance(items, str):

            import json

            try:

                items = json.loads(items)

            except Exception:

                items = []

        new_items = []

        found = False

        for itm in items:

            if not isinstance(itm, dict):

                continue

            match_id = item_id and str(itm.get("item_id", "")) == str(item_id)

            match_batch = not batch_number or str(itm.get("batch_number", "")) == str(batch_number)

            if match_id and match_batch and not found:

                found = True

                continue

            if not item_id and itm.get("itemName", itm.get("item_name", "")) == item_name and not found:

                found = True

                continue

            new_items.append(itm)

            

        if found:

            new_total = round(sum(

                float(t.get("price", t.get("Price", t.get("mrp", 0)))) * float(t.get("quantity", t.get("qty", 1)))

                for t in new_items if not t.get("is_deleted")

            ), 2)

            

            update_data = {

                "medicine_particulars": new_items,

                "total_amount": new_total,

                "net_amount": new_total,

                "lastmodified_date": datetime.now()

            }

            if len([t for t in new_items if not t.get("is_deleted")]) == 0:

                update_data["billing_status"] = "Cancelled"

                update_data["is_deleted"] = True

            collection.update_one({"_id": doc["_id"]}, {"$set": update_data})

            

            return Response({

                "success": True, 

                "message": "Medicine removed successfully",

                "remaining_medicines": len(new_items)

            })

        else:

            return Response({"success": False, "error": "Medicine not found in request"}, status=404)

            

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])

# @permission_classes([HasRoleAndDataPermission])

def get_radiology_ward_requests(request):

    try:

        params = getattr(request, "query_params", None) if hasattr(request, "query_params") else getattr(request, "GET", {})
        uhid = params.get("uhid")
        ip_number = params.get("ipNumber") or params.get("ip_number")

        if not uhid and not ip_number:
            return Response({"success": False, "error": "UHID or ipNumber is required"}, status=400)

        collection = mongo_db["hospital_investbilling"]

        query = {
            "is_active": True,
            "is_ward_request": True,
            "ward_request_type": "RADIOLOGY"
        }

        if uhid:
            query["uhid"] = uhid

        if ip_number:
            query["ipNumber"] = ip_number

        requests_data = list(collection.find(query).sort("created_date", -1))

        # Build doctor mapping (employeeId -> employeeName)
        doc_map = {}
        try:
            from pymongo import MongoClient
            import os
            g_client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
            for d in g_client["Global"]["backend_diagnostics_profile"].find({}, {"employeeId": 1, "employeeName": 1}):
                if d.get("employeeId") and d.get("employeeName"):
                    doc_map[str(d["employeeId"]).strip()] = str(d["employeeName"]).strip()
        except Exception:
            pass

        formatted_data = []

        for doc in requests_data:

            import json

            # Parse 'item' field back to list

            item_data = doc.get("item", "[]")

            if isinstance(item_data, str):

                try:

                    items = json.loads(item_data)

                except json.JSONDecodeError:

                    items = []

            else:

                items = item_data

            tests = []

            for itm in items:
                it_st = itm.get("status") or doc.get("status") or "Result Pending"
                if it_st == "Cancelled":
                    continue

                tests.append({
                    "test_id": itm.get("test_id", ""),
                    "name": itm.get("itemName", ""),
                    "billTypeNo": itm.get("billTypeNo", ""),
                    "nabh_code": itm.get("nabh_code", ""),
                    "price": itm.get("price", 0),
                    "quantity": itm.get("quantity", 1),
                    "status": it_st
                })
            
            formatted_doc = {
                "id": str(doc.get("_id")),
                "status": doc.get("status", "Result Pending"),
                "cancelReason": doc.get("cancel_reason", ""),
                "reqDate": doc.get("created_date").strftime("%d/%m/%Y") if doc.get("created_date") else "",
                "reqTime": doc.get("created_date").strftime("%I:%M %p") if doc.get("created_date") else "",
                "userName": doc.get("created_by", ""),
                "billNo": doc.get("investBillNo", ""),
                "billType": (items[0].get("billTypeNo") if items and isinstance(items[0], dict) else "") or doc.get("billTypeName", "") or doc.get("billTypeNo", "") or str(doc.get("bill_type", "")),
                "billTypeNo": doc.get("billTypeNo", ""),
                

                "billType": doc.get("billTypeName", ""),

                "wardName": doc.get("wardName", ""),

                "doctorName": doc_map.get(str(doc.get("doctor") or "").strip(), doc.get("doctorName") or doc.get("doctor", "")),
                "doctor": str(doc.get("doctor") or "").strip(),

                "tests": tests,

                "total_amount": doc.get("total_amount", 0)

            }

            formatted_data.append(formatted_doc)

        return Response({

            "success": True,

            "data": serialize_doc(formatted_data)

        })

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

@permission_classes([HasRoleAndDataPermission])

def save_radiology_ward_request(request):
    try:
        import json
        from pymongo import ReturnDocument
        data = request.data

        current_user = data.get("auth-user-id", "system")
        branch_code = data.get("auth-branch-code", "system")
        outlet_code = (
            request.data.get("auth-outlet-code") or
            request.headers.get("Outlet-Code") or "system"
        )
        hospital_code = data.get("auth-hospital-code", "system")

        uhid = str(data.get("uhid") or "").strip()
        ip_number = str(data.get("ipNumber") or data.get("ip_number") or "").strip()

        # Lookup Admission & Patient
        adm_doc = None
        if ip_number:
            adm_doc = mongo_db["hospital_admission"].find_one({"ipNumber": ip_number, "is_admitted": True, "is_cancelled": {"$ne": True}})
            if not adm_doc:
                adm_doc = mongo_db["hospital_admission"].find_one({"ipNumber": ip_number})
        if not adm_doc and uhid:
            adm_doc = mongo_db["hospital_admission"].find_one({"uhid": uhid, "is_admitted": True, "is_cancelled": {"$ne": True}})
            if not adm_doc:
                adm_doc = mongo_db["hospital_admission"].find_one({"uhid": uhid})

        pt_doc = None
        if uhid:
            pt_doc = mongo_db["hospital_patient"].find_one({"uhid": uhid})

        # Resolve Doctor ID (employeeId)
        raw_doctor = data.get("doctor") or ""
        doctor_id = str(raw_doctor).strip()
        if doctor_id:
            try:
                from pymongo import MongoClient
                import os
                g_client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
                doc_profile = g_client["Global"]["backend_diagnostics_profile"].find_one({
                    "$or": [{"employeeName": doctor_id}, {"employeeId": doctor_id}]
                })
                if doc_profile and doc_profile.get("employeeId"):
                    doctor_id = str(doc_profile.get("employeeId")).strip()
            except Exception as e:
                print("Doctor lookup error in save_radiology_ward_request:", e)

        # Resolve Room No
        raw_r = str(data.get("roomNo") or data.get("room_no") or "").strip()
        if raw_r in ["", "-", "None", "null"]:
            raw_r = str(data.get("wardName") or data.get("ward_name") or "").strip()
        if raw_r in ["-", "None", "null"]:
            raw_r = ""
        room_no = raw_r

        if not room_no and adm_doc:
            for field in ["roomShiftingDetails", "roomShitingDetails", "room_details"]:
                shifting = adm_doc.get(field, [])
                if shifting and isinstance(shifting, list):
                    active_shift = next((s for s in shifting if s.get("is_roomActive")), None)
                    if not active_shift and shifting:
                        active_shift = shifting[-1]
                    if active_shift and isinstance(active_shift, dict):
                        found_room = active_shift.get("newRoomNo") or active_shift.get("roomNo") or active_shift.get("roomNumber") or active_shift.get("room_number")
                        if found_room:
                            room_no = str(found_room).strip()
                            break
            if not room_no:
                room_no = str(adm_doc.get("roomNo") or adm_doc.get("room_no") or adm_doc.get("ward_name") or adm_doc.get("wardName") or "").strip()
        if room_no in ["-", "None", "null"]:
            room_no = ""

        # Resolve Age & Age Type
        age = str(data.get("age") or "").strip()
        age_type = str(data.get("age_type") or "Y").strip()
        if not age:
            if pt_doc and pt_doc.get("age"):
                age = str(pt_doc.get("age"))
                age_type = str(pt_doc.get("age_type") or "Y")
            elif adm_doc and adm_doc.get("age"):
                age = str(adm_doc.get("age"))
                age_type = str(adm_doc.get("age_type") or "Y")

        # Resolve bill_type (int) and billTypeNo (str)
        raw_bt = data.get("bill_type")
        bill_type_no = str(data.get("billTypeNo") or "CT01").strip()
        try:
            bill_type_val = int(raw_bt) if raw_bt is not None else 85
        except (ValueError, TypeError):
            bill_type_val = raw_bt or 85

        # Robust Item Fetching
        raw_tests = data.get("item") or data.get("selectedTests") or data.get("items") or []
        if isinstance(raw_tests, str):
            try:
                raw_tests = json.loads(raw_tests)
            except Exception:
                raw_tests = []
        if not isinstance(raw_tests, list):
            raw_tests = []

        enriched_tests = []
        total_price = 0
        for t in raw_tests:
            if not isinstance(t, dict):
                continue
            item_btn = str(t.get("billTypeNo") or bill_type_no or "CT01").strip()
            t_id_raw = str(t.get("test_id") or t.get("item_id") or "").strip()
            item_nabh = str(t.get("nabh_code") or "").strip()

            p_val = float(t.get("price", 0) or 0)
            total_price += p_val

            t_id_final = int(t_id_raw) if t_id_raw.isdigit() else (t.get("test_id") or t.get("item_id") or "")
            enriched_tests.append({
                "itemName": str(t.get("itemName") or t.get("name") or "").strip(),
                "price": str(t.get("price", "0")),
                "quantity": int(t.get("quantity") or 1),
                "billTypeNo": item_btn,
                "nabh_code": item_nabh,
                "test_id": t_id_final,
                "status": "Result Pending"
            })

        total_float = float(total_price)
        total_int = int(total_float) if total_float.is_integer() else round(total_float, 2)

        # Financial Year & Bill Number Generation
        today = datetime.now()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        prefix_key = f"{financial_year}/{bill_type_val}"
        prefix = f"{prefix_key}/"
        counters_collection = mongo_db["counters"]
        counter = counters_collection.find_one_and_update(
            {"_id": prefix_key},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        next_number = counter["seq"]
        invest_bill_no = f"{prefix}{next_number:06d}"

        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        request_doc = {
            "uhid": uhid,
            "ipNumber": ip_number,
            "doctor": doctor_id,
            "bill_type": bill_type_val,
            "billTypeNo": bill_type_no,
            "referredBy": doctor_id,
            "discountPercent": 0,
            "discount": 0,
            "discountRemarks": "",
            "total": total_int,
            "finalPrice": total_int,
            "paymentMethod": "Credit",
            "paymentStatus": "Pending",
            "item": enriched_tests,
            "is_emergency": bool(data.get("is_emergency", False)),
            "roomNo": room_no,
            "age": age,
            "age_type": age_type,
            "investBillDate": now_ist,
            "investBillNo": invest_bill_no,
            "created_by": str(current_user),
            "branch_code": str(branch_code),
            "outlet_code": str(outlet_code),
            "hospital_code": str(hospital_code),
            "created_date": now_ist,
            "lastmodified_by": None,
            "lastmodified_date": now_ist,
            "is_active": True,
            # Extra ward request fields
            "is_ward_request": True,
            "ward_request_type": "RADIOLOGY",
            "status": "Result Pending"
        }

        collection = mongo_db["hospital_investbilling"]
        result = collection.insert_one(request_doc)

        return Response({
            "success": True,
            "message": "Radiology Ward Request saved successfully",
            "data": {
                "id": str(result.inserted_id),
                "investBillNo": invest_bill_no
            }
        })
    except Exception as e:
        print("Error saving radiology ward request:", e)
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

# @permission_classes([HasRoleAndDataPermission])

def cancel_radiology_ward_request(request):

    try:

        data = request.data

        request_id = data.get("id")

        if not request_id:

            return Response({"success": False, "error": "Request ID is required"}, status=400)

        cancel_reason = str(data.get("cancel_reason") or data.get("reason") or "").strip()

        if not cancel_reason:

            return Response({"success": False, "error": "Cancellation reason is required"}, status=400)

        from bson import ObjectId

        collection = mongo_db["hospital_investbilling"]

        cancelled_by = str(getattr(request.user, "username", None) or getattr(request.user, "user_id", None) or data.get("user") or "system")

        result = collection.update_one(

            {"_id": ObjectId(request_id), "is_ward_request": True, "ward_request_type": "RADIOLOGY"},

            {"$set": {
                "is_active": False,
                "status": "Cancelled",
                "cancel_reason": cancel_reason,
                "cancelled_by": cancelled_by,
                "cancelled_date": datetime.now()
            }}

        )

        if result.modified_count > 0:

            return Response({"success": True, "message": "Request cancelled successfully"})

        else:

            return Response({"success": False, "error": "Request not found"}, status=404)

            

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

# @permission_classes([HasRoleAndDataPermission])

def remove_individual_test_from_radiology_ward_request(request):

    try:

        import json
        from decimal import Decimal
        from bson import ObjectId, Decimal128

        data = request.data

        request_id = data.get("id") or data.get("bill_id")

        test_id = data.get("test_id")

        test_name = (data.get("test_name") or data.get("name") or data.get("itemName") or "").strip()

        

        if not request_id:

            return Response({"success": False, "error": "Request ID is required"}, status=400)
        if test_id is None and not test_name:
            return Response({"success": False, "error": "test_id or test_name is required"}, status=400)

            

        collection = mongo_db["hospital_investbilling"]

        

        # Step 1: Get document

        doc = collection.find_one({"_id": ObjectId(request_id), "is_ward_request": True, "ward_request_type": "RADIOLOGY"})

        if not doc:

            return Response({"success": False, "error": "Request not found"}, status=404)

            

        # Parse items

        item_data = doc.get("item", "[]")

        items = json.loads(item_data) if isinstance(item_data, str) else list(item_data or [])

            

        # Step 2: Guard status & Remove test

        new_items = []

        found = False

        for itm in items:
            is_match = False
            if test_id and str(itm.get("test_id")) == str(test_id):
                is_match = True
            elif not test_id and test_name and (itm.get("itemName") == test_name or itm.get("test_name") == test_name):
                is_match = True

            if is_match and not found:
                item_status = itm.get("status") or doc.get("status") or "Result Pending"
                if item_status not in ["Result Pending", "Pending", ""]:
                    return Response({
                        "success": False,
                        "error": f"Cannot remove test. Status has already been updated to '{item_status}'."
                    }, status=400)
                found = True
                continue  # Physically remove this test

            new_items.append(itm)

            

        if found:

            # Step 3: Recalculate total amount with Decimal128

            new_total = sum(float(t.get("price", 0)) for t in new_items)
            dec_total = Decimal128(Decimal(str(new_total)))

            

            update_fields = {

                "item": new_items,

                "total": dec_total,

                "finalPrice": dec_total,

                "total_amount": new_total,

                "last_modified_date": timezone.now()

            }

            if not new_items:

                update_fields["status"] = "Cancelled"

                update_fields["is_active"] = False

                

            collection.update_one({"_id": ObjectId(request_id)}, {"$set": update_fields})

            

            return Response({"success": True, "message": "Test removed successfully", "remaining_tests": len(new_items)})

        else:

            return Response({"success": False, "error": "Test not found in request"}, status=404)

            

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)


def get_patient_billing_clearance_data(ip_number, uhid=None):
    """
    Evaluates inpatient clearance across 6 streams:
    1. Lab: hospital_investbilling (is_ward_request=True, ward_request_type='LAB', is_active=True, status in ['Result Pending', 'Pending'])
    2. Radiology: hospital_investbilling (is_ward_request=True, ward_request_type='RADIOLOGY', is_active=True, status in ['Result Pending', 'Pending'])
    3. Pharmacy: hospital_pharmacybilling (is_ward_request=True, is_deleted!=True, billing_status in ['Pending', 'Draft'] or unapproved pending_returns)
    4. Implants: hospital_implant_request (is_active=True and no paid bill in hospital_velavansalesbill)
    5. Diet: hospital_patientdietorder (status in ['Ordered', 'Received'])
    6. Laundry: hospital_laundrywardrequest (status in ['Pending'])
    """
    import json
    ip_clean = str(ip_number or "").strip()
    uhid_clean = str(uhid or "").strip()

    ip_filter_clauses = []
    if ip_clean:
        ip_filter_clauses.extend([
            {"ipNumber": ip_clean},
            {"inpatient_number": ip_clean},
            {"ip_number": ip_clean},
        ])
    if not ip_filter_clauses and uhid_clean:
        ip_filter_clauses.append({"uhid": uhid_clean})

    if not ip_filter_clauses:
        return {
            "is_clear_for_billing": False,
            "pending_total": 0,
            "error": "No IP number or UHID provided",
            "streams": {}
        }

    match_ip = {"$or": ip_filter_clauses} if len(ip_filter_clauses) > 1 else ip_filter_clauses[0]

    # --- 1. Lab ---
    lab_query = {
        "$and": [
            match_ip,
            {
                "is_ward_request": True,
                "ward_request_type": "LAB",
                "is_active": True,
                "status": {"$nin": ["Cancelled", "Completed", "Result Entered", "Outsourced", "Printed", "Dispatched", "cancelled", "completed", "outsourced", "printed", "dispatched"]}
            }
        ]
    }
    lab_docs = list(mongo_db["hospital_investbilling"].find(
        lab_query,
        {"investBillNo": 1, "item": 1, "status": 1, "total": 1, "finalPrice": 1, "created_date": 1, "investBillDate": 1}
    ))
    lab_bills = []
    lab_pending_items = []
    for d in lab_docs:
        bill_no = d.get("investBillNo") or "Lab Request"
        dt_raw = d.get("investBillDate") or d.get("created_date")
        dt_str = dt_raw.strftime("%d/%m/%Y, %I:%M %p") if (dt_raw and hasattr(dt_raw, "strftime")) else ""
        tot = d.get("finalPrice") if d.get("finalPrice") is not None else d.get("total")
        tot_str = f"Rs. {float(tot):,.2f}" if tot is not None else ""
        status_str = d.get("status") or "Result Pending"

        raw_items = d.get("item", [])
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = []
        item_details = []
        for it in (raw_items if isinstance(raw_items, list) else []):
            if isinstance(it, dict) and it.get("itemName"):
                it_st = str(it.get("status") or status_str or "").strip().lower()
                if it_st in ["cancelled", "completed", "result entered", "outsourced", "printed", "dispatched"] or it.get("cancelled"):
                    continue
                p = it.get("price")
                p_str = f" (Rs. {p})" if p else ""
                item_details.append(f"{it.get('itemName')}{p_str} [{it.get('status') or status_str}]")

        if item_details:
            lab_bills.append({
                "bill_no": bill_no,
                "date": dt_str,
                "status": status_str,
                "total": tot_str,
                "items": item_details
            })
            items_summary = f"{bill_no}: {', '.join(item_details)}"
            lab_pending_items.append(items_summary)

    # --- 2. Radiology ---
    rad_query = {
        "$and": [
            match_ip,
            {
                "is_ward_request": True,
                "ward_request_type": "RADIOLOGY",
                "is_active": True,
                "status": {"$nin": ["Cancelled", "Completed", "Result Entered", "Dispatched", "Printed", "Outsourced", "cancelled", "completed", "dispatched", "printed", "outsourced"]}
            }
        ]
    }
    rad_docs = list(mongo_db["hospital_investbilling"].find(
        rad_query,
        {"investBillNo": 1, "item": 1, "status": 1, "total": 1, "finalPrice": 1, "created_date": 1, "investBillDate": 1}
    ))
    rad_bills = []
    rad_pending_items = []
    for d in rad_docs:
        bill_no = d.get("investBillNo") or "Radiology Request"
        dt_raw = d.get("investBillDate") or d.get("created_date")
        dt_str = dt_raw.strftime("%d/%m/%Y, %I:%M %p") if (dt_raw and hasattr(dt_raw, "strftime")) else ""
        tot = d.get("finalPrice") if d.get("finalPrice") is not None else d.get("total")
        tot_str = f"Rs. {float(tot):,.2f}" if tot is not None else ""
        status_str = d.get("status") or "Result Pending"

        raw_items = d.get("item", [])
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = []
        item_details = []
        for it in (raw_items if isinstance(raw_items, list) else []):
            if isinstance(it, dict) and it.get("itemName"):
                it_st = str(it.get("status") or status_str or "").strip().lower()
                if it_st in ["cancelled", "completed", "result entered", "dispatched", "printed", "outsourced"] or it.get("cancelled"):
                    continue
                p = it.get("price")
                p_str = f" (Rs. {p})" if p else ""
                item_details.append(f"{it.get('itemName')}{p_str} [{it.get('status') or status_str}]")

        if item_details:
            rad_bills.append({
                "bill_no": bill_no,
                "date": dt_str,
                "status": status_str,
                "total": tot_str,
                "items": item_details
            })
            items_summary = f"{bill_no}: {', '.join(item_details)}"
            rad_pending_items.append(items_summary)

    # --- 3. Pharmacy ---
    pharm_pending_query = {
        "$and": [
            match_ip,
            {
                "is_ward_request": True,
                "is_deleted": {"$ne": True},
                "billing_status": {"$in": ["Pending", "Draft", "Processing"]}
            }
        ]
    }
    pharm_pending_docs = list(mongo_db["hospital_pharmacybilling"].find(
        pharm_pending_query,
        {"Bill_id": 1, "bill_no": 1, "billing_status": 1, "net_amount": 1, "total_amount": 1, "bill_date": 1, "created_date": 1, "ward_request_date": 1, "medicine_particulars": 1}
    ))
    pharm_item_ids = set()
    for d in pharm_pending_docs:
        for m in d.get("medicine_particulars", []):
            if isinstance(m, dict) and m.get("item_id"):
                pharm_item_ids.add(m.get("item_id"))
    pharm_map = {}
    if pharm_item_ids:
        try:
            for r in mongo_db["hospital_pharmacyitem"].find({"item_id": {"$in": list(pharm_item_ids)}}, {"item_id": 1, "item_name": 1}):
                pharm_map[r.get("item_id")] = r.get("item_name")
        except Exception:
            pass

    pharm_bills = []
    pharm_pending_items = []
    for d in pharm_pending_docs:
        b_num = d.get("bill_no") or d.get("Bill_id") or "Req"
        b_label = f"Bill #{b_num}" if not str(b_num).startswith("Bill") else str(b_num)
        dt_raw = d.get("bill_date") or d.get("created_date") or d.get("ward_request_date")
        dt_str = dt_raw.strftime("%d/%m/%Y, %I:%M %p") if (dt_raw and hasattr(dt_raw, "strftime")) else ""
        tot = d.get("net_amount") if d.get("net_amount") is not None else d.get("total_amount")
        tot_str = f"Rs. {float(tot):,.2f}" if tot is not None else ""
        st_str = d.get("billing_status") or "Pending"

        item_details = []
        for m in d.get("medicine_particulars", []):
            if isinstance(m, dict):
                m_name = m.get("item_name") or pharm_map.get(m.get("item_id")) or f"Medicine #{m.get('item_id')}"
                qty = m.get("qty") or m.get("quantity") or 1
                item_details.append(f"{m_name} (Qty: {qty})")

        pharm_bills.append({
            "bill_no": b_label,
            "date": dt_str,
            "status": st_str,
            "total": tot_str,
            "items": item_details
        })
        pharm_pending_items.append(f"{b_label} ({st_str}): {', '.join(item_details[:3])}" if item_details else f"{b_label} (Status: {st_str})")

    # Check unapproved returns in pharmacy
    pharm_return_query = {
        "$and": [
            match_ip,
            {
                "is_ward_request": True,
                "is_deleted": {"$ne": True},
                "pending_returns": {"$exists": True, "$not": {"$size": 0}}
            }
        ]
    }
    pharm_return_docs = list(mongo_db["hospital_pharmacybilling"].find(
        pharm_return_query,
        {"Bill_id": 1, "bill_no": 1, "pending_returns": 1}
    ))
    pharm_returns_pending_count = 0
    for d in pharm_return_docs:
        rets = d.get("pending_returns", [])
        unapproved = [r for r in rets if isinstance(r, dict) and not r.get("is_approved") and not r.get("is_rejected")]
        if unapproved:
            pharm_returns_pending_count += len(unapproved)
            b_num = d.get("bill_no") or d.get("Bill_id") or "Req"
            b_label = f"Bill #{b_num}" if not str(b_num).startswith("Bill") else str(b_num)
            return_details = []
            for r in unapproved:
                r_name = r.get("item_name") or pharm_map.get(r.get("item_id")) or f"Item #{r.get('item_id')}"
                r_qty = r.get("return_qty") or r.get("qty") or 1
                return_details.append(f"{r_name} (Return Qty: {r_qty})")

            pharm_bills.append({
                "bill_no": f"{b_label} - Return Request",
                "status": "Return Pending Approval",
                "items": return_details
            })
            pharm_pending_items.append(f"{b_label}: {len(unapproved)} Medicine return(s) pending approval")

    # --- 4. Implants ---
    implant_query = {
        "$and": [
            match_ip,
            {"is_active": True}
        ]
    }
    implant_docs = list(mongo_db["hospital_implant_request"].find(
        implant_query,
        {"ImplantRequest_id": 1, "items": 1, "status": 1}
    ))
    implant_item_ids = set()
    for d in implant_docs:
        for it in d.get("items", []):
            if isinstance(it, dict) and it.get("item_id"):
                implant_item_ids.add(it.get("item_id"))
    implant_map = {}
    if implant_item_ids:
        try:
            for it_rec in mongo_db["hospital_velavan_items"].find({"item_id": {"$in": list(implant_item_ids)}}, {"item_id": 1, "itemName": 1}):
                implant_map[it_rec.get("item_id")] = it_rec.get("itemName")
        except Exception:
            pass

    implant_bills = []
    implant_pending_items = []
    has_implant_requests = len(implant_docs) > 0
    if has_implant_requests:
        sales_bill = mongo_db["hospital_velavansalesbill"].find_one({
            "ip_number": ip_clean,
            "payment_status": "PAID"
        })
        if not sales_bill:
            for imp in implant_docs:
                req_id = imp.get("ImplantRequest_id") or "Req"
                b_label = f"Implant Request #{req_id}"
                st_str = "Unbilled / Payment Pending"
                item_details = []
                for it in imp.get("items", []):
                    if isinstance(it, dict):
                        it_name = it.get("itemName") or implant_map.get(it.get("item_id")) or it.get("hsn") or f"Implant #{it.get('item_id')}"
                        qty = it.get("quantity") or it.get("qty") or 1
                        item_details.append(f"{it_name} (Qty: {qty})")

                implant_bills.append({
                    "bill_no": b_label,
                    "status": st_str,
                    "items": item_details
                })
                implant_pending_items.append(f"{b_label} - {st_str}")

    # --- 5. Diet ---
    diet_query = {
        "$and": [
            match_ip,
            {"status": {"$in": ["Ordered", "Received"]}}
        ]
    }
    diet_docs = list(mongo_db["hospital_patientdietorder"].find(
        diet_query,
        {"diet_type": 1, "meal_time": 1, "status": 1, "order_date": 1}
    ))
    diet_bills = []
    diet_pending_items = []
    for d in diet_docs:
        m_time = d.get("meal_time") or "Meal"
        d_type = d.get("diet_type") or "Regular Diet"
        st = d.get("status") or "Ordered"
        dt_raw = d.get("order_date")
        dt_str = dt_raw.strftime("%d/%m/%Y, %I:%M %p") if (dt_raw and hasattr(dt_raw, "strftime")) else ""

        diet_bills.append({
            "bill_no": f"Diet: {m_time}",
            "date": dt_str,
            "status": st,
            "items": [f"{m_time} ({d_type}) - Status: {st}"]
        })
        diet_pending_items.append(f"{m_time} ({d_type}) - Status: {st}")

    # --- 6. Laundry ---
    laundry_query = {
        "$and": [
            match_ip,
            {"status": "Pending"}
        ]
    }
    laundry_docs = list(mongo_db["hospital_laundrywardrequest"].find(
        laundry_query,
        {"id": 1, "request_type": 1, "status": 1, "created_date": 1, "items": 1}
    ))
    laundry_bills = []
    laundry_pending_items = []
    for d in laundry_docs:
        lid = d.get("id") or "Req"
        rtype = d.get("request_type") or "Normal"
        st = d.get("status") or "Pending"
        dt_raw = d.get("created_date")
        dt_str = dt_raw.strftime("%d/%m/%Y, %I:%M %p") if (dt_raw and hasattr(dt_raw, "strftime")) else ""

        raw_items = d.get("items", [])
        item_details = []
        if isinstance(raw_items, list):
            for it in raw_items:
                if isinstance(it, dict):
                    i_name = it.get("item") or it.get("name") or "Linen"
                    qty = it.get("qty") or 1
                    item_details.append(f"{i_name} (Qty: {qty})")

        laundry_bills.append({
            "bill_no": f"Laundry Request #{lid} ({rtype})",
            "date": dt_str,
            "status": st,
            "items": item_details if item_details else [f"Laundry #{lid} ({rtype}) - Status: {st}"]
        })
        laundry_pending_items.append(f"Laundry #{lid} ({rtype}) - Status: {st}")

    lab_count = len(lab_bills)
    rad_count = len(rad_bills)
    pharm_count = len(pharm_bills)
    implant_count = len(implant_bills)
    diet_count = len(diet_bills)
    laundry_count = len(laundry_bills)

    pending_total = lab_count + rad_count + pharm_count + implant_count + diet_count + laundry_count
    is_clear = (pending_total == 0)

    return {
        "is_clear_for_billing": is_clear,
        "pending_total": pending_total,
        "streams": {
            "lab": {
                "name": "Lab Investigations",
                "icon": "bi-droplet",
                "is_cleared": lab_count == 0,
                "pending_count": lab_count,
                "bills": lab_bills,
                "items": lab_pending_items,
            },
            "radiology": {
                "name": "Radiology",
                "icon": "bi-camera",
                "is_cleared": rad_count == 0,
                "pending_count": rad_count,
                "bills": rad_bills,
                "items": rad_pending_items,
            },
            "pharmacy": {
                "name": "Pharmacy / Medicines",
                "icon": "bi-capsule",
                "is_cleared": pharm_count == 0,
                "pending_count": pharm_count,
                "pending_bills_count": len(pharm_pending_docs),
                "pending_returns_count": pharm_returns_pending_count,
                "bills": pharm_bills,
                "items": pharm_pending_items,
            },
            "implants": {
                "name": "Implants",
                "icon": "bi-shield-check",
                "is_cleared": implant_count == 0,
                "has_requests": has_implant_requests,
                "pending_count": implant_count,
                "bills": implant_bills,
                "items": implant_pending_items,
            },
            "diet": {
                "name": "Diet Orders",
                "icon": "bi-egg-fried",
                "is_cleared": diet_count == 0,
                "pending_count": diet_count,
                "bills": diet_bills,
                "items": diet_pending_items,
            },
            "laundry": {
                "name": "Laundry Requests",
                "icon": "bi-basket",
                "is_cleared": laundry_count == 0,
                "pending_count": laundry_count,
                "bills": laundry_bills,
                "items": laundry_pending_items,
            },
        }
    }


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def check_patient_billing_clearance(request):
    try:
        params = getattr(request, "query_params", None) if hasattr(request, "query_params") else getattr(request, "GET", {})
        ip_number = params.get("ipNumber") or params.get("ip_number", "")
        uhid = params.get("uhid", "")
        if not ip_number and not uhid:
            return Response({"success": False, "error": "ipNumber or uhid is required"}, status=400)

        clearance = get_patient_billing_clearance_data(ip_number, uhid)
        return Response({"success": True, **clearance})
    except Exception as e:
        print(f"Error checking patient billing clearance: {e}\n{traceback.format_exc()}")
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["POST"])

def update_admission_status(request):

    try:

        ip_number = request.data.get("ip_number") or request.data.get("ipNumber")

        ward_status = request.data.get("status")

        if not ip_number or not ward_status:

            return Response({"error": "ip_number and status are required"}, status=400)

        # Server-side guard: verify clearance if attempting to mark "Sent for billing"
        if ward_status == "Sent for billing":
            clearance = get_patient_billing_clearance_data(ip_number)
            if not clearance.get("is_clear_for_billing", False):
                pending_streams = []
                for s_key, s_val in clearance.get("streams", {}).items():
                    if not s_val.get("is_cleared", True):
                        pending_streams.append(f"{s_val.get('name', s_key.title())} ({s_val.get('pending_count', 1)} pending)")
                pending_msg = ", ".join(pending_streams) if pending_streams else "Pending items exist"
                return Response({
                    "success": False,
                    "error": f"Cannot send for billing. Patient has uncleared requests: {pending_msg}.",
                    "clearance": clearance
                }, status=400)

        # Update in Relational Model

        try:

            Admission.objects.filter(ipNumber=ip_number).update(ward_status=ward_status)

        except Exception as e:

            print(f"Error updating Admission model: {e}")

        # Map to specific logical statuses if needed, e.g., Sent for billing -> is_billed = True?

        update_fields = {"ward_status": ward_status}

        

        if ward_status == "Sent for billing":

            update_fields["billing_status"] = "Pending"

            update_fields["is_billed"] = False # Optional, based on existing logic

            

        result = mongo_db["hospital_admission"].update_one(

            {"ipNumber": ip_number},

            {"$set": update_fields}

        )

        if result.matched_count == 0:

            return Response({"error": "Admission record not found"}, status=404)

        return Response({"success": True, "message": "Status updated successfully"})

    except Exception as e:

        print(f"Error updating admission status: {e}")

        return Response({"error": str(e)}, status=500)

@api_view(["POST"])

# @permission_classes([HasRoleAndDataPermission])

def return_medicine_ward_request(request):

    import traceback

    try:

        data = request.data

        bill_id = data.get("Bill_id")

        returned_medicines = data.get("medicine_particulars", [])

        changed_by = (

            data.get("requested_by")

            or data.get("auth-user-id")

            or request.headers.get("auth-user-id")

            or request.META.get("HTTP_AUTH_USER_ID")

        )

        if not changed_by or str(changed_by).strip().lower() in ["unknown", "none", "", "null"]:

            changed_by = getattr(bill, "created_by", None) or "system"

        if not bill_id:

            return Response({"success": False, "error": "Bill_id is required"}, status=400)

        try:

            bill = PharmacyBilling.objects.get(Bill_id=bill_id)

        except PharmacyBilling.DoesNotExist:

            return Response({"success": False, "error": "Ward request not found"}, status=404)

        existing = list(bill.medicine_particulars or [])

        # Build a lookup map keyed by (item_id, batch_number)

        existing_map = {}

        for idx, itm in enumerate(existing):

            if not isinstance(itm, dict):

                continue

            key = (str(itm.get("item_id", "")), str(itm.get("batch_number", "")))

            existing_map[key] = (idx, itm)

        # Instead of directly processing the return, append to pending_returns

        changed_at = timezone.now().isoformat()

        

        # Load or initialize pending_returns

        pending_returns = bill.pending_returns if hasattr(bill, "pending_returns") and bill.pending_returns else []

        if not isinstance(pending_returns, list):

            pending_returns = []

        # Find a unique return ID for this request

        import uuid

        return_request_id = str(uuid.uuid4())

        new_pending_items = []

        for incoming in returned_medicines:

            if not isinstance(incoming, dict):

                continue

            key = (str(incoming.get("item_id", "")), str(incoming.get("batch_number", "")))

            if key not in existing_map:

                continue

            idx, current = existing_map[key]

            

            # The frontend sends 'returned_qty'

            return_qty = float(incoming.get("returned_qty", incoming.get("return_qty", 0)))

            if return_qty <= 0:

                continue

            # Just add to pending request

            new_pending_items.append({

                "item_id": incoming.get("item_id", ""),

                "item_name": incoming.get("item_name", current.get("item_name", "")),

                "batch_number": incoming.get("batch_number", ""),

                "return_qty": return_qty,

                "reason": incoming.get("reason", "Ward Return"),

            })

        if not new_pending_items:

            return Response({"success": False, "error": "No valid items to return"}, status=400)

        pending_returns.append({

            "return_request_id": return_request_id,

            "requested_by": changed_by,

            "requested_at": changed_at,

            "items": new_pending_items,

            "status": "Pending"

        })

        mongo_db["hospital_pharmacybilling"].update_one(

            {"Bill_id": bill.Bill_id},

            {"$set": {"pending_returns": pending_returns}}

        )

        return Response({"success": True, "message": "Return request sent to Pharmacy for approval"})

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])

# @permission_classes([HasRoleAndDataPermission])

def get_pending_ward_returns(request):

    try:

        # Fetch bills with pending returns

        collection = mongo_db["hospital_pharmacybilling"]

        

        # Match only documents that have pending_returns array where status is "Pending"

        pipeline = [

            {"$match": {

                "pending_returns": {"$exists": True, "$not": {"$size": 0}}

            }},

            {"$unwind": "$pending_returns"},

            {"$match": {

                "pending_returns.status": "Pending"

            }},

            {"$sort": {"pending_returns.requested_at": -1}}

        ]

        

        results = list(collection.aggregate(pipeline))

        

        formatted_data = []

        for doc in results:

            pr = doc.get("pending_returns", {})

            uhid_val = doc.get("uhid") or pr.get("uhid") or ""

            ip_val = doc.get("inpatient_number", doc.get("ip_number", pr.get("ip_number", "")))

            

            # Resolve patient name using dbcollection helper

            patient_name = pr.get("patient_name") or doc.get("patient_name") or ""

            if not patient_name:

                patient_name = get_patient_name_by_uhid(uhid_val, ip_val)

                if not patient_name:

                    admission = mongo_db["hospital_admission"].find_one({"uhid": uhid_val})

                    if admission and "patient_details" in admission:

                        fname = admission["patient_details"].get("firstName", "")

                        lname = admission["patient_details"].get("lastName", "")

                        patient_name = f"{fname} {lname}".strip()

            # Map existing medicine particulars to enrich items

            existing_meds = doc.get("medicine_particulars", [])

            existing_meds_map = {}

            for m in existing_meds:

                if isinstance(m, dict):

                    k = (str(m.get("item_id", "")).strip(), str(m.get("batch_number", "")).strip())

                    existing_meds_map[k] = m

            enriched_items = []

            total_return_amount = 0.0

            for itm in pr.get("items", []):

                i_id = str(itm.get("item_id", "")).strip()

                b_no = str(itm.get("batch_number", "")).strip()

                matched_med = existing_meds_map.get((i_id, b_no)) or {}

                price = float(matched_med.get("price") or itm.get("price") or 0.0)

                mrp = float(matched_med.get("mrp") or itm.get("mrp") or price)

                qty = float(itm.get("return_qty") or itm.get("qty") or 0.0)

                tax = float(matched_med.get("tax") or (float(matched_med.get("CGST_Percentage", 0)) + float(matched_med.get("SGST_Percentage", 0))))

                item_name = itm.get("item_name") or matched_med.get("item_name") or f"Item #{i_id}"

                expiry_date = matched_med.get("expiry_date") or itm.get("expiry_date") or "—"

                item_total = round(qty * price, 2)

                total_return_amount += item_total

                enriched_items.append({

                    "item_id": itm.get("item_id"),

                    "item_name": item_name,

                    "batch_number": b_no,

                    "return_qty": qty,

                    "qty": qty,

                    "price": price,

                    "mrp": mrp,

                    "tax": tax,

                    "expiry_date": expiry_date,

                    "amount": item_total,

                    "reason": itm.get("reason", "")

                })

            formatted_data.append({

                "Bill_id": doc.get("Bill_id"),

                "bill_no": doc.get("bill_no", ""),

                "bill_date": doc.get("bill_date"),

                "uhid": uhid_val,

                "ip_number": ip_val,

                "patient_name": patient_name,

                "doctor_id": doc.get("doctor_id", ""),

                "doctor_name": get_doctor_name_by_id(doc.get("doctor_id")),

                "ward_name": doc.get("room_no", ""),

                "room_no": doc.get("room_no", ""),

                "return_request_id": pr.get("return_request_id"),

                "requested_by": pr.get("requested_by"),

                "requested_at": pr.get("requested_at"),

                "items": enriched_items,

                "return_amount": round(total_return_amount, 2),

                "original_bill_amount": float(doc.get("net_amount") or doc.get("total_amount") or 0.0)

            })

            

        return Response({"success": True, "data": formatted_data})

        

    except Exception as e:

        import traceback

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])

# @permission_classes([HasRoleAndDataPermission])

def approve_ward_return(request):

    import traceback

    try:

        data = request.data

        bill_id = data.get("Bill_id")

        return_request_id = data.get("return_request_id")

        action = data.get("action", "Approve") # "Approve" or "Reject"

        changed_by = data.get("auth-user-id", "system")

        if not bill_id or not return_request_id:

            return Response({"success": False, "error": "Bill_id and return_request_id are required"}, status=400)

        # Match Bill_id as both int and str in PyMongo

        bill_query = {"Bill_id": {"$in": [bill_id, int(bill_id) if str(bill_id).isdigit() else bill_id]}}

        bill_doc = mongo_db["hospital_pharmacybilling"].find_one(bill_query)

        bill = None

        try:

            bill = PharmacyBilling.objects.get(Bill_id=int(bill_id) if str(bill_id).isdigit() else bill_id)

        except Exception:

            try:

                bill = PharmacyBilling.objects.get(Bill_id=bill_id)

            except Exception:

                pass

        if not bill and not bill_doc:

            return Response({"success": False, "error": "Ward request not found"}, status=404)

        pending_returns = (bill_doc.get("pending_returns") if bill_doc else None) or getattr(bill, "pending_returns", None) or []

        target_pr = None

        target_idx = -1

        

        for idx, pr in enumerate(pending_returns):

            if pr.get("return_request_id") == return_request_id and pr.get("status") == "Pending":

                target_pr = pr

                target_idx = idx

                break

                

        if not target_pr:

            return Response({"success": False, "error": "Pending return request not found or already processed"}, status=404)

        if action == "Reject":

            pending_returns[target_idx]["status"] = "Rejected"

            pending_returns[target_idx]["processed_by"] = changed_by

            pending_returns[target_idx]["processed_at"] = timezone.now().isoformat()

            mongo_db["hospital_pharmacybilling"].update_one(

                bill_query,

                {"$set": {"pending_returns": pending_returns}}

            )

            try:

                PharmacyBilling.objects.filter(Bill_id__in=[bill_id, int(bill_id) if str(bill_id).isdigit() else bill_id]).update(pending_returns=pending_returns)

            except Exception:

                pass

            return Response({"success": True, "message": "Return request rejected"})

        # --- Approval Logic ---

        existing = list((bill_doc.get("medicine_particulars") if bill_doc else None) or getattr(bill, "medicine_particulars", None) or [])

        existing_map = {}

        for idx, itm in enumerate(existing):

            if not isinstance(itm, dict): continue

            key = (str(itm.get("item_id", "")).strip(), str(itm.get("batch_number", "")).strip())

            existing_map[key] = (idx, itm)

        # Generate Return Bill Number (format: 2627/000001)

        now_dt = timezone.now()

        current_year = now_dt.year % 100

        next_year = (now_dt.year + 1) % 100

        financial_year = f"{current_year:02d}{next_year:02d}"

        max_no = 0

        try:

            last_records = WardReturnDetails.objects.filter(

                ward_return_bill_no__startswith=financial_year

            ).values_list("ward_return_bill_no", flat=True)

            for b in last_records:

                try:

                    lp = str(b).split("/")[-1]

                    if lp.isdigit():

                        max_no = max(max_no, int(lp))

                except Exception:

                    pass

        except Exception:

            pass

        new_no = max_no + 1

        ward_return_bill_no = f"{financial_year}/{new_no:06d}"

        processed_at = now_dt.isoformat()

        outlet_code = (bill_doc.get("outlet_code") if bill_doc else None) or getattr(bill, "outlet_code", None)

        hospital_code = (bill_doc.get("hospital_code") if bill_doc else None) or getattr(bill, "hospital_code", None)

        branch_code = (bill_doc.get("branch_code") if bill_doc else None) or getattr(bill, "branch_code", None)

        original_bill_total = float((bill_doc.get("net_amount") if bill_doc else None) or (bill_doc.get("total_amount") if bill_doc else None) or getattr(bill, "net_amount", 0.0) or getattr(bill, "total_amount", 0.0) or 0.0)

        ward_return_particulars = []

        total_return_amount = 0.0

        for incoming in target_pr.get("items", []):

            item_id_val = incoming.get("item_id")

            batch_val = str(incoming.get("batch_number", "")).strip()

            return_qty = float(incoming.get("return_qty", 0))

            if return_qty <= 0:

                continue

            # 1. Update medicine_particulars in bill

            key = (str(item_id_val).strip(), batch_val)

            billed_qty = 0.0

            item_price = 0.0

            item_mrp = 0.0

            item_name = incoming.get("item_name") or ""

            expiry_date = incoming.get("expiry_date") or ""

            cgst_pct = 2.5

            sgst_pct = 2.5

            if key in existing_map:

                idx, current = existing_map[key]

                if not item_name:

                    item_name = current.get("item_name") or ""

                item_price = float(current.get("price") or 0.0)

                item_mrp = float(current.get("mrp") or item_price)

                expiry_date = current.get("expiry_date") or expiry_date

                cgst_pct = float(current.get("CGST_Percentage") or 2.5)

                sgst_pct = float(current.get("SGST_Percentage") or 2.5)

                old_qty = float(current.get("quantity", current.get("qty", 0)))

                history_returns = [

                    float(h.get("return_qty", 0))

                    for h in current.get("edit_history", [])

                    if h.get("action") in ("returned", "sales_return")

                ]

                billed_qty = old_qty + sum(history_returns) if history_returns else old_qty

                new_qty = max(0.0, old_qty - return_qty)

                audit_entry = {

                    "changed_by": changed_by,

                    "changed_at": processed_at,

                    "action": "returned",

                    "return_qty": return_qty,

                    "old_qty": old_qty,

                    "new_qty": new_qty,

                    "reason": incoming.get("reason", "Ward Return"),

                    "return_bill_no": ward_return_bill_no

                }

                eh = current.get("edit_history", [])

                if not isinstance(eh, list):

                    eh = []

                eh.append(audit_entry)

                current["edit_history"] = eh

                current["quantity"] = new_qty

                current["qty"] = new_qty

                existing[idx] = current

            # 2. Reduce blocked_quantity in hospital_pharmacystock based on outlet_code, item_id, batch_number

            item_outlet = incoming.get("outlet_code") or outlet_code

            iid_candidates = [item_id_val]

            try:

                iid_candidates.append(int(item_id_val))

            except (ValueError, TypeError):

                pass

            try:

                iid_candidates.append(str(item_id_val).strip())

            except (ValueError, TypeError):

                pass

            iid_candidates = list(set(iid_candidates))

            stock_filter = {

                "item_id": {"$in": iid_candidates},

                "batch_number": batch_val,

            }

            if item_outlet:

                stock_filter["outlet_code"] = str(item_outlet).strip()

            if branch_code:

                stock_filter["branch_code"] = str(branch_code).strip()

            if hospital_code:

                stock_filter["hospital_code"] = str(hospital_code).strip()

            stock_doc = mongo_db["hospital_pharmacystock"].find_one(stock_filter)

            if not stock_doc and item_outlet:

                stock_doc = mongo_db["hospital_pharmacystock"].find_one({

                    "outlet_code": str(item_outlet).strip(),

                    "item_id": {"$in": iid_candidates},

                    "batch_number": batch_val,

                })

            if not stock_doc:

                stock_doc = mongo_db["hospital_pharmacystock"].find_one({

                    "item_id": {"$in": iid_candidates},

                    "batch_number": batch_val,

                })

            if stock_doc:

                if not item_price:

                    item_price = float(stock_doc.get("Selling_Price") or stock_doc.get("mrp") or 0.0)

                if not item_mrp:

                    item_mrp = float(stock_doc.get("mrp") or item_price)

                if not item_name:

                    item_name = stock_doc.get("item_name") or ""

                current_blocked = float(stock_doc.get("blocked_quantity", 0) or 0)

                new_blocked = max(0.0, current_blocked - return_qty)

                mongo_db["hospital_pharmacystock"].update_one(

                    {"_id": stock_doc["_id"]},

                    {"$set": {"blocked_quantity": new_blocked}}

                )

                try:

                    PharmacyStock.objects.filter(id=stock_doc.get("id")).update(blocked_quantity=new_blocked)

                except Exception:

                    pass

            item_return_amount = round(return_qty * item_price, 2)

            total_return_amount += item_return_amount

            cgst_amt = round(item_return_amount * cgst_pct / 100.0, 2)

            sgst_amt = round(item_return_amount * sgst_pct / 100.0, 2)

            try:

                clean_item_id = int(item_id_val)

            except Exception:

                clean_item_id = item_id_val

            ward_return_particulars.append({

                "item_id": clean_item_id,

                "item_name": item_name,

                "batch_number": batch_val,

                "expiry_date": expiry_date,

                "billed_qty": float(billed_qty),

                "return_qty": float(return_qty),

                "price": float(item_price),

                "mrp": float(item_mrp),

                "CGST_Percentage": float(cgst_pct),

                "SGST_Percentage": float(sgst_pct),

                "CGST_Amt": float(cgst_amt),

                "SGST_Amt": float(sgst_amt),

                "return_amount": float(item_return_amount),

                "amount": float(item_return_amount),

                "reason": incoming.get("reason", "Ward Return"),

            })

        # 3. Update status from "Pending" to "Approved" in the pending_returns array

        pending_returns[target_idx]["status"] = "Approved"

        pending_returns[target_idx]["processed_by"] = changed_by

        pending_returns[target_idx]["processed_at"] = processed_at

        pending_returns[target_idx]["return_bill_no"] = ward_return_bill_no

        total_return_amount = round(total_return_amount, 2)

        remaining_bill_amount = round(max(0.0, original_bill_total - total_return_amount), 2)

        # In pharmacy billing, we just give the approve (record approval status in pending_returns)

        # Original bill amounts and items are not reduced

        mongo_db["hospital_pharmacybilling"].update_one(

            bill_query,

            {"$set": {"pending_returns": pending_returns, "lastmodified_by": changed_by}}

        )

        try:

            PharmacyBilling.objects.filter(Bill_id__in=[bill_id, int(bill_id) if str(bill_id).isdigit() else bill_id]).update(pending_returns=pending_returns)

        except Exception:

            pass

        # 4. Save using WardReturnDetails Model

        bill_no = (bill_doc.get("bill_no") if bill_doc else None) or getattr(bill, "bill_no", None)

        uhid = (bill_doc.get("uhid") if bill_doc else None) or getattr(bill, "uhid", None)

        inpatient_number = (bill_doc.get("inpatient_number") if bill_doc else None) or getattr(bill, "inpatient_number", "") or ""

        room_no = (bill_doc.get("room_no") if bill_doc else None) or getattr(bill, "room_no", "") or ""

        doctor_id = (bill_doc.get("doctor_id") if bill_doc else None) or getattr(bill, "doctor_id", "") or ""

        doctor_name = get_doctor_name_by_id(doctor_id)

        patient_name = get_patient_name_by_uhid(uhid, inpatient_number)

        auth_emp_id = (

            data.get("auth-user-id")

            or data.get("employee_id")

            or data.get("changed_by")

            or request.headers.get("auth-user-id")

            or getattr(request.user, "username", "")

            or changed_by

            or ""

        )

        pharmacist_id = data.get("pharmacist_id") or auth_emp_id

        pharmacist_name = get_employee_name_by_id(pharmacist_id) or str(pharmacist_id)

        # Store using Django Model (WardReturnDetails) & Serializer

        ward_return_obj = WardReturnDetails.objects.create(

            ward_return_bill_no=ward_return_bill_no,

            ward_return_bill_date=now_dt,

            created_date=now_dt,

            created_by=str(auth_emp_id) if auth_emp_id else "",

            pharmacist_id=str(pharmacist_id) if pharmacist_id else "",

            pharmacist_name=pharmacist_name,

            branch_code=str(branch_code) if branch_code else "",

            hospital_code=str(hospital_code) if hospital_code else "",

            outlet_code=str(outlet_code) if outlet_code else "",

            bill_no=str(bill_no) if bill_no else "",

            Bill_id=int(bill.Bill_id) if bill and hasattr(bill, "Bill_id") and str(bill.Bill_id).isdigit() else (int(bill_id) if str(bill_id).isdigit() else None),

            uhid=str(uhid) if uhid else "",

            inpatient_number=str(inpatient_number),

            patient_name=patient_name,

            room_no=str(room_no),

            doctor_id=str(doctor_id),

            doctor_name=doctor_name,

            original_bill_amount=str(original_bill_total),

            return_amount=str(total_return_amount),

            remaining_bill_amount=str(remaining_bill_amount),

            status="Approved",

            medicine_particulars=ward_return_particulars,

        )

        serializer = WardReturnDetailsSerializer(ward_return_obj)

        return Response({

            "success": True,

            "message": "Return request approved successfully",

            "return_bill_no": ward_return_bill_no,

            "ward_return_bill_no": ward_return_bill_no,

            "ward_return_details": serializer.data

        })

    except Exception as e:

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])

def get_ward_return_details(request):

    try:

        from_date = request.GET.get("from_date")

        to_date = request.GET.get("to_date")

        bill_no = request.GET.get("bill_no")

        uhid = request.GET.get("uhid")

        ward_return_bill_no = request.GET.get("ward_return_bill_no")

        # Query using Django Model (WardReturnDetails)

        qs = WardReturnDetails.objects.all().order_by("-ward_return_bill_date")

        if ward_return_bill_no:

            qs = qs.filter(ward_return_bill_no=ward_return_bill_no)

        if bill_no:

            qs = qs.filter(bill_no=bill_no)

        if uhid:

            qs = qs.filter(uhid=uhid)

        if from_date and to_date:

            try:

                start_dt = timezone.make_aware(datetime.strptime(from_date, "%Y-%m-%d")) if timezone.is_naive(datetime.strptime(from_date, "%Y-%m-%d")) else datetime.strptime(from_date, "%Y-%m-%d")

                end_dt = timezone.make_aware(datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)) if timezone.is_naive(datetime.strptime(to_date, "%Y-%m-%d")) else datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)

                qs = qs.filter(ward_return_bill_date__gte=start_dt, ward_return_bill_date__lt=end_dt)

            except Exception:

                pass

        elif from_date:

            try:

                start_dt = timezone.make_aware(datetime.strptime(from_date, "%Y-%m-%d")) if timezone.is_naive(datetime.strptime(from_date, "%Y-%m-%d")) else datetime.strptime(from_date, "%Y-%m-%d")

                qs = qs.filter(ward_return_bill_date__gte=start_dt)

            except Exception:

                pass

        elif to_date:

            try:

                end_dt = timezone.make_aware(datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)) if timezone.is_naive(datetime.strptime(to_date, "%Y-%m-%d")) else datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)

                qs = qs.filter(ward_return_bill_date__lt=end_dt)

            except Exception:

                pass

        # Serialize using WardReturnDetailsSerializer

        serialized_records = WardReturnDetailsSerializer(qs, many=True).data

        data = []

        seen_return_nos = set()

        for r in serialized_records:

            ret_no = r.get("ward_return_bill_no")

            if ret_no:

                if ret_no in seen_return_nos:

                    continue

                seen_return_nos.add(ret_no)

            uhid_val = r.get("uhid", "")

            ip_val = r.get("inpatient_number", "")

            pat_name = r.get("patient_name") or get_patient_name_by_uhid(uhid_val, ip_val)

            doc_name = r.get("doctor_name") or get_doctor_name_by_id(r.get("doctor_id"))

            pharm_name = r.get("pharmacist_name") or get_employee_name_by_id(r.get("pharmacist_id") or r.get("created_by"))

            meds = r.get("medicine_particulars") or []

            if isinstance(meds, str):

                try:

                    import json

                    meds = json.loads(meds)

                except Exception:

                    meds = []

            calc_return_amt = sum(float(m.get("return_amount") or (float(m.get("return_qty", 0)) * float(m.get("price", 0)))) for m in meds if isinstance(m, dict))

            saved_return_amt = float(r.get("return_amount") or 0.0)

            return_amt = saved_return_amt if saved_return_amt > 0 else round(calc_return_amt, 2)

            orig_bill_no = r.get("bill_no")

            orig_bill = None

            if orig_bill_no:

                orig_bill = PharmacyBilling.objects.filter(bill_no=orig_bill_no).first()

            orig_amt = float(r.get("original_bill_amount") or (orig_bill.total_amount if orig_bill else 0.0) or (orig_bill.net_amount if orig_bill else 0.0) or 0.0)

            if orig_bill and orig_amt <= return_amt and float(orig_bill.net_amount or 0) > 0:

                orig_amt = float(orig_bill.net_amount or 0) + return_amt

            bal_amt = max(0.0, orig_amt - return_amt)

            data.append({

                "ward_return_bill_no": r.get("ward_return_bill_no"),

                "ward_return_bill_date": r.get("ward_return_bill_date"),

                "bill_no": orig_bill_no,

                "Bill_id": r.get("Bill_id") or (orig_bill.Bill_id if orig_bill else None),

                "uhid": uhid_val,

                "inpatient_number": ip_val or (orig_bill.inpatient_number if orig_bill else ""),

                "patient_name": pat_name,

                "room_no": r.get("room_no") or (orig_bill.room_no if orig_bill else ""),

                "doctor_name": doc_name or (orig_bill.doctor_id if orig_bill else ""),

                "pharmacist_name": pharm_name,

                "created_by": pharm_name,

                "original_bill_amount": round(orig_amt, 2),

                "return_amount": round(return_amt, 2),

                "balance_amount": round(bal_amt, 2),

                "net_amount": round(bal_amt, 2),

                "status": r.get("status", "Approved"),

                "medicine_particulars": meds,

                "bill_date": orig_bill.bill_date if orig_bill else None,

            })

        return Response({"success": True, "data": data, "count": len(data)})

    except Exception as e:

        import traceback

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

from ..models import CrashCartItem, CrashCartDailyCheck

@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def get_crash_cart_items(request):

    nursing_station = request.GET.get("nursing_station")

    try:

        if nursing_station:

            items = CrashCartItem.objects.filter(nursing_station=nursing_station).order_by('box_category', 'id')

        else:

            items = CrashCartItem.objects.all().order_by('box_category', 'id')

            

        data = [

            {

                "id": item.id,

                "box_category": item.box_category,

                "drug_name": item.drug_name,

                "required_stock": item.required_stock,

            }

            for item in items

        ]

        return Response({"success": True, "data": data})

    except Exception as e:

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET", "POST"])

@permission_classes([HasRoleAndDataPermission])

def save_crash_cart_daily_check(request):

    try:

        if request.method == "GET":

            date_str = request.GET.get("date")

            nursing_station = request.GET.get("nursing_station")

            if not date_str or not nursing_station:

                return Response({"success": False, "error": "Date and Nursing Station are required."}, status=400)

            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

            items = CrashCartItem.objects.filter(nursing_station=nursing_station).order_by('box_category', 'id')

            if not items.exists():

                items = CrashCartItem.objects.all().order_by('box_category', 'id')

            checks = CrashCartDailyCheck.objects.filter(

                date=date_obj,

                nursing_station=nursing_station

            )

            checks_dict = {check.item_id: check for check in checks}

            data = []

            for item in items:

                check = checks_dict.get(item.id)

                avail_qty = getattr(check, 'available_qty', None) if check else None

                data.append({

                    "id": item.id,

                    "box_category": item.box_category,

                    "drug_name": item.drug_name,

                    "required_stock": item.required_stock,

                    "available_qty": avail_qty if avail_qty is not None else item.required_stock,

                    "expiry_date": check.expiry_date if check else "",

                    "is_checked": check.is_checked if check else False,

                    "checked_by": check.checked_by if check else "",

                })

            return Response({"success": True, "data": data})

        elif request.method == "POST":

            data = request.data

            date_str = data.get("date")

            nursing_station = data.get("nursing_station")

            checks = data.get("checks", [])

            checked_by = data.get("auth-employee-name", "Nurse")

            if not date_str or not nursing_station:

                return Response({"success": False, "error": "Date and Nursing Station are required."}, status=400)

            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

            for check in checks:

                item_id = check.get("item_id")

                expiry_date = check.get("expiry_date", "")

                is_checked = check.get("is_checked", False)

                available_qty = check.get("available_qty")

                item = CrashCartItem.objects.filter(id=item_id).first()

                if not item:

                    continue

                defaults = {

                    "expiry_date": expiry_date,

                    "is_checked": is_checked,

                    "checked_by": checked_by,

                }

                if available_qty is not None:

                    try:

                        defaults["available_qty"] = int(available_qty)

                    except (ValueError, TypeError):

                        defaults["available_qty"] = item.required_stock

                else:

                    defaults["available_qty"] = item.required_stock

                obj, created = CrashCartDailyCheck.objects.update_or_create(

                    date=date_obj,

                    nursing_station=nursing_station,

                    item=item,

                    defaults=defaults

                )

            return Response({"success": True, "message": "Daily check saved successfully."})

    except Exception as e:

        import traceback

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def get_crash_cart_monthly_report(request):

    try:

        month = int(request.GET.get("month"))

        year = int(request.GET.get("year"))

        nursing_station = request.GET.get("nursing_station")

        if not month or not year or not nursing_station:

            return Response({"success": False, "error": "Month, Year, and Nursing Station are required."}, status=400)

        # Get all items

        items = CrashCartItem.objects.filter(nursing_station=nursing_station).order_by('box_category', 'id')

        if not items.exists():

            items = CrashCartItem.objects.all().order_by('box_category', 'id')

        

        # Get all checks for the given month and year

        import calendar

        _, last_day = calendar.monthrange(year, month)

        start_date = datetime(year, month, 1).date()

        end_date = datetime(year, month, last_day).date()

        checks = CrashCartDailyCheck.objects.filter(

            nursing_station=nursing_station,

            date__gte=start_date,

            date__lte=end_date,

        )

        # Create a dictionary mapping (item_id, day) -> check

        checks_map = {}

        for check in checks:

            checks_map[(check.item_id, check.date.day)] = {

                "is_checked": check.is_checked,

                "expiry_date": check.expiry_date,

                "available_qty": getattr(check, 'available_qty', None),

                "checked_by": check.checked_by

            }

        report_data = []

        for item in items:

            item_row = {

                "id": item.id,

                "box_category": item.box_category,

                "drug_name": item.drug_name,

                "required_stock": item.required_stock,

                "days": {}

            }

            

            # Populate days

            latest_expiry = ""

            for day in range(1, last_day + 1):

                check = checks_map.get((item.id, day))

                if check:

                    item_row["days"][day] = {

                        "is_checked": check["is_checked"],

                        "available_qty": check["available_qty"] if check["available_qty"] is not None else item.required_stock,

                        "checked_by": check["checked_by"]

                    }

                    if check["expiry_date"]:

                        latest_expiry = check["expiry_date"]

                else:

                    item_row["days"][day] = None

            item_row["expiry_date"] = latest_expiry

            report_data.append(item_row)

        return Response({"success": True, "data": report_data})

    except Exception as e:

        import traceback

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])

@permission_classes([HasRoleAndDataPermission])

def get_ward_bill_types(request):

    """

    Dedicated endpoint for Ward Management (Nursing Station) bill types.

    Decoupled from cashier outlet filtering; returns only bill types configured

    for Ward Management modules (ward_medicine, ward_lab, ward_radiology).

    Accepts optional ?module=medicine | lab | radiology

    """

    client = None

    try:

        mongo_uri = os.getenv("GLOBAL_DB_HOST")

        client = MongoClient(mongo_uri)

        db = client["HMS"]

        collection = db["hospital_billtype"]

        module = (request.GET.get("module") or "").strip().lower()

        query = {"is_active": True}

        if module in ["medicine", "pharma", "pharmacy"]:

            query["ward_medicine"] = True

        elif module == "lab":

            query["ward_lab"] = True

        elif module in ["radiology", "rad", "scan"]:

            query["ward_radiology"] = True

        else:

            query["$or"] = [

                {"ward_medicine": True},

                {"ward_lab": True},

                {"ward_radiology": True},

                {"ward_request": True}

            ]

        # Hospital / Branch scoping if provided

        branch_code = request.data.get("auth-branch-code")

        hospital_code = request.data.get("auth-hospital-code")

        if hospital_code and hospital_code != "system":

            query["hospital_code"] = hospital_code

        if branch_code and branch_code != "system":

            query["branch_code"] = branch_code

        bill_types = list(collection.find(

            query,

            {

                "_id": 0,

                "bill_type": 1,

                "bill_name": 1,

                "billTypeNo": 1,

                "outlet_code": 1,

                "is_allowDiscount": 1,

                "ward_medicine": 1,

                "ward_lab": 1,

                "ward_radiology": 1,

                "ward_request": 1,

            }

        ).sort("bill_name", 1))

        return Response({

            "success": True,

            "billTypes": bill_types,

            "count": len(bill_types)

        }, status=200)

    except Exception as e:

        import traceback

        print(traceback.format_exc())

        return Response({"success": False, "error": str(e)}, status=500)

    finally:

        if client:

            client.close()

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def get_nursing_station_pharmacy_stock(request):
    """
    Dedicated endpoint for Nursing Station / Ward Management to fetch and search pharmacy medicine stock.
    Decoupled from cashier/nurse outlet data restrictions so wards (e.g. MAIN BLOCK OLET003)
    can freely view, search, and request medicine stock from pharmacy stock outlets (e.g. IP PHARMACY OLET001).

    Query parameters / body payload:
    - search / q: Search string (item_name, generic, brand, or item_id)
    - outlet_code: Target pharmacy stock outlet (default: 'OLET001'). If a non-stock ward outlet
                   (such as OLET003 or OLET004) is passed, automatically resolves to 'OLET001'.
                   Can also pass 'ALL' to search across all active pharmacy stock outlets.
    - include_zero_stock: If true, include items with 0 available stock (default: false).
    - limit: Max records to return (default: 80 for search, 100 for empty search).
    """
    client = None
    try:
        data = request.data if isinstance(getattr(request, "data", None), dict) else {}

        # Scoping
        hospital_code = (
            request.GET.get("hospital_code")
            or request.headers.get("Hospital-Code")
            or data.get("auth-hospital-code")
            or "SH001"
        )
        branch_code = (
            request.GET.get("branch_code")
            or request.headers.get("Branch-Code")
            or data.get("auth-branch-code")
            or "SHB001"
        )

        # Target pharmacy outlet resolution
        raw_outlet = (
            request.GET.get("outlet_code")
            or request.GET.get("outlet")
            or data.get("outlet_code")
            or ""
        ).strip()

        # Non-stock ward/station outlets
        non_stock_outlets = {"OLET003", "OLET004", "OLET005"}
        if not raw_outlet or raw_outlet.upper() in non_stock_outlets:
            target_outlet = "OLET001"
        elif raw_outlet.upper() == "ALL":
            target_outlet = None  # Match all active stock outlets
        else:
            target_outlet = raw_outlet

        search_query = (
            request.GET.get("search")
            or request.GET.get("q")
            or data.get("search")
            or ""
        ).strip()

        include_zero = str(
            request.GET.get("include_zero_stock")
            or data.get("include_zero_stock")
            or "false"
        ).lower() in ("true", "1", "yes")

        limit_val = int(request.GET.get("limit") or data.get("limit") or (80 if search_query else 100))

        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_uri)
        db = client["HMS"]

        def to_num(val, default=0.0):
            if val is None:
                return default
            if hasattr(val, "to_decimal"):
                return float(val.to_decimal())
            try:
                return float(val)
            except Exception:
                return default

        def format_date(dt):
            if not dt:
                return "-"
            if isinstance(dt, (datetime, date)):
                return dt.strftime("%Y-%m-%d")
            s = str(dt).strip()
            if "T" in s:
                return s.split("T")[0]
            return s[:10]

        matching_item_ids = None
        item_priority_map = {}

        if search_query:
            escaped = re.escape(search_query)
            item_match_base = {
                "is_active": True,
                "is_blocked": False
            }
            if hospital_code and hospital_code != "system":
                item_match_base["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                item_match_base["branch_code"] = branch_code

            seen_ids = set()
            found_ordered_ids = []

            # 1. Exact starting with search query (Priority 0 - Highest)
            prefix_items = list(db["hospital_pharmacyitem"].find(
                {**item_match_base, "item_name": {"$regex": f"^{escaped}", "$options": "i"}},
                {"item_id": 1, "item_name": 1, "_id": 0}
            ).sort("item_name", 1).limit(100))

            for it in prefix_items:
                iid = it.get("item_id")
                if iid is not None and iid not in seen_ids:
                    seen_ids.add(iid)
                    found_ordered_ids.append(iid)
                    item_priority_map[iid] = 0

            # 2. Word boundary starting with search query (Priority 1)
            word_items = list(db["hospital_pharmacyitem"].find(
                {**item_match_base, "item_name": {"$regex": f"(?:^|\\s){escaped}", "$options": "i"}, "item_id": {"$nin": list(seen_ids)}},
                {"item_id": 1, "item_name": 1, "_id": 0}
            ).sort("item_name", 1).limit(60))

            for it in word_items:
                iid = it.get("item_id")
                if iid is not None and iid not in seen_ids:
                    seen_ids.add(iid)
                    found_ordered_ids.append(iid)
                    item_priority_map[iid] = 1

            # 3. Substring match in item_name, brand_name, or chemical_composition (Priority 2)
            sub_conditions = [
                {"item_name": {"$regex": escaped, "$options": "i"}},
                {"brand_name": {"$regex": escaped, "$options": "i"}},
                {"chemical_composition": {"$regex": escaped, "$options": "i"}}
            ]
            if search_query.isdigit():
                sub_conditions.append({"item_id": int(search_query)})

            sub_items = list(db["hospital_pharmacyitem"].find(
                {**item_match_base, "$or": sub_conditions, "item_id": {"$nin": list(seen_ids)}},
                {"item_id": 1, "item_name": 1, "_id": 0}
            ).sort("item_name", 1).limit(80))

            for it in sub_items:
                iid = it.get("item_id")
                if iid is not None and iid not in seen_ids:
                    seen_ids.add(iid)
                    found_ordered_ids.append(iid)
                    item_priority_map[iid] = 2

            if not found_ordered_ids:
                return Response({
                    "success": True,
                    "count": 0,
                    "target_outlet": target_outlet or "ALL",
                    "data": []
                }, status=200)

            matching_item_ids = found_ordered_ids

        # Build Stock match stage
        stock_match = {}
        if hospital_code and hospital_code != "system":
            stock_match["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            stock_match["branch_code"] = branch_code

        if target_outlet:
            stock_match["outlet_code"] = target_outlet
        else:
            stock_match["outlet_code"] = {"$in": ["OLET001", "OLET002"]}

        if matching_item_ids is not None:
            stock_match["item_id"] = {"$in": matching_item_ids}

        if not include_zero:
            stock_match["total_stock"] = {"$gt": 0}

        pipeline = [
            {"$match": stock_match},
            {
                "$lookup": {
                    "from": "hospital_pharmacyitem",
                    "let": {
                        "item_id": "$item_id",
                        "branch_code": "$branch_code",
                        "hospital_code": "$hospital_code"
                    },
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$item_id", "$$item_id"]},
                                        {"$eq": ["$branch_code", "$$branch_code"]},
                                        {"$eq": ["$hospital_code", "$$hospital_code"]}
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "item_details"
                }
            },
            {
                "$unwind": {
                    "path": "$item_details",
                    "preserveNullAndEmptyArrays": False
                }
            },
            {
                "$match": {
                    "item_details.is_active": True,
                    "item_details.is_blocked": False
                }
            },
            {
                "$addFields": {
                    "available_stock": {
                        "$add": [
                            {
                                "$subtract": [
                                    {
                                        "$subtract": [
                                            {
                                                "$subtract": [
                                                    {
                                                        "$subtract": [
                                                            {"$ifNull": ["$total_stock", 0]},
                                                            {"$ifNull": ["$sold_quantity", 0]}
                                                        ]
                                                    },
                                                    {"$ifNull": ["$transferred_out_quantity", 0]}
                                                ]
                                            },
                                            {"$ifNull": ["$grn_return_quantity", 0]}
                                        ]
                                    },
                                    {"$ifNull": ["$blocked_quantity", 0]}
                                ]
                            },
                            {"$ifNull": ["$sales_return_quantity", 0]}
                        ]
                    },
                    "reorder_level": {"$ifNull": ["$item_details.reorder_level", 0]}
                }
            }
        ]

        if not include_zero:
            pipeline.append({"$match": {"available_stock": {"$gt": 0}}})

        pipeline.append({"$sort": {"item_details.item_name": 1, "expiry_date": 1}})
        # If searching, limit pipeline loosely so we can re-order by priority in Python before final limit
        pipeline.append({"$limit": max(limit_val * 3, 200) if search_query else limit_val})

        raw_records = list(db["hospital_pharmacystock"].aggregate(pipeline))

        results = []
        for r in raw_records:
            item_info = r.get("item_details", {})
            outlet = r.get("outlet_code", "OLET001")

            shelf = item_info.get("IP_shelf_no", "") if outlet == "OLET001" else item_info.get("OP_shelf_no", item_info.get("G_shelf_no", ""))
            rack = item_info.get("IP_rack_no", "") if outlet == "OLET001" else item_info.get("OP_rack_no", item_info.get("G_rack_no", ""))

            mrp_val = to_num(r.get("mrp") or r.get("Selling_Price"))
            selling_price_val = to_num(r.get("Selling_Price") or r.get("mrp"))
            avail_stock = to_num(r.get("available_stock"))
            total_stock_val = to_num(r.get("total_stock"))
            reorder_val = to_num(r.get("reorder_level"))

            results.append({
                "id": f"{r.get('item_id')}_{r.get('batch_number')}",
                "stock_id": r.get("stock_id") or r.get("id"),
                "item_id": r.get("item_id"),
                "item_name": item_info.get("item_name") or f"Item {r.get('item_id')}",
                "name": item_info.get("item_name") or f"Item {r.get('item_id')}",
                "batch_number": r.get("batch_number") or "",
                "expiry_date": format_date(r.get("expiry_date")),
                "mrp": mrp_val,
                "Selling_Price": selling_price_val,
                "price": selling_price_val or mrp_val,
                "total_stock": total_stock_val,
                "available_stock": avail_stock,
                "outlet_code": outlet,
                "shelf_no": shelf,
                "rack_no": rack,
                "category": item_info.get("category"),
                "reorder_level": reorder_val,
                "is_low_stock": avail_stock <= reorder_val,
                "high_risk": bool(item_info.get("high_risk", False))
            })

        if search_query:
            results.sort(key=lambda x: (
                item_priority_map.get(x.get("item_id"), 99),
                str(x.get("item_name", "")).lower(),
                x.get("expiry_date", "")
            ))
            results = results[:limit_val]

        return Response({
            "success": True,
            "count": len(results),
            "target_outlet": target_outlet or "ALL",
            "data": results
        }, status=200)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)
    finally:
        if client:
            client.close()

