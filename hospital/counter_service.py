"""
Centralized atomic counter service for HMS using MongoDB 'counters' collection.
Ensures thread-safe, strictly sequential, collision-free ID and bill number generation
across huge migrated datasets for:
1. Admission (IP Number)
2. IP Advance & Refund (Bill Number)
3. Inventory (PharmacyItem, Vendor, Category, ChemicalComposition, GRN Draft)
4. Rooms (RoomCategory, Block, NursingStation/Ward, ServiceDescription, KitItems, Shifting)
5. Discharge Billing (Bill Number)
6. Pharmacy Billing (Outlet-Wise Bill Number)
"""

import os
import re
from datetime import datetime
from pymongo import MongoClient, ReturnDocument


def _get_db():
    host = os.getenv("GLOBAL_DB_HOST")
    if not host:
        try:
            from django.conf import settings
            host = getattr(settings, "GLOBAL_DB_HOST", None)
        except Exception:
            host = None
    if not host:
        host = "mongodb://localhost:27017"
    client = MongoClient(host, connectTimeoutMS=5000, serverSelectionTimeoutMS=5000)
    db_name = os.getenv("HMS_DB_NAME", "HMS")
    return client, client[db_name]


def _current_fin_year_prefix():
    now_dt = datetime.now()
    year = now_dt.year
    month = now_dt.month
    if month >= 4:
        return f"{year % 100:02d}{(year + 1) % 100:02d}"
    else:
        return f"{(year - 1) % 100:02d}{year % 100:02d}"


def _current_admission_prefix(is_daycare=False):
    now_dt = datetime.now()
    fy = (now_dt.year - 2001) if now_dt.month < 4 else (now_dt.year - 2000)
    if is_daycare:
        return f"SD{fy:02d}"
    return f"S{fy:03d}"


# ─────────────────────────────────────────────────────────────────────────────
# Seed Resolvers (only run once when a counter is not yet initialized)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_seed_admission_ip(db, prefix):
    """
    Finds maximum existing sequential IP number under prefix in the normal range (< 500000).
    Ignores test/legacy 5-series (>= 500000).
    If 000001 does not exist under prefix, starts cleanly at 0 so the first generated IP is 000001.
    """
    cursor = db["hospital_admission"].find(
        {"ipNumber": {"$regex": f"^{prefix}/"}},
        {"ipNumber": 1}
    )

    max_num = 0
    has_first = False
    for a in cursor:
        ip = str(a.get("ipNumber") or "").strip()
        if "/" in ip:
            try:
                p, n_str = ip.split("/", 1)
                if p == prefix:
                    n = int(n_str)
                    if n == 1:
                        has_first = True
                    if 0 < n < 500000 and n > max_num:
                        max_num = n
            except Exception:
                continue

    if not has_first:
        return 0

    return max_num


def _resolve_seed_advance_bill(db, fy):
    """Finds true maximum bill_no in advance_payments array for financial year."""
    pipeline = [
        {"$match": {"advance_payments.bill_no": {"$regex": f"^{fy}/|^{fy}\\d+"}}},
        {"$unwind": "$advance_payments"},
        {"$match": {"advance_payments.bill_no": {"$regex": f"^{fy}/|^{fy}\\d+"}}},
        {"$project": {"bill_no": "$advance_payments.bill_no"}},
        {"$sort": {"bill_no": -1}},
        {"$limit": 5}
    ]
    max_seq = 0
    for doc in db["hospital_admission"].aggregate(pipeline):
        try:
            bn = str(doc.get("bill_no", ""))
            if "/" in bn:
                n = int(bn.split("/")[-1])
            elif bn.startswith(fy):
                n = int(bn[len(fy):])
            else:
                continue
            if n > max_seq:
                max_seq = n
        except Exception:
            continue
    return max_seq


