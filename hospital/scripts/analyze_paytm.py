import csv

success_txns = []
with open(r'd:\SMRFT\Projects\HMS\paytm report 15.11.26 Rec.csv', 'r', encoding='utf-8', errors='ignore') as f:
    reader = csv.DictReader(f)
    for r in reader:
        status = r.get('status', '').replace("'", "").strip()
        amt_str = r.get('amount', '').replace("'", "").strip()
        if not amt_str: continue
        try:
            amt = float(amt_str)
        except ValueError:
            continue
        t_date = r.get('transaction_date', '').replace("'", "").strip()
        p_mode = r.get('payment_mode', '').replace("'", "").strip()
        order_id = r.get('order_id', '').replace("'", "").strip()
        rrn = r.get('rrncode', '').replace("'", "").strip()
        udf1 = r.get('udf1', '').replace("'", "").strip()
        pos_id = r.get('pos_id', '').replace("'", "").strip()
        success_txns.append({
            'status': status, 'amount': amt, 'date': t_date,
            'mode': p_mode, 'order_id': order_id, 'rrn': rrn,
            'udf1': udf1, 'pos_id': pos_id
        })

print(f"Total transactions parsed: {len(success_txns)}")
successful = [t for t in success_txns if t['status'] == 'SUCCESS']
print(f"Successful transactions: {len(successful)}")
tot_amt = sum(t['amount'] for t in successful)
print(f"Total successful amount: {tot_amt:.2f}")

by_pos = {}
for t in successful:
    pos = t['pos_id']
    by_pos.setdefault(pos, []).append(t)

for pos, txns in by_pos.items():
    print(f"\nPOS {pos}: {len(txns)} txns, total = {sum(x['amount'] for x in txns):.2f}")
    for x in txns:
        print(f"   {x['date']} | {x['mode']} | {x['amount']} | rrn: {x['rrn']} | order: {x['order_id']}")

