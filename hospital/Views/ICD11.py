import time
import requests
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

_cached_token = None
_expiry = 0


def get_icd11_token():
    global _cached_token, _expiry

    if _cached_token and time.time() < _expiry:
        return _cached_token

    response = requests.post(
        settings.WHO_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id": settings.WHO_ICD_CLIENT_ID,
            "client_secret": settings.WHO_ICD_CLIENT_SECRET,
            "scope": "icdapi_access",
            "grant_type": "client_credentials",
        },
        timeout=10
    )

    response.raise_for_status()
    data = response.json()

    _cached_token = data["access_token"]
    _expiry = time.time() + data["expires_in"] - 60

    return _cached_token


@api_view(["GET"])
def icd11_search(request):
    query = request.GET.get("q")
    if not query:
        return Response({"error": "q is required"}, status=400)

    token = get_icd11_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "API-Version": "v2",   # 🔥 REQUIRED
        "Accept-Language": "en"
    }

    response = requests.get(
        f"{settings.WHO_BASE_URL}/search",
        params={"q": query},
        headers=headers
    )

    return Response(response.json(), status=response.status_code)


@api_view(["GET"])
def icd11_detail(request, entity_id):
    entity_id = entity_id.strip()
    entity_id = entity_id.replace("\n", "").replace("\r", "")

    # Safety check
    if not entity_id.isdigit():
        return Response(
            {"error": "Invalid ICD-11 entity ID", "received": entity_id},
            status=400
        )

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
        timeout=10
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
