from django.db import models
from django.utils.timezone import now
from django.utils import timezone
from ...models import AuditModel


class VitalEntry(AuditModel):

    uhid = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    height = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True
    )

    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True
    )

    bp = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    bmi = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True
    )

    temp = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True
    )

    pulse_rate = models.IntegerField(
        blank=True,
        null=True
    )

    spo2 = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True
    )

    respiratory_rate = models.IntegerField(
        blank=True,
        null=True
    )

    blood_sugar = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True
    )

    vital_entry_date = models.DateTimeField(
        default=now
    )

    last_modified_date = models.DateTimeField(
        auto_now=True
    )


    def __str__(self):
        return self.uhid or "Vital Entry"