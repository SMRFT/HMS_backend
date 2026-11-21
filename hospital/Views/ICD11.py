import time
import requests
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

_cached_token = None
_expiry = 0
_search_cache = {}  # In-memory query cache for instant lookup & offline resilience


def get_icd11_token():
    global _cached_token, _expiry

    if _cached_token and time.time() < _expiry:
        return _cached_token

    client_id = getattr(settings, "WHO_ICD_CLIENT_ID", None)
    client_secret = getattr(settings, "WHO_ICD_CLIENT_SECRET", None)
    token_url = getattr(settings, "WHO_TOKEN_URL", "https://icdaccessmanagement.who.int/connect/token")

    if not client_id or not client_secret:
        raise ValueError("WHO ICD11 credentials (WHO_ICD_CLIENT_ID, WHO_ICD_CLIENT_SECRET) not configured in settings")

    response = requests.post(
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "icdapi_access",
            "grant_type": "client_credentials",
        },
        timeout=8
    )

    response.raise_for_status()
    data = response.json()

    _cached_token = data["access_token"]
    _expiry = time.time() + data.get("expires_in", 3600) - 60

    return _cached_token


@api_view(["GET"])
@permission_classes([AllowAny])
def icd11_search(request):
    global _cached_token, _search_cache
    query = request.GET.get("q")
    if not query:
        return Response({"error": "q is required"}, status=400)

    clean_q = str(query).strip().lower()

    # 1. Fast in-memory cache check (<1ms)
    if clean_q in _search_cache:
        cached_entry = _search_cache[clean_q]
        if time.time() - cached_entry.get("ts", 0) < 86400:  # 24 hour TTL
            return Response(cached_entry["data"], status=200)

    # 2. Fetch from WHO API with strict timeout & error recovery
    try:
        token = get_icd11_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "API-Version": "v2",   # Required by WHO API v2
            "Accept-Language": "en"
        }

        base_url = getattr(settings, "WHO_BASE_URL", "https://id.who.int/icd/release/11/2023-01/mms")
        response = requests.get(
            f"{base_url}/search",
            params={"q": query},
            headers=headers,
            timeout=8
        )

        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("destinationEntities"):
                _search_cache[clean_q] = {"data": res_json, "ts": time.time()}
            return Response(res_json, status=200)
        elif response.status_code in [401, 500]:
            # Reset token cache if unauthorized or server error
            _cached_token = None
            if clean_q in _search_cache:
                return Response(_search_cache[clean_q]["data"], status=200)
            return Response(
                {"error": "WHO API returned error", "status": response.status_code, "destinationEntities": []},
                status=response.status_code
            )
        else:
            return Response(response.json(), status=response.status_code)

    except requests.exceptions.Timeout:
        # If timeout occurs, fall back to cached data if available
        if clean_q in _search_cache:
            return Response(_search_cache[clean_q]["data"], status=200)
        return Response(
            {"error": "WHO ICD API connection timed out. Please try again.", "destinationEntities": []},
            status=504
        )
    except Exception as e:
        if clean_q in _search_cache:
            return Response(_search_cache[clean_q]["data"], status=200)
        return Response(
            {"error": str(e), "destinationEntities": []},
            status=500
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def icd11_detail(request, entity_id):
    entity_id = entity_id.strip()
    entity_id = entity_id.replace("\n", "").replace("\r", "")

    # Safety check
    if not entity_id.isdigit():
        return Response(
            {"error": "Invalid ICD-11 entity ID", "received": entity_id},
            status=400
        )

    try:
        token = get_icd11_token()
        url = f"{settings.WHO_BASE_URL}/entity/{entity_id}"

        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "API-Version": "v2",
                "Accept-Language": "en"
            },
            timeout=8
        )

        if response.status_code != 200:
            return Response(
                {
                    "error": "WHO API error",
                    "status": response.status_code,
                    "who_url": url,
                    "response": response.text
                },
                status=response.status_code
            )

        return Response(response.json())
    except requests.exceptions.Timeout:
        return Response(
            {"error": "WHO ICD API connection timed out"},
            status=504
        )
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=500
        )
