from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import datetime, timedelta
from pymongo import MongoClient
import os
import pytz

# Setup Mongo Client
MONGO_URI = os.getenv("GLOBAL_DB_HOST") or "mongodb://localhost:27017/HMS"
client = MongoClient(MONGO_URI)
mongo_db = client["HMS"]


def resolve_date_range(request, tz):
    now = timezone.now().astimezone(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    period = (request.GET.get("period") or "").strip().lower()
    from_str = (request.GET.get("from_date") or "").strip()
    to_str = (request.GET.get("to_date") or "").strip()

    if period == "yesterday":
        s = today_start - timedelta(days=1)
        e = today_end - timedelta(days=1)
        return s, e, "yesterday"
    elif period == "week":
        s = today_start - timedelta(days=6)
        e = today_end
        return s, e, "week"
    elif period == "month":
        s = today_start.replace(day=1)
        e = today_end
        return s, e, "month"
    elif from_str and to_str:
        try:
            f_dt = datetime.strptime(from_str, "%Y-%m-%d")
            t_dt = datetime.strptime(to_str, "%Y-%m-%d")
            s = tz.localize(f_dt.replace(hour=0, minute=0, second=0, microsecond=0))
            e = tz.localize(t_dt.replace(hour=23, minute=59, second=59, microsecond=999999))
            return s, e, (period or "custom")
        except ValueError:
            pass

    return today_start, today_end, (period or "today")


@api_view(["GET"])
def dashboard_stats(request):
    try:
        tz = pytz.timezone("Asia/Kolkata")
        start_ist, end_ist, resolved_period = resolve_date_range(request, tz)

        start_utc = start_ist.astimezone(pytz.UTC)
        end_utc = end_ist.astimezone(pytz.UTC)

        # 1. KPIs for Selected Date Range
        new_patient_docs = list(mongo_db["hospital_patient"].find(
            {"created_date": {"$gte": start_utc, "$lte": end_utc}},
            {"uhid": 1, "_id": 0}
        ))
        new_patients = len(new_patient_docs)
        new_uhids = {str(p.get("uhid") or "").strip() for p in new_patient_docs if p.get("uhid")}

        op_bills = list(mongo_db["hospital_billing"].find(
            {
                "billed_date": {"$gte": start_utc, "$lte": end_utc},
                "is_active": {"$ne": False},
                "payment_status": {"$ne": "Cancelled"}
            },
            {"uhid": 1, "_id": 0}
        ))
        op_count = len(op_bills)
        # Renewals = OP visits whose UHID was NOT registered fresh within this selected range
        renewals = sum(1 for b in op_bills if str(b.get("uhid") or "").strip() not in new_uhids)

        # Admissions: include all non-cancelled admissions (even same-day discharges)
        adm_docs = list(mongo_db["hospital_admission"].find(
            {
                "admissionDateTime": {"$gte": start_utc, "$lte": end_utc},
                "is_cancelled": {"$ne": True}
            },
            {"ipNumber": 1, "_id": 0}
        ))
        ip_count = len(adm_docs)
        daycare_ip_count = sum(1 for a in adm_docs if str(a.get("ipNumber") or "").strip().upper().startswith("SD"))
        normal_ip_count = ip_count - daycare_ip_count

        def _count_discharges_in_window(w_start_utc, w_end_utc, w_start_str, w_end_str):
            dis_cursor = mongo_db["hospital_dischargebilling"].find(
                {
                    "status": {"$in": ["Billed", "Paid"]},
                    "is_cancelled": {"$ne": True},
                    "$or": [
                        {"bill_date": {"$gte": w_start_utc, "$lte": w_end_utc}},
                        {"bill_date": {"$gte": w_start_str, "$lte": f"{w_end_str}\uffff"}}
                    ]
                },
                {"ip_number": 1, "ipNumber": 1, "_id": 0}
            )
            seen_ips = {
                str(d.get("ip_number") or d.get("ipNumber") or "").strip().upper()
                for d in dis_cursor
                if (d.get("ip_number") or d.get("ipNumber"))
            }
            return len(seen_ips)

        discharge_count = _count_discharges_in_window(
            start_utc,
            end_utc,
            start_ist.strftime("%Y-%m-%d"),
            end_ist.strftime("%Y-%m-%d")
        )

        # 2. Chart Data:
        # If single day selected, plot 7 days ending on end_ist; otherwise plot days in range (capped at 31 days).
        span_days = (end_ist.date() - start_ist.date()).days + 1
        if span_days <= 1:
            chart_start = end_ist.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
            chart_days = 7
        else:
            chart_days = min(span_days, 31)
            chart_start = end_ist.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=chart_days - 1)

        chart_data = []
        for i in range(chart_days):
            day_local = chart_start + timedelta(days=i)
            day_end_local = day_local.replace(hour=23, minute=59, second=59, microsecond=999999)

            d_start = day_local.astimezone(pytz.UTC)
            d_end = day_end_local.astimezone(pytz.UTC)

            d_new_docs = list(mongo_db["hospital_patient"].find(
                {"created_date": {"$gte": d_start, "$lte": d_end}},
                {"uhid": 1, "_id": 0}
            ))
            c_new = len(d_new_docs)
            d_new_uhids = {str(p.get("uhid") or "").strip() for p in d_new_docs if p.get("uhid")}

            d_op_bills = list(mongo_db["hospital_billing"].find(
                {
                    "billed_date": {"$gte": d_start, "$lte": d_end},
                    "is_active": {"$ne": False},
                    "payment_status": {"$ne": "Cancelled"}
                },
                {"uhid": 1, "_id": 0}
            ))
            c_op = len(d_op_bills)
            c_renew = sum(1 for b in d_op_bills if str(b.get("uhid") or "").strip() not in d_new_uhids)

            c_ip = mongo_db["hospital_admission"].count_documents({
                "admissionDateTime": {"$gte": d_start, "$lte": d_end},
                "is_cancelled": {"$ne": True}
            })
            c_dis = _count_discharges_in_window(
                d_start,
                d_end,
                day_local.strftime("%Y-%m-%d"),
                day_local.strftime("%Y-%m-%d")
            )

            chart_data.append({
                "date": day_local.strftime("%d %b"),
                "OP Visits": c_op,
                "IP Admissions": c_ip,
                "New Patients": c_new,
                "Renewals": c_renew,
                "Discharges": c_dis
            })

        return Response({
            "period": resolved_period,
            "from_date": start_ist.strftime("%Y-%m-%d"),
            "to_date": end_ist.strftime("%Y-%m-%d"),
            "today_ip": ip_count,
            "today_normal_ip": normal_ip_count,
            "today_daycare_ip": daycare_ip_count,
            "today_op": op_count,
            "today_new_patients": new_patients,
            "today_renewals": renewals,
            "today_discharge": discharge_count,
            "today_total_visits": op_count,
            "chart_data": chart_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Dashboard Stats Error: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