def _resolve_seed_advance_refund(db, fy):
    latest = db["hospital_ipadvance_refund"].find_one(
        {"refund_bill_no": {"$regex": f"^{fy}/|^{fy}\\d+"}},
        projection={"refund_bill_no": 1},
        sort=[("refund_bill_no", -1)]
    )
    if latest and latest.get("refund_bill_no"):
        try:
            s = str(latest["refund_bill_no"])
            if "/" in s:
                return int(s.split("/")[-1])
            elif s.startswith(fy):
                return int(s[len(fy):])
        except Exception:
            pass
    return 0


def _resolve_seed_discharge_bill(db, fy):
    """Finds true maximum bill_no in hospital_dischargebilling for financial year."""
    latest = db["hospital_dischargebilling"].find_one(
        {"bill_no": {"$regex": f"^{fy}/|^{fy}\\d+"}},
        projection={"bill_no": 1},
        sort=[("bill_no", -1)]
    )
    if latest and latest.get("bill_no"):
        try:
            s = str(latest["bill_no"])
            if "/" in s:
                return int(s.split("/")[-1])
            elif s.startswith(fy):
                return int(s[len(fy):])
        except Exception:
            pass
    return 0


def _resolve_seed_pharmacy_bill(db, outlet_code, fy, outlet_suffix="01"):
    """Finds maximum bill_no sequence for an outlet under financial year fy and outlet suffix."""
    clean_outlet = str(outlet_code or "").strip()
    prefix = f"{fy}{outlet_suffix}"
    max_no = 0

    try:
        match_q = {"bill_no": {"$regex": f"^{prefix}"}}
        if clean_outlet and clean_outlet != "DEFAULT":
            match_q["outlet_code"] = clean_outlet

        latest_bills = list(db["hospital_pharmacybilling"].find(
            match_q,
            projection={"bill_no": 1}
        ).sort("bill_no", -1).limit(20))

        for b in latest_bills:
            bn = str(b.get("bill_no") or "").strip()
            if bn.startswith(prefix):
                seq_str = bn[len(prefix):]
                if seq_str.isdigit():
                    num = int(seq_str)
                    if num > max_no:
                        max_no = num
    except Exception:
        pass

    try:
        from hospital.models import PharmacyBilling
        sql_bills = list(PharmacyBilling.objects.filter(bill_no__startswith=prefix).order_by('-bill_no')[:20])
        for b in sql_bills:
            bn = str(b.bill_no or "").strip()
            if bn.startswith(prefix):
                seq_str = bn[len(prefix):]
                if seq_str.isdigit():
                    num = int(seq_str)
                    if num > max_no:
                        max_no = num
    except Exception:
        pass

    return max_no


def _resolve_seed_sales_return_bill(db, outlet_code, fy, outlet_suffix="01"):
    """Finds maximum return_bill_no sequence for an outlet under financial year fy and outlet suffix."""
    clean_outlet = str(outlet_code or "").strip()
    prefix = f"{fy}{outlet_suffix}"
    max_no = 0

    try:
        match_q = {"return_bill_no": {"$regex": f"^{prefix}"}}
        if clean_outlet and clean_outlet != "DEFAULT":
            match_q["outlet_code"] = clean_outlet

        latest_returns = list(db["hospital_salesreturn"].find(
            match_q,
            projection={"return_bill_no": 1}
        ).sort("return_bill_no", -1).limit(20))

        for b in latest_returns:
            bn = str(b.get("return_bill_no") or "").strip()
            if bn.startswith(prefix):
                seq_str = bn[len(prefix):]
                if seq_str.isdigit():
                    num = int(seq_str)
                    if num > max_no:
                        max_no = num
    except Exception:
        pass

    try:
        from hospital.models import SalesReturn
        sql_returns = list(SalesReturn.objects.filter(return_bill_no__startswith=prefix).order_by('-return_bill_no')[:20])
        for b in sql_returns:
            bn = str(b.return_bill_no or "").strip()
            if bn.startswith(prefix):
                seq_str = bn[len(prefix):]
                if seq_str.isdigit():
                    num = int(seq_str)
                    if num > max_no:
                        max_no = num
    except Exception:
        pass

    return max_no


