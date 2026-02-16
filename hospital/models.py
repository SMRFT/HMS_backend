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

    def save(self, *args, **kwargs):
        now = datetime.utcnow()

        if not self.created_date:
            self.created_date = now

        self.lastmodified_date = now

        super().save(*args, **kwargs)

# Item Management Model
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
    room_number = models.CharField(max_length=10, unique=True)
    description = models.TextField(blank=True)
    room_category = models.CharField(max_length=100) # Fetched from RoomCategory
    block = models.CharField(max_length=100) # Fetched from Block
    floor = models.IntegerField()
    phone_extension = models.CharField(max_length=10, blank=True)
    nursing_station = models.CharField(max_length=50, blank=True)
    capacity = models.IntegerField(default=1) # Total beds
    admission_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    room_advance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    room_type = models.CharField(max_length=20, default="WARD")

    def __str__(self):
        return self.room_number
    
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
        ('New', 'New'),
        ('Renew', 'Renew'),
        ('Visit', 'Visit'),
    )

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
    registration_date =models.CharField(max_length=100, blank=True, null=True)
    citizen_id_type = models.CharField(max_length=20, blank=True, null=True)
    citizen_id_no = models.CharField(max_length=50, blank=True, null=True)
    customer_type =models.CharField(max_length=20, blank=True, null=True)
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
    referredBy = models.CharField(max_length=100, blank=True, null=True)
    doctorName = models.CharField(max_length=100, blank=True, null=True)
    insurance_company = models.CharField(max_length=100, blank=True, null=True)

    # MLC fields
    mlc_type = models.CharField(max_length=50, blank=True, null=True)
    mlc_doc = models.CharField(max_length=100, blank=True, null=True)
    mlc_remarks = models.TextField(blank=True, null=True)
    pass_alert_to_authority =models.CharField(max_length=100, blank=True, null=True)

    # Next of Kin fields
    next_of_kin = models.CharField(max_length=100, blank=True, null=True)
    relation = models.CharField(max_length=50, blank=True, null=True)
    kin_address = models.TextField(blank=True, null=True)
    kin_mobile = models.CharField(max_length=15, blank=True, null=True)
    kin_age = models.CharField(max_length=10, blank=True, null=True)
    kin_age_unit = models.CharField(max_length=10, default='Years')
    kin_occupation = models.CharField(max_length=100, blank=True, null=True)

    # Insurance fields
    member_number = models.CharField(max_length=50, blank=True, null=True)
    suffix_number = models.CharField(max_length=50, blank=True, null=True)
    approved_amount = models.CharField(max_length=20, blank=True, null=True)

    # Referred fields
    referred_dr_mobile = models.CharField(max_length=15, blank=True, null=True)
    referred_dr_remarks = models.TextField(blank=True, null=True)

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

class RoomServiceDescription(AuditModel):
    description = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'hospital_roomservice_description'

    def __str__(self):
        return self.description


class RoomKitDescription(AuditModel):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.name

class RoomKit(models.Model):
    room = models.ForeignKey('Room', on_delete=models.CASCADE, related_name='kits', null=True, blank=True)
    # Stores ID of RoomKitDescription
    kit_item = models.CharField(max_length=50) 
    priority = models.IntegerField(blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    enable_item = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Kit {self.kit_item} for Room"


