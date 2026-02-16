from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.views.decorators.csrf import csrf_exempt

from ..models import Block, RoomCategory, Room, Admission, RoomServiceDescription, RoomKit, RoomKitDescription
from ..serializers import (
    BlockSerializer,
    RoomCategorySerializer,
    RoomSerializer,
    RoomServiceDescriptionSerializer,
    RoomKitSerializer,
    RoomKitDescriptionSerializer
)

# MongoDB connection removed - using Django ORM


# --------------------------------------------------
# BLOCK
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def block_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                block = Block.objects.get(block_id=pk)
                if not block.is_active:
                    return Response({"error": "Block not found"}, status=404)
            except Block.DoesNotExist:
                return Response({"error": "Block not found"}, status=404)
            except (ValueError, TypeError):
                return Response({"error": "Invalid Block ID"}, status=400)

            serializer = BlockSerializer(block)
            return Response(serializer.data)

        # List – filter in Python to avoid Djongo boolean filter bug
        all_blocks = Block.objects.all().order_by("block_id")
        blocks = [b for b in all_blocks if b.is_active]
        serializer = BlockSerializer(blocks, many=True)
        return Response(serializer.data)

    # ── POST ─────────────────────────────────────────────────────────────────
    if request.method == "POST":
        serializer = BlockSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ──────────────────────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Block ID required"}, status=400)
        try:
            block = Block.objects.get(block_id=pk)
            if not block.is_active:
                return Response({"error": "Block not found"}, status=404)
        except Block.DoesNotExist:
            return Response({"error": "Block not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Block ID"}, status=400)

        serializer = BlockSerializer(block, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # ── DELETE ───────────────────────────────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Block ID required"}, status=400)
        try:
            block = Block.objects.get(block_id=pk)
            if not block.is_active:
                return Response({"error": "Block not found"}, status=404)
        except Block.DoesNotExist:
            return Response({"error": "Block not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Block ID"}, status=400)

        block.is_active = False
        block.lastmodified_by = user_id
        block.save()
        return Response({"message": "Deleted successfully"}, status=200)
        

# --------------------------------------------------
# ROOM CATEGORY
# --------------------------------------------------
# --------------------------------------------------
# ROOM CATEGORY
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_category_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ─────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                category = RoomCategory.objects.get(room_category_id=pk)
                if not category.is_active:
                    return Response({"error": "Room category not found"}, status=404)
            except RoomCategory.DoesNotExist:
                return Response({"error": "Room category not found"}, status=404)
            except (ValueError, TypeError):
                return Response({"error": "Invalid Room Category ID"}, status=400)

            serializer = RoomCategorySerializer(category)
            return Response(serializer.data)

        # List – filter in Python (Djongo boolean workaround)
        all_categories = RoomCategory.objects.all().order_by("room_category_id")
        categories = [c for c in all_categories if c.is_active]
        serializer = RoomCategorySerializer(categories, many=True)
        return Response(serializer.data)

    # ── POST ────────────────────────────────────────
    if request.method == "POST":
        serializer = RoomCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ─────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Room Category ID required"}, status=400)
        try:
            category = RoomCategory.objects.get(room_category_id=pk)
            if not category.is_active:
                return Response({"error": "Room category not found"}, status=404)
        except RoomCategory.DoesNotExist:
            return Response({"error": "Room category not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Room Category ID"}, status=400)

        serializer = RoomCategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # ── DELETE ──────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Room Category ID required"}, status=400)
        try:
            category = RoomCategory.objects.get(room_category_id=pk)
            if not category.is_active:
                return Response({"error": "Room category not found"}, status=404)
        except RoomCategory.DoesNotExist:
            return Response({"error": "Room category not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Room Category ID"}, status=400)

        category.is_active = False
        category.lastmodified_by = user_id
        category.save()
        return Response({"message": "Deleted successfully"}, status=200)



# --------------------------------------------------
# ROOM (with Nested Beds, Services, Kits)
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_view(request, pk=None):
    user_id = request.headers.get("auth-user-id", "system")

    # ==================== GET ====================
    if request.method == "GET":
        if pk:
            try:
                room = Room.objects.get(id=pk)
                if not room.is_active:
                    return Response({"error": "Room not found"}, status=404)
            except Room.DoesNotExist:
                return Response({"error": "Room not found"}, status=404)

            serializer = RoomSerializer(room)
            return Response(serializer.data)

        # Workaround for Djongo DatabaseError
        all_rooms = Room.objects.all()
        rooms = [r for r in all_rooms if r.is_active]
        serializer = RoomSerializer(rooms, many=True)
        return Response(serializer.data)

    # ==================== POST ====================
    elif request.method == "POST":
        data = request.data.copy()
        
        # Extract nested data
        beds_data = data.pop('beds', [])
        services_data = data.pop('services', [])
        kits_data = data.pop('kits', [])

        serializer = RoomSerializer(data=data)
        if serializer.is_valid():
            room = serializer.save(
                created_by=user_id,
                lastmodified_by=user_id,
                is_active=True
            )
            
            # Create Beds
            for b in beds_data:
                Bed.objects.create(
                    room=room,
                    bed_number=b.get('bed_number'),
                    bed_status=b.get('bed_status', 'Available'),
                    blocked=b.get('blocked', 'No'),
                    blocked_reason=b.get('blocked_reason', ''),
                    is_active=True,
                    created_by=user_id,
                    lastmodified_by=user_id
                )

            # Create Services
            for s in services_data:
                RoomService.objects.create(
                    room=room,
                    description=s.get('description'), # This is the ID of RoomServiceDescription
                    priority=s.get('priority'),
                    amount=s.get('amount'),
                    chargeable_for_bystander=s.get('chargeable_for_bystander', False),
                    chargeable_for_booking=s.get('chargeable_for_booking', False),
                    enable_this_service=s.get('enable_this_service', True),
                    doctors_fee=s.get('doctors_fee', False),
                    is_active=True
                )

            # Create Kits
            for k in kits_data:
                RoomKit.objects.create(
                    room=room,
                    kit_item=k.get('kit_item'), # ID of RoomKitDescription
                    priority=k.get('priority'),
                    amount=k.get('amount'),
                    enable_item=k.get('enable_item', True),
                    is_active=True
                )

            return Response(RoomSerializer(room).data, status=201)

        return Response(serializer.errors, status=400)

    # ==================== PUT ====================
    elif request.method == "PUT":
        try:
            room = Room.objects.get(id=pk)
            if not room.is_active:
                return Response({"error": "Room not found"}, status=404)
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)

        data = request.data.copy()
        beds_data = data.pop('beds', None)
        services_data = data.pop('services', None)
        kits_data = data.pop('kits', None)

        serializer = RoomSerializer(room, data=data, partial=True)
        if serializer.is_valid():
            room = serializer.save(
                lastmodified_by=user_id
            )

            # --- Update Beds ---
            if beds_data is not None:
                existing_beds = {str(b.id): b for b in Bed.objects.filter(room=room, is_active=True)}
                incoming_ids = set()

                for b_data in beds_data:
                    b_id = b_data.get('id')
                    if b_id and b_id in existing_beds:
                        # Update existing
                        bed = existing_beds[b_id]
                        bed.bed_number = b_data.get('bed_number', bed.bed_number)
                        bed.bed_status = b_data.get('bed_status', bed.bed_status)
                        bed.blocked = b_data.get('blocked', bed.blocked)
                        bed.blocked_reason = b_data.get('blocked_reason', bed.blocked_reason)
                        bed.lastmodified_by = user_id
                        bed.save()
                        incoming_ids.add(b_id)
                    else:
                        # Create new
                        new_bed = Bed.objects.create(
                            room=room,
                            bed_number=b_data.get('bed_number'),
                            bed_status=b_data.get('bed_status', 'Available'),
                            blocked=b_data.get('blocked', 'No'),
                            blocked_reason=b_data.get('blocked_reason', ''),
                            is_active=True,
                            created_by=user_id,
                            lastmodified_by=user_id
                        )
                        incoming_ids.add(str(new_bed.id))
                
                # Soft Delete missing
                for b_id, bed in existing_beds.items():
                    if b_id not in incoming_ids:
                        bed.is_active = False
                        bed.lastmodified_by = user_id
                        bed.save()

            # --- Update Services ---
            if services_data is not None:
                existing_services = {str(s.id): s for s in RoomService.objects.filter(room=room, is_active=True)}
                incoming_ids = set()
                
                for s_data in services_data:
                    s_id = s_data.get('id')
                    if s_id and s_id in existing_services:
                         svc = existing_services[s_id]
                         svc.description = s_data.get('description', svc.description)
                         svc.priority = s_data.get('priority', svc.priority)
                         svc.amount = s_data.get('amount', svc.amount)
                         svc.chargeable_for_bystander = s_data.get('chargeable_for_bystander', svc.chargeable_for_bystander)
                         svc.chargeable_for_booking = s_data.get('chargeable_for_booking', svc.chargeable_for_booking)
                         svc.enable_this_service = s_data.get('enable_this_service', svc.enable_this_service)
                         svc.doctors_fee = s_data.get('doctors_fee', svc.doctors_fee)
                         svc.save()
                         incoming_ids.add(s_id)
                    else:
                        new_svc = RoomService.objects.create(
                            room=room,
                            description=s_data.get('description'),
                            priority=s_data.get('priority'),
                            amount=s_data.get('amount'),
                            chargeable_for_bystander=s_data.get('chargeable_for_bystander', False),
                            chargeable_for_booking=s_data.get('chargeable_for_booking', False),
                            enable_this_service=s_data.get('enable_this_service', True),
                            doctors_fee=s_data.get('doctors_fee', False),
                            is_active=True
                        )
                        incoming_ids.add(str(new_svc.id))
                
                for s_id, svc in existing_services.items():
                    if s_id not in incoming_ids:
                        svc.is_active = False
                        svc.save()

            # --- Update Kits ---
            if kits_data is not None:
                existing_kits = {str(k.id): k for k in RoomKit.objects.filter(room=room, is_active=True)}
                incoming_ids = set()

                for k_data in kits_data:
                    k_id = k_data.get('id')
                    if k_id and k_id in existing_kits:
                        kit = existing_kits[k_id]
                        kit.kit_item = k_data.get('kit_item', kit.kit_item)
                        kit.priority = k_data.get('priority', kit.priority)
                        kit.amount = k_data.get('amount', kit.amount)
                        kit.enable_item = k_data.get('enable_item', kit.enable_item)
                        kit.save()
                        incoming_ids.add(k_id)
                    else:
                        new_kit = RoomKit.objects.create(
                            room=room,
                            kit_item=k_data.get('kit_item'),
                            priority=k_data.get('priority'),
                            amount=k_data.get('amount'),
                            enable_item=k_data.get('enable_item', True),
                            is_active=True
                        )
                        incoming_ids.add(str(new_kit.id))

                for k_id, kit in existing_kits.items():
                    if k_id not in incoming_ids:
                        kit.is_active = False
                        kit.save()

            return Response(RoomSerializer(room).data)

        return Response(serializer.errors, status=400)

    # ==================== DELETE ====================
    elif request.method == "DELETE":
        try:
            room = Room.objects.get(id=pk)
            if not room.is_active:
                return Response({"error": "Room not found"}, status=404)
            
            room.is_active = False
            room.lastmodified_by = user_id
            room.save()

            # Soft delete sub-items
            Bed.objects.filter(room=room).update(is_active=False)
            RoomService.objects.filter(room=room).update(is_active=False)
            RoomKit.objects.filter(room=room).update(is_active=False)

            return Response({"message": "Deleted successfully"})
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)


