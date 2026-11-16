import os
import sys

def run():
    sys.path.insert(0, 'd:/SMRFT/Projects/HMS/HMS_backend')
    from dotenv import load_dotenv
    load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
    import django
    django.setup()

    from hospital.Views.dbcollection import hms_db
    col = hms_db['hospital_storesgrn']

    total = col.count_documents({})
    print(f"Total GRN documents in collection: {total}")

    batch_size = 500
    cursor = col.find({}, {'items': 1, 'net_invoice_amount': 1, 'invoice_amount': 1, 'invoice_number': 1, 'invoice_no': 1, 'total_amount': 1, 'round_amount': 1, 'tax_on_free_items': 1, 'grn_number': 1})
    
    from pymongo import UpdateOne
    updates = []
    processed = 0
    updated_count = 0

    for d in cursor:
        processed += 1
        items = d.get('items') or []
        tot_taxable = 0.0
        tot_cgst = 0.0
        tot_sgst = 0.0
        tot_igst = 0.0
        for it in items:
            if isinstance(it, dict):
                q = float(it.get('quantity') or it.get('qty') or 0.0)
                p = float(it.get('packing') or it.get('pack') or 1.0) or 1.0
                rate = float(it.get('unitPrice') or it.get('purchaseRate') or it.get('packingPrice') or it.get('packing_price') or it.get('rate') or 0.0)
                disc = float(it.get('purchase_discount_amt') or it.get('discountedAmt') or it.get('discount') or 0.0)
                taxable = float(it.get('item_value') or it.get('itemValue') or it.get('taxableAmt') or ((rate * (q / p)) - disc))
                cgst_rate = float(it.get('cgst_percent') or it.get('cgstPercent') or (float(it.get('tax') or 0.0) / 2.0 if it.get('tax') else 0.0) or 0.0)
                sgst_rate = float(it.get('sgst_percent') or it.get('sgstPercent') or (float(it.get('tax') or 0.0) / 2.0 if it.get('tax') else 0.0) or 0.0)
                igst_rate = float(it.get('igst_percent') or it.get('igstPercent') or 0.0)
                tot_taxable += taxable
                tot_cgst += round((taxable * cgst_rate) / 100.0, 2) if cgst_rate > 0 else float(it.get('cgst_amt') or it.get('cgstAmt') or 0.0)
                tot_sgst += round((taxable * sgst_rate) / 100.0, 2) if sgst_rate > 0 else float(it.get('sgst_amt') or it.get('sgstAmt') or 0.0)
                tot_igst += round((taxable * igst_rate) / 100.0, 2) if igst_rate > 0 else float(it.get('igst_amt') or it.get('igstAmt') or 0.0)

        calc_gst = tot_cgst + tot_sgst + tot_igst
        tax_on_free = float(d.get('tax_on_free_items') or 0.0)
        calc_tot = tot_taxable + calc_gst + tax_on_free

        stored_net = float(str(d.get('net_invoice_amount') or 0.0))
        inv_amt = float(str(d.get('invoice_amount') or 0.0))
        stored_round = float(str(d.get('round_amount') or 0.0))

        if stored_net > 0:
            net_val = stored_net
            round_val = stored_round or round(stored_net - calc_tot, 2)
        elif calc_tot > 0:
            net_val = round(calc_tot + stored_round, 2)
            round_val = stored_round
        elif inv_amt > 0:
            net_val = inv_amt
            round_val = stored_round
        else:
            net_val = float(str(d.get('total_amount') or 0.0))
            round_val = 0.0

        inv_num = d.get('invoice_number') or d.get('invoice_no') or ''
        
        upd = {
            'net_invoice_amount': round(net_val, 2),
            'total_amount': round(calc_tot or net_val, 2),
            'taxable_amount': round(tot_taxable, 2),
            'cgst': round(tot_cgst, 2),
            'sgst': round(tot_sgst, 2),
            'igst': round(tot_igst, 2),
            'round_amount': round(round_val, 2),
            'invoice_no': inv_num,
            'invoice_number': inv_num
        }

        updates.append(UpdateOne({'_id': d['_id']}, {'$set': upd}))

        if len(updates) >= batch_size:
            res = col.bulk_write(updates, ordered=False)
            updated_count += res.modified_count
            updates = []
            print(f"Processed {processed}/{total} docs, modified: {updated_count}...")

    if updates:
        res = col.bulk_write(updates, ordered=False)
        updated_count += res.modified_count

    print(f"Completed! Total processed: {processed}, total modified: {updated_count}")

if __name__ == '__main__':
    run()

