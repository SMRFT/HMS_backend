from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
import calendar
from ..models import Patient, Billing, Admission, DischargeDetail, Doctor

@api_view(['GET'])
def doctor_dashboard_stats(request):
    try:
        doctor_name_param = request.GET.get('doctor_name')
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

        # Get all distinct doctors from Billing and Admission dynamically
        doctor_names = set()
        for doc in Admission.objects.values_list('consultingDoctor', flat=True).distinct():
            if doc and str(doc).strip(): doctor_names.add(str(doc).strip())
                
        for doc in Admission.objects.values_list('admittingDoctor', flat=True).distinct():
            if doc and str(doc).strip(): doctor_names.add(str(doc).strip())
                
        for doc in Billing.objects.values_list('doctor_id', flat=True).distinct():
            if doc and str(doc).strip(): doctor_names.add(str(doc).strip())

        doctor_names = sorted(list(doctor_names))
        doctor_list = [{"id": name, "name": name} for name in doctor_names]

        if not doctor_list:
            doctor_list = [{"id": "Unknown", "name": "Unknown"}]

        # Default to the first doctor if none is selected
        selected_doctor_name = doctor_name_param if doctor_name_param else doctor_list[0]['name']

        # Time ranges
        num_days = calendar.monthrange(year, month)[1]
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = now.replace(year=year, month=month, day=num_days, hour=23, minute=59, second=59, microsecond=999999)

        # 1. Doctor KPIs
        # For simplicity, we match by doctor name string in Billing/Admission since that's how it's stored
        # Total OP (Lifetime) - derived from Billings where doctor_id matches name or id
        # Wait, how is doctor_id stored in Billing? Let's check Billing
        total_op = Billing.objects.filter(doctor_id=selected_doctor_name).count()
        total_ip = Admission.objects.filter(consultingDoctor=selected_doctor_name).count() + Admission.objects.filter(admittingDoctor=selected_doctor_name).count()

        monthly_billings = list(Billing.objects.filter(doctor_id=selected_doctor_name, billed_date__range=(month_start, month_end)))
        monthly_admissions = list(Admission.objects.filter(admissionDateTime__range=(month_start, month_end)))
        
        # Filter admissions for this doctor
        doctor_monthly_admissions = [a for a in monthly_admissions if a.consultingDoctor == selected_doctor_name or a.admittingDoctor == selected_doctor_name]

        # Calculate Income
        total_income = sum([float(str(b.consulting_fee or b.total_fees or 0)) for b in monthly_billings])
        
        today_op = len([b for b in monthly_billings if today_start <= b.billed_date <= today_end])
        today_ip = len([a for a in doctor_monthly_admissions if today_start <= a.admissionDateTime <= today_end])

        kpis = {
            "total_op": total_op,
            "total_ip": total_ip,
            "monthly_income": float(total_income),
            "today_op": today_op,
            "today_ip": today_ip
        }

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
            "selected_doctor": selected_doctor_name,
            "kpis": kpis,
            "monthly_trend": monthly_trend,
            "recent_patients": recent_patients
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
