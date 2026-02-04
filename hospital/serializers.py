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


from .models import IPPharmacyStock, OPPharmacyStock,Vendor

# IP Pharmacy Stock Serializer
class IPPharmacyStockSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = IPPharmacyStock
        fields = '__all__'


# OP Pharmacy Stock Serializer
class OPPharmacyStockSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = OPPharmacyStock
        fields = '__all__'


# Vendor Serializer
class VendorSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = Vendor
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


from .models import Admission
class AdmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admission
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