from djongo import models
from django.db import transaction
from django.db.models import Max
import re
from django.utils import timezone
from django.utils.timezone import now
from datetime import datetime

# Base Audit Model
class AuditModel(models.Model):
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_date = models.DateTimeField(default=timezone.now)
    lastmodified_by = models.CharField(max_length=100, null=True, blank=True)
    lastmodified_date = models.DateTimeField(auto_now = True)
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
    company_code = models.CharField(max_length=100, blank=True, null=True)

    uhid = models.CharField(max_length=20)
    # ip_number = models.CharField(max_length=20, blank=True, null=True)
    customer_type = models.CharField(max_length=20, default='General')
    registration_date =models.CharField(max_length=100, blank=True, null=True)
    salutation = models.CharField(max_length=10, blank=True, null=True)
    firstName = models.CharField(max_length=100)
    lastName = models.CharField(max_length=100)
    dob = models.DateField()
    age = models.IntegerField()
    gender = models.CharField(max_length=10)
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

    mothers_uhid_no = models.CharField(max_length=20, blank=True, null=True)
    pediatrician_responsible = models.CharField(max_length=100, blank=True, null=True)

    # Additional fields
    is_cross_consultation = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.firstName} {self.lastName} ({self.uhid})"

    def save(self, *args, **kwargs):
        # 1. Determine Financial Year prefix (Starting April)
        today = now()
        # If month is 1, 2, or 3 (January, February, March), use previous year.
        # Otherwise use current year. (Financial Year is 2026-27 starting April 2026)
        fy_year = today.year if today.month >= 4 else today.year - 1
        prefix = f"S0{fy_year % 100:02d}"

        if not self.uhid:
            # 2. Get all patients of the current financial year to find the true numeric maximum.
            # String-based sorting (order_by('-uhid')) is flawed due to inconsistent padding (e.g. S026/0006 vs S026/00007).
            year_patients = Patient.objects.filter(uhid__startswith=prefix).values_list('uhid', flat=True)
            
            max_number = 0
            for u in year_patients:
                try:
                    # Expecting format "S0YY/NNNNN"
                    num_str = u.split('/')[-1]
                    num = int(num_str)
                    if num > max_number:
                        max_number = num
                except (ValueError, IndexError):
                    continue
            
            last_number = max_number
            
            next_number = last_number + 1
            # 3. Format with 5-digit padding as per user requirement (S026/00001)
            self.uhid = f"{prefix}/{next_number:05d}"

        super().save(*args, **kwargs)

