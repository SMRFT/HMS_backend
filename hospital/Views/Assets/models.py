from django.db import models
from django.utils.timezone import now
from django.utils import timezone
from ...models import AuditModel
from djongo import models as djongo_models

class StoresAssetsManagement(AuditModel):
    asset_id = models.CharField(max_length=50,primary_key=True)
    asset_name = models.CharField(max_length=255)
    barcode = models.CharField(max_length=255)
    date = models.DateField()
    department = models.CharField(max_length=50,null=True,blank=True)
    deactivate_remarks = models.TextField(blank=True, null=True)
    deactivated_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.asset_id} - {self.date}"    

class StoresAssetsMaintainance(AuditModel):
    asset_id = models.CharField(max_length=50,primary_key=True)
    asset_name = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=255)
    barcode = models.CharField(max_length=255)
    date = models.DateField()
    department = models.CharField(max_length=50,null=True,blank=True)
    warrenty_period = models.CharField(max_length=50,null=True,blank=True)
    warrenty_end_date = models.DateField(null=True, blank=True)
    maintainance_details = djongo_models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=50,null=True,blank=True)
    deactivate_remarks = models.TextField(blank=True, null=True)
    deactivated_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.asset_id} - {self.date}"    

class recycle_asset(AuditModel):
    asset_id = models.CharField(max_length=50,primary_key=True)
    # asset_name = models.CharField(max_length=255)
    date = models.DateField()
    items = models.JSONField(default=list, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.asset_id} - {self.date}"    