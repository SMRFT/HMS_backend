from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
import traceback
from datetime import datetime
from bson.decimal128 import Decimal128
from decimal import Decimal

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

# =====================================================
# ✅ DECIMAL FIX (Mongo + Django safe)
# =====================================================
def convert_decimal(value):
    if value is None:
        return None

    if isinstance(value, Decimal128):
        return float(value.to_decimal())

    if isinstance(value, Decimal):
        return float(value)

    return float(value)


# =====================================================
# ✅ RESPONSE FORMATTER
# =====================================================
def format_shift_response(shift):
    return {
        "shiftno": shift.shiftno,
        "CashierID": shift.CashierID,
        "CashCounter": shift.CashCounter,

        "OpeningBalance": convert_decimal(shift.OpeningBalance),
        "ClosingBalance": convert_decimal(shift.ClosingBalance),

        "ShiftStatus": shift.ShiftStatus,

        # ✅ FORMAT DATE TIME FOR UI
        "StartingTime": shift.StartingTime.strftime("%Y-%m-%d %H:%M:%S") if shift.StartingTime else None,
        "closingTime": shift.closingTime.strftime("%Y-%m-%d %H:%M:%S") if shift.closingTime else None,

        "date": str(shift.date),

        "hospital_code": shift.hospital_code,
        "branch_code": shift.branch_code,
        "outlet_code": shift.outlet_code,

        "is_active": shift.is_active,
    }

from bson.decimal128 import Decimal128
from decimal import Decimal

def convert_decimal128(value):
    if isinstance(value, Decimal128):
        return value.to_decimal()
    return value

# =====================================================
# ✅ MAIN API
# =====================================================
@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def cash_counter_shiftdetails(request):

    data = request.data

    # ✅ AUTH DATA
    employee_id   = data.get("auth-user-id")
    hospital_code = data.get("auth-hospital-code")
    branch_code   = data.get("auth-branch-code")
    outlet_code   = data.get("auth-outlet-code")

    if not employee_id:
        return Response({
            "success": False,
            "message": "User not authenticated"
        })

    # =====================================================
    # ✅ CREATE SHIFT (POST)
    # =====================================================
    if request.method == "POST":

        shift_no = generate_shift_no()

        opening_balance = convert_decimal128(data.get("OpeningBalance", 0))

        payload = {
            "shiftno": shift_no,
            "CashierID": employee_id,
            "CashCounter": data.get("CashCounter"),
            "OpeningBalance": opening_balance,
            "StartingTime": data.get("StartingTime"),
            "ShiftStatus": "active",

            "created_by": employee_id,
            "created_date": timezone.now(),
            "date": timezone.now().date(),

            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "created_br": branch_code,

            "is_active": True,
        }

        print("POST PAYLOAD:", payload)

        serializer = CashcountershiftdetailsSerializer(data=payload)

        if serializer.is_valid():
            serializer.save()

            shift = Cashcountershiftdetails.objects.get(shiftno=shift_no)

            return Response({
                "success": True,
                "message": "Shift opened successfully",
                "data": format_shift_response(shift)
            })

        return Response({
            "success": False,
            "message": "Validation error",
            "errors": serializer.errors
        })

    # =====================================================
    # ✅ CLOSE SHIFT (PATCH)
    # =====================================================
    elif request.method == "PATCH":

        shift_no = data.get("shiftno")
        closing_balance_raw = data.get("ClosingBalance")
        closing_time = data.get("closingTime")

        if not shift_no:
            return Response({"success": False, "message": "shiftno is required"})

        if closing_balance_raw is None or closing_time is None:
            return Response({
                "success": False,
                "message": "ClosingBalance and closingTime are required"
            })

        try:
            closing_balance = Decimal(str(closing_balance_raw))
        except:
            return Response({
                "success": False,
                "message": "Invalid ClosingBalance"
            })

        updated = Cashcountershiftdetails.objects.filter(
            shiftno=shift_no,
            ShiftStatus="active"
        ).update(
            ClosingBalance=closing_balance,
            closingTime=closing_time,
            ShiftStatus="inactive",
            is_active=False,
            lastmodified_by=employee_id,
            lastmodified_date=timezone.now(),
        )

        if not updated:
            return Response({
                "success": False,
                "message": "Active shift not found or already closed"
            })

        shift = Cashcountershiftdetails.objects.get(shiftno=shift_no)

        return Response({
            "success": True,
            "message": "Shift closed successfully",
            "data": format_shift_response(shift)
        })


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from ..models import Cashcountershiftdetails
from ..serializers import CashcountershiftdetailsSerializer
import traceback
from datetime import datetime
from django.utils import timezone 

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_active_shift(request):
    try:
        data = request.data

        print("===== REQUEST DATA =====")
        print(data)

        cash_counter = data.get("CashCounter")
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        print("CashCounter:", cash_counter)

        if not cash_counter:
            return Response({
                "success": False,
                "message": "CashCounter is required"
            }, status=400)

        # ✅ GET TODAY DATE (backend)
        today = timezone.now().date()
        print("Today Date:", today)

        # ✅ MAIN QUERY (with date filter added)
        queryset = Cashcountershiftdetails.objects.filter(
            CashCounter=cash_counter,
            ShiftStatus="active",
            is_active=True,
            date=today   # ✅ ADDED
        )

        # ✅ Apply filters safely
        if hospital_code:
            queryset = queryset.filter(hospital_code=hospital_code)

        if branch_code:
            queryset = queryset.filter(branch_code=branch_code)

        if outlet_code:
            queryset = queryset.filter(outlet_code=outlet_code)

        # ✅ SAFE DEBUG
        print("Queryset exists:", queryset.exists())

        # ✅ get latest shift (safe)
        shift = queryset.order_by('-StartingTime').first()

        print("Shift object:", shift)

        if not shift:
            return Response({
                "success": False,
                "message": "No active shift found for today"
            })

        serializer = CashcountershiftdetailsSerializer(shift)

        return Response({
            "success": True,
            "data": serializer.data
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "success": False,
            "message": str(e) or "Server error"
        }, status=500)
    



