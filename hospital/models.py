from djongo import models
from django.db import transaction
from django.db.models import Max
import re
from django.utils import timezone
from django.utils.timezone import now

# Base Audit Model
class AuditModel(models.Model):
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_date = models.DateTimeField(default=timezone.now)
    lastmodified_by = models.CharField(max_length=100, null=True, blank=True)
    lastmodified_date = models.DateTimeField(auto_now=True)
    branch_code = models.CharField(max_length=100, null=True, blank=True)
    outlet_code = models.CharField(max_length=100, null=True, blank=True)
    hospital_code = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.created_date:
            self.created_date = timezone.now()

        self.lastmodified_date = timezone.now()

        super().save(*args, **kwargs)

class Patient(AuditModel):
    GENDER_CHOICES = (
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    )

    CUSTOMER_TYPE_CHOICES = (
        ('General', 'General'),
        ('Insurance', 'Insurance'),
        ('Corporate', 'Corporate'),
        ('Employee', 'Employee'),
        ('Staff', 'Staff'),
        ('Family', 'Family'),
    )

    company_code = models.CharField(max_length=100, blank=True, null=True)

    BLOOD_GROUP_CHOICES = (
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
    )

    uhid = models.CharField(max_length=20)
    ip_number = models.CharField(max_length=20, blank=True, null=True)
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE_CHOICES, default='General')
    registration_date =models.CharField(max_length=100, blank=True, null=True)
    salutation = models.CharField(max_length=10, blank=True, null=True)
    firstName = models.CharField(max_length=100)
    lastName = models.CharField(max_length=100)
    dob = models.DateField()
    age = models.IntegerField()
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    permanent_address = models.TextField(blank=True, null=True)
    area = models.CharField(max_length=100, blank=True, null=True)
    zipcode = models.CharField(max_length=10, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    mobilePhone = models.CharField(max_length=15)
    home_phone = models.CharField(max_length=15, blank=True, null=True)
    blood_group =models.CharField(max_length=20, blank=True, null=True)
    spouse_name = models.CharField(max_length=100, blank=True, null=True)

    # Referred fields
    referredBy = models.CharField(max_length=100, blank=True, null=True)
    referred_doctor_phone = models.CharField(max_length=15, blank=True, null=True)
    doctorName = models.CharField(max_length=100, blank=True, null=True)

    # Emergency Contact
    emergency_contact = models.CharField(max_length=15, blank=True, null=True)

    # MLC fields
    mlc_type = models.CharField(max_length=50, blank=True, null=True)
    mlc_doc = models.CharField(max_length=100, blank=True, null=True)
    mlc_remarks = models.TextField(blank=True, null=True)
    pass_alert_to_authority =models.CharField(max_length=100, blank=True, null=True)

    # New Born fields

    # New Born fields
    birth_time = models.CharField(max_length=100, blank=True, null=True)
    birth_time_am_pm = models.CharField(max_length=20, blank=True, null=True, default='AM')
    weight = models.CharField(max_length=100, blank=True, null=True)
    mothers_uhid_no = models.CharField(max_length=20, blank=True, null=True)
    pediatrician_responsible = models.CharField(max_length=100, blank=True, null=True)

    # Additional fields
    is_cross_consultation = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.firstName} {self.lastName} ({self.uhid})"

    def save(self, *args, **kwargs):
        current_year = now().year % 100   # get last 2 digits (2026 -> 26)

        if not self.uhid:
            prefix = f"S0{current_year}"

            # get last patient of the year
            last_patient = Patient.objects.filter(
                uhid__startswith=prefix
            ).order_by('-uhid').first()

            if last_patient and last_patient.uhid:
                last_number = int(last_patient.uhid.split('/')[-1])
            else:
                last_number = 0

            next_number = last_number + 1

            self.uhid = f"{prefix}/{next_number:07d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.firstName} {self.lastName}" if self.firstName else "Unnamed Patient"


