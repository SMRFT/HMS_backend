from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from pyauth.auth import HasRoleAndDataPermission
from datetime import datetime
from bson import ObjectId
import os
import logging
from ..models import PharmacyItem  

logger = logging.getLogger(__name__)



# ── DB helpers ────────────────────────────────────────────────────────────────

def get_hms_db():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    return client, client["HMS"]


def serialize_doc(doc):
    """Convert ObjectId fields to strings so they are JSON-serialisable."""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _next_package_id(collection):
    """
    Auto-increment medPackage_id.
    Reads the largest existing numeric id and returns max + 1.
    Falls back to 1 if the collection is empty.
    """
    last = collection.find_one(
        {"medPackage_id": {"$exists": True}},
        sort=[("medPackage_id", -1)],
    )
    if last and isinstance(last.get("medPackage_id"), int):
        return last["medPackage_id"] + 1
    return 1


# ════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _sanitize_items(raw_items):
    clean = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("item_id"))
        except (TypeError, ValueError):
            continue

        try:
            obj = PharmacyItem.objects.filter(item_id=item_id).values("item_name").first()
            item_name = obj["item_name"] if obj else ""
        except Exception:
            item_name = ""

        try:
            qty = int(item.get("qty", 1))
            if qty < 1:
                qty = 1
        except (TypeError, ValueError):
            qty = 1

        clean.append({
            "item_id":   item_id,
            "item_name": item_name,
            "qty":       qty,        # ← stored in DB
        })
    return clean

