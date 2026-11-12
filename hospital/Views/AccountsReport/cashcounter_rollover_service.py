import os
import zoneinfo
from datetime import datetime, date, time
from decimal import Decimal
from bson.decimal128 import Decimal128
from pymongo import MongoClient
from django.utils import timezone

from hospital.models import Cashcountershiftdetails
from hospital.Views.cashcounter import (
    calculate_shift_collection,
    generate_shift_no,
    safe_dec,
    convert_decimal128,
    convert_decimal,
)

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# State variables for debouncing daily runs
_last_closed_date = None
_last_opened_date = None


def get_current_ist_datetime():
    return datetime.now(IST)


def auto_close_active_shifts(closing_time_ist=None):
    """
    Auto-close all active cashcounter shifts at 11:59 PM IST.
    Closing balance = Opening Balance + Cash Collected - Sales Return.
    (RemittedToBank, SubmittedToAccount, HandOverAmount are set to 0.00).
    """
    now_ist = closing_time_ist or get_current_ist_datetime()
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    shift_col = db["hospital_cashcountershiftdetails"]

    # Find all active shifts in MongoDB
    active_docs = list(shift_col.find({
        "ShiftStatus": "active",
        "is_active": True,
        "closingTime": None
    }))

    closed_shifts = []

    for doc in active_docs:
        shift_no = str(doc.get("shiftno"))
        if not shift_no:
            continue

        try:
            # 1. Recalculate live collections
            totals = calculate_shift_collection(shift_no)
            collected_amount = safe_dec(totals.get("total_collection", 0))
            credit_amount = safe_dec(totals.get("total_credit", 0))
            sales_return = safe_dec(totals.get("sales_return", 0))

            opening_val = safe_dec(doc.get("OpeningBalance", 0))
            # Formula: Opening Balance + Cash Collected - Sales Return
            closing_val = opening_val + collected_amount - sales_return

            closing_dt = now_ist.replace(hour=23, minute=59, second=0, microsecond=0) if closing_time_ist is None else closing_time_ist

            # 2. Update MongoDB document
            update_data = {
                "ShiftStatus": "inactive",
                "is_active": False,
                "closingTime": closing_dt,
                "ClosingBalance": Decimal128(str(closing_val)),
                "collected_Amount": Decimal128(str(collected_amount)),
                "CreditAmount": Decimal128(str(credit_amount)),
                "SalesReturnAmount": Decimal128(str(sales_return)),
                "auto_closed": True,
                "auto_closed_at": now_ist,
                "auto_rollover_candidate": True,
                "lastmodified_by": "SYSTEM_AUTO_ROLLOVER",
                "lastmodified_date": timezone.now(),
            }
            shift_col.update_one({"_id": doc["_id"]}, {"$set": update_data})

            # 3. Update Django ORM if exists
            try:
                orm_shift = Cashcountershiftdetails.objects.filter(shiftno=shift_no).first()
                if orm_shift:
                    orm_shift.ShiftStatus = "inactive"
                    orm_shift.is_active = False
                    orm_shift.closingTime = closing_dt
                    orm_shift.ClosingBalance = safe_dec(closing_val)
                    orm_shift.collected_Amount = safe_dec(collected_amount)
                    orm_shift.CreditAmount = safe_dec(credit_amount)
                    orm_shift.SalesReturnAmount = safe_dec(sales_return)
                    orm_shift.lastmodified_by = "SYSTEM_AUTO_ROLLOVER"
                    orm_shift.lastmodified_date = timezone.now()
                    orm_shift.save()
            except Exception as e_orm:
                print(f"⚠️ [AutoClose] ORM sync error for {shift_no}:", e_orm)

            closed_shifts.append({
                "shiftno": shift_no,
                "CashCounter": doc.get("CashCounter"),
                "CashierID": doc.get("CashierID"),
                "ClosingBalance": float(closing_val),
                "collected_Amount": float(collected_amount),
                "SalesReturnAmount": float(sales_return),
            })
            print(f"🔒 [AutoClose] Successfully auto-closed shift #{shift_no} (Closing Bal: {closing_val})")

        except Exception as err:
            print(f"❌ [AutoClose] Error auto-closing shift #{shift_no}:", err)

    client.close()
    return {
        "success": True,
        "count": len(closed_shifts),
        "closed_shifts": closed_shifts,
        "timestamp_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }


def auto_open_closed_shifts(opening_time_ist=None):
    """
    Auto-open new active shifts at 12:00 AM IST for counters whose shifts were auto-closed.
    Opening balance = 0.00 (default for all shifts).
    previous_closing_balance = Closing Balance of the auto-closed shift.
    """
    now_ist = opening_time_ist or get_current_ist_datetime()
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    shift_col = db["hospital_cashcountershiftdetails"]

    # Find candidates that were auto-closed and haven't had a new shift opened
    candidates = list(shift_col.find({
        "auto_closed": True,
        "auto_rollover_candidate": True,
        "ShiftStatus": "inactive",
    }).sort("closingTime", -1))

    opened_shifts = []

    # Keep track of counters already processed in this batch to avoid duplicates
    processed_counters = set()

    for old_shift in candidates:
        counter_code = str(old_shift.get("CashCounter") or "").strip()
        if not counter_code or counter_code in processed_counters:
            continue

        # Check if an active shift already exists for this counter
        existing_active = shift_col.find_one({
            "CashCounter": counter_code,
            "ShiftStatus": "active",
            "is_active": True,
            "closingTime": None
        })

        if existing_active:
            print(f"ℹ️ [AutoOpen] Counter {counter_code} already has active shift #{existing_active.get('shiftno')}, skipping reopen.")
            shift_col.update_one({"_id": old_shift["_id"]}, {"$set": {"auto_rollover_candidate": False}})
            continue

        try:
            # Generate new sequential shift number
            new_shift_no = generate_shift_no(counter_code)

            prev_closing = convert_decimal(old_shift.get("ClosingBalance", 0.0))
            start_dt = now_ist.replace(hour=0, minute=0, second=0, microsecond=0) if opening_time_ist is None else opening_time_ist
            shift_date = start_dt.date()

            cashier_id = str(old_shift.get("CashierID") or "SYSTEM")
            hospital_code = str(old_shift.get("hospital_code") or "SH001")
            branch_code = str(old_shift.get("branch_code") or "SHB001")
            outlet_code = str(old_shift.get("SelectedOutlet") or old_shift.get("outlet_code") or "OLET003")
            counter_name = str(old_shift.get("CashCounterName") or counter_code)
            petty_cash = old_shift.get("PettyCashBalance", 1000.0)

            new_shift_doc = {
                "shiftno": new_shift_no,
                "CashierID": cashier_id,
                "CashCounter": counter_code,
                "CashCounterName": counter_name,
                "SelectedOutlet": outlet_code,
                "OpeningBalance": Decimal128("0.00"),          # Default 0.00 for all shifts
                "previous_closing_balance": Decimal128(str(prev_closing)), # Historical reference
                "PettyCashBalance": Decimal128(str(petty_cash) if petty_cash is not None else "1000.00"),
                "StartingTime": start_dt,
                "ShiftStatus": "active",
                "is_active": True,
                "closingTime": None,
                "collected_Amount": Decimal128("0.00"),
                "CreditAmount": Decimal128("0.00"),
                "SalesReturnAmount": Decimal128("0.00"),
                "ClosingBalance": Decimal128("0.00"),
                "created_by": cashier_id,
                "created_date": start_dt,
                "date": datetime.combine(shift_date, time.min),
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
                "created_br": branch_code,
                "auto_opened": True,
                "auto_opened_at": now_ist,
                "previous_shiftno": old_shift.get("shiftno"),
            }

            # Insert into MongoDB
            shift_col.insert_one(new_shift_doc)

            # Insert into Django ORM
            try:
                Cashcountershiftdetails.objects.create(
                    shiftno=new_shift_no,
                    CashierID=cashier_id,
                    CashCounter=counter_code,
                    CashCounterName=counter_name,
                    SelectedOutlet=outlet_code,
                    OpeningBalance=Decimal("0.00"),
                    PettyCashBalance=safe_dec(petty_cash) if petty_cash is not None else Decimal("1000.00"),
                    StartingTime=start_dt,
                    ShiftStatus="active",
                    is_active=True,
                    created_by=cashier_id,
                    created_date=start_dt,
                    date=shift_date,
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    outlet_code=outlet_code,
                    created_br=branch_code,
                )
            except Exception as e_orm:
                print(f"⚠️ [AutoOpen] ORM create error for #{new_shift_no}:", e_orm)

            # Mark old shift as fulfilled (no longer pending reopen)
            shift_col.update_one({"_id": old_shift["_id"]}, {"$set": {"auto_rollover_candidate": False}})
            processed_counters.add(counter_code)

            opened_shifts.append({
                "shiftno": new_shift_no,
                "CashCounter": counter_code,
                "CashierID": cashier_id,
                "previous_shiftno": old_shift.get("shiftno"),
                "previous_closing_balance": float(prev_closing),
                "OpeningBalance": 0.0,
            })
            print(f"🔓 [AutoOpen] Successfully auto-opened shift #{new_shift_no} for counter {counter_code} (Prev Close: {prev_closing})")

        except Exception as err:
            print(f"❌ [AutoOpen] Error auto-opening shift for counter {counter_code}:", err)

    client.close()
    return {
        "success": True,
        "count": len(opened_shifts),
        "opened_shifts": opened_shifts,
        "timestamp_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }


def trigger_rollover_check():
    """
    Called periodically by the background scheduler to check if it's 11:59 PM or 12:00 AM IST.
    """
    global _last_closed_date, _last_opened_date
    now_ist = get_current_ist_datetime()
    today_ist = now_ist.date()

    # 1. Check for Auto-Close at 11:59 PM IST (23:59)
    if now_ist.hour == 23 and now_ist.minute == 59:
        if _last_closed_date != today_ist:
            print(f"⏰ [RolloverCheck] Reached 23:59 IST on {today_ist}. Executing auto-close...")
            res = auto_close_active_shifts(now_ist)
            _last_closed_date = today_ist
            return {"action": "close", "result": res}

    # 2. Check for Auto-Open at 12:00 AM IST (00:00 - 00:01)
    if now_ist.hour == 0 and now_ist.minute in (0, 1):
        if _last_opened_date != today_ist:
            print(f"⏰ [RolloverCheck] Reached 00:00 IST on {today_ist}. Executing auto-open...")
            res = auto_open_closed_shifts(now_ist)
            _last_opened_date = today_ist
            return {"action": "open", "result": res}

    return None


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def cashcounter_auto_rollover_api(request):
    """
    API endpoint for checking rollover status or manually triggering 23:59 close / 00:00 open.
    """
    action = (request.data.get("action") if request.method == "POST" else request.query_params.get("action")) or "status"

    if action == "close":
        res = auto_close_active_shifts()
        return Response(res, status=status.HTTP_200_OK)
    elif action == "open":
        res = auto_open_closed_shifts()
        return Response(res, status=status.HTTP_200_OK)
    elif action == "rollover":
        c_res = auto_close_active_shifts()
        o_res = auto_open_closed_shifts()
        return Response({"success": True, "close": c_res, "open": o_res}, status=status.HTTP_200_OK)
    else:
        now_ist = get_current_ist_datetime()
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        active_count = db["hospital_cashcountershiftdetails"].count_documents({
            "ShiftStatus": "active",
            "is_active": True,
            "closingTime": None
        })
        pending_reopen_count = db["hospital_cashcountershiftdetails"].count_documents({
            "auto_closed": True,
            "auto_rollover_candidate": True,
            "ShiftStatus": "inactive",
        })
        recent_shifts = list(db["hospital_cashcountershiftdetails"].find().sort("StartingTime", -1).limit(5))
        shifts_summary = []
        for s in recent_shifts:
            shifts_summary.append({
                "shiftno": s.get("shiftno"),
                "CashCounter": s.get("CashCounter"),
                "CashierID": s.get("CashierID"),
                "OpeningBalance": float(convert_decimal(s.get("OpeningBalance", 0))),
                "ClosingBalance": float(convert_decimal(s.get("ClosingBalance", 0))),
                "ShiftStatus": s.get("ShiftStatus"),
                "is_active": s.get("is_active"),
                "auto_closed": s.get("auto_closed", False),
                "auto_opened": s.get("auto_opened", False),
            })
        client.close()
        return Response({
            "success": True,
            "current_ist_time": now_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "active_shifts_count": active_count,
            "pending_auto_reopen_count": pending_reopen_count,
            "auto_close_schedule": "23:59:00 IST every night",
            "auto_open_schedule": "00:00:00 IST every night",
            "formula": "ClosingBalance = OpeningBalance + CashCollected - SalesReturn",
            "recent_shifts": shifts_summary,
        }, status=status.HTTP_200_OK)

