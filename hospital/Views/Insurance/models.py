from djongo import models
from ...models import AuditModel
from django.utils import timezone

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


class InsuranceMember(AuditModel):
    member_number = models.CharField(max_length=50, primary_key=True)
    uhid = models.CharField(max_length=50, blank=True, null=True)
    
    # Name details
    member_first_name = models.CharField(max_length=100, blank=True, null=True)
    member_middle_name = models.CharField(max_length=100, blank=True, null=True)
    member_last_name = models.CharField(max_length=100, blank=True, null=True)
    member_name = models.CharField(max_length=200, blank=True, null=True)
    
    guardian = models.CharField(max_length=150, blank=True, null=True)
    member_address_1 = models.TextField(blank=True, null=True)
    member_address_2 = models.TextField(blank=True, null=True)
    member_address_3 = models.TextField(blank=True, null=True)
    area = models.CharField(max_length=100, blank=True, null=True)
    member_phone = models.CharField(max_length=30, blank=True, null=True)
    
    # Demographics
    member_sex = models.CharField(max_length=20, default='MALE')
    member_age = models.IntegerField(default=0, blank=True, null=True)
    member_age_type = models.CharField(max_length=20, default='YEARS')
    member_dob = models.DateField(blank=True, null=True)
    
    # Insurance / Scheme Info
    parent_polyclinic = models.CharField(max_length=100, blank=True, null=True)
    insurance_type = models.CharField(max_length=100, default='001')
    scheme_category = models.CharField(max_length=100, blank=True, null=True)
    scheme_subcategory = models.CharField(max_length=100, blank=True, null=True)
    card_no = models.CharField(max_length=100, blank=True, null=True)
    echs_card = models.CharField(max_length=100, blank=True, null=True)
    smart_card = models.CharField(max_length=100, blank=True, null=True)
    
    # Military / Official info
    referral_number = models.CharField(max_length=100, blank=True, null=True)
    rank = models.CharField(max_length=100, blank=True, null=True)
    esm_rank = models.CharField(max_length=100, blank=True, null=True)
    service_number = models.CharField(max_length=100, blank=True, null=True)
    class_type = models.CharField(max_length=100, blank=True, null=True)
    regiment = models.CharField(max_length=100, blank=True, null=True)
    
    # Policy Financial Details
    policy_number = models.CharField(max_length=100, blank=True, null=True)
    date_of_commencement = models.DateField(blank=True, null=True)
    date_of_expiry = models.DateField(blank=True, null=True)
    proposer = models.CharField(max_length=150, blank=True, null=True)
    serial_number = models.CharField(max_length=50, blank=True, null=True)
    insured_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    premium_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    amount_collected = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    registration_date = models.DateField(blank=True, null=True)
    registration_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Other references
    nominee = models.CharField(max_length=150, blank=True, null=True)
    nominee_relation = models.CharField(max_length=100, blank=True, null=True)
    promoter = models.CharField(max_length=150, blank=True, null=True)
    receipt = models.CharField(max_length=100, blank=True, null=True)
    prev_policy = models.CharField(max_length=100, blank=True, null=True)
    
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.member_number} - {self.member_name or self.member_first_name}"

    def save(self, *args, **kwargs):
        if not self.member_name:
            parts = [p for p in [self.member_first_name, self.member_middle_name, self.member_last_name] if p]
            self.member_name = " ".join(parts) if parts else self.member_number
        if not self.echs_card and self.card_no:
            self.echs_card = self.card_no
        super().save(*args, **kwargs)


class InsuranceMemberDependent(AuditModel):
    member_number = models.CharField(max_length=50)
    dependent_sl_no = models.IntegerField(default=1)
    dependent_name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=50, default='Self')
    dob = models.DateField(blank=True, null=True)
    age = models.IntegerField(default=0, blank=True, null=True)
    gender = models.CharField(max_length=20, default='MALE')
    card_no = models.CharField(max_length=100, blank=True, null=True)
    uhid = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.member_number} - {self.dependent_name} ({self.relationship})"


class InsuranceMemberVisit(AuditModel):
    member_visit_reference = models.CharField(max_length=50, primary_key=True)
    member_number = models.CharField(max_length=50)
    patient_name = models.CharField(max_length=150, blank=True, null=True)
    dependent_sl_no = models.IntegerField(default=1)
    relationship = models.CharField(max_length=50, default='Self', blank=True, null=True)
    uhid = models.CharField(max_length=50, blank=True, null=True)
    age = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, null=True)
    
    parent_polyclinic = models.CharField(max_length=100, blank=True, null=True)
    visit_date = models.DateField(default=timezone.now)
    visit_time = models.CharField(max_length=30, blank=True, null=True)
    opd_registration_number = models.CharField(max_length=50, blank=True, null=True)
    opd_registration_date = models.DateField(blank=True, null=True)
    referral_number = models.CharField(max_length=100, blank=True, null=True)
    date_of_referral = models.DateField(blank=True, null=True)
    valid_upto = models.DateField(blank=True, null=True)
    consulting_doctor = models.CharField(max_length=100, blank=True, null=True)
    referred_polyclinic = models.CharField(max_length=100, blank=True, null=True)
    referred_doctor = models.CharField(max_length=100, blank=True, null=True)
    service_number = models.CharField(max_length=100, blank=True, null=True)
    
    provisional_diagnosis = models.TextField(blank=True, null=True)
    brief_clinical_notes = models.TextField(blank=True, null=True)
    
    admission = models.BooleanField(default=False)
    investigation = models.BooleanField(default=False)
    consultation = models.BooleanField(default=False)
    specified_services = models.BooleanField(default=False)
    services = models.BooleanField(default=False)
    
    advice = models.TextField(blank=True, null=True)
    sh_discharge = models.TextField(blank=True, null=True)
    bill_number = models.CharField(max_length=50, blank=True, null=True)
    sh_bill_type = models.CharField(max_length=50, blank=True, null=True)
    sh_company_code = models.CharField(max_length=50, blank=True, null=True)
    sh_payment_code = models.CharField(max_length=50, blank=True, null=True)
    sh = models.CharField(max_length=50, blank=True, null=True)
    
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Visit {self.member_visit_reference} - {self.member_number}"
