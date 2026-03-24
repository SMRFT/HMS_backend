from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from ..models import Patient, Billing

@api_view(['GET'])
def dashboard_stats(request):
    try:
        # 1. Overall Totals (Lifetime)
        total_registered_patients = Patient.objects.count()

        # 2. Today's Stats
        now = timezone.now()
        # Set start and end of today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Using range avoids specific database functions that might be missing in some backends (like Djongo)
        today_new_patients = Patient.objects.filter(
            created_date__gte=today_start,
            created_date__lte=today_end
        ).count()

        today_total_billings = Billing.objects.filter(
            billed_date__gte=today_start,
            billed_date__lte=today_end
        ).count()

        # Renewal = Visits - New Registrations (approximate for today)
        today_renewals = max(0, today_total_billings - today_new_patients)

        # 3. Chart Data (Last 7 Days)
        seven_days_ago = now - timedelta(days=6)
        seven_days_start = seven_days_ago.replace(hour=0, minute=0, second=0, microsecond=0)

        # Fetch raw data for Python-side processing to avoid DB aggregation issues
        
        # Get all created_at dates for patients in the last 7 days
        # We explicitly cast to list to evaluate queryset
        new_patients_dates = list(Patient.objects.filter(
            created_date__gte=seven_days_start
        ).values_list('created_date', flat=True))

        # Get all billed_date dates for billings in the last 7 days
        billings_dates = list(Billing.objects.filter(
            billed_date__gte=seven_days_start
        ).values_list('billed_date', flat=True))

        # Process in Python
        new_patients_map = {}
        for dt in new_patients_dates:
            if dt:
                # Convert to local date string YYYY-MM-DD
                d_str = timezone.localtime(dt).strftime('%Y-%m-%d')
                new_patients_map[d_str] = new_patients_map.get(d_str, 0) + 1

        billings_map = {}
        for dt in billings_dates:
            if dt:
                d_str = timezone.localtime(dt).strftime('%Y-%m-%d')
                billings_map[d_str] = billings_map.get(d_str, 0) + 1

        # Construct final chart data
        chart_data = []
        for i in range(7):
            date_cursor = seven_days_start + timedelta(days=i)
            str_date = date_cursor.strftime('%Y-%m-%d')
            display_date = date_cursor.strftime('%d %b')

            count_new = new_patients_map.get(str_date, 0)
            count_bill = billings_map.get(str_date, 0)
            
            # Logic: Total Visits = New + Renewals -> Renewals = Total - New
            count_renew = max(0, count_bill - count_new)

            chart_data.append({
                "date": display_date,
                "New Patients": count_new,
                "Renewals": count_renew,
                "Total Visits": count_bill
            })

        return Response({
            "total_registered_patients": total_registered_patients,
            "today_new_patients": today_new_patients,
            "today_renewals": today_renewals,
            "today_total_visits": today_total_billings,
            "chart_data": chart_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
