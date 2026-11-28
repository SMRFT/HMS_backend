"""
Shared idempotency lock and duplicate-submission prevention helpers for Ward Requests
(Lab, Radiology, Medicine, Implant).

Provides:
1. Atomic `client_request_id` idempotency guard backed by MongoDB `hospital_ward_request_idempotency`
   with a 24h TTL index — eliminates millisecond multi-click and network-retry race conditions.
2. Content + time-window duplicate check:
   - Auto-suppresses identical requests within `auto_suppress_seconds` (default 60s).
   - Optionally warns (HTTP 409 with `duplicate_warning: True`) if an identical active pending
     request was already raised earlier the same IST day (`> 60s`), unless `force_duplicate=True`.
"""

import json
import time
from datetime import datetime, timedelta
import pytz
from pymongo import ReturnDocument
from rest_framework.response import Response

_IDEMPOTENCY_COLL = "hospital_ward_request_idempotency"
_TTL_SECONDS = 86400  # 24 hours
_ttl_index_ready = False

_IST = pytz.timezone("Asia/Kolkata")


def _ensure_ttl_index(db):
    global _ttl_index_ready
    if _ttl_index_ready:
        return
    try:
        db[_IDEMPOTENCY_COLL].create_index(
            "created_at",
            expireAfterSeconds=_TTL_SECONDS,
            background=True,
        )
        _ttl_index_ready = True
    except Exception:
        pass


def _to_naive_utc(dt_val):
    if not dt_val or not isinstance(dt_val, datetime):
        return None
    if dt_val.tzinfo is not None:
        return dt_val.astimezone(pytz.UTC).replace(tzinfo=None)
    return dt_val


def _format_ist_time(dt_val):
    dt_utc = _to_naive_utc(dt_val)
    if not dt_utc:
        return ""
    return pytz.UTC.localize(dt_utc).astimezone(_IST).strftime("%d/%m/%Y %I:%M:%S %p")


