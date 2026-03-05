
from datetime import datetime, time
from django.utils import timezone
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Billing, Patient, Doctor

@api_view(['GET'])
def patient_registration_stats(request):
    try:
        from_date_str = request.GET.get('fromDate')
        to_date_str = request.GET.get('toDate')
        doctor_id = request.GET.get('doctorId')

        # Get current date for defaults
        today = timezone.now().date()

        if from_date_str:
             from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        else:
             from_date = today

        if to_date_str:
             to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        else:
             to_date = today
        
        # Combine with min/max time for range
        start_dt = timezone.make_aware(datetime.combine(from_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(to_date, time.max))

        # Base filter for Bills
        bill_filter = Q(billed_date__range=(start_dt, end_dt))
        
        if doctor_id:
            bill_filter &= Q(doctor_id=doctor_id)
            
        bills = Billing.objects.filter(bill_filter).select_related('patient')
        
        total_visits = bills.count()
        new_visit_count = 0
        existing_visit_count = 0
        
        for bill in bills:
            # Check if patient created in the query range
            # Note: patient.created_at is a DateTimeField.
            p_created = bill.patient.created_at
            if not timezone.is_aware(p_created):
                p_created = timezone.make_aware(p_created)
                
            # If patient was created within the range of the filter, consider it "New Visit" in this context
            # Or simplified: if patient created on the SAME DAY as the bill?
            # User likely wants "New Patients" count vs "Review Patients" count.
            # A patient created today is New. A patient created yesterday coming today is Review.
            # So compare bill date with patient creation date?
            # Let's stick to: If patient.created_at >= start_dt, it's a new registration in this period.
            
            if p_created >= start_dt:
                 new_visit_count += 1
            else:
                 existing_visit_count += 1
                 
        return Response({
            "new_visit": new_visit_count,
            "existing_visit": existing_visit_count,
            "total_visit": total_visits
        })

    except Exception as e:
        print(f"Error in stats: {e}")
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
def patient_visit_list(request):
    try:
        from_date_str = request.GET.get('fromDate')
        to_date_str = request.GET.get('toDate')
        doctor_id = request.GET.get('doctorId')

        today = timezone.now().date()

        if from_date_str:
             from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        else:
             from_date = today

        if to_date_str:
             to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        else:
             to_date = today
        
        start_dt = timezone.make_aware(datetime.combine(from_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(to_date, time.max))

        bill_filter = Q(billed_date__range=(start_dt, end_dt))
        if doctor_id:
            bill_filter &= Q(doctor_id=doctor_id)

        bills = Billing.objects.filter(bill_filter).select_related('patient').order_by('-billed_date')
        
        data = []
        for bill in bills:
            p_created = bill.patient.created_at
            if not timezone.is_aware(p_created):
                p_created = timezone.make_aware(p_created)

            visit_type = "New" if p_created >= start_dt else "Review"

            # Try to resolve doctor name if doctor_id is just an ID
            doctor_name = bill.doctor_id
            # Optionally fetch doctor name if needed, assuming doctor_id is name or ID
            
            data.append({
                "uhid": bill.patient.uhid,
                "patientName": f"{bill.patient.firstName} {bill.patient.lastName}",
                "age": bill.patient.age,
                "gender": bill.patient.gender,
                "mobile": bill.patient.mobilePhone,
                "doctor": doctor_name,
                "visitType": visit_type,
                "billAmount": bill.total_fees,
                "paymentStatus": bill.payment_status,
                "date": bill.billed_date.strftime("%d-%m-%Y %H:%M")
            })
            
        return Response(data)
        
    except Exception as e:
        print(f"Error in visit list: {e}")
        return Response({"error": str(e)}, status=500)
