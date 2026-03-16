from django.db import models
from django.utils.timezone import now
from django.utils import timezone


# Base Audit Model
class AuditModel(models.Model):
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_date = models.DateTimeField(default=now)
    lastmodified_by = models.CharField(max_length=100, null=True, blank=True)
    lastmodified_date = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class ItemMaster(AuditModel):
    item_id = models.CharField(max_length=50,primary_key=True)
    itemName = models.CharField(max_length=255)
    group = models.CharField(max_length=100, null=True, blank=True)
    group_type = models.CharField(max_length=50, null=True, blank=True)
    category = models.CharField(max_length=100, null=True, blank=True)
    department = models.CharField(max_length=50, null=True, blank=True)
    hsn = models.CharField(max_length=20, blank=True, null=True)
    stockReorderLevel = models.CharField(max_length=100, null=True, blank=True)
    total_quantity = models.IntegerField(default=0)
    approved_quantity = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.itemName

    def save(self, *args, **kwargs):
        if self.pk:  # If updating existing record
            self.lastmodified_date = timezone.now()
        super().save(*args, **kwargs)

class Department(AuditModel):
    department_id = models.CharField(max_length=50,primary_key=True)
    department_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.department_name

class Group(AuditModel):
    group_id = models.CharField(max_length=50,primary_key=True)
    group_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.group_name

class Category(AuditModel):
    category_id = models.CharField(max_length=50,primary_key=True)
    category_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.category_name

class GroupType(AuditModel):
    group_type_id = models.CharField(max_length=50,primary_key=True)
    group_type_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.group_type_name

class storesGRN(AuditModel):
    # Add GRN number field
    grn_number = models.CharField(max_length=50, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    payment_status = models.JSONField(default=list, blank=True, null=True)
    total_amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    # Basic Information
    purchase_category = models.CharField(max_length=50, choices=[
        ('TRAVELLERS IN CREDIT', 'TRAVELLERS IN CREDIT'),
        ('TRAVELLERS IN CASH', 'TRAVELLERS IN CASH'),
    ])
    vendor_id = models.CharField(max_length=255, blank=True, null=True)
    date = models.DateField()
    invoice_no = models.CharField(max_length=100)
    invoice_date = models.DateField()
    credit_period = models.CharField(max_length=50, blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)    
    payment_mode = models.CharField(max_length=50, blank=True, null=True)
    
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
    tax_on_free_items = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    total_discount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    net_invoice_amount = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    quotation_rate = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)
    courier_transport_charge = models.DecimalField(max_digits=50, decimal_places=2, default=0.00)       
    
    def __str__(self):
        return f"{self.grn_number} - {self.vendor}"    