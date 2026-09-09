from rest_framework import serializers
from .models import VitalEntry, OPDoctorConsultation
from hospital.models import Patient
from hospital.Views.dbcollection import get_employee_name_by_id


class VitalEntrySerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = VitalEntry
        fields = '__all__'


class  OPDoctorConsultationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    patient_name = serializers.SerializerMethodField()
    doctor_name = serializers.SerializerMethodField()

    class Meta:
        model = OPDoctorConsultation
        fields = '__all__'

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
            if name and name.strip():
                return name
            return f"Dr. ({doc_id})"
        return "Doctor"