class Billing(AuditModel):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="billings")
    registration_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    consulting_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_fees = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    doctor_id = models.CharField(max_length=50, blank=True, null=True)
    bill_number = models.CharField(max_length=50, unique=True, blank=True ,primary_key=True)
    billed_date = models.DateTimeField(auto_now_add=True)
    payment_status = models.CharField(max_length=20, default='Pending', choices=[('Paid', 'Paid'), ('Pending', 'Pending'), ('Unpaid', 'Unpaid')])
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    paid_date = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.bill_number:
            date_prefix = now().strftime('%Y%m%d')
            pattern = f"{date_prefix}/"
            
            # Find the last bill that matches the current date pattern
            last_bill = Billing.objects.filter(bill_number__startswith=pattern).order_by('-bill_number').first()
            
            if last_bill and last_bill.bill_number:
                try:
                    # Extract the sequence number (dates matching)
                    last_number = int(last_bill.bill_number.split('/')[-1])
                except (ValueError, IndexError):
                    last_number = 0
            else:
                last_number = 0
                
            next_number = last_number + 1
            self.bill_number = f"{pattern}{next_number:04d}"
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Billing {self.bill_number} for {self.patient.uhid} - {self.total_fees}"
class TempPatientRegistration(models.Model):
    session_id = models.CharField(max_length=100, unique=True)
    data = models.TextField() # Storing JSON data as string
    created_at = models.DateTimeField(auto_now_add=True)
    is_consumed = models.BooleanField(default=False)

    def __str__(self):
        return f"Temp Reg: {self.session_id}"
class Vendor(AuditModel):
    VENDOR_TYPE_CHOICES = [
        ('SUPPLIER', 'Supplier'),
        ('MANUFACTURER', 'Manufacturer'),
        ('BOTH', 'Both'),
    ]

    vendor_id = models.CharField(max_length=10, unique=True, primary_key=True)
    vendor_type = models.CharField(max_length=20, choices=VENDOR_TYPE_CHOICES)
    name = models.CharField(max_length=255)
    address_line_1 = models.CharField(max_length=255, null=True, blank=True)
    address_line_2 = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    pincode = models.CharField(max_length=10, null=True, blank=True)
    
    # Contact Information
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    url = models.URLField(max_length=255, null=True, blank=True)
    
    # Additional Fields
    kgst_tin_number = models.CharField(max_length=100, null=True, blank=True)
    gstin = models.CharField(max_length=20, null=True, blank=True)
    payment = models.CharField(max_length=50, null=True, blank=True)
    terms = models.TextField(null=True, blank=True)
    credit_period = models.CharField(max_length=20, null=True, blank=True)
    export_data_code = models.CharField(max_length=100, null=True, blank=True)
    tds_percent = models.CharField(max_length=10, null=True, blank=True)
    igst_supplier = models.BooleanField(default=False)
    blacklisted_supplier = models.BooleanField(default=False)
    account_on_hold = models.BooleanField(default=False)
    reason_for_holding = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.vendor_id:
            try:
                # Get all vendor IDs, find the max numerical one
                vendors = Vendor.objects.all()
                max_id = 0
                for v in vendors:
                    if v.vendor_id and str(v.vendor_id).isdigit():
                        max_id = max(max_id, int(v.vendor_id))
                self.vendor_id = str(max_id + 1)
            except Exception:
                self.vendor_id = "1"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.vendor_id})"
class PharmacyCategory(AuditModel):
    category_id = models.IntegerField(primary_key=True)
    category_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.category_id is None:
            last = PharmacyCategory.objects.order_by('-category_id').first()
            self.category_id = (last.category_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.category_name

class PharmacyItem(AuditModel):
    item_id = models.IntegerField(primary_key=True)
    item_name = models.CharField(max_length=200)
    item_last_name = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=50)
    hsn = models.CharField(max_length=50, blank=True)
    high_risk = models.BooleanField(default=False)
    look_alike = models.BooleanField(default=False)
    sound_alike = models.BooleanField(default=False)
    reorder_level = models.IntegerField(default=0)
    IP_shelf_no = models.CharField(max_length=50, blank=True)
    IP_rack_no = models.CharField(max_length=50, blank=True)
    OP_shelf_no = models.CharField(max_length=50, blank=True)
    OP_rack_no = models.CharField(max_length=50, blank=True)
    G_shelf_no = models.CharField(max_length=50, blank=True)
    G_rack_no = models.CharField(max_length=50, blank=True)
    IP_available = models.BooleanField(default=False)
    OP_available = models.BooleanField(default=False)
    G_available = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    blocked_reason = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):

        # Auto generate item_id
        if self.item_id is None:
            last = PharmacyItem.objects.order_by("-item_id").first()
            self.item_id = (last.item_id + 1) if last else 1

        # Auto generate HSN
        if not self.hsn:
            last_item = PharmacyItem.objects.exclude(hsn="").order_by("-hsn").first()

            if last_item and last_item.hsn.isdigit():
                next_hsn = int(last_item.hsn) + 1
            else:
                next_hsn = 1

            self.hsn = str(next_hsn).zfill(5)  # 00001 format

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_id} {self.item_name}"
    
