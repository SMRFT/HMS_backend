import os
from datetime import datetime
from bson import ObjectId
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse
from pyauth.auth import HasRoleAndDataPermission
from .mongo_utils import get_hms_db

INSURANCE_SCHEMES = [
    {
        "id": "cghs",
        "name": "CGHS",
        "description": "Central Government Health Scheme Packages",
        "collection": "hospital_insurance_packages_cghs",
    },
    {
        "id": "cm_scheme",
        "name": "CM Scheme",
        "description": "Chief Minister's Comprehensive Health Insurance Scheme",
        "collection": "hospital_insurance_packages_cm_scheme",
    },
    {
        "id": "echs",
        "name": "ECHS",
        "description": "Ex-Servicemen Contributory Health Scheme",
        "collection": "hospital_insurance_packages_echs",
    },
    {
        "id": "general_gipsa",
        "name": "General GIPSA",
        "description": "General Insurance Public Sector Association Packages",
        "collection": "hospital_insurance_packages_general_gipsa",
    },
    {
        "id": "implants_and_specified",
        "name": "Implants and Specified",
        "description": "Implants, High-End Procedures & Specified Packages",
        "collection": "hospital_insurance_packages_implants_and_specified",
    },
    {
        "id": "nhis",
        "name": "NHIS",
        "description": "New Health Insurance Scheme Packages",
        "collection": "hospital_insurance_packages_nhis",
    },
    {
        "id": "railway_cghs_esi_esic",
        "name": "Railway / CGHS / ESI / ESIC",
        "description": "Railway, CGHS, ESI, ESIC Integrated Package Rates",
        "collection": "hospital_insurance_packages_railway_cghs_esi_esic",
    },
]

SCHEME_LOOKUP = {s["id"]: s for s in INSURANCE_SCHEMES}
for s in INSURANCE_SCHEMES:
    SCHEME_LOOKUP[s["collection"]] = s
    SCHEME_LOOKUP[s["name"].lower().replace(" ", "_")] = s

SYSTEM_KEYS = {"_id", "id", "scheme", "scheme_id"}


def _safe_float(val, default=0.0):
    if val is None or val == "":
        return default
    try:
        if hasattr(val, "to_decimal"):
            return float(val.to_decimal())
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def _resolve_scheme(scheme_param):
    if not scheme_param:
        return None
    param_clean = str(scheme_param).strip().lower()
    meta = SCHEME_LOOKUP.get(param_clean)
    if not meta:
        for k, v in SCHEME_LOOKUP.items():
            if param_clean in k or k in param_clean:
                return v
    return meta


def _find_item_across_schemes(db, item_id, preferred_scheme=None):
    """
    Finds a document by ObjectId across insurance package collections.
    Returns (collection, scheme_meta, document, object_id) or (None, None, None, None).
    """
    try:
        obj_id = ObjectId(item_id)
    except Exception:
        return None, None, None, None

    if preferred_scheme:
        scheme_meta = _resolve_scheme(preferred_scheme)
        if scheme_meta:
            coll = db[scheme_meta["collection"]]
            doc = coll.find_one({"_id": obj_id})
            if doc:
                return coll, scheme_meta, doc, obj_id

    for s in INSURANCE_SCHEMES:
        coll = db[s["collection"]]
        doc = coll.find_one({"_id": obj_id})
        if doc:
            return coll, s, doc, obj_id

    return None, None, None, obj_id


def _format_item(it, scheme_id="", scheme_name=""):
    """
    Formats item ensuring all existing and newly added fields in the DB collection
    are preserved and returned.
    """
    nabh_rate = _safe_float(it.get("nabh_rate"))
    non_nabh_rate = _safe_float(it.get("non_nabh_rate"))
    primary_rate = nabh_rate if nabh_rate > 0 else non_nabh_rate

    # If is_active is explicitly False, item is inactive; otherwise default to True
    is_active = False if it.get("is_active") is False else True

    item_dict = {
        "id": str(it.get("_id")) if "_id" in it else "",
        "_id": str(it.get("_id")) if "_id" in it else "",
        "sl_no": it.get("sl_no"),
        "name": it.get("name", ""),
        "itemName": it.get("name", ""),
        "nabh_code": it.get("nabh_code", ""),
        "category": it.get("category", ""),
        "department": it.get("department", ""),
        "nabh_rate": nabh_rate,
        "non_nabh_rate": non_nabh_rate,
        "price": str(primary_rate),
        "rate": primary_rate,
        "package_name": scheme_name or it.get("package_name", ""),
        "scheme_id": scheme_id or it.get("scheme_id", ""),
        "is_active": is_active,
        "created_at": it.get("created_at"),
        "updated_at": it.get("updated_at"),
    }

    # Pass through any other fields present in the DB document
    for k, v in it.items():
        if k not in item_dict and k != "_id":
            item_dict[k] = v

    return item_dict


