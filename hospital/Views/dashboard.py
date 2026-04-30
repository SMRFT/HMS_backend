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

def ensure_aware(dt):
    if dt is None: return None
    if not timezone.is_aware(dt):
        return timezone.make_aware(dt)
    return dt

@api_view(['GET'])
def dashboard_stats(request):
    try:
        # Use India Standard Time (IST)
        tz = pytz.timezone('Asia/Kolkata')
        now = timezone.now().astimezone(tz)
        
        # 1. Overall Totals
        total_registered_patients = mongo_db["hospital_patient"].count_documents({})

        # 2. Today's Boundaries (Local IST)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Convert boundaries to UTC for Mongo comparison if dates are stored in UTC
        # Usually Djongo stores as UTC
        today_start_utc = today_start.astimezone(pytz.UTC)
        today_end_utc = today_end.astimezone(pytz.UTC)

        today_new_patients = mongo_db["hospital_patient"].count_documents({
            "created_date": {"$gte": today_start_utc, "$lte": today_end_utc}
        })

        today_total_billings = mongo_db["hospital_billing"].count_documents({
            "billed_date": {"$gte": today_start_utc, "$lte": today_end_utc}
        })

        today_renewals = max(0, today_total_billings - today_new_patients)

        # 3. Chart Data (Last 7 Days)
        chart_data = []
        for i in range(6, -1, -1):
            day_local = today_start - timedelta(days=i)
            day_end_local = day_local.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            d_start = day_local.astimezone(pytz.UTC)
            d_end = day_end_local.astimezone(pytz.UTC)

            count_new = mongo_db["hospital_patient"].count_documents({
                "created_date": {"$gte": d_start, "$lte": d_end}
            })
            count_bill = mongo_db["hospital_billing"].count_documents({
                "billed_date": {"$gte": d_start, "$lte": d_end}
            })
            
            chart_data.append({
                "date": day_local.strftime('%d %b'),
                "New Patients": count_new,
                "Renewals": max(0, count_bill - count_new),
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
        print(f"Dashboard Stats Error: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
