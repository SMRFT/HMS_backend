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

        # print("POST PAYLOAD:", payload)

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

        # print("===== REQUEST DATA =====")
        # print(data)

        cash_counter = data.get("CashCounter")
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        # print("CashCounter:", cash_counter)

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
        # print("Queryset exists:", queryset.exists())

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
from pymongo import MongoClient
from bson.decimal128 import Decimal128
from bson import ObjectId
import os
from datetime import datetime, timedelta

# =========================================================
# ✅ DB CONNECTIONS
# =========================================================
client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

hms_db = client["HMS"]
global_db = client["Global"]   # ✅ FIX: profile comes from Global DB

billing_col = hms_db["hospital_billing"]
invest_col = hms_db["hospital_investbilling"]
discharge_col = hms_db["hospital_dischargebilling"]
patient_col = hms_db["hospital_patient"]

profile_collection = global_db["backend_diagnostics_profile"]  # ✅ FIX
cashcounter_collection = hms_db["hospital_cashcounter"]


# =========================================================
# ✅ SERIALIZER
# =========================================================
def serialize_mongo(doc):
    if isinstance(doc, list):
        return [serialize_mongo(i) for i in doc]

    if isinstance(doc, dict):
        new_doc = {}
        for k, v in doc.items():
            if isinstance(v, ObjectId):
                new_doc[k] = str(v)
            elif isinstance(v, Decimal128):
                new_doc[k] = float(v.to_decimal())
            elif isinstance(v, (dict, list)):
                new_doc[k] = serialize_mongo(v)
            else:
                new_doc[k] = v
        return new_doc

    return doc


# =========================================================
# ✅ DECIMAL CONVERTER
# =========================================================
def convert_decimal(value):
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    try:
        return float(value)
    except:
        return 0.0