# Correctly using djongo models below
from django.utils import timezone

class PharmacyBilling(AuditModel):

    Bill_id = models.IntegerField(primary_key=True)
    bill_no = models.CharField(max_length=50, blank=True, null=True)
    estimate_no = models.CharField(max_length=50, blank=True, null=True)
    bill_date = models.DateTimeField(blank=True, null=True)
    uhid = models.CharField(max_length=50)
    inpatient_number = models.CharField(max_length=50, blank=True, null=True)
    bill_type = models.IntegerField(max_length=200, blank=True, null=True)
    doctor_id = models.CharField(max_length=50, blank=True, null=True)
    room_no = models.CharField(max_length=20, blank=True, null=True)
    medicine_particulars = models.JSONField(default=list)
    total_amount = models.FloatField(default=0)
    overall_discount_type = models.CharField(
        max_length=10,
        default="percent"
    )
    overall_discount_value = models.FloatField(default=0)
    overall_discount_amount = models.FloatField(default=0)
    net_amount = models.FloatField(default=0)
    billing_status = models.CharField(max_length=20)
    billing_mode = models.CharField(max_length=20)
    payment_details = models.JSONField(null=True, blank=True)
    Esimated_id=models.CharField(max_length=150)
    Edit_reason = models.TextField(null=True, blank=True)
    Edited_by =models.CharField(max_length=150)
    is_deleted= models.BooleanField(default=False)
    delete_reason = models.TextField(null=True, blank=True)
    deleted_by =models.CharField(max_length=150)
    round_off= models.IntegerField(default=0)
    cashier_id = models.CharField(max_length=50, blank=True, null=True)
    is_ward_request = models.BooleanField(default=False)
    ward_request_date = models.DateTimeField(blank=True, null=True)
    payment_mode = models.CharField(max_length=100, blank=True, null=True)

    # :white_check_mark: AUTO-INCREMENT LOGIC
    def save(self, *args, **kwargs):
        if not self.Bill_id:
            last = PharmacyBilling.objects.order_by('-Bill_id').first()
            self.Bill_id = (last.Bill_id + 1) if last else 1

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.billing_status} - {self.patient_name}"


        
class PharmacyStock(AuditModel):
    stock_id                 = models.AutoField(primary_key=True)
    department_code          = models.CharField(max_length=20)
    item_id                  = models.IntegerField()
    batch_number             = models.CharField(max_length=50)       
    expiry_date              = models.CharField(max_length=50)
    mrp                      = models.DecimalField(max_digits=10, decimal_places=2)
    grn_number               = models.CharField(max_length=50)
    total_stock              = models.IntegerField()
    sold_quantity            = models.IntegerField(default=0)
    transferred_out_quantity = models.IntegerField(default=0)
    stock_type               = models.CharField(max_length=50, default="grn")
    stock_ref_id             = models.IntegerField(default=0)        
    grn_return_quantity      = models.IntegerField(default=0)
    grn_return_ref_id        = models.IntegerField(null=True, blank=True)
    blocked_quantity         = models.IntegerField(default=0)
    sales_return_quantity    = models.IntegerField(default=0)
    sales_return_ref_id      = models.IntegerField(null=True, blank=True)
    CGST_Percentage          = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    SGST_Percentage          = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    CGST_Amt                 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    SGST_Amt                 = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.grn_number} | {self.item_id} | batch:{self.batch_number}"

