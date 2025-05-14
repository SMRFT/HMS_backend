from django.db import models
from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password


class Register(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=50)  # Add role
    department = models.CharField(max_length=100)
    password = models.CharField(max_length=100)

    def __str__(self):
        return self.name
    
class PharmacyStock(models.Model):
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


class HSNCode(models.Model):
    chapter = models.CharField(max_length=50)
    hsn_code = models.CharField(max_length=10, unique=True, primary_key=True)
    description = models.TextField()
    tax = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return f"{self.chapter} - {self.hsn_code}"


from django.db import models
from django.utils.timezone import now

class Patient(models.Model):
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
    salutation = models.CharField(max_length=100)
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
    mobile_phone = models.CharField(max_length=15)
    home_phone = models.CharField(max_length=15, blank=True, null=True)
    blood_group =models.CharField(max_length=20, blank=True, null=True)
    spouse_name = models.CharField(max_length=100, blank=True, null=True)
    referred_by = models.CharField(max_length=100, blank=True, null=True)
    doctor_name = models.CharField(max_length=100, blank=True, null=True)
    registration_fee = models.CharField(max_length=100, blank=True, null=True)
    consulting_fee = models.CharField(max_length=20, blank=True, null=True)
    total_fees =models.CharField(max_length=100, blank=True, null=True)
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
        return f"{self.name} ({self.uhid})"

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
        return self.name if self.name else "Unnamed Patient"

    
class Ventor(models.Model):
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

        
class Doctor(models.Model):
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



from django.db import models

class CTReport(models.Model):
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


from django.db import models

# Define MRI Report model
class MRIReport(models.Model):
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
    
# Define MRI Report model
class USGReport(models.Model):
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

# Define MRI Report model
class XRayReport(models.Model):
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



from django.db import models

class Admission(models.Model):
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
    birthTime = models.TimeField(blank=True, null=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    mothersUHIDNo = models.CharField(max_length=20, blank=True)
    pediatricianResponsible = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.firstName} {self.lastName} ({self.uhid})"

from djongo import models

class Summary(models.Model):
    _id = models.ObjectIdField()  # MongoDB ID field
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

    def __str__(self):
        return self.patient or "Summary"
    
    
# models.py
from django.db import models

class EstimateBilling(models.Model):
    EstBillNo = models.CharField(max_length=50, blank=True)
    EstBillDate = models.CharField(max_length=50)
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



# models.py
from django.db import models

class InvestBilling(models.Model):
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

class qrscan(models.Model):
    name =models.CharField(max_length=100) # This will store the admission type as JSON
    email = models.CharField(max_length=255)
    mobile = models.CharField(max_length=100)
    company = models.CharField(max_length=255)
    searchFor = models.CharField(max_length=50)
    def __str__(self):
        return self.name
    

class ReferenceDoctor(models.Model):
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


class Log(models.Model):
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


class Block(models.Model):
    block_id = models.CharField(max_length=10, unique=True, blank=True)
    block_name = models.CharField(max_length=100)

    def save(self, *args, **kwargs):
        if not self.block_id:
            last_block = Block.objects.order_by('id').last()
            if last_block and last_block.block_id:
                last_number = int(last_block.block_id.replace("B", ""))
                self.block_id = f"B{last_number + 1}"
            else:
                self.block_id = "B1"
        super(Block, self).save(*args, **kwargs)

    def __str__(self):
        return self.block_name


class Room(models.Model):
    ROOM_CATEGORIES = [
        ("PRIVATE ROOM", "PRIVATE ROOM"),
        ("SEMI PRIVATE", "SEMI PRIVATE"),
        ("GENERAL WARD", "GENERAL WARD"),
    ]

    BLOCKS = [
        ("MAIN BLOCK", "MAIN BLOCK"),
        ("CANCER BLOCK", "CANCER BLOCK"),
    ]

    NURSING_STATIONS = [
        ("MICU", "MICU"),
        ("SICU", "SICU"),
    ]

    ROOM_TYPES = [
        ("ICU", "ICU"),
        ("CCU", "CCU"),
        ("ICCU", "ICCU"),
        ("NICU", "NICU"),
        ("CASUALITY", "CASUALITY"),
        ("OTHERS", "OTHERS"),
    ]

    room_number = models.CharField(max_length=10, unique=True)
    description = models.TextField()
    room_category = models.CharField(max_length=20, choices=ROOM_CATEGORIES)
    block = models.CharField(max_length=20, choices=BLOCKS)
    floor = models.IntegerField()
    phone_extension = models.CharField(max_length=10)
    nursing_station = models.CharField(max_length=10, choices=NURSING_STATIONS)
    capacity = models.IntegerField()
    admission_fee = models.DecimalField(max_digits=10, decimal_places=2)
    room_advance = models.DecimalField(max_digits=10, decimal_places=2)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES)

    def __str__(self):
        return self.room_number
    

class DischargeDetail(models.Model):
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