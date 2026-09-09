from django.db import models
from django.utils.timezone import now
from django.utils import timezone
from ...models import AuditModel, RawJSONField



class registration360(AuditModel):
    date              = models.DateField(default=timezone.now)
    bill_number       =  models.CharField(max_length=50, blank=True, null=True)
    patient_name      =  models.CharField(max_length=255, blank=True, null=True)
    mobile_number    = models.CharField(max_length=20, blank=True, null=True)
    doctor_name       = RawJSONField(default=list, blank=True, null=True)
    staff_name       = models.CharField(max_length=255, blank=True, null=True)
    medicine_name     = RawJSONField(default=list, blank=True, null=True)
    total_amount     = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    doctor_fees        = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    staff_nurse_fees   = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    doctor_staff_fees_remaining = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    medicine_charge    = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    hospital_amount     = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    service_list          = RawJSONField(default=list, blank=True, null=True)
    transportation_mode   = models.CharField(max_length=100, blank=True, null=True)
    test_name             = RawJSONField(default=list, blank=True, null=True)
    reference_id    =  models.CharField(max_length=50, blank=True, null=True) 
    order_id        =  models.CharField(max_length=50, blank=True, null=True) 
    
    
    
    

    
   

    
    