def _resolve_seed_pharmacy_item(db):
    latest = db["hospital_pharmacyitem"].find_one(sort=[("item_id", -1)], projection={"item_id": 1})
    if latest and latest.get("item_id") is not None:
        try:
            return int(latest["item_id"])
        except Exception:
            pass
    return 0


def _resolve_seed_vendor(db):
    max_v = 0
    for v in db["hospital_vendor"].find({}, {"vendor_id": 1}):
        try:
            vid = int(v.get("vendor_id", 0))
            if vid > max_v:
                max_v = vid
        except Exception:
            pass
    return max_v


def _resolve_seed_pharmacy_category(db):
    latest = db["hospital_pharmacycategory"].find_one(sort=[("category_id", -1)], projection={"category_id": 1})
    if latest and latest.get("category_id") is not None:
        try:
            return int(latest["category_id"])
        except Exception:
            pass
    return 0


def _resolve_seed_chemical_composition(db):
    latest = db["hospital_chemicalcomposition"].find_one(sort=[("composition_id", -1)], projection={"composition_id": 1})
    if latest and latest.get("composition_id") is not None:
        try:
            return int(latest["composition_id"])
        except Exception:
            pass
    return 0


def _resolve_seed_grn_draft(db, fy):
    latest = db["hospital_grn"].find_one(
        {"draft_number": {"$regex": f"^DRAFT/{fy}/"}},
        projection={"draft_number": 1},
        sort=[("draft_number", -1)]
    )
    if latest and latest.get("draft_number"):
        try:
            return int(str(latest["draft_number"]).split("/")[-1])
        except Exception:
            pass
    return 0


def _resolve_seed_room_category(db):
    latest = db["hospital_roomcategory"].find_one(sort=[("room_category_id", -1)], projection={"room_category_id": 1})
    if latest and latest.get("room_category_id") is not None:
        try:
            return int(latest["room_category_id"])
        except Exception:
            pass
    return 0


def _resolve_seed_block(db):
    latest = db["hospital_block"].find_one(sort=[("block_id", -1)], projection={"block_id": 1})
    if latest and latest.get("block_id") is not None:
        try:
            return int(latest["block_id"])
        except Exception:
            pass
    return 0


def _resolve_seed_ward(db):
    latest = db["hospital_nursingstation"].find_one(sort=[("ward_id", -1)], projection={"ward_id": 1})
    if latest and latest.get("ward_id") is not None:
        try:
            return int(latest["ward_id"])
        except Exception:
            pass
    return 0


def _resolve_seed_room_service_description(db):
    latest = db["hospital_roomservicedescription"].find_one(sort=[("description_id", -1)], projection={"description_id": 1})
    if latest and latest.get("description_id") is not None:
        try:
            return int(latest["description_id"])
        except Exception:
            pass
    return 0


def _resolve_seed_room_kit(db):
    latest = db["hospital_roomkititems"].find_one(sort=[("kit_id", -1)], projection={"kit_id": 1})
    if latest and latest.get("kit_id") is not None:
        try:
            return int(latest["kit_id"])
        except Exception:
            pass
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Core Atomic Sequence Generator
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_initial_seed(db, counter_name, seed_resolver=None, default_seed=0):
    """Computes the initial seed value when a counter document does not yet exist."""
    seed = 0
    if seed_resolver and callable(seed_resolver):
        try:
            seed = seed_resolver(db)
        except Exception as e:
            print(f"[counter_service] Error resolving seed for {counter_name}: {e}")
    if seed == 0 and default_seed > 0:
        seed = default_seed
    return seed


def peek_next_sequence_value(counter_name, seed_resolver=None, default_seed=0, db_instance=None):
    """
    Read-only preview of the next integer sequence (current seq + 1) for counter_name
    WITHOUT incrementing or mutating the 'counters' collection.
    """
    should_close = False
    if db_instance is not None:
        db = db_instance
    else:
        client, db = _get_db()
        should_close = True

    try:
        counters = db["counters"]
        existing = counters.find_one({"_id": counter_name})
        if existing is not None and "seq" in existing:
            return int(existing["seq"]) + 1
        seed = _resolve_initial_seed(db, counter_name, seed_resolver, default_seed)
        return int(seed) + 1
    finally:
        if should_close:
            try:
                client.close()
            except Exception:
                pass


