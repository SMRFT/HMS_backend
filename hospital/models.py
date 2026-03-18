from django.db import models
from django.utils import timezone
from django.utils.timezone import now
from bson import ObjectId
from decimal import Decimal
from datetime import datetime

class AuditModel(models.Model):
    hospital_code = models.CharField(max_length=100, null=True, blank=True, default="SH001")
    # branch_code = models.CharField(max_length=100, null=True, blank=True)
    # department_code = models.CharField(max_length=100, null=True, blank=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_date = models.DateTimeField(null=True, blank=True)
    lastmodified_by = models.CharField(max_length=100, null=True, blank=True)
    lastmodified_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        now = datetime.utcnow()

        if not self.created_date:
            self.created_date = now

        self.lastmodified_date = now

        super().save(*args, **kwargs)


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
    

class PharmacyStock(AuditModel):

    stock_id = models.IntegerField(primary_key=True)

    department_code = models.CharField(max_length=20)
    item_id = models.IntegerField()
    batch_number = models.CharField(max_length=50)

    expiry_date = models.DateField(null=True, blank=True)

    mrp = models.DecimalField(max_digits=10, decimal_places=2)

    grn_number = models.CharField(max_length=50)

    total_stock = models.IntegerField()

    sold_quantity = models.IntegerField(default=0)
    transferred_out_quantity = models.IntegerField(default=0)

    stock_type = models.CharField(max_length=50, default="grn")
    stock_ref_id = models.IntegerField(default=0)

    grn_return_quantity = models.IntegerField(default=0)
    grn_return_ref_id = models.IntegerField(null=True, blank=True)

    blocked_quantity = models.IntegerField(default=0)

    sales_return_quantity = models.IntegerField(default=0)
    sales_return_ref_id = models.IntegerField(null=True, blank=True)

    CGST_Percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    SGST_Percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    CGST_Amt = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    SGST_Amt = models.DecimalField(max_digits=10, decimal_places=2, default=0)


    def save(self, *args, **kwargs):

        if not self.stock_id:

            while True:
                last = PharmacyStock.objects.order_by("-stock_id").first()
                next_id = (last.stock_id + 1) if last else 1

                if not PharmacyStock.objects.filter(stock_id=next_id).exists():
                    self.stock_id = next_id
                    break

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.stock_id} - {self.item_id}"

class Vendor(AuditModel):
    vendor_id = models.CharField(primary_key=True,max_length=10)
    supplier_type = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    address_line1 = models.CharField(max_length=300)
    address_line2 = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    payment_terms = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.vendor_id:
            last = Vendor.objects.all()
            max_id = 0
            for v in last:
                if v.vendor_id and v.vendor_id.isdigit():
                    max_id = max(max_id, int(v.vendor_id))
            self.vendor_id = str(max_id + 1)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


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
    room_status = models.CharField(max_length=20, default="Available")
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    bill_number = models.CharField(max_length=50, unique=True, blank=True)
    billed_date = models.DateTimeField(auto_now_add=True)

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

class Admission(AuditModel):
    uhid                = models.CharField(max_length=20)
    ipNumber            = models.CharField(max_length=20, unique=True)
    ipserial_number     = models.CharField(max_length=50, blank=True, null=True)
    admissionDateTime   = models.DateTimeField(default=timezone.now)
    admittingDoctor     = models.CharField(max_length=100)           
    consultingDoctor    = models.CharField(max_length=100, blank=True, null=True)  
    packageName         = models.CharField(max_length=100, blank=True, null=True)
    room_details        = models.JSONField(default=list)
    roomShitingDetails  = models.JSONField(default=list, blank=True, null=True)
    reasonForAdmission  = models.TextField(blank=True, null=True)

    # Stores each advance payment as a list of objects:
    # [{ bill_number, amount, payment_mode, remarks, paid_date, type, created_by }]
    advance_payments    = models.JSONField(default=list, blank=True, null=True)

    # ── MLC ────────────────────────────────────────────────────────────────
    mlc_type            = models.CharField(max_length=50, blank=True, null=True)
    mlc_doc             = models.CharField(max_length=200, blank=True, null=True)
    mlc_remarks         = models.TextField(blank=True, null=True)

    # ── Flags ──────────────────────────────────────────────────────────────
    is_advanceActive    = models.BooleanField(default=False)
    is_admissionActive  = models.BooleanField(default=True)
    is_discharged       = models.BooleanField(default=False)

    class Meta:
        ordering = ['-admissionDateTime']

    def __str__(self):
        return f"{self.uhid} | {self.ipNumber}"

class DischargeBilling(AuditModel):
    # ── Identity ──────────────────────────────────────────────────────────────
    status          = models.CharField(max_length=20, db_index=True)
    estimate_number = models.CharField(max_length=60, blank=True, null=True, unique=True)
    bill_no         = models.CharField(max_length=60, blank=True, null=True, unique=True)

    # ── Patient Reference (no FK — same pattern as investbilling) ─────────────
    uhid            = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    ip_number       = models.CharField(max_length=50, blank=True, null=True, db_index=True)

    # ── Bill Date (auto today from backend) ───────────────────────────────────
    bill_date       = models.DateField(default=timezone.now)

    # ── Items stored as JSON array ────────────────────────────────────────────
    # Each item: { investigation_id, itemName, category, quantity, rate, discount, amount, doctor, doctor_fee, item_description }
    items           = models.JSONField(default=list)

    # ── Financial Summary ─────────────────────────────────────────────────────
    total_amount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)   # gross before discount
    advance_amount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sales_return      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    medicines_amount  = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    taxable_amount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    non_tax_amount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    gst_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    room_tax          = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    discount_percent  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    disc_reason       = models.CharField(max_length=300, blank=True, null=True)
    item_disc         = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_disc        = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    net_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0)   

    remarks           = models.TextField(blank=True, null=True)

    # ── Estimate→Bill traceability ────────────────────────────────────────────
    converted_from_id = models.IntegerField(blank=True, null=True)   # pk of original estimate
    is_active         = models.BooleanField(default=True)

    def __str__(self):
        ref = self.bill_no if self.status == "Billed" else self.estimate_number
        return f"{self.uhid or self.ip_number} | {ref} | {self.status}"

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
    

