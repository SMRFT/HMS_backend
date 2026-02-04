from django.http import JsonResponse
from pymongo import MongoClient
import os

# MongoDB Configuration
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_pharmacystock"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
collection = mongo_db[COLLECTION_NAME]

def get_pharmacy_stock(request):
    try:
        # Fetch all documents and exclude MongoDB _id
        data = list(collection.find({}, {"_id": 0}))
        print(f"Fetched {len(data)} records from {COLLECTION_NAME}")
        return JsonResponse(data, safe=False)   # ✅ Return array directly
    except Exception as e:
        print("Error while fetching pharmacy stock:", str(e))
        return JsonResponse({"error": str(e)}, status=500)
