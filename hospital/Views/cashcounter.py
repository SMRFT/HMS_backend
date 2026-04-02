from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
import traceback
from datetime import datetime

from ..models import Cashcountershiftdetails
from ..serializers import CashcountershiftdetailsSerializer


# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission
from rest_framework.decorators import api_view, permission_classes


# =========================================
# 🔢 SHIFT NUMBER GENERATOR (DJONGO SAFE)
# =========================================
def generate_shift_no():

    now = datetime.now()

    # Financial year (NO HYPHEN)
    if now.month >= 4:
        start = now.year
        end = now.year + 1
    else:
        start = now.year - 1
        end = now.year

    fy = f"{str(start)[-2:]}{str(end)[-2:]}"   # ✅ 2526

    shifts = Cashcountershiftdetails.objects.filter(
        shiftno__startswith=fy
    )

    last_number = 0

    for s in shifts:
        try:
            num = int(s.shiftno.split("/")[-1])
            if num > last_number:
                last_number = num
        except:
            pass

    new_number = last_number + 1

    return f"{fy}/{str(new_number).zfill(6)}"   

# =========================================
# 🚀 MAIN API
# =========================================
@api_view(["POST", "PATCH"])
@permission_classes(HasRoleAndDataPermission)
def cash_counter_shiftdetails(request):
    data = request.data

    try:

        # =====================================
        # 🟢 START SHIFT (POST)
        # =====================================
        if request.method == "POST":

            shift_no = generate_shift_no()

            payload = {
                "shiftno": shift_no,  # ✅ GENERATED
                "CashierID": data.get("CashierID"),
                "CashCounter": data.get("CashCounter"),
                "OpeningBalance": data.get("OpeningBalance", 0),
                "ShiftStatus": "active",
                "StartingTime": data.get("StartingTime"),
                "is_active": True,
            }

            serializer = CashcountershiftdetailsSerializer(data=payload)

            if serializer.is_valid():
                serializer.save(branch_code=data.get("branch_code"))

                return Response({
                    "success": True,
                    "message": "Shift started successfully",
                    "shiftno": shift_no,   # ✅ send to frontend
                    "data": serializer.data
                })

            return Response({
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            })

        # =====================================
        # 🔴 STOP SHIFT (PATCH)
        # =====================================
        elif request.method == "PATCH":

            shift_no = data.get("shiftno")

            if not shift_no:
                return Response({
                    "success": False,
                    "message": "shiftno is required"
                })

            # 🔹 Fetch using primary key (SAFE)
            try:
                shift = Cashcountershiftdetails.objects.get(shiftno=shift_no)
            except Cashcountershiftdetails.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Shift not found"
                })

            # 🔹 Update values
            shift.ClosingBalance = data.get("ClosingBalance", 0)
            shift.closingTime    = data.get("closingTime") or timezone.now()
            shift.ShiftStatus    = "completed"
            shift.is_active      = False

            shift.save()

            return Response({
                "success": True,
                "message": "Shift closed successfully",
                "data": CashcountershiftdetailsSerializer(shift).data
            })

    except Exception as e:
        print("ERROR:", traceback.format_exc())

        return Response({
            "success": False,
            "message": str(e)
        })





from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from ..models import Cashcountershiftdetails
from ..serializers import CashcountershiftdetailsSerializer

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_active_shift(request):
    try:
        branch_code = str(request.GET.get("branch_code", "")).strip()
        cashier_id  = str(request.GET.get("CashierID", "")).strip()
        cash_counter = request.GET.get("CashCounter")

        if not branch_code or not cashier_id:
            return Response({
                "success": False,
                "message": "branch_code and CashierID are required"
            }, status=400)

        # ✅ STEP-BY-STEP FILTER (Djongo safe)
        queryset = Cashcountershiftdetails.objects.all()

        queryset = queryset.filter(branch_code=branch_code)
        queryset = queryset.filter(CashierID=cashier_id)
        queryset = queryset.filter(is_active=True)
        queryset = queryset.filter(ShiftStatus="active")

        if cash_counter:
            queryset = queryset.filter(CashCounter=cash_counter)

        shift = queryset.first()

        if not shift:
            return Response({
                "success": False,
                "message": "No active shift found"
            })

        serializer = CashcountershiftdetailsSerializer(shift)

        return Response({
            "success": True,
            "data": serializer.data
        })

    except Exception as e:
        traceback.print_exc()
        return Response({
            "success": False,
            "message": str(e) or "Server error"
        }, status=500)