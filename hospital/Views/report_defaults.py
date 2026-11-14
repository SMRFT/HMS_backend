from datetime import datetime
from hospital.Views.dbcollection import hms_db

DEFAULT_REPORT_GROUPS = [   {   'group': 'Stores Report',
        'group_id': 1,
        'order': 1,
        'pages': [   {   'description': 'Generate, manage, and print '
                                        'standardized Hospital Purchase Orders '
                                        'with vendor terms and item tax lines.',
                         'icon': 'ShoppingBag',
                         'name': 'Purchase Order Format (PO)',
                         'page_id': 1,
                         'permissions': {   'Purchase Order Format (PO)': 'HMS-STORES-PO-RPT'},
                         'route': '/StoresPurchaseOrderReport'},
                     {   'description': 'Return defective or excess goods to '
                                        'suppliers with automatic stock '
                                        'deduction and printable Debit Notes.',
                         'icon': 'RotateCcw',
                         'name': 'Purchase Return & Debit Notes',
                         'page_id': 2,
                         'permissions': {   'Purchase Return & Debit Notes': 'HMS-STORES-PURCHASE-RET-RPT'},
                         'route': '/StoresPurchaseReturnReport'},
                     {   'description': 'Analyze monthly purchase trends, '
                                        'vendor spend shares, top purchased '
                                        'goods, and price fluctuations over '
                                        'time.',
                         'icon': 'TrendingUp',
                         'name': 'Purchase Analysis Report',
                         'page_id': 3,
                         'permissions': {   'Purchase Analysis Report': 'HMS-STORES-PURCHASE-ANALYSIS-RPT'},
                         'route': '/StoresPurchaseAnalysisReport'},
                     {   'description': 'Daily opening stock balance, GRN '
                                        'inward receipts, Indent outward '
                                        'issues, returns, and closing '
                                        'valuation.',
                         'icon': 'Layers',
                         'name': 'Previous Day / Daily Stock Report',
                         'page_id': 4,
                         'permissions': {   'Previous Day / Daily Stock Report': 'HMS-STORES-PREV-STOCK'},
                         'route': '/StoresPreviousDayStockReport'},
                     {   'description': 'Comprehensive directory of suppliers '
                                        'with cumulative order values, total '
                                        'payments made, and pending dues.',
                         'icon': 'Building2',
                         'name': 'Supplier-Wise List & Ledger',
                         'page_id': 5,
                         'permissions': {   'Supplier-Wise List & Ledger': 'HMS-STORES-SUPPLIER-WISE-RPT'},
                         'route': '/StoresSupplierWiseReport'},
                     {   'description': 'Identify slow-moving and idle items '
                                        'with zero indents over 30 / 60 / 90 / '
                                        '180+ days to prevent dead capital.',
                         'icon': 'Clock',
                         'name': 'Non-Moving Items Report (Dead Stock)',
                         'page_id': 6,
                         'permissions': {   'Non-Moving Items Report (Dead Stock)': 'HMS-STORES-NON-MOVING-RPT'},
                         'route': '/StoresNonMovingReport'},
                     {   'description': 'Early warning alert report tracking '
                                        'pharmaceutical and medical items '
                                        'nearing expiry within 30, 60, or 90 '
                                        'days.',
                         'icon': 'AlertTriangle',
                         'name': 'Short Expiry & Expired List',
                         'page_id': 7,
                         'permissions': {   'Short Expiry & Expired List': 'HMS-STORES-SHORT-EXPIRY-RPT'},
                         'route': '/StoresShortExpiryReport'},
                     {   'description': 'Real-time stock threshold monitoring, '
                                        'identifying out-of-stock and '
                                        'low-stock items with suggested '
                                        'reorder quantities.',
                         'icon': 'AlertCircle',
                         'name': 'Reorder Level Indication',
                         'page_id': 8,
                         'permissions': {   'Reorder Level Indication': 'HMS-STORES-REORDER-RPT'},
                         'route': '/StoresReorderLevelReport'},
                     {   'description': 'Spatial inventory mapping to manage '
                                        'Racks, Shelves, and Bins with barcode '
                                        'scanner integration.',
                         'icon': 'Grid',
                         'name': 'Barcode Entry & Rack Classification',
                         'page_id': 9,
                         'permissions': {   'Barcode Entry & Rack Classification': 'HMS-STORES-RACK-RPT'},
                         'route': '/StoresRackClassificationReport'},
                     {   'description': 'Goods Received Note (GRN) report '
                                        'categorized by Supplier / Vendor with '
                                        'tax details and payment status.',
                         'icon': 'ShieldCheck',
                         'name': 'Supplier-Based GRN Report',
                         'page_id': 10,
                         'permissions': {   'Supplier-Based GRN Report': 'HMS-STORES-SUPPLIER-GRN-RPT'},
                         'route': '/StoresSupplierGrnReport'},
                     {   'description': 'Store item requisitions (indents) '
                                        'grouped by Department with approval '
                                        'status and item quantities.',
                         'icon': 'ClipboardList',
                         'name': 'Department-Based Indent Report',
                         'page_id': 11,
                         'permissions': {   'Department-Based Indent Report': 'HMS-STORES-DEPT-INDENT-RPT'},
                         'route': '/StoresDepartmentIndentReport'},
                     {   'description': 'Track Vending Machine sales, compare '
                                        'revenue against GRN costs, and '
                                        'calculate stock reconciliation.',
                         'icon': 'ShoppingCart',
                         'name': 'Vending Machine Sales & Stock Report',
                         'page_id': 12,
                         'permissions': {   'Vending Machine Sales & Stock Report': 'HMS-STORES-VM-RPT'},
                         'route': '/VendingMachineReport'},
                     {   'description': 'Comprehensive general GRN report with '
                                        'invoice details, vendor mapping, and '
                                        'payment tracking.',
                         'icon': 'FileText',
                         'name': 'Stores GRN General Report',
                         'page_id': 13,
                         'permissions': {   'Stores GRN General Report': 'HMS-STORES-GRN-GEN-RPT'},
                         'route': '/StoresGRNGeneralReport'},
                     {   'description': 'Review, approve, and track department '
                                        'store intent requisitions.',
                         'icon': 'ClipboardList',
                         'name': 'Stores Intent Approval Report',
                         'page_id': 14,
                         'permissions': {   'Stores Intent Approval Report': 'HMS-STORES-INDENT-RET-RPT'},
                         'route': '/StoresIntentReturnReport'},
                     {   'description': 'Analysis report categorizing '
                                        'inventory items based on ABC value '
                                        'and VED criticality.',
                         'icon': 'BarChart3',
                         'name': 'Stores ABC & VED Analysis Report',
                         'page_id': 15,
                         'permissions': {   'Stores ABC & VED Analysis Report': 'HMS-STORES-ABC-VED-RPT'},
                         'route': '/StoresAbcVedReport'},
                     {   'description': 'Complete audit trail of Item Master '
                                        'opening stock values, adjustments, '
                                        'audit remarks, and user history.',
                         'icon': 'CheckCircle',
                         'name': 'Opening Stock Audit Report',
                         'page_id': 16,
                         'permissions': {   'Opening Stock Audit Report': 'HMS-STORES-OPENING-RPT'},
                         'route': '/StoresOpeningStockReport'},
                     {   'description': 'Store B2B invoice-level purchase tax register in Winman format.',
                         'icon': 'FileText',
                         'name': 'General Stores - B2B Invoices',
                         'page_id': 18,
                         'permissions': {   'General Stores - B2B Invoices': 'HMS-STORES-PURCHASE-GST-RPT'},
                         'route': '/StoreB2BReport'},
                     {   'description': 'Store items HSN code breakdown with UOM, quantity, and tax lines.',
                         'icon': 'Boxes',
                         'name': 'General Stores - HSN Wise Summary',
                         'page_id': 19,
                         'permissions': {   'General Stores - HSN Wise Summary': 'HMS-STORES-PURCHASE-GST-RPT'},
                         'route': '/StoreHSNReport'},
                     {   'description': 'Store inward invoice voucher document series and net issued numbers.',
                         'icon': 'Layers',
                         'name': 'General Stores - Document Summary',
                         'page_id': 20,
                         'permissions': {   'General Stores - Document Summary': 'HMS-STORES-PURCHASE-GST-RPT'},
                         'route': '/StoreDocsReport'}]},
    {   'group': 'Accounts Report',
        'group_id': 2,
        'order': 2,
        'pages': [   {   'description': 'Patient advance payments register '
                                        'with mode of payment breakdown.',
                         'icon': 'Wallet',
                         'name': 'Advance Registration Report',
                         'page_id': 101,
                         'permissions': {   'Advance Registration Report': 'HMS-ACC-ADV-REG-RPT'},
                         'route': '/AdvanceRegistration'},
                     {   'description': 'TPA and Corporate insurance advance '
                                        'deposits and claim ledgers.',
                         'icon': 'ShieldCheck',
                         'name': 'Insurance Advance Registration Report',
                         'page_id': 102,
                         'permissions': {   'Insurance Advance Registration Report': 'HMS-ACC-ADV-INS-RPT'},
                         'route': '/AdvanceRegistrationInsurence'},
                     {   'description': 'Comprehensive transactional audit '
                                        'report for all cash counter vouchers '
                                        'and billing adjustments.',
                         'icon': 'FileText',
                         'name': 'Accounts Audit Report',
                         'page_id': 103,
                         'permissions': {   'Accounts Audit Report': 'HMS-ACC-AUDIT-RPT'},
                         'route': '/AuditReport'},
                     {   'description': 'Detailed log of cancelled receipts '
                                        'and refunded bills with authorized '
                                        'reasons.',
                         'icon': 'MinusCircle',
                         'name': 'Bill Cancellation Register',
                         'page_id': 104,
                         'permissions': {   'Bill Cancellation Register': 'HMS-ACC-BILL-CANCEL-RPT'},
                         'route': '/BillCancelReport'},
                     {   'description': 'Itemized line-by-line revenue '
                                        'analysis per patient bill.',
                         'icon': 'FileText',
                         'name': 'Bill Wise Detailed Report',
                         'page_id': 105,
                         'permissions': {   'Bill Wise Detailed Report': 'HMS-ACC-BILL-WISE-RPT'},
                         'route': '/BillWiseReport'},
                     {   'description': 'Direct cash receipts summary '
                                        'categorized by billing heads.',
                         'icon': 'Banknote',
                         'name': 'Cash Bills Summary Report',
                         'page_id': 106,
                         'permissions': {   'Cash Bills Summary Report': 'HMS-ACC-CASH-BILLS-RPT'},
                         'route': '/CashBillsReport'},
                     {   'description': 'Detailed audit of collections per '
                                        'cashier across active shifts.',
                         'icon': 'UserCheck',
                         'name': 'Cashier-Wise Detailed Collection',
                         'page_id': 107,
                         'permissions': {   'Cashier-Wise Detailed Collection': 'HMS-ACC-CASHIER-DET-RPT'},
                         'route': '/CashierWiseDetailedReport'},
                     {   'description': 'Total cash, card, and UPI collections '
                                        'per counter operator.',
                         'icon': 'Users',
                         'name': 'Cashier-Wise Collection Summary',
                         'page_id': 108,
                         'permissions': {   'Cashier-Wise Collection Summary': 'HMS-ACC-CASHIER-WISE-RPT'},
                         'route': '/CashierWiseReport'},
                     {   'description': 'Credit card POS machine receipts and '
                                        'electronic settlement report.',
                         'icon': 'CreditCard',
                         'name': 'Credit Card & Electronic Payment Report',
                         'page_id': 109,
                         'permissions': {   'Credit Card & Electronic Payment Report': 'HMS-ACC-CREDIT-CARD-RPT'},
                         'route': '/CreditCardReport'},
                     {   'description': 'Consolidated daily collection '
                                        'statement with bank deposit handover.',
                         'icon': 'Calendar',
                         'name': 'Daily Cash Collection Report',
                         'page_id': 110,
                         'permissions': {   'Daily Cash Collection Report': 'HMS-ACC-DAILY-CASH-RPT'},
                         'route': '/DailyCashReport'},
                     {   'description': 'Summary of day-by-day revenue across '
                                        'departments for custom date ranges.',
                         'icon': 'TrendingUp',
                         'name': 'Date-Wise Collection Summary',
                         'page_id': 111,
                         'permissions': {   'Date-Wise Collection Summary': 'HMS-ACC-DATEWISE-COLL-RPT'},
                         'route': '/DatewiseCollectionSummary'},
                     {   'description': 'GST output tax collection report '
                                        'grouped per operating day.',
                         'icon': 'Percent',
                         'name': 'Day-Wise Sales Tax Register',
                         'page_id': 112,
                         'permissions': {   'Day-Wise Sales Tax Register': 'HMS-ACC-DAYWISE-TAX-RPT'},
                         'route': '/DaywiseSalesTaxRegister'},
                     {   'description': 'Pending patient receivables and '
                                        'unsettled balance dues.',
                         'icon': 'Clock',
                         'name': 'Debit & Due Bills Register',
                         'page_id': 113,
                         'permissions': {   'Debit & Due Bills Register': 'HMS-ACC-DEBIT-BILLS-RPT'},
                         'route': '/DebitBillsReport'},
                     {   'description': 'Financial revenue performance grouped '
                                        'by clinical and store departments.',
                         'icon': 'BarChart3',
                         'name': 'Department-Wise Collection Report',
                         'page_id': 114,
                         'permissions': {   'Department-Wise Collection Report': 'HMS-ACC-DEPT-WISE-RPT'},
                         'route': '/DepartmentWiseReport'},
                     {   'description': 'IP final settlement bills and '
                                        'clearance summary for discharged '
                                        'patients.',
                         'icon': 'ClipboardList',
                         'name': 'Discharge Patient Bills Summary',
                         'page_id': 115,
                         'permissions': {   'Discharge Patient Bills Summary': 'HMS-ACC-DISCHARGE-BILLS-RPT'},
                         'route': '/DischargeBills'},
                     {   'description': 'In-depth audit of pharmacy, lab, '
                                        'nursing, and room tariff on '
                                        'discharge.',
                         'icon': 'FileText',
                         'name': 'Discharge Bills Detailed Breakdown',
                         'page_id': 116,
                         'permissions': {   'Discharge Bills Detailed Breakdown': 'HMS-ACC-DISCHARGE-DET-RPT'},
                         'route': '/DischargeBillsDetailed'},
                     {   'description': 'Hospital concessions, management '
                                        'waivers, and authorized doctor '
                                        'discounts.',
                         'icon': 'Percent',
                         'name': 'Discount Bills Register',
                         'page_id': 117,
                         'permissions': {   'Discount Bills Register': 'HMS-ACC-DISCOUNT-BILLS-RPT'},
                         'route': '/DiscountBillsReport'},
                     {   'description': 'All interim running advance receipts '
                                        'deposited during inpatient stays.',
                         'icon': 'Wallet',
                         'name': 'IP Advance Collection Register',
                         'page_id': 118,
                         'permissions': {   'IP Advance Collection Register': 'HMS-ACC-IP-ADV-RPT'},
                         'route': '/IPAdvanceReport'},
                     {   'description': 'Non-patient sundry income and general '
                                        'hospital receipts.',
                         'icon': 'Banknote',
                         'name': 'Miscellaneous Payment Report',
                         'page_id': 119,
                         'permissions': {   'Miscellaneous Payment Report': 'HMS-ACC-MISC-PAY-RPT'},
                         'route': '/MiscellaneousPaymentReport'},
                     {   'description': 'Monthly GST returns filing register '
                                        'with CGST, SGST, and IGST breakdowns.',
                         'icon': 'Percent',
                         'name': 'Monthly Sales Tax Register',
                         'page_id': 120,
                         'permissions': {   'Monthly Sales Tax Register': 'HMS-ACC-SALES-TAX-RPT'},
                         'route': '/SalesTaxRegister'},
                      {   'description': 'Drug Purchase B2B invoice-level tax register in Winman GSTR-1 format.',
                          'icon': 'FileText',
                          'name': 'Drug Purchase - B2B Invoices',
                          'page_id': 126,
                          'permissions': {   'Drug Purchase - B2B Invoices': 'HMS-ACC-PURCHASE-GST-RPT'},
                          'route': '/DrugB2BReport'},
                      {   'description': 'Drug Purchase medicine HSN-wise summaries with quantity, rate, and ITC breakdowns.',
                          'icon': 'Boxes',
                          'name': 'Drug Purchase - HSN Wise Summary',
                          'page_id': 127,
                          'permissions': {   'Drug Purchase - HSN Wise Summary': 'HMS-ACC-PURCHASE-GST-RPT'},
                          'route': '/DrugHSNReport'},
                      {   'description': 'Drug Purchase inward supply invoice document series, range, and voucher counts.',
                          'icon': 'Layers',
                          'name': 'Drug Purchase - Document Summary',
                          'page_id': 128,
                          'permissions': {   'Drug Purchase - Document Summary': 'HMS-ACC-PURCHASE-GST-RPT'},
                          'route': '/DrugDocsReport'},
                      {   'description': 'General Stores inward purchase invoice tax register by tax rate.',
                          'icon': 'FileText',
                          'name': 'General Stores - B2B Invoices',
                          'page_id': 129,
                          'permissions': {   'General Stores - B2B Invoices': 'HMS-ACC-PURCHASE-GST-RPT'},
                          'route': '/StoreB2BReport'},
                      {   'description': 'General Stores product HSN summary with UOM, quantity, taxable value, and tax lines.',
                          'icon': 'Boxes',
                          'name': 'General Stores - HSN Wise Summary',
                          'page_id': 130,
                          'permissions': {   'General Stores - HSN Wise Summary': 'HMS-ACC-PURCHASE-GST-RPT'},
                          'route': '/StoreHSNReport'},
                      {   'description': 'General Stores inward invoice series, serial ranges, and cancellation counts.',
                          'icon': 'Layers',
                          'name': 'General Stores - Document Summary',
                          'page_id': 131,
                          'permissions': {   'General Stores - Document Summary': 'HMS-ACC-PURCHASE-GST-RPT'},
                          'route': '/StoreDocsReport'},
                      {   'description': 'Consolidated multi-tab register covering both Drug Purchase & General Stores.',
                          'icon': 'FileSpreadsheet',
                          'name': 'Purchase GST Register - Consolidated (GSTR-1)',
                          'page_id': 123,
                          'permissions': {   'Purchase GST Register': 'HMS-ACC-PURCHASE-GST-RPT'},
                          'route': '/PurchaseGSTReport'},
                      {   'description': 'OP Pharmacy outward patient sales invoices with Bill No as Invoice No, Customer Name, and GST tax breakdown.',
                          'icon': 'FileText',
                          'name': 'OP Pharmacy Sales - Invoices',
                          'page_id': 132,
                          'permissions': {   'OP Pharmacy Sales - Invoices': 'HMS-ACC-OP-PHARMACY-SALES-RPT'},
                          'route': '/OPPharmacyB2BReport'},
                      {   'description': 'HSN-wise medicine product sales summary with quantities, tax rates, and output GST totals.',
                          'icon': 'Boxes',
                          'name': 'OP Pharmacy Sales - HSN Wise Summary',
                          'page_id': 133,
                          'permissions': {   'OP Pharmacy Sales - HSN Wise Summary': 'HMS-ACC-OP-PHARMACY-SALES-RPT'},
                          'route': '/OPPharmacyHSNReport'},
                      {   'description': 'Document summary of OP Pharmacy outward supply bills, serial number series from/to, and cancellations.',
                          'icon': 'Layers',
                          'name': 'OP Pharmacy Sales - Document Summary',
                          'page_id': 134,
                          'permissions': {   'OP Pharmacy Sales - Document Summary': 'HMS-ACC-OP-PHARMACY-SALES-RPT'},
                          'route': '/OPPharmacyDocsReport'},
                      {   'description': 'Consolidated multi-tab sales register covering sales invoices, HSN summary, and document summary in Winman format.',
                          'icon': 'FileSpreadsheet',
                          'name': 'OP Pharmacy Sales GST Register - Consolidated (GSTR-1)',
                          'page_id': 135,
                          'permissions': {   'OP Pharmacy Sales GST Register': 'HMS-ACC-OP-PHARMACY-SALES-RPT'},
                          'route': '/OPPharmacySalesReport'},
                     {   'description': 'Cash counter shift handovers, closing '
                                        'balances, and discrepancy logs.',
                         'icon': 'Clock',
                         'name': 'Shift Basis Collection Report',
                         'page_id': 121,
                         'permissions': {   'Shift Basis Collection Report': 'HMS-ACC-SHIFT-BASIS-RPT'},
                         'route': '/ShiftBasisReport'},
                     {   'description': 'Reconciliation of medical items '
                                        'dispensed to inpatients vs '
                                        'outpatients.',
                         'icon': 'Package',
                         'name': 'IP / OP Stock Movement Report',
                         'page_id': 122,
                         'permissions': {   'IP / OP Stock Movement Report': 'HMS-ACC-STOCK-IP-OP-RPT'},
                         'route': '/StockReportIpOp'},
                     {   'description': 'IP and OP pharmacy sales returns with patient, doctor, and item details.',
                         'icon': 'RotateCcw',
                         'name': 'Sales Return Report',
                         'page_id': 136,
                         'permissions': {   'Sales Return Report': 'HMS-ACC-SALES-RETURN-RPT'},
                         'route': '/SalesReturnReport'},
                     {   'description': 'Inpatient admission and discharge comparison sorted by IP Number, with room, stay duration, advance, and company name.',
                         'icon': 'Users',
                         'name': 'Admission vs Discharge Report',
                         'page_id': 137,
                         'permissions': {   'Admission vs Discharge Report': 'HMS-ACC-ADM-DIS-RPT'},
                         'route': '/AdmissionVsDischargeReport'}]},
    {   'group': 'Hospital Reports',
        'group_id': 3,
        'order': 3,
        'pages': [   {   'description': 'Centralized hospital management and '
                                        'clinical reports portal.',
                         'icon': 'BarChart3',
                         'name': 'Central Reports Dashboard',
                         'page_id': 201,
                         'permissions': {   'Central Reports Dashboard': 'HMS-RPT-DASHBOARD'},
                         'route': '/ReportsDashboard'},
                     {   'description': 'Financial statements and hospital '
                                        'revenue ledgers.',
                         'icon': 'Wallet',
                         'name': 'General Accounts Reports',
                         'page_id': 202,
                         'permissions': {   'General Accounts Reports': 'HMS-RPT-ACCOUNTS'},
                         'route': '/AccountsReports'},
                     {   'description': 'Outpatient registrations, doctor '
                                        'consultation counts, and visit '
                                        'statistics.',
                         'icon': 'Users',
                         'name': 'Front Office & OPD Reports',
                         'page_id': 203,
                         'permissions': {   'Front Office & OPD Reports': 'HMS-RPT-FRONT-OFFICE'},
                         'route': '/FrontOfficeReports'},
                     {   'description': 'Corporate credit status and pending '
                                        'TPA approval tracker.',
                         'icon': 'ShieldCheck',
                         'name': 'Insurance & Corporate Credit Report',
                         'page_id': 204,
                         'permissions': {   'Insurance & Corporate Credit Report': 'HMS-RPT-INSURANCE-CREDIT'},
                         'route': '/InsuranceCreditReport'},
                     {   'description': 'Referral doctor statistics, PRO '
                                        'conversion analysis, and outreach '
                                        'metrics.',
                         'icon': 'TrendingUp',
                         'name': 'Marketing & Referral Analysis Report',
                         'page_id': 205,
                         'permissions': {   'Marketing & Referral Analysis Report': 'HMS-RPT-MARKETING'},
                         'route': '/MarketingReport'},
                     {   'description': 'Active warning report of medicines '
                                        'nearing expiry within 30, 60, or 90 '
                                        'days.',
                         'icon': 'AlertTriangle',
                         'name': 'Pharmacy Expiry Alert Report',
                         'page_id': 206,
                         'permissions': {   'Pharmacy Expiry Alert Report': 'HMS-RPT-PHARMACY-EXPIRY'},
                         'route': '/PharmacyExpiryReport'},
                     {   'description': 'Live dispensary stock levels and '
                                        'daily consumption trends.',
                         'icon': 'Package',
                         'name': 'Pharmacy Stock & Consumption Dashboard',
                         'page_id': 207,
                         'permissions': {   'Pharmacy Stock & Consumption Dashboard': 'HMS-RPT-PHARMACY-STOCK'},
                         'route': '/PharmacyStockDashboard'},
                     {   'description': 'Census report of ward and room '
                                        'occupancy snapshot as of yesterday '
                                        'midnight.',
                         'icon': 'Calendar',
                         'name': 'Previous Day Room Occupancy Report',
                         'page_id': 208,
                         'permissions': {   'Previous Day Room Occupancy Report': 'HMS-RPT-PRE-OCCUPANCY'},
                         'route': '/PreDayRoomOccupancyReport'},
                     {   'description': 'Live bed status showing occupied, '
                                        'vacant, cleaning, and maintenance '
                                        'beds.',
                         'icon': 'Building2',
                         'name': 'Real-Time Room Occupancy Report',
                         'page_id': 209,
                         'permissions': {   'Real-Time Room Occupancy Report': 'HMS-RPT-ROOM-OCCUPANCY'},
                         'route': '/RoomOccupencyReport'},
                     {   'description': 'Audit of patient returned medications '
                                        'and pharmacy refund slips.',
                         'icon': 'RotateCcw',
                         'name': 'Pharmacy Sales Return Report',
                         'page_id': 210,
                         'permissions': {   'Pharmacy Sales Return Report': 'HMS-RPT-SALES-RETURN'},
                         'route': '/SalesReturnReport'},
                      {   'description': 'Comprehensive corporate, ECHS, railway, and TPA insurance reports dashboard.',
                          'icon': 'ShieldCheck',
                          'name': 'Insurance Reports Dashboard',
                          'page_id': 211,
                          'permissions': {   'Insurance Reports Dashboard': 'HMS-P-FOR'},
                          'route': '/InsuranceReportsDashboard'},
                      {   'description': 'Drug purchase, procurement, inventory, and stock movement reports dashboard.',
                          'icon': 'Pill',
                          'name': 'Drug Purchase Reports Dashboard',
                          'page_id': 212,
                          'permissions': {   'Drug Purchase Reports Dashboard': 'HMS-P-DPRD'},
                          'route': '/DrugPurchaseReportsDashboard'}]},
    {   'created_by': 'system',
        'group': 'Front Office Reports',
        'group_id': 4,
        'is_active': True,
        'lastmodified_by': 'system',
        'order': 4,
        'pages': [   {   'description': 'Patients registered with a referring '
                                        'source, for the selected period.',
                         'icon': 'UserPlus',
                         'name': 'Referred Patients',
                         'page_id': 401,
                         'permissions': {   'Referred Patients': 'HMS-RPT-REFERRED-PATIENTS'},
                         'route': '/ReferredPatientsReport'},
                     {   'description': 'Full outpatient registration list for '
                                        'the selected period.',
                         'icon': 'Users',
                         'name': 'OP Patient Register',
                         'page_id': 402,
                         'permissions': {   'OP Patient Register': 'HMS-RPT-OP-PATIENTS'},
                         'route': '/OPPatientRegister'},
                     {   'description': 'IP admissions with room, doctor, and '
                                        'reason for admission.',
                         'icon': 'FileText',
                         'name': 'Admission Register',
                         'page_id': 403,
                         'permissions': {   'Admission Register': 'HMS-RPT-ADMISSION-REGISTER'},
                         'route': '/AdmissionRegister'},
                     {   'description': 'Discharged patients with '
                                        'admission/discharge dates and doctor.',
                         'icon': 'LogOut',
                         'name': 'Discharge Register',
                         'page_id': 404,
                         'permissions': {   'Discharge Register': 'HMS-RPT-DISCHARGE-REGISTER'},
                         'route': '/DischargeRegister'},
                     {   'description': 'IP billing collection totals grouped '
                                        'by doctor.',
                         'icon': 'IndianRupee',
                         'name': 'Doctor wise IP Collection',
                         'page_id': 405,
                         'permissions': {   'Doctor wise IP Collection': 'HMS-RPT-DOCTOR-WISE-IP-COLLECTION'},
                         'route': '/DoctorWiseIPCollection'},
                     {   'description': 'Newborn registrations linked to a '
                                        'mother UHID.',
                         'icon': 'Baby',
                         'name': 'New Born Babies List',
                         'page_id': 406,
                         'permissions': {   'New Born Babies List': 'HMS-RPT-NEWBORN-BABIES'},
                         'route': '/NewBornBabiesReport'},
                     {   'description': 'IP admissions grouped and filterable '
                                        'by admitting doctor.',
                         'icon': 'UserCheck',
                         'name': 'Doctor wise Admission',
                         'page_id': 407,
                         'permissions': {   'Doctor wise Admission': 'HMS-RPT-DOCTOR-WISE-ADMISSION'},
                         'route': '/DoctorWiseAdmission'},
                     {   'description': 'Live view of currently occupied rooms '
                                        'and beds.',
                         'icon': 'BedDouble',
                         'name': 'Room Occupancy Report',
                         'page_id': 408,
                         'permissions': {   'Room Occupancy Report': 'HMS-RPT-ROOM-OCCUPANCY'},
                         'route': '/RoomOccupencyReport'},
                     {   'description': 'Room occupancy as it stood at '
                                        'end-of-day for any past date.',
                         'icon': 'History',
                         'name': 'Previous Day Room Occupancy',
                         'page_id': 409,
                         'permissions': {   'Previous Day Room Occupancy': 'HMS-RPT-PRE-OCCUPANCY'},
                         'route': '/PreDayRoomOccupancyReport'},
                     {   'description': 'Comprehensive tracking of insurance '
                                        'credit bills, active admissions, room '
                                        'occupancy & lab investigations.',
                         'icon': 'ShieldCheck',
                         'name': 'Insurance & Credit Billing Report',
                         'page_id': 410,
                         'permissions': {   'Insurance & Credit Billing Report': 'HMS-RPT-INSURANCE-CREDIT'},
                         'route': '/InsuranceCreditReport'}]},
    {   'created_by': 'system',
        'group': 'Insurance Reports',
        'group_id': 5,
        'is_active': True,
        'lastmodified_by': 'system',
        'order': 5,
        'pages': [
            {
                'description': 'Real-time billing, despatch and settlement status with disallowed and due amounts.',
                'icon': 'FileText',
                'name': 'Insurance Bills Status',
                'page_id': 501,
                'permissions': {'Insurance Bills Status': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsStatus'
            },
            {
                'description': 'ECHS eligibility, polyclinic reference, and medical fitness certificates.',
                'icon': 'Award',
                'name': 'Echs Certificates',
                'page_id': 502,
                'permissions': {'Echs Certificates': 'HMS-RPT-INSURANCE'},
                'route': '/EchsCertificatesReport'
            },
            {
                'description': 'Diagnostic, biochemistry, pathology, and radiology tests ordered under credit.',
                'icon': 'Activity',
                'name': 'Lab Investigation Report',
                'page_id': 503,
                'permissions': {'Lab Investigation Report': 'HMS-RPT-INSURANCE'},
                'route': '/LabInvestigationReport'
            },
            {
                'description': 'Branch-level due amounts, pending claims, and settlement aging for insurance.',
                'icon': 'Building2',
                'name': 'Insurance Bills Status(Report Branch Wise) Dues',
                'page_id': 504,
                'permissions': {'Insurance Bills Status(Report Branch Wise) Dues': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsStatusBranchDuesReport'
            },
            {
                'description': 'Employees State Insurance (ESI) outpatient claim submissions and status.',
                'icon': 'ShieldCheck',
                'name': 'Esi Claim For Op',
                'page_id': 505,
                'permissions': {'Esi Claim For Op': 'HMS-RPT-INSURANCE'},
                'route': '/EsiClaimOpReport'
            },
            {
                'description': 'Southern Railway outpatient medical reimbursement and credit clearance log.',
                'icon': 'CheckCircle',
                'name': 'Railway Claim For Op',
                'page_id': 506,
                'permissions': {'Railway Claim For Op': 'HMS-RPT-INSURANCE'},
                'route': '/RailwayClaimOpReport'
            },
            {
                'description': 'Live and historical company-wise ward and room bed occupancy.',
                'icon': 'BedDouble',
                'name': 'Occupancy List Company Wise',
                'page_id': 507,
                'permissions': {'Occupancy List Company Wise': 'HMS-RPT-INSURANCE'},
                'route': '/OccupancyListCompanyWiseReport'
            },
            {
                'description': 'Standard inpatient discharge settlement vouchers with ticket reference.',
                'icon': 'ClipboardList',
                'name': 'Insurance Discharge Bill (Tkt)',
                'page_id': 508,
                'permissions': {'Insurance Discharge Bill (Tkt)': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceDischargeBillTktReport'
            },
            {
                'description': 'Southern Railway inpatient discharge billing statement with medical grade.',
                'icon': 'FileSpreadsheet',
                'name': 'Insurance Discharge Bill(Railway).',
                'page_id': 509,
                'permissions': {'Insurance Discharge Bill(Railway).': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceDischargeBillRailwayReport'
            },
            {
                'description': 'Surgical procedure charges, OT tariffs, and implants for ticketed insurance patients.',
                'icon': 'HeartPulse',
                'name': 'Insurance Discharge Bill (Tkt) Surgery',
                'page_id': 510,
                'permissions': {'Insurance Discharge Bill (Tkt) Surgery': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceDischargeBillTktSurgeryReport'
            },
            {
                'description': 'Pending receivable balances and overdue hospital claim accounts.',
                'icon': 'Clock',
                'name': 'Insurance Bills Due List',
                'page_id': 511,
                'permissions': {'Insurance Bills Due List': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsDueList'
            },
            {
                'description': 'Comprehensive multi-company inpatient discharge vouchers.',
                'icon': 'Layers',
                'name': 'Insurance Discharge Bill(All Company).',
                'page_id': 512,
                'permissions': {'Insurance Discharge Bill(All Company).': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceDischargeBillAllCompanyReport'
            },
            {
                'description': 'Outpatient credit consultation, day care, and pharmacy ticket clearance.',
                'icon': 'FileText',
                'name': 'Insurance Discharge Bill (Tkt) OP',
                'page_id': 513,
                'permissions': {'Insurance Discharge Bill (Tkt) OP': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceDischargeBillTktOpReport'
            },
            {
                'description': 'Registration registry of patients categorized by corporate and insurance sponsors.',
                'icon': 'Users',
                'name': 'Companywise Patient Registration',
                'page_id': 514,
                'permissions': {'Companywise Patient Registration': 'HMS-RPT-INSURANCE'},
                'route': '/CompanywisePatientRegistrationReport'
            },
            {
                'description': 'Consolidated hospital branch performance for corporate and TPA claims.',
                'icon': 'Building2',
                'name': 'Insurance Bills Status(Report Branch Wise)',
                'page_id': 515,
                'permissions': {'Insurance Bills Status(Report Branch Wise)': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsStatusBranchWiseReport'
            },
            {
                'description': 'Ex-Servicemen Contributory Health Scheme outpatient claim bills and approvals.',
                'icon': 'ShieldCheck',
                'name': 'ECHS Claim For OP',
                'page_id': 516,
                'permissions': {'ECHS Claim For OP': 'HMS-RPT-INSURANCE'},
                'route': '/EchsClaimOpReport'
            },
            {
                'description': 'Departmental laboratory tests volume, charges, and insurance recovery analysis.',
                'icon': 'BarChart3',
                'name': 'Lab Abstract Report',
                'page_id': 517,
                'permissions': {'Lab Abstract Report': 'HMS-RPT-INSURANCE'},
                'route': '/LabAbstractReport'
            },
            {
                'description': 'Pharmaceutical dispensation abstract and medicine cost share under credit.',
                'icon': 'Package',
                'name': 'Medicine Abstract Report',
                'page_id': 518,
                'permissions': {'Medicine Abstract Report': 'HMS-RPT-INSURANCE'},
                'route': '/MedicineAbstractReport'
            },
            {
                'description': 'Complete ECHS inpatient and outpatient claim dossier and approval trail.',
                'icon': 'ShieldCheck',
                'name': 'Echs Claim',
                'page_id': 519,
                'permissions': {'Echs Claim': 'HMS-RPT-INSURANCE'},
                'route': '/EchsClaimReport'
            },
            {
                'description': 'ECHS diagnostic test vouchers indexed by polyclinic referral date.',
                'icon': 'Calendar',
                'name': 'Insurance Echs Investigation Bills(Referal_Date)',
                'page_id': 520,
                'permissions': {'Insurance Echs Investigation Bills(Referal_Date)': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceEchsInvestigationReferralReport'
            },
            {
                'description': 'Daily chronological breakdown of insurance invoices and collections.',
                'icon': 'TrendingUp',
                'name': 'Date Wise Insurance Bills Details',
                'page_id': 521,
                'permissions': {'Date Wise Insurance Bills Details': 'HMS-RPT-INSURANCE'},
                'route': '/DateWiseInsuranceBillsDetailsReport'
            },
            {
                'description': 'Serial bill continuity check to prevent gaps, duplicates, or missing numbers.',
                'icon': 'Search',
                'name': 'Insurance Bill Number Checking',
                'page_id': 522,
                'permissions': {'Insurance Bill Number Checking': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillNumberCheckingReport'
            },
            {
                'description': 'Master ledger of all insurance discharge statements across departments.',
                'icon': 'ClipboardList',
                'name': 'Insurance Discharge Bill (All)',
                'page_id': 523,
                'permissions': {'Insurance Discharge Bill (All)': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceDischargeBillAllReport'
            },
            {
                'description': 'Claim performance and recovery grouped by origin polyclinic centers.',
                'icon': 'MapPin',
                'name': 'Insurance Bills Status(Polyclinic Wise)',
                'page_id': 524,
                'permissions': {'Insurance Bills Status(Polyclinic Wise)': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsStatusPolyclinicReport'
            },
            {
                'description': 'Demographics, medical officer notes, and visit log of ECHS outpatients.',
                'icon': 'UserCheck',
                'name': 'Echs Op Patient Details',
                'page_id': 525,
                'permissions': {'Echs Op Patient Details': 'HMS-RPT-INSURANCE'},
                'route': '/EchsOpPatientDetailsReport'
            },
            {
                'description': 'Clinical medication orders and pharmacy fulfillment for credit patients.',
                'icon': 'FileText',
                'name': 'Prescription Details',
                'page_id': 526,
                'permissions': {'Prescription Details': 'HMS-RPT-INSURANCE'},
                'route': '/PrescriptionDetailsReport'
            },
            {
                'description': 'Executive summary of total billed, received, TDS, and outstanding insurance.',
                'icon': 'Banknote',
                'name': 'Insurance Bills Summary',
                'page_id': 527,
                'permissions': {'Insurance Bills Summary': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsSummaryReport'
            },
            {
                'description': 'Investigation bill items for ECHS defense personnel and veterans.',
                'icon': 'Activity',
                'name': 'Insurance Echs Investigation Bills',
                'page_id': 528,
                'permissions': {'Insurance Echs Investigation Bills': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceEchsInvestigationBillsReport'
            },
            {
                'description': 'Billing and payment status strictly for outpatient credit patients.',
                'icon': 'Users',
                'name': 'Insurance Bills Status(Op Patients)',
                'page_id': 529,
                'permissions': {'Insurance Bills Status(Op Patients)': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsStatusOpPatientsReport'
            },
            {
                'description': 'Southern Railway ticketed patient inpatient discharge vouchers.',
                'icon': 'FileSpreadsheet',
                'name': 'Insurance Discharge Bill(TKT)Railway',
                'page_id': 530,
                'permissions': {'Insurance Discharge Bill(TKT)Railway': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceDischargeBillTktRailwayReport'
            },
            {
                'description': 'Comprehensive corporate and TPA insurance bills status report with patient details and dues.',
                'icon': 'ShieldCheck',
                'name': 'Insurance Bills Status Report',
                'page_id': 531,
                'permissions': {'Insurance Bills Status Report': 'HMS-RPT-INSURANCE'},
                'route': '/InsuranceBillsStatusReport'
            }
        ]
    },
    {   'created_by': 'system',
        'group': 'Drug Purchase Reports',
        'group_id': 6,
        'is_active': True,
        'lastmodified_by': 'system',
        'order': 6,
        'pages': [
            {
                'description': 'Return defective or excess goods to suppliers with automatic stock deduction and printable Debit Notes.',
                'icon': 'RotateCcw',
                'name': 'Purchase Return & Debit Notes',
                'page_id': 601,
                'permissions': {'Purchase Return & Debit Notes': 'HMS-STORES-PURCHASE-RET-RPT'},
                'route': '/DrugPurchaseReturnReport'
            },
            {
                'description': 'Analyze monthly purchase trends, vendor spend shares, top purchased goods, and price fluctuations over time.',
                'icon': 'TrendingUp',
                'name': 'Purchase Analysis Report',
                'page_id': 602,
                'permissions': {'Purchase Analysis Report': 'HMS-STORES-PURCHASE-ANALYSIS-RPT'},
                'route': '/DrugPurchaseAnalysisReport'
            },
            {
                'description': 'Daily opening stock balance, GRN inward receipts, Indent outward issues, returns, and closing valuation.',
                'icon': 'Layers',
                'name': 'Previous Day / Daily Stock Report',
                'page_id': 603,
                'permissions': {'Previous Day / Daily Stock Report': 'HMS-STORES-PREV-STOCK'},
                'route': '/DrugPreviousDayStockReport'
            },
            {
                'description': 'Comprehensive directory of suppliers with cumulative order values, total payments made, and pending dues.',
                'icon': 'Building2',
                'name': 'Supplier-Wise List & Ledger',
                'page_id': 604,
                'permissions': {'Supplier-Wise List & Ledger': 'HMS-STORES-SUPPLIER-WISE-RPT'},
                'route': '/DrugSupplierWiseReport'
            },
            {
                'description': 'Identify slow-moving and idle items with zero indents over 30 / 60 / 90 / 180+ days to prevent dead capital.',
                'icon': 'Clock',
                'name': 'Non-Moving Items Report (Dead Stock)',
                'page_id': 605,
                'permissions': {'Non-Moving Items Report (Dead Stock)': 'HMS-STORES-NON-MOVING-RPT'},
                'route': '/DrugNonMovingReport'
            },
            {
                'description': 'Early warning alert report tracking pharmaceutical and medical items nearing expiry within 30, 60, or 90 days.',
                'icon': 'AlertTriangle',
                'name': 'Short Expiry & Expired List',
                'page_id': 606,
                'permissions': {'Short Expiry & Expired List': 'HMS-STORES-SHORT-EXPIRY-RPT'},
                'route': '/DrugShortExpiryReport'
            },
            {
                'description': 'Real-time stock threshold monitoring, identifying out-of-stock and low-stock items with suggested reorder quantities.',
                'icon': 'AlertCircle',
                'name': 'Reorder Level Indication',
                'page_id': 607,
                'permissions': {'Reorder Level Indication': 'HMS-STORES-REORDER-RPT'},
                'route': '/DrugReorderLevelReport'
            },
            {
                'description': 'Spatial inventory mapping to manage Racks, Shelves, and Bins with barcode scanner integration.',
                'icon': 'Grid',
                'name': 'Barcode Entry & Rack Classification',
                'page_id': 608,
                'permissions': {'Barcode Entry & Rack Classification': 'HMS-STORES-RACK-RPT'},
                'route': '/DrugRackClassificationReport'
            },
            {
                'description': 'Goods Received Note (GRN) report categorized by Supplier / Vendor with tax details and payment status.',
                'icon': 'ShieldCheck',
                'name': 'Supplier-Based GRN Report',
                'page_id': 609,
                'permissions': {'Supplier-Based GRN Report': 'HMS-STORES-SUPPLIER-GRN-RPT'},
                'route': '/DrugSupplierGrnReport'
            },
            {
                'description': 'Store item requisitions (indents) grouped by Department with approval status and item quantities.',
                'icon': 'ClipboardList',
                'name': 'Department-Based Indent Report',
                'page_id': 610,
                'permissions': {'Department-Based Indent Report': 'HMS-STORES-DEPT-INDENT-RPT'},
                'route': '/DrugDepartmentIndentReport'
            },
            {
                'description': 'Comprehensive general GRN report with invoice details, vendor mapping, and payment tracking.',
                'icon': 'FileText',
                'name': 'Drug Purchase GRN General Report',
                'page_id': 611,
                'permissions': {'Stores GRN General Report': 'HMS-STORES-GRN-GEN-RPT'},
                'route': '/DrugGRNGeneralReport'
            },
            {
                'description': 'Review, approve, and track department store intent requisitions.',
                'icon': 'ClipboardList',
                'name': 'Drug Purchase Intent Approval Report',
                'page_id': 612,
                'permissions': {'Stores Intent Approval Report': 'HMS-STORES-INDENT-RET-RPT'},
                'route': '/DrugIntentReturnReport'
            },
            {
                'description': 'Analysis report categorizing inventory items based on ABC value and VED criticality.',
                'icon': 'BarChart3',
                'name': 'Drug Purchase ABC & VED Analysis Report',
                'page_id': 613,
                'permissions': {'Stores ABC & VED Analysis Report': 'HMS-STORES-ABC-VED-RPT'},
                'route': '/DrugAbcVedReport'
            },
            {
                'description': 'Complete audit trail of Item Master opening stock values, adjustments, audit remarks, and user history.',
                'icon': 'CheckCircle',
                'name': 'Opening Stock Audit Report',
                'page_id': 614,
                'permissions': {'Opening Stock Audit Report': 'HMS-STORES-OPENING-RPT'},
                'route': '/DrugOpeningStockReport'
            }
        ]
    }]

def seed_default_report_masters(force=False):
    collection = hms_db['hospital_reportmaster']
    now = datetime.utcnow()
    for g in DEFAULT_REPORT_GROUPS:
        update_filter = {
            '$or': [
                {'group_id': g['group_id']},
                {'group_id': str(g['group_id'])},
                {'group': g['group']}
            ]
        }
        existing = collection.find_one(update_filter)
        if not existing:
            doc = {
                'group': g['group'],
                'group_id': g['group_id'],
                'order': g.get('order', 1),
                'pages': g.get('pages', []),
                'is_active': True,
                'created_by': 'system_seed',
                'created_date': now,
                'lastmodified_date': now,
            }
            collection.insert_one(doc)
        elif force:
            collection.update_one(
                {'_id': existing['_id']},
                {
                    '$set': {
                        'group': g['group'],
                        'group_id': g['group_id'],
                        'order': g.get('order', 1),
                        'pages': g.get('pages', []),
                        'is_active': True,
                        'lastmodified_by': 'system_seed',
                        'lastmodified_date': now,
                    }
                }
            )
