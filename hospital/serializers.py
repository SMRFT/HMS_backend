from rest_framework import serializers
from bson import ObjectId
from .models import SurgerySchedule,PharmacyStock,HSNCode,Ventor,IPPharmacyStock, OPPharmacyStock,Vendor,Patient,Doctor,Admission,Summary,EstimateBilling
class ObjectIdField(serializers.Field):
    def to_representation(self, value):
        return str(value)

    def to_internal_value(self, data):
        try:
            return ObjectId(data)
        except:
            return data
        
class PharmacyStockSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = PharmacyStock
        fields = '__all__'

class HSNCodeSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = HSNCode
        fields = '__all__'

class VentorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ventor
        fields = ['id', 'ventor_name', 'phone', 'address', 'gst_number']

class IPPharmacyStockSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = IPPharmacyStock
        fields = '__all__'


class OPPharmacyStockSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = OPPharmacyStock
        fields = '__all__'


class VendorSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = Vendor
        fields = '__all__'


class PatientSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    uhid = serializers.CharField(read_only=True)
    class Meta:
        model = Patient
        fields = '__all__'


class DoctorSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = Doctor
        fields = '__all__'

class AdmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admission
        fields = '__all__'


class SummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Summary
        fields = '__all__'


class EstimateBillingSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstimateBilling
        fields = '__all__'


from .models import ReferenceDoctor
class ReferenceDoctorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceDoctor
        fields = '__all__'


from .models import Block, RoomCategory, Bed, Service, Room

class BlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = '__all__'


class RoomCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomCategory
        fields = '__all__'


class BedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bed
        fields = '__all__'


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = '__all__'


class RoomSerializer(serializers.ModelSerializer):
    beds = BedSerializer(many=True, read_only=True)

    class Meta:
        model = Room
        fields = '__all__'


from .models import DischargeDetail
class DischargeDetailSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = DischargeDetail
        fields = '__all__'


from .models import IPGRN, OPGRN

class IPGRNSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = IPGRN
        fields = '__all__'


class OPGRNSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = OPGRN
        fields = '__all__'


from .models import OPPharmacyBill
class OPPharmacyBillSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = OPPharmacyBill
        fields = '__all__'

class SurgeryScheduleSerializer(serializers.ModelSerializer):
    """
    Used for READ responses (list, retrieve, after create/update).
    All audit/system fields are read-only — never accepted from the client.
    """

    class Meta:
        model  = SurgerySchedule
        fields = "__all__"
        read_only_fields = [
            "reference_no",
            "status",
            "is_active",
            "is_postponed",
            "postponed_date",
            "post_startTime",
            "post_endTime",
            "created_by",
            "created_date",
            "lastmodified_by",
            "lastmodified_date",
            "branch_code",
            "hospital_code",
        ]


class SurgeryScheduleWriteSerializer(serializers.ModelSerializer):
 
    class Meta:
        model  = SurgerySchedule
        fields = [
            "ip_number",
            "ot_id",
            "surgery_name",
            "surgeon_id",
            "scheduled_date",
            "startTime",
            "endTime",
            "surgery_type",
            "is_emergency",
            "anaesthetist_id",
            "anesthesia_id",
            "diagnosis",
            "remarks",
            "additional_anaesthetists",
            "additional_doctors",
            "is_pack_request_CSSD",
            "is_pack_return_CSSD",
        ]

    # ── Field-level validation ─────────────────────────────────────────────
    def validate_ip_number(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("IP Number is required.")
        return value.strip()

    def validate_ot_id(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Operation Theater is required.")
        return value.strip()

    def validate_surgery_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Surgery Name is required.")
        return value.strip()

    def validate_surgeon_id(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Scheduled Surgeon is required.")
        return value.strip()

    def validate_scheduled_date(self, value):
        if not value:
            raise serializers.ValidationError("Scheduled Date is required.")
        return value

    def validate_additional_anaesthetists(self, value):
        """Accept dict or JSON string; always store as JSON string."""
        import json
        if isinstance(value, dict):
            return json.dumps(value)
        if isinstance(value, str):
            try:
                json.loads(value)   # validate it's parseable
            except (ValueError, TypeError):
                raise serializers.ValidationError("Must be a valid JSON object string.")
        return value

    def validate_additional_doctors(self, value):
        import json
        if isinstance(value, dict):
            return json.dumps(value)
        if isinstance(value, str):
            try:
                json.loads(value)
            except (ValueError, TypeError):
                raise serializers.ValidationError("Must be a valid JSON object string.")
        return value

    # ── Object-level validation ────────────────────────────────────────────
    def validate(self, attrs):
        start = attrs.get("startTime")
        end   = attrs.get("endTime")
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"endTime": "End time must be after start time."}
            )
        return attrs