from rest_framework.decorators import api_view
from rest_framework.response import Response
from pymongo import MongoClient
import os

MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_Receiptpayment"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
outlet_collection = mongo_db[COLLECTION_NAME]


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_active_account_heads(request):
    try:
        # ✅ AUTH DATA (your requirement)
        hospital_code = request.data.get("auth-hospital-code") 
        branch_code   = request.data.get("auth-branch-code")   
        outlet_code   = request.data.get("auth-outlet-code")  

        # 🔍 Build query dynamically
        query = {
            "is_active": True
        }

        # ✅ Add filters only if present
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        # 🔎 Fetch data
        data = list(outlet_collection.find(query))

        # ✅ Convert MongoDB types
        for item in data:
            item["_id"] = str(item["_id"])
            if "created_date" in item and item["created_date"]:
                item["created_date"] = item["created_date"].isoformat()

        return Response({
            "status": "success",
            "count": len(data),
            "data": data
        })

    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=500)
    



def generate_voucher_no():
    last_record = ReceiptAndPayment.objects.order_by('-voucher_no').first()

    if last_record and last_record.voucher_no.isdigit():
        next_no = int(last_record.voucher_no) + 1
    else:
        next_no = 1

    return str(next_no).zfill(8)  # 00000001 format


from rest_framework.decorators import api_view
from rest_framework.response import Response
from ..models import ReceiptAndPayment
from ..serializers import ReceiptAndPaymentSerializer


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def post_receipt_payments(request):
    try:
        data = request.data

        # ✅ AUTH DATA
        employee_id   = data.get("auth-user-id")
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        # ✅ REQUIRED FIELDS FROM FRONTEND
        receipt_type = data.get("receipt_type")
        account_head = data.get("account_head")
        description  = data.get("description")
        amount       = data.get("amount")
        cash_counter = data.get("CashCounter")
        shiftno      = data.get("shiftno")

        # 🔴 Validation
        if not all([receipt_type, account_head, amount, cash_counter, shiftno]):
            return Response({
                "status": "error",
                "message": "Missing required fields"
            }, status=400)

        # ✅ Generate voucher number
        voucher_no = generate_voucher_no()

        # ✅ Create record
        obj = ReceiptAndPayment.objects.create(
            receipt_type = receipt_type,
            account_head = account_head,
            description  = description,
            amount       = amount,
            voucher_no   = voucher_no,
            CashCounter  = cash_counter,
            shiftno      = shiftno,

            # ✅ From backend
            CashierID    = employee_id,
            created_by   = employee_id,
            hospital_code = hospital_code,
            branch_code   = branch_code,
            outlet_code   = outlet_code
        )

        serializer = ReceiptAndPaymentSerializer(obj)

        return Response({
            "status": "success",
            "message": "Receipt/Payment created successfully",
            "data": serializer.data
        })

    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=500)
    


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from bson.decimal128 import Decimal128
from bson import ObjectId
from pymongo import MongoClient
from django.utils import timezone
import os, json


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_receipt_payments(request):
    try:
        data = request.data

        employee_id   = data.get("auth-user-id")
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        if not employee_id:
            return Response({"status": "error", "message": "User not authenticated"}, status=401)

        # ✅ DATE FILTER
        from datetime import datetime, time, timedelta
        today = timezone.localdate()
        start = datetime.combine(today, time.min)
        end   = start + timedelta(days=1)

        # ✅ DB CONNECTION
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        transaction_col = db["hospital_receiptandpayment"]
        account_col     = db["hospital_Receiptpayment"]

        # ✅ FETCH DATA
        transactions = list(transaction_col.find({
            "voucher_date": {"$gte": start, "$lt": end},
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code
        }).sort("voucher_no", -1))

        account_heads = list(account_col.find({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "is_active": True
        }))

        # ✅ ACCOUNT MAP
        account_map = {
            str(item.get("S.No")): item.get("account_head")
            for item in account_heads
        }

        result = []

        for t in transactions:
            # ✅ CONVERT FULL DOCUMENT
            doc = {}

            for key, value in t.items():

                # ObjectId → string
                if isinstance(value, ObjectId):
                    doc[key] = str(value)

                # Decimal128 → float
                elif isinstance(value, Decimal128):
                    doc[key] = float(value.to_decimal())

                # datetime → ISO format
                elif hasattr(value, "isoformat"):
                    doc[key] = value.isoformat()

                # description JSON string → dict
                elif key == "description" and isinstance(value, str):
                    try:
                        doc[key] = json.loads(value)
                    except:
                        doc[key] = value

                else:
                    doc[key] = value

            # ✅ ADD ENRICHED ACCOUNT HEAD
            acc_no = str(t.get("account_head"))
            doc["account_head_details"] = {
                "no": acc_no,
                "name": account_map.get(acc_no, "Unknown")
            }

            result.append(doc)

        return Response({
            "status": "success",
            "count": len(result),
            "data": result
        })

    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=500)






