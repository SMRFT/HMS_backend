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
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        backend_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(backend_env):
            load_dotenv(backend_env, override=True)
    except Exception:
        pass
    host = os.getenv("GLOBAL_DB_HOST")
    if not host:
        try:
            from django.conf import settings
            host = getattr(settings, "GLOBAL_DB_HOST", None)
        except Exception:
            host = None
    if not host:
        try:
            env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("GLOBAL_DB_HOST"):
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                host = parts[1].strip()
                                break
        except Exception:
            pass
    if not host:
        host = "mongodb://admin:SMRFT%40prod2026@45.252.190.162:27017/"
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
# Seed Resolvers (find true maximum existing sequence in database)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_seed_admission_ip(db, prefix):
    """
    Finds the maximum existing IP number under the given prefix.
    Preserves the highest sequence even if 000001 does not exist.
    """
    cursor = db["hospital_admission"].find(
        {"ipNumber": {"$regex": f"^{re.escape(prefix)}/"}},
        {"ipNumber": 1}
    )
    max_num = 0
    for admission in cursor:
        ip = str(admission.get("ipNumber") or "").strip()
        try:
            if "/" in ip:
                p, n_str = ip.split("/", 1)
                if p == prefix:
                    n = int(n_str)
                    if 0 < n < 500000:
                        max_num = max(max_num, n)
        except (ValueError, TypeError):
            continue
    return max_num


def _resolve_seed_advance_bill(db, fy):
    """Finds true maximum bill_no in advance_payments array for financial year."""
    max_seq = 0
    try:
        cursor = db["hospital_admission"].find(
            {"advance_payments.bill_no": {"$regex": f"^{re.escape(fy)}"}},
            {"advance_payments.bill_no": 1, "advance_payments.bill_number": 1}
        )
        for doc in cursor:
            for adv in doc.get("advance_payments", []):
                bn = str(adv.get("bill_no") or adv.get("bill_number") or "").strip()
                try:
                    if "/" in bn:
                        p, n_str = bn.split("/", 1)
                        if p == fy:
                            n = int(n_str)
                            if n > max_seq:
                                max_seq = n
                    elif bn.startswith(fy):
                        seq_str = bn[len(fy):]
                        if seq_str.isdigit():
                            n = int(seq_str)
                            if n > max_seq:
                                max_seq = n
                except (ValueError, TypeError):
                    continue
    except Exception:
        pass
    return max_seq


def _resolve_seed_advance_refund(db, fy):
    """Finds maximum refund_bill_no in hospital_ipadvance_refund for financial year."""
    max_seq = 0
    try:
        cursor = db["hospital_ipadvance_refund"].find(
            {"refund_bill_no": {"$regex": f"^{re.escape(fy)}"}},
            {"refund_bill_no": 1}
        )
        for doc in cursor:
            s = str(doc.get("refund_bill_no") or "").strip()
            try:
                if "/" in s:
                    p, n_str = s.split("/", 1)
                    if p == fy:
                        n = int(n_str)
                        if n > max_seq:
                            max_seq = n
                elif s.startswith(fy):
                    seq_str = s[len(fy):]
                    if seq_str.isdigit():
                        n = int(seq_str)
                        if n > max_seq:
                            max_seq = n
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return max_seq


def _resolve_seed_discharge_bill(db, fy):
    """Finds true maximum bill_no in hospital_dischargebilling for financial year (for cash/non-insurance bills)."""
    max_seq = 0
    try:
        cursor = db["hospital_dischargebilling"].find(
            {
                "customer_type": {"$ne": "INSURANCE"},
                "bill_no": {"$regex": f"^{re.escape(fy)}"}
            },
            {"bill_no": 1}
        )
        for doc in cursor:
            bn = str(doc.get("bill_no") or "").strip()
            try:
                if "/" in bn:
                    p, n_str = bn.split("/", 1)
                    if p == fy:
                        n = int(n_str)
                        if n > max_seq:
                            max_seq = n
                elif bn.startswith(fy):
                    seq_str = bn[len(fy):]
                    if seq_str.isdigit():
                        n = int(seq_str)
                        if n > max_seq:
                            max_seq = n
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return max_seq