# GRN Model
class GRN(AuditModel):
    CATEGORY_PREFIX = {
        "MEDICINE_PURCHASE":    "OP",
        "MEDICINE_PURCHASE_IP": "IP",
        "OPENING_STOCK_DRUG":   "OSD",
    }

    draft_number        = models.CharField(max_length=50, primary_key=True)
    grn_number          = models.CharField(max_length=50, unique=True, blank=True)

    date                = models.DateTimeField()
    purchase_category   = models.CharField(max_length=50)
    vendor_id           = models.IntegerField()
    grn_type            = models.CharField(max_length=20, default="INVOICE")
    invoice_no          = models.CharField(max_length=100)
    invoice_date        = models.DateTimeField()
    payment_mode        = models.CharField(max_length=20)
    items               = models.TextField(default="[]")
    taxable_amount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    non_taxable_amount  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst                = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst                = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst                = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_paid_to_supplier= models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_discount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True, null=True)
    total_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_invoice_amount  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status      = models.TextField(default="[]")
    remarks             = models.TextField(blank=True, default="")
    status              = models.CharField(max_length=50, default="Draft")

    def __str__(self):
        return self.grn_number or self.draft_number
    
    # Additional Fields
    kgst_tin_number = models.CharField(max_length=100, null=True, blank=True)
    gstin = models.CharField(max_length=20, null=True, blank=True)
    payment = models.CharField(max_length=50, null=True, blank=True)
    terms = models.TextField(null=True, blank=True)
    credit_period = models.CharField(max_length=20, null=True, blank=True)
    export_data_code = models.CharField(max_length=100, null=True, blank=True)
    tds_percent = models.CharField(max_length=10, null=True, blank=True)
    igst_supplier = models.BooleanField(default=False)
    blacklisted_supplier = models.BooleanField(default=False)
    account_on_hold = models.BooleanField(default=False)
    reason_for_holding = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.vendor_id:
            try:
                # Get all vendor IDs, find the max numerical one
                vendors = Vendor.objects.all()
                max_id = 0
                for v in vendors:
                    if v.vendor_id and str(v.vendor_id).isdigit():
                        max_id = max(max_id, int(v.vendor_id))
                self.vendor_id = str(max_id + 1)
            except Exception:
                self.vendor_id = "1"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.vendor_id})"


