from django.db import models
from django.utils.timezone import now
from django.utils import timezone
from ...models import AuditModel


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

from djongo import models as djongo_models

class storesGRN(AuditModel):

    grn_number = models.CharField(max_length=50, unique=True, primary_key=True)
    is_active = models.BooleanField(default=True)
    # Import djongo models to bypass the Django JSONField stringification issue
    payment_status = djongo_models.JSONField(default=list, blank=True)

    total_amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    purchase_category = models.CharField(max_length=50,null=True,blank=True)

    vendor_id = models.CharField(max_length=255, blank=True, null=True)

    date = models.DateField()

    invoice_no = models.CharField(max_length=100)
    invoice_date = models.DateField()

    credit_period = models.CharField(max_length=50, blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)

    payment_mode = models.CharField(max_length=50, blank=True, null=True)

    items = djongo_models.JSONField(default=list, blank=True)

    non_taxable_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    tax_paid_to_supplier = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    local_tax = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    remarks = models.TextField(blank=True, null=True)

    cgst = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    igst = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    cess = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    central_sales_tax = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    round_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    total_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    tax_on_free_items = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    total_discount = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    net_invoice_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    quotation_rate = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    courier_transport_charge = models.DecimalField(max_digits=20, decimal_places=2, default=0)     
    is_approved = models.BooleanField(default=False)    
    
    def __str__(self):
        return f"{self.grn_number} - {self.vendor}"    

class storesIntent(AuditModel):
    intent_id = models.CharField(max_length=50,primary_key=True)
    is_active = models.BooleanField(default=True)
    date = models.DateField()
    items = djongo_models.JSONField(default=list, blank=True)
    department = models.CharField(max_length=50,null=True,blank=True)
    is_approved = models.BooleanField(default=False)    
    
    def __str__(self):
        return f"{self.intent_id} - {self.date}"    



from django.db import models

class Stores_LabApprovedItem(AuditModel):
    item_id = models.CharField(max_length=50,primary_key=True)
    name = models.CharField(max_length=255)
    date = models.DateTimeField(default=now)
    hsn = models.CharField(max_length=50, null=True, blank=True)
    quantity = models.IntegerField()
    used_qty = models.IntegerField(null=True, blank=True, default=None)

    def __str__(self):
        return f"{self.name} ({self.item_id})"


class Stores_LabUsedQtyDetail(AuditModel):
    """Daily usage record per date, storing an array of items used on that date."""
    date = models.DateTimeField(max_length=50, primary_key=True)  # Format: YYYY-MM-DD
    items = djongo_models.JSONField(default=list, blank=True)  # [{"item_id": "...", "name": "...", "used_qty": n, "hsn": "..."}, ...]

    def __str__(self):
        return f"{self.date} — {len(self.items)} items"

