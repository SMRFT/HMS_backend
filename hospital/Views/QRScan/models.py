from django.db import models
from django.utils import timezone

class InPatientFeedback(models.Model):
    feedback_type = models.CharField(max_length=100, blank=True, null=True)
    patient_name = models.CharField(max_length=255, blank=True, null=True)
    discharge_date = models.CharField(max_length=50, blank=True, null=True)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    ip_number = models.CharField(max_length=100, blank=True, null=True)
    doctor_name = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    overall_experience = models.CharField(max_length=100, blank=True, null=True)
    recommend_rating = models.CharField(max_length=20, blank=True, null=True)
    chose_hospital_reason = models.TextField(blank=True, null=True)
    referral_doctor_name = models.CharField(max_length=255, blank=True, null=True)
    
    # Rating options

    admission_experience = models.CharField(max_length=100, blank=True, null=True)
    in_room_experience = models.CharField(max_length=100, blank=True, null=True)
    in_room_cleanliness_experience = models.CharField(max_length=100, blank=True, null=True)
    doctor_care = models.CharField(max_length=100, blank=True, null=True)
    nursing_care = models.CharField(max_length=100, blank=True, null=True)
    diagnostic_experience = models.CharField(max_length=100, blank=True, null=True)
    pharmacy_experience = models.CharField(max_length=100, blank=True, null=True)
    canteen_experience = models.CharField(max_length=100, blank=True, null=True)
    food_quality = models.CharField(max_length=100, blank=True, null=True)
    ip_billing_experience = models.CharField(max_length=100, blank=True, null=True)
    ip_insurance_experience = models.CharField(max_length=100, blank=True, null=True)
    discharge_experience = models.CharField(max_length=100, blank=True, null=True)
    cleanliness_experience = models.CharField(max_length=100, blank=True, null=True)
    
    # Text Feedback
    suggestion_or_observation = models.TextField(blank=True, null=True)
    special_mention_staff = models.TextField(blank=True, null=True)
    
    created_date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Feedback ({self.feedback_type or 'General'}) by {self.patient_name or 'Anonymous'} - {self.created_date}"


class OutPatientFeedback(models.Model):
    patient_name = models.CharField(max_length=255, blank=True, null=True)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    op_number = models.CharField(max_length=100, blank=True, null=True)
    doctor_name = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    overall_experience = models.CharField(max_length=100, blank=True, null=True)
    recommend_rating = models.CharField(max_length=20, blank=True, null=True)
    chose_hospital_reason = models.TextField(blank=True, null=True)
    refer = models.CharField(max_length=255, blank=True, null=True)
    referral_doctor_name = models.CharField(max_length=255, blank=True, null=True)


    registration_experience = models.CharField(max_length=100, blank=True, null=True)
    doctor_consultation_experience = models.CharField(max_length=100, blank=True, null=True)
    nursing_care = models.CharField(max_length=100, blank=True, null=True)
    diagnostic_experience = models.CharField(max_length=100, blank=True, null=True)
    housekeeping_experience = models.CharField(max_length=100, blank=True, null=True)
    pharmacy_experience = models.CharField(max_length=100, blank=True, null=True)
    canteen_experience = models.CharField(max_length=100, blank=True, null=True)
    op_insurance_experience = models.CharField(max_length=100, blank=True, null=True)
    op_billing_experience = models.CharField(max_length=100, blank=True, null=True)
    billing_experience = models.CharField(max_length=100, blank=True, null=True)
    cleanliness_experience = models.CharField(max_length=100, blank=True, null=True)


    suggestion_or_observation = models.TextField(blank=True, null=True)
    special_mention_staff = models.TextField(blank=True, null=True)

    created_date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"OP Feedback by {self.patient_name or 'Anonymous'} - {self.created_date}"