class Block(AuditModel):
    block_id = models.IntegerField(primary_key=True)
    block_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.block_id is None:
            last = Block.objects.order_by('-block_id').first()
            self.block_id = (last.block_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.block_name

class RoomCategory(AuditModel):
    room_category_id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.room_category_id is None:
            last = RoomCategory.objects.order_by('-room_category_id').first()
            self.room_category_id = (last.room_category_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Room(AuditModel):
    room_number = models.CharField(max_length=10, primary_key=True)
    description = models.TextField(blank=True)
    room_category = models.CharField(max_length=100)         
    block = models.CharField(max_length=100)                 
    floor = models.IntegerField()
    room_type = models.CharField(max_length=20)
    phone_extension = models.CharField(max_length=10, blank=True)
    nursing_station = models.CharField(max_length=50, blank=True)
    capacity = models.IntegerField(default=1)                
    occupancy = models.IntegerField(default=0)               
    admission_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    room_advance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    room_status = models.CharField(max_length=20)
    room_blocked = models.BooleanField(default=False)
    blocked_reason = models.TextField(blank=True)
    include_in_final_bill = models.BooleanField(default=True)
    enable_luxury_tax = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    services = models.JSONField(default=list, blank=True)
    beds = models.JSONField(default=list, blank=True)
    room_kits = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.room_number

    def save(self, *args, **kwargs):
        # Ensure JSON fields are lists if not set
        if self.services is None:
            self.services = []
        if self.beds is None:
            self.beds = []
        if self.room_kits is None:
            self.room_kits = []
        super().save(*args, **kwargs)


class Admission(AuditModel):
    uhid                = models.CharField(max_length=20)
    ipNumber            = models.CharField(max_length=10, primary_key=True)
    ipserial_number     = models.IntegerField(blank=True, null=True)   # ✅ change to IntegerField

    admissionDateTime   = models.DateTimeField(default=timezone.now)
    admittingDoctor     = models.CharField(max_length=100)           
    consultingDoctor    = models.CharField(max_length=100, blank=True, null=True)  
    packageName         = models.CharField(max_length=100, blank=True, null=True)

    room_details        = models.JSONField(default=list)
    roomShitingDetails  = models.JSONField(default=list, blank=True, null=True)
    reasonForAdmission  = models.TextField(blank=True, null=True)

    advance_payments    = models.JSONField(default=list, blank=True, null=True)

    mlc_type            = models.CharField(max_length=50, blank=True, null=True)
    mlc_doc             = models.CharField(max_length=200, blank=True, null=True)
    mlc_remarks         = models.TextField(blank=True, null=True)

    is_admissionActive  = models.BooleanField(default=True)
    is_discharged       = models.BooleanField(default=False)
    is_admitted         = models.BooleanField(default=True)

    class Meta:
        ordering = ['-admissionDateTime']

    def save(self, *args, **kwargs):

        # 🔥 AUTO GENERATE SERIAL NUMBER
        if not self.ipserial_number:

            last_admission = Admission.objects.filter(
                uhid=self.uhid
            ).order_by('-ipserial_number').first()

            if last_admission and last_admission.ipserial_number:
                self.ipserial_number = last_admission.ipserial_number + 1
            else:
                self.ipserial_number = 1

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.uhid} | {self.ipNumber}"

class DischargeDetail(AuditModel):
    uhid_no = models.CharField(max_length=100, blank=True)
    ip_number = models.CharField(max_length=100, blank=True)
    discharge_date = models.DateField(null=True, blank=True)
    discharge_time = models.TimeField(null=True, blank=True)
    free_visits = models.CharField(max_length=100, blank=True)
    other_consultants = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=50, blank=True)
    patient_expired = models.BooleanField(default=False)
    date_of_death = models.DateField(null=True, blank=True)
    time_of_death = models.TimeField(null=True, blank=True)
    discharge_reason = models.TextField(blank=True)


    def __str__(self):
        return f"{self.uhid_no} - {self.status}"





    

class Doctor(AuditModel):
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')])
    marital_status = models.CharField(max_length=20, choices=[('Single', 'Single'), ('Married', 'Married')])
    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True, null=True)
    address_line_3 = models.CharField(max_length=255, blank=True, null=True)
    area = models.CharField(max_length=100)
    pin = models.CharField(max_length=10)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15)
    designation = models.CharField(max_length=100)
    department = models.CharField(max_length=100)
    registration_fee = models.DecimalField(max_digits=10, decimal_places=2)
    consulting_fee = models.DecimalField(max_digits=10, decimal_places=2)
    renewal_fee = models.DecimalField(max_digits=10, decimal_places=2)
    consultation_start_time = models.TimeField()
    consultation_end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    

class RadiologyReport(AuditModel):
    date = models.DateTimeField()
    slot_DateTime = models.DateTimeField()
    investBillNo = models.CharField(max_length=50, blank=True)
    billTypeNo = models.TextField()    
    itemName = models.TextField()
    impression = models.TextField()    
    is_approved = models.BooleanField(default=False)
    approved_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)   # ✅ add this

    def __str__(self):
        return f"Radiology Report - {self.investBillNo} ({self.uhid})"


class Summary(AuditModel):
    date = models.DateField(null=True, blank=True)
    ipNo = models.CharField(max_length=100, blank=True, null=True)
    uhid = models.CharField(max_length=100, blank=True, null=True)
    doa = models.DateField(null=True, blank=True)
    dod = models.DateField(null=True, blank=True)
    dodTime = models.TimeField(null=True, blank=True)
    doaTime = models.TimeField(null=True, blank=True)
    roomNo = models.CharField(max_length=100, blank=True, null=True)   
    surgeryDate = models.DateField(null=True, blank=True)
    nextReviewDate = models.DateField(null=True, blank=True)
    doctor = models.CharField(max_length=100, blank=True, null=True)
    summaryType = models.CharField(max_length=100, blank=True, null=True)
    heading = models.CharField(max_length=200, blank=True, null=True)
    diseaseCode = models.CharField(max_length=100, blank=True, null=True)
    disease = models.CharField(max_length=200, blank=True, null=True)
    fieldsData = models.JSONField(blank=True, null=True)  # To store dynamic field data
    approve = models.BooleanField(default=False)
    approve_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)


    def __str__(self):
        return self.patient or "Summary"
    
    
