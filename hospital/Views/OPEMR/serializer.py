from rest_framework import serializers
from .models import VitalEntry, OPDoctorConsultation
from hospital.models import Patient
from hospital.Views.dbcollection import get_employee_name_by_id


class VitalEntrySerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = VitalEntry
        fields = '__all__'

    def get_created_by_name(self, obj):
        emp_id = getattr(obj, 'created_by', None)
        if emp_id:
            name = get_employee_name_by_id(str(emp_id))
            if name and name != "Unknown":
                return name
            return f"Staff ({emp_id})"
        return "Staff"


class  OPDoctorConsultationSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    _id = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    doctor_name = serializers.SerializerMethodField()

    class Meta:
        model = OPDoctorConsultation
        fields = '__all__'

    def get_id(self, obj):
        return str(getattr(obj, '_id', None) or getattr(obj, 'id', None) or getattr(obj, 'pk', '') or '')

    def get__id(self, obj):
        return str(getattr(obj, '_id', None) or getattr(obj, 'id', None) or getattr(obj, 'pk', '') or '')

    def get_patient_name(self, obj):
        if obj.uhid:
            try:
                patient = Patient.objects.get(uhid=obj.uhid)
                name_parts = [patient.salutation, patient.firstName, patient.lastName]
                return " ".join(part for part in name_parts if part).strip()
            except Patient.DoesNotExist:
                return "Unknown"
        return "Unknown"

    def get_doctor_name(self, obj):
        doc_id = getattr(obj, 'doctor_id', None) or getattr(obj, 'created_by', None)
        if doc_id:
            name = get_employee_name_by_id(str(doc_id))
            if name and name.strip() and name != "Unknown":
                return name
            doc_str = str(doc_id).strip()
            if doc_str and not doc_str.isdigit() and doc_str.lower() != "doctor":
                return doc_str
            return f"Dr. ({doc_id})"
        return "Doctor"
