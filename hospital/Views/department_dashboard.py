from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from django.utils import timezone
import calendar
import os
from pymongo import MongoClient
from ..models import Patient, Billing, Admission, PharmacyBilling, DischargeBilling

MONGO_URI = os.getenv("GLOBAL_DB_HOST")

def get_department_mapping(global_db):
    try:
        dept_collection = global_db['backend_diagnostics_Departments']
        dept_mapping = {}
        for d in dept_collection.find({}):
            code = d.get('department_code') or d.get('dept_code') or d.get('code')
            name = d.get('department_name') or d.get('dept_name') or d.get('name')
            if code and name:
                dept_mapping[code] = name
        return dept_mapping
    except Exception as e:
        print("Error fetching department mapping:", e)
        return {}


@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def department_dashboard_stats(request):
    """
    Department-based Analytics Dashboard backend API.
    Calculates OP, IP, Pharmacy, Department Bills, and Revenue per Department.
    """
    try:
        client = MongoClient(MONGO_URI)
        global_db = client['Global']
        
        # 1. Fetch Department Mappings
        dept_map = get_department_mapping(global_db)
        
        # 2. Fetch all Doctor Profiles from diagnostics_profile
        diagnostics_collection = global_db['backend_diagnostics_profile']
        doctor_profiles = list(diagnostics_collection.find(
            {"designation": "DESIG094"},
            {"employeeId": 1, "employeeName": 1, "department": 1, "specialty": 1, "_id": 0}
        ))
        
        # Build mapping of doctor employeeId -> resolved department name & profile info
        doctor_dept_map = {} # employeeId -> dept_name
        doctor_info_map = {} # employeeId -> profile dict
        
        for doc in doctor_profiles:
            emp_id = str(doc.get("employeeId", "")).strip()
            raw_dept = doc.get("department", "")
            resolved_dept = dept_map.get(raw_dept, raw_dept) if raw_dept else "General"
            
            doctor_dept_map[emp_id] = resolved_dept
            doctor_info_map[emp_id] = {
                "id": emp_id,
                "name": doc.get("employeeName", emp_id),
                "department": resolved_dept,
                "specialty": doc.get("specialty", "General")
            }

        # Unique Departments List
        all_departments = sorted(list(set(doctor_dept_map.values())))
        if not all_departments:
            all_departments = ["General"]

        # Request Parameters
        selected_dept = request.GET.get('department') or "All"
        month_param = request.GET.get('month')
        year_param = request.GET.get('year')

        now = timezone.now()
        if not month_param or not year_param:
            month = now.month
            year = now.year
        else:
            month = int(month_param)
            year = int(year_param)

        num_days = calendar.monthrange(year, month)[1]
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = now.replace(year=year, month=month, day=num_days, hour=23, minute=59, second=59, microsecond=999999)

        # 3. Fetch Monthly Records
        monthly_billings = list(Billing.objects.filter(billed_date__range=(month_start, month_end)))
        monthly_admissions = list(Admission.objects.filter(admissionDateTime__range=(month_start, month_end)))
        monthly_pharmacy = list(PharmacyBilling.objects.filter(
            billing_status="Paid",
            bill_date__range=(month_start, month_end)
        ))
        monthly_discharge = list(DischargeBilling.objects.filter(
            status="Billed",
            bill_date__range=(month_start.date(), month_end.date())
        ))

        # 4. Aggregate Stats per Department
        dept_stats = {d: {
            "department": d,
            "doctor_count": 0,
            "total_op": 0,
            "today_op": 0,
            "total_ip": 0,
            "today_ip": 0,
            "op_income": 0.0,
            "pharmacy_income": 0.0,
            "department_income": 0.0,
            "total_revenue": 0.0
        } for d in all_departments}

        # Count doctors per department
        for emp_id, d_name in doctor_dept_map.items():
            if d_name in dept_stats:
                dept_stats[d_name]["doctor_count"] += 1

        # Process OP Billings
        for b in monthly_billings:
            doc_id = str(b.doctor_id or "").strip()
            d_name = doctor_dept_map.get(doc_id, "General")
            if d_name not in dept_stats:
                dept_stats[d_name] = {
                    "department": d_name, "doctor_count": 0, "total_op": 0, "today_op": 0,
                    "total_ip": 0, "today_ip": 0, "op_income": 0.0, "pharmacy_income": 0.0,
                    "department_income": 0.0, "total_revenue": 0.0
                }
            
            fee = float(str(b.consulting_fee or b.total_fees or 0))
            dept_stats[d_name]["total_op"] += 1
            dept_stats[d_name]["op_income"] += fee
            if today_start <= b.billed_date <= today_end:
                dept_stats[d_name]["today_op"] += 1

        # Process IP Admissions
        for a in monthly_admissions:
            c_doc = str(a.consultingDoctor or "").strip()
            a_doc = str(a.admittingDoctor or "").strip()
            d_name = doctor_dept_map.get(c_doc) or doctor_dept_map.get(a_doc) or "General"
            
            if d_name not in dept_stats:
                dept_stats[d_name] = {
                    "department": d_name, "doctor_count": 0, "total_op": 0, "today_op": 0,
                    "total_ip": 0, "today_ip": 0, "op_income": 0.0, "pharmacy_income": 0.0,
                    "department_income": 0.0, "total_revenue": 0.0
                }
            
            dept_stats[d_name]["total_ip"] += 1
            if today_start <= a.admissionDateTime <= today_end:
                dept_stats[d_name]["today_ip"] += 1

        # Process Pharmacy Billings
        for p in monthly_pharmacy:
            doc_id = str(p.doctor_id or "").strip()
            d_name = doctor_dept_map.get(doc_id, "General")
            if d_name in dept_stats:
                dept_stats[d_name]["pharmacy_income"] += float(str(p.net_amount or 0))

        # Process Discharge / Department Billings
        for db in monthly_discharge:
            for item in (db.items or []):
                if not isinstance(item, dict): continue
                doc_id = str(item.get("doctor") or "").strip()
                d_name = doctor_dept_map.get(doc_id, "General")
                amt = float(str(item.get("doctor_fee") or item.get("amount") or 0))
                if d_name in dept_stats:
                    dept_stats[d_name]["department_income"] += amt

        # Calculate Total Revenue per Department
        for d_name, stats in dept_stats.items():
            stats["total_revenue"] = stats["op_income"] + stats["pharmacy_income"] + stats["department_income"]

        # Department Breakdown Array
        dept_breakdown = list(dept_stats.values())
        dept_breakdown = sorted(dept_breakdown, key=lambda x: x["total_revenue"], reverse=True)

        # Overall Totals (across all departments or filtered by selected department)
        target_depts = [selected_dept] if selected_dept != "All" else all_departments
        
        overall_kpis = {
            "total_op": sum(dept_stats[d]["total_op"] for d in target_depts if d in dept_stats),
            "today_op": sum(dept_stats[d]["today_op"] for d in target_depts if d in dept_stats),
            "total_ip": sum(dept_stats[d]["total_ip"] for d in target_depts if d in dept_stats),
            "today_ip": sum(dept_stats[d]["today_ip"] for d in target_depts if d in dept_stats),
            "total_revenue": sum(dept_stats[d]["total_revenue"] for d in target_depts if d in dept_stats),
            "op_income": sum(dept_stats[d]["op_income"] for d in target_depts if d in dept_stats),
            "pharmacy_income": sum(dept_stats[d]["pharmacy_income"] for d in target_depts if d in dept_stats),
            "department_income": sum(dept_stats[d]["department_income"] for d in target_depts if d in dept_stats),
            "doctor_count": sum(dept_stats[d]["doctor_count"] for d in target_depts if d in dept_stats),
        }

        # Doctor Performance Table (for doctors in selected department)
        doctor_performance = []
        for emp_id, info in doctor_info_map.items():
            if selected_dept != "All" and info["department"] != selected_dept:
                continue
            
            doc_op = len([b for b in monthly_billings if str(b.doctor_id or "").strip() == emp_id])
            doc_ip = len([a for a in monthly_admissions if str(a.consultingDoctor or "").strip() == emp_id or str(a.admittingDoctor or "").strip() == emp_id])
            doc_rev = sum([float(str(b.consulting_fee or b.total_fees or 0)) for b in monthly_billings if str(b.doctor_id or "").strip() == emp_id])
            
            doctor_performance.append({
                "employeeId": emp_id,
                "doctorName": info["name"],
                "department": info["department"],
                "specialty": info["specialty"],
                "op_count": doc_op,
                "ip_count": doc_ip,
                "revenue": doc_rev
            })
        
        doctor_performance = sorted(doctor_performance, key=lambda x: x["revenue"], reverse=True)

        # Monthly Trend per Day
        monthly_trend = []
        for day in range(1, num_days + 1):
            day_start = month_start.replace(day=day)
            day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

            d_op = 0
            d_ip = 0
            d_income = 0.0

            for b in monthly_billings:
                doc_id = str(b.doctor_id or "").strip()
                d_name = doctor_dept_map.get(doc_id, "General")
                if selected_dept != "All" and d_name != selected_dept:
                    continue
                if day_start <= b.billed_date <= day_end:
                    d_op += 1
                    d_income += float(str(b.consulting_fee or b.total_fees or 0))

            for a in monthly_admissions:
                c_doc = str(a.consultingDoctor or "").strip()
                a_doc = str(a.admittingDoctor or "").strip()
                d_name = doctor_dept_map.get(c_doc) or doctor_dept_map.get(a_doc) or "General"
                if selected_dept != "All" and d_name != selected_dept:
                    continue
                if day_start <= a.admissionDateTime <= day_end:
                    d_ip += 1

            monthly_trend.append({
                "day": day,
                "OP": d_op,
                "IP": d_ip,
                "Income": d_income
            })

        return Response({
            "departments": ["All"] + all_departments,
            "selected_department": selected_dept,
            "kpis": overall_kpis,
            "department_breakdown": dept_breakdown,
            "doctor_performance": doctor_performance,
            "monthly_trend": monthly_trend
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
