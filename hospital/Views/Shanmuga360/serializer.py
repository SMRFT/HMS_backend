from rest_framework import serializers
from .models import registration360


class registration360Serializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    doctor_name = serializers.JSONField(required=False, default=list)
    medicine_name = serializers.JSONField(required=False, default=list)
    test_name = serializers.JSONField(required=False, default=list)
    service_list = serializers.JSONField(required=False, default=list)

    class Meta:
        model = registration360
        fields = '__all__'

    def to_internal_value(self, data):
        data_copy = data.copy() if hasattr(data, 'copy') else dict(data)

        # If client sends 'test', convert to 'test_name' and remove 'test' to prevent duplicate storage
        if 'test' in data_copy:
            test_val = data_copy.pop('test')
            if not data_copy.get('test_name'):
                data_copy['test_name'] = test_val

        # Standardize on lab_test_bill_number and eliminate duplicate labtestbillnumber
        if 'labtestbillnumber' in data_copy:
            legacy_bill = data_copy.pop('labtestbillnumber')
            if not data_copy.get('lab_test_bill_number'):
                data_copy['lab_test_bill_number'] = legacy_bill

        # Ensure decimal fields are numbers or None (not empty string)
        decimal_fields = [
            'delivery_fee', 'lab_delivery_fee', 'medicine_delivery_fee',
            'total_amount', 'doctor_fees', 'staff_nurse_fees',
            'doctor_staff_fees_remaining', 'medicine_charge', 'hospital_amount',
            'cash_collected_amount'
        ]
        for df in decimal_fields:
            if df in data_copy and (data_copy[df] == '' or data_copy[df] is None):
                data_copy[df] = 0.0

        # Always compute total delivery_fee from separate lab and medicine delivery fees
        l_fee = float(data_copy.get('lab_delivery_fee') or 0.0)
        m_fee = float(data_copy.get('medicine_delivery_fee') or 0.0)
        if (l_fee > 0 or m_fee > 0) or not data_copy.get('delivery_fee'):
            data_copy['delivery_fee'] = round(l_fee + m_fee, 2)

        # Sync app_booking and is_app_booking
        if 'is_app_booking' in data_copy and not data_copy.get('app_booking'):
            data_copy['app_booking'] = 'App' if data_copy['is_app_booking'] else 'Manual'
        if data_copy.get('app_booking') and 'is_app_booking' not in data_copy:
            data_copy['is_app_booking'] = str(data_copy['app_booking']).lower() == 'app'

        # Ensure array fields are stored as lists
        array_fields = ['doctor_name', 'medicine_name', 'test_name', 'service_list']
        for field in array_fields:
            val = data_copy.get(field)
            if isinstance(val, str):
                if val.strip():
                    data_copy[field] = [item.strip() for item in val.split(',') if item.strip()]
                else:
                    data_copy[field] = []
            elif val is None:
                data_copy[field] = []
            elif not isinstance(val, list):
                data_copy[field] = [val]

        return super().to_internal_value(data_copy)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Ensure array fields are always returned as lists in GET API
        array_fields = ['doctor_name', 'medicine_name', 'test_name', 'service_list']
        for field in array_fields:
            val = ret.get(field)
            if isinstance(val, str):
                if val.strip():
                    ret[field] = [item.strip() for item in val.split(',') if item.strip()]
                else:
                    ret[field] = []
            elif val is None:
                ret[field] = []

        # Backward compatibility: populate lab_test_bill_number if legacy record only had labtestbillnumber
        if not ret.get('lab_test_bill_number') and ret.get('labtestbillnumber'):
            ret['lab_test_bill_number'] = ret.get('labtestbillnumber')

        return ret