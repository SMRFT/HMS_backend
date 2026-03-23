from django.db import models, transaction
from django.utils import timezone
from django.utils.timezone import now

# Base Audit Model
class AuditModel(models.Model):
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_date = models.DateTimeField(default=now)
    lastmodified_by = models.CharField(max_length=100, null=True, blank=True)
    lastmodified_date = models.DateTimeField(auto_now=True)
    branch_code = models.CharField(max_length=100, null=True, blank=True)
    department_code = models.CharField(max_length=100, null=True, blank=True)
    hospital_code = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        abstract = True

# IP Pharmacy Stock Model
class IPPharmacyStock(AuditModel):
    ip_stock_id = models.CharField(max_length=10, unique=True)
    medicine_name = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=100)
    hsn_code = models.CharField(max_length=100, null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    purchase_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    mrp = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    cgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    sgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_quantity = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        if not self.ip_stock_id:
            try:
                stocks = IPPharmacyStock.objects.all()
                max_id = 0
                for s in stocks:
                    if s.ip_stock_id and str(s.ip_stock_id).isdigit():
                        max_id = max(max_id, int(s.ip_stock_id))
                self.ip_stock_id = str(max_id + 1)
            except Exception:
                self.ip_stock_id = "1"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.medicine_name} ({self.ip_stock_id})"


# OP Pharmacy Stock Model
class OPPharmacyStock(AuditModel):
    op_stock_id = models.CharField(max_length=10, unique=True)
    medicine_name = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=100)
    hsn_code = models.CharField(max_length=100, null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    purchase_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    mrp = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    cgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    sgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_quantity = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        if not self.op_stock_id:
            try:
                stocks = OPPharmacyStock.objects.all()
                max_id = 0
                for s in stocks:
                    if s.op_stock_id and str(s.op_stock_id).isdigit():
                        max_id = max(max_id, int(s.op_stock_id))
                self.op_stock_id = str(max_id + 1)
            except Exception:
                self.op_stock_id = "1"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.medicine_name} ({self.op_stock_id})"


# Vendor/Supplier Model
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


# IP GRN Model
class IPGRN(AuditModel):
    grn_number = models.CharField(max_length=50, unique=True)
    vendor_id = models.CharField(max_length=50) # References Vendor.vendor_id
    date = models.DateField()
    invoice_no = models.CharField(max_length=50)
    invoice_date = models.DateField()
    credit_period = models.CharField(max_length=100, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    payment_mode = models.CharField(max_length=50, null=True, blank=True)
    purchase_category = models.CharField(max_length=50, default="IP PHARMACY")
    
    # Financial Summary
    taxable_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    non_taxable_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    tax_paid_to_supplier = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    cgst = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    sgst = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    igst = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    cess = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    central_sales_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    local_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    round_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    net_invoice_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    total_discount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    tax_on_free_items = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    quotation_rate = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    courier_transport_charge = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    
    # JSON Fields (Stored as Text/JSON in MongoDB)
    items = models.TextField() # Array of item objects
    payment_status = models.TextField(null=True, blank=True) # Array of payment tracking
    total_amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    remarks = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.grn_number:
            try:
                # Logic for 2526/000001
                from datetime import date
                year_part = date.today().strftime("%y")
                next_year = str(int(year_part) + 1)
                prefix = f"{year_part}{next_year}/"
                
                last_grn = IPGRN.objects.filter(grn_number__startswith=prefix).order_by('-grn_number').first()
                if last_grn:
                    last_num = int(last_grn.grn_number.split('/')[-1])
                    self.grn_number = f"{prefix}{str(last_num + 1).zfill(6)}"
                else:
                    self.grn_number = f"{prefix}000001"
            except Exception:
                self.grn_number = "GRN-IP-1"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.grn_number} - {self.invoice_no}"


