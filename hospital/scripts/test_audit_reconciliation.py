import os, sys, django, datetime
sys.path.insert(0, 'd:/SMRFT/Projects/HMS/HMS_backend')
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env', override=True)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from django.test import RequestFactory
import hospital.Views.AccountsReport.accounting_reports as ar
from hospital.Views.cashcounter import get_shift_summary_report

ar.cash_bills_report.cls.permission_classes = []
ar.credit_card_report.cls.permission_classes = []
ar.advance_registration_report.cls.permission_classes = []

rf = RequestFactory()

for target_date in ['2026-11-15', '2026-11-16']:
    print(f"\n=======================================================")
    print(f"               AUDIT FOR {target_date}                 ")
    print(f"=======================================================")
    
    # 1. SHIFT BASIS SUMMARY REPORT
    req_shift = rf.post('/_b_a_c_k_e_n_d/HMS/get_shift_summary_report/', {
        'from_date': target_date,
        'to_date': target_date,
        'outlet_code': 'all'
    })
    res_shift = get_shift_summary_report(req_shift)
    shift_data = res_shift.data.get('data', []) if hasattr(res_shift, 'data') else []
    
    shift_by_outlet = {}
    total_shift_cash = 0.0
    total_shift_credit = 0.0
    total_shift_returns = 0.0
    
    for s in shift_data:
        outlet = s.get('outlet_code') or s.get('SelectedOutlet') or 'UNKNOWN'
        c_coll = float(s.get('collected_Amount') or 0)
        cr_coll = float(s.get('CreditAmount') or 0)
        ret = float(s.get('SalesReturnAmount') or 0)
        
        total_shift_cash += c_coll
        total_shift_credit += cr_coll
        total_shift_returns += ret
        
        info = shift_by_outlet.setdefault(outlet, {'cash': 0.0, 'credit': 0.0, 'returns': 0.0, 'shifts': []})
        info['cash'] += c_coll
        info['credit'] += cr_coll
        info['returns'] += ret
        info['shifts'].append(f"{s.get('shiftno')} ({s.get('cashier_name')}): cash={c_coll}, credit={cr_coll}")

    print(f"\n--- 1. SHIFTS SUMMARY ---")
    print(f"Total Shift Cash: {total_shift_cash:.2f}")
    print(f"Total Shift Credit: {total_shift_credit:.2f}")
    print(f"Total Shift Returns: {total_shift_returns:.2f}")
    for olet, info in shift_by_outlet.items():
        print(f"  Outlet {olet}: Cash={info['cash']:.2f}, Credit={info['credit']:.2f}, Returns={info['returns']:.2f}")
        for sh in info['shifts']:
            print(f"    - {sh}")

    # 2. CASH BILLS REPORT (All outlets & by outlet)
    req_cash_all = rf.get(f'/_b_a_c_k_e_n_d/HMS/cash-bills-report/?from_date={target_date}&to_date={target_date}&outlet_code=all')
    res_cash_all = ar.cash_bills_report(req_cash_all)
    cash_grand_total = float(res_cash_all.data.get('grand_total') or 0)
    print(f"\n--- 2. CASH BILLS REPORT ---")
    print(f"Cash Bills Grand Total (All): {cash_grand_total:.2f}")
    for olet in shift_by_outlet.keys():
        req_c = rf.get(f'/_b_a_c_k_e_n_d/HMS/cash-bills-report/?from_date={target_date}&to_date={target_date}&outlet_code={olet}')
        res_c = ar.cash_bills_report(req_c)
        c_gt = float(res_c.data.get('grand_total') or 0)
        diff = c_gt - shift_by_outlet[olet]['cash']
        print(f"  Outlet {olet}: Cash Bills Total={c_gt:.2f} | Shift Cash={shift_by_outlet[olet]['cash']:.2f} | Diff={diff:.2f}")

    # 3. CREDIT CARD REPORT (All outlets & by outlet)
    req_card_all = rf.get(f'/_b_a_c_k_e_n_d/HMS/credit-card-report/?from_date={target_date}&to_date={target_date}&outlet_code=all')
    res_card_all = ar.credit_card_report(req_card_all)
    card_grand_total = float(res_card_all.data.get('grand_total') or 0)
    print(f"\n--- 3. CREDIT CARD REPORT ---")
    print(f"Credit Card Grand Total (All): {card_grand_total:.2f}")
    for olet in shift_by_outlet.keys():
        req_cr = rf.get(f'/_b_a_c_k_e_n_d/HMS/credit-card-report/?from_date={target_date}&to_date={target_date}&outlet_code={olet}')
        res_cr = ar.credit_card_report(req_cr)
        cr_gt = float(res_cr.data.get('grand_total') or 0)
        diff = cr_gt - shift_by_outlet[olet]['credit']
        print(f"  Outlet {olet}: Credit Card Total={cr_gt:.2f} | Shift Credit={shift_by_outlet[olet]['credit']:.2f} | Diff={diff:.2f}")

    # 4. ADVANCE REGISTRATION REPORT
    req_adv = rf.get(f'/_b_a_c_k_e_n_d/HMS/advance_registration_report/?from_date={target_date}&to_date={target_date}')
    res_adv = ar.advance_registration_report(req_adv)
    adv_records = res_adv.data.get('data', [])
    adv_cash = sum(float(r.get('cash_amount') or 0) for r in adv_records)
    adv_credit = sum(float(r.get('credit_amount') or r.get('credit_card_amount') or 0) for r in adv_records)
    print(f"\n--- 4. ADVANCE REGISTRATION REPORT ---")
    print(f"Total Advance Records: {len(adv_records)}")
    print(f"Advance Cash: {adv_cash:.2f}")
    print(f"Advance Credit: {adv_credit:.2f}")
    for r in adv_records:
        print(f"  Bill {r.get('bill_no')}: {r.get('patient_name')} | Cash={r.get('cash_amount')} | Card={r.get('credit_card_amount')} | Mode={r.get('payment_mode')}")