def _parse_items_list(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return raw if isinstance(raw, list) else []


def canonical_item_signature(
    items,
    id_keys=("test_id", "item_id"),
    name_key="itemName",
    qty_keys=("quantity", "qty"),
):
    """Produces a stable sorted JSON string representing the requested item/test set."""
    normalized = []
    for it in _parse_items_list(items):
        if not isinstance(it, dict):
            continue
        ident = ""
        for k in id_keys:
            val = it.get(k)
            if val not in (None, ""):
                ident = str(val).strip()
                break
        if not ident and name_key:
            ident = str(it.get(name_key) or it.get("name") or "").strip().lower()
        qty_val = 1.0
        for qk in qty_keys:
            qv = it.get(qk)
            if qv not in (None, ""):
                try:
                    qty_val = float(qv)
                except (ValueError, TypeError):
                    qty_val = 1.0
                break
        btn = str(it.get("billTypeNo") or "").strip()
        if ident:
            normalized.append((ident, btn, round(qty_val, 3)))
    normalized.sort()
    return json.dumps(normalized)


def _claim_idempotency_key(db, lock_key, req_type, uhid):
    """
    Atomically acquires `lock_key` in MongoDB.
    Returns (claimed_bool, existing_doc_if_not_claimed).
    """
    _ensure_ttl_index(db)
    coll = db[_IDEMPOTENCY_COLL]
    now_utc = datetime.utcnow()

    existing = coll.find_one_and_update(
        {"_id": lock_key},
        {
            "$setOnInsert": {
                "status": "processing",
                "req_type": req_type,
                "uhid": uhid,
                "created_at": now_utc,
            }
        },
        upsert=True,
        return_document=ReturnDocument.BEFORE,
    )
    if existing is None:
        return True, None

    if existing.get("status") == "failed":
        reclaimed = coll.find_one_and_update(
            {"_id": lock_key, "status": "failed"},
            {"$set": {"status": "processing", "created_at": now_utc}},
            return_document=ReturnDocument.AFTER,
        )
        if reclaimed is not None:
            return True, None
        existing = coll.find_one({"_id": lock_key}) or existing

    # Wait briefly if another worker is mid-flight so multi-click receives clean result
    if existing.get("status") == "processing":
        for _ in range(6):
            time.sleep(0.15)
            refreshed = coll.find_one({"_id": lock_key})
            if not refreshed:
                break
            if refreshed.get("status") in ("completed", "failed"):
                existing = refreshed
                break

    return False, existing


def complete_ward_request_guard(db, lock_key, response_payload):
    if not lock_key or db is None:
        return
    try:
        db[_IDEMPOTENCY_COLL].update_one(
            {"_id": lock_key},
            {
                "$set": {
                    "status": "completed",
                    "response_payload": response_payload,
                    "completed_at": datetime.utcnow(),
                }
            },
        )
    except Exception:
        pass


def fail_ward_request_guard(db, lock_key):
    if not lock_key or db is None:
        return
    try:
        db[_IDEMPOTENCY_COLL].delete_one({"_id": lock_key, "status": "processing"})
    except Exception:
        pass


def acquire_ward_request_guard(
    db,
    *,
    req_type,
    client_request_id="",
    uhid="",
    ip_number="",
    bill_type_no="",
    signature="",
    force_duplicate=False,
    auto_suppress_seconds=60,
    check_same_day_warning=False,
    collection_specs=None,
):
    """
    Checks idempotency and recent duplicate submissions before creating a new ward request.

    Returns (proceed: bool, early_response: Response | None, lock_key: str | None)
    If `proceed` is False, the caller MUST return `early_response` immediately.
    If `proceed` is True, the caller MUST call either `complete_ward_request_guard(db, lock_key, payload)`
    on success or `fail_ward_request_guard(db, lock_key)` on failure.
    """
    clean_cid = str(client_request_id or "").strip()
    lock_key = f"{req_type}:{clean_cid}" if clean_cid else None

    if lock_key:
        claimed, existing = _claim_idempotency_key(db, lock_key, req_type, uhid)
        if not claimed:
            if existing and existing.get("status") == "completed" and existing.get("response_payload"):
                payload = dict(existing["response_payload"])
                payload["duplicate_suppressed"] = True
                return False, Response(payload, status=200), None
            return (
                False,
                Response(
                    {
                        "success": False,
                        "in_progress": True,
                        "error": "Request is already being saved. Please wait a moment.",
                    },
                    status=409,
                ),
                None,
            )

    # Layer 2: Recent duplicate & same-day pending check
    if uhid and signature and collection_specs and not force_duplicate:
        now_utc = datetime.utcnow()
        now_ist = datetime.now(_IST)
        ist_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_utc = ist_midnight.astimezone(pytz.UTC).replace(tzinfo=None)
        suppress_cutoff_utc = now_utc - timedelta(seconds=auto_suppress_seconds)

        query_since = day_start_utc if check_same_day_warning else suppress_cutoff_utc

        for spec in collection_specs:
            coll_name = spec["collection"]
            items_field = spec.get("items_field", "item")
            date_field = spec.get("date_field", "created_date")
            bill_fields = spec.get("bill_fields", ("EstBillNo", "investBillNo"))
            pending_statuses = set(spec.get("pending_statuses", ("Result Pending", "Pending", "")))

            base_q = {
                "uhid": uhid,
                "is_active": {"$nin": [False, 0, "false", "False"]},
                "is_deleted": {"$ne": True},
                "status": {"$nin": ["Cancelled", "Deleted"]},
                date_field: {"$gte": query_since},
            }
            if ip_number and ip_number not in ("-", "None", "null"):
                ip_field = spec.get("ip_field", "ipNumber")
                base_q[ip_field] = ip_number
            if spec.get("extra_query"):
                base_q.update(spec["extra_query"])

            id_keys = spec.get("id_keys", ("test_id", "item_id"))
            qty_keys = spec.get("qty_keys", ("quantity", "qty"))

            candidates = list(db[coll_name].find(base_q).sort(date_field, -1).limit(25))
            for cand in candidates:
                cand_sig = canonical_item_signature(
                    cand.get(items_field),
                    id_keys=id_keys,
                    qty_keys=qty_keys,
                )
                if cand_sig != signature:
                    continue

                if bill_type_no and cand.get("billTypeNo") and str(cand.get("billTypeNo")).strip() != bill_type_no:
                    continue

                cand_dt = _to_naive_utc(cand.get(date_field) or cand.get("created_date"))
                if not cand_dt:
                    continue

                bill_val = ""
                for bf in bill_fields:
                    if cand.get(bf):
                        bill_val = str(cand.get(bf)).strip()
                        break
                bill_id = str(cand.get(spec.get("pk_field", "_id")))

                if cand_dt >= suppress_cutoff_utc:
                    resp_payload = spec["build_suppressed_payload"](cand, bill_val, bill_id)
                    resp_payload["duplicate_suppressed"] = True
                    if lock_key:
                        complete_ward_request_guard(db, lock_key, resp_payload)
                    return False, Response(resp_payload, status=200), None

                cand_status = str(cand.get("status") or cand.get("billing_status") or "").strip()
                if check_same_day_warning and cand_status in pending_statuses:
                    fail_ward_request_guard(db, lock_key)
                    existing_time = _format_ist_time(cand_dt)
                    return (
                        False,
                        Response(
                            {
                                "success": False,
                                "duplicate_warning": True,
                                "existing_bill_no": bill_val,
                                "existing_time": existing_time,
                                "error": (
                                    f"Same item(s) already requested today in Ref #{bill_val or bill_id} "
                                    f"at {existing_time} (Status: {cand_status or 'Pending'}). "
                                    "Do you still want to raise another request?"
                                ),
                            },
                            status=409,
                        ),
                        None,
                    )

    return True, None, lock_key