class CustomerType(AuditModel):
    type_id = models.IntegerField(primary_key=True)
    type_name = models.CharField(max_length=100, unique=True)
    registration_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    priority = models.IntegerField(default=1)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.type_id is None:
            last = CustomerType.objects.order_by('-type_id').first()
            self.type_id = (last.type_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.type_name

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
    shiftno = models.CharField(max_length=100, blank=True, null=True)
    billtype = models.CharField(max_length=50, blank=True, null=True)
    edit_history = models.JSONField(default=list, blank=True)

    def save(self, *args, **kwargs):

        if not self.bill_number:

            current_date = now()

            year = current_date.year
            month = current_date.month

            # Financial Year Calculation
            if month >= 4:
                start_year = year % 100
                end_year = (year + 1) % 100
            else:
                start_year = (year - 1) % 100
                end_year = year % 100

            fy_prefix = f"{start_year:02d}{end_year:02d}"

            pattern = f"{fy_prefix}/"

            # Find last bill number
            last_bill = Billing.objects.filter(
                bill_number__startswith=pattern
            ).order_by('-bill_number').first()

            if last_bill and last_bill.bill_number:
                try:
                    last_number = int(
                        last_bill.bill_number.split('/')[-1]
                    )
                except (ValueError, IndexError):
                    last_number = 0
            else:
                last_number = 0

            next_number = last_number + 1

            self.bill_number = f"{fy_prefix}/{next_number:06d}"

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
    
class ChemicalComposition(AuditModel):
    composition_id   = models.IntegerField(primary_key=True)
    composition_name = models.CharField(max_length=255)
    is_active        = models.BooleanField(default=True)
 
    def save(self, *args, **kwargs):
        if self.composition_id is None:
            last = ChemicalComposition.objects.order_by('-composition_id').first()
            self.composition_id = (last.composition_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.composition_name
    
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
    
    # Additional Fields
    gstin = models.CharField(max_length=20, null=True, blank=True)
    payment_terms = models.CharField(max_length=50, null=True, blank=True)
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

class PharmacyItem(AuditModel):
    item_id = models.IntegerField(primary_key=True)
    item_name = models.CharField(max_length=200)
    item_last_name = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=50)
    brand_name = models.CharField(max_length=100, blank=True)
    chemical_composition = models.CharField(max_length=255, blank=True)
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
    
class StockTransfer(AuditModel):
    transfer_ref_number = models.CharField(max_length=30, unique=True)
    to_outlet = models.CharField(max_length=50, blank=True, default="")
    items = models.JSONField(default=list)
    remarks = models.TextField(blank=False, default="")
    approved_by = models.CharField(max_length=100, blank=True, default="")
    approved_date = models.DateTimeField(null=True, blank=True)
    IS_VERIFIED_CHOICES = [
        ("Draft",    "Draft"),
        ("Approved", "Approved"),
        ("Rejected", "Rejected"),
    ]
    is_verified = models.CharField(max_length=20, choices=IS_VERIFIED_CHOICES, default="Draft")

class PurchaseReturn(AuditModel):
    purchase_return_bill_no   = models.CharField(max_length=30, unique=True)
    purchase_return_bill_date = models.DateTimeField(default=timezone.now)
    grn_number                = models.CharField(max_length=50)
    vendor_code               = models.CharField(max_length=50, blank=True, default="")
    vendor_name               = models.CharField(max_length=255, blank=True, default="")
    outlet_code               = models.CharField(max_length=50, blank=True, default="")
    # items stores: item_id, item_name, stock_id, batch_number,
    #               return_qty, price, cause_of_return
    items                     = models.JSONField(default=list)
    purchase_return_amount    = models.CharField(max_length=50, default="0.00")
    # Charge breakdowns (stored as strings to avoid float precision issues)
    gst_amount                = models.CharField(max_length=30, default="0.00")
    cgst_amount               = models.CharField(max_length=30, default="0.00")
    sgst_amount               = models.CharField(max_length=30, default="0.00")
    other_amount              = models.CharField(max_length=30, default="0.00")
    round_amount              = models.CharField(max_length=30, default="0.00")
    return_remark             = models.TextField(blank=True, default="")
    status                    = models.CharField(max_length=50, default="Returned")
 
    def __str__(self):
        return f"{self.purchase_return_bill_no} — {self.grn_number}"
    

PR_STATUS_CHOICES = [
    ("Draft",                     "Draft"),
    ("Approved",                  "Approved"),
    ("Rejected",                  "Rejected"),
    ("Purchase Order Initiated",  "Purchase Order Initiated"),
    ("Purchased",                 "Purchased"),
    ("Stock Restocked",           "Stock Restocked"),
]
 
 
class PurchaseRequisition(AuditModel):
    pr_number = models.CharField(max_length=30, primary_key=True)   # PR/2627/000001
 
    # ── Medicine items ──────────────────────────────────────────────────────
    # Stored as a native list of dicts:
    #   [{ "item_id": <id|None>, "medicine_name": "<name>" }, ...]
    # Persisted as a BSON array (MongoDB via djongo) — same pattern as
    # PurchaseOrder.items. Never json.dumps / json.loads this field.
    items = models.JSONField(default=list, blank=True)
 
    # ── Header ───────────────────────────────────────────────────────────────
    status = models.CharField(max_length=30, default="Draft", choices=PR_STATUS_CHOICES)
 
    # ── Approval ─────────────────────────────────────────────────────────────
    approved_by   = models.CharField(max_length=100, blank=True, default="")
    approved_date = models.DateTimeField(null=True, blank=True)
 
    # ── Rejection ────────────────────────────────────────────────────────────
    rejected_by     = models.CharField(max_length=100, blank=True, default="")
    rejected_reason = models.TextField(blank=True, default="")
    rejected_date   = models.DateTimeField(null=True, blank=True)
 
    # ── Purchase Order Initiated ────────────────────────────────────────────
    po_initiated_by   = models.CharField(max_length=100, blank=True, default="")
    po_initiated_date = models.DateTimeField(null=True, blank=True)
 
    # ── Purchased ────────────────────────────────────────────────────────────
    purchased_by   = models.CharField(max_length=100, blank=True, default="")
    purchased_date = models.DateTimeField(null=True, blank=True)
 
    # ── Stock Restocked ──────────────────────────────────────────────────────
    stock_restocked_by   = models.CharField(max_length=100, blank=True, default="")
    stock_restocked_date = models.DateTimeField(null=True, blank=True)
 
    # ── Edit audit ───────────────────────────────────────────────────────────
    edited_by     = models.CharField(max_length=100, blank=True, default="")
    edited_reason = models.TextField(blank=True, default="")
    edited_date   = models.DateTimeField(null=True, blank=True)
 
    def __str__(self):
        names = ", ".join(
            i.get("medicine_name", "") for i in (self.items or []) if isinstance(i, dict)
        )
        return f"{self.pr_number} — {names or '—'} [{self.status}]"
    
    
from django.utils import timezone

class PharmacyBilling(AuditModel):

    Bill_id = models.IntegerField(primary_key=True)
    bill_no = models.CharField(max_length=50, blank=True, null=True)
    estimate_no = models.CharField(max_length=50, blank=True, null=True)
    bill_date = models.DateTimeField(blank=True, null=True)
    uhid = models.CharField(max_length=5,blank=True, null=True)
    inpatient_number = models.CharField(max_length=50, blank=True, null=True)
    patientname = models.CharField(max_length=100, blank=True, null=True)
    age = models.IntegerField(blank=True, null=True)
    bill_type = models.IntegerField(blank=True, null=True)
    doctor_id = models.CharField(max_length=50, blank=True, null=True)
    room_no = models.CharField(max_length=20, blank=True, null=True)
    medicine_particulars = models.JSONField(default=list)
    total_amount = models.FloatField(default=0)
    overall_discount_type = models.CharField(max_length=10,default="percent")
    overall_discount_value = models.FloatField(default=0)
    overall_discount_amount = models.FloatField(default=0)
    net_amount = models.FloatField(default=0)
    billing_status = models.CharField(max_length=20)
    billing_mode = models.CharField(max_length=20)
    payment_details = models.JSONField(null=True, blank=True)
    Esimated_id=models.CharField(max_length=150)
    edit_reason = models.TextField(null=True, blank=True)
    edited_by = models.CharField(max_length=150)
    is_deleted= models.BooleanField(default=False)
    delete_reason = models.TextField(null=True, blank=True)
    deleted_by =models.CharField(max_length=150)
    round_off= models.IntegerField(default=0)
    cashier_id = models.CharField(max_length=500, blank=True, null=True)
    is_ward_request = models.BooleanField(default=False)
    ward_request_date = models.DateTimeField(blank=True, null=True)
    is_dispatched = models.BooleanField(default=False)
    is_received = models.BooleanField(default=False)
    pending_returns = models.JSONField(default=list, blank=True, null=True)
    payment_mode = models.CharField(max_length=100, blank=True, null=True)
    pending_returns = models.JSONField(default=list, blank=True, null=True)
    Package_id = models.CharField(max_length=100, blank=True, null=True)
    is_received = models.BooleanField(default=False)

    # :white_check_mark: AUTO-INCREMENT LOGIC
    def save(self, *args, **kwargs):
        if not self.Bill_id:
            last = PharmacyBilling.objects.order_by('-Bill_id').first()
            self.Bill_id = (last.Bill_id + 1) if last else 1

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.billing_status} - {self.patient_name}"  


        
class PharmacyStock(AuditModel):
    stock_id = models.IntegerField(primary_key=True)
    item_id = models.IntegerField()
    batch_number = models.CharField(max_length=50)

    expiry_date = models.DateField(null=True, blank=True)

    mrp = models.DecimalField(max_digits=10, decimal_places=2)
    Selling_Price = models.DecimalField(max_digits=10, decimal_places=2)

    grn_number = models.CharField(max_length=50)

    total_stock = models.IntegerField()

    sold_quantity = models.IntegerField(default=0)
    transferred_out_quantity = models.IntegerField(default=0)

    stock_type = models.CharField(max_length=50, default="grn")
    stock_ref_id = models.IntegerField(default=0)

    grn_return_quantity = models.IntegerField(default=0)

    blocked_quantity = models.IntegerField(default=0)

    sales_return_quantity = models.IntegerField(default=0)

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

