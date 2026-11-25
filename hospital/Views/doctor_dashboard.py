from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import datetime, timedelta
import os
import pytz
from pymongo import MongoClient

MONGO_URI = os.getenv("GLOBAL_DB_HOST") or "mongodb://localhost:27017/HMS"
_client = MongoClient(MONGO_URI)
mongo_db = _client["HMS"]
_global_db = _client["Global"]
_profile_collection = _global_db["backend_diagnostics_profile"]
_dept_collection = _global_db["backend_diagnostics_Departments"]


def _safe_float(val):
    if val is None:
        return 0.0
    try:
        if hasattr(val, "to_decimal"):
            return float(val.to_decimal())
        return float(str(val).strip() or 0)
    except (ValueError, TypeError):
        return 0.0


@api_view(['GET'])
def doctor_dashboard_stats(request):
    """
    Doctor-wise Analytics Endpoint:
    Returns doctor-wise OP, IP, Discharges, Investigations, and Revenue breakdown.
    Supports time filters: period='today'|'week'|'month'|'custom'|'all', from_date, to_date.
    """
    try:
        period = (request.GET.get('period') or 'today').strip().lower()
        from_date_str = (request.GET.get('from_date') or '').strip()
        to_date_str = (request.GET.get('to_date') or '').strip()

        tz = pytz.timezone('Asia/Kolkata')
        now = timezone.now().astimezone(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Compute date range (in IST -> UTC)
        start_ist = None
        end_ist = None

        if period == 'all':
            start_ist = None
            end_ist = None
        elif period == 'yesterday':
            start_ist = today_start - timedelta(days=1)
            end_ist = today_end - timedelta(days=1)
        elif period == 'week':
            start_ist = today_start - timedelta(days=6)
            end_ist = today_end
        elif period == 'month':
            start_ist = today_start.replace(day=1)
            end_ist = today_end
        elif from_date_str and to_date_str:
            try:
                f_dt = datetime.strptime(from_date_str, "%Y-%m-%d")
                t_dt = datetime.strptime(to_date_str, "%Y-%m-%d")
                start_ist = tz.localize(f_dt.replace(hour=0, minute=0, second=0, microsecond=0))
                end_ist = tz.localize(t_dt.replace(hour=23, minute=59, second=59, microsecond=999999))
            except ValueError:
                start_ist, end_ist = today_start, today_end
        else:
            # Default: today
            start_ist = today_start
            end_ist = today_end

        start_utc = start_ist.astimezone(pytz.UTC) if start_ist else None
        end_utc = end_ist.astimezone(pytz.UTC) if end_ist else None

        # 1. Load Department & Doctor Master Mappings
        dept_map = {}
        for d in _dept_collection.find({}, {"department_code": 1, "department_name": 1}):
            code = str(d.get("department_code") or "").strip()
            name = str(d.get("department_name") or "").strip()
            if code and name:
                dept_map[code] = name

        id_to_profile = {}
        name_to_id = {}
        for p in _profile_collection.find({}, {"employeeId": 1, "employeeName": 1, "department": 1, "designation": 1}):
            eid = str(p.get("employeeId") or "").strip()
            ename = str(p.get("employeeName") or "").strip()
            dept_code = str(p.get("department") or "").strip()
            dept_name = dept_map.get(dept_code, dept_code)
            if eid:
                id_to_profile[eid] = {
                    "id": eid,
                    "name": ename or eid,
                    "department": dept_name or "General"
                }
            if ename and eid:
                name_to_id[ename.upper()] = eid

        def resolve_doctor(raw_doc):
            s = str(raw_doc or "").strip()
            if not s or s.lower() in ("none", "null", "-", "unknown"):
                return None, None, None
            if s in id_to_profile:
                prof = id_to_profile[s]
                return prof["id"], prof["name"], prof["department"]
            s_upper = s.upper()
            if s_upper in name_to_id:
                eid = name_to_id[s_upper]
                prof = id_to_profile[eid]
                return prof["id"], prof["name"], prof["department"]
            return s, s, "Specialist"

        doctor_metrics_map = {}

        def get_bucket(raw_doc):
            did, dname, dept = resolve_doctor(raw_doc)
            if not did:
                return None
            if did not in doctor_metrics_map:
                doctor_metrics_map[did] = {
                    "doctor_id": did,
                    "doctor_name": dname,
                    "department": dept,
                    "op_count": 0,
                    "op_revenue": 0.0,
                    "ip_count": 0,
                    "ip_revenue": 0.0,
                    "discharge_count": 0,
                    "investigation_count": 0,
                    "investigation_revenue": 0.0,
                    "total_revenue": 0.0
                }
            return doctor_metrics_map[did]

        # 2. Aggregate OP Consultations & Revenue (hospital_billing)
        op_match = {"is_active": {"$ne": False}, "payment_status": {"$ne": "Cancelled"}}
        if start_utc and end_utc:
            op_match["billed_date"] = {"$gte": start_utc, "$lte": end_utc}

        op_pipeline = [
            {"$match": op_match},
            {
                "$group": {
                    "_id": "$doctor_id",
                    "op_count": {"$sum": 1},
                    "op_revenue": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$payment_status", "Paid"]},
                                {
                                    "$convert": {
                                        "input": {"$ifNull": ["$consulting_fee", "$total_fees"]},
                                        "to": "double",
                                        "onError": 0.0,
                                        "onNull": 0.0
                                    }
                                },
                                0.0
                            ]
                        }
                    }
                }
            }
        ]
        for row in mongo_db["hospital_billing"].aggregate(op_pipeline):
            bucket = get_bucket(row.get("_id"))
            if bucket:
                bucket["op_count"] += int(row.get("op_count") or 0)
                bucket["op_revenue"] += float(row.get("op_revenue") or 0.0)

        # 3. Aggregate IP Admissions (hospital_admission)
        ip_match = {"is_admitted": True}
        if start_utc and end_utc:
            ip_match["admissionDateTime"] = {"$gte": start_utc, "$lte": end_utc}

        ip_pipeline = [
            {"$match": ip_match},
            {
                "$group": {
                    "_id": {"$ifNull": ["$consultingDoctor", "$admittingDoctor"]},
                    "ip_count": {"$sum": 1}
                }
            }
        ]
        for row in mongo_db["hospital_admission"].aggregate(ip_pipeline):
            bucket = get_bucket(row.get("_id"))
            if bucket:
                bucket["ip_count"] += int(row.get("ip_count") or 0)

        # 4. Aggregate Discharges (hospital_admission)
        dis_match = {"is_discharged": True}
        if start_utc and end_utc:
            dis_match["$or"] = [
                {"dischargeDateTime": {"$gte": start_utc, "$lte": end_utc}},
                {"dischargeDateTime": None, "lastmodified_date": {"$gte": start_utc, "$lte": end_utc}},
                {"dischargeDateTime": {"$exists": False}, "lastmodified_date": {"$gte": start_utc, "$lte": end_utc}}
            ]

        dis_pipeline = [
            {"$match": dis_match},
            {
                "$group": {
                    "_id": {"$ifNull": ["$consultingDoctor", "$admittingDoctor"]},
                    "discharge_count": {"$sum": 1}
                }
            }
        ]
        for row in mongo_db["hospital_admission"].aggregate(dis_pipeline):
            bucket = get_bucket(row.get("_id"))
            if bucket:
                bucket["discharge_count"] += int(row.get("discharge_count") or 0)

        # 5. Aggregate Investigations & Investigation Revenue (hospital_investbilling)
        inv_match = {"is_active": True}
        if start_utc and end_utc:
            inv_match["investBillDate"] = {"$gte": start_utc, "$lte": end_utc}

        inv_pipeline = [
            {"$match": inv_match},
            {
                "$group": {
                    "_id": "$doctor",
                    "inv_count": {"$sum": 1},
                    "inv_revenue": {
                        "$sum": {
                            "$convert": {
                                "input": {"$ifNull": ["$finalPrice", "$total"]},
                                "to": "double",
                                "onError": 0.0,
                                "onNull": 0.0
                            }
                        }
                    }
                }
            }
        ]
        for row in mongo_db["hospital_investbilling"].aggregate(inv_pipeline):
            bucket = get_bucket(row.get("_id"))
            if bucket:
                bucket["investigation_count"] += int(row.get("inv_count") or 0)
                bucket["investigation_revenue"] += float(row.get("inv_revenue") or 0.0)

        # 6. Aggregate IP Procedure / Doctor Fees from Discharge Billing (hospital_dischargebilling)
        dbill_match = {"status": "Billed"}
        if start_utc and end_utc:
            s_str = start_ist.strftime("%Y-%m-%d")
            e_str = end_ist.strftime("%Y-%m-%d")
            dbill_match["$or"] = [
                {"bill_date": {"$gte": start_utc, "$lte": end_utc}},
                {"bill_date": {"$gte": s_str, "$lte": e_str}}
            ]

        for dbill in mongo_db["hospital_dischargebilling"].find(dbill_match, {"items": 1}):
            for item in (dbill.get("items") or []):
                if not isinstance(item, dict):
                    continue
                item_doc = item.get("doctor")
                if item_doc:
                    fee = _safe_float(item.get("doctor_fee") or item.get("amount"))
                    bucket = get_bucket(item_doc)
                    if bucket and fee > 0:
                        bucket["ip_revenue"] += fee

        # Finalize totals & sort
        doctor_metrics = []
        summary = {
            "active_doctors": 0,
            "total_op": 0,
            "total_ip": 0,
            "total_discharges": 0,
            "total_investigations": 0,
            "total_revenue": 0.0,
            "total_op_revenue": 0.0,
            "total_ip_revenue": 0.0,
            "total_investigation_revenue": 0.0
        }

        for doc in doctor_metrics_map.values():
            doc["op_revenue"] = round(doc["op_revenue"], 2)
            doc["ip_revenue"] = round(doc["ip_revenue"], 2)
            doc["investigation_revenue"] = round(doc["investigation_revenue"], 2)
            doc["total_revenue"] = round(
                doc["op_revenue"] + doc["ip_revenue"] + doc["investigation_revenue"], 2
            )

            doctor_metrics.append(doc)
            summary["active_doctors"] += 1
            summary["total_op"] += doc["op_count"]
            summary["total_ip"] += doc["ip_count"]
            summary["total_discharges"] += doc["discharge_count"]
            summary["total_investigations"] += doc["investigation_count"]
            summary["total_op_revenue"] += doc["op_revenue"]
            summary["total_ip_revenue"] += doc["ip_revenue"]
            summary["total_investigation_revenue"] += doc["investigation_revenue"]
            summary["total_revenue"] += doc["total_revenue"]

        summary["total_op_revenue"] = round(summary["total_op_revenue"], 2)
        summary["total_ip_revenue"] = round(summary["total_ip_revenue"], 2)
        summary["total_investigation_revenue"] = round(summary["total_investigation_revenue"], 2)
        summary["total_revenue"] = round(summary["total_revenue"], 2)

        doctor_metrics.sort(key=lambda x: (x["total_revenue"], x["op_count"] + x["ip_count"]), reverse=True)

        return Response({
            "success": True,
            "period": period,
            "from_date": start_ist.strftime("%Y-%m-%d") if start_ist else None,
            "to_date": end_ist.strftime("%Y-%m-%d") if end_ist else None,
            "summary": summary,
            "doctor_metrics": doctor_metrics
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
