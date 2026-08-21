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

class StoresAssetsmaintenance(AuditModel):
    asset_id = models.CharField(max_length=50,primary_key=True)
    asset_name = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=255)
    barcode = models.CharField(max_length=255)
    date = models.DateField()
    department = models.CharField(max_length=50,null=True,blank=True)
    warrenty_period = models.CharField(max_length=50,null=True,blank=True)
    warrenty_end_date = models.DateField(null=True, blank=True)
    maintenance_details = djongo_models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=50,null=True,blank=True)
    incharge_id = models.CharField(max_length=50, null=True, blank=True)
    incharge_name = models.CharField(max_length=255, null=True, blank=True)
    last_service_date = models.DateField(null=True, blank=True)
    deactivate_remarks = models.TextField(blank=True, null=True)
    deactivated_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.asset_id} - {self.date}"    

class AssetMaintenanceRequest(AuditModel):
    request_id = models.CharField(max_length=50, primary_key=True)
    asset_id = models.CharField(max_length=50)
    asset_name = models.CharField(max_length=255)
    date = models.DateField(default=now)
    description = models.TextField(blank=True, null=True)
    requested_by = models.CharField(max_length=255)
    requested_by_id = models.CharField(max_length=50, null=True, blank=True)
    priority = models.CharField(max_length=50, default='Low') # Low, Medium, High
    status = models.CharField(max_length=50, default='Pending') # Pending, Approved, Completed, Rejected
    incharge_id = models.CharField(max_length=50, null=True, blank=True)
    incharge_name = models.CharField(max_length=255, null=True, blank=True)
    approval_date = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=255, null=True, blank=True)
    completion_date = models.DateTimeField(null=True, blank=True)
    completed_by = models.CharField(max_length=255, null=True, blank=True)
    service_cost = models.FloatField(default=0.0)
    service_remarks = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.request_id} - {self.asset_name} ({self.status})"    

class recycle_asset(AuditModel):
    asset_id = models.CharField(max_length=50,primary_key=True)
    date = models.DateField()
    items = models.JSONField(default=list, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.asset_id} - {self.date}"    