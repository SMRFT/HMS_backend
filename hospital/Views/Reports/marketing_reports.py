from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.http import JsonResponse
from django.db.models import Count, Sum
from ...models import Patient, Billing
from datetime import datetime, timedelta
import pytz

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission]) 
def marketing_area_zipcode_report(request):
    try:
        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')

        if not from_date_str or not to_date_str:
            return JsonResponse({'error': 'from_date and to_date are required'}, status=400)

        # Assuming the date format is YYYY-MM-DD
        try:
            from_dt = datetime.strptime(from_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
            to_dt = datetime.strptime(to_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            
            # Localize to IST if needed, for now just use simple filtering
            if from_dt.tzinfo is None:
                from_dt = pytz.utc.localize(from_dt)
                to_dt = pytz.utc.localize(to_dt)
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

        # Base patient query based on created_date (or registration date)
        patients_qs = Patient.objects.filter(created_date__gte=from_dt, created_date__lte=to_dt)
        
        hospital_code = request.data.get('auth-hospital-code', '')
        if hospital_code and hospital_code != 'system':
            patients_qs = patients_qs.filter(hospital_code=hospital_code)

        # Aggregate by area and zipcode
        aggregation = patients_qs.values('area', 'zipcode').annotate(
            patient_count=Count('uhid')
        ).order_by('-patient_count')

        result_data = []
        for item in aggregation:
            area = item.get('area') or 'Unknown'
            zipcode = item.get('zipcode') or 'Unknown'
            
            # Filter billings for these specific patients in the area/zipcode
            # This is an approximation of revenue for this cohort
            # For a more exact revenue report, one would aggregate directly on Billing 
            patients_in_area = patients_qs.filter(area=item.get('area'), zipcode=item.get('zipcode'))
            
            patients_list = []
            area_total_revenue = 0.0
            
            for p in patients_in_area:
                # Calculate revenue for this specific patient
                patient_billings = Billing.objects.filter(patient=p).values_list('total_fees', flat=True)
                p_revenue = sum(float(str(fee)) for fee in patient_billings if fee is not None)
                area_total_revenue += p_revenue
                
                patients_list.append({
                    'uhid': p.uhid,
                    'name': f"{p.firstName or ''} {p.lastName or ''}".strip(),
                    'phone': p.mobilePhone,
                    'age': p.age,
                    'gender': p.gender,
                    'revenue': round(p_revenue, 2)
                })

            result_data.append({
                'area': area,
                'zipcode': zipcode,
                'patient_count': item['patient_count'],
                'total_revenue': round(area_total_revenue, 2),
                'patients': patients_list
            })

        return JsonResponse({'data': result_data}, status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)