# GRN Model
class GRN(AuditModel):
    CATEGORY_PREFIX = {
        "MEDICINE_PURCHASE":    "OP",
        "MEDICINE_PURCHASE_IP": "IP",
        "OPENING_STOCK_DRUG":   "DP",
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
    tax_paid_to_supplier= models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_discount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True, null=True)
    total_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_invoice_amount  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status      = models.TextField(default="[]")
    remarks             = models.TextField(blank=True, default="")
    status              = models.CharField(max_length=50, default="Draft")
    edited_by     = models.CharField(max_length=100, blank=True, default="")
    edited_date   = models.DateTimeField(null=True, blank=True)
    edited_reason = models.TextField(blank=True, default="")
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
        return f"{self.grn_number or self.draft_number} ({self.vendor_id})"

class MedicineRequisition(AuditModel):
      STATUS_CHOICES = [
          ("Draft",    "Draft"),
          ("Approved", "Approved"),
          ("Rejected", "Rejected"),
      ]

      mr_number           = models.CharField(max_length=30, primary_key=True)
      medicine_name       = models.CharField(max_length=255)
      chemical_composition= models.TextField(blank=True, default="")
      consultant_name     = models.CharField(max_length=255, blank=True, default="")
      request_date        = models.DateTimeField()
      remarks             = models.TextField(blank=True, default="")
      status              = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")

      # Approval
      approved_by         = models.CharField(max_length=100, blank=True, default="")
      approved_date       = models.DateTimeField(null=True, blank=True)

      # Rejection
      rejected_by         = models.CharField(max_length=100, blank=True, default="")
      rejected_reason     = models.TextField(blank=True, default="")
      rejected_date       = models.DateTimeField(null=True, blank=True)

      # Edit audit
      edited_by           = models.CharField(max_length=100, blank=True, default="")
      edited_reason       = models.TextField(blank=True, default="")
      edited_date         = models.DateTimeField(null=True, blank=True)

      def __str__(self):
          return f"{self.pr_number} — {self.medicine_name}"
      
