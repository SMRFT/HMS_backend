from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
import calendar
import os
from pymongo import MongoClient
from ..models import Patient, Billing, Admission, PharmacyBilling, DischargeBilling

MONGO_URI = os.getenv("GLOBAL_DB_HOST")
_client = MongoClient(MONGO_URI)
_global_db = _client["Global"]
_profile_collection = _global_db["backend_diagnostics_profile"]


@api_view(['GET'])
def doctor_dashboard_stats(request):
    try:
        doctor_id_param = request.GET.get('doctor_id') or request.GET.get('doctor_name')
        month = request.GET.get('month')
        year = request.GET.get('year')

        now = timezone.now()
        if not month or not year:
            target_date = now
            month = target_date.month
            year = target_date.year
        else:
            month = int(month)
            year = int(year)
            target_date = now.replace(year=year, month=month, day=1)

        # Get all distinct doctor employeeIds from Billing and Admission dynamically.
        # These fields store the doctor's raw employeeId, not their display name.
        doctor_ids = set()
        for doc in Admission.objects.values_list('consultingDoctor', flat=True).distinct():
            if doc and str(doc).strip(): doctor_ids.add(str(doc).strip())

        for doc in Admission.objects.values_list('admittingDoctor', flat=True).distinct():
            if doc and str(doc).strip(): doctor_ids.add(str(doc).strip())

        for doc in Billing.objects.values_list('doctor_id', flat=True).distinct():
            if doc and str(doc).strip(): doctor_ids.add(str(doc).strip())

        doctor_ids = sorted(list(doctor_ids))

        # Resolve employeeId -> employeeName via the shared employee profile collection
        doctor_map = {}
        if doctor_ids:
            doctor_cursor = _profile_collection.find(
                {"employeeId": {"$in": doctor_ids}},
                {"employeeId": 1, "employeeName": 1}
            )
            doctor_map = {
                str(doc["employeeId"]): doc.get("employeeName", "")
                for doc in doctor_cursor
            }

        doctor_list = [
            {"id": did, "name": doctor_map.get(did) or did}
            for did in doctor_ids
        ]

        if not doctor_list:
            doctor_list = [{"id": "Unknown", "name": "Unknown"}]

        # Default to the first doctor if none is selected
        selected_doctor_id = doctor_id_param if doctor_id_param else doctor_list[0]['id']
        selected_doctor_name = doctor_map.get(selected_doctor_id) or selected_doctor_id

        # Time ranges
        num_days = calendar.monthrange(year, month)[1]
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = now.replace(year=year, month=month, day=num_days, hour=23, minute=59, second=59, microsecond=999999)

        # 1. Doctor KPIs — Billing.doctor_id / Admission.consultingDoctor / admittingDoctor
        # store the doctor's employeeId, so we filter by selected_doctor_id (not the name).
        total_op = Billing.objects.filter(doctor_id=selected_doctor_id).count()
        total_ip = Admission.objects.filter(consultingDoctor=selected_doctor_id).count() + Admission.objects.filter(admittingDoctor=selected_doctor_id).count()

        monthly_billings = list(Billing.objects.filter(doctor_id=selected_doctor_id, billed_date__range=(month_start, month_end)))
        monthly_admissions = list(Admission.objects.filter(admissionDateTime__range=(month_start, month_end)))

        # Filter admissions for this doctor
        doctor_monthly_admissions = [a for a in monthly_admissions if a.consultingDoctor == selected_doctor_id or a.admittingDoctor == selected_doctor_id]

        # Calculate Income — OP consultation (Billing)
        consultation_income = sum([float(str(b.consulting_fee or b.total_fees or 0)) for b in monthly_billings])

        # Pharmacy income for this doctor, this month
        monthly_pharmacy_billings = list(PharmacyBilling.objects.filter(
            doctor_id=selected_doctor_id,
            billing_status="Paid",
            bill_date__range=(month_start, month_end)
        ))
        pharmacy_income = sum([float(str(p.net_amount or 0)) for p in monthly_pharmacy_billings])

        # Department billing income for this doctor, this month.
        # DischargeBilling has no top-level doctor field — the doctor is recorded
        # per line-item inside `items` (each item may carry its own doctor/doctor_fee).
        monthly_discharge_billings = list(DischargeBilling.objects.filter(
            status="Billed",
            bill_date__range=(month_start.date(), month_end.date())
        ))
        department_income = 0.0
        for bill in monthly_discharge_billings:
            for item in (bill.items or []):
                if not isinstance(item, dict): continue
                if str(item.get("doctor") or "").strip() != selected_doctor_id: continue
                department_income += float(str(item.get("doctor_fee") or item.get("amount") or 0))

        total_income = consultation_income + pharmacy_income + department_income

        today_op = len([b for b in monthly_billings if today_start <= b.billed_date <= today_end])
        today_ip = len([a for a in doctor_monthly_admissions if today_start <= a.admissionDateTime <= today_end])

        kpis = {
            "total_op": total_op,
            "total_ip": total_ip,
            "monthly_income": float(total_income),
            "consultation_income": float(consultation_income),
            "pharmacy_income": float(pharmacy_income),
            "department_income": float(department_income),
            "today_op": today_op,
            "today_ip": today_ip
        }

        income_breakdown = [
            {"source": "Consultation (OP)", "amount": float(consultation_income)},
            {"source": "Pharmacy", "amount": float(pharmacy_income)},
            {"source": "Department Billing", "amount": float(department_income)}
        ]

        # 2. Monthly Trend (OP/IP) for this doctor
        monthly_trend = []
        for day in range(1, num_days + 1):
            day_start = month_start.replace(day=day)
            day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

            d_op = len([b for b in monthly_billings if day_start <= b.billed_date <= day_end])
            d_ip = len([a for a in doctor_monthly_admissions if day_start <= a.admissionDateTime <= day_end])
            d_income = sum([float(str(b.consulting_fee or b.total_fees or 0)) for b in monthly_billings if day_start <= b.billed_date <= day_end])

            monthly_trend.append({
                "day": day,
                "OP": d_op,
                "IP": d_ip,
                "Income": d_income
            })

        # 3. Recent Patients (OP)
        # Assuming Billing has patient relation
        recent_patients = []
        recent_bills = sorted(monthly_billings, key=lambda x: x.billed_date, reverse=True)[:5]
        for b in recent_bills:
            try:
                recent_patients.append({
                    "patient_name": f"{b.patient.firstName} {b.patient.lastName}",
                    "uhid": b.patient.uhid,
                    "date": b.billed_date.strftime("%Y-%m-%d"),
                    "fee": float(str(b.consulting_fee or b.total_fees or 0))
                })
            except Patient.DoesNotExist:
                continue

        return Response({
            "doctors": doctor_list,
            "selected_doctor": selected_doctor_id,
            "selected_doctor_name": selected_doctor_name,
            "kpis": kpis,
            "income_breakdown": income_breakdown,
            "monthly_trend": monthly_trend,
            "recent_patients": recent_patients
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