# --------------------------------------------------
# BED
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def bed_view(request, pk=None):

    if request.method == "GET":
        if pk:
            try:
                bed = Bed.objects.get(id=pk)
                if not bed.is_active:
                    return Response({"error": "Bed not found"}, status=404)
            except Bed.DoesNotExist:
                return Response({"error": "Bed not found"}, status=404)

            serializer = BedSerializer(bed)
            return Response(serializer.data)

        # Workaround for Djongo DatabaseError
        all_beds = Bed.objects.all()
        beds = [b for b in all_beds if b.is_active]
        serializer = BedSerializer(beds, many=True)
        return Response(serializer.data)

    elif request.method == "POST":
        serializer = BedSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(
                created_by=request.headers.get('auth-user-id', 'system'),
                lastmodified_by=request.headers.get('auth-user-id', 'system'),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)

    elif request.method == "PUT":
        try:
            bed = Bed.objects.get(id=pk)
            if not bed.is_active:
                return Response({"error": "Bed not found"}, status=404)
        except Bed.DoesNotExist:
            return Response({"error": "Bed not found"}, status=404)

        serializer = BedSerializer(bed, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(
                lastmodified_by=request.headers.get('auth-user-id', 'system')
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=400)

    elif request.method == "DELETE":
        try:
            bed = Bed.objects.get(id=pk)
            if not bed.is_active:
                return Response({"error": "Bed not found"}, status=404)
            
            bed.is_active = False
            bed.lastmodified_by = request.headers.get('auth-user-id', 'system')
            bed.save()
            return Response({"message": "Deleted successfully"})
        except Bed.DoesNotExist:
            return Response({"error": "Bed not found"}, status=404)


@api_view(['GET'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def roomservice_description_view(request, pk=None):
    try:
        # 🔹 GET Single
        if pk:
            try:
                description = RoomServiceDescription.objects.get(pk=pk, is_active=True)
            except RoomServiceDescription.DoesNotExist:
                return Response({"error": "Not found"}, status=404)
            except Exception:
                return Response({"error": "Invalid ID"}, status=400)

            serializer = RoomServiceDescriptionSerializer(description)
            return Response(serializer.data)

        # 🔹 GET All Active
        descriptions = RoomServiceDescription.objects.filter(is_active=True)
        serializer = RoomServiceDescriptionSerializer(descriptions, many=True)
        return Response(serializer.data)

    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)

# --------------------------------------------------
# SERVICE
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def service_view(request, pk=None):

    # ==================== GET ====================
    if request.method == "GET":
        if pk:
            try:
                service = RoomService.objects.get(id=pk)
                if not service.is_active:
                    return Response({"error": "Service not found"}, status=404)
            except RoomService.DoesNotExist:
                return Response({"error": "Service not found"}, status=404)

            serializer = RoomServiceSerializer(service)
            return Response(serializer.data)

        # Workaround for Djongo DatabaseError
        all_services = RoomService.objects.all().order_by("priority")
        services = [s for s in all_services if s.is_active]
        serializer = RoomServiceSerializer(services, many=True)
        return Response(serializer.data)

    # ==================== POST ====================
    elif request.method == "POST":
        serializer = RoomServiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(
                is_active=True
            )
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ==================== PUT ====================
    elif request.method == "PUT":
        if not pk:
            return Response({"error": "ID required"}, status=400)

        try:
            service = RoomService.objects.get(id=pk)
            if not service.is_active:
                return Response({"error": "Service not found"}, status=404)
        except RoomService.DoesNotExist:
            return Response({"error": "Service not found"}, status=404)

        serializer = RoomServiceSerializer(service, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=400)

    # ==================== DELETE ====================
    elif request.method == "DELETE":
        if not pk:
            return Response({"error": "ID required"}, status=400)

        try:
            service = RoomService.objects.get(id=pk)
            if not service.is_active:
                return Response({"error": "Service not found"}, status=404)
            
            service.is_active = False
            # RoomService model does not inherit form AuditModel, so we rely on updated_at
            service.save()
            return Response({"message": "Deleted successfully"})
        except RoomService.DoesNotExist:
            return Response({"error": "Service not found"}, status=404)


# --------------------------------------------------
# ROOM ENQUIRY (Block → Floor → Room → Bed)
# --------------------------------------------------
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_enquiry_view(request):

    result = []

    blocks = Block.objects.filter(is_active=True)

    for block in blocks:
        rooms = Room.objects.filter(
            block=block.block_name,
            is_active=True
        ).order_by("floor")

        floor_map = {}

        for room in rooms:
            floor = room.floor or 0
            floor_map.setdefault(floor, [])

            beds = Bed.objects.filter(
                room=room,
                is_active=True
            )

            room_data = RoomSerializer(room).data
            room_data["beds"] = BedSerializer(beds, many=True).data

            floor_map[floor].append(room_data)

        result.append({
            "block": BlockSerializer(block).data,
            "floors": floor_map
        })

    return Response(result)


# --------------------------------------------------
# ROOM SHIFTING
# --------------------------------------------------
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_view(request):
    user_id = request.headers.get("auth-user-id", "system")

    # ==================== GET (Search Admission) ====================
    if request.method == "GET":
        query = request.GET.get("search") # UHID or IP

        if not query:
            return Response({"error": "Search query (UHID or IP) required"}, status=400)

        # Try to find active admission by UHID or IP
        admissions = Admission.objects.filter(is_active=True).filter(
            models.Q(uhid__icontains=query) | models.Q(ipNumber__icontains=query)
        )
        
        if not admissions.exists():
             return Response({"error": "Active admission not found"}, status=404)
        
        # Return the first match or list? Let's return list if needed, but simplistic approach first match
        admission = admissions.first()

        return Response({
            "uhid": admission.uhid,
            "ip_no": admission.ipNumber,
            "patient_name": f"{admission.firstName} {admission.lastName}",
            "current_room_no": admission.roomNo,
            "current_bed_no": admission.bedNo,
        })

    # ==================== POST (Shift Room) ====================
    elif request.method == "POST":
        uhid = request.data.get("uhid")
        ip_no = request.data.get("ip_no")
        new_room_no = request.data.get("newRoomNo")
        new_bed_no = request.data.get("newBedNo")

        if not (uhid or ip_no) or not (new_room_no and new_bed_no):
            return Response({"error": "Missing required fields"}, status=400)

        try:
            if uhid:
                admission = Admission.objects.get(uhid=uhid, is_active=True)
            else:
                admission = Admission.objects.get(ipNumber=ip_no, is_active=True)
        except Admission.DoesNotExist:
            return Response({"error": "Active admission not found"}, status=404)
        
        old_room_no = admission.roomNo
        old_bed_no = admission.bedNo

        # 1. Update Admission
        admission.roomNo = new_room_no
        admission.bedNo = new_bed_no
        admission.lastmodified_by = user_id
        admission.save()

        # 2. Update Old Bed (Make Available)
        if old_room_no and old_bed_no:
            try:
                # Find room first (roomNo is unique in Room model)
                old_room = Room.objects.get(room_number=old_room_no, is_active=True)
                old_bed = Bed.objects.get(room=old_room, bed_number=old_bed_no, is_active=True)
                old_bed.bed_status = "Available"
                old_bed.blocked = "No"
                old_bed.save()
            except (Room.DoesNotExist, Bed.DoesNotExist):
                pass # Log error or ignore if data inconsistent

        # 3. Update New Bed (Make Occupied)
        try:
            new_room = Room.objects.get(room_number=new_room_no, is_active=True)
            new_bed = Bed.objects.get(room=new_room, bed_number=new_bed_no, is_active=True)
            new_bed.bed_status = "Occupied"
            new_bed.save()
        except Room.DoesNotExist:
             return Response({"error": f"New Room {new_room_no} not found"}, status=404)
        except Bed.DoesNotExist:
             return Response({"error": f"New Bed {new_bed_no} not found"}, status=404)

        return Response({"message": "Room shifted successfully"})


# --------------------------------------------------
# ROOM KIT DESCRIPTION
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_kit_description_view(request, pk=None):
    user_id = request.headers.get("auth-user-id", "system")

    if request.method == "GET":
        if pk:
            try:
                desc = RoomKitDescription.objects.get(id=pk)
                if not desc.is_active:
                     return Response({"error": "Description not found"}, status=404)
                serializer = RoomKitDescriptionSerializer(desc)
                return Response(serializer.data)
            except RoomKitDescription.DoesNotExist:
                 return Response({"error": "Description not found"}, status=404)
        
        all_descs = RoomKitDescription.objects.all()
        descs = [d for d in all_descs if d.is_active]
        serializer = RoomKitDescriptionSerializer(descs, many=True)
        return Response(serializer.data)

    elif request.method == "POST":
        serializer = RoomKitDescriptionSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(
                created_by=user_id,
                lastmodified_by=user_id,
                is_active=True
            )
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    elif request.method == "PUT":
        try:
            desc = RoomKitDescription.objects.get(id=pk)
            if not desc.is_active:
                return Response({"error": "Description not found"}, status=404)
        except RoomKitDescription.DoesNotExist:
            return Response({"error": "Description not found"}, status=404)

        serializer = RoomKitDescriptionSerializer(desc, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    elif request.method == "DELETE":
        try:
            desc = RoomKitDescription.objects.get(id=pk)
            if not desc.is_active:
                return Response({"error": "Description not found"}, status=404)
            desc.is_active = False
            desc.lastmodified_by = user_id
            desc.save()
            return Response({"message": "Deleted successfully"})
        except RoomKitDescription.DoesNotExist:
            return Response({"error": "Description not found"}, status=404)