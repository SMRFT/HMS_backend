import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import ItemMaster, Department, Group, Category, GroupType
from .serializer import (
    ItemMasterSerializer, DepartmentSerializer, 
    GroupSerializer, CategorySerializer, GroupTypeSerializer
)

def get_financial_year_string():
    now = datetime.datetime.now()
    if now.month <= 3:
        return f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"
    else:
        return f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"

def generate_custom_id(model_class, id_field_name, prefix, sequence_length):
    fy_str = get_financial_year_string()
    base_prefix = f"{prefix}{fy_str}"
    
    last_record = model_class.objects.filter(**{f"{id_field_name}__startswith": base_prefix}).order_by('-created_date').first()
    
    if last_record:
        last_id = getattr(last_record, id_field_name)
        try:
            last_sequence = int(last_id.replace(base_prefix, ''))
            new_sequence = last_sequence + 1
        except ValueError:
            new_sequence = 1
    else:
        new_sequence = 1
        
    return f"{base_prefix}{new_sequence:0{sequence_length}d}"

# --- Item Master Views ---
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def item_master_list_create(request):
    if request.method == 'GET':
        items = ItemMaster.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = ItemMasterSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('item_id'):
            data['item_id'] = generate_custom_id(ItemMaster, 'item_id', 'ITM', 7)
            
        serializer = ItemMasterSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def item_master_detail(request, pk):
    try:
        item = ItemMaster.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Item not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = ItemMasterSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = ItemMasterSerializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "Item soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

# --- Department Views ---
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def department_list_create(request):
    if request.method == 'GET':
        items = Department.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = DepartmentSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('department_id'):
            data['department_id'] = generate_custom_id(Department, 'department_id', 'DPT', 5)
            
        serializer = DepartmentSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def department_detail(request, pk):
    try:
        item = Department.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Department not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = DepartmentSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = DepartmentSerializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "Department soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

# --- Group Views ---
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def group_list_create(request):
    if request.method == 'GET':
        items = Group.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = GroupSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('group_id'):
            data['group_id'] = generate_custom_id(Group, 'group_id', 'GRP', 5)
            
        serializer = GroupSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def group_detail(request, pk):
    try:
        item = Group.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Group not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = GroupSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = GroupSerializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "Group soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

# --- Category Views ---
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def category_list_create(request):
    if request.method == 'GET':
        items = Category.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = CategorySerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('category_id'):
            data['category_id'] = generate_custom_id(Category, 'category_id', 'CAT', 5)
            
        serializer = CategorySerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def category_detail(request, pk):
    try:
        item = Category.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "Category not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = CategorySerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = CategorySerializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "Category soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

# --- Group Type Views ---
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def group_type_list_create(request):
    if request.method == 'GET':
        items = GroupType.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = GroupTypeSerializer(items, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('group_type_id'):
            data['group_type_id'] = generate_custom_id(GroupType, 'group_type_id', 'GRPT', 5)
            
        serializer = GroupTypeSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def group_type_detail(request, pk):
    try:
        item = GroupType.objects.filter(pk=pk, is_active__in=[True]).first()
        if not item:
            return Response({"error": "GroupType not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = GroupTypeSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = GroupTypeSerializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        item.is_active = False
        item.save()
        return Response({"message": "GroupType soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
