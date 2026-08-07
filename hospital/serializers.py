from rest_framework import serializers
from decimal import Decimal, InvalidOperation
from bson import ObjectId

class ObjectIdField(serializers.Field):
    def to_representation(self, value):
        return str(value)

    def to_internal_value(self, data):
        try:
            return ObjectId(data)
        except:
            return data

from .models import ChemicalComposition
class ChemicalCompositionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ChemicalComposition
        fields = "__all__"
        read_only_fields = ["composition_id"]
from .models import ABHAProfile


        
from .models import PharmacyCategory,Cashcountershiftdetails
class PharmacyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PharmacyCategory
        fields = "__all__"
        read_only_fields = ["category_id"]

        
from .models import PharmacyItem,CashCounter
class CashCounterSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    counter_id = serializers.CharField(required=False, allow_blank=True)
    bill_type = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    class Meta:
        model = CashCounter
        fields = '__all__'

class PharmacyItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PharmacyItem
        fields = "__all__"
        read_only_fields = ["item_id"]


from .models import StockTransfer
class StockTransferSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model  = StockTransfer
        fields = "__all__"


from .models import PurchaseRequisition
class PurchaseRequisitionSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model  = PurchaseRequisition
        fields = "__all__"


from .models import PurchaseReturn
class PurchaseReturnSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    items = serializers.JSONField(required=False, default=list)
 
    class Meta:
        model  = PurchaseReturn
        fields = "__all__"
 
    def validate_status(self, value):
        valid = [
            "Returned",
            "Supplier Collected",
            "Partial Credit Note",
            "Credit Note Settled",
        ]
        if value not in valid:
            raise serializers.ValidationError(
                f"status must be one of {valid}"
            )
        return value
 
    def validate_items(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("items must be a list")
        valid_causes = [
            "Broken", "Damage", "Nearing Expiry", "Non Moving",
            "Price Difference", "Returns", "Shortage",
        ]
        for idx, item in enumerate(value):
            if not isinstance(item, dict):
                raise serializers.ValidationError(f"Item {idx + 1} must be an object")
            cause = item.get("cause_of_return", "")
            if cause and cause not in valid_causes:
                raise serializers.ValidationError(
                    f"Item {idx + 1}: cause_of_return '{cause}' is not valid"
                )
        return value

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

from rest_framework import serializers
from .models import PharmacyBilling

class PharmacyBillingSerializer(serializers.ModelSerializer):

    class Meta:
        model = PharmacyBilling
        fields = "__all__"

from .models import GRN
class GRNSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = GRN
        fields = '__all__'


from .models import MedicineRequisition
class MedicineRequisitionSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = MedicineRequisition
        fields = "__all__"


from .models import PhysicalStockEntry
class PhysicalStockEntrySerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = PhysicalStockEntry
        fields = "__all__"


from .models import PurchaseOrder
class PurchaseOrderSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model  = PurchaseOrder
        fields = "__all__"


from .models import Block, RoomCategory, Room, NursingStation, RoomKitItems, RoomServiceDescription
class BlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = "__all__"
        read_only_fields = [
            "block_id",
            "created_by",
            "created_date",
            "lastmodified_by",
            "lastmodified_date",
            "is_active"
        ]

class RoomCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomCategory
        fields = "__all__"
        read_only_fields = [
            "room_category_id",
            "created_by",
            "created_date",
            "lastmodified_by",
            "lastmodified_date",
            "is_active"
        ]

class NursingStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = NursingStation
        fields = "__all__"
        read_only_fields = [
            "ward_id",
            "created_by",
            "created_date",
            "lastmodified_by",
            "lastmodified_date",
            "is_active"
        ]
       
class RoomServiceDescriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomServiceDescription
        fields = "__all__"
        read_only_fields = [
            "description_id",
            "created_by",
            "created_date",
            "lastmodified_by",
            "lastmodified_date",
            "is_active"
        ]

class RoomKitItemsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomKitItems
        fields = "__all__"
        read_only_fields = [
            "kit_id",
            "created_by",
            "created_date",
            "lastmodified_by",
            "lastmodified_date",
            "is_active"
        ]

class RoomSerializer(serializers.ModelSerializer):
    services  = serializers.JSONField(required=False, allow_null=True, default=list)
    beds      = serializers.JSONField(required=False, allow_null=True, default=list)
    room_kits = serializers.JSONField(required=False, allow_null=True, default=list)
    class Meta:
        model  = Room
        fields = "__all__"
        read_only_fields = [
            "kit_id",
            "created_by",
            "created_date",
            "lastmodified_by",
            "lastmodified_date",
            "is_active"
        ]

    # ── Field-level validators ────────────────────────────────────────────────
 
    def validate_room_status(self, value):
        allowed = {"Available", "Maintenance", "Blocked"}
        if value and value not in allowed:
            raise serializers.ValidationError(
                f"room_status must be one of: {', '.join(sorted(allowed))}"
            )
        return value or "Available"
 
    def validate_capacity(self, value):
        if value is not None and value < 1:
            raise serializers.ValidationError("Capacity must be at least 1.")
        return value
 
    def validate_services(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Services must be a list.")
        return value
 
    def validate_beds(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Beds must be a list.")
        for i, bed in enumerate(value):
            if not isinstance(bed, dict):
                raise serializers.ValidationError(f"Bed at index {i} must be an object.")
            if not bed.get("bed_number", "").strip():
                raise serializers.ValidationError(
                    f"Bed at index {i} is missing 'bed_number'."
                )
            # Ensure bed_status is set correctly from blocked flag
            blocked = bool(bed.get("blocked", False))
            bed["blocked"] = blocked
            bed["bed_status"] = "Blocked" if blocked else "Available"
            if blocked and not bed.get("blocked_reason", "").strip():
                raise serializers.ValidationError(
                    f"Bed '{bed['bed_number']}' is blocked but has no blocking reason."
                )
        return value
 
    def validate_room_kits(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Room kits must be a list.")
        return value
    

from .models import Patient, InsuranceProvider, Admission
class ABHAProfileSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = ABHAProfile
        fields = "__all__"



class PatientSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    uhid = serializers.CharField(read_only=True)
    class Meta:
        model = Patient
        fields = '__all__'

class InsuranceProviderSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = InsuranceProvider
        fields = '__all__'

class AdmissionSerializer(serializers.ModelSerializer):
    patient_details = serializers.SerializerMethodField()
    insurance_details = serializers.SerializerMethodField()
    registration_details = serializers.SerializerMethodField()
    room_info = serializers.SerializerMethodField()

    class Meta:
        model = Admission
        fields = "__all__"

    def get_patient_details(self, obj):
        patient = Patient.objects.filter(uhid=obj.uhid).first()
        if patient:
            return PatientSerializer(patient).data
        return None 

    def get_insurance_details(self, obj):
        # Fetch insurance details by comparing company_code from patient
        patient = Patient.objects.filter(uhid=obj.uhid).first()
        if patient and patient.company_code:
            insurance = InsuranceProvider.objects.filter(company_code=patient.company_code).first()
            if insurance:
                return {
                    "company_code": insurance.company_code,
                    "company_name": insurance.company_name,
                }
        return None

    def get_registration_details(self, obj):
        # Fetch registration details from patient record
        patient = Patient.objects.filter(uhid=obj.uhid).first()
        if patient:
            return {
                "registration_date": patient.registration_date,
                "customer_type": patient.customer_type,
            }
        return None

    def get_room_info(self, obj):
        # Logic to extract current room/bed from room_details
        import json
        details = obj.room_details
        if isinstance(details, str):
            try: details = json.loads(details)
            except: details = []
        
        if details:
            for r in reversed(details):
                if isinstance(r, dict) and r.get("is_roomActive"):
                    return {
                        "room_no": r.get("roomNo"),
                        "bed_no": r.get("bedNo")
                    }
        return {}



from .models import DischargeBilling
class DischargeBillingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DischargeBilling
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

class CashcountershiftdetailsSerializer(serializers.ModelSerializer):

    class Meta:
        model = Cashcountershiftdetails
        fields = '__all__'

    def validate_OpeningBalance(self, value):
        return self._clean_decimal(value)

    def validate_ClosingBalance(self, value):
        return self._clean_decimal(value)

    def validate_collected_Amount(self, value):
        return self._clean_decimal(value)

    def validate_PettyCashBalance(self, value):
        return self._clean_decimal(value)

    def validate_RemittedToBank(self, value):
        return self._clean_decimal(value)

    def validate_SubmittedToAccount(self, value):
        return self._clean_decimal(value)

    def validate_HandOverAmount(self, value):
        return self._clean_decimal(value)

    def validate_PendingAmount(self, value):
        return self._clean_decimal(value)

    def validate_IPAdvanceAmount(self, value):
        return self._clean_decimal(value)

    def validate_SalesReturnAmount(self, value):
        return self._clean_decimal(value)

    def _clean_decimal(self, value):
        if value is None or value == "":
            return Decimal("0.00")

        raw = str(value)

        # Remove all types of quotes and whitespace
        for char in ['"', "'", "“", "”", "‘", "’", "₹", " "]:
            raw = raw.replace(char, "")

        if not raw:
            return Decimal("0.00")

        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            # Fallback for complex strings: try to extract numeric part
            import re
            numeric_part = re.sub(r'[^\d.]', '', raw)
            try:
                return Decimal(numeric_part) if numeric_part else Decimal("0.00")
            except:
                return Decimal("0.00")


from .models import CustomerType
class CustomerTypeSerializer(serializers.ModelSerializer):
    patient_count = serializers.SerializerMethodField()
    class Meta:
        model = CustomerType
        fields = '__all__'
        read_only_fields = ["type_id"]

    def get_patient_count(self, obj):
        from .models import Patient
        return Patient.objects.filter(customer_type=obj.type_name).count()


from .models import SurgerySchedule
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


from .models import ReceiptAndPayment, CashCounter
class ReceiptAndPaymentSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = ReceiptAndPayment
        fields = '__all__'



from .models import SalesReturn
class SalesReturnSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model   = SalesReturn
        exclude = ['lastmodified_by', 'lastmodified_date']

from .models import CashCounterCollection
class CashCounterCollectionSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = CashCounterCollection
        fields = '__all__'



from .models import DialysisDischargeSummary
class DialysisDischargeSummarySerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = DialysisDischargeSummary
        fields = '__all__'




from .models import licence_master
class licence_masterSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    class Meta:
        model = licence_master
        fields = '__all__'


from .models import licencemasterdetails
class licencemasterdetailsSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    s_no = serializers.IntegerField(read_only=True)
    class Meta:
        model = licencemasterdetails
        fields = '__all__'

from rest_framework import serializers
from .models import LabInventory

class LabInventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LabInventory
        fields = '__all__'


from rest_framework import serializers
from .models import RaiseIndent

class RaiseIndentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RaiseIndent
        fields = "__all__"
        read_only_fields = ["indent_no"]  # auto-generated in model.save()



from .models import DoctorFeeCuts
class DoctorFeeCutsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorFeeCuts
        fields = '__all__'
