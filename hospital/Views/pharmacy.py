from django.http import JsonResponse
from pymongo import MongoClient
import os
from ..serializers import OPPharmacyBillSerializer
from rest_framework.response import Response
from rest_framework.decorators import api_view

# MongoDB Configuration
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_oppharmacystock"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
collection = mongo_db[COLLECTION_NAME]

from bson.decimal128 import Decimal128

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal128):
        return float(obj.to_decimal())
    return obj

def get_oppharmacy_stock(request):
    try:
        data = list(collection.find({}, {"_id": 0}))

        for item in data:
            total_qty = item.get("total_quantity", 0)
            reduced = item.get("reduced_stock", 0)
            
            # Ensure these are numbers for calculation if they are Decimal128
            if isinstance(total_qty, Decimal128):
                total_qty = float(total_qty.to_decimal())
            if isinstance(reduced, Decimal128):
                reduced = float(reduced.to_decimal())

            item["available_stock"] = total_qty - reduced

        data = convert_decimals(data)
        return JsonResponse(data, safe=False)

    except Exception as e:
        print("Error while fetching pharmacy stock:", str(e))
        return JsonResponse({"error": str(e)}, status=500)




@api_view(["POST"])
def save_oppharmacy_bill(request):
    serializer = OPPharmacyBillSerializer(data=request.data)

    if serializer.is_valid():
        bill = serializer.save()

        client = MongoClient(MONGO_URI)
        db = client["HMS"]
        stock_collection = db["hospital_oppharmacystock"]

        medicine_list = request.data.get("medicine_name", [])

        for item in medicine_list:
            hsn_code = item.get("hsn_code")
            quantity = int(item.get("quantity", 0))

            if not hsn_code:
                continue

            stock_items = stock_collection.find({"hsn_code": hsn_code})

            for stock_item in stock_items:
                current_reduced = stock_item.get("reduced_stock", 0)
                new_reduced = current_reduced + quantity

                stock_collection.update_one(
                    {"_id": stock_item["_id"]},
                    {"$set": {"reduced_stock": new_reduced}}
                )

        return Response({"message": "Bill saved and stock updated successfully"}, status=201)

    return Response(serializer.errors, status=400)
