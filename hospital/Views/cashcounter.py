from pymongo import MongoClient, DESCENDING
import os
import re
from rest_framework.decorators import api_view

from rest_framework.response import Response

from django.utils import timezone

import traceback

from datetime import datetime

from bson.decimal128 import Decimal128

from decimal import Decimal

from ..models import Cashcountershiftdetails,PharmacyBilling,Patient,DischargeBilling,Billing


from ..serializers import CashcountershiftdetailsSerializer,PharmacyBillingSerializer, PatientSerializer, DischargeBillingSerializer, BillingSerializer
from .dbcollection import (
    get_employee_cashcounter_permissions,
    validate_employee_cashcounter_access,
    filter_bills_by_employee_counter,
    extract_aud_employee_id,
    admission_collection,
    patient_collection
)
def format_dt(val):
    if not val: return None
    if isinstance(val, str):
        s = val.strip()
        if "T" in s and not s.endswith("Z") and "+" not in s:
            return s + "Z"
        return s
    try:
        if getattr(val, "tzinfo", None) is None:
            return val.isoformat() + "Z"
        return val.astimezone(timezone.utc).isoformat()
    except:
        return str(val)
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
            # Convert to model instance for compatibility (filtering to valid fields)
            from ..models import Cashcountershiftdetails
            doc.pop('_id', None)
            valid_fields = {f.name for f in Cashcountershiftdetails._meta.get_fields()}
            clean_doc = {k: v for k, v in doc.items() if k in valid_fields}
            return Cashcountershiftdetails(**clean_doc)
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

def generate_shift_no(cash_counter=None):
    import re
    now = datetime.now()
    if now.month >= 4:
        start, end = now.year, now.year + 1
    else:
        start, end = now.year - 1, now.year
    fy = f"{str(start)[-2:]}{str(end)[-2:]}"

    # Extract 2-digit counter code from cash_counter (e.g. "CC0001" -> "01", "CC0002" -> "02")
    counter_code = "01"
    if cash_counter:
        digits = re.findall(r"\d+", str(cash_counter))
        if digits:
            try:
                num = int(digits[-1])
                counter_code = str(num).zfill(2)
            except Exception:
                counter_code = "01"

    from pymongo import MongoClient
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    col = db["hospital_cashcountershiftdetails"]
    prefix = f"{fy}/{counter_code}/"
    shifts = list(col.find({"shiftno": {"$regex": f"^{re.escape(prefix)}"}}, {"shiftno": 1}))

    last_number = 0
    for s in shifts:
        try:
            s_no = str(s.get("shiftno", "")).strip()
            parts = s_no.split("/")
            if len(parts) >= 3:
                num = int(parts[-1])
                if num > last_number:
                    last_number = num
        except Exception:
            continue

    new_number = last_number + 1
    return f"{prefix}{str(new_number).zfill(6)}"


def resolve_outlet(outlet_input, db):
    """
    Resolves an outlet input (which could be an outlet_code like 'OLET003' or
    an outlet_name like 'MAIN BLOCK') to (outlet_code, outlet_name).
    """
    if not outlet_input:
        return None, None
    clean = str(outlet_input).strip()
    col = db["hospital_outlets"]
    doc = col.find_one({"outlet_code": re.compile(f"^{re.escape(clean)}$", re.I)})
    if not doc:
        doc = col.find_one({"outlet_name": re.compile(f"^{re.escape(clean)}$", re.I)})
    if doc:
        return doc.get("outlet_code"), doc.get("outlet_name")
    return clean, clean


def outlets_match(out1, out2, db):
    """
    Checks if two outlet identifiers match, whether passed as codes or names.
    """
    if not out1 or not out2:
        return False
    c1, n1 = resolve_outlet(out1, db)
    c2, n2 = resolve_outlet(out2, db)
    if c1 and c2 and str(c1).strip().upper() == str(c2).strip().upper():
        return True
    if n1 and n2 and str(n1).strip().upper() == str(n2).strip().upper():
        return True
    return False


def find_cashcounter_doc(counter_input, db):
    """
    Looks up a cash counter document in hospital_cashcounter by counter_id or counter_name,
    handling code variations like CC001 vs CC0001.
    """
    if not counter_input:
        return None
    clean = str(counter_input).strip()
    col = db["hospital_cashcounter"]

    # 1. Exact or case-insensitive match on counter_id
    doc = col.find_one({"counter_id": re.compile(f"^{re.escape(clean)}$", re.I)})
    if doc:
        return doc

    # 2. Number normalization: CC001 -> matches CC0001, CC01, CC1
    m = re.match(r"^([A-Za-z]+)0*(\d+)$", clean)
    if m:
        prefix, num = m.group(1), int(m.group(2))
        doc = col.find_one({"counter_id": re.compile(f"^{prefix}0*{num}$", re.I)})
        if doc:
            return doc

    # 3. Match by counter_name
    return col.find_one({"counter_name": re.compile(f"^{re.escape(clean)}$", re.I)})


def get_counter_aliases(counter_doc, counter_id_input):
    """
    Returns a list of aliases (e.g. ['CC0001', 'CC001', 'CC01', 'CC1', counter_name])
    for robust MongoDB queries against running shifts.
    """
    aliases = set()
    for val in [counter_id_input, counter_doc.get("counter_id") if counter_doc else None, counter_doc.get("counter_name") if counter_doc else None]:
        if val:
            aliases.add(str(val).strip())

    raw_candidates = [counter_id_input]
    if counter_doc and counter_doc.get("counter_id"):
        raw_candidates.append(counter_doc.get("counter_id"))

    for item in raw_candidates:
        if not item:
            continue
        m = re.match(r"^([A-Za-z]+)0*(\d+)$", str(item).strip())
        if m:
            prefix, num = m.group(1).upper(), int(m.group(2))
            aliases.add(f"{prefix}{num}")
            aliases.add(f"{prefix}{num:02d}")
            aliases.add(f"{prefix}{num:03d}")
            aliases.add(f"{prefix}{num:04d}")

    return list(aliases)

def generate_accounts_bill_no(db, date_val):
    if date_val.month >= 4:
        start, end = date_val.year, date_val.year + 1
    else:
        start, end = date_val.year - 1, date_val.year
    fy = f"{str(start)[-2:]}{str(end)[-2:]}"
    prefix = f"ACT/{fy}/"
    
    col = db["hospital_cashcountercollection"]
    records = list(col.find({"bill_number": {"$regex": f"^{prefix}"}}))
    last_num = 0
    for r in records:
        b_no = r.get("bill_number", "")
        try:
            num = int(b_no.split("/")[-1])
            if num > last_num:
                last_num = num
        except:
            pass
    new_num = last_num + 1
    return f"{prefix}{str(new_num).zfill(5)}"

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

def validate_active_shift(shiftno, counter_id, outlet_code, hospital_code, branch_code):
    """
    Validates that:
    1. There is an active shift for the specified counter or shiftno.
    2. The provided shiftno matches an active shift.
    3. The shift's status is 'active'.
    """
    if not shiftno and not counter_id:
        return False, "Shift number or Cash Counter is required for transaction.", None

    from pymongo import MongoClient
    import os
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    col = db["hospital_cashcountershiftdetails"]

    # 1. If shiftno is given, look up that exact shift
    if shiftno:
        clean_shiftno = str(shiftno).strip()
        doc = col.find_one({
            "shiftno": clean_shiftno,
            "ShiftStatus": "active",
            "is_active": True
        })
        if doc:
            client.close()
            return True, "Shift is active and valid.", doc.get("shiftno")

        # Check if the shift was already closed
        closed_doc = col.find_one({"shiftno": clean_shiftno})
        if closed_doc:
            client.close()
            return False, f"Shift '{clean_shiftno}' is already closed or inactive. Please start a new shift.", None

    # 2. Lookup active shift by counter_id
    query = {
        "ShiftStatus": "active",
        "is_active": True,
    }
    if counter_id:
        query["CashCounter"] = str(counter_id).strip()

    doc = col.find_one(query, sort=[("StartingTime", -1)])
    client.close()

    if not doc:
        counter_msg = f" for counter '{counter_id}'" if counter_id else ""
        return False, f"No active shift found{counter_msg}. Please open/start a shift first.", None

    active_shiftno = doc.get("shiftno")
    if shiftno and str(active_shiftno).strip() != str(shiftno).strip():
        return False, f"Shift mismatch or shift is not active. The active shift is '{active_shiftno}', but transaction requested '{shiftno}'.", active_shiftno

    return True, "Shift is active and valid.", active_shiftno

# =====================================================

# ✅ RESPONSE FORMATTER

# =====================================================

