from rest_framework import serializers
from bson import ObjectId

class ObjectIdField(serializers.Field):
    def to_representation(self, value):
        return str(value)

    def to_internal_value(self, data):
        try:
            return ObjectId(data)
        except:
            return data
        
from .models import PharmacyCategory
class PharmacyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PharmacyCategory
        fields = "__all__"
        read_only_fields = ["category_id"]

        
from .models import PharmacyItem
class PharmacyItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PharmacyItem
        fields = "__all__"
        read_only_fields = ["item_id"]


from .models import Vendor
class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = "__all__"
        read_only_fields = ["vendor_id"]


from .models import PharmacyStock
class PharmacyStockSerializer(serializers.ModelSerializer):
    stock_id = serializers.IntegerField(read_only=True)

    class Meta:
        model  = PharmacyStock
        fields = "__all__"


from .models import GRN
class GRNSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = GRN
        fields = '__all__'


from .models import Block, RoomCategory, Room
class BlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = "__all__"
        read_only_fields = ["block_id"]


class RoomCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomCategory
        fields = "__all__"
        read_only_fields = ["room_category_id"]

class RoomSerializer(serializers.ModelSerializer):
    # These fields will be handled as JSON
    services = serializers.JSONField(required=False, allow_null=True, default=list)
    beds = serializers.JSONField(required=False, allow_null=True, default=list)
    room_kits = serializers.JSONField(required=False, allow_null=True, default=list)

    class Meta:
        model = Room
        fields = [
            'room_number',
            'description',
            'room_category',
            'block',
            'floor',
            'phone_extension',
            'nursing_station',
            'capacity',
            'admission_fee',
            'room_advance',
            'room_type',
            'room_blocked',
            'blocked_reason',
            'is_active',
            'services',
            'beds',
            'room_kits',
            'created_by',
            'created_date',
            'lastmodified_by',
            'lastmodified_date',
        ]
        read_only_fields = ['id', 'created_date', 'lastmodified_date']

    def validate_services(self, value):
        """Validate services array"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Services must be a list")
        return value

    def validate_beds(self, value):
        """Validate beds array"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Beds must be a list")
        return value

    def validate_room_kits(self, value):
        """Validate room_kits array"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Room kits must be a list")
        return value
    

from .models import Admission
from .models import Admission, Patient

class AdmissionSerializer(serializers.ModelSerializer):

    patient_details = serializers.SerializerMethodField()

    class Meta:
        model = Admission
        fields = "__all__"

    def get_patient_details(self, obj):
        patient = Patient.objects.filter(uhid=obj.uhid).first()

        if patient:
            return PatientSerializer(patient).data
        return None 


from .models import DischargeDetail
class DischargeDetailSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = DischargeDetail
        fields = '__all__'


from .models import Patient
class PatientSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    uhid = serializers.CharField(read_only=True)
    class Meta:
        model = Patient
        fields = '__all__'


from .models import Doctor
class DoctorSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)

    class Meta:
        model = Doctor
        fields = '__all__'




from .models import Summary
class SummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Summary
        fields = '__all__'


from .models import EstimateBilling
class EstimateBillingSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstimateBilling
        fields = '__all__'


from .models import ReferenceDoctor
class ReferenceDoctorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceDoctor
        fields = '__all__'


from .models import OPPharmacyBill
class OPPharmacyBillSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = OPPharmacyBill
        fields = '__all__'

from .models import Billing
class BillingSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.firstName', read_only=True)
    patient_uhid = serializers.CharField(source='patient.uhid', read_only=True)
    
    class Meta:
        model = Billing
        fields = '__all__'

from .models import InsuranceProvider
class InsuranceProviderSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = InsuranceProvider
        fields = '__all__'