class PurchaseOrder(AuditModel):

    STATUS_CHOICES = [
        ("Draft",    "Draft"),
        ("Verified", "Verified"),
        ("Rejected", "Rejected"),
    ]
 
    po_number     = models.CharField(max_length=30, primary_key=True)
 
    # Vendor
    vendor_id     = models.IntegerField()
 
    # Medicine items — stored as JSON text
    items = models.JSONField(default=list, blank=True)
 
    # Workflow
    status        = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="Draft"
    )
 
    # Approval
    approved_by   = models.CharField(max_length=100, blank=True, default="")
    approved_date = models.DateTimeField(null=True, blank=True)
 
    # Rejection
    rejected_by     = models.CharField(max_length=100, blank=True, default="")
    rejected_reason = models.TextField(blank=True, default="")
    rejected_date   = models.DateTimeField(null=True, blank=True)
 
    # Edit audit
    edited_by     = models.CharField(max_length=100, blank=True, default="")
    edited_reason = models.TextField(blank=True, default="")
    edited_date   = models.DateTimeField(null=True, blank=True)
 
    def __str__(self):
        return self.po_number


from django.db import models


# ── PhysicalStockEntry ────────────────────────────────────────────────────────
# Stores the physical stock count entered by staff, saved separately from
# PharmacyStock.  Approval workflow: is_approved=False until a manager approves.
# ─────────────────────────────────────────────────────────────────────────────

class PhysicalStockEntry(models.Model):
    entry_id        = models.AutoField(primary_key=True)

    # ── Item / batch reference (denormalised for quick reads) ──────────────
    item_id         = models.IntegerField()
    item_name       = models.CharField(max_length=255)
    batch_number    = models.CharField(max_length=100)
    stock_id        = models.IntegerField(null=True, blank=True)   # FK to PharmacyStock.stock_id

    # ── Stock snapshot at time of entry ───────────────────────────────────
    computer_stock  = models.IntegerField(default=0)   # calculated at save time
    physical_stock  = models.IntegerField(default=0)   # manually entered
    stock_date      = models.DateField()               # date of physical count

    # ── Variance (computed on approval or save) ───────────────────────────
    variance        = models.IntegerField(default=0)   # physical - computer

    # ── Approval workflow ─────────────────────────────────────────────────
    is_approved     = models.BooleanField(default=False)
    approved_by     = models.CharField(max_length=100, null=True, blank=True)
    approved_date   = models.DateTimeField(null=True, blank=True)
    approval_notes  = models.TextField(null=True, blank=True)

    # ── Audit ──────────────────────────────────────────────────────────────
    is_active        = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.item_name} | {self.batch_number} | {self.stock_date}"

