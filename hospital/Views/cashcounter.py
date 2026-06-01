from pymongo import MongoClient, DESCENDING
import os
from rest_framework.decorators import api_view

from rest_framework.response import Response

from django.utils import timezone

import traceback

from datetime import datetime

from bson.decimal128 import Decimal128

from decimal import Decimal

from ..models import Cashcountershiftdetails

from ..serializers import CashcountershiftdetailsSerializer
def format_dt(val):
    if not val: return None
    if isinstance(val, str): return val
    try: return val.isoformat()
    except: return str(val)
def safe_dec(val):
    if val is None: return Decimal('0.00')
    if hasattr(val, 'to_decimal'):
        try: return val.to_decimal()
        except: return Decimal('0.00')
    if isinstance(val, str):
        import re
        clean = re.sub(r'[^0-9\.\-]', '', val)
        try: return Decimal(clean or '0.00')
        except: return Decimal('0.00')
    try: return Decimal(str(val))
    except: return Decimal('0.00')

def get_shift_pymongo(query, sort_field=None):
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        col = db["hospital_cashcountershiftdetails"]
        
        sort_query = []
        if sort_field:
            sort_query = [(sort_field, DESCENDING)]
            
        doc = col.find_one(query, sort=sort_query)
        if doc:
            # Convert to model instance for compatibility
            from ..models import Cashcountershiftdetails
            doc.pop('_id', None)
            return Cashcountershiftdetails(**doc)
        return None
    except Exception as e:
        print(f"PyMongo Error: {e}")
        return None

# Auth/permissions

from pyauth.auth import HasRoleAndDataPermission

from rest_framework.decorators import api_view, permission_classes

# =========================================

# 🔢 SHIFT NUMBER GENERATOR (DJONGO SAFE)

# =========================================

def generate_shift_no():
    now = datetime.now()
    if now.month >= 4:
        start, end = now.year, now.year + 1
    else:
        start, end = now.year - 1, now.year
    fy = f"{str(start)[-2:]}{str(end)[-2:]}"

    from pymongo import MongoClient
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    col = db["hospital_cashcountershiftdetails"]
    shifts = list(col.find({"shiftno": {"$regex": f"^{fy}/"}}))
    
    last_number = 0
    for s in shifts:
        try:
            s_no = s.get("shiftno", "")
            if "/" in s_no:
                num_part = s_no.split("/")[1]
                num = int(num_part)
                if num > last_number: last_number = num
        except: continue
            
    new_number = last_number + 1
    return f"{fy}/{str(new_number).zfill(6)}"

def convert_decimal(value):

    if value is None:

        return 0.0

    if isinstance(value, Decimal128):

        return float(value.to_decimal())

    if isinstance(value, (Decimal, int, float)):

        return float(value)

    try:

        return float(value)

    except:

        return 0.0

def convert_decimal128(value):
    if value is None: return Decimal('0.00')
    if hasattr(value, 'to_decimal'): return value.to_decimal()
    if isinstance(value, str):
        clean = value.replace("“", "").replace("”", "").replace("₹", "").replace(",", "").strip()
        try: return Decimal(clean or '0.00')
        except: return Decimal('0.00')
    try: return Decimal(str(value))
    except: return Decimal('0.00')

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

        "collected_Amount": convert_decimal(shift.collected_Amount),

        "PettyCashBalance": convert_decimal(shift.PettyCashBalance),

        "RemittedToBank": convert_decimal(shift.RemittedToBank),

        "HandOverAmount": convert_decimal(shift.HandOverAmount),
        "SalesReturnAmount": convert_decimal(shift.SalesReturnAmount),
        "SelectedOutlet": shift.SelectedOutlet,

        "ShiftStatus": shift.ShiftStatus,

        # ✅ FORMAT DATE TIME FOR UI

        "StartingTime": format_dt(shift.StartingTime),

        "closingTime": format_dt(shift.closingTime),

        "date": str(shift.date),

        "hospital_code": shift.hospital_code,

        "branch_code": shift.branch_code,

        "outlet_code": shift.outlet_code,

        "is_active": shift.is_active,

    }

def get_previous_shift_balance(cash_counter, outlet_code, hospital_code, branch_code):

    query = {
        "CashCounter": cash_counter,
        "SelectedOutlet": outlet_code,
        "hospital_code": hospital_code,
        "branch_code": branch_code,
        "ShiftStatus": "inactive"
    }
    last_shift = get_shift_pymongo(query, "closingTime")

    

    if last_shift:

        return convert_decimal(last_shift.ClosingBalance)

    return 0.0