class EstimateBilling(AuditModel):
    EstBillNo = models.CharField(max_length=50, blank=True)
    EstBillDate = models.DateTimeField() 
    uhid = models.CharField(max_length=50)
    ipNumber = models.CharField(max_length=50,blank=True)
    bill_type       = models.CharField(max_length=100, blank=True, null=True)  # collection / category key
    billTypeNo      = models.CharField(max_length=50, blank=True, null=True)
    doctor = models.CharField(max_length=100)     
    referredBy = models.CharField(max_length=100, blank=True, null=True)
    item = models.JSONField()  # Stores the selected item as a JSON field
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    discountPercent = models.IntegerField()
    discount = models.DecimalField(max_digits=10,blank=True, decimal_places=2, default=0.0)
    discountRemarks = models.TextField(blank=True, null=True)
    finalPrice = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    paymentMethod = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)


    def __str__(self):
        return f"Billing for {self.firstName} {self.lastName} ({self.uhid})"
    

class ReferenceDoctor(AuditModel):
    doctor = models.CharField(max_length=255)
    qualification = models.CharField(max_length=255, blank=True, null=True)
    mobile1 = models.CharField(max_length=15, blank=True, null=True)
    mobile2 = models.CharField(max_length=15, blank=True, null=True)
    area = models.CharField(max_length=255, blank=True, null=True)
    clinic_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    clinic_address = models.JSONField(default=list)  # Store as JSON list
    clinic_phone = models.CharField(max_length=15, blank=True, null=True)
    resi_address = models.JSONField(default=list)  # Store as JSON list
    resi_phone = models.CharField(max_length=15, blank=True, null=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.doctor


class Log(AuditModel):
    LOG_TYPE_CHOICES = [
        ('INFO', 'INFO'),
        ('WARNING', 'WARNING'),
        ('ERROR', 'ERROR'),
    ]
    log_type = models.CharField(max_length=10, choices=LOG_TYPE_CHOICES)
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.log_type} - {self.message}"



class InsuranceProvider(AuditModel):
    company_name = models.CharField(max_length=255)
    company_code = models.CharField(max_length=100,primary_key=True)
    address_line_1 = models.CharField(max_length=255, null=True, blank=True)
    address_line_2 = models.CharField(max_length=255, null=True, blank=True)
    address_line_3 = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    pincode = models.CharField(max_length=20, null=True, blank=True)
    gstin = models.CharField(max_length=50, null=True, blank=True)
    contact_person = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    mobile = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    insurance_print_format = models.CharField(max_length=100, null=True, blank=True)
    claim_pre_authorization_template = models.FileField(upload_to='insurance_templates/', null=True, blank=True)
    blocked = models.BooleanField(default=False)
    blocking_reason = models.TextField(null=True, blank=True)
    enable_service_tax = models.BooleanField(default=False)

    def __str__(self):
        return self.company_name


