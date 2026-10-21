from djongo import models
from django.utils import timezone
from ...models import AuditModel


class BreastCancerScreening(AuditModel):
    _id                  = models.ObjectIdField()
    date                 = models.DateField(default=timezone.localdate)
    bill_number          = models.CharField(max_length=50, blank=True, null=True)
    patientname          = models.CharField(max_length=50, blank=True, null=True)
    uhid                 = models.CharField(max_length=50, blank=True, null=True)
    age                  = models.CharField(max_length=50, blank=True, null=True)
    gender               = models.CharField(max_length=20, default='Female', blank=True, null=True)

    # Fields from Form
    subject_id           = models.CharField(max_length=100, blank=True, null=True)
    subject_phone_number = models.CharField(max_length=20, blank=True, null=True)
    subject_address      = models.TextField(blank=True, null=True)
    surveyor_name        = models.CharField(max_length=150, blank=True, null=True)
    risk_level           = models.CharField(max_length=50, blank=True, null=True)  # "High Risk" or "Low risk"

    remarks              = models.TextField(blank=True, null=True)

    @classmethod
    def generate_next_bill_number(cls):
        """
        Auto-generates sequential Hospital Bill / Receipt Number based on financial year.
        Format: <FIN_YEAR>/<SEQ starting from 01> (e.g. 2627/01, 2627/02, ...)
        Increases sequentially with each new entry.
        """
        today = timezone.localdate()
        from_yr = today.year if today.month >= 4 else today.year - 1
        to_yr = from_yr + 1
        fin_year = f"{str(from_yr)[-2:]}{str(to_yr)[-2:]}"
        prefix = f"{fin_year}/"

        existing_bills = cls.objects.filter(
            bill_number__startswith=prefix
        ).values_list('bill_number', flat=True)

        max_seq = 0
        for bill in existing_bills:
            if bill and '/' in str(bill):
                try:
                    parts = str(bill).strip().split('/')
                    seq = int(parts[-1])
                    if seq > max_seq:
                        max_seq = seq
                except (ValueError, IndexError):
                    pass

        next_seq = max_seq + 1
        return f"{prefix}{str(next_seq).zfill(2)}"

    def save(self, *args, **kwargs):
        # Auto-generate bill_number if not provided or empty
        if not self.bill_number or not str(self.bill_number).strip():
            self.bill_number = self.generate_next_bill_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.bill_number or 'No Bill'} - {self.subject_id} - {self.risk_level}"


class StudentSurveyorRegistration(AuditModel):
    _id              = models.ObjectIdField()
    date             = models.DateField(default=timezone.localdate)
    institute_name   = models.CharField(max_length=255, blank=True, null=True)
    course_name_year = models.CharField(max_length=255, blank=True, null=True)
    surveyor_name    = models.CharField(max_length=150, blank=True, null=True)
    subject_id       = models.CharField(max_length=100, blank=True, null=True)
    phone_number     = models.CharField(max_length=20, blank=True, null=True)
    remarks          = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.surveyor_name} - {self.institute_name} ({self.subject_id})"