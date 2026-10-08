"""
Centralized atomic counter service for HMS using MongoDB 'counters' collection.
Ensures thread-safe, strictly sequential, collision-free ID and bill number generation
across huge migrated datasets for:
1. Admission (IP Number)
2. IP Advance & Refund (Bill Number)
3. Inventory (PharmacyItem, Vendor, Category, ChemicalComposition, GRN Draft)
4. Rooms (RoomCategory, Block, NursingStation/Ward, ServiceDescription, KitItems, Shifting)
5. Discharge Billing (Bill Number)
"""

import os
import re
from datetime import datetime
from pymongo import MongoClient, ReturnDocument


def _get_db():
    host = os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017")
    client = MongoClient(host, connectTimeoutMS=5000, serverSelectionTimeoutMS=5000)
    return client, client["HMS"]


def _current_fin_year_prefix():
    now_dt = datetime.now()
    year = now_dt.year
    month = now_dt.month
    if month >= 4:
        return f"{year % 100:02d}{(year + 1) % 100:02d}"
    else:
        return f"{(year - 1) % 100:02d}{year % 100:02d}"


def _current_admission_prefix():
    now_dt = datetime.now()
    fy = (now_dt.year - 2001) if now_dt.month < 4 else (now_dt.year - 2000)
    return f"S{fy:03d}"


# ─────────────────────────────────────────────────────────────────────────────
# Seed Resolvers (only run once when a counter is not yet initialized)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_seed_admission_ip(db, prefix):
    """Finds maximum existing IP number under prefix, excluding legacy test offset >= 500k."""
    top_ips = list(db["hospital_admission"].find(
        {"ipNumber": {"$regex": f"^{prefix}/"}},
        {"ipNumber": 1}
    ).sort("ipNumber", -1).limit(50))

    max_num = 0
    for a in top_ips:
        ip = str(a.get("ipNumber") or "").strip()
        if "/" in ip:
            try:
                p, n_str = ip.split("/", 1)
                if p == prefix:
                    n = int(n_str)
                    if n < 500000 and n > max_num:
                        max_num = n
            except Exception:
                continue

    if max_num == 0 and top_ips:
        for a in top_ips:
            ip = str(a.get("ipNumber") or "").strip()
            if "/" in ip:
                try:
                    p, n_str = ip.split("/", 1)
                    if p == prefix:
                        n = int(n_str)
                        if n > max_num:
                            max_num = n
                except Exception:
                    continue
    return max_num


def _resolve_seed_advance_bill(db, fy):
    """Finds true maximum bill_no in advance_payments array for financial year."""
    pipeline = [
        {"$match": {"advance_payments.bill_no": {"$regex": f"^{fy}/"}}},
        {"$unwind": "$advance_payments"},
        {"$match": {"advance_payments.bill_no": {"$regex": f"^{fy}/"}}},
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
                if n > max_seq:
                    max_seq = n
        except Exception:
            continue
    return max_seq


def _resolve_seed_advance_refund(db, fy):
    latest = db["hospital_ipadvance_refund"].find_one(
        {"refund_bill_no": {"$regex": f"^{fy}/"}},
        projection={"refund_bill_no": 1},
        sort=[("refund_bill_no", -1)]
    )
    if latest and latest.get("refund_bill_no"):
        try:
            return int(str(latest["refund_bill_no"]).split("/")[-1])
        except Exception:
            pass
    return 0


def _resolve_seed_discharge_bill(db, fy):
    """Finds true maximum bill_no in hospital_dischargebilling for financial year."""
    latest = db["hospital_dischargebilling"].find_one(
        {"bill_no": {"$regex": f"^{fy}/"}},
        projection={"bill_no": 1},
        sort=[("bill_no", -1)]
    )
    if latest and latest.get("bill_no"):
        try:
            return int(str(latest["bill_no"]).split("/")[-1])
        except Exception:
            pass
    return 0


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

def get_next_sequence_value(counter_name, seed_resolver=None, default_seed=0):
    """
    Atomically increments and returns the next integer sequence for counter_name.
    - If the counter doesn't exist in MongoDB, it seeds from seed_resolver(db) or default_seed.
    - Uses find_one_and_update with $inc and ReturnDocument.AFTER.
    """
    client, db = _get_db()
    try:
        counters = db["counters"]
        existing = counters.find_one({"_id": counter_name})

        if existing is None:
            # Seed the counter from existing database data
            seed = 0
            if seed_resolver and callable(seed_resolver):
                try:
                    seed = seed_resolver(db)
                except Exception as e:
                    print(f"[counter_service] Error resolving seed for {counter_name}: {e}")
            if seed == 0 and default_seed > 0:
                seed = default_seed

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
        client.close()


# ─────────────────────────────────────────────────────────────────────────────
# Domain-Specific Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

# 1. Admission IP Number
def get_next_admission_ip(prefix=None):
    """Returns next sequential IP number, e.g. 'S026/001692'."""
    p = prefix or _current_admission_prefix()
    counter_name = f"admission_ip_{p}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_admission_ip(db, p)
    )
    return f"{p}/{seq:06d}"


# 2. IP Advance & Refund Bill Numbers
def get_next_advance_bill_no(fy=None):
    """Returns next sequential IP Advance bill number, e.g. '2627/028226'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"ip_advance_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_advance_bill(db, year_prefix)
    )
    return f"{year_prefix}/{seq:06d}"


def get_next_advance_refund_bill_no(fy=None):
    """Returns next sequential IP Advance Refund bill number, e.g. '2627/000003'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"ip_refund_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_advance_refund(db, year_prefix)
    )
    return f"{year_prefix}/{seq:06d}"


# 3. Discharge Billing Bill Number
def get_next_discharge_bill_no(fy=None):
    """Returns next sequential Discharge bill number, e.g. '2627/005691'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"discharge_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_discharge_bill(db, year_prefix)
    )
    return f"{year_prefix}/{seq:06d}"


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
