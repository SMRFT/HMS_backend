from django.db import models
from django.utils.timezone import now
from django.utils import timezone
from ...models import AuditModel, RawJSONField


class VitalEntry(AuditModel):

    uhid = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    doctor_id = models.CharField(
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
    
    pain_score = models.IntegerField(blank=True, null=True)

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
    date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.uhid or "Vital Entry"


class OPDoctorConsultation(AuditModel):
    uhid = models.CharField(max_length=50, blank=True, null=True)
    doctor_id = models.CharField(max_length=50, blank=True, null=True)
    vitals = RawJSONField(default=dict, blank=True, null=True)
    pain_score = models.IntegerField(blank=True, null=True)
    allergies = models.TextField(blank=True, null=True)
    chief_complaints = models.TextField(blank=True, null=True)
    past_history = RawJSONField(default=list, blank=True, null=True)
    present_medications = models.TextField(blank=True, null=True)
    symptoms = RawJSONField(default=list, blank=True, null=True)
    investigation_test_ids = RawJSONField(default=list, blank=True, null=True)
    investigation_details = RawJSONField(default=list, blank=True, null=True)
    prescription_item_ids = RawJSONField(default=list, blank=True, null=True)
    prescription_details = RawJSONField(default=list, blank=True, null=True)
    finding = models.TextField(blank=True, null=True)
    diet = models.TextField(blank=True, null=True)
    refer_to_doctor = models.CharField(max_length=255, blank=True, null=True)
    followup_date = models.CharField(max_length=50, blank=True, null=True)
    consultation_start_time = models.DateTimeField(blank=True, null=True)
    consultation_end_time = models.DateTimeField(blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Consultation {self.uhid} - Dr. {self.doctor_name}"
