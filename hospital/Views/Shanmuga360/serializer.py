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

        # Support both labtestbillnumber and lab_test_bill_number
        if 'labtestbillnumber' in data_copy and not data_copy.get('lab_test_bill_number'):
            data_copy['lab_test_bill_number'] = data_copy['labtestbillnumber']
        if 'lab_test_bill_number' in data_copy and not data_copy.get('labtestbillnumber'):
            data_copy['labtestbillnumber'] = data_copy['lab_test_bill_number']

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
        return ret