from rest_framework import serializers
from .models import InsuranceClaim
from ...models import Patient, Admission

class InsuranceClaimSerializer(serializers.ModelSerializer):
    patient_details = serializers.SerializerMethodField()
    admission_details = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceClaim
        fields = "__all__"
        read_only_fields = ['claim_id']

    def get_patient_details(self, obj):
        # Clear ordering to avoid Djongo SQLDecodeError
        patient = Patient.objects.filter(uhid=obj.uhid).order_by().first()
        if patient:
            return {
                "firstName": patient.firstName,
                "lastName": patient.lastName,
                "age": patient.age,
                "gender": patient.gender,
                "customer_type": patient.customer_type
            }
        return {}

    def get_admission_details(self, obj):
        # Clear ordering to avoid Djongo SQLDecodeError
        admission = Admission.objects.filter(ipNumber=obj.ip_number).order_by().first()
        if admission:
            return {
                "admissionDateTime": admission.admissionDateTime,
                "admittingDoctor": admission.admittingDoctor,
                "room_details": admission.room_details
            }
        return {}