# =========================================================
# ✅ MAIN API
# =========================================================
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_mainblock_pendingbills(request):
    try:
        data = request.data

        hospital_code = data.get("auth-hospital-code")
        branch_code = data.get("auth-branch-code")
        employee_id = data.get("auth-user-id")

        print("employee_id:", employee_id)

        final_data = []

        # =========================================================
        # ✅ EMPLOYEE PROFILE (Global DB)
        # =========================================================
        employee_profile = profile_collection.find_one(
            {"employeeId": str(employee_id)},
            {
                "employeeId": 1,
                "cashcounter": 1
            }
        )

        if not employee_profile:
            return Response({
                "success": False,
                "message": "Employee not found"
            }, status=404)

        emp_cashcounter = employee_profile.get("cashcounter")

        if not emp_cashcounter:
            return Response({
                "success": False,
                "message": "Cashcounter not mapped"
            }, status=400)

        # =========================================================
        # ✅ CASHCOUNTER FETCH
        # =========================================================
        cashcounter_doc = cashcounter_collection.find_one(
            {
                "counter_id": emp_cashcounter,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "is_active": True
            }
        )

        if not cashcounter_doc:
            return Response({
                "success": False,
                "message": "No matching cashcounter found"
            }, status=404)

        cashcounter_details = {
            "counter_id": cashcounter_doc.get("counter_id"),
            "counter_name": cashcounter_doc.get("counter_name")
        }

        # =========================================================
        # ✅ BILL TYPES
        # =========================================================
        allowed_bill_type_details = cashcounter_doc.get("bill_type", [])

        allowed_bill_types = [
            {
                "bill_type": bt.get("bill_type"),
                "bill_name": bt.get("bill_name")
            }
            for bt in allowed_bill_type_details
            if bt.get("bill_type") is not None
        ]

        # =========================================================
        # ✅ DATE FILTER
        # =========================================================
        today = datetime.utcnow().date()
        start = datetime.combine(today, datetime.min.time())
        end = datetime.combine(today + timedelta(days=1), datetime.min.time())

        # =========================================================
        # 1. BILLING
        # =========================================================
        billing_docs = list(billing_col.find({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "payment_status": "Pending",
            "billed_date": {"$gte": start, "$lt": end}
        }))

        for bill in billing_docs:
            patient = patient_col.find_one({
                "id": bill.get("patient_id"),
                "hospital_code": hospital_code,
                "branch_code": branch_code
            })

            final_data.append({
                "type": "Billing",
                "bill_no": bill.get("bill_number"),
                "uhid": patient.get("uhid") if patient else None,
                "patient_name": (
                    f"{patient.get('firstName')} {patient.get('lastName')}"
                    if patient else None
                ),
                "amount": convert_decimal(bill.get("total_fees")),
                "status": bill.get("payment_status"),
                "date": bill.get("billed_date"),
                "raw": serialize_mongo(bill)
            })

        # =========================================================
        # 2. INVESTIGATION
        # =========================================================
        invest_docs = list(invest_col.find({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "paymentMethod": "Cash",
            "paymentStatus": "Pending",
            "investBillDate": {"$gte": start, "$lt": end}
        }))

        for inv in invest_docs:
            patient = patient_col.find_one({
                "uhid": inv.get("uhid"),
                "hospital_code": hospital_code,
                "branch_code": branch_code
            })

            final_data.append({
                "type": "Investigation",
                "bill_no": inv.get("investBillNo"),
                "uhid": inv.get("uhid"),
                "patient_name": (
                    f"{patient.get('firstName')} {patient.get('lastName')}"
                    if patient else None
                ),
                "amount": convert_decimal(inv.get("finalPrice")),
                "status": inv.get("paymentStatus"),
                "date": inv.get("investBillDate"),
                "raw": serialize_mongo(inv)
            })

        # =========================================================
        # 3. DISCHARGE
        # =========================================================
        discharge_docs = list(discharge_col.find({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "status": "Billed",
            "bill_date": {"$gte": start, "$lt": end}
        }))

        for dis in discharge_docs:
            patient = patient_col.find_one({
                "uhid": dis.get("uhid"),
                "hospital_code": hospital_code,
                "branch_code": branch_code
            })

            final_data.append({
                "type": "Discharge",
                "bill_no": dis.get("bill_no"),
                "uhid": dis.get("uhid"),
                "patient_name": (
                    f"{patient.get('firstName')} {patient.get('lastName')}"
                    if patient else None
                ),
                "amount": convert_decimal(dis.get("net_amount")),
                "status": dis.get("status"),
                "date": dis.get("bill_date"),
                "items": serialize_mongo(dis.get("items", [])),
                "raw": serialize_mongo(dis)
            })

        # =========================================================
        # ✅ FINAL RESPONSE
        # =========================================================
        return Response({
            "status": "success",
            "count": len(final_data),
            "cashcounter": cashcounter_details,
            "allowed_bill_types": allowed_bill_types,
            "data": final_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from bson.decimal128 import Decimal128
from datetime import datetime
import os

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
db = client["HMS"]

billing_col    = db["hospital_billing"]
invest_col     = db["hospital_investbilling"]
discharge_col  = db["hospital_dischargebilling"]


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def update_mainblock_pendingbills(request):
    """
    Update payment status + insert payment_details for a pending bill.

    Expected body:
    {
        "bill_no":         "BL-20240427-001",   # required
        "type":            "Billing",            # required: "Billing" | "Investigation" | "Discharge"
        "payment_details": {                     # required
            "method":      "cash"|"card"|"cheque"|"Multiple Payment",
            "Paid_amount": 5000,
            "card_no":     "ICICIBANK2102",      # optional
            "cheque_no":   "CHQ001",             # optional
            "breakdown":   [...]                 # optional, for multiple payment
        },
        "shiftno":         "SH-001",             # optional
        "pendingAmount":   0                     # optional — stored when partial payment
    }
    """
    try:
        data            = request.data
        hospital_code   = data.get("auth-hospital-code")
        branch_code     = data.get("auth-branch-code")
        employee_id   = data.get("auth-user-id")
        CashierID = employee_id
        

        bill_no         = data.get("bill_no")
        payment_details = data.get("payment_details")
        shiftno         = data.get("shiftno", "")
        pending_amount  = data.get("pendingAmount", 0)

        # Accept "type" or "bill_type" from frontend
        bill_type = data.get("type") or data.get("bill_type")

        # Infer type from field names present in the payload
        # e.g. frontend sends "paymentStatus" -> Investigation
        #                     "payment_status" -> Billing
        #                     "status"         -> Discharge
        if not bill_type:
            if data.get("paymentStatus"):
                bill_type = "Investigation"
            elif data.get("payment_status"):
                bill_type = "Billing"
            elif data.get("status"):
                bill_type = "Discharge"

        # Infer type from bill_no prefix as last fallback
        # e.g. "2526/DCH/000005" -> Discharge
        #      "2526/INV/000005" -> Investigation
        #      "2526/BIL/000005" -> Billing
        if not bill_type and bill_no:
            upper = bill_no.upper()
            if "DCH" in upper or "DIS" in upper:
                bill_type = "Discharge"
            elif "INV" in upper:
                bill_type = "Investigation"
            elif "BIL" in upper or "/BL" in upper or upper.startswith("BL"):
                bill_type = "Billing"

        # ── Validation ────────────────────────────────────────────────────────
        if not bill_no:
            return Response({"status": "error", "message": "bill_no is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        if not bill_type:
            return Response({
                "status": "error",
                "message": "Could not determine bill type. Please send 'type': 'Billing' | 'Investigation' | 'Discharge'."
            }, status=status.HTTP_400_BAD_REQUEST)

        if not payment_details or not isinstance(payment_details, dict):
            return Response({"status": "error", "message": "payment_details is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        if bill_type not in ("Billing", "Investigation", "Discharge"):
            return Response(
                {"status": "error",
                 "message": f"Invalid type '{bill_type}'. Must be Billing, Investigation, or Discharge."},
                status=status.HTTP_400_BAD_REQUEST
            )

        paid_amount = float(payment_details.get("Paid_amount", 0))
        if paid_amount <= 0:
            return Response({"status": "error", "message": "Paid_amount must be greater than 0."},
                            status=status.HTTP_400_BAD_REQUEST)

        # ── Enrich payment_details with meta ─────────────────────────────────
        paid_at = datetime.utcnow().isoformat()

        # ── Route by type ─────────────────────────────────────────────────────

        # =====================================================================
        # 1. BILLING  →  hospital_billing
        #    filter : bill_number  |  status field : payment_status
        # =====================================================================
        if bill_type == "Billing":
            query = {
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "bill_number":   bill_no,
                "payment_status": "Pending",
            }

            new_status = "Paid" if pending_amount == 0 else "Partial"

            update = {
                "$set": {
                    "payment_status":  new_status,
                    "payment_details": payment_details,
                    "shiftno":         shiftno,
                    "paid_at":         paid_at,
                    "CashierID":       CashierID, 
                    **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),
                }
            }

            result = billing_col.update_one(query, update)

            if result.matched_count == 0:
                return Response(
                    {"status": "error",
                     "message": f"No Pending Billing bill found with bill_no '{bill_no}'."},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                "status":  "success",
                "message": f"Billing bill '{bill_no}' updated to '{new_status}'.",
                "bill_no": bill_no,
                "type":    "Billing",
                "new_payment_status": new_status,
                "pendingAmount": pending_amount,
                "payment_details": payment_details,
            }, status=status.HTTP_200_OK)

        # =====================================================================
        # 2. INVESTIGATION  →  hospital_investbilling
        #    filter : investBillNo  |  status field : paymentStatus
        # =====================================================================
        elif bill_type == "Investigation":
            query = {
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "investBillNo":  bill_no,
                "paymentStatus": "Pending",
            }

            new_status = "Paid" if pending_amount == 0 else "Partial"

            update = {
                "$set": {
                    "paymentStatus":   new_status,
                    "payment_details": payment_details,
                    "shiftno":         shiftno,
                    "paid_at":         paid_at,
                    "CashierID":       CashierID,
                    **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),
                }
            }

            result = invest_col.update_one(query, update)

            if result.matched_count == 0:
                return Response(
                    {"status": "error",
                     "message": f"No Pending Investigation bill found with bill_no '{bill_no}'."},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                "status":  "success",
                "message": f"Investigation bill '{bill_no}' updated to '{new_status}'.",
                "bill_no": bill_no,
                "type":    "Investigation",
                "new_payment_status": new_status,
                "pendingAmount": pending_amount,
                "payment_details": payment_details,
            }, status=status.HTTP_200_OK)

        # =====================================================================
        # 3. DISCHARGE  →  hospital_dischargebilling
        #    filter : bill_no  |  status field : items[].payment_status
        # =====================================================================
        elif bill_type == "Discharge":
            # Match by bill_no only — no status pre-filter so we always find the doc
            query = {
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "bill_no":       bill_no,
            }

            new_status = "Paid" if pending_amount == 0 else "Partial"

            update = {
                "$set": {
                    # Root-level status: "Billed" -> "Paid"
                    "status":          new_status,
                    # Also mark all items as Paid
                    "items.$[].payment_status": new_status,
                    "payment_details": payment_details,
                    "shiftno":         shiftno,
                    "paid_at":         paid_at,
                    "CashierID":       CashierID,
                    **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),
                }
            }

            result = discharge_col.update_one(query, update)

            if result.matched_count == 0:
                return Response(
                    {"status": "error",
                     "message": f"No Discharge bill found with bill_no '{bill_no}'."},
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                "status":  "success",
                "message": f"Discharge bill '{bill_no}' status updated to '{new_status}'.",
                "bill_no": bill_no,
                "type":    "Discharge",
                "new_payment_status": new_status,
                "pendingAmount": pending_amount,
                "payment_details": payment_details,
            }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "status":  "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)