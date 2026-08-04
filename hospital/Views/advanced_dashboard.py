from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.utils.timezone import make_aware, is_aware
from datetime import datetime, timedelta
import calendar
from pymongo import MongoClient
import os
import pytz

# Setup Mongo Client
MONGO_URI = os.getenv("GLOBAL_DB_HOST") or "mongodb://localhost:27017/HMS"
client = MongoClient(MONGO_URI)
mongo_db = client["HMS"]
global_db = client["Global"]
profile_collection = global_db["backend_diagnostics_profile"]

def ensure_aware(dt):
    """Ensures a datetime object is timezone-aware (UTC)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not is_aware(dt):
        return make_aware(dt)
    return dt

@api_view(['GET'])
def advanced_dashboard_stats(request):
    try:
        month = request.GET.get('month')
        year = request.GET.get('year')
        
        # Explicitly use India Standard Time (IST)
        tz = pytz.timezone('Asia/Kolkata')
        now = timezone.now().astimezone(tz)
        
        if not month or not year:
            target_date = now
            month = target_date.month
            year = target_date.year
        else:
            month = int(month)
            year = int(year)
            target_date = now.replace(year=year, month=month, day=1)

        # 1. KPIs
        total_op = mongo_db["hospital_patient"].count_documents({})
        total_ip_lifetime = mongo_db["hospital_admission"].count_documents({})
        total_discharge_lifetime = mongo_db["hospital_admission"].count_documents({"is_discharged": True})
        current_ip = mongo_db["hospital_admission"].count_documents({"is_admitted": True, "is_discharged": {"$ne": True}})
        
        # Income Aggregations
        income_pipeline = [
            {"$match": {"payment_status": "Paid"}},
            {"$group": {"_id": None, "total": {"$sum": "$total_fees"}}}
        ]
        op_income_res = list(mongo_db["hospital_billing"].aggregate(income_pipeline))
        op_income = float(str(op_income_res[0]["total"])) if op_income_res else 0.0

        discharge_income_pipeline = [
            {"$match": {"status": "Billed"}},
            {"$group": {"_id": None, "total": {"$sum": "$net_amount"}}}
        ]
        ip_income_res = list(mongo_db["hospital_dischargebilling"].aggregate(discharge_income_pipeline))
        ip_income = float(str(ip_income_res[0]["total"])) if ip_income_res else 0.0

        pharmacy_income_pipeline = [
            {"$match": {"billing_status": "Paid"}},
            {"$group": {"_id": None, "total": {"$sum": "$net_amount"}}}
        ]
        pharm_income_res = list(mongo_db["hospital_pharmacybilling"].aggregate(pharmacy_income_pipeline))
        pharm_income = float(str(pharm_income_res[0]["total"])) if pharm_income_res else 0.0

        total_income_lifetime = op_income + ip_income + pharm_income

        # Today's Dates (IST)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        today_ip = mongo_db["hospital_admission"].count_documents({
            "is_admitted": True, 
            "admissionDateTime": {"$gte": today_start, "$lte": today_end}
        })
        
        today_visits = mongo_db["hospital_billing"].count_documents({
            "payment_status": "Paid", 
            "billed_date": {"$gte": today_start, "$lte": today_end}
        })
        today_op = max(0, today_visits - today_ip)

        today_discharge = mongo_db["hospital_admission"].count_documents({
            "is_discharged": True, 
            "lastmodified_date": {"$gte": today_start, "$lte": today_end}
        })

        # Today's Income (Billing + Pharmacy)
        today_op_income_pipeline = [
            {"$match": {"payment_status": "Paid", "billed_date": {"$gte": today_start, "$lte": today_end}}},
            {"$group": {"_id": None, "total": {"$sum": "$total_fees"}}}
        ]
        t_op_inc = list(mongo_db["hospital_billing"].aggregate(today_op_income_pipeline))
        today_op_income = float(str(t_op_inc[0]["total"])) if t_op_inc else 0.0

        today_pharm_income_pipeline = [
            {"$match": {"billing_status": "Paid", "bill_date": {"$gte": today_start, "$lte": today_end}}},
            {"$group": {"_id": None, "total": {"$sum": "$net_amount"}}}
        ]
        t_ph_inc = list(mongo_db["hospital_pharmacybilling"].aggregate(today_pharm_income_pipeline))
        today_pharm_income = float(str(t_ph_inc[0]["total"])) if t_ph_inc else 0.0

        today_revenue = today_op_income + today_pharm_income

        kpis = {
            "total_op": total_op,
            "total_ip": total_ip_lifetime,
            "total_discharge": total_discharge_lifetime,
            "current_ip": current_ip,
            "total_income": total_income_lifetime,
            "today_revenue": today_revenue,
            "today_ip": today_ip,
            "today_op": today_op,
            "today_discharge": today_discharge
        }

        # 2. Monthly Stats
        num_days = calendar.monthrange(year, month)[1]
        monthly_op_ip = []
        monthly_income_expense = []

        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.UTC)
        month_end = now.replace(year=year, month=month, day=num_days, hour=23, minute=59, second=59, microsecond=999999).astimezone(pytz.UTC)

        admissions = list(mongo_db["hospital_admission"].find({
            "is_admitted": True,
            "admissionDateTime": {"$gte": month_start, "$lte": month_end}
        }))
        
        billings = list(mongo_db["hospital_billing"].find({
            "payment_status": "Paid",
            "billed_date": {"$gte": month_start, "$lte": month_end}
        }))
        
        pharm_billings = list(mongo_db["hospital_pharmacybilling"].find({
            "billing_status": "Paid",
            "bill_date": {"$gte": month_start, "$lte": month_end}
        }))

        discharge_billings = list(mongo_db["hospital_dischargebilling"].find({
            "status": "Billed",
            "bill_date": {"$gte": month_start.strftime("%Y-%m-%d"), "$lte": month_end.strftime("%Y-%m-%d")}
        }))
        
        grns = list(mongo_db["hospital_grn"].find({
            "status": "Approved",
            "date": {"$gte": month_start, "$lte": month_end}
        }))

        for day in range(1, num_days + 1):
            # We work in IST for day boundaries
            d_start_local = now.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
            d_end_local = d_start_local.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # Convert to UTC for comparison with DB results
            d_start = d_start_local.astimezone(pytz.UTC)
            d_end = d_end_local.astimezone(pytz.UTC)

            day_admissions = [a for a in admissions if d_start <= ensure_aware(a.get("admissionDateTime")) <= d_end]
            day_billings = [b for b in billings if d_start <= ensure_aware(b.get("billed_date")) <= d_end]
            
            d_ip = len(day_admissions)
            d_visits = len(day_billings)
            d_op = max(0, d_visits - d_ip)

            monthly_op_ip.append({"day": day, "OP": d_op, "IP": d_ip})

            # Income
            d_income = sum([float(str(b.get("total_fees") or 0)) for b in day_billings])
            d_str = d_start_local.strftime("%Y-%m-%d")
            d_discharges = [db for db in discharge_billings if db.get("bill_date") == d_str]
            d_income += sum([float(str(db.get("net_amount") or 0)) for db in d_discharges])
            
            d_pharm = [pb for pb in pharm_billings if d_start <= ensure_aware(pb.get("bill_date")) <= d_end]
            d_income += sum([float(str(pb.get("net_amount") or 0)) for pb in d_pharm])

            # Expense
            d_grns = [g for g in grns if d_start <= ensure_aware(g.get("date")) <= d_end]
            d_expense = sum([float(str(g.get("net_invoice_amount") or 0)) for g in d_grns])

            monthly_income_expense.append({"day": day, "Income": d_income, "Expense": d_expense})

        # 3. Income Methods Today
        t_billings = [b for b in billings if today_start.astimezone(pytz.UTC) <= ensure_aware(b.get("billed_date")) <= today_end.astimezone(pytz.UTC)]
        t_pharm = [pb for pb in pharm_billings if today_start.astimezone(pytz.UTC) <= ensure_aware(pb.get("bill_date")) <= today_end.astimezone(pytz.UTC)]
        
        methods = {}
        for b in t_billings:
            m = b.get("payment_method") or "Cash"
            methods[m] = methods.get(m, 0) + float(str(b.get("total_fees") or 0))
        for pb in t_pharm:
            m = pb.get("payment_mode") or "Cash"
            methods[m] = methods.get(m, 0) + float(str(pb.get("net_amount") or 0))
        todays_income_method = [{"method": k, "amount": v} for k, v in methods.items()]

        # 4. Doctor Stats — monthly OP/IP counts and monthly income, per doctor
        # consultingDoctor/admittingDoctor/doctor_id all store the doctor's employeeId,
        # so we group by that id and resolve it to a display name below (not the raw id).
        doc_stats = {}
        for a in admissions:
            d = str(a.get("consultingDoctor") or a.get("admittingDoctor") or "").strip()
            if not d: continue
            if d not in doc_stats: doc_stats[d] = {"OP": 0, "IP": 0, "Amount": 0.0}
            doc_stats[d]["IP"] += 1

        for b in billings:
            d = str(b.get("doctor_id") or "").strip()
            if not d: continue
            if d not in doc_stats: doc_stats[d] = {"OP": 0, "IP": 0, "Amount": 0.0}
            doc_stats[d]["OP"] += 1
            doc_stats[d]["Amount"] += float(str(b.get("consulting_fee") or b.get("total_fees") or 0))

        doctor_ids = list(doc_stats.keys())
        doctor_name_map = {}
        if doctor_ids:
            doctor_cursor = profile_collection.find(
                {"employeeId": {"$in": doctor_ids}},
                {"employeeId": 1, "employeeName": 1}
            )
            doctor_name_map = {str(d["employeeId"]): d.get("employeeName", "") for d in doctor_cursor}

        doctor_wise = [
            {"name": doctor_name_map.get(k) or k, "OP": v["OP"], "IP": v["IP"], "Amount": v["Amount"]}
            for k, v in doc_stats.items()
        ]
        doctor_wise = sorted(doctor_wise, key=lambda x: x["Amount"], reverse=True)[:10]

        # 5. Bed Occupancy
        total_beds_res = list(mongo_db["hospital_room"].aggregate([{"$group": {"_id": None, "total": {"$sum": "$capacity"}}}]))
        total_beds = total_beds_res[0]["total"] if total_beds_res else 0
        occupied_beds = mongo_db["hospital_admission"].count_documents({"is_admitted": True, "is_discharged": {"$ne": True}})
        
        bed_occupancy = [
            {"name": "Occupied", "value": occupied_beds},
            {"name": "Vacant", "value": max(0, total_beds - occupied_beds)}
        ]

        return Response({
            "kpis": kpis,
            "monthly_op_ip": monthly_op_ip,
            "monthly_income_expense": monthly_income_expense,
            "todays_income_method": todays_income_method,
            "doctor_wise": doctor_wise,
            "bed_occupancy": bed_occupancy
        })

    except Exception as e:
        print(f"Advanced Dashboard Error: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