def _resolve_seed_discharge_estimate(db, fy):
    """Finds true maximum estimate_number in hospital_dischargebilling for financial year (e.g. EST/2627/000001)."""
    max_seq = 0
    try:
        prefix = f"EST/{fy}/"
        cursor = db["hospital_dischargebilling"].find(
            {"estimate_number": {"$regex": f"^{re.escape(prefix)}"}},
            {"estimate_number": 1}
        )
        for doc in cursor:
            en = str(doc.get("estimate_number") or "").strip()
            try:
                parts = en.split("/")
                if len(parts) >= 3 and parts[1] == fy:
                    n = int(parts[2])
                    if n > max_seq:
                        max_seq = n
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return max_seq


def _resolve_seed_pharmacy_bill(db, outlet_code, fy, outlet_suffix="01"):
    """Finds maximum bill_no sequence for an outlet under financial year fy and outlet suffix."""
    clean_outlet = str(outlet_code or "").strip()
    prefix = f"{fy}{outlet_suffix}"
    alt_prefix = f"{fy}/"
    max_no = 0

    try:
        match_q = {"$or": [
            {"bill_no": {"$regex": f"^{prefix}"}},
            {"bill_no": {"$regex": f"^{re.escape(alt_prefix)}"}}
        ]}
        if clean_outlet and clean_outlet != "DEFAULT":
            match_q["outlet_code"] = clean_outlet

        cursor = db["hospital_pharmacybilling"].find(match_q, {"bill_no": 1})
        for b in cursor:
            bn = str(b.get("bill_no") or "").strip()
            try:
                if bn.startswith(prefix):
                    seq_str = bn[len(prefix):]
                    if seq_str.isdigit():
                        num = int(seq_str)
                        if num > max_no:
                            max_no = num
                elif "/" in bn:
                    p, seq_str = bn.split("/", 1)
                    if p == fy and seq_str.isdigit():
                        num = int(seq_str)
                        if num > max_no:
                            max_no = num
            except (ValueError, TypeError):
                continue
    except Exception:
        pass

    try:
        from hospital.models import PharmacyBilling
        sql_bills = list(PharmacyBilling.objects.filter(bill_no__startswith=prefix).values_list('bill_no', flat=True))
        for bn in sql_bills:
            bn = str(bn or "").strip()
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
    alt_prefix = f"{fy}/"
    max_no = 0

    try:
        match_q = {"$or": [
            {"return_bill_no": {"$regex": f"^{prefix}"}},
            {"return_bill_no": {"$regex": f"^{re.escape(alt_prefix)}"}}
        ]}
        if clean_outlet and clean_outlet != "DEFAULT":
            match_q["outlet_code"] = clean_outlet

        cursor = db["hospital_salesreturn"].find(match_q, {"return_bill_no": 1})
        for b in cursor:
            bn = str(b.get("return_bill_no") or "").strip()
            try:
                if bn.startswith(prefix):
                    seq_str = bn[len(prefix):]
                    if seq_str.isdigit():
                        num = int(seq_str)
                        if num > max_no:
                            max_no = num
                elif "/" in bn:
                    p, seq_str = bn.split("/", 1)
                    if p == fy and seq_str.isdigit():
                        num = int(seq_str)
                        if num > max_no:
                            max_no = num
            except (ValueError, TypeError):
                continue
    except Exception:
        pass

    try:
        from hospital.models import SalesReturn
        sql_returns = list(SalesReturn.objects.filter(return_bill_no__startswith=prefix).values_list('return_bill_no', flat=True))
        for bn in sql_returns:
            bn = str(bn or "").strip()
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
    """Finds maximum item_id for PharmacyItem across numeric and string records."""
    max_id = 0
    try:
        latest = db["hospital_pharmacyitem"].find_one(
            {"item_id": {"$type": "number"}},
            sort=[("item_id", -1)],
            projection={"item_id": 1}
        )
        if latest and latest.get("item_id") is not None:
            max_id = max(max_id, int(latest["item_id"]))
    except Exception:
        pass
    try:
        for doc in db["hospital_pharmacyitem"].find({"item_id": {"$type": "string"}}, {"item_id": 1}):
            try:
                max_id = max(max_id, int(doc["item_id"]))
            except Exception:
                pass
    except Exception:
        pass
    return max_id


def _resolve_seed_vendor(db):
    """Finds maximum vendor_id for Vendor."""
    max_v = 0
    try:
        for v in db["hospital_vendor"].find({}, {"vendor_id": 1}):
            try:
                vid = int(v.get("vendor_id", 0))
                if vid > max_v:
                    max_v = vid
            except Exception:
                pass
    except Exception:
        pass
    return max_v


