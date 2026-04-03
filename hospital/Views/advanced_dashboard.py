from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
import calendar
from django.db.models import Sum, Count
from ..models import Patient, Billing, Admission, GRN, Room

@api_view(['GET'])
def advanced_dashboard_stats(request):
    try:
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

        # 1. KPIs
        total_op = Patient.objects.count() # Approximation for total OP lifetime
        total_ip = Admission.objects.count()
        
        # Avoid Djongo aggregate error for Decimal128 by summing values manually
        total_income = 0
        for fee in Billing.objects.values_list('total_fees', flat=True):
            if fee:
                total_income += float(str(fee))

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        today_ip = Admission.objects.filter(admissionDateTime__range=(today_start, today_end)).count()
        today_visits = Billing.objects.filter(billed_date__range=(today_start, today_end)).count()
        today_op = max(0, today_visits - today_ip)

        today_discharge = DischargeDetail.objects.filter(discharge_date=now.date()).count()

        kpis = {
            "total_op": total_op,
            "total_ip": total_ip,
            "total_income": float(total_income),
            "today_ip": today_ip,
            "today_op": today_op,
            "today_discharge": today_discharge
        }

        # 2. Monthly OP/IP & Income/Expense
        num_days = calendar.monthrange(year, month)[1]
        monthly_op_ip = []
        monthly_income_expense = []

        # Get all records for the month to avoid N+1 queries
        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = now.replace(year=year, month=month, day=num_days, hour=23, minute=59, second=59, microsecond=999999)

        admissions = list(Admission.objects.filter(admissionDateTime__range=(month_start, month_end)))
        billings = list(Billing.objects.filter(billed_date__range=(month_start, month_end)))
        grns = list(GRN.objects.filter(created_date__range=(month_start, month_end)))

        for day in range(1, num_days + 1):
            day_start = now.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

            # OP/IP
            day_admissions = [a for a in admissions if day_start <= a.admissionDateTime <= day_end]
            day_billings = [b for b in billings if day_start <= b.billed_date <= day_end]
            
            d_ip = len(day_admissions)
            d_visits = len(day_billings)
            d_op = max(0, d_visits - d_ip)

            monthly_op_ip.append({
                "day": day,
                "OP": d_op,
                "IP": d_ip
            })

            # Income/Expense
            day_income = sum([float(str(b.total_fees or 0)) for b in day_billings])
            day_grns = [g for g in grns if day_start <= g.created_date <= day_end]
            day_expense = sum([float(str(g.net_invoice_amount or 0)) for g in day_grns])

            monthly_income_expense.append({
                "day": day,
                "Income": day_income,
                "Expense": day_expense
            })

        # 3. Today's Income by Method
        today_billings = [b for b in billings if today_start <= b.billed_date <= today_end]
        income_methods = {}
        for b in today_billings:
            method = b.payment_method or "Unknown"
            if not method.strip(): method = "Unknown"
            income_methods[method] = income_methods.get(method, 0) + float(str(b.total_fees or 0))
        
        todays_income_method = [{"method": k, "amount": v} for k, v in income_methods.items()]

        # 4. Doctor-wise OP/IP (Today)
        doctor_stats = {}
        # IP from admissions
        today_admissions = [a for a in admissions if today_start <= a.admissionDateTime <= today_end]
        for a in today_admissions:
            doc = a.consultingDoctor or a.admittingDoctor or "Unknown"
            if not doc.strip(): doc = "Unknown"
            if doc not in doctor_stats: doctor_stats[doc] = {"OP": 0, "IP": 0, "Amount": 0.0}
            doctor_stats[doc]["IP"] += 1

        # OP from billings
        for b in today_billings:
            doc = b.doctor_id or "Unknown"
            if not doc.strip(): doc = "Unknown"
            if doc not in doctor_stats: doctor_stats[doc] = {"OP": 0, "IP": 0, "Amount": 0.0}
            doctor_stats[doc]["OP"] += 1
            doctor_stats[doc]["Amount"] += float(str(b.consulting_fee or 0))
        
        doctor_wise = [{"name": k, "OP": v["OP"], "IP": v["IP"], "Amount": v["Amount"]} for k, v in doctor_stats.items() if k != "Unknown"]
        # Limit to top 10 for UI
        doctor_wise = sorted(doctor_wise, key=lambda x: x["OP"] + x["IP"], reverse=True)[:10]

        # 5. Bed Occupancy
        total_beds = sum([c for c in Room.objects.values_list('capacity', flat=True) if c])
        discharged_uhids = set(DischargeDetail.objects.values_list('uhid_no', flat=True))
        occupied_beds = Admission.objects.exclude(uhid__in=discharged_uhids).count()
        vacant_beds = max(0, total_beds - occupied_beds)

        bed_occupancy = [
            {"name": "Occupied", "value": occupied_beds},
            {"name": "Vacant", "value": vacant_beds}
        ]

        return Response({
            "kpis": kpis,
            "monthly_op_ip": monthly_op_ip,
            "monthly_income_expense": monthly_income_expense,
            "todays_income_method": todays_income_method,
            "doctor_wise": doctor_wise,
            "bed_occupancy": bed_occupancy
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