class CTReport(AuditModel):
    date = models.DateField()
    time = models.CharField(max_length=50)
    patientId = models.CharField(max_length=50)
    patientName = models.CharField(max_length=100)
    age = models.IntegerField()
    gender = models.CharField(max_length=10)
    investigation = models.CharField(max_length=100)
    impression = models.TextField()
    approve = models.BooleanField(default=False)  # Boolean field for approval status
    approve_time = models.DateTimeField(null=True, blank=True)  # DateTime field for approval time

    def __str__(self):
        return f"CT Report - {self.patientName} ({self.patientId})"


# Define MRI Report model
class MRIReport(AuditModel):
    patientId = models.CharField(max_length=255)
    patientName = models.CharField(max_length=255)
    age = models.IntegerField()
    gender = models.CharField(max_length=50)
    investigation = models.TextField()
    impression = models.TextField()
    approve = models.BooleanField(default=False)
    approve_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.patientName
    

# Define USG Report model
class USGReport(AuditModel):
    patientId = models.CharField(max_length=255)
    patientName = models.CharField(max_length=255)
    age = models.IntegerField()
    gender = models.CharField(max_length=50)
    investigation = models.TextField()
    impression = models.TextField()
    approve = models.BooleanField(default=False)
    approve_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.patientName


# Define XRay Report model
class XRayReport(AuditModel):
    patientId = models.CharField(max_length=255)
    patientName = models.CharField(max_length=255)
    age = models.IntegerField()
    gender = models.CharField(max_length=50)
    investigation = models.TextField()
    impression = models.TextField()
    approve = models.BooleanField(default=False)
    approve_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.patientName


class Summary(AuditModel):
    date = models.DateTimeField(null=True, blank=True)
    ipNo = models.CharField(max_length=100, blank=True, null=True)
    uhid = models.CharField(max_length=100, blank=True, null=True)
    patient = models.CharField(max_length=100, blank=True, null=True)
    doa = models.CharField(max_length=100, blank=True, null=True)
    dod = models.CharField(max_length=100, blank=True, null=True)
    roomNo = models.CharField(max_length=100, blank=True, null=True)
    age = models.CharField(max_length=100, blank=True, null=True)
    surgeryDate = models.CharField(max_length=100, blank=True, null=True)
    nextReviewDate = models.CharField(max_length=100, blank=True, null=True)
    doctor = models.CharField(max_length=100, blank=True, null=True)
    gender = models.CharField(max_length=20, blank=True, null=True)
    summaryType = models.CharField(max_length=100, blank=True, null=True)
    heading = models.CharField(max_length=200, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
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
    EstBillDate = models.CharField(max_length=50)
    time = models.CharField(max_length=50)
    uhid = models.CharField(max_length=50)
    ipNumber = models.CharField(max_length=50,blank=True)
    billType = models.CharField(max_length=100)
    doctor = models.CharField(max_length=100)    
    salutation = models.CharField(max_length=10)
    firstName = models.CharField(max_length=50)
    lastName = models.CharField(max_length=50,blank=True)
    age = models.IntegerField()
    gender = models.CharField(max_length=10)
    item = models.JSONField()  # Stores the selected item as a JSON field
    referredBy = models.CharField(max_length=100, blank=True, null=True)
    discountPercent = models.IntegerField()
    discount = models.DecimalField(max_digits=10,blank=True, decimal_places=2, default=0.0)
    discountRemarks = models.TextField(blank=True, null=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    finalPrice = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    paymentMethod = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)


    def __str__(self):
        return f"Billing for {self.firstName} {self.lastName} ({self.uhid})"


class InvestBilling(AuditModel):
    investBillNo = models.CharField(max_length=50)
    investBillDate = models.CharField(max_length=50)
    time = models.CharField(max_length=50)
    uhid = models.CharField(max_length=50)
    ipNumber = models.CharField(max_length=50,blank=True)
    salutation = models.CharField(max_length=10)
    firstName = models.CharField(max_length=50)
    middleName = models.CharField(max_length=50, blank=True, null=True)
    lastName = models.CharField(max_length=50)
    age = models.IntegerField()
    gender = models.CharField(max_length=10)
    doctor = models.CharField(max_length=100)
    billType = models.CharField(max_length=100)
    item = models.JSONField()  # Stores the selected item as a JSON field
    referredBy = models.CharField(max_length=100, blank=True, null=True)
    discountPercent = models.IntegerField()
    discount = models.DecimalField(max_digits=10,blank=True, decimal_places=2, default=0.0)
    discountRemarks = models.TextField(blank=True, null=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    finalPrice = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    paymentMethod = models.CharField(max_length=50)

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


class OPPharmacyBill(AuditModel):
    patient_name=models.CharField(max_length=200)
    bill_no = models.CharField(max_length=50)
    bill_date = models.CharField(max_length=20)
    op_number = models.CharField(max_length=50)
    inpatient_number = models.CharField(max_length=50, blank=True, null=True)
    patient_name = models.CharField(max_length=100)
    doctor = models.CharField(max_length=100)
    room_no = models.CharField(max_length=20, blank=True, null=True)
    medicine_name = models.JSONField()
    net_amount = models.FloatField(default=0)

    def __str__(self):
        return f"Bill {self.bill_no} - {self.patient_name}"