class NursingStation(AuditModel):
    ward_id = models.IntegerField(primary_key=True)
    ward_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.ward_id is None:
            last = NursingStation.objects.order_by('-ward_id').first()
            self.ward_id = (last.ward_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.ward_name
    
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

class RoomServiceDescription(AuditModel):
    description_id = models.IntegerField(primary_key=True)
    description_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.description_id is None:
            last = RoomServiceDescription.objects.order_by('-description_id').first()
            self.description_id = (last.description_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.description_name

class RoomKitItems(AuditModel):
    kit_id = models.IntegerField(primary_key=True)
    kit_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.kit_id is None:
            last = RoomKitItems.objects.order_by('-kit_id').first()
            self.kit_id = (last.kit_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.kit_name

ROOM_STATUS_CHOICES = [
    ("Available",    "Available"),
    ("Maintenance",  "Maintenance"),
    ("Blocked",      "Blocked"),
]
 
 
class Room(AuditModel):
    room_number      = models.CharField(max_length=10, primary_key=True)
    description      = models.TextField(blank=True)
    room_category    = models.CharField(max_length=100)
    block            = models.CharField(max_length=100)
    phone_extension  = models.CharField(max_length=10, blank=True)
    nursing_station  = models.CharField(max_length=100, blank=True)
    capacity         = models.IntegerField(default=1)
    occupancy        = models.IntegerField(default=0)
    room_status      = models.CharField(
                           max_length=20,
                           choices=ROOM_STATUS_CHOICES,
                           default="Available"
                       )
    is_active        = models.BooleanField(default=True)
 
    # Nested JSON sub-documents
    services         = models.JSONField(default=list, blank=True)
    beds             = models.JSONField(default=list, blank=True)
    room_kits        = models.JSONField(default=list, blank=True)
 
    def __str__(self):
        return self.room_number
 
    def save(self, *args, **kwargs):
        if self.services is None:
            self.services = []
        if self.beds is None:
            self.beds = []
        if self.room_kits is None:
            self.room_kits = []
        super().save(*args, **kwargs)


class RoomBooking(AuditModel):
    ip_number     = models.CharField(max_length=10, primary_key=True)
    room_number  = models.CharField(max_length=50)
    bed_number   = models.CharField(max_length=50)
    is_booked    = models.BooleanField(default=True)
    room_shifted = models.BooleanField(default=False)   # True once patient is actually shifted
    booked_date  = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Booking: IP={self.ip_number} | Room={self.room_number}/{self.bed_number} | shifted={self.room_shifted}"

class Admission(AuditModel):
    uhid                = models.CharField(max_length=20)
    ipNumber            = models.CharField(max_length=10, primary_key=True)
    ipserial_number     = models.IntegerField(blank=True, null=True)
    age_type            = models.CharField(max_length=10)
    age     = models.IntegerField(blank=True, null=True)
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
 
    # ── Cancellation tracking ─────────────────────────────────────────────────
    is_cancelled        = models.BooleanField(default=False)
    cancelled_by        = models.CharField(max_length=100, blank=True, null=True)
    cancelled_Reason    = models.TextField(blank=True, null=True)
 
    # ── Edit tracking ─────────────────────────────────────────────────────────
    is_edited           = models.BooleanField(default=False)
    edited_by           = models.CharField(max_length=100, blank=True, null=True)
    edited_Reason       = models.TextField(blank=True, null=True)
 
    # ── Ward / admission status ───────────────────────────────────────────────
    ward_status         = models.CharField(max_length=50, blank=True, null=True)
 
    # ── Core boolean flags ────────────────────────────────────────────────────
    is_discharged       = models.BooleanField(default=False)
    is_admitted         = models.BooleanField(default=True)
 
    class Meta:
        ordering = ['-admissionDateTime']
 
    def save(self, *args, **kwargs):
        # Auto-generate IP serial number per UHID
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


class AdmissionRefund(models.Model):
    refund_bill_no   = models.CharField(max_length=30, unique=True)
    refund_date      = models.DateTimeField()
    refund_amount        = models.DecimalField(max_digits=12, decimal_places=2)

    bill_no          = models.CharField(max_length=30) 
    ip_number        = models.CharField(max_length=50)

    advance_amount       = models.DecimalField(max_digits=12, decimal_places=2)
    total_refunded_so_far= models.DecimalField(max_digits=12, decimal_places=2)
    remaining_balance    = models.DecimalField(max_digits=12, decimal_places=2)
    remarks              = models.TextField(blank=True, default="")

    bill_type        = models.CharField(max_length=20)
    status           = models.CharField(max_length=20, default="Pending")

class DischargeBilling(AuditModel):
    # ── Identity ──────────────────────────────────────────────────────────────
    discharge_id    = models.IntegerField(primary_key=True)
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
    next_visit_date   = models.DateField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.discharge_id is None:
            last = DischargeBilling.objects.order_by('-discharge_id').first()
            self.discharge_id = (last.discharge_id + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        ref = self.bill_no if self.status == "Billed" else self.estimate_number
        return f"{self.uhid or self.ip_number} | {ref} | {self.status}"


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

class RadiologyReport(AuditModel):
    date = models.DateTimeField()
    slot_DateTime = models.DateTimeField()
    patientIn_DateTime = models.DateTimeField(null=True, blank=True)
    scan_started_DateTime = models.DateTimeField(null=True, blank=True)
    investBillNo = models.CharField(max_length=50, blank=True)
    uhid = models.TextField()    
    billTypeNo = models.TextField()    
    itemName = models.TextField()
    item_id = models.IntegerField()
    valuedetails      = models.JSONField(default=dict)
    impression = models.TextField()    
    is_approved = models.BooleanField(default=False)
    approved_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)   # ✅ add this
    has_report = models.BooleanField(default=False)   # ✅ add this
    type = models.TextField()    
    is_Dispatched = models.BooleanField(default=False)
    dispatch_DateTime = models.DateTimeField(null=True, blank=True)
    dispatched_by = models.CharField(max_length=100, blank=True)


    def __str__(self):
        return f"Radiology Report - {self.investBillNo} ({self.uhid})"
    
class JRDReport(AuditModel):
    """
    Stores the JRD (Form-F) register data captured from the ANC Register UI.
    One record per ANC report line — linked via investBillNo + item_id.
 
    jrd_id  → sequential business key (1, 2, 3 …) scoped per hospital+branch.
              Generated once on creation and never changed.
    """
    jrd_id       = models.IntegerField(db_index=True)           # sequential business key
    hospital_code = models.CharField(max_length=50, blank=True)
    branch_code   = models.CharField(max_length=50, blank=True)
 
    investBillNo = models.CharField(max_length=50, db_index=True)
    item_id      = models.IntegerField(db_index=True)
    form_no      = models.CharField(max_length=100, blank=True)  # S. No of Form -F
    mtp_advice   = models.CharField(max_length=500, blank=True)  # MTP Advice if Any
    is_active    = models.BooleanField(default=True)
 
    class Meta:
        unique_together = [
            ('investBillNo', 'item_id'),                          # one record per ANC scan
            ('hospital_code', 'branch_code', 'jrd_id'),          # jrd_id unique per branch
        ]
        ordering = ['jrd_id']
 
    def __str__(self):
        return f"JRD-{self.jrd_id} [{self.investBillNo} / item {self.item_id}]"


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
    
    # ── Patient Identity ──────────────────────────────────────
    uhid = models.CharField(max_length=50, blank=True)        # ← blank=True (manual entry)
    ipNumber = models.CharField(max_length=50, blank=True)
    salutation = models.CharField(max_length=20, blank=True)   # ← new
    firstName = models.CharField(max_length=100, blank=True)   # ← new
    lastName = models.CharField(max_length=100, blank=True)    # ← new
    age = models.CharField(max_length=50, blank=True)          # ← blank=True
    age_type = models.CharField(max_length=50, blank=True)     # ← blank=True
    gender = models.CharField(max_length=20, blank=True)       # ← new
    roomNo = models.CharField(max_length=50, blank=True)       # ← blank=True

    # ── Billing Details ───────────────────────────────────────
    bill_type = models.CharField(max_length=100, blank=True, null=True)
    billTypeNo = models.CharField(max_length=50, blank=True, null=True)
    doctor = models.CharField(max_length=100, blank=True)      # ← blank=True
    referredBy = models.CharField(max_length=100, blank=True, null=True)
    item = models.JSONField()
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    discountPercent = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)  # ← DecimalField (was Int)
    discount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, default=0.0)
    discountRemarks = models.TextField(blank=True, null=True)
    finalPrice = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    paymentMethod = models.CharField(max_length=50, blank=True)  # ← blank=True

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Estimate for {f'{self.firstName} {self.lastName}'.strip()} ({self.uhid or 'No UHID'})"
    

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
    surgeon_id = models.CharField(max_length=255, blank=True, null=True)
    customer_type = models.CharField(max_length=255, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)

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
    is_approved = models.BooleanField(default=False)
    approved_by = models.CharField(max_length=255, blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)

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
    category = models.CharField(max_length=50, blank=True, default="")
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
    ClosingBalance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    ShiftStatus    = models.CharField(max_length=50, default="active")
    StartingTime   = models.DateTimeField()
    closingTime    = models.DateTimeField(null=True, blank=True)
    date         = models.DateField(default=timezone.now)
    collected_Amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    PettyCashBalance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    RemittedToBank = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    SubmittedToAccount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    HandOverAmount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    SalesReturnAmount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    SelectedOutlet = models.CharField(max_length=100, null=True, blank=True)
    is_active      = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.CashierID} - {self.CashCounter}"
    

