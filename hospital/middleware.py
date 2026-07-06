import json
from django.http import JsonResponse
from .models import UserSession


# Endpoints that are exempt from session enforcement
EXEMPT_PATHS = [
    "/create-session/",
    "/admin/",
]


def _get_employee_id_from_jwt(request):
    """
    Extracts the employee_id (aud field) from the JWT without full validation.
    We only need the payload here — pyauth already validates on real requests.
    """
    try:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            return None
        token = auth_header.strip()
        # JWT is three base64url parts separated by dots
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Decode payload (middle part); add padding if needed
        import base64
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        return str(payload.get("aud", ""))
    except Exception:
        return None


class SessionEnforcementMiddleware:
    """
    Middleware that enforces single-device login.

    On every request:
    1. Reads the X-Session-Token header sent by the frontend.
    2. Decodes the JWT to get the employee_id.
    3. Looks up the active session for that employee in the DB.
    4. If the tokens don't match -> returns 401 { "force_logout": true }.
    5. If they match -> updates last_seen and allows the request through.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip enforcement for exempt paths
        for exempt in EXEMPT_PATHS:
            if request.path_info.endswith(exempt):
                return self.get_response(request)

        session_token = request.META.get("HTTP_X_SESSION_TOKEN", "").strip()

        # Only enforce if a session token is present in the request
        if session_token:
            employee_id = _get_employee_id_from_jwt(request)
            if employee_id:
                try:
                    user_session = UserSession.objects.filter(
                        employee_id=employee_id
                    ).first()

                    if user_session and user_session.session_token != session_token:
                        # Token mismatch -> force logout
                        return JsonResponse(
                            {"force_logout": True, "error": "Session invalidated. Please login again."},
                            status=401,
                        )
                    elif user_session and user_session.session_token == session_token:
                        # Token valid -> update last_seen (auto_now handles this on save)
                        user_session.save(update_fields=["last_seen"])
                except Exception:
                    # Don't block requests on DB errors -- fail open
                    pass

        return self.get_response(request)