def get_next_sequence_value(counter_name, seed_resolver=None, default_seed=0, db_instance=None):
    """
    Atomically increments and returns the next integer sequence for counter_name.
    - If the counter doesn't exist in MongoDB, it seeds from seed_resolver(db) or default_seed.
    - Uses find_one_and_update with $inc and ReturnDocument.AFTER.
    - If db_instance is provided, it reuses the connection without closing it.
    """
    should_close = False
    if db_instance is not None:
        db = db_instance
    else:
        client, db = _get_db()
        should_close = True

    try:
        counters = db["counters"]
        existing = counters.find_one({"_id": counter_name})

        if existing is None:
            seed = _resolve_initial_seed(db, counter_name, seed_resolver, default_seed)

            # Insert document with initial seed
            try:
                counters.update_one(
                    {"_id": counter_name},
                    {"$setOnInsert": {"seq": seed}},
                    upsert=True
                )
            except Exception:
                pass

        # Atomic increment
        doc = counters.find_one_and_update(
            {"_id": counter_name},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        return doc["seq"]
    finally:
        if should_close:
            try:
                client.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Domain-Specific Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

# 1. Admission IP Number
def peek_next_admission_ip(prefix=None, db_instance=None, is_daycare=False):
    """Read-only preview of next IP number (e.g. 'S026/000001' or 'SD26/000001') without consuming a sequence."""
    p = prefix or _current_admission_prefix(is_daycare=is_daycare)
    counter_name = f"admission_ip_{p}"
    seq = peek_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_admission_ip(db, p),
        db_instance=db_instance,
    )
    return f"{p}/{seq:06d}"


def get_next_admission_ip(prefix=None, db_instance=None, is_daycare=False):
    """Returns next sequential IP number, e.g. 'S026/000001' or 'SD26/000001'."""
    p = prefix or _current_admission_prefix(is_daycare=is_daycare)
    counter_name = f"admission_ip_{p}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_admission_ip(db, p),
        db_instance=db_instance,
    )
    return f"{p}/{seq:06d}"


# 2. IP Advance & Refund Bill Numbers
def get_next_advance_bill_no(fy=None):
    """Returns next sequential IP Advance bill number, e.g. '2627028226'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"ip_advance_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_advance_bill(db, year_prefix)
    )
    return f"{year_prefix}{seq:06d}"


def get_next_advance_refund_bill_no(fy=None):
    """Returns next sequential IP Advance Refund bill number, e.g. '2627000003'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"ip_refund_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_advance_refund(db, year_prefix)
    )
    return f"{year_prefix}{seq:06d}"


# 3. Discharge Billing Bill Number
def get_next_discharge_bill_no(fy=None):
    """Returns next sequential Discharge bill number, e.g. '2627005691'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"discharge_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_discharge_bill(db, year_prefix)
    )
    return f"{year_prefix}{seq:06d}"


# 4. Inventory Module IDs
def get_next_pharmacy_item_id():
    """Returns next integer item_id for PharmacyItem."""
    return get_next_sequence_value(
        "inventory_pharmacy_item_id",
        seed_resolver=_resolve_seed_pharmacy_item
    )


def get_next_vendor_id():
    """Returns next vendor_id as string, e.g. '836'."""
    val = get_next_sequence_value(
        "inventory_vendor_id",
        seed_resolver=_resolve_seed_vendor
    )
    return str(val)


def get_next_pharmacy_category_id():
    """Returns next integer category_id for PharmacyCategory."""
    return get_next_sequence_value(
        "inventory_category_id",
        seed_resolver=_resolve_seed_pharmacy_category
    )


def get_next_chemical_composition_id():
    """Returns next integer composition_id for ChemicalComposition."""
    return get_next_sequence_value(
        "inventory_chemical_composition_id",
        seed_resolver=_resolve_seed_chemical_composition
    )


def get_next_grn_draft_number(fy=None):
    """Returns next sequential GRN draft number, e.g. 'DRAFT/2627/001448'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"inventory_grn_draft_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_grn_draft(db, year_prefix)
    )
    return f"DRAFT/{year_prefix}/{str(seq).zfill(5)}"