# ─────────────────────────────────────────────────────────────────────────────
# 1. Scheme List with Active/Inactive Counts
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_insurance_package_schemes(request):
    """
    Returns the list of available insurance package schemes along with document counts:
    total items, active items (is_active != False), and inactive items (is_active == False).
    """
    try:
        _, db = get_hms_db()
        schemes_with_counts = []
        for s in INSURANCE_SCHEMES:
            coll_name = s["collection"]
            coll = db[coll_name]
            try:
                total_count = coll.count_documents({})
                inactive_count = coll.count_documents({"is_active": False})
                active_count = total_count - inactive_count
            except Exception:
                total_count = 0
                active_count = 0
                inactive_count = 0

            schemes_with_counts.append({
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "collection": s["collection"],
                "total_items": total_count,
                "active_items": active_count,
                "inactive_items": inactive_count,
            })
        return Response({
            "success": True,
            "schemes": schemes_with_counts,
            "total": len(schemes_with_counts),
        })
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Package Items: List & Create
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def insurance_package_items_list_create(request):
    """
    GET:
      Fetch items from a scheme collection.
      Query params:
        - scheme: scheme id or collection name (default: cghs)
        - status: 'active', 'inactive', or 'all'
        - is_active: 'true' or 'false'
        - search / itemName / q: text query
        - category: category filter
        - page, page_size: optional pagination for large lists
        - limit: optional max items

    POST:
      Create a new insurance package item with all provided fields.
      Body:
        - scheme: scheme id or collection name (required)
        - name: item / procedure name (required)
        - nabh_code, category, department: optional
        - nabh_rate, non_nabh_rate: numbers
        - is_active: boolean (default True)
        - ANY other custom fields are dynamically stored in the DB document.
    """
    try:
        _, db = get_hms_db()

        # ─── POST: CREATE NEW ITEM ──────────────────────────────────────────
        if request.method == "POST":
            scheme_param = (
                request.data.get("scheme") or
                request.data.get("scheme_id") or
                request.GET.get("scheme") or
                ""
            ).strip()

            scheme_meta = _resolve_scheme(scheme_param)
            if not scheme_meta:
                return Response({
                    "success": False,
                    "error": f"Valid scheme is required. Schemes: {[s['id'] for s in INSURANCE_SCHEMES]}"
                }, status=status.HTTP_400_BAD_REQUEST)

            name = str(request.data.get("name") or request.data.get("itemName") or "").strip()
            if not name:
                return Response({
                    "success": False,
                    "error": "Package name / procedure name is required."
                }, status=status.HTTP_400_BAD_REQUEST)

            coll = db[scheme_meta["collection"]]

            # Determine next sl_no
            last_item = coll.find_one({}, sort=[("sl_no", -1)])
            next_sl_no = 1
            if last_item and isinstance(last_item.get("sl_no"), (int, float)):
                next_sl_no = int(last_item["sl_no"]) + 1
            else:
                next_sl_no = coll.count_documents({}) + 1

            raw_is_active = request.data.get("is_active", True)
            if isinstance(raw_is_active, str):
                is_active = raw_active = raw_is_active.lower() not in ("false", "0", "no")
            else:
                is_active = bool(raw_is_active)

            new_doc = {
                "sl_no": int(request.data.get("sl_no")) if str(request.data.get("sl_no", "")).isdigit() else next_sl_no,
                "name": name,
                "nabh_code": str(request.data.get("nabh_code", "")).strip(),
                "category": str(request.data.get("category", "")).strip(),
                "department": str(request.data.get("department", "")).strip(),
                "nabh_rate": _safe_float(request.data.get("nabh_rate", 0)),
                "non_nabh_rate": _safe_float(request.data.get("non_nabh_rate", 0)),
                "is_active": is_active,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            # Add ANY new/custom fields passed into the DB collection document
            for k, v in request.data.items():
                if k not in new_doc and k not in SYSTEM_KEYS:
                    new_doc[k] = v

            result = coll.insert_one(new_doc)
            new_doc["_id"] = result.inserted_id

            return Response({
                "success": True,
                "message": f"Insurance package added to {scheme_meta['name']} successfully.",
                "item": _format_item(new_doc, scheme_meta["id"], scheme_meta["name"]),
            }, status=status.HTTP_201_CREATED)

        # ─── GET: LIST ITEMS ────────────────────────────────────────────────
        scheme_param = request.GET.get("scheme", "").strip()
        if not scheme_param:
            return get_insurance_package_schemes(request._request)

        scheme_meta = _resolve_scheme(scheme_param)
        if not scheme_meta:
            return Response({
                "success": False,
                "error": f"Invalid scheme '{scheme_param}'. Valid schemes: {[s['id'] for s in INSURANCE_SCHEMES]}"
            }, status=status.HTTP_400_BAD_REQUEST)

        coll_name = scheme_meta["collection"]
        scheme_id = scheme_meta["id"]
        scheme_name = scheme_meta["name"]
        coll = db[coll_name]

        query = {}

        # Filter by is_active / status
        status_param = request.GET.get("status", "").strip().lower()
        is_active_param = request.GET.get("is_active", "").strip().lower()

        if status_param == "active" or is_active_param in ("true", "1"):
            query["is_active"] = {"$ne": False}
        elif status_param == "inactive" or is_active_param in ("false", "0"):
            query["is_active"] = False

        search_query = (
            request.GET.get("search") or
            request.GET.get("itemName") or
            request.GET.get("q") or
            ""
        ).strip()

        if search_query:
            query["$or"] = [
                {"name": {"$regex": search_query, "$options": "i"}},
                {"nabh_code": {"$regex": search_query, "$options": "i"}},
                {"category": {"$regex": search_query, "$options": "i"}},
                {"department": {"$regex": search_query, "$options": "i"}},
            ]

        category = request.GET.get("category", "").strip()
        if category:
            query["category"] = {"$regex": f"^{category}$", "$options": "i"}

        # Pagination support
        page_param = request.GET.get("page")
        page_size_param = request.GET.get("page_size") or request.GET.get("limit")

        if page_param and page_param.isdigit():
            page = max(1, int(page_param))
            page_size = int(page_size_param) if page_size_param and page_size_param.isdigit() else 50
            total_count = coll.count_documents(query)
            skip = (page - 1) * page_size
            cursor = coll.find(query).sort([("sl_no", 1), ("name", 1)]).skip(skip).limit(page_size)
            raw_items = list(cursor)
            total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 1

            formatted = [_format_item(it, scheme_id, scheme_name) for it in raw_items]
            return Response({
                "success": True,
                "scheme": scheme_id,
                "scheme_name": scheme_name,
                "collection": coll_name,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "items": formatted,
            })
        else:
            limit = int(page_size_param) if page_size_param and page_size_param.isdigit() else 0
            cursor = coll.find(query).sort([("sl_no", 1), ("name", 1)])
            if limit > 0:
                cursor = cursor.limit(limit)
            raw_items = list(cursor)
            formatted = [_format_item(it, scheme_id, scheme_name) for it in raw_items]
            return Response({
                "success": True,
                "scheme": scheme_id,
                "scheme_name": scheme_name,
                "collection": coll_name,
                "total": len(formatted),
                "items": formatted,
            })

    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Package Item Detail: GET, PUT (Edit), DELETE (Soft Delete)
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def insurance_package_item_detail(request, item_id):
    """
    GET: Retrieve package item detail.
    PUT / PATCH: Edit package item attributes and any new fields.
    DELETE: Soft delete by setting is_active = False in DB.
    """
    try:
        _, db = get_hms_db()
        scheme_param = request.GET.get("scheme") or request.data.get("scheme")
        coll, scheme_meta, doc, obj_id = _find_item_across_schemes(db, item_id, scheme_param)

        if not doc:
            return Response({
                "success": False,
                "error": f"Insurance package item with ID '{item_id}' not found."
            }, status=status.HTTP_404_NOT_FOUND)

        scheme_id = scheme_meta["id"] if scheme_meta else ""
        scheme_name = scheme_meta["name"] if scheme_meta else ""

        # ─── GET: DETAIL ────────────────────────────────────────────────────
        if request.method == "GET":
            return Response({
                "success": True,
                "item": _format_item(doc, scheme_id, scheme_name),
            })

        # ─── PUT / PATCH: EDIT (Dynamic updates including new fields) ───────
        if request.method in ("PUT", "PATCH"):
            update_data = {}

            # Process all provided fields dynamically
            for k, v in request.data.items():
                if k in SYSTEM_KEYS:
                    continue
                if k in ("nabh_rate", "non_nabh_rate"):
                    update_data[k] = _safe_float(v)
                elif k == "sl_no" and str(v).isdigit():
                    update_data[k] = int(v)
                elif k == "is_active":
                    if isinstance(v, str):
                        update_data[k] = v.lower() not in ("false", "0", "no")
                    else:
                        update_data[k] = bool(v)
                else:
                    update_data[k] = v

            update_data["updated_at"] = datetime.utcnow().isoformat()

            coll.update_one({"_id": obj_id}, {"$set": update_data})
            updated_doc = coll.find_one({"_id": obj_id})

            return Response({
                "success": True,
                "message": "Insurance package updated successfully.",
                "item": _format_item(updated_doc, scheme_id, scheme_name),
            })

        # ─── DELETE: SOFT DELETE (is_active = False in DB) ──────────────────
        if request.method == "DELETE":
            coll.update_one(
                {"_id": obj_id},
                {"$set": {"is_active": False, "updated_at": datetime.utcnow().isoformat()}}
            )
            return Response({
                "success": True,
                "message": "Insurance package deleted successfully (is_active: false).",
                "id": str(obj_id),
                "is_active": False,
            })

    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Toggle Active Status (is_active: True / False)
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def toggle_insurance_package_item_active(request, item_id):
    """
    Toggles or sets the is_active status of an insurance package item in DB.
    """
    try:
        _, db = get_hms_db()
        scheme_param = request.GET.get("scheme") or request.data.get("scheme")
        coll, scheme_meta, doc, obj_id = _find_item_across_schemes(db, item_id, scheme_param)

        if not doc:
            return Response({
                "success": False,
                "error": f"Insurance package item with ID '{item_id}' not found."
            }, status=status.HTTP_404_NOT_FOUND)

        if "is_active" in request.data:
            raw_active = request.data["is_active"]
            if isinstance(raw_active, str):
                new_status = raw_active.lower() not in ("false", "0", "no")
            else:
                new_status = bool(raw_active)
        else:
            current_active = False if doc.get("is_active") is False else True
            new_status = not current_active

        coll.update_one(
            {"_id": obj_id},
            {"$set": {"is_active": new_status, "updated_at": datetime.utcnow().isoformat()}}
        )

        scheme_id = scheme_meta["id"] if scheme_meta else ""
        scheme_name = scheme_meta["name"] if scheme_meta else ""

        return Response({
            "success": True,
            "message": f"Package status updated to {'active' if new_status else 'inactive'}.",
            "id": str(obj_id),
            "is_active": new_status,
            "scheme_id": scheme_id,
            "scheme_name": scheme_name,
        })
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Backward Compatible Aliases & Hub
# ─────────────────────────────────────────────────────────────────────────────
get_insurance_package_items = insurance_package_items_list_create


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def insurance_packages_hub(request):
    """
    Hub endpoint:
    - If ?scheme=... is provided, returns items for that scheme.
    - If no scheme is provided, returns all insurance package schemes.
    """
    if request.GET.get("scheme"):
        return insurance_package_items_list_create(request._request)
    return get_insurance_package_schemes(request._request)