class VelavanInvoice(AuditModel):
    # GRN number
    grn_number = models.CharField(max_length=50, unique=True, blank=True)
    # Vendor fields
    vendor_id = models.CharField(max_length=255, blank=True, null=True) 
    # Invoice / Date fields
    date = models.DateField()
    invoice_no = models.CharField(max_length=100)
    invoice_date = models.DateField()
    payment_mode = models.CharField(max_length=50, blank=True, null=True)

    # Patient / Surgery details (hospital-specific)
    ip_number = models.CharField(max_length=100, blank=True, null=True)
    patient_name = models.CharField(max_length=255, blank=True, null=True)
    surgeon_name = models.CharField(max_length=255, blank=True, null=True)

    # Items stored as JSON
    items = models.JSONField(default=list, blank=True)

    # Summary fields
    non_taxable_amount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    taxable_amount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    tax_paid_to_supplier = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    local_tax = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    remarks = models.TextField(blank=True, null=True)
    cgst = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    sgst = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    igst = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    cess = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    central_sales_tax = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    round_amount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    total_discount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    net_invoice_amount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    quotation_rate = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)

    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f"{self.grn_number} - {self.vendor_id}"

    @staticmethod
    def get_financial_year_prefix():
        today = timezone.now().date()
        if today.month >= 4:
            return f"{today.year % 100}{(today.year + 1) % 100}"
        else:
            return f"{(today.year - 1) % 100}{today.year % 100}"

    @staticmethod
    def generate_grn_number():
        with transaction.atomic():
            current_fy_prefix = VelavanInvoice.get_financial_year_prefix()
            prefix = f"V{current_fy_prefix}"  # → "V2526"
            
            last_record = VelavanInvoice.objects.filter(
                grn_number__startswith=f"{prefix}/"
            ).order_by('-grn_number').first()

            if last_record:
                last_sequence = int(last_record.grn_number.split('/')[1])
                next_sequence = last_sequence + 1
            else:
                next_sequence = 1

            return f"{prefix}/{next_sequence:05d}"  # 5 digits → V2526/00001

    def save(self, *args, **kwargs):
        if not self.pk and not self.grn_number:
            self.grn_number = self.generate_grn_number()
        if self.pk:
            self.lastmodified_date = timezone.now()
        super().save(*args, **kwargs)


class VelavanVendors(AuditModel):
    vendor_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    name = models.CharField(max_length=255)
    addressLine1 = models.CharField(max_length=255)
    addressLine2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=20, blank=True, null=True)
    contactPerson = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    kgstTinNumber = models.CharField(max_length=50, blank=True, null=True)
    gstin = models.CharField(max_length=50)
    payment = models.CharField(max_length=50, blank=True, null=True)
    tdsPercent = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'hospital_velavan_vendors'

    def __str__(self):
        return self.name

    def generate_vendor_id(self):
        """Generate auto-incrementing vendor_id starting from 1"""
        with transaction.atomic():
            try:
                # Get all vendors and find the maximum numeric vendor_id
                all_vendors = VelavanVendors.objects.filter(vendor_id__isnull=False).values_list('vendor_id', flat=True)
                
                max_id = 0
                for vendor_id in all_vendors:
                    try:
                        numeric_id = int(vendor_id)
                        if numeric_id > max_id:
                            max_id = numeric_id
                    except (ValueError, TypeError):
                        continue
                
                new_id = max_id + 1
                
                # Ensure uniqueness
                while VelavanVendors.objects.filter(vendor_id=str(new_id)).exists():
                    new_id += 1
                
                return str(new_id)
                
            except Exception as e:
                # Fallback: return "1" if there's any issue
                return "1"

    def save(self, *args, **kwargs):
        try:
            # Generate vendor_id if it's a new record and vendor_id is not provided
            if not self.pk and not self.vendor_id:
                self.vendor_id = self.generate_vendor_id()
            
            if self.pk:  # If updating existing record
                self.lastmodified_date = timezone.now()
            
            super().save(*args, **kwargs)
            
        except Exception as e:
            # Log the specific error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error saving vendor: {str(e)}")
            raise e  # Re-raise the exception



class VelavanItems(AuditModel):
    itemName = models.CharField(max_length=255)
    hsn = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'hospital_velavan_items'
    def __str__(self):
        return self.itemName



from django.db import models

class Cashcountershiftdetails(AuditModel):

    shiftno = models.CharField(primary_key=True,max_length=100000)

    CashierID      = models.CharField(max_length=100)
    CashCounter    = models.CharField(max_length=100)

    OpeningBalance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ClosingBalance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    ShiftStatus    = models.CharField(max_length=50, default="active")

    StartingTime   = models.DateTimeField()
    closingTime    = models.DateTimeField(null=True, blank=True)

    

    is_active      = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.CashierID} - {self.CashCounter}"