# OP GRN Model
class OPGRN(AuditModel):
    grn_number = models.CharField(max_length=50, unique=True)
    vendor_id = models.CharField(max_length=50)
    date = models.DateField()
    invoice_no = models.CharField(max_length=50)
    invoice_date = models.DateField()
    credit_period = models.CharField(max_length=100, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    payment_mode = models.CharField(max_length=50, null=True, blank=True)
    purchase_category = models.CharField(max_length=50, default="OP PHARMACY")
    
    # Financial Summary
    taxable_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    non_taxable_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    tax_paid_to_supplier = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    cgst = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    sgst = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    igst = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    cess = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    central_sales_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    local_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    round_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    net_invoice_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    total_discount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    tax_on_free_items = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    quotation_rate = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    courier_transport_charge = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    
    # JSON Fields
    items = models.TextField()
    payment_status = models.TextField(null=True, blank=True)
    total_amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    remarks = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.grn_number:
            try:
                from datetime import date
                year_part = date.today().strftime("%y")
                next_year = str(int(year_part) + 1)
                prefix = f"{year_part}{next_year}/"
                
                last_grn = OPGRN.objects.filter(grn_number__startswith=prefix).order_by('-grn_number').first()
                if last_grn:
                    last_num = int(last_grn.grn_number.split('/')[-1])
                    self.grn_number = f"{prefix}{str(last_num + 1).zfill(6)}"
                else:
                    self.grn_number = f"{prefix}000001"
            except Exception:
                self.grn_number = "GRN-OP-1"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.grn_number} - {self.invoice_no}"


class Admission(AuditModel):
    uhid = models.CharField(max_length=20)
    ipNumber = models.CharField(max_length=20)
    admissionDateTime = models.DateTimeField()
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


class Block(AuditModel):
    block_id = models.CharField(max_length=10, unique=True, blank=True)
    block_name = models.CharField(max_length=100)

    def save(self, *args, **kwargs):
        if not self.block_id:
            last_block = Block.objects.order_by('id').last()
            if last_block and last_block.block_id:
                try:
                    last_number = int(last_block.block_id.replace("B", ""))
                    self.block_id = f"B{last_number + 1}"
                except ValueError:
                    self.block_id = "B1"
            else:
                self.block_id = "B1"
        super(Block, self).save(*args, **kwargs)

    def __str__(self):
        return self.block_name


class RoomCategory(AuditModel):
    ward_name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.ward_name


class Room(AuditModel):
    NURSING_STATIONS = [
        ("MICU", "MICU"),
        ("SICU", "SICU"),
        ("General", "General"),
        # Add more as needed or make dynamic
    ]

    ROOM_TYPES = [
        ("ICU", "ICU"),
        ("CCU", "CCU"),
        ("ICCU", "ICCU"),
        ("NICU", "NICU"),
        ("CASUALITY", "CASUALITY"),
        ("WARD", "WARD"),
        ("OTHERS", "OTHERS"),
    ]

    room_number = models.CharField(max_length=10, unique=True)
    description = models.TextField(blank=True)
    room_category = models.CharField(max_length=100) # Fetched from RoomCategory
    block = models.CharField(max_length=100) # Fetched from Block
    floor = models.IntegerField()
    phone_extension = models.CharField(max_length=10, blank=True)
    nursing_station = models.CharField(max_length=50, choices=NURSING_STATIONS, blank=True)
    capacity = models.IntegerField(default=1) # Total beds
    admission_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    room_advance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES, default="WARD")

    def __str__(self):
        return self.room_number


class Bed(AuditModel):
    BED_STATUS = [
        ("Available", "Available"),
        ("Occupied", "Occupied"),
        ("Maintenance", "Maintenance"),
    ]
    
    bed_number = models.CharField(max_length=20)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='beds')
    bed_type = models.CharField(max_length=50, blank=True) # Manual or Electric etc
    status = models.CharField(max_length=20, choices=BED_STATUS, default="Available")
    daily_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.room.room_number} - {self.bed_number}"


class Service(AuditModel):
    service_name = models.CharField(max_length=100)
    service_code = models.CharField(max_length=20, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    department = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.service_name
    

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



class PharmacyStock(AuditModel):
    invoice_number = models.CharField(max_length=100)
    invoice_date = models.DateField()
    supplier_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=15)
    gst_number = models.CharField(max_length=15)
    address = models.CharField(max_length=15)
    medicine_name = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=100)
    hsn_code = models.CharField(max_length=100)
    expiry_date = models.DateField()
    quantity = models.IntegerField()
    pack = models.IntegerField()
    free = models.IntegerField(default=0)
    purchase_rate = models.DecimalField(max_digits=10, decimal_places=5)
    purchase_cost = models.DecimalField(max_digits=10, decimal_places=5)
    mrp = models.DecimalField(max_digits=10, decimal_places=5)
    discount = models.DecimalField(max_digits=10, decimal_places=5)
    taxable_amount = models.DecimalField(max_digits=10, decimal_places=5)
    cgst_rate = models.DecimalField(max_digits=10, decimal_places=5)
    cgst_amount = models.DecimalField(max_digits=10, decimal_places=5)
    sgst_rate = models.DecimalField(max_digits=10, decimal_places=5)
    sgst_amount = models.DecimalField(max_digits=10, decimal_places=5)
    total_amount = models.DecimalField(max_digits=10, decimal_places=5)

    def __str__(self):
        return self.medicine_name
