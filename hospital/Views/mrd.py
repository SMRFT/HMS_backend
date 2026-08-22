import os
import datetime
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient

from pyauth.auth import HasRoleAndDataPermission
from ..models import MRD, Admission, Patient


def _get_db():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    return client["HMS"]


def _format_datetime(dt):
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


def _format_date(d):
    if not d:
        return ""
    if isinstance(d, datetime.datetime):
        return d.date().isoformat()
    if isinstance(d, datetime.date):
        return d.isoformat()
    if isinstance(d, str):
        return d.split("T")[0]
    return str(d)


def _resolve_doctor_map(db, doc_ids=None):
    """
    Build a comprehensive mapping of doctor_id / employeeId -> doctor name
    from Global['backend_diagnostics_profile'] and HMS['hospital_doctormaster'].
    """
    doc_map = {}
    clean_ids = list(set(str(d).strip() for d in (doc_ids or []) if d and str(d).strip()))

    # 1. Look up in Global['backend_diagnostics_profile'] by employeeId
    try:
        mongo_host = os.getenv("GLOBAL_DB_HOST")
        global_db_name = "Global"
        client = MongoClient(mongo_host)
        global_db = client[global_db_name]

        profile_query = {}
        if clean_ids:
            profile_query = {"employeeId": {"$in": clean_ids}}

        cursor = global_db["backend_diagnostics_profile"].find(
            profile_query,
            {"employeeId": 1, "employeeName": 1, "firstName": 1, "lastName": 1, "name": 1, "_id": 0}
        )
        for doc in cursor:
            e_id = str(doc.get("employeeId") or "").strip()
            name = (
                doc.get("employeeName")
                or doc.get("name")
                or f"{doc.get('firstName', '')} {doc.get('lastName', '')}"
            ).strip()
            if e_id and name:
                doc_map[e_id] = name
    except Exception as e:
        print(f"[MRD] Profile lookup error: {e}")

    # 2. Look up in HMS['hospital_doctormaster']
    try:
        doc_query = {}
        if clean_ids:
            doc_query = {"$or": [{"doctor_id": {"$in": clean_ids}}, {"employeeId": {"$in": clean_ids}}]}

        doctors = list(db["hospital_doctormaster"].find(doc_query, {"doctor_id": 1, "employeeId": 1, "doctorName": 1, "firstName": 1, "lastName": 1}))
        for d in doctors:
            d_id = str(d.get("doctor_id") or d.get("employeeId") or "").strip()
            name = (d.get("doctorName") or f"{d.get('firstName', '')} {d.get('lastName', '')}").strip()
            if d_id and name:
                if d_id not in doc_map or not doc_map[d_id]:
                    doc_map[d_id] = name
    except Exception as e:
        print(f"[MRD] Doctormaster lookup error: {e}")

    return doc_map


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def mrd_discharged_files(request):
    """
    List all discharged patient files where is_discharged=True strictly from hospital_admission.
    Combines with the MRD tracking model (Pending, Received, Scanned) and Nurse/Doctor error fields.
    """
    try:
        db = _get_db()
        status_filter = request.GET.get("status", "All").strip()
        from_date_str = request.GET.get("from_date", "").strip()
        to_date_str   = request.GET.get("to_date", "").strip()
        search_query  = request.GET.get("q", "").strip().lower()

        # 1. Fetch discharged admissions only (is_discharged: True)
        adm_query = {
            "is_discharged": True,
            "is_cancelled": {"$ne": True}
        }
        admissions = list(db["hospital_admission"].find(adm_query))

        # 2. Fetch all MRD records
        mrd_records = list(db["hospital_mrd"].find({"is_active": {"$ne": False}}))
        mrd_map = {str(m.get("ip_no", "")).strip(): m for m in mrd_records if m.get("ip_no")}

        # 3. Doctor lookup map based on employeeId
        doc_ids = set()
        for a in admissions:
            d = a.get("consultingDoctor") or a.get("admittingDoctor") or a.get("primary_doctor") or a.get("doctor")
            if d:
                doc_ids.add(str(d).strip())

        doc_map = _resolve_doctor_map(db, doc_ids)

        # 4. Collect unique UHIDs for patient details lookup
        all_uhids = set()
        for a in admissions:
            if a.get("uhid"):
                all_uhids.add(str(a.get("uhid")).strip())

        patient_docs = list(db["hospital_patient"].find({"uhid": {"$in": list(all_uhids)}}))
        patient_map = {}
        for p in patient_docs:
            u = str(p.get("uhid", "")).strip()
            p_name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            patient_map[u] = {
                "patient_name": p_name,
                "age": p.get("age"),
                "gender": p.get("gender"),
                "mobile": p.get("mobilePhone") or p.get("mobile_number") or "",
            }

        # 5. Build records list from hospital_admission
        all_records = []
        counts = {
            "total": 0,
            "pending": 0,
            "received": 0,
            "scanned": 0,
            "has_error": 0,
            "resolved_error": 0,
        }


        for adm in admissions:
            ip_no = str(adm.get("ipNumber") or "").strip()
            if not ip_no:
                continue

            uhid = str(adm.get("uhid") or "").strip()
            p_info = patient_map.get(uhid, {})

            # Doctor resolution: get employee name from profile by employeeId
            doc_id = str(adm.get("consultingDoctor") or adm.get("admittingDoctor") or adm.get("primary_doctor") or adm.get("doctor") or "").strip()
            doc_name = doc_map.get(doc_id) or doc_id or "N/A"


            # Room / Ward resolution
            room_details = adm.get("room_details") or []
            room_no = ""
            ward_name = adm.get("ward_status") or ""
            if isinstance(room_details, list) and len(room_details) > 0:
                active_r = next((r for r in reversed(room_details) if r.get("is_roomActive")), room_details[-1])
                room_no = str(active_r.get("roomNo") or "")
                if not ward_name and active_r.get("wardName"):
                    ward_name = active_r.get("wardName")

            discharge_dt = adm.get("lastmodified_date") or adm.get("discharge_date") or adm.get("admissionDateTime")

            item = {
                "ip_no": ip_no,
                "uhid": uhid,
                "patient_name": p_info.get("patient_name") or adm.get("patient_name") or "N/A",
                "age": p_info.get("age") or adm.get("age") or "",
                "gender": p_info.get("gender") or adm.get("gender") or "",
                "mobile": p_info.get("mobile") or "",
                "doctor_id": doc_id,
                "doctor_name": doc_name,
                "admission_date": _format_datetime(adm.get("admissionDateTime") or adm.get("created_date")),
                "discharge_date": _format_datetime(discharge_dt),
                "admitted_by": adm.get("created_by") or "",
                "discharged_by": adm.get("lastmodified_by") or "",
                "room_no": room_no,
                "ward_name": ward_name,
                "bill_no": "",
                "company_code": adm.get("company_code") or "",
                "customer_type": adm.get("customer_type") or "General",
            }

            # 6. Attach MRD Tracking & Error Information
            mrd = mrd_map.get(ip_no)

            if mrd:
                mrd_status = mrd.get("status") or "Pending"
                item["mrd_id"]             = mrd.get("mrd_id") or ""
                item["status"]             = mrd_status
                item["received_date"]      = _format_datetime(mrd.get("received_date"))
                item["received_by"]        = mrd.get("received_by") or ""
                item["scanned_date"]       = _format_datetime(mrd.get("scanned_date"))
                item["scanned_by"]         = mrd.get("scanned_by") or ""
                item["mrd_created_date"]   = _format_datetime(mrd.get("created_date"))

                # Error tracking fields
                item["is_error"]            = bool(mrd.get("is_error", False))
                item["nurse_error"]         = mrd.get("nurse_error") or ""
                item["doctor_error"]        = mrd.get("doctor_error") or ""
                item["is_error_resolved"]   = bool(mrd.get("is_error_resolved", False))
                item["error_reported_by"]   = mrd.get("error_reported_by") or ""
                item["error_reported_date"] = _format_datetime(mrd.get("error_reported_date"))
                item["error_resolved_by"]   = mrd.get("error_resolved_by") or ""
                item["error_resolved_date"] = _format_datetime(mrd.get("error_resolved_date"))
            else:
                item["mrd_id"]             = ""
                item["status"]             = "Pending"
                item["received_date"]      = ""
                item["received_by"]        = ""
                item["scanned_date"]       = ""
                item["scanned_by"]         = ""
                item["mrd_created_date"]   = ""

                item["is_error"]            = False
                item["nurse_error"]         = ""
                item["doctor_error"]        = ""
                item["is_error_resolved"]   = False
                item["error_reported_by"]   = ""
                item["error_reported_date"] = ""
                item["error_resolved_by"]   = ""
                item["error_resolved_date"] = ""


            counts["total"] += 1
            if item["status"] == "Received":
                counts["received"] += 1
            elif item["status"] == "Scanned":
                counts["scanned"] += 1
            else:
                counts["pending"] += 1

            if item["is_error"] and not item["is_error_resolved"]:
                counts["has_error"] += 1
            if item["is_error"] and item["is_error_resolved"]:
                counts["resolved_error"] += 1

            all_records.append(item)

        # 7. Apply Filters (Status, Date Range, Search Query)
        filtered_records = []
        for r in all_records:
            # Status Filter
            if status_filter and status_filter.lower() != "all":
                if status_filter.lower() in ["error", "unresolved"]:
                    if not r["is_error"] or r["is_error_resolved"]:
                        continue
                elif status_filter.lower() in ["resolved", "resolved_error"]:
                    if not r["is_error"] or not r["is_error_resolved"]:
                        continue
                elif r["status"].lower() != status_filter.lower():
                    continue


            # Date Range Filter on discharge_date
            if from_date_str and r["discharge_date"]:
                if r["discharge_date"] < from_date_str:
                    continue
            if to_date_str and r["discharge_date"]:
                if r["discharge_date"] > to_date_str:
                    continue

            # Global Search Filter
            if search_query:
                haystack = f"{r['ip_no']} {r['uhid']} {r['patient_name']} {r['doctor_name']} {r['mrd_id']} {r['nurse_error']} {r['doctor_error']}".lower()
                if search_query not in haystack:
                    continue

            filtered_records.append(r)

        # Sort descending by discharge date or IP No
        filtered_records.sort(
            key=lambda x: (x.get("discharge_date") or "", x.get("admission_date") or "", x.get("ip_no") or ""),
            reverse=True,
        )

        return Response({
            "success": True,
            "stats": counts,
            "data": filtered_records,
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "success": False,
            "error": f"Failed to fetch discharged files: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def mrd_update_status(request):
    """
    Update or initialize the MRD status of an IP discharge file, or report/resolve errors.
    Statuses:
      - 'Received': Marks file as received in MRD.
      - 'Scanned': Marks file as scanned. Guard: File cannot be scanned if there is an unresolved error!
      - 'Pending': Reverts status to pending.
    Error Fields supported:
      - is_error: Boolean
      - nurse_error: String
      - doctor_error: String
      - is_error_resolved: Boolean
    """
    try:
        data = request.data
        ip_no = str(data.get("ip_no") or "").strip()
        target_status = data.get("status")
        remarks = data.get("remarks")

        if not ip_no:
            return Response({"success": False, "error": "ip_no is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Extract logged in user identifier
        user_id = (
            request.data.get("auth-user-id")
            or request.headers.get("auth-user-id")
            or (request.user.username if request.user and request.user.is_authenticated else None)
            or "system"
        )
        user_name = request.data.get("user_name") or user_id
        now = timezone.now()

        # Find or create MRD record
        mrd_obj = MRD.objects.filter(ip_no=ip_no).first()

        if not mrd_obj:
            uhid = data.get("uhid")
            if not uhid:
                adm = Admission.objects.filter(ipNumber=ip_no).first()
                if adm:
                    uhid = adm.uhid

            mrd_obj = MRD(
                ip_no=ip_no,
                uhid=uhid or "",
                status=target_status if target_status else "Pending",
                created_by=user_name,
                created_date=now,
                lastmodified_by=user_name,
                lastmodified_date=now,
            )

        current_status = mrd_obj.status or "Pending"

        # Handle Error Updates if provided in request
        if "is_error" in data:
            is_err = bool(data.get("is_error"))
            mrd_obj.is_error = is_err

            if is_err:
                if "nurse_error" in data:
                    mrd_obj.nurse_error = str(data.get("nurse_error") or "").strip()
                if "doctor_error" in data:
                    mrd_obj.doctor_error = str(data.get("doctor_error") or "").strip()

                mrd_obj.error_reported_by = mrd_obj.error_reported_by or user_name
                mrd_obj.error_reported_date = mrd_obj.error_reported_date or now

                if "is_error_resolved" in data:
                    is_res = bool(data.get("is_error_resolved"))
                    mrd_obj.is_error_resolved = is_res
                    if is_res:
                        mrd_obj.error_resolved_by = user_name
                        mrd_obj.error_resolved_date = now
                    else:
                        mrd_obj.error_resolved_by = None
                        mrd_obj.error_resolved_date = None
            else:
                mrd_obj.nurse_error = ""
                mrd_obj.doctor_error = ""
                mrd_obj.is_error_resolved = False
                mrd_obj.error_reported_by = None
                mrd_obj.error_reported_date = None
                mrd_obj.error_resolved_by = None
                mrd_obj.error_resolved_date = None

        # Handle Status Transitions if status is passed
        if target_status:
            target_status = str(target_status).strip()
            valid_statuses = ["Pending", "Received", "Scanned"]
            if target_status not in valid_statuses:
                return Response(
                    {"success": False, "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validation rule 1: 'Scanned' requires file to be 'Received' or already 'Scanned'
            if target_status == "Scanned" and current_status not in ["Received", "Scanned"]:
                return Response({
                    "success": False,
                    "error": "Cannot mark as Scanned: File must be marked as 'Received' first."
                }, status=status.HTTP_400_BAD_REQUEST)

            # Validation rule 2: 'Scanned' CANNOT be marked if there is an unresolved error!
            if target_status == "Scanned" and mrd_obj.is_error and not mrd_obj.is_error_resolved:
                return Response({
                    "success": False,
                    "error": "Cannot mark as Scanned: File has unresolved Nurse/Doctor error(s). Please click 'Resolved' first."
                }, status=status.HTTP_400_BAD_REQUEST)

            mrd_obj.status = target_status

            if target_status == "Received":
                mrd_obj.received_by = user_name
                mrd_obj.received_date = now
            elif target_status == "Scanned":
                mrd_obj.received_by = mrd_obj.received_by or user_name
                mrd_obj.received_date = mrd_obj.received_date or now
                mrd_obj.scanned_by = user_name
                mrd_obj.scanned_date = now
            elif target_status == "Pending":
                mrd_obj.received_by = None
                mrd_obj.received_date = None
                mrd_obj.scanned_by = None
                mrd_obj.scanned_date = None

        mrd_obj.lastmodified_by = user_name
        mrd_obj.lastmodified_date = now
        mrd_obj.save()

        return Response({
            "success": True,
            "message": f"MRD details updated successfully!",
            "data": {
                "mrd_id": mrd_obj.mrd_id,
                "ip_no": mrd_obj.ip_no,
                "uhid": mrd_obj.uhid,
                "status": mrd_obj.status,
                "received_by": mrd_obj.received_by,
                "received_date": _format_datetime(mrd_obj.received_date),
                "scanned_by": mrd_obj.scanned_by,
                "scanned_date": _format_datetime(mrd_obj.scanned_date),
                "is_error": mrd_obj.is_error,
                "nurse_error": mrd_obj.nurse_error or "",
                "doctor_error": mrd_obj.doctor_error or "",
                "is_error_resolved": mrd_obj.is_error_resolved,
                "error_reported_by": mrd_obj.error_reported_by or "",
                "error_reported_date": _format_datetime(mrd_obj.error_reported_date),
                "error_resolved_by": mrd_obj.error_resolved_by or "",
                "error_resolved_date": _format_datetime(mrd_obj.error_resolved_date),
                "lastmodified_date": _format_datetime(mrd_obj.lastmodified_date),
            }
        }, status=status.HTTP_200_OK)


    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "success": False,
            "error": f"Failed to update MRD status: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def mrd_stats(request):
    """
    Get quick statistics for MRD tracking strictly from hospital_admission.
    """
    try:
        db = _get_db()
        discharged_adms = db["hospital_admission"].count_documents({"is_discharged": True, "is_cancelled": {"$ne": True}})
        received_count = db["hospital_mrd"].count_documents({"status": "Received", "is_active": {"$ne": False}})
        scanned_count  = db["hospital_mrd"].count_documents({"status": "Scanned", "is_active": {"$ne": False}})
        error_count    = db["hospital_mrd"].count_documents({"is_error": True, "is_error_resolved": False, "is_active": {"$ne": False}})
        resolved_count = db["hospital_mrd"].count_documents({"is_error": True, "is_error_resolved": True, "is_active": {"$ne": False}})
        pending_count  = max(0, discharged_adms - (received_count + scanned_count))

        return Response({
            "success": True,
            "stats": {
                "total": discharged_adms,
                "pending": pending_count,
                "received": received_count,
                "scanned": scanned_count,
                "has_error": error_count,
                "resolved_error": resolved_count,
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