@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def cash_counter_shiftdetails(request):

    data = request.data

    # :white_check_mark: AUTH DATA
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
    # :white_check_mark: CREATE SHIFT (POST)
    # =====================================================
    if request.method == "POST":
        cash_counter = data.get("CashCounter")
        
        # ✅ ACCESS CONTROL: Check if there is already an active shift for this outlet & counter
        query = {
            "CashCounter": cash_counter,
            "SelectedOutlet": outlet_code,
            "ShiftStatus": "active",
            "is_active": True,
            "hospital_code": hospital_code,
            "branch_code": branch_code
        }
        existing_active = get_shift_pymongo(query, "StartingTime")
        
        if existing_active:
            if existing_active.CashierID != employee_id:
                return Response({
                    "success": False,
                    "message": f"Outlet {cash_counter} is already being used by another cashier ({existing_active.CashierID}). Please close that shift first."
                }, status=400)
            else:
                return Response({
                    "success": True,
                    "message": "You already have an active shift for this outlet.",
                    "data": format_shift_response(existing_active)
                })

        shift_no = generate_shift_no()
        opening_balance = convert_decimal128(data.get("OpeningBalance", 0))

        payload = {
            "shiftno": shift_no,
            "CashierID": employee_id,
            "CashCounter": cash_counter,
            "SelectedOutlet": outlet_code,
            "OpeningBalance": opening_balance,
            "StartingTime": data.get("StartingTime") or timezone.now(),
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
    # :white_check_mark: CLOSE SHIFT (PATCH)
    # =====================================================
    elif request.method == "PATCH":
        shift_no = data.get("shiftno")
        if not shift_no:
            return Response({"success": False, "message": "shiftno is required"})

        # ✅ ACCESS CONTROL: Shift must be closed by the same cashier who opened it
        try:
            shift = Cashcountershiftdetails.objects.get(shiftno=shift_no)
        except Cashcountershiftdetails.DoesNotExist:
            return Response({"success": False, "message": "Shift not found"})

        if shift.CashierID != employee_id:
            return Response({
                "success": False,
                "message": "Shift must be closed by the same cashier who opened it."
            }, status=403)

        if shift.ShiftStatus != "active":
            return Response({"success": False, "message": "Shift is already closed"})

        closing_balance_raw = data.get("ClosingBalance")
        closing_time = data.get("closingTime") or timezone.now()

        # Recalculate collection before closing to ensure accuracy
        totals = calculate_shift_collection(shift_no)
        
        shift.collected_Amount = safe_dec(totals['total_collection'])
        shift.SalesReturnAmount = safe_dec(totals['sales_return'])
        
        # Use provided fields or defaults
        shift.ClosingBalance = safe_dec(closing_balance_raw or totals['total_collection'])
        shift.RemittedToBank = safe_dec(data.get("RemittedToBank", shift.RemittedToBank))
        shift.HandOverAmount = safe_dec(data.get("HandOverAmount", 0))
        
        # ✅ Thoroughly clean all decimal fields before saving to avoid conflicts
        for field in [
            'OpeningBalance', 'ClosingBalance', 'collected_Amount', 
            'PettyCashBalance', 'RemittedToBank', 'SubmittedToAccount', 
            'HandOverAmount', 'PendingAmount', 'IPAdvanceAmount', 'SalesReturnAmount'
        ]:
            setattr(shift, field, safe_dec(getattr(shift, field, 0)))

        shift.closingTime = closing_time
        shift.ShiftStatus = "inactive"
        shift.is_active = False
        shift.lastmodified_by = employee_id
        shift.lastmodified_date = timezone.now()
        shift.save()

        return Response({
            "success": True,
            "message": "Shift closed successfully",
            "data": format_shift_response(shift)
        })

def calculate_shift_collection(shift_no):
    """
    Calculates the total collected amount and other financial metrics for a shift.
    Returns a dictionary with all metrics.
    """
    results = {
        "total_collection": 0.0,
        "pending_amount": 0.0,
        "ip_advance": 0.0,
        "sales_return": 0.0,
        "receipts": 0.0,
        "payments": 0.0
    }

    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        # 1. Billing (Registration/Consultation)
        # Paid
        paid_bills = list(db["hospital_billing"].find({"shiftno": shift_no, "payment_status": "Paid"}))
        for b in paid_bills:
            results["total_collection"] += convert_decimal(b.get("total_fees", 0))
        
        # Pending
        pending_bills = list(db["hospital_billing"].find({"shiftno": shift_no, "payment_status": "Pending"}))
        for b in pending_bills:
            results["pending_amount"] += convert_decimal(b.get("total_fees", 0))

        # 2. Investigation
        paid_invest = list(db["hospital_investbilling"].find({"shiftno": shift_no, "paymentStatus": "Paid"}))
        for d in paid_invest:
            results["total_collection"] += convert_decimal(d.get("finalPrice") or d.get("total") or 0)
            
        pending_invest = list(db["hospital_investbilling"].find({"shiftno": shift_no, "paymentStatus": "Pending"}))
        for d in pending_invest:
            results["pending_amount"] += convert_decimal(d.get("finalPrice") or d.get("total") or 0)

        # 3. Discharge
        paid_discharge = list(db["hospital_dischargebilling"].find({"shiftno": shift_no, "status": "Paid"}))
        for d in paid_discharge:
            results["total_collection"] += convert_decimal(d.get("net_amount", 0))
            
        pending_discharge = list(db["hospital_dischargebilling"].find({"shiftno": shift_no, "status": "Pending"}))
        for d in pending_discharge:
            results["pending_amount"] += convert_decimal(d.get("net_amount", 0))

        # 4. Pharmacy
        paid_pharmacy = list(db["hospital_pharmacybilling"].find({"shiftno": shift_no, "billing_status": "Paid"}))
        for d in paid_pharmacy:
            results["total_collection"] += convert_decimal(d.get("net_amount", 0))
            
        pending_pharmacy = list(db["hospital_pharmacybilling"].find({"shiftno": shift_no, "billing_status": "Pending"}))
        for d in pending_pharmacy:
            results["pending_amount"] += convert_decimal(d.get("net_amount", 0))

        # 5. IP Advance (from Admission model's advance_payments)
        # Since shiftno might not be in the JSON yet, we might need a fallback or check if it was added
        admissions = list(db["hospital_admission"].find({"advance_payments.shiftno": shift_no}))
        for adm in admissions:
            payments = adm.get("advance_payments", [])
            for p in payments:
                if p.get("shiftno") == shift_no and p.get("is_advanceActive"):
                    amt = convert_decimal(p.get("advance_amount", 0))
                    results["ip_advance"] += amt
                    results["total_collection"] += amt

        # 6. Sales Return
        returns = list(db["hospital_salesreturn"].find({"shiftno": shift_no}))
        for r in returns:
            amt = convert_decimal(r.get("return_amount", 0))
            results["sales_return"] += amt
            results["total_collection"] -= amt

        # 7. Receipt and Payment
        rp_docs = list(db["hospital_receiptandpayment"].find({"shiftno": shift_no}))
        for d in rp_docs:
            amt = convert_decimal(d.get("amount", 0))
            if d.get("receipt_type") == "Receipt":
                results["receipts"] += amt
                results["total_collection"] += amt
            elif d.get("receipt_type") == "Payment":
                results["payments"] += amt
                results["total_collection"] -= amt

        client.close()

    except Exception as e:
        print("Error calculating shift collection:", e)
        traceback.print_exc()

    return results



# =====================================================

# ✅ MAIN API

        # ✅ SAFE DEBUG
        # print("Queryset exists:", queryset.exists())


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_active_shift(request):
    try:
        data = request.data
        cash_counter = data.get("CashCounter") or request.META.get("HTTP_OUTLET_CODE")
        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = data.get("auth-branch-code") or request.META.get("HTTP_BRANCH_CODE")
        outlet_code = data.get("auth-outlet-code") or request.META.get("HTTP_AUTH_OUTLET_CODE")
        
        today = timezone.now().date()
        # Bypassing Djongo ORM for the active shift query to avoid SQLDecodeError
        query = {
            "CashCounter": cash_counter,
            "SelectedOutlet": outlet_code,
            "ShiftStatus": "active",
            "is_active": True,
            "hospital_code": hospital_code,
            "branch_code": branch_code
        }
        # If the date filter is causing issues, we can check it manually after fetch
        # Removing date restriction: if a shift is active, it must be closed regardless of date
        shift = get_shift_pymongo(query, "StartingTime")

        if not shift:
            expected = get_previous_shift_balance(cash_counter, outlet_code, hospital_code, branch_code)
            return Response({
                "success": False, "message": "No active shift found",
                "expected_opening": expected, "default_petty_cash": 1000.0, "is_active": False
            })

        # Using global safe_dec

        # Thoroughly clean all decimal fields before saving to avoid Decimal128/String conflicts
        totals = calculate_shift_collection(shift.shiftno)
        shift.collected_Amount = safe_dec(totals['total_collection'])
        shift.SalesReturnAmount = safe_dec(totals['sales_return'])
        
        # ✅ Thoroughly clean all decimal fields before saving to avoid conflicts
        for field in [
            'OpeningBalance', 'ClosingBalance', 'collected_Amount', 
            'PettyCashBalance', 'RemittedToBank', 'SubmittedToAccount', 
            'HandOverAmount', 'PendingAmount', 'IPAdvanceAmount', 'SalesReturnAmount'
        ]:
            setattr(shift, field, safe_dec(getattr(shift, field, 0)))

        shift.save()
        
        return Response({"success": True, "data": format_shift_response(shift)})
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("❌ get_active_shift ERROR:\n", error_details)
        return Response({"success": False, "message": str(e), "traceback": error_details}, status=500)

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

        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE") 

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

        employee_id   = data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID") or request.META.get("HTTP_AUTH_USER_ID")

        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")

        branch_code   = data.get("auth-branch-code") or request.META.get("HTTP_BRANCH_CODE") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE"))

        outlet_code   = data.get("auth-outlet-code") or request.META.get("HTTP_OUTLET_CODE") or (request.META.get("HTTP_AUTH_OUTLET_CODE") or request.META.get("HTTP_OUTLET_CODE"))



        # ✅ REQUIRED FIELDS FROM FRONTEND

        receipt_type = data.get("receipt_type")

        account_head = data.get("account_head")

        description  = data.get("description")

        amount       = data.get("amount")

        cash_counter = data.get("CashCounter") or request.META.get("HTTP_OUTLET_CODE")

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



        employee_id   = data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID") or request.META.get("HTTP_AUTH_USER_ID")

        hospital_code = data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")

        branch_code   = data.get("auth-branch-code") or request.META.get("HTTP_BRANCH_CODE") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE"))

        outlet_code   = data.get("auth-outlet-code") or request.META.get("HTTP_OUTLET_CODE") or (request.META.get("HTTP_AUTH_OUTLET_CODE") or request.META.get("HTTP_OUTLET_CODE"))



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
from django.utils import timezone

# =========================================================
# ✅ DB CONNECTIONS
# =========================================================
client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

hms_db = client["HMS"]
global_db = client["Global"]

billing_col = hms_db["hospital_billing"]
invest_col = hms_db["hospital_investbilling"]
discharge_col = hms_db["hospital_dischargebilling"]
patient_col = hms_db["hospital_patient"]

profile_collection = global_db["backend_diagnostics_profile"]
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
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        employee_id   = data.get("auth-user-id")

        final_data = []

        # =========================================================
        # ✅ EMPLOYEE PROFILE FETCH
        # =========================================================
        employee_profile = profile_collection.find_one(
            {
                "employeeId": str(employee_id)
            },
            {
                "employeeId": 1,
                "employeeName": 1,
                "cashcounter": 1,
                "hms_outlets": 1
            }
        )

        if not employee_profile:

            return Response({
                "status": "error",
                "message": "Employee profile not found"
            }, status=status.HTTP_404_NOT_FOUND)

        # =========================================================
        # ✅ HMS OUTLET VALIDATION
        # =========================================================
        employee_outlets = employee_profile.get("hms_outlets", [])

        if outlet_code not in employee_outlets:

            return Response({
                "status": "error",
                "message": "Outlet not mapped for this employee",
                "employee_outlets": employee_outlets
            }, status=status.HTTP_400_BAD_REQUEST)

        # =========================================================
        # ✅ GET CASHCOUNTER FROM PROFILE
        # =========================================================
        emp_cashcounter = employee_profile.get("cashcounter")

        if not emp_cashcounter:

            return Response({
                "status": "error",
                "message": "Cashcounter not mapped for employee"
            }, status=status.HTTP_400_BAD_REQUEST)

        # =========================================================
        # ✅ CASHCOUNTER FETCH
        # =========================================================
        cashcounter_doc = cashcounter_collection.find_one(
            {
                "counter_id": emp_cashcounter,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet": outlet_code,
                "is_active": True
            }
        )

        if not cashcounter_doc:

            return Response({
                "status": "error",
                "message": "Matching cashcounter not found"
            }, status=status.HTTP_404_NOT_FOUND)

        # =========================================================
        # ✅ CASHCOUNTER DETAILS
        # =========================================================
        cashcounter_details = {
            "counter_id": cashcounter_doc.get("counter_id"),
            "counter_name": cashcounter_doc.get("counter_name"),
            "outlet": cashcounter_doc.get("outlet")
        }

        # =========================================================
        # ✅ BILL TYPES
        # =========================================================
        allowed_bill_type_details = []

        for bt in cashcounter_doc.get("bill_type", []):

            allowed_bill_type_details.append({
                "bill_type": bt.get("bill_type"),
                "bill_name": bt.get("bill_name")
            })

        # =========================================================
        # ✅ ALLOWED BILL TYPE IDS
        # =========================================================
        allowed_bill_type_ids = [
            bt.get("bill_type")
            for bt in cashcounter_doc.get("bill_type", [])
            if bt.get("bill_type") is not None
        ]

        # =========================================================
        # ✅ TODAY FILTER
        # =========================================================
        today = timezone.localdate()

        start = datetime.combine(today, datetime.min.time())
        end   = start + timedelta(days=1)

        # =========================================================
        # ✅ 1. OP BILLING
        # =========================================================
        billing_docs = list(
            billing_col.find({
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
                "payment_status": "Pending",
                "billed_date": {
                    "$gte": start,
                    "$lt": end
                }
            })
        )

        for bill in billing_docs:

            bill_type = bill.get("bill_type")

            # ✅ FILTER BASED ON CASHCOUNTER BILL TYPES
            if bill_type not in allowed_bill_type_ids:
                continue

            patient = patient_col.find_one({
                "id": bill.get("patient_id"),
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                
            })

            final_data.append({

                "type": "Billing",

                "bill_type": bill_type,

                "bill_no": bill.get("bill_number"),

                "uhid": patient.get("uhid") if patient else None,

                "patient_name": (
                f"{patient.get('salutation', '')} "
                f"{patient.get('firstName', '')} "
                f"{patient.get('lastName', '')}".strip()
                if patient else None
            ),

                "amount": convert_decimal(
                    bill.get("total_fees")
                ),

                "status": bill.get("payment_status"),

                "date": bill.get("billed_date"),

                "raw": serialize_mongo(bill)
            })

        # =========================================================
        # ✅ 2. INVESTIGATION BILLING
        # =========================================================
        invest_docs = list(
            invest_col.find({
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
                "paymentStatus": "Pending",
                "investBillDate": {
                    "$gte": start,
                    "$lt": end
                }
            })
        )

        for inv in invest_docs:

            bill_type = inv.get("bill_type")

            # ✅ FILTER BASED ON CASHCOUNTER BILL TYPES
            if bill_type not in allowed_bill_type_ids:
                continue

            patient = patient_col.find_one({
                "uhid": inv.get("uhid"),
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                
            })

            final_data.append({

                "type": "Investigation",

                "bill_type": bill_type,

                "bill_no": inv.get("investBillNo"),

                "uhid": inv.get("uhid"),

                "patient_name": (
                f"{patient.get('salutation', '')} "
                f"{patient.get('firstName', '')} "
                f"{patient.get('lastName', '')}".strip()
                if patient else None
            ),


                "amount": convert_decimal(
                    inv.get("finalPrice")
                ),

                "status": inv.get("paymentStatus"),

                "date": inv.get("investBillDate"),

                "raw": serialize_mongo(inv)
            })

        # =========================================================
        # ✅ 3. DISCHARGE BILLING
        # =========================================================
        discharge_docs = list(
            discharge_col.find({
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
                "status": "Billed",
                "bill_date": {
                    "$gte": start,
                    "$lt": end
                }
            })
        )

        for dis in discharge_docs:

            items = dis.get("items", [])

            # ✅ CHECK ITEM BILL TYPES
            matched_items = []

            for item in items:

                if item.get("bill_type") in allowed_bill_type_ids:
                    matched_items.append(item)

            # ✅ SKIP IF NO MATCHED ITEMS
            if not matched_items:
                continue

            patient = patient_col.find_one({
                "uhid": dis.get("uhid"),
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                
            })

            final_data.append({

                "type": "Discharge",

                "bill_type": list(set([
                    item.get("bill_type")
                    for item in matched_items
                ])),

                "bill_no": dis.get("bill_no"),

                "uhid": dis.get("uhid"),

                "patient_name": (
                f"{patient.get('salutation', '')} "
                f"{patient.get('firstName', '')} "
                f"{patient.get('lastName', '')}".strip()
                if patient else None
            ),

                "amount": convert_decimal(
                    dis.get("net_amount")
                ),

                "status": dis.get("status"),

                "date": dis.get("bill_date"),

                "items": serialize_mongo(matched_items),

                "raw": serialize_mongo(dis)
            })

        # =========================================================
        # ✅ SORT BY DATE DESC
        # =========================================================
        final_data = sorted(
            final_data,
            key=lambda x: x.get("date", datetime.min),
            reverse=True
        )

        # =========================================================
        # ✅ FINAL RESPONSE
        # =========================================================
        return Response({

            "status": "success",

            "cashcounter": cashcounter_details,

            "allowed_bill_type_details": allowed_bill_type_details,

            "count": len(final_data),

            "data": serialize_mongo(final_data)

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
from ..serializers import CashCounterCollectionSerializer
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

    try:

        data = request.data

        hospital_code = data.get("auth-hospital-code")
        branch_code = data.get("auth-branch-code")

        outlet_code = (
            data.get("auth-outlet-code")
            or request.META.get("HTTP_AUTH_OUTLET_CODE")
            or request.META.get("HTTP_OUTLET_CODE")
        )

        employee_id = data.get("auth-user-id")

        CashierID = employee_id

        bill_no = data.get("bill_no")

        payment_details = data.get("payment_details")

        shiftno = (
            data.get("shiftno")
            or data.get("shift_no")
        )

        counter_id = data.get("counter_id")

        remarks = data.get("remarks", "")

        pending_amount = float(
            data.get("pendingAmount", 0)
        )

        paid_at = datetime.utcnow().isoformat()

        # =====================================================
        # VALIDATION
        # =====================================================

        if not bill_no:
            return Response(
                {
                    "status": "error",
                    "message": "bill_no is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not payment_details:
            return Response(
                {
                    "status": "error",
                    "message": "payment_details is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        paid_amount = float(
            payment_details.get("Paid_amount", 0)
        )

        if paid_amount <= 0:
            return Response(
                {
                    "status": "error",
                    "message": "Paid_amount must be greater than 0."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =====================================================
        # 1. CHECK BILLING COLLECTION
        # =====================================================

        billing_doc = billing_col.find_one({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "bill_number": bill_no
        })

        if billing_doc:

            new_status = (
                "Paid"
                if pending_amount == 0
                else "Partial"
            )

            billing_col.update_one(
                {
                    "_id": billing_doc["_id"]
                },
                {
                    "$set": {
                        "payment_status": new_status,
                        "payment_details": payment_details,
                        "shiftno": shiftno,
                        "paid_at": paid_at,
                        "CashierID": CashierID,
                        "lastmodified_by": CashierID,
                        "lastmodified_date": datetime.utcnow(),
                        **(
                            {
                                "pendingAmount": Decimal128(
                                    str(pending_amount)
                                )
                            }
                            if pending_amount > 0
                            else {}
                        ),
                    }
                }
            )

            # =============================================
            # GET bill_type FROM COLLECTION
            # =============================================

            bill_type = billing_doc.get("bill_type", 1)

            # =============================================
            # SAVE CASH COUNTER COLLECTION
            # =============================================

            cash_counter_data = {

                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,

                "created_by": CashierID,
                "lastmodified_by": CashierID,

                "bill_no": bill_no,
                "bill_number": bill_no,

                "bill_type": bill_type,

                "counter_code": counter_id,

                "shift_no": shiftno,

                "billing_category": "Billing",

                "transaction_type": "collected",

                "collected_amount": str(
                    payment_details.get("Paid_amount", 0)
                ),

                "Returned_amount": "0.00",

                "remarks": remarks,
            }

            cc_serializer = CashCounterCollectionSerializer(
                data=cash_counter_data
            )

            if cc_serializer.is_valid():
                cc_serializer.save()
            else:
                return Response(
                    {
                        "status": "error",
                        "serializer_errors": cc_serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "status": "success",
                    "type": "Billing",
                    "bill_type": bill_type,
                    "bill_no": bill_no,
                    "new_payment_status": new_status
                },
                status=status.HTTP_200_OK
            )

        # =====================================================
        # 2. CHECK INVESTIGATION COLLECTION
        # =====================================================

        invest_doc = invest_col.find_one({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "investBillNo": bill_no
        })

        if invest_doc:

            new_status = (
                "Paid"
                if pending_amount == 0
                else "Partial"
            )

            invest_col.update_one(
                {
                    "_id": invest_doc["_id"]
                },
                {
                    "$set": {
                        "paymentStatus": new_status,
                        "payment_details": payment_details,
                        "shiftno": shiftno,
                        "paid_at": paid_at,
                        "CashierID": CashierID,
                        "lastmodified_by": CashierID,
                        "lastmodified_date": datetime.utcnow(),
                        **(
                            {
                                "pendingAmount": Decimal128(
                                    str(pending_amount)
                                )
                            }
                            if pending_amount > 0
                            else {}
                        ),
                    }
                }
            )

            # =============================================
            # GET bill_type FROM COLLECTION
            # =============================================

            bill_type = invest_doc.get("bill_type")

            # =============================================
            # SAVE CASH COUNTER COLLECTION
            # =============================================

            cash_counter_data = {

                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,

                "created_by": CashierID,
                "lastmodified_by": CashierID,

                "bill_no": bill_no,
                "bill_number": bill_no,

                "bill_type": bill_type,

                "counter_code": counter_id,

                "shift_no": shiftno,

                "billing_category": "Investigation",

                "transaction_type": "collected",

                "collected_amount": str(
                    payment_details.get("Paid_amount", 0)
                ),

                "Returned_amount": "0.00",

                "remarks": remarks,
            }

            cc_serializer = CashCounterCollectionSerializer(
                data=cash_counter_data
            )

            if cc_serializer.is_valid():
                cc_serializer.save()
            else:
                return Response(
                    {
                        "status": "error",
                        "serializer_errors": cc_serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "status": "success",
                    "type": "Investigation",
                    "bill_type": bill_type,
                    "bill_no": bill_no,
                    "new_payment_status": new_status
                },
                status=status.HTTP_200_OK
            )

        # =====================================================
        # 3. CHECK DISCHARGE COLLECTION
        # =====================================================

        discharge_doc = discharge_col.find_one({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "bill_no": bill_no
        })

        if discharge_doc:

            new_status = (
                "Paid"
                if pending_amount == 0
                else "Partial"
            )

            discharge_col.update_one(
                {
                    "_id": discharge_doc["_id"]
                },
                {
                    "$set": {
                        "status": new_status,
                        "items.$[].payment_status": new_status,
                        "payment_details": payment_details,
                        "shiftno": shiftno,
                        "paid_at": paid_at,
                        "CashierID": CashierID,
                        "lastmodified_by": CashierID,
                        "lastmodified_date": datetime.utcnow(),
                        **(
                            {
                                "pendingAmount": Decimal128(
                                    str(pending_amount)
                                )
                            }
                            if pending_amount > 0
                            else {}
                        ),
                    }
                }
            )

            # =============================================
            # GET bill_type FROM ITEMS
            # =============================================

            bill_type = None

            items = discharge_doc.get("items", [])

            if items and isinstance(items, list):
                bill_type = items[0].get("bill_type")

            # =============================================
            # SAVE CASH COUNTER COLLECTION
            # =============================================

            cash_counter_data = {

                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,

                "created_by": CashierID,
                "lastmodified_by": CashierID,

                "bill_no": bill_no,
                "bill_number": bill_no,

                "bill_type": bill_type,

                "counter_code": counter_id,

                "shift_no": shiftno,

                "billing_category": "Discharge",

                "transaction_type": "collected",

                "collected_amount": str(
                    payment_details.get("Paid_amount", 0)
                ),

                "Returned_amount": "0.00",

                "remarks": remarks,
            }

            cc_serializer = CashCounterCollectionSerializer(
                data=cash_counter_data
            )

            if cc_serializer.is_valid():
                cc_serializer.save()
            else:
                return Response(
                    {
                        "status": "error",
                        "serializer_errors": cc_serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "status": "success",
                    "type": "Discharge",
                    "bill_type": bill_type,
                    "bill_no": bill_no,
                    "new_payment_status": new_status
                },
                status=status.HTTP_200_OK
            )

        # =====================================================
        # NO BILL FOUND
        # =====================================================

        return Response(
            {
                "status": "error",
                "message": f"No bill found for '{bill_no}'"
            },
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception as e:

        return Response(
            {
                "status": "error",
                "message": str(e)
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    




@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def get_shift_summary_report(request):
    try:
        data = request.data
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        hospital_code = data.get("auth-hospital-code") 
        branch_code = data.get("auth-branch-code")
        queryset = Cashcountershiftdetails.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        )
        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)
        shifts = queryset.order_by("-date", "-StartingTime")
        cashier_ids = list(set([s.CashierID for s in shifts]))
        cashier_name_map = {}
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client['Global']
            profiles = list(db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            client.close()
        except:
            pass
        report_data = []
        for s in shifts:
            res = format_shift_response(s)
            res["User"] = cashier_name_map.get(s.CashierID, s.CashierID)
            # Format times for report display
            res["StartTime"] = s.StartingTime.strftime("%I.%M%p").lower() if s.StartingTime else ""
            res["EndTime"] = s.closingTime.strftime("%I.%M%p").lower() if s.closingTime else ""
            report_data.append(res)
        return Response({
            "success": True,
            "data": report_data
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("❌ get_active_shift ERROR:\n", error_details)
        return Response({"success": False, "message": str(e), "traceback": error_details}, status=500)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_registration_bills(request):
    try:
        # S &  AUTH DATA (Robust header check)
        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = request.data.get("auth-branch-code") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE")) or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE")) or request.META.get("HTTP_BRANCH_CODE")
        # ================================
        # S &  FILTER BILLING DATA
        # ================================
        from ..models import Billing
        filter_query = {
            "payment_status": "Pending"
        }
        if hospital_code is not None:
            filter_query["hospital_code"] = hospital_code
        if branch_code is not None:
            filter_query["branch_code"] = branch_code
        # Using ORM for Registration bills as they are natively in Django
        bills = Billing.objects.select_related('patient').filter(**filter_query).order_by('-billed_date')
        response_data = []
        # ================================
        # S &  BUILD RESPONSE
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
                "total_fees": convert_decimal(bill.total_fees),
                "payment_status": bill.payment_status
            })

        return Response({
            "status": True,
            "count": len(response_data),
            "data": response_data
        }, status=status.HTTP_200_OK)
    except Exception as e:
        import traceback
        return Response({
            "status": False,
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    



from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from pymongo import MongoClient
from bson.decimal128 import Decimal128
from bson import ObjectId

from datetime import datetime
import os

# ---------------------------------------------------
# MONGO CONNECTION
# ---------------------------------------------------

MONGO_URI = os.getenv("GLOBAL_DB_HOST")

client = MongoClient(MONGO_URI)

# HMS DATABASE
mongo_db = client["HMS"]

# GLOBAL DATABASE
global_db = client["Global"]


# ---------------------------------------------------
# COMMON SERIALIZER
# ---------------------------------------------------

def convert_decimal(value):

    if isinstance(value, Decimal128):
        return float(value.to_decimal())

    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, list):
        return [convert_decimal(v) for v in value]

    if isinstance(value, dict):
        return {k: convert_decimal(v) for k, v in value.items()}

    return value


# ---------------------------------------------------
# GET RETURN BILLS
# ---------------------------------------------------

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_return_bills(request):

    print("Before_get_return_bills")

    try:

        # ---------------------------------------------------
        # REQUEST DATA
        # ---------------------------------------------------

        data = request.data

        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        employee_id   = data.get("auth-user-id")

        # ---------------------------------------------------
        # CURRENT DATE
        # ---------------------------------------------------

        current_date = datetime.utcnow().date()

        # ---------------------------------------------------
        # VALIDATION
        # ---------------------------------------------------

        if not employee_id:

            return Response(
                {
                    "status": "error",
                    "message": "auth-user-id is required"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ---------------------------------------------------
        # COLLECTIONS
        # ---------------------------------------------------

        salesreturn_collection = mongo_db["hospital_salesreturn"]

        refund_collection = mongo_db["hospital_refund"]

        investrefund_collection = mongo_db["hospital_investrefund"]

        ipadvance_refund_collection = mongo_db["hospital_ipadvance_refund"]

        patient_collection = mongo_db["hospital_patient"]

        cashcounter_collection = mongo_db["hospital_cashcounter"]

        profile_collection = global_db["backend_diagnostics_profile"]

        # ---------------------------------------------------
        # GET EMPLOYEE PROFILE
        # ---------------------------------------------------

        profile_data = profile_collection.find_one(
            {
                "employeeId": str(employee_id)
            }
        )

        if not profile_data:

            return Response(
                {
                    "status": "error",
                    "message": "Employee profile not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # ---------------------------------------------------
        # CHECK HMS OUTLETS
        # ---------------------------------------------------

        hms_outlets = profile_data.get("hms_outlets", [])

        if outlet_code not in hms_outlets:

            return Response(
                {
                    "status": "error",
                    "message": "Outlet not mapped for employee",
                    "employee_outlets": hms_outlets
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ---------------------------------------------------
        # GET CASHCOUNTER
        # ---------------------------------------------------

        emp_cashcounter = profile_data.get("cashcounter")

        if not emp_cashcounter:

            return Response(
                {
                    "status": "error",
                    "message": "Cashcounter not mapped for employee"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ---------------------------------------------------
        # GET CASHCOUNTER DATA
        # ---------------------------------------------------

        cashcounter_data = cashcounter_collection.find_one(
            {
                "counter_id": emp_cashcounter,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet": outlet_code,
                "is_active": True
            }
        )

        if not cashcounter_data:

            return Response(
                {
                    "status": "error",
                    "message": "Matching cashcounter not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )

        counter_id = cashcounter_data.get("counter_id")

        counter_name = cashcounter_data.get("counter_name")

        allowed_bill_types = cashcounter_data.get(
            "bill_type",
            []
        )

        # ---------------------------------------------------
        # BILL TYPE MAP
        # ---------------------------------------------------

        bill_type_map = {}

        allowed_bill_type_ids = []

        if isinstance(allowed_bill_types, list):

            for item in allowed_bill_types:

                if isinstance(item, dict):

                    bill_type = item.get("bill_type")

                    bill_name = item.get("bill_name")

                    bill_type_map[bill_type] = bill_name

                    allowed_bill_type_ids.append(bill_type)

        # ---------------------------------------------------
        # COMMON DOCUMENT PROCESSOR
        # ---------------------------------------------------

        def process_documents(documents, collection_name):

            processed = []

            for doc in documents:

                doc = convert_decimal(doc)

                # ---------------------------------------------------
                # BILL TYPE FILTER
                # ---------------------------------------------------

                bill_type = doc.get("bill_type")

                try:
                    bill_type = int(bill_type)
                except:
                    pass

                if (
                    allowed_bill_type_ids
                    and bill_type not in allowed_bill_type_ids
                ):
                    continue

                # ---------------------------------------------------
                # GET UHID
                # ---------------------------------------------------

                uhid = (
                    doc.get("uhid")
                    or doc.get("UHID")
                )

                # ---------------------------------------------------
                # GET PATIENT NAME
                # ---------------------------------------------------

                patient_name = ""

                if uhid:

                    patient_data = patient_collection.find_one(
                        {
                            "uhid": uhid,
                            "hospital_code": hospital_code,
                            "branch_code": branch_code
                        }
                    )

                    if patient_data:

                        salutation = patient_data.get(
                            "salutation",
                            ""
                        )

                        first_name = patient_data.get(
                            "firstName",
                            ""
                        )

                        last_name = patient_data.get(
                            "lastName",
                            ""
                        )

                        patient_name = (
                            f"{salutation} "
                            f"{first_name} "
                            f"{last_name}"
                        ).strip()

                # ---------------------------------------------------
                # BILL TYPE NAME
                # ---------------------------------------------------

                bill_type_name = bill_type_map.get(
                    bill_type,
                    str(bill_type) if bill_type else None
                )

                # ---------------------------------------------------
                # ADD EXTRA FIELDS
                # ---------------------------------------------------

                doc["collection_name"] = collection_name
                doc["patient_name"] = patient_name
                doc["counter_id"] = counter_id
                doc["counter_name"] = counter_name
                doc["bill_type_name"] = bill_type_name

                doc["hospital_code"] = (
                    doc.get("hospital_code")
                    or hospital_code
                )

                doc["branch_code"] = (
                    doc.get("branch_code")
                    or branch_code
                )

                doc["outlet_code"] = (
                    doc.get("outlet_code")
                    or outlet_code
                )

                processed.append(doc)

            return processed

        # ---------------------------------------------------
        # FETCH SALES RETURN
        # ONLY CURRENT DATE
        # ---------------------------------------------------

        salesreturn_docs = list(
            salesreturn_collection.find(
                {
                    "status": {
                        "$in": ["Pending", "Paid"]
                    },
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code,
                    "$expr": {
                        "$eq": [
                            {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$return_bill_date"
                                }
                            },
                            current_date.strftime("%Y-%m-%d")
                        ]
                    }
                }
            )
        )

        # ---------------------------------------------------
        # FETCH REFUND
        # ONLY CURRENT DATE
        # ---------------------------------------------------

        refund_docs = list(
            refund_collection.find(
                {
                    "status": {
                        "$in": ["Pending", "Paid"]
                    },
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code,
                    "$expr": {
                        "$eq": [
                            {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$refund_date"
                                }
                            },
                            current_date.strftime("%Y-%m-%d")
                        ]
                    }
                }
            )
        )

        # ---------------------------------------------------
        # FETCH IP ADVANCE REFUND
        # ONLY CURRENT DATE
        # ---------------------------------------------------

        ipadvance_docs = list(
            ipadvance_refund_collection.find(
                {
                    "status": {
                        "$in": ["Pending", "Paid"]
                    },
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code,
                    "$expr": {
                        "$eq": [
                            {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$refund_date"
                                }
                            },
                            current_date.strftime("%Y-%m-%d")
                        ]
                    }
                }
            )
        )

        # ---------------------------------------------------
        # FETCH INVEST REFUND
        # ONLY CURRENT DATE
        # ---------------------------------------------------

        investrefund_docs = list(
            investrefund_collection.find(
                {
                    "paymentStatus": {
                        "$in": ["Pending", "Paid"]
                    },
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code,
                    "$expr": {
                        "$eq": [
                            {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$refundBillDate"
                                }
                            },
                            current_date.strftime("%Y-%m-%d")
                        ]
                    }
                }
            )
        )

        # ---------------------------------------------------
        # PROCESS DOCUMENTS
        # ---------------------------------------------------

        response_data = []

        response_data.extend(
            process_documents(
                salesreturn_docs,
                "hospital_salesreturn"
            )
        )

        response_data.extend(
            process_documents(
                refund_docs,
                "hospital_refund"
            )
        )

        response_data.extend(
            process_documents(
                ipadvance_docs,
                "hospital_ipadvance_refund"
            )
        )

        response_data.extend(
            process_documents(
                investrefund_docs,
                "hospital_investrefund"
            )
        )

        # ---------------------------------------------------
        # SORT BY DATE DESC
        # ---------------------------------------------------

        def get_sort_date(item):

            return (
                item.get("return_bill_date")
                or item.get("refund_date")
                or item.get("created_date")
                or item.get("refundBillDate")
                or ""
            )

        response_data = sorted(
            response_data,
            key=get_sort_date,
            reverse=True
        )

        # ---------------------------------------------------
        # FINAL RESPONSE
        # ---------------------------------------------------

        return Response(
            {
                "status": "success",

                "count": len(response_data),

                "cashcounter_details": {
                    "counter_id": counter_id,
                    "counter_name": counter_name,
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code,
                    "bill_types": allowed_bill_types
                },

                "data": response_data
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:

        return Response(
            {
                "status": "error",
                "message": str(e)
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )






from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from pymongo import MongoClient
from bson.decimal128 import Decimal128
from datetime import datetime

from ..serializers import CashCounterCollectionSerializer

import os

# =====================================================
# MONGO CONNECTION
# =====================================================

client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

mongo_db = client["HMS"]

# =====================================================
# COLLECTIONS
# =====================================================

sales_return_col        = mongo_db["hospital_salesreturn"]
refund_collection       = mongo_db["hospital_refund"]
investrefund_collection = mongo_db["hospital_investrefund"]
ipadvance_refund_collection = mongo_db["hospital_ipadvance_refund"]

# =====================================================
# HELPER: build & save CashCounterCollection row
# =====================================================

def _save_cash_counter(
    hospital_code,
    branch_code,
    outlet_code,
    cashier_id,
    bill_no,           # original bill_no  (e.g. "2627/000001")
    return_bill_no,    # return / refund bill_no (e.g. "2627/000003")
    bill_type,
    counter_id,
    shiftno,
    billing_category,
    paid_amount,
    remarks="",
):
    """
    Creates one CashCounterCollection row for a return / refund payment.

    Field mapping
    ─────────────
    bill_no        → original bill that was returned / refunded
    return_bill_no → the return / refund bill number
    bill_number    → same as original bill_no (for backward compatibility)
    transaction_type = "Refund"  (cashier is paying money OUT to the patient)
    collected_amount = 0.00      (nothing being collected)
    Returned_amount  = paid_amount
    """
    cash_counter_data = {
        "hospital_code":    hospital_code,
        "branch_code":      branch_code,
        "outlet_code":      outlet_code,
        "created_by":       cashier_id,
        "lastmodified_by":  cashier_id,
        # ── bill references ─────────────────────────────────────────────
        "bill_no":          bill_no,            # original bill
        "return_bill_no":   return_bill_no,     # return / refund bill  ← NEW
        "bill_number":      bill_no,            # kept for backward compatibility
        # ── classification ──────────────────────────────────────────────
        "bill_type":        bill_type,
        "counter_code":     counter_id,
        "shift_no":         shiftno,
        "billing_category": billing_category,
        "transaction_type": "Refund",
        # ── amounts ─────────────────────────────────────────────────────
        "collected_amount": "0.00",
        "Returned_amount":  str(paid_amount),
        # ── misc ────────────────────────────────────────────────────────
        "remarks":          remarks,
    }

    serializer = CashCounterCollectionSerializer(data=cash_counter_data)
    if serializer.is_valid():
        serializer.save()
        return True, None
    return False, serializer.errors


# =====================================================
# HELPER: build the $set payload for payment update
# =====================================================

def _payment_set(cashier_id, payment_details, shiftno, pending_amount, new_status):
    return {
        "status":           "Paid",            # was "Pending" → always "Paid" after cashier processes
        "payment_status":   new_status,        # "Refund" or "Partial"
        "payment_details":  payment_details,
        "shiftno":          shiftno,
        "refund_datetime":  datetime.utcnow().isoformat(),
        "paid_at":          datetime.utcnow().isoformat(),
        "CashierID":        cashier_id,
        "lastmodified_by":  cashier_id,
        "lastmodified_date": datetime.utcnow(),
        "pendingAmount":    Decimal128(str(pending_amount)),
    }


# =====================================================
# API: POST /cashcounter/collectpayment_return_bills/
# =====================================================

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def collectpayment_return_bills(request):
    """
    Collect / process a cashier payment for a return / refund bill.

    Expected payload
    ─────────────────
    {
        "uhid":           "S026/0000001",
        "bill_no":        "2627/000001",          ← original bill (from GET response)
        "return_bill_no": "2627/000003",          ← return/refund bill number
        "bill_type":      42,                     ← from the bill row's bill_type
        "counter_id":     "CC0002",
        "shiftno":        "2627/000029",
        "payment_details": {
            "method":      "Cash",
            "Paid_amount": 21.24
        },
        "pendingAmount":  0,                      ← optional; > 0 → Partial status
        "remarks":        ""                      ← optional
    }

    Logic
    ──────
    1. Try each Mongo collection in order:
       hospital_salesreturn      → field: return_bill_no
       hospital_refund           → field: refund_bill_no
       hospital_investrefund     → field: refund_bill_no
       hospital_ipadvance_refund → field: refund_bill_no

    2. When matched:
       • Update document: document_status / payment_status → "Refund"
         (or "Partial" if pending_amount > 0), add payment_details,
         shiftno, CashierID, refund_datetime.
       • Insert one CashCounterCollection row:
           bill_no        = original bill_no
           return_bill_no = return/refund bill_no   ← BOTH stored
           bill_number    = original bill_no
           transaction_type = "Refund"

    3. Return success / error JSON.
    """

    try:

        data = request.data

        # ── Auth context ────────────────────────────────────────────────────
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        cashier_id    = data.get("auth-user-id")

        # ── Request payload ─────────────────────────────────────────────────
        uhid            = data.get("uhid")
        bill_no         = data.get("bill_no")            # original bill (e.g. "2627/000001")
        return_bill_no  = data.get("return_bill_no")     # return/refund bill (e.g. "2627/000003")
        bill_type       = data.get("bill_type")          # int, from the bill row
        counter_id      = data.get("counter_id")
        shiftno         = data.get("shiftno", "")
        payment_details = data.get("payment_details")
        remarks         = data.get("remarks", "")

        # ── Validation ───────────────────────────────────────────────────────
        if not return_bill_no:
            return Response(
                {"status": "error", "message": "return_bill_no is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not payment_details:
            return Response(
                {"status": "error", "message": "payment_details is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not bill_type:
            return Response(
                {"status": "error", "message": "bill_type is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paid_amount = float(payment_details.get("Paid_amount", 0))

        if paid_amount <= 0:
            return Response(
                {"status": "error", "message": "Paid_amount must be greater than 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Determine new status ─────────────────────────────────────────────
        # We compare paid_amount against the document's return_amount later;
        # for now derive pending from what the frontend sends (if any).
        # The frontend should send pendingAmount = return_amount - paid_amount.
        pending_amount = float(data.get("pendingAmount", 0))

        new_status = "Partial" if pending_amount > 0 else "Refund"

        base_filter = {
            "hospital_code": hospital_code,
            "branch_code":   branch_code,
            "outlet_code":   outlet_code,
        }

        # ═══════════════════════════════════════════════════════════════
        # 1. hospital_salesreturn  — keyed on return_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = sales_return_col.find_one(
            {**base_filter, "return_bill_no": return_bill_no}
        )

        if doc:
            sales_return_col.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(cashier_id, payment_details, shiftno, pending_amount, new_status)},
            )

            # Resolve the original bill_no from the matched document (most reliable source)
            original_bill_no = doc.get("bill_no") or bill_no or ""

            ok, errors = _save_cash_counter(
                hospital_code, branch_code, outlet_code,
                cashier_id,
                original_bill_no,   # original bill_no  → bill_no + bill_number
                return_bill_no,     # return bill_no    → return_bill_no  ← NEW
                bill_type,
                counter_id,
                shiftno,
                "Sales Return",
                paid_amount,
                remarks,
            )
            if not ok:
                return Response(
                    {"status": "error", "message": "CashCounter save failed.", "serializer_errors": errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status":              "success",
                    "type":                "Sales Return",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid,
                    "new_document_status": new_status,
                },
                status=status.HTTP_200_OK,
            )

        # ═══════════════════════════════════════════════════════════════
        # 2. hospital_refund  — keyed on refund_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = refund_collection.find_one(
            {**base_filter, "refund_bill_no": return_bill_no}
        )

        if doc:
            refund_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(cashier_id, payment_details, shiftno, pending_amount, new_status)},
            )

            original_bill_no = doc.get("bill_no") or bill_no or ""

            ok, errors = _save_cash_counter(
                hospital_code, branch_code, outlet_code,
                cashier_id,
                original_bill_no,
                return_bill_no,
                bill_type,
                counter_id,
                shiftno,
                "Refund",
                paid_amount,
                remarks,
            )
            if not ok:
                return Response(
                    {"status": "error", "message": "CashCounter save failed.", "serializer_errors": errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status":              "success",
                    "type":                "Refund",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid,
                    "new_document_status": new_status,
                },
                status=status.HTTP_200_OK,
            )

        # ═══════════════════════════════════════════════════════════════
        # 3. hospital_investrefund  — keyed on refund_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = investrefund_collection.find_one(
            {**base_filter, "refund_bill_no": return_bill_no}
        )

        if doc:
            investrefund_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(cashier_id, payment_details, shiftno, pending_amount, new_status)},
            )

            original_bill_no = doc.get("bill_no") or bill_no or ""

            ok, errors = _save_cash_counter(
                hospital_code, branch_code, outlet_code,
                cashier_id,
                original_bill_no,
                return_bill_no,
                bill_type,
                counter_id,
                shiftno,
                "Investigation Refund",
                paid_amount,
                remarks,
            )
            if not ok:
                return Response(
                    {"status": "error", "message": "CashCounter save failed.", "serializer_errors": errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status":              "success",
                    "type":                "Investigation Refund",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid,
                    "new_document_status": new_status,
                },
                status=status.HTTP_200_OK,
            )

        # ═══════════════════════════════════════════════════════════════
        # 4. hospital_ipadvance_refund  — keyed on refund_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = ipadvance_refund_collection.find_one(
            {**base_filter, "refund_bill_no": return_bill_no}
        )

        if doc:
            ipadvance_refund_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(cashier_id, payment_details, shiftno, pending_amount, new_status)},
            )

            original_bill_no = doc.get("bill_no") or bill_no or ""

            ok, errors = _save_cash_counter(
                hospital_code, branch_code, outlet_code,
                cashier_id,
                original_bill_no,
                return_bill_no,
                bill_type,
                counter_id,
                shiftno,
                "IP Advance Refund",
                paid_amount,
                remarks,
            )
            if not ok:
                return Response(
                    {"status": "error", "message": "CashCounter save failed.", "serializer_errors": errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status":              "success",
                    "type":                "IP Advance Refund",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid,
                    "new_document_status": new_status,
                },
                status=status.HTTP_200_OK,
            )

        # ── No document matched ──────────────────────────────────────────────
        return Response(
            {
                "status":  "error",
                "message": f"No return/refund bill found for '{return_bill_no}'.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception as exc:
        return Response(
            {"status": "error", "message": str(exc)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )