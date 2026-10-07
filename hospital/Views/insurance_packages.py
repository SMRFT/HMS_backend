import os
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
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


def _safe_float(val, default=0.0):
    if val is None or val == "":
        return default
    try:
        if hasattr(val, "to_decimal"):
            return float(val.to_decimal())
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_insurance_package_schemes(request):
    """
    Returns the list of available insurance package schemes along with document counts.
    """
    try:
        _, db = get_hms_db()
        schemes_with_counts = []
        for s in INSURANCE_SCHEMES:
            coll_name = s["collection"]
            try:
                count = db[coll_name].count_documents({})
            except Exception:
                count = 0
            schemes_with_counts.append({
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "collection": s["collection"],
                "total_items": count,
            })
        return Response({
            "success": True,
            "schemes": schemes_with_counts,
            "total": len(schemes_with_counts),
        })
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_insurance_package_items(request):
    """
    Fetches items from a specific insurance package collection with search/filter.
    Query params:
      - scheme: 'cghs', 'cm_scheme', 'echs', etc. (required)
      - search / itemName / q: text query
      - category: category filter
      - limit: optional max items
    """
    try:
        scheme_param = request.GET.get("scheme", "").strip().lower()
        if not scheme_param:
            # Fallback to returning scheme list if no scheme requested
            return get_insurance_package_schemes(request._request)

        scheme_meta = SCHEME_LOOKUP.get(scheme_param)
        if not scheme_meta:
            # Try fuzzy match
            for k, v in SCHEME_LOOKUP.items():
                if scheme_param in k or k in scheme_param:
                    scheme_meta = v
                    break

        if not scheme_meta:
            return Response({
                "success": False,
                "error": f"Invalid scheme '{scheme_param}'. Valid schemes: {list(SCHEME_LOOKUP.keys())}"
            }, status=400)

        coll_name = scheme_meta["collection"]
        scheme_id = scheme_meta["id"]
        scheme_name = scheme_meta["name"]

        _, db = get_hms_db()
        coll = db[coll_name]

        query = {}
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

        limit_param = request.GET.get("limit")
        limit = int(limit_param) if limit_param and limit_param.isdigit() else 0

        cursor = coll.find(query, {"_id": 0}).sort([("sl_no", 1), ("name", 1)])
        if limit > 0:
            cursor = cursor.limit(limit)

        raw_items = list(cursor)
        formatted = []
        for it in raw_items:
            nabh_rate = _safe_float(it.get("nabh_rate"))
            non_nabh_rate = _safe_float(it.get("non_nabh_rate"))
            # Default rate priority: nabh_rate if > 0 else non_nabh_rate
            primary_rate = nabh_rate if nabh_rate > 0 else non_nabh_rate

            formatted.append({
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
                "package_name": scheme_name,
                "scheme_id": scheme_id,
            })

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


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def insurance_packages_hub(request):
    """
    Hub endpoint:
    - If ?scheme=... is provided, returns items for that scheme.
    - If no scheme is provided, returns all insurance package schemes.
    """
    if request.GET.get("scheme"):
        return get_insurance_package_items(request._request)
    return get_insurance_package_schemes(request._request)
