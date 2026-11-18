"""
Master Accounts Reports URL Routing Table
=========================================
Maps all 35 hospital accounts and billing reports across 6 clusters.
All endpoints are completely isolated from legacy accounting views.
"""

from django.urls import path
from .cluster1_shift_cash import (
    shift_basis_collection_api,
    cash_bills_summary_api,
    daily_cash_report_api,
    cashier_wise_summary_api,
    cashier_wise_detailed_api,
)
from .cluster2_digital_dept import (
    credit_card_report_api,
    date_wise_collection_summary_api,
    department_wise_collection_api,
    bill_type_wise_collection_api,
)
from .cluster3_ip_advances import (
    advance_registration_api,
    insurance_advance_registration_api,
    ip_advance_collection_register_api,
    discharge_bills_summary_api,
    discharge_bills_detailed_api,
    debit_and_due_bills_api,
    discount_bills_api,
    bill_cancellation_register_api,
)
from .admission_vs_discharge_api import admission_vs_discharge_api
from .cluster4_audit_sundry import (
    accounts_audit_report_api,
    bill_wise_detailed_api,
    miscellaneous_payment_api,
)
from .cluster5_gst_taxation import (
    sales_tax_register_api,
    op_pharmacy_sales_gst_api,
    purchase_gst_consolidated_api,
    drug_purchase_gst_api,
    stores_purchase_gst_api,
)
from .cluster6_inventory_stock import (
    ip_op_stock_movement_api,
    sales_return_report_api,
)
from hospital.Views.AccountsReport.unified_accounts_report import unified_accounts_report_api

urlpatterns = [
    # Unified Single Source of Truth
    path('unified-accounts-report/', unified_accounts_report_api, name='master_unified_accounts_report'),

    # Cluster 1: Shift & Cash Management
    path('shift-basis-collection/', shift_basis_collection_api, name='master_shift_basis_collection'),
    path('cash-bills-summary/', cash_bills_summary_api, name='master_cash_bills_summary'),
    path('daily-cash-collection/', daily_cash_report_api, name='master_daily_cash_collection'),
    path('cashier-wise-summary/', cashier_wise_summary_api, name='master_cashier_wise_summary'),
    path('cashier-wise-detailed/', cashier_wise_detailed_api, name='master_cashier_wise_detailed'),

    # Cluster 2: Digital & Departmental Collections
    path('credit-card-electronic-payment/', credit_card_report_api, name='master_credit_card_electronic_payment'),
    path('date-wise-collection-summary/', date_wise_collection_summary_api, name='master_date_wise_collection_summary'),
    path('department-wise-collection/', department_wise_collection_api, name='master_department_wise_collection'),
    path('bill-type-wise-collection/', bill_type_wise_collection_api, name='master_bill_type_wise_collection'),

    # Cluster 3: IP Admissions, Advances & Billing
    path('advance-registration/', advance_registration_api, name='master_advance_registration'),
    path('insurance-advance-registration/', insurance_advance_registration_api, name='master_insurance_advance_registration'),
    path('ip-advance-collection/', ip_advance_collection_register_api, name='master_ip_advance_collection'),
    path('admission-vs-discharge/', admission_vs_discharge_api, name='master_admission_vs_discharge'),
    path('discharge-bills-summary/', discharge_bills_summary_api, name='master_discharge_bills_summary'),
    path('discharge-bills-detailed/', discharge_bills_detailed_api, name='master_discharge_bills_detailed'),
    path('debit-and-due-bills/', debit_and_due_bills_api, name='master_debit_and_due_bills'),
    path('discount-bills/', discount_bills_api, name='master_discount_bills'),
    path('bill-cancellation/', bill_cancellation_register_api, name='master_bill_cancellation'),

    # Cluster 4: Auditing & Sundry Income
    path('accounts-audit/', accounts_audit_report_api, name='master_accounts_audit'),
    path('bill-wise-detailed/', bill_wise_detailed_api, name='master_bill_wise_detailed'),
    path('miscellaneous-payment/', miscellaneous_payment_api, name='master_miscellaneous_payment'),

    # Cluster 5: GST Taxation & Invoicing
    path('sales-tax-register/', sales_tax_register_api, name='master_sales_tax_register'),
    path('op-pharmacy-sales-gst-consolidated/', op_pharmacy_sales_gst_api, name='master_op_pharmacy_sales_gst_consolidated'),
    path('purchase-gst-consolidated/', purchase_gst_consolidated_api, name='master_purchase_gst_consolidated'),
    path('op-pharmacy-b2c-invoices/', op_pharmacy_sales_gst_api, name='master_op_pharmacy_b2c_invoices'),
    path('op-pharmacy-hsn-summary/', op_pharmacy_sales_gst_api, name='master_op_pharmacy_hsn_summary'),
    path('op-pharmacy-doc-summary/', op_pharmacy_sales_gst_api, name='master_op_pharmacy_doc_summary'),
    path('purchase-b2b-invoices/', purchase_gst_consolidated_api, name='master_purchase_b2b_invoices'),
    path('purchase-hsn-summary/', purchase_gst_consolidated_api, name='master_purchase_hsn_summary'),
    path('purchase-doc-summary/', purchase_gst_consolidated_api, name='master_purchase_doc_summary'),
    path('drug-purchase-gst/', drug_purchase_gst_api, name='master_drug_purchase_gst'),
    path('stores-purchase-gst/', stores_purchase_gst_api, name='master_stores_purchase_gst'),

    # Cluster 6: Inventory & Stock Auditing
    path('ip-op-stock-movement/', ip_op_stock_movement_api, name='master_ip_op_stock_movement'),
    path('sales-return/', sales_return_report_api, name='master_sales_return'),
]