# ════════════════════════════════════════════════════════════════════════════
#  LIST
# ════════════════════════════════════════════════════════════════════════════

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_medicine_packages(request):
    """
    Return all active medicine packages.

    Optional query params:
        ?search=<term>   — case-insensitive search on medPackage_name
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db["hospital_medicine_package"]

        query = {"is_active": True}

        search = request.query_params.get("search", "").strip()
        if search:
            query["medPackage_name"] = {"$regex": search, "$options": "i"}

        projection = {
            "_id": 1,
            "medPackage_id": 1,
            "medPackage_name": 1,
            "branch_code": 1,
            "outlet_code": 1,
            "hospital_code": 1,
            "items": 1,
            "is_active": 1,
            "created_date": 1,
            "lastmodified_date": 1,
        }

        packages = [serialize_doc(p) for p in collection.find(query, projection)]
        return Response({"packages": packages}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_medicine_packages failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ════════════════════════════════════════════════════════════════════════════
#  CREATE
# ════════════════════════════════════════════════════════════════════════════

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def create_medicine_package(request):
    """
    Create a new medicine package.

    Required payload fields:
        medPackage_name  (str)
        items            (list of {item_id, item_name})

    Optional:
        branch_code, outlet_code, hospital_code, is_active
    """
    client = None
    try:
        client, db = get_hms_db()
        collection = db["hospital_medicine_package"]

        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        created_by    = data.pop("auth-user-id",       "system")
        branch_code   = data.get("auth-branch-code",   "")
        hospital_code = data.get("auth-hospital-code", "")

        # strip all auth-* keys
        data = {k: v for k, v in data.items() if not k.startswith("auth-")}

        # ── Validation ───────────────────────────────────────────────────
        errors = {}
        if not str(data.get("medPackage_name", "")).strip():
            errors["medPackage_name"] = "Package name is required."

        raw_items = data.get("items", [])
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            errors["items"] = "At least one medicine item is required."

        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        sanitized_items = _sanitize_items(raw_items)
        if not sanitized_items:
            return Response(
                {"items": "No valid items found. Each item must have a numeric item_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        next_id = _next_package_id(collection)

        doc = {
            "medPackage_id":   next_id,
            "medPackage_name": str(data["medPackage_name"]).strip(),
            "branch_code":   branch_code,
            "outlet_code":   "OLET001",
            "hospital_code": hospital_code,
            "items":           sanitized_items,
            "is_active":       bool(data.get("is_active", True)),
            "created_by":      created_by,
            "created_date":    datetime.utcnow(),
            "lastmodified_by": created_by,
            "lastmodified_date": datetime.utcnow(),
        }

        result = collection.insert_one(doc)

        return Response(
            {
                "message":       "Medicine package created successfully.",
                "medPackage_id": next_id,
                "_id":           str(result.inserted_id),
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        logger.exception("create_medicine_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ════════════════════════════════════════════════════════════════════════════
#  RETRIEVE (single)
# ════════════════════════════════════════════════════════════════════════════

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_medicine_package(request, pkg_id):
    """Retrieve a single active medicine package by medPackage_id."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db["hospital_medicine_package"]

        doc = collection.find_one({"medPackage_id": int(pkg_id), "is_active": True})
        if not doc:
            return Response({"error": "Medicine package not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(serialize_doc(doc), status=status.HTTP_200_OK)

    except (ValueError, TypeError):
        return Response({"error": "Invalid package ID."}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("get_medicine_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ════════════════════════════════════════════════════════════════════════════
#  UPDATE
# ════════════════════════════════════════════════════════════════════════════

@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
def update_medicine_package(request, pkg_id):
    client = None
    try:
        client, db = get_hms_db()
        collection = db["hospital_medicine_package"]

        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        modified_by = data.pop("auth-user-id", "system")

        # Strip immutable, auth, and location fields — never update these
        immutable = {
            "_id", "medPackage_id", "created_by", "created_date",
            "branch_code", "outlet_code", "hospital_code",   # ← added
        }
        data = {
            k: v
            for k, v in data.items()
            if k not in immutable and not k.startswith("auth-")
        }

        # validate name if provided
        if "medPackage_name" in data and not str(data["medPackage_name"]).strip():
            return Response(
                {"medPackage_name": "Package name cannot be blank."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # validate + sanitize items if provided
        if "items" in data:
            if not isinstance(data["items"], list) or len(data["items"]) == 0:
                return Response(
                    {"items": "At least one medicine item is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            sanitized = _sanitize_items(data["items"])
            if not sanitized:
                return Response(
                    {"items": "No valid items found. Each item must have a numeric item_id."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            data["items"] = sanitized

        data["lastmodified_by"]   = modified_by
        data["lastmodified_date"] = datetime.utcnow()

        result = collection.update_one(
            {"medPackage_id": int(pkg_id), "is_active": True},
            {"$set": data},
        )

        if result.matched_count == 0:
            return Response(
                {"error": "Medicine package not found or already deleted."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"message": "Medicine package updated successfully."}, status=status.HTTP_200_OK)

    except (ValueError, TypeError):
        return Response({"error": "Invalid package ID."}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("update_medicine_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ════════════════════════════════════════════════════════════════════════════
#  SOFT DELETE
# ════════════════════════════════════════════════════════════════════════════

@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
def delete_medicine_package(request, pkg_id):
    """Soft-delete: sets is_active=False."""
    client = None
    try:
        client, db = get_hms_db()
        collection = db["hospital_medicine_package"]

        deleted_by = request.data.get("auth-user-id", "system")

        result = collection.update_one(
            {"medPackage_id": int(pkg_id), "is_active": True},
            {
                "$set": {
                    "is_active":    False,
                    "deleted_by":   deleted_by,
                    "deleted_date": datetime.utcnow(),
                }
            },
        )

        if result.matched_count == 0:
            return Response(
                {"error": "Medicine package not found or already deleted."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"message": "Medicine package deleted successfully."}, status=status.HTTP_200_OK)

    except (ValueError, TypeError):
        return Response({"error": "Invalid package ID."}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("delete_medicine_package failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


# ════════════════════════════════════════════════════════════════════════════
#  PHARMACY ITEMS (read from Django ORM → PharmacyItem)
# ════════════════════════════════════════════════════════════════════════════

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_items(request):
    """   
    Supports query params:
        ?is_active=true        (default true)
        ?search=<term>         (case-insensitive search on item_name)

    Response shape:
        { "items": [ { "item_id": int, "item_name": str }, ... ] }
    """
    try:
        is_active_param = request.query_params.get("is_active", "true").lower()
        is_active = is_active_param not in ("false", "0", "no")

        qs = PharmacyItem.objects.filter(
            is_active=is_active,
        ).values("item_id", "item_name")

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(item_name__icontains=search)

        items = [
            {"item_id": row["item_id"], "item_name": row["item_name"]}
            for row in qs.order_by("item_name")
        ]

        return Response({"items": items}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("get_pharmacy_items failed")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)