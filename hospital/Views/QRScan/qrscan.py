"""
QRScan module for hospital management system.
Contains models, serializers, and view controllers for InPatient feedback form.
"""

from .models import InPatientFeedback, OutPatientFeedback
from .serializer import InPatientFeedbackSerializer, OutPatientFeedbackSerializer
from .views import (
    inpatient_feedback_list_create,
    inpatient_feedback_detail,
    outpatient_feedback_list_create,
    outpatient_feedback_detail,
)

# Export view references
inpatient_feedback_api = inpatient_feedback_list_create
outpatient_feedback_api = outpatient_feedback_list_create