class HSNCode(AuditModel):
    chapter = models.CharField(max_length=50)
    hsn_code = models.CharField(max_length=10, unique=True, primary_key=True)
    description = models.TextField()
    tax = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return f"{self.chapter} - {self.hsn_code}"


class Ventor(AuditModel):
    SUPPLIER_TYPE_CHOICES = [
        ('Supplier', 'Supplier'),
        ('Manufacturer', 'Manufacturer'),
        ('Both', 'Both'),
    ]
    ventor_name = models.CharField(max_length=100, unique=True)  # Set unique for POST/PATCH
    supplier_type = models.CharField(max_length=20, choices=SUPPLIER_TYPE_CHOICES, default='Supplier')
    phone = models.CharField(max_length=15, blank=True, null=True)
    landline = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField()
    gst_number = models.CharField(max_length=15, unique=True)
    def __str__(self):

        return f"{self.ventor_name} - {self.supplier_type}"
    
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
    

class OTMaster(AuditModel):
    ot_id = models.CharField(max_length=20, primary_key=True)
    ot_name = models.CharField(max_length=100)
    availability = models.CharField(
        max_length=20,
        choices=[("Available", "Available"), ("In Use", "In Use"), ("Under Maintenance", "Under Maintenance")],
        default="Available"
    )
    capacity = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.ot_id} - {self.ot_name}"


class AnesMaster(AuditModel):
    anesthesia_id = models.CharField(max_length=20, primary_key=True)
    anesthesia_name = models.CharField(max_length=100)
    type_of_anesthesia = models.CharField(
        max_length=30,
        choices=[
            ("General",  "General"),
            ("Regional", "Regional"),
            ("Local",    "Local"),
            ("Sedation", "Sedation"),
            ("Combined", "Combined"),
        ],
        default="General",
    )
    admin_guide = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
 
    def __str__(self):
        return f"{self.anesthesia_id} - {self.anesthesia_name}"


class SurgerySchedule(AuditModel):
    STATUS_CHOICES = [
        ("Scheduled",  "Scheduled"),
        ("Confirmed",  "Confirmed"),
        ("Completed",  "Completed"),
        ("Postponed",  "Postponed"),
        ("Cancelled",  "Cancelled"),
    ]
    reference_no = models.CharField(max_length=20, primary_key=True)
    ip_number   = models.CharField(max_length=30)         
    ot_id            = models.CharField(max_length=20)     # Operation Theater
    surgery_name     = models.CharField(max_length=100)    # billTypeNo maps to surgery
    surgeon_id       = models.CharField(max_length=30)     # Scheduled Surgeon
    scheduled_date   = models.DateField()
    startTime        = models.TimeField(null=True, blank=True)
    endTime          = models.TimeField(null=True, blank=True)
 
    # ── Surgery Meta ──────────────────────────────────────────────────────────
    surgery_type  = models.CharField(
        max_length=10,
        choices=[("Major", "Major"), ("Minor", "Minor")],
        default="Minor",
    )
    is_emergency  = models.BooleanField(default=False)
    diagnosis     = models.CharField(max_length=200, blank=True, default="")
    remarks       = models.TextField(blank=True, default="")
    anaesthetist_id  = models.CharField(max_length=30, blank=True, default="")
    anesthesia_id    = models.CharField(max_length=20, blank=True, default="")
    additional_anaesthetists = models.TextField(default="{}")
    additional_doctors       = models.TextField(default="{}")
    is_pack_request_CSSD = models.BooleanField(default=False)
    is_pack_return_CSSD  = models.BooleanField(default=False)
    is_postponed    = models.BooleanField(default=False)
    postponed_date  = models.DateField(null=True, blank=True)
    post_startTime  = models.TimeField(null=True, blank=True)
    post_endTime    = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Scheduled")
    is_active         = models.BooleanField(default=True)
 
    def __str__(self):
        return f"{self.reference_no} - {self.surgery_name} ({self.scheduled_date})"
 
    class Meta:
        ordering = ["-scheduled_date"]
 