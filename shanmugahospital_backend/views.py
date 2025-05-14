from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .models import Doctor
from .serializers import DoctorSerializer

@csrf_exempt
def doctor_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            serializer = DoctorSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return JsonResponse(serializer.data, status=201)
            return JsonResponse(serializer.errors, status=400)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON data"}, status=400)
    return JsonResponse({"error": "Method not allowed"}, status=405)
