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
    class Meta:
        model = PharmacyStock
        fields = "__all__"
        read_only_fields = ["stock_id"]


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
class AdmissionSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = Admission
        fields = '__all__'


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


from .models import CTReport
class CTReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = CTReport
        fields = ['age', 'date', 'gender', 'impression', 'investigation', 'patientId', 'patientName', 'approve','approve_time']


from .models import MRIReport
class MRIReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = MRIReport
        fields = ['patientId', 'patientName', 'age', 'gender', 'investigation', 'impression', 'approve', 'approve_time']


from .models import USGReport
class USGReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = USGReport
        fields = ['patientId', 'patientName', 'age', 'gender', 'investigation', 'impression', 'approve', 'approve_time']


from .models import XRayReport
class XRayReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = XRayReport
        fields = ['patientId', 'patientName', 'age', 'gender', 'investigation', 'impression', 'approve', 'approve_time']


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


from .models import InvestBilling
class InvestBillingSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestBilling
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