class CashCounter(AuditModel):
    counter_id = models.CharField(primary_key=True,max_length=100000)
    counter_name = models.CharField(max_length=50)
    outlet = models.CharField(max_length=50)
    bill_type = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.counter_id

    def save(self, *args, **kwargs):
        if not self.counter_id:
            # Find the highest numeric ID starting with 'CC'
            last = CashCounter.objects.filter(counter_id__startswith="CC").order_by("-counter_id").first()
            if last:
                try:
                    # Extract number from "CC0001" -> 1
                    last_num = int(last.counter_id[2:])
                    self.counter_id = f"CC{(last_num + 1):04d}"
                except (ValueError, IndexError):
                    self.counter_id = "CC0001"
            else:
                self.counter_id = "CC0001"
        
        # Ensure bill_type is a list for saving
        if isinstance(self.bill_type, str):
            try:
                import json
                self.bill_type = json.loads(self.bill_type)
            except:
                pass

        super().save(*args, **kwargs)

        # 🚀 Force BSON array storage in MongoDB using pymongo
        try:
            from pymongo import MongoClient
            import os
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client["HMS"]
            db["hospital_cashcounter"].update_one(
                {"counter_id": self.counter_id},
                {"$set": {"bill_type": self.bill_type if isinstance(self.bill_type, list) else []}}
            )
            client.close()
        except Exception as e:
            print(f"Pymongo force update failed: {e}")

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
    


    

class PatientDietOrder(AuditModel):
    STATUS_CHOICES = [
        ("Ordered",   "Ordered"),
        ("Received",  "Received"),
        ("Delivered", "Delivered"),
        ("Cancelled", "Cancelled"),
    ]
    MEAL_TIME_CHOICES = [
        ("Breakfast", "Breakfast"),
        ("Lunch",     "Lunch"),
        ("Dinner",    "Dinner"),
        ("Snacks",    "Snacks"),
    ]

    diet_id              = models.AutoField(primary_key=True)
    uhid                 = models.CharField(max_length=50)
    inpatient_number     = models.CharField(max_length=50, null=True, blank=True)
    patient_name         = models.CharField(max_length=200, null=True, blank=True)
    ward_name            = models.CharField(max_length=100, null=True, blank=True)
    room_no              = models.CharField(max_length=50, null=True, blank=True)
    food_items           = models.TextField(null=True, blank=True)

    diet_type            = models.CharField(max_length=100)          # e.g. "Normal Diet"
    special_diet_note    = models.CharField(max_length=500, null=True, blank=True)  # when diet_type=="Special Diet"

    meal_time            = models.CharField(max_length=20, choices=MEAL_TIME_CHOICES, default="Lunch")

    extra_items          = models.TextField(default="[]")            # JSON array [{item, qty}]
    attender_count       = models.IntegerField(default=0)

    diet_price           = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    extra_items_price    = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_price          = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    special_instructions = models.TextField(null=True, blank=True)

    status               = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Ordered")
    ordered_by           = models.CharField(max_length=100, null=True, blank=True)
    order_date           = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.uhid} – {self.diet_type} ({self.meal_time}) [{self.status}]"
    




class ReceiptAndPayment(AuditModel):

    receipt_type = models.CharField(max_length=50)
    account_head = models.CharField(max_length=150)

    description = models.JSONField(null=True, blank=True)

    voucher_no = models.CharField(max_length=100, unique=True)
    voucher_date = models.DateField(auto_now_add=True)

    amount = models.DecimalField(max_digits=120, decimal_places=2)

    shiftno = models.CharField(max_length=100)
    CashierID      = models.CharField(max_length=100,null=True, blank=True)
    CashCounter    = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.voucher_no} - {self.account_head}"
    

