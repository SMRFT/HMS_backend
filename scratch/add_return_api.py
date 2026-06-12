import re

file_path = "/Users/parthibanmurugan/Desktop/Live Projects/HMS/HMS_backend/hospital/Views/NursingStation.py"

with open(file_path, "r") as f:
    content = f.read()

new_api = """
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def return_medicine_ward_request(request):
    import traceback
    try:
        data = request.data
        bill_id = data.get("Bill_id")
        returned_medicines = data.get("medicine_particulars", [])
        changed_by = data.get("auth-user-id", "system")

        if not bill_id:
            return Response({"success": False, "error": "Bill_id is required"}, status=400)

        try:
            bill = PharmacyBilling.objects.get(Bill_id=bill_id)
        except PharmacyBilling.DoesNotExist:
            return Response({"success": False, "error": "Ward request not found"}, status=404)

        existing = list(bill.medicine_particulars or [])

        # Build a lookup map keyed by (item_id, batch_number)
        existing_map = {}
        for idx, itm in enumerate(existing):
            if not isinstance(itm, dict):
                continue
            key = (str(itm.get("item_id", "")), str(itm.get("batch_number", "")))
            existing_map[key] = (idx, itm)

        changed_at = timezone.now().isoformat()

        for incoming in returned_medicines:
            if not isinstance(incoming, dict):
                continue
            key = (str(incoming.get("item_id", "")), str(incoming.get("batch_number", "")))
            if key not in existing_map:
                continue

            idx, current = existing_map[key]
            
            return_qty = float(incoming.get("return_qty", 0))
            if return_qty <= 0:
                continue

            old_qty = float(current.get("quantity", current.get("qty", 0)))
            new_qty = old_qty - return_qty
            
            if new_qty < 0:
                new_qty = 0

            audit_entry = {
                "changed_by": changed_by,
                "changed_at": changed_at,
                "action": "returned",
                "return_qty": return_qty,
                "old_qty": old_qty,
                "new_qty": new_qty,
                "reason": incoming.get("reason", "Ward Return")
            }

            eh = current.get("edit_history", [])
            if not isinstance(eh, list):
                eh = []
            eh.append(audit_entry)
            current["edit_history"] = eh
            current["quantity"] = new_qty
            current["qty"] = new_qty

            existing[idx] = current

        bill.medicine_particulars = existing

        # Recalculate totals from non-deleted items
        new_total = sum(
            float(itm.get("quantity", itm.get("qty", 0))) * float(itm.get("price", 0))
            for itm in existing
            if isinstance(itm, dict) and not itm.get("is_deleted")
        )
        bill.total_amount = round(new_total, 2)
        bill.net_amount = round(new_total, 2)
        bill.lastmodified_by = changed_by
        bill.save()

        return Response({"success": True, "message": "Medicines returned successfully"})

    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)
"""

if "def return_medicine_ward_request" not in content:
    content += "\n" + new_api
    with open(file_path, "w") as f:
        f.write(content)
    print("Added return_medicine_ward_request to NursingStation.py")
else:
    print("Already exists.")