def _resolve_seed_pharmacy_category(db):
    """Finds maximum category_id for PharmacyCategory."""
    max_cat = 0
    try:
        for c in db["hospital_pharmacycategory"].find({}, {"category_id": 1}):
            try:
                cid = int(c.get("category_id", 0))
                if cid > max_cat:
                    max_cat = cid
            except Exception:
                pass
    except Exception:
        pass
    return max_cat


def _resolve_seed_chemical_composition(db):
    """Finds maximum composition_id for ChemicalComposition."""
    max_comp = 0
    try:
        for c in db["hospital_chemicalcomposition"].find({}, {"composition_id": 1}):
            try:
                cid = int(c.get("composition_id", 0))
                if cid > max_comp:
                    max_comp = cid
            except Exception:
                pass
    except Exception:
        pass
    return max_comp


def _resolve_seed_grn_draft(db, fy):
    """Finds maximum sequential draft number for GRN Draft under financial year."""
    max_draft = 0
    try:
        cursor = db["hospital_grn"].find(
            {"draft_number": {"$regex": f"^DRAFT/{re.escape(fy)}/"}},
            {"draft_number": 1}
        )
        for doc in cursor:
            s = str(doc.get("draft_number") or "").split("/")[-1]
            try:
                n = int(s)
                if n > max_draft:
                    max_draft = n
            except Exception:
                pass
    except Exception:
        pass
    return max_draft


def _resolve_seed_room_category(db):
    max_id = 0
    try:
        for r in db["hospital_roomcategory"].find({}, {"room_category_id": 1}):
            try:
                rid = int(r.get("room_category_id", 0))
                if rid > max_id:
                    max_id = rid
            except Exception:
                pass
    except Exception:
        pass
    return max_id


def _resolve_seed_block(db):
    max_id = 0
    try:
        for b in db["hospital_block"].find({}, {"block_id": 1}):
            try:
                bid = int(b.get("block_id", 0))
                if bid > max_id:
                    max_id = bid
            except Exception:
                pass
    except Exception:
        pass
    return max_id


def _resolve_seed_ward(db):
    max_id = 0
    try:
        for w in db["hospital_nursingstation"].find({}, {"ward_id": 1}):
            try:
                wid = int(w.get("ward_id", 0))
                if wid > max_id:
                    max_id = wid
            except Exception:
                pass
    except Exception:
        pass
    return max_id


def _resolve_seed_room_service_description(db):
    max_id = 0
    try:
        for d in db["hospital_roomservicedescription"].find({}, {"description_id": 1}):
            try:
                did = int(d.get("description_id", 0))
                if did > max_id:
                    max_id = did
            except Exception:
                pass
    except Exception:
        pass
    return max_id


def _resolve_seed_room_kit(db):
    max_id = 0
    try:
        for k in db["hospital_roomkititems"].find({}, {"kit_id": 1}):
            try:
                kid = int(k.get("kit_id", 0))
                if kid > max_id:
                    max_id = kid
            except Exception:
                pass
    except Exception:
        pass
    return max_id


def _resolve_seed_medicine_ward_request(db, prefix):
    """Finds maximum sequence for medicine ward request prefix (e.g. MRIP or MROP)."""
    max_num = 0
    try:
        cursor = db["hospital_pharmacybilling"].find(
            {"$or": [
                {"request_no": {"$regex": f"^{re.escape(prefix)}"}},
                {"bill_no": {"$regex": f"^{re.escape(prefix)}"}}
            ]},
            {"request_no": 1, "bill_no": 1}
        )
        for doc in cursor:
            raw = str(doc.get("request_no") or doc.get("bill_no") or "").strip()
            digits = re.findall(r'\d+', raw.replace(prefix, ""))
            if digits:
                try:
                    num = int(digits[0])
                    if num > max_num:
                        max_num = num
                except Exception:
                    pass
    except Exception:
        pass
    return max_num


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
    If the counter document exists, strictly returns current seq + 1 without side-effects.
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
    - If the counter already exists, it strictly increments seq by 1 via atomic $inc.
    - Never overrides or resets the sequence set by administrators or users.
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
    """Read-only preview of next IP number (e.g. 'S026/008225' or 'SD26/000001') without consuming a sequence."""
    p = prefix or _current_admission_prefix(is_daycare=is_daycare)
    counter_name = f"admission_ip_{p}"
    seq = peek_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_admission_ip(db, p),
        db_instance=db_instance,
    )
    return f"{p}/{seq:06d}"