class SalesReturn(AuditModel):
    return_bill_no = models.CharField(max_length=200, unique=True)
    return_bill_date = models.DateTimeField(auto_now_add=True)
    bill_no = models.CharField(max_length=200)
    uhid = models.CharField(max_length=20)
    return_amount = models.CharField(max_length=200)
    medicine_particulars = models.JSONField()
    pharmacist_id = models.CharField(max_length=500, blank=True, null=True)
    PaymentType= models.CharField(max_length=500, blank=True, null=True)
   

    # ✅ ADD THIS
    status = models.CharField(
        max_length=100,
        default="Pending",
        blank=True,
        null=True
    )

    bill_type = models.IntegerField(
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):
        # 1. Standard Django Save
        super().save(*args, **kwargs)

        # 2. Force BSON array storage in MongoDB using pymongo
        try:
            from pymongo import MongoClient
            import os
            import json

            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client["HMS"]

            meds = self.medicine_particulars

            if isinstance(meds, str):
                try:
                    meds = json.loads(meds)
                except:
                    meds = []

            db["hospital_salesreturn"].update_one(
                {"return_bill_no": self.return_bill_no},
                {
                    "$set": {
                        "medicine_particulars": meds if isinstance(meds, list) else [],
                        "status": self.status  ,
                        "bill_type": self.bill_type,  
                    }
                }
            )

            client.close()

        except Exception as e:
            print(f"SalesReturn Pymongo force update failed: {e}")


class DietMaster(AuditModel):
    id               = models.AutoField(primary_key=True)
    item_id          = models.CharField(max_length=50, null=True, blank=True)
    diet_name        = models.CharField(max_length=100, unique=True)
    morning_items    = models.TextField(null=True, blank=True)
    afternoon_items  = models.TextField(null=True, blank=True)
    evening_items    = models.TextField(null=True, blank=True)
    dinner_items     = models.TextField(null=True, blank=True)
    price            = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_active        = models.BooleanField(default=True)

    def __str__(self):
        return self.diet_name

class DietExtraMaster(AuditModel):
    id               = models.AutoField(primary_key=True)
    item_id          = models.CharField(max_length=50, null=True, blank=True)
    item_name        = models.CharField(max_length=100, unique=True)
    price            = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_active        = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.item_name} - {self.price}"
    




class CashCounterCollection(AuditModel):

    collection_id = models.AutoField(primary_key=True)

    Bill_id = models.IntegerField(
        null=True,
        blank=True
    )

    bill_no = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    return_bill_no= models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    bill_type = models.IntegerField(
        null=True,
        blank=True
    )

    counter_code = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    # ✅ CHANGED TO CHARFIELD
    shift_no = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    billing_category = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    bill_number = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    transaction_type = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    collected_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00
    )

    Returned_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        null=True,
        blank=True
    )

    RemittedToBank = models.DecimalField(max_digits=12, decimal_places=2, default=0,null=True,blank=True)
    
    HandOverAmount = models.DecimalField(max_digits=12, decimal_places=2, default=0,null=True,blank=True)

    remarks = models.TextField(
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.bill_number} - {self.collected_amount}"
    





import json
import os
from pymongo import MongoClient
from django.db import models


class DialysisDischargeSummary(AuditModel):

    # Patient Details
    name = models.CharField(max_length=255)
    age = models.PositiveIntegerField()
    gender = models.CharField(max_length=100)

    uhid = models.CharField(max_length=100, unique=True)
    consultant = models.CharField(max_length=255,null=True, blank=True)
    id_no = models.CharField(max_length=100,null=True, blank=True)
    insurance = models.CharField(max_length=255, blank=True, default="")

    address = models.TextField()
    date = models.DateField(auto_now_add=True)
    diagnosis = models.TextField()

    date_of_first_dialysis = models.DateField(null=True, blank=True)
    date_of_last_dialysis = models.DateField(null=True, blank=True)

    blood_investigations = models.JSONField(default=list,null=True, blank=True)
    hd_sessions = models.JSONField(default=list, blank=True)
    complications_during_hd = models.JSONField(default=list, null=True, blank=True)

    condition_on_discharge = models.TextField()

    advice_on_discharge = models.JSONField(default=list, null=True, blank=True)

    next_hd_session_on = models.DateField()

    def _parse_json_field(self, value):
        """Safely parse a field that may already be a list or a JSON string."""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return []
        return []

    def save(self, *args, **kwargs):

        # ==========================================
        # NORMAL DJANGO SAVE
        # ==========================================

        super().save(*args, **kwargs)

        # ==========================================
        # FORCE BSON ARRAY SAVE
        # ==========================================

        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client["HMS"]

            db["hospital_dialysisdischargesummary"].update_one(
                {"uhid": self.uhid},
                {
                    "$set": {
                        "blood_investigations": self._parse_json_field(self.blood_investigations),
                        "hd_sessions": self._parse_json_field(self.hd_sessions),
                        "complications_during_hd": self._parse_json_field(self.complications_during_hd),
                        "advice_on_discharge": self._parse_json_field(self.advice_on_discharge),
                        "date_of_first_dialysis": (
                            self.date_of_first_dialysis.isoformat()
                            if self.date_of_first_dialysis else None
                        ),
                        "date_of_last_dialysis": (
                            self.date_of_last_dialysis.isoformat()
                            if self.date_of_last_dialysis else None
                        ),
                    }
                },
            )

            client.close()

        except Exception as e:
            print(f"DialysisDischargeSummary pymongo update failed: {e}")

    def __str__(self):
        return f"{self.name} - {self.uhid}"


