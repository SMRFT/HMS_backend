from djongo import models
from ...models import AuditModel

class InsuranceClaim(AuditModel):
    claim_id = models.CharField(max_length=50, primary_key=True)
    uhid = models.CharField(max_length=50)
    ip_number = models.CharField(max_length=50)
    
    # Claim Details
    policy_no = models.CharField(max_length=100, blank=True, null=True)
    policy_date = models.DateField(blank=True, null=True)
    insurance_id = models.CharField(max_length=100, blank=True, null=True)
    insurance_company = models.CharField(max_length=255, blank=True, null=True)
    
    estimate_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    approved_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    approved_date = models.DateField(blank=True, null=True)
    claim_date = models.DateField(auto_now_add=True)
    
    # Status: Approved, Rejected, Pending
    claim_status = models.CharField(max_length=20, default='Pending')
    
    # Ward info
    patient_ward = models.CharField(max_length=100, blank=True, null=True)
    
    remarks = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Claim {self.claim_id} - {self.uhid}"

    def save(self, *args, **kwargs):
        if not self.claim_id:
            from django.utils.timezone import now
            prefix = now().strftime('%Y%m%d')
            last = InsuranceClaim.objects.filter(claim_id__startswith=f"CLM{prefix}").order_by('-claim_id').first()
            if last:
                try:
                    last_num = int(last.claim_id[-4:])
                    new_num = last_num + 1
                except:
                    new_num = 1
            else:
                new_num = 1
            self.claim_id = f"CLM{prefix}{new_num:04d}"
        super().save(*args, **kwargs)