def format_shift_response(shift):
    from ..models import CashCounter
    counter_name = shift.CashCounter
    try:
        cc = CashCounter.objects.filter(counter_id=shift.CashCounter).first()
        if cc:
            counter_name = cc.counter_name
    except:
        pass

    prev_closing = 0.0
    try:
        prev_closing = convert_decimal(getattr(shift, "previous_closing_balance", 0.0))
    except Exception:
        pass

    return {

        "shiftno": shift.shiftno,

        "CashierID": shift.CashierID,

        "CashCounter": shift.CashCounter,

        "CashCounterName": counter_name,

        "OpeningBalance": convert_decimal(shift.OpeningBalance),

        "previous_closing_balance": prev_closing,

        "ClosingBalance": convert_decimal(shift.ClosingBalance),

        "collected_Amount": convert_decimal(shift.collected_Amount),
        "CreditAmount": convert_decimal(getattr(shift, "CreditAmount", 0)),
        "credit_amount": convert_decimal(getattr(shift, "CreditAmount", 0)),

        "PettyCashBalance": convert_decimal(shift.PettyCashBalance),

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
 
    hospital_code = data.get("auth-hospital-code")
    branch_code   = data.get("auth-branch-code")
    outlet_code   = data.get("auth-outlet-code")
    employee_id   = data.get("auth-user-id") or extract_aud_employee_id(request)

    if isinstance(outlet_code, (list, tuple)):
        outlet_code = outlet_code[0] if outlet_code else None

    if not employee_id:
        return Response({
            "success": False,
            "message": "User not authenticated. Employee ID is required."
        }, status=401)

    # =====================================================
    # ✅ CREATE SHIFT (POST)
    # =====================================================
    if request.method == "POST":
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        global_db = client["Global"]
        hms_db = client["HMS"]
        profile_col = global_db["backend_diagnostics_profile"]
        shift_col = hms_db["hospital_cashcountershiftdetails"]

        try:
            query_id = str(employee_id).strip()
            search_query = {"employeeId": {"$in": [query_id, int(query_id) if query_id.isdigit() else query_id]}}
        except Exception:
            search_query = {"employeeId": str(employee_id).strip()}
            
        profile_data = profile_col.find_one(search_query)
        emp_cashcounter = profile_data.get("cashcounter") if profile_data else None

        # 1. ENFORCE: Profile must have an assigned cash counter
        if not emp_cashcounter or not str(emp_cashcounter).strip():
            return Response({
                "success": False,
                "code": "NO_COUNTER_ALLOCATED",
                "message": "No cash counter is allocated to your profile. Please assign a cash counter in Employee Master before starting a shift."
            }, status=400)

        assigned_counter = str(emp_cashcounter).strip()
        req_counter = data.get("CashCounter")

        # Resolve counter doc in hospital_cashcounter
        cc_doc = find_cashcounter_doc(assigned_counter, hms_db)
        if not cc_doc:
            return Response({
                "success": False,
                "code": "COUNTER_NOT_FOUND",
                "message": f"Assigned cash counter '{assigned_counter}' was not found in hospital cash counter master."
            }, status=400)

        canonical_counter_id = str(cc_doc.get("counter_id") or assigned_counter).strip()
        counter_name = str(cc_doc.get("counter_name") or canonical_counter_id).strip()
        allotted_outlet = str(cc_doc.get("outlet") or "").strip()
        allotted_outlet_code, allotted_outlet_name = resolve_outlet(allotted_outlet, hms_db)

        # If client explicitly specifies a counter code starting with CC, verify it matches assigned counter
        if req_counter and str(req_counter).strip().startswith("CC"):
            req_doc = find_cashcounter_doc(req_counter, hms_db)
            req_canonical = (req_doc.get("counter_id") if req_doc else req_counter).strip().upper()
            if req_canonical != canonical_counter_id.upper():
                return Response({
                    "success": False,
                    "code": "COUNTER_ACCESS_DENIED",
                    "message": f"Access blocked: Cashier {employee_id} is assigned to counter '{canonical_counter_id}' ({counter_name}) and cannot start counter '{req_counter}'."
                }, status=403)

        # 2. ENFORCE OUTLET ALLOCATION: Compare request active outlet against counter's allotted outlet
        raw_current_outlet = (
            data.get("SelectedOutlet")
            or data.get("auth-outlet-code")
            or data.get("outlet_code")
            or request.headers.get("auth-outlet-code")
            or request.headers.get("Outlet-Code")
            or outlet_code
        )
        if isinstance(raw_current_outlet, (list, tuple)):
            raw_current_outlet = raw_current_outlet[0] if raw_current_outlet else None
        raw_current_outlet = str(raw_current_outlet).strip() if raw_current_outlet else ""
        current_outlet_code, current_outlet_name = resolve_outlet(raw_current_outlet, hms_db)

        if not outlets_match(raw_current_outlet, allotted_outlet, hms_db):
            return Response({
                "success": False,
                "code": "OUTLET_MISMATCH",
                "message": f"Cash Counter '{counter_name}' ({canonical_counter_id}) is allotted to outlet '{allotted_outlet_name}' ({allotted_outlet_code}). You are currently on '{current_outlet_name or raw_current_outlet}'. You can only start a shift for this counter in '{allotted_outlet_name}'."
            }, status=400)

        # 3. ENFORCE NO RUNNING SHIFT ON THIS COUNTER: Check globally across ALL outlets
        counter_aliases = get_counter_aliases(cc_doc, assigned_counter)
        existing_counter_shift = shift_col.find_one({
            "CashCounter": {"$in": counter_aliases},
            "ShiftStatus": "active",
            "is_active": True,
            "closingTime": None
        }, sort=[("StartingTime", -1)])

        if existing_counter_shift:
            existing_cashier = str(existing_counter_shift.get("CashierID", "")).strip()
            if existing_cashier != str(employee_id).strip():
                return Response({
                    "success": False,
                    "code": "COUNTER_ALREADY_RUNNING",
                    "message": f"Cash Counter '{counter_name}' ({canonical_counter_id}) already has an active running shift ({existing_counter_shift.get('shiftno')}) started by cashier '{existing_cashier}'. Only one active shift is permitted per counter."
                }, status=400)
            else:
                existing_model = Cashcountershiftdetails.objects.filter(shiftno=existing_counter_shift.get("shiftno")).first()
                return Response({
                    "success": True,
                    "message": "You already have an active shift for this counter.",
                    "data": format_shift_response(existing_model) if existing_model else existing_counter_shift
                })

        # 4. ENFORCE CASHIER ONLY HAS ONE ACTIVE SHIFT: Check if cashier is active on another counter
        existing_cashier_shift = shift_col.find_one({
            "CashierID": str(employee_id).strip(),
            "CashCounter": {"$nin": counter_aliases},
            "ShiftStatus": "active",
            "is_active": True,
            "closingTime": None
        }, sort=[("StartingTime", -1)])

        if existing_cashier_shift:
            return Response({
                "success": False,
                "code": "CASHIER_ALREADY_ACTIVE",
                "message": f"Cashier {employee_id} already has an active running shift ({existing_cashier_shift.get('shiftno')}) on counter '{existing_cashier_shift.get('CashCounter')}'. Please close that shift before starting a new one."
            }, status=400)

        # 5. START SHIFT WITH CANONICAL DATA
        shift_no = generate_shift_no(canonical_counter_id)
        # Opening balance defaults to 0.00 for all shifts
        opening_balance = convert_decimal128(data.get("OpeningBalance") if data.get("OpeningBalance") is not None else 0)
        petty_cash_balance = convert_decimal128(data.get("PettyCashBalance", 0))

        final_outlet_code = allotted_outlet_code or current_outlet_code or "OLET003"
        final_selected_outlet = allotted_outlet_code or current_outlet_code or "OLET003"
        prev_closing = get_previous_shift_balance(canonical_counter_id, final_selected_outlet, hospital_code, branch_code)

        payload = {
            "shiftno": shift_no,
            "CashierID": str(employee_id),
            "CashCounter": str(canonical_counter_id),
            "CashCounterName": str(counter_name),
            "SelectedOutlet": str(final_selected_outlet),
            "OpeningBalance": opening_balance,
            "previous_closing_balance": Decimal128(str(prev_closing)),
            "PettyCashBalance": petty_cash_balance,
            "StartingTime": data.get("StartingTime") or timezone.now(),
            "ShiftStatus": "active",

            "created_by": str(employee_id),
            "created_date": timezone.now(),
            "date": timezone.now().date(),

            "hospital_code": str(hospital_code),
            "branch_code": str(branch_code),
            "outlet_code": str(final_outlet_code),
            "created_br": str(branch_code),

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

        is_admin_or_manager = data.get("force_close") is True or data.get("is_admin") is True
        if shift.CashierID != employee_id and not is_admin_or_manager:
            return Response({
                "success": False,
                "message": "Shift must be closed by the same cashier who opened it, or by an administrator."
            }, status=403)

        if shift.ShiftStatus != "active":
            return Response({"success": False, "message": "Shift is already closed"})

        closing_balance_raw = data.get("ClosingBalance")
        closing_time = data.get("closingTime") or timezone.now()

        # Recalculate collection before closing to ensure accuracy
        totals = calculate_shift_collection(shift_no)
        
        shift.collected_Amount = safe_dec(totals.get('total_collection', 0))
        shift.CreditAmount = safe_dec(totals.get('total_credit', 0))
        shift.SalesReturnAmount = safe_dec(totals.get('sales_return', 0))
        
        # RemittedToBank, SubmittedToAccount, HandOverAmount are not used/subtracted
        shift.RemittedToBank = Decimal('0.00')
        shift.SubmittedToAccount = Decimal('0.00')
        shift.HandOverAmount = Decimal('0.00')
        # Formula: Opening Balance + Cash Collected - Sales Return
        shift.ClosingBalance = safe_dec(shift.OpeningBalance) + safe_dec(shift.collected_Amount) - safe_dec(shift.SalesReturnAmount)
        
        # ✅ Thoroughly clean all decimal fields before saving to avoid conflicts
        for field in [
            'OpeningBalance', 'ClosingBalance', 'collected_Amount', 'CreditAmount',
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

        try:
            m_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            m_db = m_client["HMS"]
            m_db["hospital_cashcountershiftdetails"].update_one(
                {"shiftno": str(shift_no)},
                {"$set": {
                    "collected_Amount": Decimal128(str(shift.collected_Amount)),
                    "CreditAmount": Decimal128(str(shift.CreditAmount)),
                    "ClosingBalance": Decimal128(str(shift.ClosingBalance)),
                    "SalesReturnAmount": Decimal128(str(shift.SalesReturnAmount)),
                }}
            )
            m_client.close()
        except Exception:
            pass

        # ✅ Record remitted/submitted transactions in hospital_cashcountercollection
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client["HMS"]
            
            # Record Remitted
            remitted_val = float(shift.RemittedToBank)
            if remitted_val > 0:
                existing = db["hospital_cashcountercollection"].find_one({
                    "shift_no": shift_no,
                    "billing_category": "remitted",
                    "transaction_type": "remitted"
                })
                if not existing:
                    bill_no_remit = generate_accounts_bill_no(db, timezone.now())
                    db["hospital_cashcountercollection"].insert_one({
                        "created_by": employee_id,
                        "created_date": timezone.now(),
                        "lastmodified_by": employee_id,
                        "lastmodified_date": timezone.now(),
                        "branch_code": branch_code or shift.branch_code,
                        "outlet_code": outlet_code or shift.outlet_code,
                        "hospital_code": hospital_code or shift.hospital_code,
                        "counter_code": shift.CashCounter,
                        "shift_no": shift_no,
                        "billing_category": "remitted",
                        "bill_number": bill_no_remit,
                        "transaction_type": "remitted",
                        "collected_amount": Decimal128(str(remitted_val)),
                        "Returned_amount": Decimal128("0.00"),
                        "remarks": "Remitted to Bank on closing"
                    })
                else:
                    db["hospital_cashcountercollection"].update_one(
                        {"_id": existing["_id"]},
                        {"$set": {
                            "collected_amount": Decimal128(str(remitted_val)),
                            "lastmodified_by": employee_id,
                            "lastmodified_date": timezone.now()
                        }}
                    )

            # Record Submitted
            submitted_val = float(shift.SubmittedToAccount)
            if submitted_val > 0:
                existing = db["hospital_cashcountercollection"].find_one({
                    "shift_no": shift_no,
                    "billing_category": "submit",
                    "transaction_type": "submit"
                })
                if not existing:
                    bill_no_submit = generate_accounts_bill_no(db, timezone.now())
                    db["hospital_cashcountercollection"].insert_one({
                        "created_by": employee_id,
                        "created_date": timezone.now(),
                        "lastmodified_by": employee_id,
                        "lastmodified_date": timezone.now(),
                        "branch_code": branch_code or shift.branch_code,
                        "outlet_code": outlet_code or shift.outlet_code,
                        "hospital_code": hospital_code or shift.hospital_code,
                        "counter_code": shift.CashCounter,
                        "shift_no": shift_no,
                        "billing_category": "submit",
                        "bill_number": bill_no_submit,
                        "transaction_type": "submit",
                        "collected_amount": Decimal128(str(submitted_val)),
                        "Returned_amount": Decimal128("0.00"),
                        "remarks": "Submitted to Account on closing"
                    })
                else:
                    db["hospital_cashcountercollection"].update_one(
                        {"_id": existing["_id"]},
                        {"$set": {
                            "collected_amount": Decimal128(str(submitted_val)),
                            "lastmodified_by": employee_id,
                            "lastmodified_date": timezone.now()
                        }}
                    )
            client.close()
        except Exception as e:
            print("Error recording remitted/submitted to cash counter collection:", e)

        return Response({
            "success": True,
            "message": "Shift closed successfully",
            "data": format_shift_response(shift)
        })

def parse_payment_split(doc, default_amt=0.0):
    """
    Parses a bill or receipt document to separate payment into:
    cash_amount, credit_amount (where credit_amount includes UPI, Card, Credit, Cheque, Online, etc.)
    """
    def _clean_num(v):
        if v is None:
            return 0.0
        if hasattr(v, 'to_decimal'):
            try:
                return float(v.to_decimal())
            except:
                pass
        try:
            return float(v)
        except:
            return 0.0

    tot = _clean_num(default_amt)

    pd = doc.get("payment_details")
    if isinstance(pd, str):
        import json, ast
        try:
            pd = json.loads(pd)
        except:
            try:
                pd = ast.literal_eval(pd)
            except:
                pd = None

    if isinstance(pd, dict):
        method = str(pd.get("method") or "").strip().lower()
        if "multiple" in method or pd.get("breakdown"):
            bd = pd.get("breakdown") or []
            cash_sum = 0.0
            credit_sum = 0.0
            for item in bd:
                if isinstance(item, dict):
                    m = str(item.get("method") or "").strip().lower()
                    amt = _clean_num(item.get("Paid_amount") or item.get("amount") or 0)
                    if "cash" in m:
                        cash_sum += amt
                    else:
                        credit_sum += amt
            if (cash_sum + credit_sum) > 0:
                return cash_sum, credit_sum
        else:
            amt = _clean_num(pd.get("Paid_amount") or pd.get("amount") or tot)
            if "cash" in method:
                return amt, 0.0
            elif method:
                return 0.0, amt

    # Check payment_method / payment_mode / PaymentType / mode_of_payment
    for k in ["payment_method", "payment_mode", "paymentMode", "PaymentType", "mode_of_payment"]:
        val = str(doc.get(k) or "").strip().lower()
        if not val or val == "none":
            continue
        if "cash" in val:
            return tot, 0.0
        elif any(term in val for term in ["card", "upi", "credit", "cheque", "checque", "check", "chq", "bank", "online", "pos", "pay later", "insurance", "neft", "rtgs", "dd", "demand draft"]):
            return 0.0, tot

    # If payment mode is completely unspecified, default to cash
    return tot, 0.0


def calculate_shift_collection(shift_no):
    """
    Calculates the total collected amount and other financial metrics for a shift.
    collected amount only includes cash amount.
    UPI, CARD, CREDIT, CHEQUE, ONLINE, etc. are calculated into total_credit (Credit Amount).
    """
    def to_float(val):
        if val is None:
            return 0.0
        if hasattr(val, 'to_decimal'):
            try:
                return float(val.to_decimal())
            except:
                pass
        try:
            return float(val)
        except:
            return 0.0

    results = {
        "total_collection": 0.0,  # Only cash amount
        "total_credit": 0.0,      # UPI, Card, Credit, Cheque, Online, etc.
        "cash_collection": 0.0,
        "credit_collection": 0.0,
        "pending_amount": 0.0,
        "ip_advance": 0.0,
        "sales_return": 0.0,
        "receipts": 0.0,
        "payments": 0.0
    }

    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        shift_vals = [shift_no]
        try:
            shift_vals.append(int(shift_no))
        except (ValueError, TypeError):
            pass
        try:
            shift_vals.append(str(shift_no))
        except (ValueError, TypeError):
            pass
        shift_vals = list(set(shift_vals))

        # 1. Billing (Registration/Consultation)
        paid_bills = list(db["hospital_billing"].find(
            {"shiftno": {"$in": shift_vals}, "payment_status": {"$in": ["Paid", "Billing"]}},
            {"total_fees": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1}
        ))
        for b in paid_bills:
            fee = to_float(b.get("total_fees", 0))
            c_amt, cr_amt = parse_payment_split(b, fee)
            results["total_collection"] += c_amt
            results["total_credit"] += cr_amt
            results["cash_collection"] += c_amt
            results["credit_collection"] += cr_amt
        
        # Pending
        pending_bills = list(db["hospital_billing"].find(
            {"shiftno": {"$in": shift_vals}, "payment_status": {"$in": ["Pending", "Cash Pending"]}},
            {"total_fees": 1}
        ))
        for b in pending_bills:
            results["pending_amount"] += to_float(b.get("total_fees", 0))

        # 2. Investigation
        paid_invest = list(db["hospital_investbilling"].find(
            {"shiftno": {"$in": shift_vals}, "paymentStatus": "Paid"},
            {"finalPrice": 1, "total": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1}
        ))
        for d in paid_invest:
            inv_amt = to_float(d.get("finalPrice") or d.get("total") or 0)
            c_amt, cr_amt = parse_payment_split(d, inv_amt)
            results["total_collection"] += c_amt
            results["total_credit"] += cr_amt
            results["cash_collection"] += c_amt
            results["credit_collection"] += cr_amt
            
        pending_invest = list(db["hospital_investbilling"].find(
            {"shiftno": {"$in": shift_vals}, "paymentStatus": "Pending"},
            {"finalPrice": 1, "total": 1}
        ))
        for d in pending_invest:
            results["pending_amount"] += to_float(d.get("finalPrice") or d.get("total") or 0)

        # 3. Discharge
        paid_discharge = list(db["hospital_dischargebilling"].find(
            {"shiftno": {"$in": shift_vals}, "status": "Paid"},
            {"net_amount": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1}
        ))
        for d in paid_discharge:
            dis_amt = to_float(d.get("net_amount", 0))
            c_amt, cr_amt = parse_payment_split(d, dis_amt)
            results["total_collection"] += c_amt
            results["total_credit"] += cr_amt
            results["cash_collection"] += c_amt
            results["credit_collection"] += cr_amt
            
        pending_discharge = list(db["hospital_dischargebilling"].find(
            {"shiftno": {"$in": shift_vals}, "status": "Pending"},
            {"net_amount": 1}
        ))
        for d in pending_discharge:
            results["pending_amount"] += to_float(d.get("net_amount", 0))

        # 4. Pharmacy
        paid_pharmacy = list(db["hospital_pharmacybilling"].find(
            {"shiftno": {"$in": shift_vals}, "billing_status": "Paid"},
            {"net_amount": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1}
        ))
        for d in paid_pharmacy:
            ph_amt = to_float(d.get("net_amount", 0))
            c_amt, cr_amt = parse_payment_split(d, ph_amt)
            results["total_collection"] += c_amt
            results["total_credit"] += cr_amt
            results["cash_collection"] += c_amt
            results["credit_collection"] += cr_amt
            
        pending_pharmacy = list(db["hospital_pharmacybilling"].find(
            {"shiftno": {"$in": shift_vals}, "billing_status": "Pending"},
            {"net_amount": 1}
        ))
        for d in pending_pharmacy:
            results["pending_amount"] += to_float(d.get("net_amount", 0))

        # 5. IP Advance (from Admission model's advance_payments)
        native_adms = list(db["hospital_admission"].find(
            {"advance_payments.shiftno": {"$in": shift_vals}},
            {"advance_payments": 1}
        ))
        
        counted_advance_ids = set()
        for adm in native_adms:
            payments = adm.get("advance_payments", [])
            if isinstance(payments, str):
                import json, ast
                try:
                    payments = json.loads(payments)
                except:
                    try:
                        payments = ast.literal_eval(payments)
                    except:
                        payments = []
            if isinstance(payments, list):
                for p in payments:
                    if isinstance(p, dict) and p.get("shiftno") in shift_vals:
                        bill_no = p.get("bill_no")
                        if bill_no and bill_no not in counted_advance_ids:
                            # Only count collected (Paid) advances
                            if str(p.get("status", "")).lower() == "paid":
                                amt = to_float(p.get("advance_amount", 0))
                                results["ip_advance"] += amt
                                c_amt, cr_amt = parse_payment_split(p, amt)
                                results["total_collection"] += c_amt
                                results["total_credit"] += cr_amt
                                results["cash_collection"] += c_amt
                                results["credit_collection"] += cr_amt
                                counted_advance_ids.add(bill_no)

        # 6. Sales Return & Refunds
        for col_name, amt_fields in [
            ("hospital_salesreturn", ["return_amount", "amount"]),
            ("hospital_refund", ["refund_amount", "amount"]),
            ("hospital_investrefund", ["refund_finalPrice", "refund_amount", "amount"]),
            ("hospital_ipadvance_refund", ["refund_amount", "advance_amount", "amount"]),
        ]:
            col_returns = list(db[col_name].find(
                {"shiftno": {"$in": shift_vals}},
                {"return_amount": 1, "refund_amount": 1, "refund_finalPrice": 1, "advance_amount": 1, "amount": 1,
                 "payment_details": 1, "payment_method": 1, "PaymentType": 1, "payment_mode": 1}
            ))
            for r in col_returns:
                amt = 0.0
                for fld in amt_fields:
                    if r.get(fld):
                        amt = to_float(r.get(fld))
                        break
                if amt == 0.0 and isinstance(r.get("payment_details"), dict):
                    amt = to_float(r["payment_details"].get("Paid_amount", 0))

                results["sales_return"] += amt
                c_ret, cr_ret = parse_payment_split(r, amt)
                if cr_ret > 0 and c_ret == 0:
                    results["total_credit"] = max(0.0, results["total_credit"] - cr_ret)
                    results["credit_collection"] = max(0.0, results["credit_collection"] - cr_ret)
                else:
                    deduct = c_ret if c_ret > 0 else amt
                    results["total_collection"] = max(0.0, results["total_collection"] - deduct)
                    results["cash_collection"] = max(0.0, results["cash_collection"] - deduct)

        # 7. Receipt and Payment
        rp_docs = list(db["hospital_receiptandpayment"].find(
            {"shiftno": {"$in": shift_vals}},
            {"amount": 1, "receipt_type": 1, "payment_details": 1, "payment_method": 1, "payment_mode": 1, "mode_of_payment": 1}
        ))
        for d in rp_docs:
            amt = to_float(d.get("amount", 0))
            if d.get("receipt_type") == "Receipt":
                results["receipts"] += amt
                c_amt, cr_amt = parse_payment_split(d, amt)
                results["total_collection"] += c_amt
                results["total_credit"] += cr_amt
                results["cash_collection"] += c_amt
                results["credit_collection"] += cr_amt
            elif d.get("receipt_type") == "Payment":
                results["payments"] += amt
                results["total_collection"] -= amt
                results["cash_collection"] -= amt

        client.close()

    except Exception as e:
        print("Error calculating shift collection:", e)
        traceback.print_exc()

    return results


def recalculate_and_update_shift_details(shift_no):
    """
    Recalculates and updates all collection, return, remitted, and hand over amounts
    in hospital_cashcountershiftdetails for a given shift_no.
    """
    if not shift_no:
        return

    try:
        from ..models import Cashcountershiftdetails, CashCounterCollection
        from django.db.models import Sum

        try:
            shift = Cashcountershiftdetails.objects.get(shiftno=shift_no)
        except Cashcountershiftdetails.DoesNotExist:
            print(f"[recalculate_and_update_shift_details] Shift {shift_no} not found.")
            return

        # 1. Recalculate collection and returns using existing function
        totals = calculate_shift_collection(shift_no)
        
        # 2. Update collected_Amount, CreditAmount, and SalesReturnAmount
        shift.collected_Amount = safe_dec(totals.get('total_collection', 0))
        shift.CreditAmount = safe_dec(totals.get('total_credit', 0))
        shift.SalesReturnAmount = safe_dec(totals.get('sales_return', 0))

        # 3. Sum up RemittedToBank and HandOverAmount, and check for close-shift records or manual entries in MongoDB directly
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        col = db["hospital_cashcountercollection"]

        remitted_sum = Decimal('0.00')
        handover_sum = Decimal('0.00')
        extra_remitted = Decimal('0.00')
        extra_submit = Decimal('0.00')

        shift_vals = [shift_no]
        try:
            shift_vals.append(int(shift_no))
        except (ValueError, TypeError):
            pass
        try:
            shift_vals.append(str(shift_no))
        except (ValueError, TypeError):
            pass
        shift_vals = list(set(shift_vals))

        docs = list(col.find(
            {"shift_no": {"$in": shift_vals}},
            {"RemittedToBank": 1, "HandOverAmount": 1, "billing_category": 1, "collected_amount": 1}
        ))
        for doc in docs:
            # Sum up RemittedToBank and HandOverAmount
            remitted_sum += safe_dec(doc.get("RemittedToBank"))
            handover_sum += safe_dec(doc.get("HandOverAmount"))

            # Check for extra remitted/submit categories
            cat = doc.get("billing_category")
            val = doc.get("collected_amount", 0)
            if cat == "remitted":
                extra_remitted += safe_dec(val)
            elif cat == "submit":
                extra_submit += safe_dec(val)

        client.close()

        # 4. Set fields - RemittedToBank and HandOverAmount are not used
        shift.RemittedToBank = Decimal('0.00')
        shift.HandOverAmount = Decimal('0.00')
        shift.SubmittedToAccount = Decimal('0.00')

        # ClosingBalance = OpeningBalance + collected_Amount (Cash) - SalesReturnAmount
        shift.ClosingBalance = safe_dec(shift.OpeningBalance) + safe_dec(shift.collected_Amount) - safe_dec(shift.SalesReturnAmount)

        # Clean all decimal fields to avoid conversion/saving errors
        for field in [
            'OpeningBalance', 'ClosingBalance', 'collected_Amount', 'CreditAmount',
            'PettyCashBalance', 'RemittedToBank', 'SubmittedToAccount', 
            'HandOverAmount', 'PendingAmount', 'IPAdvanceAmount', 'SalesReturnAmount'
        ]:
            if hasattr(shift, field):
                setattr(shift, field, safe_dec(getattr(shift, field, 0)))

        shift.save()

        # Also sync directly to MongoDB
        try:
            m_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            m_db = m_client["HMS"]
            m_db["hospital_cashcountershiftdetails"].update_one(
                {"shiftno": str(shift_no)},
                {"$set": {
                    "collected_Amount": Decimal128(str(shift.collected_Amount)),
                    "CreditAmount": Decimal128(str(shift.CreditAmount)),
                    "ClosingBalance": Decimal128(str(shift.ClosingBalance)),
                    "SalesReturnAmount": Decimal128(str(shift.SalesReturnAmount)),
                }}
            )
            m_client.close()
        except Exception:
            pass

        print(f"[recalculate_and_update_shift_details] Shift {shift_no} updated successfully.")

    except Exception as e:
        print(f"[recalculate_and_update_shift_details] Error: {e}")
        traceback.print_exc()


# =====================================================
# ✅ DEDICATED ADMIN CLOSE SHIFT API
# =====================================================
@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def admin_close_shift(request):
    """
    Dedicated Administrator API to close an active cash counter shift.
    Allows administrators and managers to close shifts on behalf of any cashier,
    recalculating collection totals, recording remitted and submitted transactions,
    updating shift status to inactive, and logging administrator audit details.
    """
    try:
        data = request.data or {}

        shift_no = data.get("shiftno") or data.get("shift_no")
        if not shift_no:
            return Response({"success": False, "message": "shiftno is required"}, status=400)

        admin_id = (
            data.get("admin_id")
            or data.get("auth-user-id")
            or request.META.get("HTTP_AUTH_USER_ID")
            or request.headers.get("auth-user-id")
            or extract_aud_employee_id(request)
            or "ADMIN"
        )
        hospital_code = (
            data.get("auth-hospital-code")
            or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
            or request.headers.get("Hospital-Code")
            or "SH001"
        )
        branch_code = (
            data.get("auth-branch-code")
            or request.META.get("HTTP_BRANCH_CODE")
            or request.headers.get("Branch-Code")
            or "SHB001"
        )
        outlet_code = (
            data.get("auth-outlet-code")
            or data.get("outlet_code")
            or data.get("SelectedOutlet")
            or request.META.get("HTTP_AUTH_OUTLET_CODE")
        )
        remarks = data.get("remarks") or data.get("reason") or "Closed by Administrator"

        # 1. Fetch shift via PyMongo directly to avoid Djongo localhost issues
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        col = db["hospital_cashcountershiftdetails"]

        # Priority 1: Match by exact MongoDB _id if sent from frontend
        shift_id = data.get("_id") or data.get("id")
        m_shift = None
        if shift_id:
            from bson.objectid import ObjectId
            try:
                m_shift = col.find_one({"_id": ObjectId(str(shift_id))})
            except Exception:
                pass

        # Priority 2: Match ACTIVE shift with this shiftno
        if not m_shift or m_shift.get("ShiftStatus") != "active":
            active_shift = col.find_one({"shiftno": shift_no, "ShiftStatus": "active"})
            if active_shift:
                m_shift = active_shift

        # Priority 3: Match shift by shiftno where closingTime is None
        if not m_shift or m_shift.get("ShiftStatus") != "active":
            unclosed_shift = col.find_one({"shiftno": shift_no, "closingTime": None})
            if unclosed_shift:
                m_shift = unclosed_shift

        # Priority 4: Match latest shift by StartingTime / _id
        if not m_shift:
            m_shift = col.find_one({"shiftno": shift_no}, sort=[("StartingTime", -1), ("_id", -1)])

        if not m_shift:
            client.close()
            return Response({"success": False, "message": f"Shift {shift_no} not found"}, status=404)

        # Check if already closed, but search for active duplicate before failing
        if m_shift.get("ShiftStatus") != "active" and not m_shift.get("is_active") and m_shift.get("closingTime") is not None:
            active_fallback = col.find_one({
                "shiftno": shift_no,
                "$or": [{"ShiftStatus": "active"}, {"closingTime": None}, {"is_active": True}]
            })
            if active_fallback:
                m_shift = active_fallback
            else:
                client.close()
                return Response({"success": False, "message": f"Shift {shift_no} is already closed"}, status=400)

        closing_time = data.get("closingTime") or timezone.now()

        # 2. Recalculate totals
        totals = calculate_shift_collection(shift_no)
        collected_amount = float(safe_dec(totals.get('total_collection', 0)))
        credit_amount = float(safe_dec(totals.get('total_credit', 0)))
        sales_return = float(safe_dec(totals.get('sales_return', 0)))

        def to_num(val, default=0.0):
            if val is None:
                return default
            try:
                if hasattr(val, 'to_decimal'):
                    return float(val.to_decimal())
                return float(val)
            except Exception:
                return default

        opening_balance = to_num(m_shift.get("OpeningBalance", 0))
        remitted_val = 0.0
        submitted_val = 0.0
        handover_val = 0.0

        # Formula: Opening Balance + Cash Collected - Sales Return
        closing_balance = opening_balance + collected_amount - sales_return

        # 3. Update MongoDB shift document
        update_fields = {
            "ShiftStatus": "inactive",
            "is_active": False,
            "closingTime": closing_time,
            "ClosingBalance": Decimal128(f"{closing_balance:.2f}"),
            "collected_Amount": Decimal128(f"{collected_amount:.2f}"),
            "CreditAmount": Decimal128(f"{credit_amount:.2f}"),
            "SalesReturnAmount": Decimal128(f"{sales_return:.2f}"),
            "closed_by_admin": True,
            "admin_id": str(admin_id),
            "admin_close_remarks": remarks,
            "lastmodified_by": str(admin_id),
            "lastmodified_date": timezone.now()
        }
        # Update the exact document by _id
        col.update_one({"_id": m_shift["_id"]}, {"$set": update_fields})

        # Also close any other active duplicates with this shiftno to eliminate ghost active shifts
        col.update_many(
            {"shiftno": shift_no, "ShiftStatus": "active"},
            {"$set": {
                "ShiftStatus": "inactive",
                "is_active": False,
                "closingTime": closing_time,
                "lastmodified_by": str(admin_id),
                "lastmodified_date": timezone.now()
            }}
        )

        # 4. Also update Django ORM instance if possible
        try:
            orm_shift = Cashcountershiftdetails.objects.filter(shiftno=shift_no).first()
            if orm_shift:
                orm_shift.ShiftStatus = "inactive"
                orm_shift.is_active = False
                orm_shift.closingTime = closing_time
                orm_shift.ClosingBalance = safe_dec(closing_balance)
                orm_shift.collected_Amount = safe_dec(collected_amount)
                orm_shift.CreditAmount = safe_dec(credit_amount)
                orm_shift.SalesReturnAmount = safe_dec(sales_return)
                orm_shift.RemittedToBank = safe_dec(remitted_val)
                orm_shift.SubmittedToAccount = safe_dec(submitted_val)
                orm_shift.HandOverAmount = safe_dec(handover_val)
                orm_shift.lastmodified_by = str(admin_id)
                orm_shift.lastmodified_date = timezone.now()
                orm_shift.save()
        except Exception as orm_err:
            print("Notice: ORM shift save skipped/error:", orm_err)

        # 5. Record Remitted to Bank in hospital_cashcountercollection
        counter_code = m_shift.get("CashCounter", "")
        shift_branch = branch_code or m_shift.get("branch_code", "SHB001")
        shift_outlet = outlet_code or m_shift.get("outlet_code") or m_shift.get("SelectedOutlet", "")
        shift_hospital = hospital_code or m_shift.get("hospital_code", "SH001")

        if remitted_val > 0:
            existing_remit = db["hospital_cashcountercollection"].find_one({
                "shift_no": shift_no,
                "billing_category": "remitted",
                "transaction_type": "remitted"
            })
            if not existing_remit:
                bill_no_remit = generate_accounts_bill_no(db, timezone.now())
                db["hospital_cashcountercollection"].insert_one({
                    "created_by": str(admin_id),
                    "created_date": timezone.now(),
                    "lastmodified_by": str(admin_id),
                    "lastmodified_date": timezone.now(),
                    "branch_code": shift_branch,
                    "outlet_code": shift_outlet,
                    "hospital_code": shift_hospital,
                    "counter_code": counter_code,
                    "shift_no": shift_no,
                    "billing_category": "remitted",
                    "bill_number": bill_no_remit,
                    "transaction_type": "remitted",
                    "collected_amount": Decimal128(f"{remitted_val:.2f}"),
                    "Returned_amount": Decimal128("0.00"),
                    "remarks": f"Remitted to Bank on admin closing ({remarks})"
                })
            else:
                db["hospital_cashcountercollection"].update_one(
                    {"_id": existing_remit["_id"]},
                    {"$set": {
                        "collected_amount": Decimal128(f"{remitted_val:.2f}"),
                        "lastmodified_by": str(admin_id),
                        "lastmodified_date": timezone.now()
                    }}
                )

        # 6. Record Submitted to Account in hospital_cashcountercollection
        if submitted_val > 0:
            existing_submit = db["hospital_cashcountercollection"].find_one({
                "shift_no": shift_no,
                "billing_category": "submit",
                "transaction_type": "submit"
            })
            if not existing_submit:
                bill_no_submit = generate_accounts_bill_no(db, timezone.now())
                db["hospital_cashcountercollection"].insert_one({
                    "created_by": str(admin_id),
                    "created_date": timezone.now(),
                    "lastmodified_by": str(admin_id),
                    "lastmodified_date": timezone.now(),
                    "branch_code": shift_branch,
                    "outlet_code": shift_outlet,
                    "hospital_code": shift_hospital,
                    "counter_code": counter_code,
                    "shift_no": shift_no,
                    "billing_category": "submit",
                    "bill_number": bill_no_submit,
                    "transaction_type": "submit",
                    "collected_amount": Decimal128(f"{submitted_val:.2f}"),
                    "Returned_amount": Decimal128("0.00"),
                    "remarks": f"Submitted to Account on admin closing ({remarks})"
                })
            else:
                db["hospital_cashcountercollection"].update_one(
                    {"_id": existing_submit["_id"]},
                    {"$set": {
                        "collected_amount": Decimal128(f"{submitted_val:.2f}"),
                        "lastmodified_by": str(admin_id),
                        "lastmodified_date": timezone.now()
                    }}
                )

        # 7. Prepare response data
        counter_name = counter_code
        try:
            cc = db["hospital_cashcounter"].find_one({"counter_id": counter_code})
            if cc and cc.get("counter_name"):
                counter_name = cc.get("counter_name")
        except:
            pass

        client.close()

        resp_data = {
            "shiftno": shift_no,
            "CashierID": m_shift.get("CashierID"),
            "CashCounter": counter_code,
            "CashCounterName": counter_name,
            "OpeningBalance": opening_balance,
            "ClosingBalance": round(closing_balance, 2),
            "collected_Amount": round(collected_amount, 2),
            "CreditAmount": round(credit_amount, 2),
            "credit_amount": round(credit_amount, 2),
            "ShiftStatus": "inactive",
            "StartingTime": str(m_shift.get("StartingTime")),
            "closingTime": str(closing_time),
            "date": str(m_shift.get("date")),
            "is_active": False,
            "closed_by_admin": True,
            "admin_id": str(admin_id),
            "admin_close_remarks": remarks
        }

        return Response({
            "success": True,
            "message": f"Shift {shift_no} successfully closed by administrator ({admin_id}).",
            "data": resp_data
        })

    except Exception as e:
        import traceback
        err_str = traceback.format_exc()
        print("❌ admin_close_shift ERROR:\n", err_str)
        return Response({
            "success": False,
            "message": f"Error closing shift: {str(e)}",
            "traceback": err_str
        }, status=500)


# =====================================================

# ✅ MAIN API

        # ✅ SAFE DEBUG
        # print("Queryset exists:", queryset.exists())


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_active_shift(request):
    try:
        data = request.data or {}
 
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        employee_id   = data.get("auth-user-id") 

        if isinstance(outlet_code, (list, tuple)):
            outlet_code = outlet_code[0] if outlet_code else None 
        
        # Get cashcounter from employee profile
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        global_db = client["Global"]
        hms_db = client["HMS"]
        profile_col = global_db["backend_diagnostics_profile"]
        shift_col = hms_db["hospital_cashcountershiftdetails"]
        
        try:
            query_id = str(employee_id).strip()
            search_query = {"employeeId": {"$in": [query_id, int(query_id) if query_id.isdigit() else query_id]}}
        except Exception:
            search_query = {"employeeId": str(employee_id).strip()}
            
        profile_data = profile_col.find_one(search_query)
        emp_cashcounter = profile_data.get("cashcounter") if profile_data else None

        if not emp_cashcounter or not str(emp_cashcounter).strip():
            return Response({
                "success": False,
                "message": "No cash counter is allocated to your profile. Please assign a cash counter in Employee Master before starting a shift.",
                "counter_allocated": False,
                "is_active": False,
                "shift_active": False
            })

        assigned_counter = str(emp_cashcounter).strip()
        cc_doc = find_cashcounter_doc(assigned_counter, hms_db)
        if not cc_doc:
            return Response({
                "success": False,
                "message": f"Assigned cash counter '{assigned_counter}' was not found in hospital cash counter master.",
                "counter_allocated": False,
                "is_active": False,
                "shift_active": False
            })

        canonical_counter_id = str(cc_doc.get("counter_id") or assigned_counter).strip()
        counter_name = str(cc_doc.get("counter_name") or canonical_counter_id).strip()
        allotted_outlet = str(cc_doc.get("outlet") or "").strip()
        allotted_outlet_code, allotted_outlet_name = resolve_outlet(allotted_outlet, hms_db)

        # Resolve current active outlet from request
        raw_current_outlet = (
            outlet_code
            or data.get("SelectedOutlet")
            or data.get("outlet_code")
            or request.headers.get("auth-outlet-code")
            or request.headers.get("Outlet-Code")
        )
        if isinstance(raw_current_outlet, (list, tuple)):
            raw_current_outlet = raw_current_outlet[0] if raw_current_outlet else None
        raw_current_outlet = str(raw_current_outlet).strip() if raw_current_outlet else ""
        current_outlet_code, current_outlet_name = resolve_outlet(raw_current_outlet, hms_db)

        outlet_match = outlets_match(raw_current_outlet, allotted_outlet, hms_db) if raw_current_outlet else True

        cashcounter_details = {
            "counter_id": canonical_counter_id,
            "counter_name": counter_name,
            "outlet": allotted_outlet_code,
            "outlet_name": allotted_outlet_name
        }
        allowed_bill_type_details = cc_doc.get("bill_type", [])

        # Check running shifts
        counter_aliases = get_counter_aliases(cc_doc, assigned_counter)

        # Check running shift on this counter globally
        counter_running_shift = shift_col.find_one({
            "CashCounter": {"$in": counter_aliases},
            "ShiftStatus": "active",
            "is_active": True,
            "closingTime": None
        }, sort=[("StartingTime", -1)])

        counter_occupied = False
        occupied_by = None
        occupied_shiftno = None
        if counter_running_shift:
            shift_cashier = str(counter_running_shift.get("CashierID", "")).strip()
            if shift_cashier != str(employee_id).strip():
                counter_occupied = True
                occupied_by = shift_cashier
                occupied_shiftno = str(counter_running_shift.get("shiftno", ""))

        # Check if the active user has their own running shift on this counter
        shift = None
        if counter_running_shift and not counter_occupied:
            shift = get_shift_pymongo({"_id": counter_running_shift["_id"]}, "StartingTime")

        if not shift:
            # Fallback check for this CashierID on this counter
            fallback_doc = shift_col.find_one({
                "CashierID": str(employee_id).strip(),
                "CashCounter": {"$in": counter_aliases},
                "ShiftStatus": "active",
                "is_active": True,
                "closingTime": None
            }, sort=[("StartingTime", -1)])
            if fallback_doc:
                shift = get_shift_pymongo({"_id": fallback_doc["_id"]}, "StartingTime")

        if not shift:
            expected = get_previous_shift_balance(canonical_counter_id, allotted_outlet_code, hospital_code, branch_code)
            return Response({
                "success": False,
                "message": "No active shift found",
                "counter_allocated": True,
                "outlet_match": outlet_match,
                "allotted_outlet": allotted_outlet_code,
                "allotted_outlet_name": allotted_outlet_name,
                "current_outlet": current_outlet_code,
                "current_outlet_name": current_outlet_name,
                "outlet_mismatch_message": (
                    f"Cash Counter '{counter_name}' ({canonical_counter_id}) is allotted to outlet '{allotted_outlet_name}' ({allotted_outlet_code}). You are currently on '{current_outlet_name or raw_current_outlet}'. Please switch to '{allotted_outlet_name}' before starting a shift."
                    if not outlet_match else None
                ),
                "counter_occupied": counter_occupied,
                "occupied_by": occupied_by,
                "occupied_shiftno": occupied_shiftno,
                "occupied_message": (
                    f"Cash Counter '{counter_name}' ({canonical_counter_id}) is currently in use by cashier '{occupied_by}' (Shift #{occupied_shiftno}). Only one active shift is permitted per counter."
                    if counter_occupied else None
                ),
                "expected_opening": 0.0,
                "previous_closing_balance": expected,
                "default_petty_cash": 1000.0,
                "is_active": False,
                "shift_active": False,
                "cashcounter": cashcounter_details,
                "allowed_bill_type_details": allowed_bill_type_details
            })

        # Using global safe_dec
        # Active shift found for this cashier
        totals = calculate_shift_collection(shift.shiftno)
        shift.collected_Amount = safe_dec(totals.get('total_collection', 0))
        shift.CreditAmount = safe_dec(totals.get('total_credit', 0))
        shift.SalesReturnAmount = safe_dec(totals.get('sales_return', 0))
        shift.RemittedToBank = Decimal('0.00')
        shift.SubmittedToAccount = Decimal('0.00')
        shift.HandOverAmount = Decimal('0.00')
        # Formula: Opening Balance + Cash Collected - Sales Return
        shift.ClosingBalance = safe_dec(shift.OpeningBalance) + safe_dec(shift.collected_Amount) - safe_dec(shift.SalesReturnAmount)
        
        # ✅ Thoroughly clean all decimal fields before saving to avoid conflicts
        for field in [
            'OpeningBalance', 'ClosingBalance', 'collected_Amount', 'CreditAmount',
            'PettyCashBalance', 'RemittedToBank', 'SubmittedToAccount', 
            'HandOverAmount', 'PendingAmount', 'IPAdvanceAmount', 'SalesReturnAmount'
        ]:
            setattr(shift, field, safe_dec(getattr(shift, field, 0)))

        shift.save()

        try:
            m_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            m_db = m_client["HMS"]
            m_db["hospital_cashcountershiftdetails"].update_one(
                {"shiftno": str(shift.shiftno)},
                {"$set": {
                    "collected_Amount": Decimal128(str(shift.collected_Amount)),
                    "CreditAmount": Decimal128(str(shift.CreditAmount)),
                    "ClosingBalance": Decimal128(str(shift.ClosingBalance)),
                    "SalesReturnAmount": Decimal128(str(shift.SalesReturnAmount)),
                }}
            )
            m_client.close()
        except Exception:
            pass
        
        shift_data = format_shift_response(shift)
        try:
            prev_closing = get_previous_shift_balance(canonical_counter_id, allotted_outlet_code, hospital_code, branch_code)
            shift_data["previous_closing_balance"] = prev_closing
        except Exception:
            pass

        return Response({
            "success": True, 
            "data": shift_data,
            "counter_allocated": True,
            "outlet_match": True,
            "allotted_outlet": allotted_outlet_code,
            "allotted_outlet_name": allotted_outlet_name,
            "current_outlet": current_outlet_code,
            "current_outlet_name": current_outlet_name,
            "counter_occupied": False,
            "cashcounter": cashcounter_details,
            "allowed_bill_type_details": allowed_bill_type_details
        })
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

        # ✅ AUTH DATA (read from request.data or headers/META)
        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE") or request.META.get("HTTP_HOSPITAL_CODE")
        branch_code   = request.data.get("auth-branch-code") or request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE")
        outlet_code   = request.data.get("auth-outlet-code") or request.META.get("HTTP_AUTH_OUTLET_CODE") or request.META.get("HTTP_OUTLET_CODE")

        # 🔍 Build query dynamically
        query = {
            "is_active": True
        }

        # ✅ Add filters only if present
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code

        # Try finding outlet-specific heads first; if none exist, fall back to branch-wide heads
        if outlet_code:
            if isinstance(outlet_code, list):
                outlet_query = {**query, "outlet_code": {"$in": outlet_code}}
            else:
                outlet_query = {**query, "outlet_code": outlet_code}
            data = list(outlet_collection.find(outlet_query))
            if not data:
                data = list(outlet_collection.find(query))
        else:
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

        # Resolve cash counter from employee profile
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        global_db = client["Global"]
        profile_col = global_db["backend_diagnostics_profile"]
        try:
            query_id = str(employee_id)
            search_query = {"employeeId": {"$in": [query_id, int(query_id) if query_id.isdigit() else query_id]}}
        except:
            search_query = {"employeeId": str(employee_id)}
            
        profile_data = profile_col.find_one(search_query)
        emp_cashcounter = profile_data.get("cashcounter") if profile_data else None
        
        if emp_cashcounter:
            cash_counter = emp_cashcounter
        else:
            cash_counter = data.get("CashCounter") or request.META.get("HTTP_OUTLET_CODE")

        shiftno      = data.get("shiftno")



        # 🔴 Validation (counter code is not required or stored)
        if not all([receipt_type, account_head, amount, shiftno]):
            return Response({
                "status": "error",
                "message": "Missing required fields"
            }, status=400)

        # Active shift validation
        is_valid, msg, active_shift = validate_active_shift(
            shiftno=shiftno,
            counter_id=cash_counter,
            outlet_code=outlet_code,
            hospital_code=hospital_code,
            branch_code=branch_code
        )
        if not is_valid:
            return Response({
                "status": "error",
                "message": msg
            }, status=400)

        # ✅ Generate voucher number
        voucher_no = generate_voucher_no()

        # ✅ Create record (Counter code should not be stored)
        obj = ReceiptAndPayment.objects.create(
            receipt_type = receipt_type,
            account_head = account_head,
            description  = description,
            amount       = amount,
            voucher_no   = voucher_no,
            CashCounter  = None,
            shiftno      = shiftno,

            # ✅ From backend
            CashierID    = employee_id,
            created_by   = employee_id,
            hospital_code = hospital_code,
            branch_code   = branch_code,
            outlet_code   = outlet_code
        )

        try:
            _rp_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            _rp_client["HMS"]["hospital_receiptandpayment"].update_one(
                {"_id": obj.pk},
                {"$unset": {"CashCounter": ""}}
            )
            _rp_client.close()
        except Exception:
            pass



        serializer = ReceiptAndPaymentSerializer(obj)

        recalculate_and_update_shift_details(shiftno)

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
        def _clean_val(v, fallback=""):
            if isinstance(v, (list, tuple)):
                v = v[0] if v else ""
            if v is None:
                return fallback
            return str(v).strip()

        data = request.data or {}
        employee_id   = _clean_val(data.get("auth-user-id"))
        hospital_code = _clean_val(data.get("auth-hospital-code"))
        branch_code   = _clean_val(data.get("auth-branch-code"))
        outlet_code   = _clean_val(data.get("auth-outlet-code"))

        if not employee_id:
            return Response({"status": "error", "message": "User not authenticated"}, status=401)

        from datetime import datetime, time, timedelta

        # ✅ Check for optional date filters (from_date / to_date) and voucher_type
        from_date_str = data.get("from_date")
        to_date_str   = data.get("to_date")
        voucher_type  = data.get("voucher_type")

        # ✅ DB CONNECTION
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        transaction_col = db["hospital_receiptandpayment"]
        account_col     = db["hospital_Receiptpayment"]

        # Base query strictly based on hospital_code, branch_code, and outlet_code
        query = {}
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        # Optional voucher_type filter
        if voucher_type and str(voucher_type).strip().lower() not in ["all", ""]:
            query["receipt_type"] = voucher_type

        # Date range handling
        if from_date_str and to_date_str:
            try:
                start_dt = datetime.strptime(str(from_date_str).strip(), "%Y-%m-%d")
                end_dt   = datetime.strptime(str(to_date_str).strip(), "%Y-%m-%d") + timedelta(days=1)
                query["voucher_date"] = {"$gte": start_dt, "$lt": end_dt}
            except Exception:
                pass
        elif from_date_str:
            try:
                start_dt = datetime.strptime(str(from_date_str).strip(), "%Y-%m-%d")
                query["voucher_date"] = {"$gte": start_dt}
            except Exception:
                pass
        else:
            # ✅ Default main screen: display current date alone
            today = timezone.localdate()
            today_start = datetime.combine(today, time.min)
            today_end   = today_start + timedelta(days=1)
            query["voucher_date"] = {"$gte": today_start, "$lt": today_end}

        # ✅ FETCH DATA (strictly for this outlet, branch, hospital)
        transactions = list(transaction_col.find(query).sort("voucher_no", -1).limit(200))



        account_query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "is_active": True
        }
        if outlet_code:
            if isinstance(outlet_code, list):
                account_heads = list(account_col.find({**account_query, "outlet_code": {"$in": outlet_code}}))
            else:
                account_heads = list(account_col.find({**account_query, "outlet_code": outlet_code}))
            if not account_heads:
                account_heads = list(account_col.find(account_query))
        else:
            account_heads = list(account_col.find(account_query))



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
from datetime import datetime, date, timedelta
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

            elif isinstance(v, (datetime, date)):
                if isinstance(v, datetime):
                    new_doc[k] = v.isoformat() + ("Z" if v.tzinfo is None else "")
                else:
                    new_doc[k] = v.isoformat()

            elif isinstance(v, (dict, list)):
                new_doc[k] = serialize_mongo(v)

            else:
                new_doc[k] = v

        return new_doc

    if isinstance(doc, (datetime, date)):
        if isinstance(doc, datetime):
            return doc.isoformat() + ("Z" if doc.tzinfo is None else "")
        return doc.isoformat()

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
# ✅ PATIENT LOOKUP HELPER (ROBUST MULTI-FALLBACK SEARCH)
# =========================================================
def get_patient_info(patient_col, uhid=None, patient_id=None, hospital_code=None, branch_code=None):
    if not patient_col:
        return None

    import re

    # ── 1. Lookup by patient_id ──
    if patient_id is not None:
        pids = [patient_id]
        try:
            pids.append(int(patient_id))
        except (ValueError, TypeError):
            pass
        pids.append(str(patient_id))

        id_clauses = [
            {"id": {"$in": pids}},
            {"patient_id": {"$in": pids}},
            {"patientId": {"$in": pids}},
            {"uhid": {"$in": [str(p) for p in pids]}},
        ]

        # 1a. Try with hospital_code and branch_code
        base_query = {}
        if hospital_code:
            base_query["hospital_code"] = hospital_code
        if branch_code:
            base_query["branch_code"] = branch_code

        if base_query:
            doc = patient_col.find_one({**base_query, "$or": id_clauses})
            if doc:
                return doc

        # 1b. Fallback without hospital_code / branch_code
        doc = patient_col.find_one({"$or": id_clauses})
        if doc:
            return doc

    # ── 2. Lookup by uhid ──
    if uhid:
        uhid_str = str(uhid).strip()
        if uhid_str:
            base_query = {}
            if hospital_code:
                base_query["hospital_code"] = hospital_code
            if branch_code:
                base_query["branch_code"] = branch_code

            if base_query:
                doc = patient_col.find_one({**base_query, "uhid": uhid_str})
                if doc:
                    return doc

            doc = patient_col.find_one({"uhid": uhid_str})
            if doc:
                return doc

            doc = patient_col.find_one({"uhid": {"$regex": f"^{re.escape(uhid_str)}$", "$options": "i"}})
            if doc:
                return doc

            m = re.match(r"^([A-Za-z0-9]+/)(0*)(\d+)$", uhid_str)
            if m:
                prefix, _, num = m.groups()
                candidates = [
                    f"{prefix}{int(num):06d}",
                    f"{prefix}{int(num):05d}",
                    f"{prefix}{int(num):04d}",
                    f"{prefix}{num}",
                ]
                doc = patient_col.find_one({"uhid": {"$in": candidates}})
                if doc:
                    return doc
                doc = patient_col.find_one({"uhid": {"$regex": f"^{re.escape(prefix)}0*{num}$"}})
                if doc:
                    return doc

    # ── 3. Fallback to hospital_admission if available ──
    try:
        adm_col = hms_db["hospital_admission"]
        adm_clauses = []
        if uhid:
            adm_clauses.append({"uhid": str(uhid).strip()})
        if patient_id is not None:
            adm_clauses.extend([
                {"patient_id": patient_id},
                {"id": patient_id},
                {"inpatient_number": str(patient_id)},
            ])
        if adm_clauses:
            adm = adm_col.find_one({"$or": adm_clauses})
            if adm:
                p_details = adm.get("patient_details") or {}
                fn = p_details.get("firstName") or adm.get("patient_name") or ""
                ln = p_details.get("lastName") or ""
                sal = p_details.get("salutation") or ""
                return {
                    "uhid": adm.get("uhid") or p_details.get("uhid"),
                    "firstName": fn,
                    "lastName": ln,
                    "salutation": sal,
                    "patient_name": f"{sal} {fn} {ln}".strip() or fn,
                }
    except Exception:
        pass

    return None


def format_patient_name(patient):
    if not patient:
        return None
    salutation = (patient.get("salutation") or "").strip()
    first_name = (patient.get("firstName") or patient.get("patient_name") or patient.get("name") or "").strip()
    last_name = (patient.get("lastName") or "").strip()
    full_name = f"{salutation} {first_name} {last_name}".strip()
    return full_name if full_name else None


# =========================================================
# ✅ MAIN API
# =========================================================
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_mainblock_pendingbills(request):

    try:

        data = request.data if isinstance(request.data, dict) else {}
        employee_id = (
            data.get("auth-user-id") )
        hospital_code = (
            data.get("auth-hospital-code") 
           
        )
        branch_code = (
            data.get("auth-branch-code") 
            
        )
        outlet_code = (
            data.get("auth-outlet-code") 
           )

        final_data = []

        # =========================================================
        # ✅ EMPLOYEE CASHCOUNTER & BILL TYPE PERMISSION (aud -> profile -> cashcounter)
        # =========================================================
        emp_perms = get_employee_cashcounter_permissions(
            employee_id or request,
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code
        )

        requested_counter = data.get("CashCounter") or request.GET.get("CashCounter")
        if requested_counter and emp_perms.get("success") and emp_perms.get("counter_id"):
            if str(requested_counter).strip().upper() != str(emp_perms["counter_id"]).strip().upper():
                return Response({
                    "status": "error",
                    "code": "COUNTER_ACCESS_DENIED",
                    "message": f"Access blocked: Cashier {emp_perms['employee_id']} is assigned to counter '{emp_perms['counter_id']}' ({emp_perms['counter_name']}) and cannot access counter '{requested_counter}'.",
                    "cashcounter": emp_perms.get("cashcounter_details"),
                    "allowed_bill_type_details": emp_perms.get("bill_type_details", []),
                    "data": []
                }, status=status.HTTP_403_FORBIDDEN)

        if not emp_perms.get("success"):
            return Response({
                "status": "error",
                "message": emp_perms.get("message", "No active cash counter or bill types configured for this user"),
                "cashcounter": None,
                "allowed_bill_type_details": [],
                "shift_active": False,
                "count": 0,
                "data": []
            }, status=status.HTTP_403_FORBIDDEN)

        cashcounter_details = emp_perms["cashcounter_details"]
        allowed_bill_type_details = emp_perms["bill_type_details"]
        allowed_bill_type_ids = emp_perms["allowed_bill_types"]
        target_outlet = emp_perms["outlet"] or outlet_code
        emp_cashcounter = emp_perms["counter_id"]
        counter_id_check = emp_cashcounter
        if not employee_id:
            employee_id = emp_perms.get("employee_id")

        # =========================================================
        # ✅ VERIFY ACTIVE SHIFT IN DB (DO NOT DISPLAY IF NOT STARTED)
        # =========================================================
        shift_col = hms_db["hospital_cashcountershiftdetails"]
        counter_id_check = cashcounter_details.get("counter_id") if cashcounter_details else emp_cashcounter
        shift_filter = {
            "ShiftStatus": "active",
        }
        if hospital_code:
            shift_filter["hospital_code"] = hospital_code
        if branch_code:
            shift_filter["branch_code"] = branch_code
        if counter_id_check:
            shift_filter["CashCounter"] = counter_id_check
        active_shift = shift_col.find_one(shift_filter)
        if not active_shift and counter_id_check:
            active_shift = shift_col.find_one({
                "CashCounter": counter_id_check,
                "ShiftStatus": "active",
            })
        if not active_shift and employee_id:
            emp_shift_filter = {
                "CashierID": str(employee_id),
                "ShiftStatus": "active",
            }
            if hospital_code:
                emp_shift_filter["hospital_code"] = hospital_code
            if branch_code:
                emp_shift_filter["branch_code"] = branch_code
            active_shift = shift_col.find_one(emp_shift_filter)
        if not active_shift and employee_id:
            active_shift = shift_col.find_one({
                "CashierID": str(employee_id),
                "ShiftStatus": "active",
            })
        if not active_shift:
            # Check for any active shift
            active_shift = shift_col.find_one({
                "ShiftStatus": "active",
            })

        if not active_shift:
            return Response({
                "status": "success",
                "cashcounter": cashcounter_details,
                "allowed_bill_type_details": allowed_bill_type_details,
                "shift_active": False,
                "message": "Shift not started. Please start a shift to view bills.",
                "count": 0,
                "data": []
            }, status=status.HTTP_200_OK)

        # =========================================================
        # ✅ DYNAMIC DATE FILTER & STATUS (Pending / Unpaid / Received)
        # =========================================================
        req_status = request.GET.get("status") or (data.get("status") if data else None) or "pending"
        req_status_str = str(req_status).strip().lower()
        is_received_req = req_status_str in ["paid", "received"]
        is_unpaid_req = req_status_str in ["unpaid", "unpaid_bills"]

        status_op = "Paid" if is_received_req else "Pending"
        status_inv = "Paid" if is_received_req else "Pending"
        status_dis = "Paid" if is_received_req else "Billed"

        # Dynamic dt / date / from_date / to_date (do not hardcode anything)
        dt_param = request.GET.get("dt") or request.GET.get("date") or (data.get("dt") if data else None) or (data.get("date") if data else None)
        from_date_param = request.GET.get("from_date") or (data.get("from_date") if data else None)
        to_date_param = request.GET.get("to_date") or (data.get("to_date") if data else None)

        today = timezone.localdate() if hasattr(timezone, "localdate") else timezone.now().date()
        d_start = datetime.combine(today, datetime.min.time())
        d_end = d_start + timedelta(days=1)

        date_query = {}
        if dt_param:
            parsed_d = None
            dt_str = str(dt_param).strip()
            if "T" in dt_str:
                try:
                    parsed_d = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).date()
                except Exception:
                    pass
            if not parsed_d:
                clean_dt = dt_str.split(" ")[0]
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                    try:
                        parsed_d = datetime.strptime(clean_dt, fmt).date()
                        break
                    except Exception:
                        continue
            if parsed_d:
                p_start = datetime.combine(parsed_d, datetime.min.time())
                p_end = p_start + timedelta(days=1)
                date_query = {"$gte": p_start, "$lt": p_end}
        elif from_date_param or to_date_param:
            range_q = {}
            if from_date_param:
                f_str = str(from_date_param).strip().split(" ")[0]
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                    try:
                        range_q["$gte"] = datetime.strptime(f_str, fmt)
                        break
                    except Exception:
                        pass
            if to_date_param:
                t_str = str(to_date_param).strip().split(" ")[0]
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                    try:
                        range_q["$lt"] = datetime.strptime(t_str, fmt) + timedelta(days=1)
                        break
                    except Exception:
                        pass
            if range_q:
                date_query = range_q
        else:
            if is_unpaid_req:
                # ✅ 3. UNPAID BILLS: bills not paid on that day (prior dates before today: < d_start)
                date_query = {"$lt": d_start}
            else:
                # ✅ 2. PENDING BILLS (default): current date alone [d_start, d_end)
                date_query = {"$gte": d_start, "$lt": d_end}

        # =========================================================
        # ✅ PAYMENT FILTERS:
        # - Pending Bills: strictly Cash alone (no Credit / Insurance)
        # - Received Bills: allow all counter payments (Cash, Multiple Payment, Card, UPI, etc.)
        # =========================================================
        pending_cash_filter = {
            "$or": [
                {"payment_method": {"$regex": r"^\s*cash\s*$", "$options": "i"}},
                {"paymentMethod": {"$regex": r"^\s*cash\s*$", "$options": "i"}},
                {"payment_details.method": {"$regex": r"^\s*cash\s*$", "$options": "i"}},
                {"payment_details.payment_mode": {"$regex": r"^\s*cash\s*$", "$options": "i"}},
            ]
        }

        received_payment_filter = {
            "$or": [
                {"payment_method": {"$in": ["Cash", "cash", "CASH", "Multiple Payment", "multiple payment", "Multiple payment", "Card", "card", "UPI", "upi", "Cheque", "cheque"]}},
                {"paymentMethod": {"$in": ["Cash", "cash", "CASH", "Multiple Payment", "multiple payment", "Multiple payment", "Card", "card", "UPI", "upi", "Cheque", "cheque"]}},
                {"payment_details.method": {"$in": ["Cash", "cash", "CASH", "Multiple Payment", "multiple payment", "Multiple payment", "Card", "card", "UPI", "upi", "Cheque", "cheque"]}},
                {"payment_details.breakdown.method": {"$regex": r"^\s*cash\s*$", "$options": "i"}},
                {"shiftno": {"$ne": None}},
                {"CashierID": {"$ne": None}},
            ]
        }

        def is_allowed_bill_doc(doc):
            if not isinstance(doc, dict):
                return False
            if is_received_req:
                return True
            for fld in ("payment_method", "paymentMethod"):
                val = doc.get(fld)
                if isinstance(val, str) and val.strip().lower() == "cash":
                    return True
            pd = doc.get("payment_details")
            if isinstance(pd, dict):
                for fld in ("method", "payment_mode"):
                    val = pd.get(fld)
                    if isinstance(val, str) and val.strip().lower() == "cash":
                        return True
            return False

        def build_module_query(status_key, status_val, date_key):
            conds = [
                {status_key: status_val},
                {"is_cancelled": {"$ne": True}}
            ]
            if is_received_req:
                conds.append(received_payment_filter)
            else:
                conds.append(pending_cash_filter)

            if hospital_code:
                conds.append({"hospital_code": hospital_code})
            if branch_code:
                conds.append({"branch_code": branch_code})
            if target_outlet:
                conds.append({"outlet_code": target_outlet})

            if date_query:
                if is_received_req:
                    conds.append({
                        "$or": [
                            {"paid_date": date_query},
                            {date_key: date_query}
                        ]
                    })
                else:
                    conds.append({date_key: date_query})

            return {"$and": conds}

        # =========================================================
        # ✅ BILL TYPE NAME RESOLUTION MAP (id -> Display Name)
        # =========================================================
        bill_type_name_map = {}
        if allowed_bill_type_details:
            for btd in allowed_bill_type_details:
                b_id = btd.get("bill_type")
                b_nm = btd.get("bill_name")
                if b_id is not None and b_nm:
                    bill_type_name_map[b_id] = b_nm
                    try:
                        bill_type_name_map[int(b_id)] = b_nm
                    except (ValueError, TypeError):
                        pass
                    bill_type_name_map[str(b_id)] = b_nm

        try:
            for bt_rec in hms_db["hospital_billtype"].find({}, {"bill_type": 1, "bill_name": 1}):
                b_id = bt_rec.get("bill_type")
                b_nm = bt_rec.get("bill_name")
                if b_id is not None and b_nm:
                    bill_type_name_map[b_id] = b_nm
                    try:
                        bill_type_name_map[int(b_id)] = b_nm
                    except (ValueError, TypeError):
                        pass
                    bill_type_name_map[str(b_id)] = b_nm
        except Exception:
            pass

        # Doctor name resolver helper
        profile_col = global_db["backend_diagnostics_profile"]
        doc_name_cache = {}
        def _get_doctor_display(doc_val):
            if not doc_val:
                return "-"
            d_str = str(doc_val).strip()
            if not d_str or d_str.lower() in ["none", "null", "-", "undefined"]:
                return "-"
            if d_str in doc_name_cache:
                return doc_name_cache[d_str]
            if any(d_str.lower().startswith(p) for p in ["dr.", "dr ", "doctor"]):
                doc_name_cache[d_str] = d_str
                return d_str
            if not d_str.isdigit() and len(d_str) > 6:
                doc_name_cache[d_str] = d_str
                return d_str
            try:
                ids = [d_str]
                if d_str.isdigit():
                    ids.append(int(d_str))
                p_doc = profile_col.find_one({"employeeId": {"$in": ids}}, {"employeeName": 1, "name": 1})
                if p_doc:
                    nm = p_doc.get("employeeName") or p_doc.get("name")
                    if nm:
                        doc_name_cache[d_str] = nm
                        return nm
            except Exception:
                pass
            res = f"Dr. {d_str}" if d_str.isdigit() else d_str
            doc_name_cache[d_str] = res
            return res

        # =========================================================
        # ✅ 1. OP BILLING (payment_method: 'Cash' alone)
        # =========================================================
        billing_query = build_module_query("payment_status", status_op, "billed_date")
        billing_docs = list(billing_col.find(billing_query).sort("billed_date", -1).limit(500 if not date_query else 1000))

        for bill in billing_docs:
            if not is_allowed_bill_doc(bill):
                continue
            bill_type = bill.get("bill_type")
            try:
                bt_num = int(bill_type)
            except (ValueError, TypeError):
                bt_num = bill_type

            # ✅ FILTER BASED ON CASHCOUNTER BILL TYPES
            if allowed_bill_type_ids and bill_type not in allowed_bill_type_ids and bt_num not in allowed_bill_type_ids:
                continue

            patient = get_patient_info(
                patient_col,
                uhid=bill.get("uhid") or bill.get("patient_uhid"),
                patient_id=bill.get("patient_id"),
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            resolved_uhid = (patient.get("uhid") if patient else None) or bill.get("uhid") or bill.get("patient_uhid")
            resolved_patient_name = format_patient_name(patient) or bill.get("patient_name") or bill.get("patient") or bill.get("customer_name")
            bt_display_name = (
                bill_type_name_map.get(bill_type)
                or bill_type_name_map.get(bt_num)
                or (bill.get("bill_type_name") if bill.get("bill_type_name") else None)
                or "REGISTRATION"
            )

            doc_display = _get_doctor_display(bill.get("doctor_id") or bill.get("doctor_name") or bill.get("doctor"))
            raw_pm = bill.get("payment_method") or (bill.get("payment_details", {}).get("method") if isinstance(bill.get("payment_details"), dict) else None)
            pay_method = str(raw_pm).strip() if raw_pm and str(raw_pm).strip() not in ["", "None", "null", "-"] else ("Cash" if is_received_req else "-")
            total_fee = convert_decimal(bill.get("total_fees") or bill.get("consulting_fee") or 0)

            final_uhid = resolved_uhid or (f"P-{bill.get('patient_id')}" if bill.get('patient_id') else "-")
            final_patient_name = resolved_patient_name or (f"Patient #{bill.get('patient_id')}" if bill.get('patient_id') else "-")

            final_data.append({
                "type": "Billing",
                "bill_type": bt_display_name,
                "bill_type_id": bill_type,
                "bill_type_name": bt_display_name,
                "bill_name": bt_display_name,
                "bill_no": bill.get("bill_number"),
                "uhid": final_uhid,
                "patient_name": final_patient_name,
                "amount": total_fee,
                "total": total_fee,
                "status": bill.get("payment_status"),
                "doctor": doc_display,
                "doctor_name": doc_display,
                "payment_method": pay_method,
                "date": (bill.get("paid_date") if is_received_req else None) or bill.get("billed_date") or bill.get("created_date"),
                "billed_date": bill.get("billed_date") or bill.get("created_date"),
                "paid_date": bill.get("paid_date"),
                "payment_details": serialize_mongo(bill.get("payment_details")),
                "payment_breakdown": serialize_mongo(bill.get("payment_details", {}).get("breakdown")) if isinstance(bill.get("payment_details"), dict) else None,
                "raw": serialize_mongo(bill)
            })

        # =========================================================
        # ✅ 2. INVESTIGATION BILLING (payment_method: 'Cash' alone)
        # =========================================================
        invest_query = build_module_query("paymentStatus", status_inv, "investBillDate")
        invest_docs = list(invest_col.find(invest_query).sort("investBillDate", -1).limit(200 if not date_query else 500))

        for inv in invest_docs:
            if not is_allowed_bill_doc(inv):
                continue
            bill_type = inv.get("bill_type")
            try:
                bt_num = int(bill_type)
            except (ValueError, TypeError):
                bt_num = bill_type

            # ✅ FILTER BASED ON CASHCOUNTER BILL TYPES
            if allowed_bill_type_ids and bill_type not in allowed_bill_type_ids and bt_num not in allowed_bill_type_ids:
                continue

            patient = get_patient_info(
                patient_col,
                uhid=inv.get("uhid"),
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            resolved_uhid = (patient.get("uhid") if patient else None) or inv.get("uhid")
            resolved_patient_name = format_patient_name(patient) or inv.get("patient_name") or inv.get("patient")
            bt_display_name = (
                bill_type_name_map.get(bill_type)
                or bill_type_name_map.get(bt_num)
                or inv.get("investigationName")
                or "INVESTIGATION"
            )

            doc_display = _get_doctor_display(inv.get("doctor") or inv.get("doctor_name") or inv.get("referedDoctor") or inv.get("prescribedBy"))
            raw_pm = inv.get("payment_method") or inv.get("paymentMethod") or (inv.get("payment_details", {}).get("method") if isinstance(inv.get("payment_details"), dict) else None)
            pay_method = str(raw_pm).strip() if raw_pm and str(raw_pm).strip() not in ["", "None", "null", "-"] else ("Cash" if is_received_req else "-")
            total_amt = convert_decimal(inv.get("finalPrice") or inv.get("totalAmount") or 0)

            final_uhid = resolved_uhid or (f"P-{inv.get('patient_id')}" if inv.get('patient_id') else "-")
            final_patient_name = resolved_patient_name or (f"Patient #{inv.get('patient_id')}" if inv.get('patient_id') else "-")

            final_data.append({
                "type": "Investigation",
                "bill_type": bt_display_name,
                "bill_type_id": bill_type,
                "bill_type_name": bt_display_name,
                "bill_name": bt_display_name,
                "bill_no": inv.get("investBillNo"),
                "uhid": final_uhid,
                "patient_name": final_patient_name,
                "amount": total_amt,
                "total": total_amt,
                "status": inv.get("paymentStatus"),
                "doctor": doc_display,
                "doctor_name": doc_display,
                "payment_method": pay_method,
                "date": (inv.get("paid_date") if is_received_req else None) or inv.get("investBillDate") or inv.get("created_date"),
                "billed_date": inv.get("investBillDate") or inv.get("created_date"),
                "paid_date": inv.get("paid_date"),
                "payment_details": serialize_mongo(inv.get("payment_details")),
                "payment_breakdown": serialize_mongo(inv.get("payment_details", {}).get("breakdown")) if isinstance(inv.get("payment_details"), dict) else None,
                "raw": serialize_mongo(inv)
            })

        # =========================================================
        # ✅ 3. DISCHARGE BILLING (payment_method: 'Cash' alone)
        # =========================================================
        discharge_allowed_types = {
            btd.get("bill_type")
            for btd in allowed_bill_type_details
            if isinstance(btd, dict) and "discharge" in str(btd.get("bill_name", "")).lower()
        }
        discharge_allowed_types.update({
            str(x) for x in discharge_allowed_types if x is not None
        })
        is_discharge_allowed = bool(discharge_allowed_types) or any(
            str(b).strip() == "2" for b in allowed_bill_type_ids
        )

        discharge_query = build_module_query("status", status_dis, "bill_date")
        discharge_docs = list(discharge_col.find(discharge_query).sort("bill_date", -1).limit(100 if not date_query else 500))

        for dis in discharge_docs:
            if not is_allowed_bill_doc(dis):
                continue
            if not is_discharge_allowed and allowed_bill_type_ids:
                continue

            items = dis.get("items", [])
            matched_items = []

            for item in items:
                ibt = item.get("bill_type")
                try:
                    ibt_num = int(ibt)
                except (ValueError, TypeError):
                    ibt_num = ibt

                if not allowed_bill_type_ids or ibt in allowed_bill_type_ids or ibt_num in allowed_bill_type_ids or ibt in discharge_allowed_types or str(ibt) in discharge_allowed_types:
                    matched_items.append(item)

            if not matched_items and (not allowed_bill_type_ids or is_discharge_allowed):
                matched_items = items

            if not matched_items:
                continue

            patient = get_patient_info(
                patient_col,
                uhid=dis.get("uhid"),
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            resolved_uhid = (patient.get("uhid") if patient else None) or dis.get("uhid")
            resolved_patient_name = format_patient_name(patient) or dis.get("patient_name") or dis.get("patient")
            bt_display_name = "DISCHARGE"

            doc_display = _get_doctor_display(dis.get("doctor_name") or dis.get("doctor") or dis.get("admittingDoctor") or dis.get("consultingDoctor"))
            raw_pm = dis.get("payment_method") or (dis.get("payment_details", {}).get("method") if isinstance(dis.get("payment_details"), dict) else None)
            pay_method = str(raw_pm).strip() if raw_pm and str(raw_pm).strip() not in ["", "None", "null", "-"] else ("Cash" if is_received_req else "-")
            total_amt = convert_decimal(dis.get("net_amount") or dis.get("total_amount") or 0)

            final_uhid = resolved_uhid or (f"P-{dis.get('patient_id')}" if dis.get("patient_id") else "-")
            final_patient_name = resolved_patient_name or (f"Patient #{dis.get('patient_id')}" if dis.get("patient_id") else "-")

            final_data.append({
                "type": "Discharge",
                "bill_type": bt_display_name,
                "bill_type_id": 2,
                "bill_type_name": bt_display_name,
                "bill_name": bt_display_name,
                "bill_no": dis.get("bill_no"),
                "uhid": final_uhid,
                "patient_name": final_patient_name,
                "amount": total_amt,
                "total": total_amt,
                "status": dis.get("status"),
                "doctor": doc_display,
                "doctor_name": doc_display,
                "payment_method": pay_method,
                "date": (dis.get("paid_date") if is_received_req else None) or dis.get("bill_date") or dis.get("created_date"),
                "billed_date": dis.get("bill_date") or dis.get("created_date"),
                "paid_date": dis.get("paid_date"),
                "payment_details": serialize_mongo(dis.get("payment_details")),
                "payment_breakdown": serialize_mongo(dis.get("payment_details", {}).get("breakdown")) if isinstance(dis.get("payment_details"), dict) else None,
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

        def _clean_str(val, fallback=""):
            if val is None:
                return fallback
            if isinstance(val, (list, tuple)):
                return str(val[0]).strip() if val else fallback
            s = str(val).strip()
            if s.startswith("[") and s.endswith("]"):
                import json
                try:
                    arr = json.loads(s)
                    if isinstance(arr, list) and arr:
                        return str(arr[0]).strip()
                except Exception:
                    pass
            return s or fallback

        hospital_code = _clean_str(data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE"), "SH001")
        branch_code   = _clean_str(data.get("auth-branch-code") or request.META.get("HTTP_AUTH_BRANCH_CODE") or request.headers.get("Branch-Code"), "SHB001")
        outlet_code   = _clean_str(data.get("auth-outlet-code") or request.META.get("HTTP_AUTH_OUTLET_CODE") or request.headers.get("Outlet-Code"), "")
        employee_id   = _clean_str(data.get("auth-user-id") or request.META.get("HTTP_AUTH_USER_ID") or extract_aud_employee_id(request), "")

        CashierID = employee_id or "admin"

        bill_no = data.get("bill_no")

        payment_details = data.get("payment_details")

        shiftno = (data.get("shiftno"))

        counter_id = data.get("counter_id")
        if not counter_id and employee_id:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            global_db = client["Global"]
            profile_col = global_db["backend_diagnostics_profile"]
            try:
                query_id = str(employee_id)
                search_query = {"employeeId": {"$in": [query_id, int(query_id) if query_id.isdigit() else query_id]}}
            except:
                search_query = {"employeeId": str(employee_id)}
            profile_data = profile_col.find_one(search_query)
            emp_cashcounter = profile_data.get("cashcounter") if profile_data else None
            if emp_cashcounter:
                counter_id = emp_cashcounter

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

        # Active shift validation
        is_valid, msg, active_shift = validate_active_shift(
            shiftno=shiftno,
            counter_id=counter_id,
            outlet_code=outlet_code,
            hospital_code=hospital_code,
            branch_code=branch_code
        )
        if not is_valid:
            return Response(
                {
                    "status": "error",
                    "message": msg
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

        if pending_amount > 0:
            return Response(
                {
                    "status": "error",
                    "message": "Low amount / partial payment is not allowed. Full net amount must be paid."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        target_category = str(data.get("type") or data.get("bill_category") or data.get("category") or "").strip().lower()

        def update_billing(billing_doc):
            new_status = "Paid" if pending_amount == 0 else "Partial"
            billing_col.update_one(
                {"_id": billing_doc["_id"]},
                {
                    "$set": {
                        "payment_status": new_status,
                        "payment_details": payment_details,
                        "payment_method": payment_details.get("method") or billing_doc.get("payment_method") or "Cash",
                        "shiftno": shiftno,
                        "paid_at": paid_at,
                        "paid_date": datetime.utcnow(),
                        "CashierID": CashierID,
                        "lastmodified_by": CashierID,
                        "lastmodified_date": datetime.utcnow(),
                        **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),
                    }
                }
            )
            raw_bt = billing_doc.get("bill_type", 1)
            try:
                bill_type = int(raw_bt) if raw_bt is not None else 1
            except (ValueError, TypeError):
                bill_type = 1

            final_outlet = _clean_str(outlet_code or billing_doc.get("outlet_code"), "OLET001")
            final_hosp = _clean_str(hospital_code or billing_doc.get("hospital_code"), "SH001")
            final_branch = _clean_str(branch_code or billing_doc.get("branch_code"), "SHB001")
            final_cashier = _clean_str(CashierID or billing_doc.get("CashierID") or billing_doc.get("created_by"), "admin")

            cash_counter_data = {
                "hospital_code": final_hosp,
                "branch_code": final_branch,
                "outlet_code": final_outlet,
                "created_by": final_cashier,
                "lastmodified_by": final_cashier,
                "bill_no": bill_no,
                "bill_number": bill_no,
                "bill_type": bill_type,
                "counter_code": _clean_str(counter_id, "CC0001"),
                "shift_no": _clean_str(shiftno, ""),
                "billing_category": "Billing",
                "transaction_type": "collected",
                "collected_amount": str(payment_details.get("Paid_amount", 0)),
                "Returned_amount": "0.00",
                "remarks": remarks,
            }
            cc_serializer = CashCounterCollectionSerializer(data=cash_counter_data)
            if cc_serializer.is_valid():
                cc_serializer.save()
            else:
                print(f"[CashCounterCollection] Warning for bill {bill_no}: {cc_serializer.errors}")
            recalculate_and_update_shift_details(shiftno)
            return Response({
                "status": "success",
                "type": "Billing",
                "bill_type": bill_type,
                "bill_no": bill_no,
                "new_payment_status": new_status
            }, status=status.HTTP_200_OK)

        def update_investigation(invest_doc):
            new_status = "Paid" if pending_amount == 0 else "Partial"
            invest_col.update_one(
                {"_id": invest_doc["_id"]},
                {
                    "$set": {
                        "paymentStatus": new_status,
                        "payment_details": payment_details,
                        "payment_method": payment_details.get("method") or invest_doc.get("payment_method") or "Cash",
                        "shiftno": shiftno,
                        "paid_at": paid_at,
                        "paid_date": datetime.utcnow(),
                        "CashierID": CashierID,
                        "lastmodified_by": CashierID,
                        "lastmodified_date": datetime.utcnow(),
                        **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),
                    }
                }
            )
            raw_bt = invest_doc.get("bill_type")
            try:
                bill_type = int(raw_bt) if raw_bt is not None else 6
            except (ValueError, TypeError):
                bill_type = 6

            final_outlet = _clean_str(outlet_code or invest_doc.get("outlet_code"), "OLET001")
            final_hosp = _clean_str(hospital_code or invest_doc.get("hospital_code"), "SH001")
            final_branch = _clean_str(branch_code or invest_doc.get("branch_code"), "SHB001")
            final_cashier = _clean_str(CashierID or invest_doc.get("CashierID") or invest_doc.get("created_by"), "admin")

            cash_counter_data = {
                "hospital_code": final_hosp,
                "branch_code": final_branch,
                "outlet_code": final_outlet,
                "created_by": final_cashier,
                "lastmodified_by": final_cashier,
                "bill_no": bill_no,
                "bill_number": bill_no,
                "bill_type": bill_type,
                "counter_code": _clean_str(counter_id, "CC0001"),
                "shift_no": _clean_str(shiftno, ""),
                "billing_category": "Investigation",
                "transaction_type": "collected",
                "collected_amount": str(payment_details.get("Paid_amount", 0)),
                "Returned_amount": "0.00",
                "remarks": remarks,
            }
            cc_serializer = CashCounterCollectionSerializer(data=cash_counter_data)
            if cc_serializer.is_valid():
                cc_serializer.save()
            else:
                print(f"[CashCounterCollection] Warning for invest {bill_no}: {cc_serializer.errors}")
            recalculate_and_update_shift_details(shiftno)
            return Response({
                "status": "success",
                "type": "Investigation",
                "bill_type": bill_type,
                "bill_no": bill_no,
                "new_payment_status": new_status
            }, status=status.HTTP_200_OK)

        def update_discharge(discharge_doc):
            new_status = "Paid" if pending_amount == 0 else "Partial"
            discharge_col.update_one(
                {"_id": discharge_doc["_id"]},
                {
                    "$set": {
                        "status": new_status,
                        "items.$[].payment_status": new_status,
                        "payment_details": payment_details,
                        "payment_method": payment_details.get("method") or discharge_doc.get("payment_method") or "Cash",
                        "shiftno": shiftno,
                        "paid_at": paid_at,
                        "paid_date": datetime.utcnow(),
                        "CashierID": CashierID,
                        "lastmodified_by": CashierID,
                        "lastmodified_date": datetime.utcnow(),
                        **({"pendingAmount": Decimal128(str(pending_amount))} if pending_amount > 0 else {}),
                    }
                }
            )
            bill_type = None
            items = discharge_doc.get("items", [])
            if items and isinstance(items, list):
                bill_type = items[0].get("bill_type")
            if not bill_type:
                bill_type = 2
            try:
                bill_type = int(bill_type)
            except (ValueError, TypeError):
                bill_type = 2

            final_outlet = _clean_str(outlet_code or discharge_doc.get("outlet_code"), "OLET001")
            final_hosp = _clean_str(hospital_code or discharge_doc.get("hospital_code"), "SH001")
            final_branch = _clean_str(branch_code or discharge_doc.get("branch_code"), "SHB001")
            final_cashier = _clean_str(CashierID or discharge_doc.get("CashierID") or discharge_doc.get("created_by"), "admin")

            cash_counter_data = {
                "hospital_code": final_hosp,
                "branch_code": final_branch,
                "outlet_code": final_outlet,
                "created_by": final_cashier,
                "lastmodified_by": final_cashier,
                "bill_no": bill_no,
                "bill_number": bill_no,
                "bill_type": bill_type,
                "counter_code": _clean_str(counter_id, "CC0001"),
                "shift_no": _clean_str(shiftno, ""),
                "billing_category": "Discharge",
                "transaction_type": "collected",
                "collected_amount": str(payment_details.get("Paid_amount", 0)),
                "Returned_amount": "0.00",
                "remarks": remarks,
            }
            cc_serializer = CashCounterCollectionSerializer(data=cash_counter_data)
            if cc_serializer.is_valid():
                cc_serializer.save()
            else:
                print(f"[CashCounterCollection] Warning for discharge {bill_no}: {cc_serializer.errors}")
            recalculate_and_update_shift_details(shiftno)
            return Response({
                "status": "success",
                "type": "Discharge",
                "bill_type": bill_type,
                "bill_no": bill_no,
                "new_payment_status": new_status
            }, status=status.HTTP_200_OK)

        # ── 0. Match by Direct Document ID (_id / bill_id) ────────────
        bill_doc_id = data.get("bill_id") or data.get("_id") or data.get("id")
        if bill_doc_id:
            from bson import ObjectId
            id_queries = []
            try:
                id_queries.append({"_id": ObjectId(str(bill_doc_id))})
            except Exception:
                pass
            id_queries.append({"_id": bill_doc_id})
            if str(bill_doc_id).isdigit():
                id_queries.append({"id": int(bill_doc_id)})
                id_queries.append({"_id": int(bill_doc_id)})

            for id_q in id_queries:
                if target_category in ["billing", "op"]:
                    doc = billing_col.find_one(id_q)
                    if doc:
                        return update_billing(doc)
                elif target_category == "investigation":
                    doc = invest_col.find_one(id_q)
                    if doc:
                        return update_investigation(doc)
                elif target_category == "discharge":
                    doc = discharge_col.find_one(id_q)
                    if doc:
                        return update_discharge(doc)
                else:
                    doc = billing_col.find_one(id_q)
                    if doc:
                        return update_billing(doc)
                    doc = invest_col.find_one(id_q)
                    if doc:
                        return update_investigation(doc)
                    doc = discharge_col.find_one(id_q)
                    if doc:
                        return update_discharge(doc)

        # ── 1. Match PENDING / UNPAID Bills Prioritized (Newest First) ───────────
        pending_statuses = ["Pending", "Unpaid", "pending", "unpaid"]

        req_bt = data.get("bill_type")
        bt_filters = []
        if req_bt is not None:
            try:
                bt_filters = [req_bt, int(req_bt), str(req_bt)]
            except (ValueError, TypeError):
                bt_filters = [req_bt, str(req_bt)]

        def _find_newest(collection, query):
            return collection.find_one(query, sort=[("_id", -1)])

        if target_category in ["billing", "op"]:
            b_q = {"bill_number": bill_no, "payment_status": {"$in": pending_statuses}}
            if hospital_code:
                b_q["hospital_code"] = hospital_code
            if branch_code:
                b_q["branch_code"] = branch_code
            if bt_filters:
                b_q["bill_type"] = {"$in": bt_filters}
            doc = _find_newest(billing_col, b_q)
            if not doc and bt_filters:
                del b_q["bill_type"]
                doc = _find_newest(billing_col, b_q)
            if not doc:
                doc = _find_newest(billing_col, {"bill_number": bill_no, "payment_status": {"$in": pending_statuses}})
            if doc:
                return update_billing(doc)

        elif target_category == "investigation":
            i_q = {"investBillNo": bill_no, "paymentStatus": {"$in": pending_statuses}}
            if hospital_code:
                i_q["hospital_code"] = hospital_code
            if branch_code:
                i_q["branch_code"] = branch_code
            doc = _find_newest(invest_col, i_q)
            if not doc:
                doc = _find_newest(invest_col, {"investBillNo": bill_no, "paymentStatus": {"$in": pending_statuses}})
            if doc:
                return update_investigation(doc)

        elif target_category == "discharge":
            d_q = {"bill_no": bill_no, "status": {"$in": ["Billed", "Pending", "Unpaid", "pending", "unpaid"]}}
            if hospital_code:
                d_q["hospital_code"] = hospital_code
            if branch_code:
                d_q["branch_code"] = branch_code
            doc = _find_newest(discharge_col, d_q)
            if not doc:
                doc = _find_newest(discharge_col, {"bill_no": bill_no, "status": {"$in": ["Billed", "Pending", "Unpaid", "pending", "unpaid"]}})
            if doc:
                return update_discharge(doc)

        # Match by specific payload status indicators
        if "status" in data and "payment_status" not in data and "paymentStatus" not in data:
            doc = _find_newest(discharge_col, {"bill_no": bill_no, "status": {"$in": ["Billed", "Pending", "Unpaid", "pending", "unpaid"]}})
            if doc:
                return update_discharge(doc)

        if "paymentStatus" in data and "payment_status" not in data and "status" not in data:
            doc = _find_newest(invest_col, {"investBillNo": bill_no, "paymentStatus": {"$in": pending_statuses}})
            if doc:
                return update_investigation(doc)

        # Check pending in billing, then invest, then discharge
        doc = _find_newest(billing_col, {"bill_number": bill_no, "payment_status": {"$in": pending_statuses}})
        if doc:
            return update_billing(doc)

        doc = _find_newest(invest_col, {"investBillNo": bill_no, "paymentStatus": {"$in": pending_statuses}})
        if doc:
            return update_investigation(doc)

        doc = _find_newest(discharge_col, {"bill_no": bill_no, "status": {"$in": ["Billed", "Pending", "Unpaid", "pending", "unpaid"]}})
        if doc:
            return update_discharge(doc)

        # ── 2. Fallback to Any Document Matching Bill Number (Newest First) ───
        if target_category in ["billing", "op"]:
            doc = _find_newest(billing_col, {"bill_number": bill_no})
            if doc:
                return update_billing(doc)
        elif target_category == "investigation":
            doc = _find_newest(invest_col, {"investBillNo": bill_no})
            if doc:
                return update_investigation(doc)
        elif target_category == "discharge":
            doc = _find_newest(discharge_col, {"bill_no": bill_no})
            if doc:
                return update_discharge(doc)

        doc = _find_newest(billing_col, {"bill_number": bill_no})
        if doc:
            return update_billing(doc)
        doc = _find_newest(invest_col, {"investBillNo": bill_no})
        if doc:
            return update_investigation(doc)
        doc = _find_newest(discharge_col, {"bill_no": bill_no})
        if doc:
            return update_discharge(doc)

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
    




@api_view(["POST", "GET"])
def get_shift_summary_report(request):
    """
    Ultra-fast shift summary report using direct PyMongo with field projection,
    pre-fetched cash counter mappings, bulk cashier profile names, and selective
    live collection aggregation for active shifts.
    """
    try:
        import datetime
        from pymongo import MongoClient

        data = request.data if request.method == "POST" else request.query_params
        if not data:
            data = {}

        hospital_code = (
            data.get("auth-hospital-code")
            or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
            or request.META.get("HTTP_HOSPITAL_CODE")
            or (request.headers.get("hospital-code") if hasattr(request, "headers") else None)
        )
        branch_code = (
            data.get("auth-branch-code")
            or request.META.get("HTTP_AUTH_BRANCH_CODE")
            or request.META.get("HTTP_BRANCH_CODE")
            or (request.headers.get("branch-code") if hasattr(request, "headers") else None)
        )
        status_filter = data.get("status") or data.get("shift_status")
        outlet_code_filter = data.get("outlet_code") or data.get("outlet")
        shiftno_filter = data.get("shiftno") or data.get("shift_no")
        cashier_filter = data.get("cashier_id") or data.get("CashierID")
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        user_limit = data.get("limit")

        # ── MongoDB Query Filter ──────────────────────────────────────
        query = {}
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if status_filter and str(status_filter).lower() != "all":
            s_low = str(status_filter).strip().lower()
            if s_low == "active":
                # Active shifts must have ShiftStatus active AND closingTime None AND is_active != False
                query["ShiftStatus"] = {"$regex": "^active$", "$options": "i"}
                query["closingTime"] = None
                query["is_active"] = {"$ne": False}
            elif s_low in ("inactive", "closed"):
                query["$or"] = [
                    {"ShiftStatus": {"$regex": "^inactive$", "$options": "i"}},
                    {"closingTime": {"$ne": None}},
                    {"is_active": False}
                ]
            else:
                query["ShiftStatus"] = {"$regex": f"^{s_low}$", "$options": "i"}
        if outlet_code_filter and str(outlet_code_filter).lower() != "all":
            query["$or"] = [{"outlet_code": str(outlet_code_filter)}, {"SelectedOutlet": str(outlet_code_filter)}]
        if shiftno_filter:
            query["shiftno"] = {"$regex": str(shiftno_filter).strip(), "$options": "i"}
        if cashier_filter and str(cashier_filter).lower() != "all":
            query["CashierID"] = str(cashier_filter)

        # Parse date bounds safely
        date_filter = {}
        if from_date:
            try:
                parts = [int(p) for p in str(from_date).split("T")[0].split("-")]
                date_filter["$gte"] = datetime.datetime(parts[0], parts[1], parts[2], 0, 0, 0)
            except Exception:
                pass
        if to_date:
            try:
                parts = [int(p) for p in str(to_date).split("T")[0].split("-")]
                date_filter["$lte"] = datetime.datetime(parts[0], parts[1], parts[2], 23, 59, 59, 999999)
            except Exception:
                pass
        if date_filter:
            query["date"] = date_filter

        # Dynamic limit to safeguard against unbound full-scan queries
        try:
            limit_val = int(user_limit) if user_limit else 0
        except Exception:
            limit_val = 0

        is_active_only = bool(status_filter and str(status_filter).lower() == "active")
        if limit_val <= 0 and not is_active_only and not shiftno_filter and not (from_date and to_date):
            limit_val = 500

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db = client["HMS"]
        col_shifts = hms_db["hospital_cashcountershiftdetails"]

        projection = {
            "shiftno": 1, "CashierID": 1, "CashCounter": 1,
            "OpeningBalance": 1, "ClosingBalance": 1, "collected_Amount": 1, "CreditAmount": 1,
            "PettyCashBalance": 1, "RemittedToBank": 1, "SubmittedToAccount": 1,
            "HandOverAmount": 1, "SalesReturnAmount": 1, "ShiftStatus": 1,
            "StartingTime": 1, "closingTime": 1, "date": 1,
            "outlet_code": 1, "SelectedOutlet": 1, "hospital_code": 1, "branch_code": 1
        }

        cursor = col_shifts.find(query, projection).sort([("date", -1), ("StartingTime", -1)])
        if limit_val > 0:
            cursor = cursor.limit(limit_val)
        shifts = list(cursor)

        # Bulk pre-fetch cash counters (only 10 rows in database)
        cc_map = {}
        try:
            cc_map = {c["counter_id"]: c.get("counter_name", c["counter_id"]) for c in hms_db["hospital_cashcounter"].find({}, {"counter_id": 1, "counter_name": 1})}
        except Exception:
            pass

        # Bulk fetch cashier profile employee names
        cashier_ids = list({s.get("CashierID") for s in shifts if s.get("CashierID")})
        cashier_name_map = {}
        if cashier_ids:
            try:
                prof_db = client["Global"]
                profiles = list(prof_db["backend_diagnostics_profile"].find(
                    {"employeeId": {"$in": cashier_ids}},
                    {"employeeId": 1, "employeeName": 1, "_id": 0}
                ))
                cashier_name_map = {p["employeeId"]: p.get("employeeName", p["employeeId"]) for p in profiles}
            except Exception:
                pass

        # Query live collections ONLY for active shifts in the batch
        active_nos = [s["shiftno"] for s in shifts if (s.get("ShiftStatus") or "").lower() == "active" and s.get("shiftno")]
        shift_totals = {}
        if active_nos:
            try:
                for s_no in active_nos:
                    calc = calculate_shift_collection(s_no)
                    shift_totals[s_no] = {
                        "collected": float(calc.get("total_collection") or 0.0),
                        "credit": float(calc.get("total_credit") or 0.0),
                        "returns": float(calc.get("sales_return") or 0.0),
                        "remitted": 0.0,
                        "submitted": 0.0,
                    }
                col_c = hms_db["hospital_cashcountercollection"]
                ccc_docs = list(col_c.find(
                    {"shift_no": {"$in": active_nos}, "billing_category": {"$in": ["remitted", "submit"]}},
                    {"shift_no": 1, "billing_category": 1, "transaction_type": 1, "collected_amount": 1, "RemittedToBank": 1}
                ))
                for doc in ccc_docs:
                    s_no = doc.get("shift_no")
                    if s_no in shift_totals:
                        cat = (doc.get("billing_category") or "").lower()
                        tx_type = (doc.get("transaction_type") or "").lower()
                        try:
                            amt = float(str(doc.get("collected_amount") or doc.get("RemittedToBank") or 0))
                        except Exception:
                            amt = 0.0
                        if cat == "remitted" or tx_type == "remitted":
                            shift_totals[s_no]["remitted"] += amt
                        elif cat == "submit" or tx_type == "submit":
                            shift_totals[s_no]["submitted"] += amt
            except Exception as e:
                print("Error aggregating active shift collections:", e)

        def _to_num(val):
            if val is None:
                return 0.0
            try:
                return float(str(val))
            except Exception:
                return 0.0

        report_data = []
        for s in shifts:
            sno = s.get("shiftno", "")
            cid = s.get("CashierID", "")
            cc_id = s.get("CashCounter", "")
            st = shift_totals.get(sno, {})

            col_amt = st.get("collected") if sno in shift_totals else _to_num(s.get("collected_Amount"))
            credit_amt = st.get("credit") if sno in shift_totals else _to_num(s.get("CreditAmount"))
            ret_amt = st.get("returns") if sno in shift_totals else _to_num(s.get("SalesReturnAmount"))
            rem_amt = st.get("remitted") if (sno in shift_totals and st.get("remitted", 0) > 0) else _to_num(s.get("RemittedToBank"))
            sub_amt = st.get("submitted") if (sno in shift_totals and st.get("submitted", 0) > 0) else _to_num(s.get("SubmittedToAccount"))

            # Standard Indian Time (IST = UTC+05:30)
            IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

            def _to_ist(val):
                if not val:
                    return None
                if isinstance(val, str):
                    try:
                        val = datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except Exception:
                        return None
                if isinstance(val, datetime.datetime):
                    if val.tzinfo is None:
                        val = val.replace(tzinfo=datetime.timezone.utc)
                    return val.astimezone(IST)
                return None

            st_time = s.get("StartingTime")
            cl_time = s.get("closingTime")
            st_ist = _to_ist(st_time)
            cl_ist = _to_ist(cl_time)

            st_iso = st_ist.isoformat() if st_ist else (str(st_time or ""))
            cl_iso = cl_ist.isoformat() if cl_ist else None

            # Standard Indian Time: 12-hour format with AM/PM (e.g. 08:39 PM)
            st_disp = st_ist.strftime("%I:%M %p") if st_ist else ""
            cl_disp = cl_ist.strftime("%I:%M %p") if cl_ist else ""

            # Standard Indian Date (DD/MM/YYYY) and raw sortable date (YYYY-MM-DD)
            dt = s.get("date")
            dt_str = ""
            raw_date_str = ""
            if dt:
                if isinstance(dt, datetime.datetime):
                    dt_ist = _to_ist(dt) or dt
                    dt_str = dt_ist.strftime("%d/%m/%Y")
                    raw_date_str = dt_ist.strftime("%Y-%m-%d")
                elif isinstance(dt, datetime.date):
                    dt_str = dt.strftime("%d/%m/%Y")
                    raw_date_str = dt.strftime("%Y-%m-%d")
                else:
                    dt_str = str(dt)
                    raw_date_str = str(dt)
            elif st_ist:
                dt_str = st_ist.strftime("%d/%m/%Y")
                raw_date_str = st_ist.strftime("%Y-%m-%d")

            report_data.append({
                "_id": str(s.get("_id", "")),
                "id": str(s.get("_id", "")),
                "shiftno": sno,
                "CashierID": cid,
                "User": cashier_name_map.get(cid, cid),
                "CashCounter": cc_id,
                "CashCounterName": cc_map.get(cc_id, cc_id),
                "OpeningBalance": _to_num(s.get("OpeningBalance")),
                "ClosingBalance": _to_num(s.get("ClosingBalance")),
                "collected_Amount": round(col_amt - ret_amt, 2),
                "CreditAmount": round(credit_amt, 2),
                "credit_amount": round(credit_amt, 2),
                "PettyCashBalance": _to_num(s.get("PettyCashBalance")),
                "RemittedToBank": 0.0,
                "SubmittedToAccount": 0.0,
                "HandOverAmount": 0.0,
                "SalesReturnAmount": round(ret_amt, 2),
                "ShiftStatus": s.get("ShiftStatus", ""),
                "StartingTime": st_iso,
                "StartTime": st_disp,
                "closingTime": cl_iso,
                "EndTime": cl_disp,
                "date": dt_str,
                "raw_date": raw_date_str,
                "hospital_code": s.get("hospital_code", ""),
                "branch_code": s.get("branch_code", ""),
                "outlet_code": s.get("outlet_code", ""),
                "SelectedOutlet": s.get("SelectedOutlet") or s.get("outlet_code", "")
            })

        return Response({
            "success": True,
            "data": report_data
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("❌ get_shift_summary_report ERROR:", error_details)
        return Response({"success": False, "message": str(e), "traceback": error_details}, status=500)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_registration_bills(request):
    try:
        # S &  AUTH DATA (Robust header check)
        hospital_code = request.data.get("auth-hospital-code") 
        branch_code = request.data.get("auth-branch-code") 
        # ================================
        # S &  FILTER BILLING DATA
        # ================================
        from ..models import Billing
        filter_query = {
            "payment_status": {"$in": ["Pending", "Cash Pending"]}
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
        "hospital_code":    str(hospital_code[0] if isinstance(hospital_code, (list, tuple)) else (hospital_code or "SH001")).strip(),
        "branch_code":      str(branch_code[0] if isinstance(branch_code, (list, tuple)) else (branch_code or "SHB001")).strip(),
        "outlet_code":      str(outlet_code[0] if isinstance(outlet_code, (list, tuple)) else (outlet_code or "OLET001")).strip(),
        "created_by":       str(cashier_id[0] if isinstance(cashier_id, (list, tuple)) else (cashier_id or "admin")).strip(),
        "lastmodified_by":  str(cashier_id[0] if isinstance(cashier_id, (list, tuple)) else (cashier_id or "admin")).strip(),
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
    now_dt = datetime.utcnow()
    return {
        "status":            "Paid",            # was "Pending" → always "Paid" after cashier processes
        "payment_status":    new_status,        # "Refund" or "Partial"
        "paymentStatus":     "Paid",            # for collections using camelCase (hospital_investrefund)
        "payment_details":   payment_details,
        "shiftno":           shiftno,
        "refund_datetime":   now_dt.isoformat(),
        "paid_at":           now_dt.isoformat(),
        "paid_date":         now_dt,
        "CashierID":         cashier_id,
        "lastmodified_by":   cashier_id,
        "lastmodified_date": now_dt,
        "pendingAmount":     Decimal128(str(pending_amount)),
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
       hospital_salesreturn      → field: return_bill_no / refund_bill_no / refundBillNo
       hospital_refund           → field: refund_bill_no / refundBillNo / return_bill_no
       hospital_investrefund     → field: refundBillNo / refund_bill_no / return_bill_no
       hospital_ipadvance_refund → field: refund_bill_no / refundBillNo / return_bill_no

    2. When matched:
       • Update document: status / paymentStatus → "Paid", payment_status → "Refund"
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

        data = request.data if isinstance(request.data, dict) else {}

        # ── Auth context ────────────────────────────────────────────────────
        hospital_code = (
            data.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or
            request.headers.get("Hospital-Code") or
            request.GET.get("auth-hospital-code")
        )
        branch_code = (
            data.get("auth-branch-code") or
            request.headers.get("auth-branch-code") or
            request.headers.get("Branch-Code") or
            request.GET.get("auth-branch-code")
        )
        outlet_code = (
            data.get("auth-outlet-code") or
            request.headers.get("auth-outlet-code") or
            request.headers.get("Outlet-Code") or
            request.GET.get("auth-outlet-code")
        )
        cashier_id = (
            data.get("auth-user-id") or
            request.headers.get("auth-user-id") or
            request.headers.get("User-Id") or
            request.GET.get("auth-user-id")
        )

        def _clean_str(val):
            if isinstance(val, (list, tuple)):
                val = val[0] if val else None
            return str(val).strip() if val is not None else None

        clean_hospital = _clean_str(hospital_code) or "SH001"
        clean_branch   = _clean_str(branch_code) or "SHB001"
        clean_outlet   = _clean_str(outlet_code)
        clean_cashier  = _clean_str(cashier_id) or "admin"

        # ── Request payload ─────────────────────────────────────────────────
        uhid            = data.get("uhid")
        bill_no         = data.get("bill_no")            # original bill (e.g. "2627/000001")
        return_bill_no  = data.get("return_bill_no")     # return/refund bill (e.g. "2627/000003")
        bill_type       = data.get("bill_type")          # int, from the bill row
        counter_id      = data.get("counter_id")
        if not counter_id and clean_cashier:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            global_db = client["Global"]
            profile_col = global_db["backend_diagnostics_profile"]
            try:
                query_id = str(clean_cashier)
                search_query = {"employeeId": {"$in": [query_id, int(query_id) if query_id.isdigit() else query_id]}}
            except:
                search_query = {"employeeId": str(clean_cashier)}
            profile_data = profile_col.find_one(search_query)
            emp_cashcounter = profile_data.get("cashcounter") if profile_data else None
            if emp_cashcounter:
                counter_id = emp_cashcounter

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

        # Active shift validation
        is_valid, msg, active_shift = validate_active_shift(
            shiftno=shiftno,
            counter_id=counter_id,
            outlet_code=clean_outlet,
            hospital_code=clean_hospital,
            branch_code=clean_branch
        )
        if not is_valid:
            return Response(
                {"status": "error", "message": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Determine new status ─────────────────────────────────────────────
        # We compare paid_amount against the document's return_amount later;
        # for now derive pending from what the frontend sends (if any).
        # The frontend should send pendingAmount = return_amount - paid_amount.
        pending_amount = float(data.get("pendingAmount", 0))

        new_status = "Partial" if pending_amount > 0 else "Refund"

        base_filter = {}
        if clean_hospital:
            base_filter["hospital_code"] = clean_hospital
        if clean_branch:
            base_filter["branch_code"] = clean_branch
        if clean_outlet:
            base_filter["outlet_code"] = clean_outlet

        return_query = {
            "$or": [
                {"refundBillNo": return_bill_no},
                {"refund_bill_no": return_bill_no},
                {"return_bill_no": return_bill_no},
            ]
        }

        # ═══════════════════════════════════════════════════════════════
        # 1. hospital_salesreturn  — keyed on return_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = sales_return_col.find_one({**base_filter, **return_query})
        if not doc and "outlet_code" in base_filter:
            doc = sales_return_col.find_one({
                "hospital_code": base_filter.get("hospital_code"),
                "branch_code": base_filter.get("branch_code"),
                **return_query
            })

        if doc:
            sales_return_col.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(clean_cashier, payment_details, shiftno, pending_amount, new_status)},
            )

            # Resolve the original bill_no from the matched document (most reliable source)
            original_bill_no = (
                doc.get("bill_no")
                or doc.get("investBillNo")
                or doc.get("original_bill_no")
                or bill_no
                or ""
            )

            ok, errors = _save_cash_counter(
                clean_hospital,
                clean_branch,
                clean_outlet or doc.get("outlet_code"),
                clean_cashier,
                original_bill_no,   # original bill_no  → bill_no + bill_number
                return_bill_no,     # return bill_no    → return_bill_no
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

            recalculate_and_update_shift_details(shiftno)

            return Response(
                {
                    "status":              "success",
                    "type":                "Sales Return",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid or doc.get("uhid"),
                    "new_document_status": new_status,
                },
                status=status.HTTP_200_OK,
            )

        # ═══════════════════════════════════════════════════════════════
        # 2. hospital_refund  — keyed on refund_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = refund_collection.find_one({**base_filter, **return_query})
        if not doc and "outlet_code" in base_filter:
            doc = refund_collection.find_one({
                "hospital_code": base_filter.get("hospital_code"),
                "branch_code": base_filter.get("branch_code"),
                **return_query
            })

        if doc:
            refund_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(clean_cashier, payment_details, shiftno, pending_amount, new_status)},
            )

            original_bill_no = (
                doc.get("bill_no")
                or doc.get("investBillNo")
                or doc.get("original_bill_no")
                or bill_no
                or ""
            )

            ok, errors = _save_cash_counter(
                clean_hospital,
                clean_branch,
                clean_outlet or doc.get("outlet_code"),
                clean_cashier,
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

            recalculate_and_update_shift_details(shiftno)

            return Response(
                {
                    "status":              "success",
                    "type":                "Refund",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid or doc.get("uhid"),
                    "new_document_status": new_status,
                },
                status=status.HTTP_200_OK,
            )

        # ═══════════════════════════════════════════════════════════════
        # 3. hospital_investrefund  — keyed on refundBillNo / refund_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = investrefund_collection.find_one({**base_filter, **return_query})
        if not doc and "outlet_code" in base_filter:
            doc = investrefund_collection.find_one({
                "hospital_code": base_filter.get("hospital_code"),
                "branch_code": base_filter.get("branch_code"),
                **return_query
            })

        if doc:
            investrefund_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(clean_cashier, payment_details, shiftno, pending_amount, new_status)},
            )

            original_bill_no = (
                doc.get("bill_no")
                or doc.get("investBillNo")
                or doc.get("original_bill_no")
                or bill_no
                or ""
            )

            ok, errors = _save_cash_counter(
                clean_hospital,
                clean_branch,
                clean_outlet or doc.get("outlet_code"),
                clean_cashier,
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

            recalculate_and_update_shift_details(shiftno)

            return Response(
                {
                    "status":              "success",
                    "type":                "Investigation Refund",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid or doc.get("uhid"),
                    "new_document_status": new_status,
                },
                status=status.HTTP_200_OK,
            )

        # ═══════════════════════════════════════════════════════════════
        # 4. hospital_ipadvance_refund  — keyed on refund_bill_no
        # ═══════════════════════════════════════════════════════════════
        doc = ipadvance_refund_collection.find_one({**base_filter, **return_query})
        if not doc and "outlet_code" in base_filter:
            doc = ipadvance_refund_collection.find_one({
                "hospital_code": base_filter.get("hospital_code"),
                "branch_code": base_filter.get("branch_code"),
                **return_query
            })

        if doc:
            ipadvance_refund_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": _payment_set(clean_cashier, payment_details, shiftno, pending_amount, new_status)},
            )

            original_bill_no = (
                doc.get("bill_no")
                or doc.get("investBillNo")
                or doc.get("original_bill_no")
                or bill_no
                or ""
            )

            ok, errors = _save_cash_counter(
                clean_hospital,
                clean_branch,
                clean_outlet or doc.get("outlet_code"),
                clean_cashier,
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

            recalculate_and_update_shift_details(shiftno)

            return Response(
                {
                    "status":              "success",
                    "type":                "IP Advance Refund",
                    "bill_no":             original_bill_no,
                    "return_bill_no":      return_bill_no,
                    "bill_type":           bill_type,
                    "uhid":                uhid or doc.get("uhid"),
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
    




from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from ..models import Admission, CashCounterCollection
from ..serializers import CashCounterCollectionSerializer
from pymongo import MongoClient
import os
import traceback

# ✅ Mongo connection
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(MONGO_URI)

# ✅ DATABASES
mongo_db = client["HMS"]
global_db = client["Global"]

# ✅ COLLECTIONS
patient_collection = mongo_db["hospital_patient"]
cashcounter_collection = mongo_db["hospital_cashcounter"]
profile_collection = global_db["backend_diagnostics_profile"]


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def ipadvance_bills(request):
    try:

        # =========================================
        # ✅ EXTRACT AUTH DYNAMICALLY (NO HARDCODE)
        # =========================================
        data = request.data if isinstance(request.data, dict) else {}
        employee_id = (
            data.get("auth-user-id") or
            request.headers.get("auth-user-id") or
            request.headers.get("User-Id") or
            request.GET.get("auth-user-id")
        )
        hospital_code = (
            data.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or
            request.headers.get("Hospital-Code") or
            request.GET.get("auth-hospital-code")
        )
        branch_code = (
            data.get("auth-branch-code") or
            request.headers.get("auth-branch-code") or
            request.headers.get("Branch-Code") or
            request.GET.get("auth-branch-code")
        )
        outlet_code = (
            data.get("auth-outlet-code") or
            request.headers.get("auth-outlet-code") or
            request.headers.get("Outlet-Code") or
            request.GET.get("auth-outlet-code")
        )
        cashier_id = employee_id

        # =========================================
        # ✅ DYNAMIC CASHCOUNTER & BILL TYPE PERMISSIONS (aud -> profile -> cashcounter)
        # =========================================
        emp_perms = get_employee_cashcounter_permissions(
            employee_id or request,
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code
        )
        if not emp_perms.get("success"):
            return Response(
                {"error": emp_perms.get("message", "No active cash counter or bill types configured for this user")},
                status=status.HTTP_403_FORBIDDEN
            )

        cashcounter_data = emp_perms["cashcounter_details"]
        allowed_bill_type_details = emp_perms["bill_type_details"]
        target_outlet = emp_perms["outlet"] or outlet_code
        cashcounter_id = emp_perms["counter_id"]

        # Allowed bill types strictly as configured in hospital_cashcounter
        allowed_bill_types = {
            str(bt).strip()
            for bt in emp_perms["allowed_bill_types"]
            if bt is not None
        }

        # Strict check: zero hardcoding of bill types, zero hardcoded fallback counter
        if not cashcounter_data or not allowed_bill_types:
            return Response(
                {"error": "No active cash counter or bill types configured for this user"},
                status=status.HTTP_403_FORBIDDEN
            )

        def _payment_bill_type(p):
            bt = p.get("bill_type") if p.get("bill_type") is not None else p.get(" bill_type")
            return str(bt).strip() if bt is not None else None

        # =========================================
        # ✅ VERIFY ACTIVE SHIFT (DO NOT DISPLAY IF NOT STARTED)
        # =========================================
        shift_col = hms_db["hospital_cashcountershiftdetails"]
        active_shift = shift_col.find_one({
            "CashCounter": cashcounter_id,
            "ShiftStatus": "active"
        })
        if not active_shift and cashier_id:
            active_shift = shift_col.find_one({
                "CashierID": str(cashier_id),
                "ShiftStatus": "active"
            })
        if not active_shift:
            active_shift = shift_col.find_one({
                "ShiftStatus": "active"
            })

        if not active_shift:
            return Response({
                "cashcounter": cashcounter_data,
                "allowed_bill_type_details": allowed_bill_type_details,
                "status": "success",
                "shift_active": False,
                "message": "Shift not started. Please start a shift to view bills.",
                "count": 0,
                "data": []
            }, status=status.HTTP_200_OK)

        # =========================================
        # ✅ GET METHOD (Ultra-fast PyMongo + Bulk Prefetch)
        # =========================================
        if request.method == "GET":

            req_status = request.GET.get("status") or (data.get("status") if data else None) or "pending"
            req_status_str = str(req_status).strip().lower()
            is_received_req = req_status_str in ["paid", "received"]
            is_unpaid_req = req_status_str in ["unpaid", "unpaid_bills"]

            from datetime import date, timedelta
            today = timezone.localdate() if hasattr(timezone, "localdate") else timezone.now().date()
            d_start = datetime.combine(today, datetime.min.time())
            d_end = d_start + timedelta(days=1)

            def _parse_bill_dt(payment):
                bd = payment.get("bill_date") or payment.get("date") or payment.get("created_date")
                if not bd:
                    return None
                if isinstance(bd, datetime):
                    return bd.replace(tzinfo=None) if bd.tzinfo else bd
                if isinstance(bd, date):
                    return datetime.combine(bd, datetime.min.time())
                if isinstance(bd, str):
                    s = bd.strip().replace("Z", "+00:00")
                    try:
                        dt = datetime.fromisoformat(s)
                        return dt.replace(tzinfo=None) if dt.tzinfo else dt
                    except Exception:
                        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                            try:
                                return datetime.strptime(s.split(" ")[0].split("T")[0], fmt)
                            except Exception:
                                continue
                return None

            adm_filter = {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "is_admitted": True,
                "is_discharged": False
            }
            if target_outlet:
                adm_filter["outlet_code"] = target_outlet

            raw_admissions = list(
                admission_collection.find(
                    adm_filter,
                    {
                        "ipNumber": 1,
                        "ipserial_number": 1,
                        "uhid": 1,
                        "hospital_code": 1,
                        "branch_code": 1,
                        "outlet_code": 1,
                        "admissionDateTime": 1,
                        "admittingDoctor": 1,
                        "consultingDoctor": 1,
                        "packageName": 1,
                        "room_details": 1,
                        "roomShitingDetails": 1,
                        "reasonForAdmission": 1,
                        "mlc_type": 1,
                        "mlc_doc": 1,
                        "mlc_remarks": 1,
                        "is_discharged": 1,
                        "is_admitted": 1,
                        "created_by": 1,
                        "created_date": 1,
                        "lastmodified_by": 1,
                        "lastmodified_date": 1,
                        "advance_payments": 1,
                        "patient_details": 1
                    }
                ).sort("admissionDateTime", -1)
            )

            # Bulk fetch patient details in 1 single query (eliminates N+1 loop queries)
            all_uhids = list({str(a.get("uhid")).strip() for a in raw_admissions if a.get("uhid")})
            patient_map = {}
            if all_uhids:
                try:
                    for p in patient_collection.find(
                        {"uhid": {"$in": all_uhids}},
                        {"uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1, "patient_name": 1, "_id": 0}
                    ):
                        u = str(p.get("uhid")).strip()
                        p_name = p.get("patient_name")
                        if not p_name:
                            sal = (p.get("salutation") or "").strip()
                            fn = (p.get("firstName") or "").strip()
                            ln = (p.get("lastName") or "").strip()
                            p_name = f"{sal} {fn} {ln}".strip()
                        patient_map[u] = p_name
                except Exception as e:
                    print("ipadvance_bills bulk patient error:", e)

            result = []

            for admission in raw_admissions:
                u_str = str(admission.get("uhid") or "").strip()
                p_det = admission.get("patient_details") or {}
                embedded_name = ""
                if isinstance(p_det, dict):
                    embedded_name = p_det.get("patient_name") or f"{p_det.get('firstName', '')} {p_det.get('lastName', '')}".strip()

                patient_name = embedded_name or patient_map.get(u_str) or None

                raw_ap = admission.get("advance_payments") or []
                if isinstance(raw_ap, str):
                    import json
                    import ast
                    try:
                        raw_ap = json.loads(raw_ap)
                    except:
                        try:
                            raw_ap = ast.literal_eval(raw_ap)
                        except:
                            raw_ap = []
                if not isinstance(raw_ap, list):
                    raw_ap = []

                clean_payments = []
                for payment in raw_ap:
                    if isinstance(payment, dict):
                        p_copy = dict(payment)
                        bt = p_copy.get("bill_type") if p_copy.get("bill_type") is not None else p_copy.get(" bill_type")
                        p_copy["bill_type"] = bt
                        # ✅ Only bills whose bill_type is allowed for this cash counter
                        if _payment_bill_type(p_copy) not in allowed_bill_types:
                            continue

                        # Check is_advanceActive
                        if not p_copy.get("is_advanceActive", True):
                            continue

                        # Payment method check: Cash only
                        pm = ""
                        p_det = p_copy.get("payment_details")
                        if isinstance(p_det, dict):
                            pm = str(p_det.get("method") or p_det.get("payment_mode") or "").strip().lower()
                        if not pm:
                            pm = str(p_copy.get("payment_method") or p_copy.get("paymentMethod") or "cash").strip().lower()

                        if is_received_req and pm not in ["cash"]:
                            continue
                        elif not is_received_req and pm not in ["cash", ""]:
                            continue

                        p_status = str(p_copy.get("status") or "").strip().lower()
                        p_dt = _parse_bill_dt(p_copy)
                        p_paid_dt = _parse_bill_dt({
                            "bill_date": p_copy.get("paid_datetime") or p_copy.get("paid_date") or p_copy.get("bill_date") or p_copy.get("date")
                        }) or p_dt

                        if is_received_req:
                            if p_status not in ["paid", "received"]:
                                continue
                            # ✅ Received bills also display current date paid bills
                            if p_paid_dt and not (d_start <= p_paid_dt < d_end):
                                continue
                            p_copy["_dt"] = p_paid_dt
                        elif is_unpaid_req:
                            # Prior date / other date unpaid bills
                            if p_status != "pending":
                                continue
                            if p_dt and (d_start <= p_dt < d_end):
                                # Skip today's bills in unpaid tab
                                continue
                            p_copy["_dt"] = p_dt
                        else:
                            # Current date pending bills
                            if p_status != "pending":
                                continue
                            if p_dt and not (d_start <= p_dt < d_end):
                                # Skip older bills in pending tab
                                continue
                            p_copy["_dt"] = p_dt

                        clean_payments.append(p_copy)

                if not clean_payments:
                    continue   # admission has no bills for this counter/status

                # Sort payments newest first
                clean_payments.sort(key=lambda x: x.get("_dt") or datetime.min, reverse=True)
                for cp in clean_payments:
                    cp.pop("_dt", None)

                adm_dt = admission.get("admissionDateTime")
                if adm_dt and hasattr(adm_dt, "isoformat"):
                    adm_dt = adm_dt.isoformat()

                admission_data = {
                    "ipNumber": admission.get("ipNumber"),
                    "ipserial_number": admission.get("ipserial_number"),
                    "uhid": admission.get("uhid"),
                    "patient_name": patient_name,
                    "hospital_code": admission.get("hospital_code"),
                    "branch_code": admission.get("branch_code"),
                    "outlet_code": admission.get("outlet_code"),
                    "admissionDateTime": adm_dt,
                    "admittingDoctor": admission.get("admittingDoctor"),
                    "consultingDoctor": admission.get("consultingDoctor"),
                    "packageName": admission.get("packageName"),
                    "room_details": admission.get("room_details"),
                    "roomShitingDetails": admission.get("roomShitingDetails"),
                    "reasonForAdmission": admission.get("reasonForAdmission"),
                    "mlc_type": admission.get("mlc_type"),
                    "mlc_doc": admission.get("mlc_doc"),
                    "mlc_remarks": admission.get("mlc_remarks"),
                    "is_discharged": admission.get("is_discharged"),
                    "is_admitted": admission.get("is_admitted"),
                    "created_by": admission.get("created_by"),
                    "created_date": admission.get("created_date"),
                    "lastmodified_by": admission.get("lastmodified_by"),
                    "lastmodified_date": admission.get("lastmodified_date"),
                    "advance_payments": clean_payments
                }

                result.append(admission_data)

            # Sort admissions by newest payment date
            result.sort(
                key=lambda a: max(
                    (_parse_bill_dt(p) or datetime.min for p in a.get("advance_payments", [])),
                    default=datetime.min
                ),
                reverse=True
            )

            return Response({
                "cashcounter": cashcounter_data,
                "allowed_bill_type_details": allowed_bill_type_details,
                "status": "success",
                "count": len(result),
                "data": result
            }, status=status.HTTP_200_OK)

        # =========================================
        # ✅ POST METHOD (UPDATE PAYMENT)
        # =========================================
        if request.method == "POST":

            if not cashier_id:
                return Response(
                    {"error": "auth-user-id (cashier_id) required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            ipNumber = data.get("ipNumber")
            advance_id = data.get("advance_id")
            payment_details = data.get("payment_details", {})
            shiftno = data.get("shiftno")

            # ✅ NEW — bill_type sent from frontend for CashCounterCollection
            bill_type_from_request = data.get("bill_type")

            # ✅ Reject bill types not allowed for this cash counter
            if bill_type_from_request is not None and str(bill_type_from_request).strip() not in allowed_bill_types:
                return Response(
                    {"error": "Bill type not allowed for this cash counter"},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not ipNumber:
                return Response(
                    {"error": "ipNumber required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Active shift validation
            is_valid, msg, active_shift = validate_active_shift(
                shiftno=shiftno,
                counter_id=cashcounter_id,
                outlet_code=target_outlet or outlet_code,
                hospital_code=hospital_code,
                branch_code=branch_code
            )
            if not is_valid:
                return Response(
                    {"error": msg},
                    status=status.HTTP_400_BAD_REQUEST
                )

            admission = Admission.objects.filter(
                ipNumber=ipNumber,
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=target_outlet or outlet_code
            ).first()

            if not admission:
                admission = Admission.objects.filter(
                    ipNumber=ipNumber,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                ).first()

            if not admission:
                return Response(
                    {"error": "Admission not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            payments = admission.advance_payments or []
            if isinstance(payments, str):
                import json
                import ast
                try:
                    payments = json.loads(payments)
                except:
                    try:
                        payments = ast.literal_eval(payments)
                    except:
                        payments = []
            if not isinstance(payments, list):
                payments = []

            updated = False
            paid_datetime = timezone.now()

            # ✅ Track which payments were just updated (for CashCounterCollection)
            just_paid_payments = []

            for p in payments:

                if not isinstance(p, dict):
                    continue

                # ✅ Skip payments whose bill_type this counter is not allowed to collect
                if _payment_bill_type(p) not in allowed_bill_types:
                    continue

                # ✅ CASE 1: Specific advance_id
                if advance_id:

                    if p.get("advance_id") == advance_id:

                        if str(p.get("status", "")).lower() == "pending":

                            p["status"] = "Paid"
                            p["payment_details"] = payment_details
                            p["cashier_id"] = cashier_id
                            p["paid_datetime"] = paid_datetime.isoformat()
                            p["shiftno"] = shiftno

                            just_paid_payments.append(p)
                            updated = True

                # ✅ CASE 2: Update ALL pending
                else:

                    if str(p.get("status", "")).lower() == "pending":

                        p["status"] = "Paid"
                        p["payment_details"] = payment_details
                        p["cashier_id"] = cashier_id
                        p["paid_datetime"] = paid_datetime.isoformat()
                        p["shiftno"] = shiftno

                        just_paid_payments.append(p)
                        updated = True

            if not updated:
                return Response(
                    {"message": "No pending payments found"},
                    status=status.HTTP_200_OK
                )

            # ✅ SAVE ADMISSION using PyMongo directly to bypass Djongo JSONField string serialization
            # Safe parse room_details and roomShitingDetails if they are strings to ensure they are stored as native object arrays
            room_details = admission.room_details or []
            if isinstance(room_details, str):
                import json
                import ast
                try:
                    room_details = json.loads(room_details)
                except:
                    try:
                        room_details = ast.literal_eval(room_details)
                    except:
                        room_details = []

            roomShitingDetails = admission.roomShitingDetails or []
            if isinstance(roomShitingDetails, str):
                import json
                import ast
                try:
                    roomShitingDetails = json.loads(roomShitingDetails)
                except:
                    try:
                        roomShitingDetails = ast.literal_eval(roomShitingDetails)
                    except:
                        roomShitingDetails = []

            from pymongo import MongoClient
            import os
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client["HMS"]
            admission_col = db["hospital_admission"]

            # Save via Django for model lifecycle, signals, and validation
            admission.room_details = room_details
            admission.roomShitingDetails = roomShitingDetails
            admission.advance_payments = payments
            admission.lastmodified_by = cashier_id
            admission.lastmodified_date = paid_datetime
            admission.save()

            # Force writing the native object arrays to Mongo via PyMongo to prevent Djongo stringification
            admission_col.update_one(
                {"ipNumber": ipNumber, "hospital_code": hospital_code, "branch_code": branch_code},
                {"$set": {
                    "room_details": room_details,
                    "roomShitingDetails": roomShitingDetails,
                    "advance_payments": payments,
                    "lastmodified_by": cashier_id,
                    "lastmodified_date": paid_datetime
                }}
            )

            # =========================================
            # ✅ SAVE CashCounterCollection RECORDS
            # =========================================
            for paid_payment in just_paid_payments:

                # ✅ Resolve bill_type:
                #    Priority: frontend-sent bill_type → payment's own bill_type → space-keyed fallback
                resolved_bill_type = (
                    bill_type_from_request
                    or paid_payment.get("bill_type")
                    or paid_payment.get(" bill_type")   # space-prefixed key fix
                )

                # ✅ Resolve collected_amount
                collected_amount = float(paid_payment.get("advance_amount") or 0)

                # ✅ Resolve bill_no
                bill_no_value = paid_payment.get("bill_no") or None

                cashcounter_collection_payload = {
                    "bill_no":           bill_no_value,
                    "bill_type":         resolved_bill_type,
                    "counter_code":      cashcounter_data.get("counter_id"),
                    "shift_no":          str(shiftno) if shiftno else None,
                    "billing_category":  "IPAdvance Payment",
                    "bill_number":       str(admission.ipserial_number or admission.ipNumber),
                    "transaction_type":  "Advance Amount collected",
                    "collected_amount":  collected_amount,
                    "Returned_amount":   0.00,
                    "RemittedToBank":    0.00,
                    "HandOverAmount":    0.00,
                    "remarks":           "",
                    # ✅ AuditModel fields
                    "hospital_code":     str(hospital_code[0] if isinstance(hospital_code, (list, tuple)) else (hospital_code or "SH001")).strip(),
                    "branch_code":       str(branch_code[0] if isinstance(branch_code, (list, tuple)) else (branch_code or "SHB001")).strip(),
                    "outlet_code":       str(outlet_code[0] if isinstance(outlet_code, (list, tuple)) else (outlet_code or "OLET001")).strip(),
                    "created_by":        str(cashier_id[0] if isinstance(cashier_id, (list, tuple)) else (cashier_id or "admin")).strip(),
                    "lastmodified_by":   str(cashier_id[0] if isinstance(cashier_id, (list, tuple)) else (cashier_id or "admin")).strip(),
                }

                cc_serializer = CashCounterCollectionSerializer(
                    data=cashcounter_collection_payload
                )

                if cc_serializer.is_valid():
                    cc_serializer.save()
                else:
                    # ✅ Log but do NOT fail the main payment — just warn
                    print(
                        f"[CashCounterCollection] Save error for advance_id="
                        f"{paid_payment.get('advance_id')}: {cc_serializer.errors}"
                    )

            # =========================================
            # ✅ FETCH PATIENT NAME FOR RESPONSE
            # =========================================
            patient = patient_collection.find_one({
                "uhid": admission.uhid,
                "hospital_code": hospital_code,
                "branch_code": branch_code
            })

            if patient:
                salutation = patient.get("salutation", "")
                firstName = patient.get("firstName", "")
                lastName = patient.get("lastName", "")
                patient_name = f"{salutation} {firstName} {lastName}".strip()
            else:
                patient_name = None

            recalculate_and_update_shift_details(shiftno)

            return Response({
                "cashcounter": cashcounter_data,
                "allowed_bill_type_details": allowed_bill_type_details,
                "status": "success",
                "message": "Payment updated successfully",
                "data": {
                    "ipNumber": admission.ipNumber,
                    "uhid": admission.uhid,
                    "patient_name": patient_name,
                    "hospital_code": admission.hospital_code,
                    "branch_code": admission.branch_code,
                    "outlet_code": admission.outlet_code,

                    # ✅ FULL UPDATED ARRAY
                    "advance_payments": payments
                }
            }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "error": str(e),
            "type": type(e).__name__,
            "trace": traceback.format_exc()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from datetime import datetime, date, timedelta
from rest_framework import status
from pymongo import MongoClient
import os

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def OPPharmacy_pending_bills(request):
    try:
        data = request.data
        employee_id = data.get("auth-user-id")

        # ✅ AUTH CODES
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        # =========================================================
        # ✅ MongoDB Collections
        # =========================================================
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        global_db = client["Global"]
        profile_collection = global_db["backend_diagnostics_profile"]

        hms_db = client["HMS"]
        billtype_collection       = hms_db["hospital_billtype"]
        pharmacy_item_collection  = hms_db["hospital_pharmacyitem"]
        pharmacy_stock_collection = hms_db["hospital_pharmacystock"]
        oppharmacy_collection     = hms_db["hospital_pharmacybilling"]
        cashcounter_collection    = hms_db["hospital_cashcounter"]

        # =========================================================
        # ✅ Employee Cashcounter & Bill Type Permission Check
        # =========================================================
        emp_perms = get_employee_cashcounter_permissions(
            employee_id or request,
            hospital_code=hospital_code,
            branch_code=branch_code
        )

        requested_counter = data.get("CashCounter") or request.GET.get("CashCounter")
        if requested_counter and emp_perms.get("success") and emp_perms.get("counter_id"):
            if str(requested_counter).strip().upper() != str(emp_perms["counter_id"]).strip().upper():
                return Response({
                    "status": "error",
                    "code": "COUNTER_ACCESS_DENIED",
                    "message": f"Access blocked: Cashier {emp_perms['employee_id']} is assigned to counter '{emp_perms['counter_id']}' ({emp_perms['counter_name']}) and cannot access counter '{requested_counter}'.",
                    "cashcounter": emp_perms.get("cashcounter_details"),
                    "allowed_bill_type_details": emp_perms.get("bill_type_details", []),
                    "data": []
                }, status=status.HTTP_403_FORBIDDEN)

        if emp_perms.get("success"):
            cashcounter_details       = emp_perms["cashcounter_details"]
            allowed_bill_type_details = emp_perms["bill_type_details"]
            allowed_bill_types        = emp_perms["allowed_bill_types"]
            emp_cashcounter           = emp_perms["counter_id"]
            matched_outlet            = emp_perms["outlet"] or outlet_code
            emp_name                  = emp_perms.get("employee_name") or str(employee_id)
        else:
            # Dynamically resolve cash counter without hardcoding
            counter_filter = {"hospital_code": hospital_code, "branch_code": branch_code, "is_active": True}
            if requested_counter:
                counter_filter["counter_id"] = str(requested_counter).strip()
            elif outlet_code and isinstance(outlet_code, str):
                counter_filter["outlet"] = outlet_code

            counter_doc = cashcounter_collection.find_one(counter_filter) or cashcounter_collection.find_one({
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "is_active": True
            })

            if counter_doc:
                emp_cashcounter     = counter_doc.get("counter_id", "")
                matched_outlet      = counter_doc.get("outlet") or outlet_code
                cashcounter_details = {
                    "counter_id": emp_cashcounter,
                    "counter_name": counter_doc.get("counter_name", ""),
                    "outlet": matched_outlet
                }
                raw_bts = counter_doc.get("bill_type") or counter_doc.get("bill_types") or []
                allowed_bill_types = []
                allowed_bill_type_details = []
                if isinstance(raw_bts, list):
                    for bt in raw_bts:
                        if isinstance(bt, dict) and "bill_type" in bt:
                            allowed_bill_types.append(bt["bill_type"])
                            allowed_bill_type_details.append(bt)
                        elif str(bt).isdigit():
                            allowed_bill_types.append(int(bt))
                if allowed_bill_types and not allowed_bill_type_details:
                    bt_docs = list(billtype_collection.find({"bill_type": {"$in": allowed_bill_types}}, {"bill_type": 1, "bill_name": 1, "_id": 0}))
                    allowed_bill_type_details = [{"bill_type": b.get("bill_type"), "bill_name": b.get("bill_name", "")} for b in bt_docs]
            else:
                emp_cashcounter     = str(requested_counter or "").strip()
                matched_outlet      = outlet_code
                cashcounter_details = {"counter_id": emp_cashcounter, "counter_name": "", "outlet": matched_outlet}
                allowed_bill_types  = []
                allowed_bill_type_details = []

            emp_name = str(employee_id or "")

        # =========================================================
        # ✅ VERIFY ACTIVE SHIFT IN DB (DO NOT DISPLAY UNTIL SHIFT START)
        # =========================================================
        shift_col = hms_db["hospital_cashcountershiftdetails"]
        counter_id_check = cashcounter_details.get("counter_id") if cashcounter_details else emp_cashcounter
        shift_filter = {
            "ShiftStatus": {"$regex": "^active$", "$options": "i"},
            "is_active": True,
            "hospital_code": hospital_code,
            "branch_code": branch_code
        }
        if counter_id_check:
            shift_filter["CashCounter"] = counter_id_check
        active_shift = shift_col.find_one(shift_filter)
        if not active_shift and employee_id:
            active_shift = shift_col.find_one({
                "CashierID": str(employee_id),
                "ShiftStatus": {"$regex": "^active$", "$options": "i"},
                "is_active": True,
                "hospital_code": hospital_code,
                "branch_code": branch_code
            })

        if not active_shift:
            return Response({
                "employee_id": employee_id,
                "employee_name": emp_name,
                "cashcounter": cashcounter_details,
                "allowed_bill_type_details": allowed_bill_type_details,
                "shift_active": False,
                "message": "Shift not started. Please start a shift to view bills.",
                "data": []
            }, status=status.HTTP_200_OK)

        # =========================================================
        # ✅ Query Pharmacy Bills via PyMongo (payment_mode: "Cash" only)
        # =========================================================
        date_str = request.GET.get("date") or data.get("date")
        from_date_str = request.GET.get("from_date") or data.get("from_date")
        to_date_str = request.GET.get("to_date") or data.get("to_date")

        from_dt = None
        to_dt = None
        if from_date_str and to_date_str:
            try:
                from_dt = datetime.strptime(from_date_str.strip()[:10], "%Y-%m-%d")
                to_dt = datetime.strptime(to_date_str.strip()[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
            except Exception:
                pass
        elif date_str:
            try:
                from_dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
                to_dt = from_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            except Exception:
                pass

        import pytz
        from datetime import date
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        today_date_ist = now_ist.date()

        today_start_ist = ist.localize(datetime(now_ist.year, now_ist.month, now_ist.day, 0, 0, 0))
        today_end_ist = ist.localize(datetime(now_ist.year, now_ist.month, now_ist.day, 23, 59, 59, 999999))
        today_start_utc = today_start_ist.astimezone(pytz.utc).replace(tzinfo=None)
        today_end_utc = today_end_ist.astimezone(pytz.utc).replace(tzinfo=None)

        mongo_filter = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            # 🎯 1. PAYMENT MODE: CASH ALONE
            "payment_mode": {"$in": ["Cash", "cash", "CASH"]},
            "$or": [
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}}
            ]
        }

        if allowed_bill_types:
            mongo_filter["bill_type"] = {"$in": allowed_bill_types}

        if matched_outlet:
            if isinstance(matched_outlet, (list, tuple)):
                parsed_matched = [str(x).strip() for x in matched_outlet if str(x).strip()]
                if len(parsed_matched) == 1:
                    mongo_filter["outlet_code"] = parsed_matched[0]
                elif parsed_matched:
                    mongo_filter["outlet_code"] = {"$in": parsed_matched}
            elif str(matched_outlet).strip().upper() not in ["ALL", ""]:
                mongo_filter["outlet_code"] = str(matched_outlet).strip()

        if from_dt and to_dt:
            mongo_filter["billing_status"] = {"$in": ["Billed", "Paid", "Processing", "Pending"]}
            mongo_filter["$and"] = [
                {"$or": [
                    {"paid_date": {"$gte": from_dt, "$lte": to_dt}},
                    {"paid_datetime": {"$gte": from_dt, "$lte": to_dt}},
                    {"bill_date": {"$gte": from_dt, "$lte": to_dt}},
                    {"created_date": {"$gte": from_dt, "$lte": to_dt}},
                ]}
            ]
        else:
            # 🎯 Unpaid cash bills (current date + older past dates) + Paid cash bills (current date paid_date or bill_date)
            mongo_filter["$and"] = [
                {"$or": [
                    {"billing_status": {"$in": ["Billed", "Processing", "Pending"]}},
                    {
                        "billing_status": "Paid",
                        "$or": [
                            {"paid_date": {"$gte": today_start_utc, "$lte": today_end_utc}},
                            {"paid_datetime": {"$gte": today_start_utc, "$lte": today_end_utc}},
                            {"bill_date": {"$gte": today_start_utc, "$lte": today_end_utc}},
                            {"created_date": {"$gte": today_start_utc, "$lte": today_end_utc}}
                        ]
                    }
                ]}
            ]

        raw_bills = list(oppharmacy_collection.find(mongo_filter).sort("created_date", -1).limit(2000))

        if not raw_bills:
            return Response({
                "employee_id": employee_id,
                "employee_name": emp_name,
                "cashcounter": cashcounter_details,
                "allowed_bill_type_details": allowed_bill_type_details,
                "shift_active": True,
                "data": []
            }, status=status.HTTP_200_OK)

        # =========================================================
        # ✅ Patient Mapping (Batch fetch)
        # =========================================================
        uhids = list(set([str(b.get("uhid")).strip() for b in raw_bills if b.get("uhid")]))
        patient_map = {}
        if uhids:
            try:
                patients = Patient.objects.filter(uhid__in=uhids)
                patient_map = {
                    str(p.uhid).strip(): f"{p.salutation or ''} {p.firstName or ''} {p.lastName or ''}".strip()
                    for p in patients
                }
            except Exception:
                pass

        # =========================================================
        # ✅ Doctor Mapping (Batch fetch from profile_collection)
        # =========================================================
        doctor_ids = []
        for b in raw_bills:
            d_id = b.get("doctor_id")
            if d_id:
                s_id = str(d_id).strip()
                doctor_ids.append(s_id)
                if s_id.isdigit():
                    doctor_ids.append(int(s_id))
        doctor_ids = list(set(doctor_ids))

        doctor_map = {}
        if doctor_ids:
            doctor_cursor = profile_collection.find(
                {"employeeId": {"$in": doctor_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            )
            for doc in doctor_cursor:
                doc_name = doc.get("employeeName", "")
                if doc_name and not doc_name.lower().startswith("dr"):
                    doc_name = f"Dr. {doc_name}"
                doctor_map[str(doc.get("employeeId"))] = doc_name

        # =========================================================
        # ✅ Bill Type Mapping
        # =========================================================
        bill_types = []
        for b in raw_bills:
            bt_val = b.get("bill_type")
            if bt_val is not None:
                if str(bt_val).isdigit():
                    bill_types.append(int(bt_val))
                else:
                    bill_types.append(bt_val)
        bill_types = list(set(bill_types))

        billtype_map = {}
        if bill_types:
            billtype_cursor = billtype_collection.find(
                {"bill_type": {"$in": bill_types}},
                {"bill_type": 1, "bill_name": 1, "_id": 0}
            )
            billtype_map = {
                bt["bill_type"]: bt.get("bill_name", "")
                for bt in billtype_cursor
            }

        # =========================================================
        # ✅ Collect Items & Stock Mapping
        # =========================================================
        item_ids = set()
        item_batch_set = set()
        for b in raw_bills:
            for item in b.get("medicine_particulars", []):
                if not isinstance(item, dict):
                    continue
                iid = item.get("item_id")
                if iid is not None:
                    try:
                        item_ids.add(int(iid))
                    except (ValueError, TypeError):
                        item_ids.add(str(iid))
                b_num = str(item.get("batch_number") or "").strip()
                if iid is not None and b_num:
                    try:
                        item_batch_set.add((int(iid), b_num))
                    except (ValueError, TypeError):
                        item_batch_set.add((str(iid), b_num))

        item_ids = list(item_ids)
        batch_numbers = list(set([i[1] for i in item_batch_set]))

        item_map = {}
        if item_ids:
            item_cursor = pharmacy_item_collection.find(
                {
                    "item_id": {"$in": item_ids},
                    "hospital_code": hospital_code,
                    "branch_code": branch_code
                },
                {"item_id": 1, "item_name": 1, "_id": 0}
            )
            item_map = {i["item_id"]: i.get("item_name", "") for i in item_cursor}

        stock_map = {}
        if item_ids and batch_numbers:
            stock_filter = {
                "item_id": {"$in": item_ids},
                "batch_number": {"$in": batch_numbers},
                "hospital_code": hospital_code,
                "branch_code": branch_code
            }
            if matched_outlet:
                if isinstance(matched_outlet, (list, tuple)):
                    parsed_so = [str(x).strip() for x in matched_outlet if str(x).strip()]
                    if len(parsed_so) == 1:
                        stock_filter["outlet_code"] = parsed_so[0]
                    elif parsed_so:
                        stock_filter["outlet_code"] = {"$in": parsed_so}
                elif str(matched_outlet).strip().upper() not in ["ALL", ""]:
                    stock_filter["outlet_code"] = str(matched_outlet).strip()

            stock_cursor = pharmacy_stock_collection.find(
                stock_filter,
                {
                    "item_id": 1,
                    "batch_number": 1,
                    "CGST_Percentage": 1,
                    "SGST_Percentage": 1,
                    "CGST_Amt": 1,
                    "SGST_Amt": 1,
                    "_id": 0
                }
            )
            stock_map = {
                (s["item_id"], str(s.get("batch_number") or "").strip()): s
                for s in stock_cursor
            }

        # =========================================================
        # ✅ Final Response Serialization
        # =========================================================
        bills_result = []
        for bill in raw_bills:
            serialized = dict(bill)
            if "_id" in serialized:
                serialized["_id"] = str(serialized["_id"])
            for d_key in ["created_date", "lastmodified_date", "bill_date", "paid_date", "paid_datetime", "ward_request_date"]:
                val = serialized.get(d_key)
                if val and hasattr(val, "isoformat"):
                    serialized[d_key] = val.isoformat()

            b_status = str(bill.get("billing_status") or "").strip()
            is_unpaid_status = b_status in ["Billed", "Processing", "Pending"]
            is_paid_status = (b_status == "Paid")

            # 🎯 Evaluate date against current date (Asia/Kolkata):
            # For paid bills, evaluate using paid_date (as requested: "received also display based on the today paid_date")
            if is_paid_status:
                raw_bdate = bill.get("paid_date") or bill.get("paid_datetime") or bill.get("lastmodified_date") or bill.get("bill_date") or bill.get("created_date")
            else:
                raw_bdate = bill.get("bill_date") or bill.get("created_date")

            is_today = False
            if raw_bdate:
                if isinstance(raw_bdate, str):
                    try:
                        clean_str = raw_bdate.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(clean_str)
                        if dt.tzinfo is None:
                            dt_ist = pytz.utc.localize(dt).astimezone(ist)
                        else:
                            dt_ist = dt.astimezone(ist)
                        is_today = (dt_ist.date() == today_date_ist)
                    except Exception:
                        pass
                elif isinstance(raw_bdate, datetime):
                    if raw_bdate.tzinfo is None:
                        dt_ist = pytz.utc.localize(raw_bdate).astimezone(ist)
                    else:
                        dt_ist = raw_bdate.astimezone(ist)
                    is_today = (dt_ist.date() == today_date_ist)
                elif isinstance(raw_bdate, date):
                    is_today = (raw_bdate == today_date_ist)

            serialized["is_current_date"] = is_today
            serialized["is_pending"] = bool(is_unpaid_status and is_today)
            serialized["is_unpaid"] = bool(is_unpaid_status and not is_today)
            serialized["is_received"] = bool(is_paid_status and is_today)

            uhid_str = str(bill.get("uhid") or "").strip()
            doc_id_str = str(bill.get("doctor_id") or "").strip()
            bt_raw = bill.get("bill_type")
            bt_key = int(bt_raw) if str(bt_raw).isdigit() else bt_raw

            serialized["patient_name"] = patient_map.get(uhid_str, "") or bill.get("patientname") or ""
            serialized["doctor_name"]  = doctor_map.get(doc_id_str, "")
            serialized["bill_type_name"] = billtype_map.get(bt_key, "")

            medicine_list = bill.get("medicine_particulars", [])
            updated_items = []
            for item in medicine_list:
                if not isinstance(item, dict):
                    continue
                it_dict = dict(item)
                iid_val = int(it_dict["item_id"]) if str(it_dict.get("item_id", "")).isdigit() else it_dict.get("item_id")
                batch_number = str(it_dict.get("batch_number") or "").strip()

                it_dict["item_name"] = it_dict.get("item_name") or item_map.get(iid_val, "")

                stock = stock_map.get((iid_val, batch_number), {})
                it_dict["CGST_Percentage"] = convert_decimal(stock.get("CGST_Percentage", 0))
                it_dict["SGST_Percentage"] = convert_decimal(stock.get("SGST_Percentage", 0))
                it_dict["CGST_Amt"]        = convert_decimal(stock.get("CGST_Amt", 0))
                it_dict["SGST_Amt"]        = convert_decimal(stock.get("SGST_Amt", 0))

                updated_items.append(it_dict)

            serialized["medicine_particulars"] = updated_items
            bills_result.append(serialized)

        req_status = (request.GET.get("status") or (data.get("status") if isinstance(data, dict) else "") or request.GET.get("type") or "").strip().lower()
        if req_status == "pending":
            bills_result = [b for b in bills_result if b.get("is_pending")]
        elif req_status == "unpaid":
            bills_result = [b for b in bills_result if b.get("is_unpaid")]
        elif req_status in ["received", "paid"]:
            bills_result = [b for b in bills_result if b.get("is_received")]

        return Response({
            "employee_id": employee_id,
            "employee_name": emp_name,
            "cashcounter": cashcounter_details,
            "allowed_bill_type_details": allowed_bill_type_details,
            "shift_active": True,
            "data": bills_result
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "status": "error",
            "message": "Failed to fetch OP Pharmacy pending bills",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


