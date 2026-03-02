from django.db import models
from django.utils import timezone
from django.utils.timezone import now
from bson import ObjectId
from decimal import Decimal
from datetime import datetime

class AuditModel(models.Model):
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_date = models.DateTimeField(null=True, blank=True)
    lastmodified_by = models.CharField(max_length=100, null=True, blank=True)
    lastmodified_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

class TempPatientRegistration(models.Model):
    session_id = models.CharField(max_length=100, unique=True)
    data = models.TextField() # Storing JSON data as string
    created_at = models.DateTimeField(auto_now_add=True)
    is_consumed = models.BooleanField(default=False)

    def __str__(self):
        return f"Temp Reg: {self.session_id}"


        if not self.created_date:
            self.created_date = now

        self.lastmodified_date = now

        super().save(*args, **kwargs)

class HSNCode(AuditModel):
    chapter = models.CharField(max_length=50)
    hsn_code = models.CharField(max_length=10, unique=True, primary_key=True)
    description = models.TextField()
    tax = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return f"{self.chapter} - {self.hsn_code}"

class PharmacyItem(AuditModel):
    item_id = models.IntegerField(primary_key=True)
    item_first_name = models.CharField(max_length=200)
    item_last_name = models.CharField(max_length=200, blank=True)
    group = models.CharField(max_length=50)
    category = models.CharField(max_length=50)
    classification = models.CharField(max_length=100)
    hsn = models.CharField(max_length=50, blank=True)
    dosage = models.CharField(max_length=20,blank=True)
    shelf_no = models.CharField(max_length=50, blank=True)
    rack_no = models.CharField(max_length=50, blank=True)
    high_risk = models.BooleanField(default=False)
    look_alike = models.BooleanField(default=False)
    sound_alike = models.BooleanField(default=False)
    reorder_level = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.item_id is None:
            last = PharmacyItem.objects.order_by("-item_id").first()
            self.item_id = (last.item_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_first_name} {self.item_last_name}"

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

    grn_id = models.IntegerField(primary_key=True)

    # Header fields
    purchase_category = models.CharField(max_length=50)
    vendor_id = models.IntegerField()
    vendor_name = models.CharField(max_length=200, blank=True, default="")
    supplier_address = models.CharField(max_length=400, blank=True, default="")
    contact_person = models.CharField(max_length=150, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")

    invoice_no = models.CharField(max_length=100)
    invoice_date = models.DateField()
    date = models.DateField()
    payment_mode = models.CharField(max_length=20)

    # Items stored as JSON string
    items = models.TextField(default="[]")

    # Financial summary
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    non_taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_paid_to_supplier = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        if self.grn_id is None:
            last = GRN.objects.order_by("-grn_id").first()
            self.grn_id = (last.grn_id + 1) if last else 1
        if not self.grn_id:
            self.grn_id = f"GRN{str(self.grn_id).zfill(6)}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.grn_id
    
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
    uhid = models.CharField(max_length=20)
    ipNumber = models.CharField(max_length=20)
    salutation = models.CharField(max_length=10, blank=True)
    firstName = models.CharField(max_length=50)
    middleName = models.CharField(max_length=50, blank=True)
    lastName = models.CharField(max_length=50)
    age = models.IntegerField()
    gender = models.CharField(max_length=10)
    admissionDate = models.DateField()
    time = models.TimeField()
    customerType = models.CharField(max_length=20, default='General')
    admittingDoctor = models.CharField(max_length=100)
    consultingDoctor = models.CharField(max_length=100, blank=True)
    roomNo = models.CharField(max_length=10)
    bedNo = models.CharField(max_length=10)
    extensionNumber = models.CharField(max_length=10, blank=True)
    callRelease = models.CharField(max_length=10, default='Local')
    nursingStation = models.CharField(max_length=50, blank=True)
    presentComplaints = models.TextField(blank=True)
    reasonForAdmission = models.TextField(blank=True)
    admissionFee = models.DecimalField(max_digits=10, decimal_places=2)
    creditLimit = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    mlcType = models.CharField(max_length=20, blank=True)
    mlcRemarks = models.TextField(blank=True)
    uploadMLCDoc = models.FileField(upload_to='mlc_docs/', blank=True, null=True)
    passAlertToAuthority = models.BooleanField(default=False)
    birthTime = models.CharField(max_length=10, blank=True, null=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    mothersUHIDNo = models.CharField(max_length=20, blank=True)
    pediatricianResponsible = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.firstName} {self.lastName} ({self.uhid})"

    def save(self, *args, **kwargs):
        if not self.ipNumber:
            # Logic for IP26/00001
            from datetime import date
            today = date.today()
            year_part = today.strftime("%y") # e.g. 26
            prefix = f"IP{year_part}/"
            
            # Find last admission with this prefix
            last_admission = Admission.objects.filter(ipNumber__startswith=prefix).order_by('-ipNumber').first()
            
            if last_admission:
                try:
                    last_num = int(last_admission.ipNumber.split('/')[-1])
                    next_num = last_num + 1
                except ValueError:
                    next_num = 1
            else:
                next_num = 1
            
            self.ipNumber = f"{prefix}{str(next_num).zfill(5)}"
        
        super().save(*args, **kwargs)

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


from django.db import models
from django.utils.timezone import now

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
        current_year = now().year

        # Generate UHID if not already set
        if not self.uhid:
            # Get the last UHID for the current year
            last_patient = Patient.objects.filter(uhid__startswith=f"S0{current_year}").order_by('-uhid').first()
            if last_patient and last_patient.uhid:
                # Extract the last number from UHID
                last_number = int(last_patient.uhid.split('/')[-1])
            else:
                last_number = 0
            next_number = last_number + 1
            self.uhid = f"S0{current_year}/{next_number:06d}"

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