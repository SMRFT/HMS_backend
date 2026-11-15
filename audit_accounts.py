 import os, sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env', override=True)
import django
django.setup()

from rest_framework.test import APIRequestFactory
from hospital.Views.AccountsReport import accounting_reports, bill_wise_report, shift_basis_report

factory = APIRequestFactory()

print("="*60)
print("AUDITING HMS ACCOUNT REPORTS CALCULATION AND TALLYING")
print("="*60)

# 1. Advance Registration Report
accounting_reports.advance_registration_report.cls.permission_classes = []
req = factory.get('/_b_a_c_k_e_n_d/HMS/advance-registration-report/?from_date=2026-11-01&to_date=2026-11-15')
res = accounting_reports.advance_registration_report(req)
d_adv = res.data.get('data', [])
adv_tally_ok = True
adv_cash_tot = 0.0
adv_cred_tot = 0.0
adv_amt_tot = 0.0
for r in d_adv:
    amt = round(float(r.get('amount', 0)), 2)
    cash = round(float(r.get('cash_amount', 0)), 2)
    credit = round(float(r.get('credit_amount', 0)), 2)
    adv_cash_tot += cash
    adv_cred_tot += credit
    adv_amt_tot += amt
    if round(cash + credit, 2) != amt:
        adv_tally_ok = False
        print(f"MISMATCH in Advance Reg: {r.get('bill_no')}: amt={amt} != cash({cash}) + credit({credit})")
print(f"1. Advance Registration Report: {len(d_adv)} rows | Total: {adv_amt_tot:.2f} | Cash: {adv_cash_tot:.2f} | Credit: {adv_cred_tot:.2f} | Tallied: {adv_tally_ok}")

# 2. Discharge Bills Report
accounting_reports.discharge_bills_report.cls.permission_classes = []
req = factory.get('/_b_a_c_k_e_n_d/HMS/discharge-bills-report/?from_date=2026-11-01&to_date=2026-11-15')
res = accounting_reports.discharge_bills_report(req)
d_dis = res.data.get('data', [])
dis_tally_count = 0
for r in d_dis:
    tot = round(float(r.get('total_amount', 0)), 2)
    disc = round(float(r.get('discount_amount', 0)), 2)
    adv = round(float(r.get('advance_amount', 0)), 2)
    net = round(float(r.get('net_amount', 0)), 2)
    paid = round(float(r.get('paid_by_patient', 0)), 2)
    due = round(float(r.get('due', 0)), 2)
    # Check if net + disc + adv roughly corresponds to tot
    if abs((tot - disc - adv) - net) > 1.0 and net > 0:
        dis_tally_count += 1
print(f"2. Discharge Bills Report: {len(d_dis)} rows | Formula Discrepancies: {dis_tally_count}")

# 3. Bill Wise Report
bill_wise_report.bill_wise_report.cls.permission_classes = []
req = factory.post('/_b_a_c_k_e_n_d/HMS/bill_wise_report/', {'from_date': '2026-11-01', 'to_date': '2026-11-15'}, format='json')
res = bill_wise_report.bill_wise_report(req)
d_bwr = res.data.get('data', [])
summary_bwr = res.data.get('summary', {})
print(f"3. Bill Wise Report: {len(d_bwr)} rows | Summary: {summary_bwr}")

# 4. Date Wise Collection Summary Report
accounting_reports.date_wise_collection_summary_report.cls.permission_classes = []
req = factory.get('/_b_a_c_k_e_n_d/HMS/date_wise_collection_summary_report/?from_date=2026-11-01&to_date=2026-11-15')
res = accounting_reports.date_wise_collection_summary_report(req)
d_date = res.data.get('data', [])
date_tally_ok = True
for r in d_date:
    net = round(float(r.get('net_amount', 0)), 2)
    cash = round(float(r.get('cash', 0)), 2)
    bank = round(float(r.get('bank', 0)), 2)
    if round(cash + bank, 2) != net:
        date_tally_ok = False
        print(f"MISMATCH in DateWise: {r.get('date')} {r.get('bill_name')}: net={net} != cash({cash}) + bank({bank})")
print(f"4. Date Wise Collection Summary: {len(d_date)} rows | Cash+Bank==Net Tallied: {date_tally_ok}")

# 5. Cash Bills Report
accounting_reports.cash_bills_report.cls.permission_classes = []
req = factory.get('/_b_a_c_k_e_n_d/HMS/cash-bills-report/?from_date=2026-11-01&to_date=2026-11-15')
res = accounting_reports.cash_bills_report(req)
d_cash = res.data.get('data', [])
s_cash = res.data.get('summary', {})
cash_sum = sum(float(r.get('amount', 0)) for r in d_cash)
print(f"5. Cash Bills Report: {len(d_cash)} rows | Rows Sum: {cash_sum:.2f} | Summary Total: {s_cash.get('total_amount', 0):.2f} | Tallied: {round(cash_sum, 2) == round(s_cash.get('total_amount', 0), 2)}")

# 6. Credit Card Report
accounting_reports.credit_card_report.cls.permission_classes = []
req = factory.get('/_b_a_c_k_e_n_d/HMS/credit-card-report/?from_date=2026-11-01&to_date=2026-11-15')
res = accounting_reports.credit_card_report(req)
d_card = res.data.get('data', [])
s_card = res.data.get('summary', {})
card_sum = sum(float(r.get('amount', 0)) for r in d_card)
print(f"6. Credit Card Report: {len(d_card)} rows | Rows Sum: {card_sum:.2f} | Summary Total: {s_card.get('total_amount', 0):.2f} | Tallied: {round(card_sum, 2) == round(s_card.get('total_amount', 0), 2)}")

# 7. Daily Cash Report
accounting_reports.daily_cash_report.cls.permission_classes = []
req = factory.get('/_b_a_c_k_e_n_d/HMS/daily-cash-report/?from_date=2026-11-01&to_date=2026-11-15')
res = accounting_reports.daily_cash_report(req)
d_daily = res.data.get('data', [])
s_daily = res.data.get('summary', {})
daily_ok = True
for r in d_daily:
    c_in = round(float(r.get('cash_in', 0)), 2)
    c_out = round(float(r.get('cash_out', 0)), 2)
    net = round(float(r.get('net', 0)), 2)
    if round(c_in - c_out, 2) != net:
        daily_ok = False
print(f"7. Daily Cash Report: {len(d_daily)} days | Net == In - Out: {daily_ok} | Summary Net: {s_daily.get('net', 0)}")

# 8. Shift Basis Accounts Report
shift_basis_report.shift_basis_accounts_report.cls.permission_classes = []
req = factory.post('/_b_a_c_k_e_n_d/HMS/shift_basis_accounts_report/', {'from_date': '2026-11-01', 'to_date': '2026-11-15'}, format='json')
res = shift_basis_report.shift_basis_accounts_report(req)
d_sbr = res.data.get('data', [])
s_sbr = res.data.get('summary', {})
sbr_sum = sum(float(r.get('display_amount', 0)) for r in d_sbr)
print(f"8. Shift Basis Report: {len(d_sbr)} rows | Rows Sum: {sbr_sum:.2f} | Summary Net: {s_sbr.get('total_net', 0):.2f} | Tallied: {round(sbr_sum, 2) == round(s_sbr.get('total_net', 0), 2)}")

