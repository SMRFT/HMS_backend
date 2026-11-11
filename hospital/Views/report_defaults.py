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
                         'route': '/StoresOpeningStockReport'}]},
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
                         'route': '/StockReportIpOp'}]},
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
                         'route': '/SalesReturnReport'}]},
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
                         'route': '/InsuranceCreditReport'}]}]

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