class Refund(AuditModel):
    id = models.AutoField(primary_key=True)
    refund_bill_no = models.CharField(max_length=50, unique=True, null=True, blank=True)
    refund_date = models.DateTimeField(auto_now_add=True)
    bill_no = models.CharField(max_length=50) # Original Bill Number
    uhid = models.CharField(max_length=50)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    bill_type = models.CharField(max_length=50, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default='Pending') # Pending, Approved, etc.
    
    # Audit info is inherited from AuditModel (created_by, created_date, etc.)

    def save(self, *args, **kwargs):
        if not self.refund_bill_no:
            from django.utils import timezone
            
            # Generate refund bill number: YY-YY/000001 (matching user example)
            now = timezone.now()
            year = now.year
            if now.month >= 4:
                fy = f"{str(year)[2:]}{str(year+1)[2:]}"
            else:
                fy = f"{str(year-1)[2:]}{str(year)[2:]}"
            
            prefix = f"{fy}/"
            
            last_refund = Refund.objects.filter(refund_bill_no__startswith=prefix).order_by('-refund_bill_no').first()
            if last_refund:
                try:
                    last_no = int(last_refund.refund_bill_no.split('/')[-1])
                    new_no = last_no + 1
                except (ValueError, IndexError):
                    new_no = 1
            else:
                new_no = 1
            
            self.refund_bill_no = f"{prefix}{new_no:06d}"
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.refund_bill_no} - {self.uhid} (₹{self.refund_amount})"


class LaundryWardRequest(AuditModel):
    id = models.IntegerField(primary_key=True)
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Processing", "Processing"),
        ("Completed", "Completed"),
        ("Cancelled", "Cancelled"),
    ]
    REQUEST_TYPE_CHOICES = [
        ("Normal", "Normal"),
        ("Urgent", "Urgent"),
    ]

    patient_name = models.CharField(max_length=200, null=True, blank=True)
    uhid = models.CharField(max_length=50)
    ipNumber = models.CharField(max_length=50, null=True, blank=True)
    wardName = models.CharField(max_length=100, null=True, blank=True)
    roomNo = models.CharField(max_length=50, null=True, blank=True)
    bedNo = models.CharField(max_length=50, null=True, blank=True)
    
    # Store laundry items (e.g., {"Bedsheets": 2, "Towels": 1})
    items = models.JSONField(default=list)
    
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, default="Normal")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    remarks = models.TextField(null=True, blank=True)
    
    requested_by = models.CharField(max_length=100, null=True, blank=True)
    requested_date = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if self.id is None:
            last = LaundryWardRequest.objects.order_by('-id').first()
            self.id = (last.id + 1) if last and last.id else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Laundry Request - {self.uhid} - {self.status}"


class LaundryItemMaster(AuditModel):
    id = models.IntegerField(primary_key=True)
    item_id = models.CharField(max_length=50, null=True, blank=True)
    item_name = models.CharField(max_length=200, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.id is None:
            last = LaundryItemMaster.objects.order_by('-id').first()
            self.id = (last.id + 1) if last and last.id else 1
        if not self.item_id:
            self.item_id = f"L-{self.id:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_name} - ₹{self.price}"


class CrashCartItem(models.Model):
    id = models.IntegerField(primary_key=True)
    nursing_station = models.CharField(max_length=100, null=True, blank=True)
    box_category = models.CharField(max_length=100) # e.g., "BOX-1(EMERGENCY MEDICINE)"
    drug_name = models.CharField(max_length=255)    # e.g., "INJ.ADRENALINE 1 mg"
    required_stock = models.IntegerField()          # e.g., 10

    def save(self, *args, **kwargs):
        if not self.id:
            last = CrashCartItem.objects.order_by('-id').first()
            self.id = (last.id + 1) if last else 1
        super().save(*args, **kwargs)
    
class CrashCartDailyCheck(models.Model):
    id = models.IntegerField(primary_key=True)
    date = models.DateField(default=timezone.now)
    nursing_station = models.CharField(max_length=100) # e.g., "CHEMO WARD"
    item = models.ForeignKey(CrashCartItem, on_delete=models.CASCADE)
    expiry_date = models.CharField(max_length=50, null=True, blank=True) # Expiry date
    is_checked = models.BooleanField(default=False)
    checked_by = models.CharField(max_length=100) # Nurse Name/ID

    def save(self, *args, **kwargs):
        if not self.id:
            last = CrashCartDailyCheck.objects.order_by('-id').first()
            self.id = (last.id + 1) if last else 1
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('date', 'nursing_station', 'item')