# 5. Rooms Module IDs
def get_next_room_category_id():
    """Returns next integer room_category_id."""
    return get_next_sequence_value(
        "rooms_category_id",
        seed_resolver=_resolve_seed_room_category
    )


def get_next_block_id():
    """Returns next integer block_id."""
    return get_next_sequence_value(
        "rooms_block_id",
        seed_resolver=_resolve_seed_block
    )


def get_next_ward_id():
    """Returns next integer ward_id for NursingStation."""
    return get_next_sequence_value(
        "rooms_ward_id",
        seed_resolver=_resolve_seed_ward
    )


def get_next_room_service_description_id():
    """Returns next integer description_id for RoomServiceDescription."""
    return get_next_sequence_value(
        "rooms_service_description_id",
        seed_resolver=_resolve_seed_room_service_description
    )


def get_next_room_kit_id():
    """Returns next integer kit_id for RoomKitItems."""
    return get_next_sequence_value(
        "rooms_kit_id",
        seed_resolver=_resolve_seed_room_kit
    )


# 6. Pharmacy Billing Bill Number (Outlet-Wise)
def get_next_pharmacy_bill_no(outlet_code=None, fy=None, db_instance=None):
    """
    Returns next sequential, outlet-wise Pharmacy bill number:
    e.g. '262702000001' for OLET002, '262701000001' for OLET001.
    Formula: {FY}{outlet_code_2digits}{6-digit auto-increment}.
    Database-backed and atomic via MongoDB 'counters' collection.
    Independent series maintained per outlet_code.
    """
    clean_outlet = str(outlet_code or "DEFAULT").strip()
    year_prefix = fy or _current_fin_year_prefix()

    # Extract 2-digit outlet suffix (e.g. OLET002 -> 02, OLET001 -> 01)
    digits = re.findall(r'\d+', clean_outlet)
    if digits:
        try:
            outlet_suffix = f"{int(digits[-1]):02d}"
        except Exception:
            outlet_suffix = "01"
    else:
        outlet_suffix = "01"

    counter_name = f"pharmacy_bill_{clean_outlet}_{year_prefix}_{outlet_suffix}"

    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_pharmacy_bill(db, clean_outlet, year_prefix, outlet_suffix),
        db_instance=db_instance
    )
    return f"{year_prefix}{outlet_suffix}{seq:06d}"


# 7. Sales Return Bill Number (Outlet-Wise)
def get_next_sales_return_bill_no(outlet_code=None, fy=None, db_instance=None):
    """
    Returns next sequential, outlet-wise Sales Return bill number:
    e.g. '262702000001' for OLET002, '262701000001' for OLET001.
    Formula: {FY}{outlet_code_2digits}{6-digit auto-increment}.
    Database-backed and atomic via MongoDB 'counters' collection.
    Independent series maintained per outlet_code.
    """
    clean_outlet = str(outlet_code or "DEFAULT").strip()
    year_prefix = fy or _current_fin_year_prefix()

    # Extract 2-digit outlet suffix (e.g. OLET002 -> 02, OLET001 -> 01)
    digits = re.findall(r'\d+', clean_outlet)
    if digits:
        try:
            outlet_suffix = f"{int(digits[-1]):02d}"
        except Exception:
            outlet_suffix = "01"
    else:
        outlet_suffix = "01"

    counter_name = f"sales_return_bill_{clean_outlet}_{year_prefix}_{outlet_suffix}"

    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_sales_return_bill(db, clean_outlet, year_prefix, outlet_suffix),
        db_instance=db_instance
    )
    return f"{year_prefix}{outlet_suffix}{seq:06d}"
