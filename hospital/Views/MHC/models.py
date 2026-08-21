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




class MasterHealthcheckup(AuditModel):

    mhc_no = models.PositiveIntegerField(unique=True, blank=True, null=True)

    patient_name = models.CharField(max_length=100, blank=True, null=True)
    age = models.IntegerField(blank=True, null=True)
    gender = models.CharField(max_length=20, blank=True, null=True)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    op_number = models.CharField(max_length=50, blank=True, null=True)
    package = models.CharField(max_length=100, blank=True, null=True)
    source = models.CharField(max_length=100, blank=True, null=True)
    package_category = models.CharField(max_length=100, blank=True, null=True)

    package_fee = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    doctor_fee = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    add_tests = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    pharmacy = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    ip = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    total_fees = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )

    follow_up = models.CharField(max_length=100, blank=True, null=True)
    description = models.CharField(max_length=100, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.mhc_no:
            last_record = MasterHealthcheckup.objects.order_by("-mhc_no").first()

            if last_record and last_record.mhc_no:
                self.mhc_no = last_record.mhc_no + 1
            else:
                self.mhc_no = 1

        super().save(*args, **kwargs)