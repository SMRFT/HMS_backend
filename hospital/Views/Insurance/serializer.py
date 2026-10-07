from rest_framework import serializers
from .models import InsuranceClaim, InsuranceMember, InsuranceMemberDependent, InsuranceMemberVisit
from ...models import Patient, Admission

class InsuranceClaimSerializer(serializers.ModelSerializer):
    patient_details = serializers.SerializerMethodField()
    admission_details = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceClaim
        fields = "__all__"
        read_only_fields = ['claim_id']

    def get_patient_details(self, obj):
        try:
            patient = Patient.objects.filter(uhid=obj.uhid).order_by().first()
            if patient:
                return {
                    "firstName": getattr(patient, 'firstName', ''),
                    "lastName": getattr(patient, 'lastName', ''),
                    "age": getattr(patient, 'age', ''),
                    "gender": getattr(patient, 'gender', ''),
                    "customer_type": getattr(patient, 'customer_type', '')
                }
        except Exception:
            pass
        return {}

    def get_admission_details(self, obj):
        try:
            admission = Admission.objects.filter(ipNumber=obj.ip_number).order_by().first()
            if admission:
                return {
                    "admissionDateTime": getattr(admission, 'admissionDateTime', None),
                    "admittingDoctor": getattr(admission, 'admittingDoctor', ''),
                    "room_details": getattr(admission, 'room_details', '')
                }
        except Exception:
            pass
        return {}


class InsuranceMemberDependentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceMemberDependent
        fields = "__all__"


class InsuranceMemberSerializer(serializers.ModelSerializer):
    dependents = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceMember
        fields = "__all__"

    def get_dependents(self, obj):
        try:
            all_deps = list(InsuranceMemberDependent.objects.filter(member_number=obj.member_number).order_by())
            active_deps = [d for d in all_deps if getattr(d, 'is_active', True) is not False]
            active_deps.sort(key=lambda x: getattr(x, 'dependent_sl_no', 1))
            return InsuranceMemberDependentSerializer(active_deps, many=True).data
        except Exception:
            return []


class InsuranceMemberVisitSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceMemberVisit
        fields = "__all__"
