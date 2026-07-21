from django.db import models
from django.utils import timezone
from djongo import models as djongo_models
from ...models import AuditModel

class Complaint(AuditModel):
    issue_id = models.CharField(max_length=50, primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    steps_to_reproduce = models.TextField(blank=True, null=True)
    environment = models.TextField(blank=True, null=True)  # OS, Browser, Version, etc.
    ticket_type = models.CharField(max_length=50, default='Issue', blank=True, null=True)  # Issue, Add ons, Changes
    department = models.CharField(max_length=100, blank=True, null=True)  # Related department
    modules = models.CharField(max_length=255, blank=True, null=True)  # Related module(s)
    status = models.CharField(max_length=50, default='Pending')  # Pending, In Progress, Completed
    priority = models.CharField(max_length=50, blank=True, null=True)  # Low, Medium, High, Critical
    severity = models.CharField(max_length=50, blank=True, null=True)  # Minor, Major, Critical, Blocker
    reporter = models.CharField(max_length=100, blank=True, null=True)  # Employee ID of reporter
    assignee = models.CharField(max_length=100, blank=True, null=True)  # Assigned employee
    reported_date = models.DateTimeField(default=timezone.now)
    due_date = models.DateField(blank=True, null=True)
    final_completion_date = models.DateField(blank=True, null=True)
    labels_tags = djongo_models.JSONField(default=list, blank=True)  # List of tags
    attachments = djongo_models.JSONField(default=list, blank=True)  # List of {name, url, file_type, etc.}
    rca = models.TextField(blank=True, null=True)  # Root Cause Analysis

    def __str__(self):
        return f"{self.issue_id} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.issue_id:
            import datetime
            now = datetime.datetime.now()
            year_suffix = f"{now.year % 100:02d}"
            prefix = f"TCK{year_suffix}/"
            
            # Find the last complaint code starting with TCKYY/
            last_record = Complaint.objects.filter(issue_id__startswith=prefix).order_by('-created_date').first()
            if last_record and last_record.issue_id:
                try:
                    last_sequence = int(last_record.issue_id.split('/')[-1])
                    new_sequence = last_sequence + 1
                except (ValueError, IndexError):
                    new_sequence = 1
            else:
                new_sequence = 1
            
            self.issue_id = f"{prefix}{new_sequence:06d}"
            
        super().save(*args, **kwargs)