def get_next_admission_ip(prefix=None, db_instance=None, is_daycare=False):
    """Returns next sequential IP number, e.g. 'S026/008225' or 'SD26/000001'."""
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
    """Returns next sequential IP Advance bill number, e.g. '2627003004'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"ip_advance_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_advance_bill(db, year_prefix)
    )
    return f"{year_prefix}{seq:06d}"


def get_next_advance_refund_bill_no(fy=None):
    """Returns next sequential IP Advance Refund bill number, e.g. '2627000004'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"ip_refund_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_advance_refund(db, year_prefix)
    )
    return f"{year_prefix}{seq:06d}"


# 3. Discharge Billing Bill Number
def get_next_discharge_bill_no(fy=None):
    """Returns next sequential Discharge bill number, e.g. '2627008125'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"discharge_bill_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_discharge_bill(db, year_prefix)
    )
    return f"{year_prefix}{seq:06d}"


def get_next_discharge_estimate_no(fy=None):
    """Returns next sequential Discharge estimate number, e.g. 'EST/2627/000001'."""
    year_prefix = fy or _current_fin_year_prefix()
    counter_name = f"discharge_estimate_{year_prefix}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_discharge_estimate(db, year_prefix)
    )
    return f"EST/{year_prefix}/{seq:06d}"


# 4. Inventory Module IDs
def get_next_pharmacy_item_id():
    """Returns next integer item_id for PharmacyItem."""
    return get_next_sequence_value(
        "inventory_pharmacy_item_id",
        seed_resolver=_resolve_seed_pharmacy_item
    )


def get_next_vendor_id():
    """Returns next vendor_id as string, e.g. '838'."""
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
    """Returns next sequential GRN draft number, e.g. 'DRAFT/2627/02043'."""
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


# 6. Pharmacy Billing Bill Number & Primary Key Bill_id
def get_next_pharmacy_bill_id(db_instance=None):
    """
    Returns the next strictly unique, collision-free integer Bill_id for PharmacyBilling.
    Thread-safe and atomic across all billing and ward request workflows.

    Guarantees:
    1. Uses MongoDB 'counters' collection (_id: 'pharmacy_billing_bill_id') with atomic $inc.
    2. Self-healing synchronization: if 'seq' in counters ever lags behind the true
       maximum Bill_id in 'hospital_pharmacybilling', it immediately synchronizes
       and jumps past the maximum existing Bill_id.
    3. Collision check: verifies against 'hospital_pharmacybilling' that the candidate
       Bill_id does NOT already exist. If any document exists (e.g. from legacy or direct inserts),
       it advances the counter until an unused, strictly unique Bill_id is secured.
    """
    should_close = False
    if db_instance is not None:
        db = db_instance
    else:
        client, db = _get_db()
        should_close = True

    try:
        counters = db["counters"]
        pharm_col = db["hospital_pharmacybilling"]

        # Atomic increment
        doc = counters.find_one_and_update(
            {"_id": "pharmacy_billing_bill_id"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        candidate = int(doc.get("seq", 1))

        # Check for collision against actual hospital_pharmacybilling collection
        if pharm_col.find_one({"Bill_id": {"$in": [candidate, int(candidate)]}}, {"_id": 1}) is not None:
            # Collision detected! Find the true maximum Bill_id in collection
            max_doc = pharm_col.find_one(
                {"Bill_id": {"$ne": None}},
                sort=[("Bill_id", -1)],
                projection={"Bill_id": 1}
            )
            true_max = int(max_doc["Bill_id"]) if (max_doc and max_doc.get("Bill_id") is not None) else candidate
            target = max(candidate, true_max) + 1

            # Advance counter atomically to target
            counters.update_one(
                {"_id": "pharmacy_billing_bill_id"},
                {"$max": {"seq": target}}
            )

            # Skip any sparse scattered IDs ahead
            while pharm_col.find_one({"Bill_id": {"$in": [target, int(target)]}}, {"_id": 1}) is not None:
                target += 1
                counters.update_one(
                    {"_id": "pharmacy_billing_bill_id"},
                    {"$max": {"seq": target}}
                )

            # Ensure counter seq is updated to target
            counters.update_one(
                {"_id": "pharmacy_billing_bill_id"},
                {"$max": {"seq": target}}
            )
            return target

        return candidate
    finally:
        if should_close:
            try:
                client.close()
            except Exception:
                pass


def peek_next_pharmacy_bill_id(db_instance=None):
    """Read-only preview of the next candidate Bill_id without consuming a sequence."""
    should_close = False
    if db_instance is not None:
        db = db_instance
    else:
        client, db = _get_db()
        should_close = True

    try:
        counters = db["counters"]
        pharm_col = db["hospital_pharmacybilling"]
        existing = counters.find_one({"_id": "pharmacy_billing_bill_id"})
        seq = int(existing["seq"]) if (existing and "seq" in existing) else 0

        max_doc = pharm_col.find_one(
            {"Bill_id": {"$ne": None}},
            sort=[("Bill_id", -1)],
            projection={"Bill_id": 1}
        )
        true_max = int(max_doc["Bill_id"]) if (max_doc and max_doc.get("Bill_id") is not None) else 0
        candidate = max(seq, true_max) + 1
        return candidate
    finally:
        if should_close:
            try:
                client.close()
            except Exception:
                pass


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


# 8. Medicine Ward Request Number (MRIP / MROP)
def get_next_medicine_ward_request_no(is_ip=True, prefix=None, db_instance=None):
    """
    Returns next sequential Medicine Ward Request number:
    e.g. 'MRIP001', 'MRIP002' for IP; 'MROP001', 'MROP002' for OP.
    Thread-safe and atomic via MongoDB 'counters' collection.
    """
    if not prefix:
        prefix = "MRIP" if is_ip else "MROP"
    clean_prefix = str(prefix).strip().upper()
    counter_name = f"medicine_ward_request_{clean_prefix.lower()}"
    seq = get_next_sequence_value(
        counter_name,
        seed_resolver=lambda db: _resolve_seed_medicine_ward_request(db, clean_prefix),
        db_instance=db_instance
    )
    return f"{clean_prefix}{seq:03d}"


# 9. Estimate Billing / Ward Request EstBillNo (e.g. '000778')
def _resolve_seed_est_bill(db):
    """Finds the true maximum numeric EstBillNo across hospital_estimatebilling and ORM."""
    max_num = 0
    try:
        cursor = db["hospital_estimatebilling"].find(
            {"EstBillNo": {"$regex": "^[0-9]+$"}},
            {"EstBillNo": 1}
        )
        for doc in cursor:
            raw = str(doc.get("EstBillNo") or "").strip()
            if raw.isdigit():
                val = int(raw)
                if val > max_num:
                    max_num = val
    except Exception:
        pass

    try:
        from hospital.models import EstimateBilling
        for raw in EstimateBilling.objects.values_list("EstBillNo", flat=True):
            s = str(raw or "").strip()
            if s.isdigit():
                val = int(s)
                if val > max_num:
                    max_num = val
    except Exception:
        pass

    return max_num


def get_next_est_bill_no(db_instance=None):
    """
    Returns the next strictly unique, zero-padded 6-digit EstBillNo (e.g. '000778').
    Thread-safe and collision-free via MongoDB 'counters' atomic $inc plus collision advancement.
    """
    should_close = False
    if db_instance is not None:
        db = db_instance
    else:
        client, db = _get_db()
        should_close = True

    try:
        counters = db["counters"]
        est_col = db["hospital_estimatebilling"]
        counter_name = "estimate_billing_est_bill_no"

        candidate = int(get_next_sequence_value(
            counter_name,
            seed_resolver=_resolve_seed_est_bill,
            db_instance=db
        ))
        est_bill_no = f"{candidate:06d}"

        while est_col.find_one({"EstBillNo": est_bill_no}, {"_id": 1}) is not None:
            candidate += 1
            est_bill_no = f"{candidate:06d}"
            counters.update_one(
                {"_id": counter_name},
                {"$max": {"seq": candidate}}
            )

        counters.update_one(
            {"_id": counter_name},
            {"$max": {"seq": candidate}}
        )
        return est_bill_no
    finally:
        if should_close:
            try:
                client.close()
            except Exception:
                pass