from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..models import Billing
from ..serializers import PatientSerializer

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_registration_bills(request):
    try:
        # ================================
        # ✅ AUTH DATA (YOUR STRUCTURE)
        # ================================
        hospital_code = request.data.get("auth-hospital-code")
        branch_code = request.data.get("auth-branch-code")

        print("request.data:", request.data)
        print("hospital_code:", hospital_code)
        print("branch_code:", branch_code)

        # ================================
        # ✅ FILTER BILLING DATA
        # ================================
        filter_query = {
            "payment_status": "Pending"
        }

        if hospital_code is not None:
            filter_query["hospital_code"] = hospital_code

        if branch_code is not None:
            filter_query["branch_code"] = branch_code

        bills = Billing.objects.select_related('patient').filter(**filter_query).order_by('-billed_date')

        response_data = []

        # ================================
        # ✅ BUILD RESPONSE
        # ================================
        for index, bill in enumerate(bills, start=1):

            patient = bill.patient

            billed_date = bill.billed_date
            date_str = billed_date.strftime("%d-%m-%Y") if billed_date else None
            time_str = billed_date.strftime("%H:%M:%S") if billed_date else None

            response_data.append({
                "Sl No": index,
                "Date": date_str,
                "Time": time_str,
                "Bill No": bill.bill_number,
                "Bill Type": "Registration",
                "UHID No": patient.uhid if patient else None,
                "Patient": f"{patient.firstName} {patient.lastName}" if patient else None,
                "Ip Number": getattr(patient, "ip_number", None),

                # ✅ Billing details
                "registration_fee": bill.registration_fee,
                "consulting_fee": bill.consulting_fee,
                "total_fees": bill.total_fees,
                "doctor_id": bill.doctor_id,
                "payment_status": bill.payment_status
            })

        return Response({
            "status": True,
            "count": len(response_data),
            "data": response_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "status": False,
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)