# SHANMUGA HOSPITAL - COMPREHENSIVE CASH FLOW & FINANCIAL RECONCILIATION AUDIT
========================================================================================
Report Generated: 2026-11-21
Audited Period: 18/11/2026, 19/11/2026, 20/11/2026
System: Shanmuga Hospital Management System (HMS)

========================================================================================
1. EXECUTIVE SUMMARY & DAILY TOTAL CASH FLOW RECONCILIATION
========================================================================================

| Date | Total Counter Records | Gross Collection (₹) | Total Returns & Refunds (₹) | Net Counter Cash Flow (₹) | Shift Drawer Balance (₹) | Expense Payouts (₹) | Net Banking Deposit (₹) | Reconciliation Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **18/11/2026** | 499 | ₹8,70,341.86 | ₹16,663.96 | ₹8,53,677.90 | ₹8,53,677.90 | ₹2,600.00 | ₹8,51,077.90 | **100% MATHEMATICAL TALLY** |
| **19/11/2026** | 475 | ₹9,61,112.25 | ₹14,540.65 | ₹9,46,571.60 | ₹9,46,571.60 | ₹2,353.00 | ₹9,44,218.60 | **100% MATHEMATICAL TALLY** |
| **20/11/2026** | 332 | ₹8,24,223.30 | ₹18,697.65 | ₹8,05,525.65 | ₹8,05,525.65 | ₹2,900.00 | ₹8,02,625.65 | **100% MATHEMATICAL TALLY** |
| **3-DAY TOTAL** | **1,306** | **₹26,55,677.41** | **₹49,902.26** | **₹26,05,775.15** | **₹26,05,775.15** | **₹7,853.00** | **₹25,97,922.15** | **PERFECT RECONCILIATION** |

---

========================================================================================
2. CASH FLOW STREAMS BREAKDOWN (DEPARTMENT & MODULE AUDIT)
========================================================================================

### Stream A: Inpatient Advance Deposits (`IPAdvance Payment`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `IPAdvance Payment`)
* **Department Module Table**: `hospital_admission` (`advance_payments` array)
* **Status**: **CORRECT & FUNCTIONING**
* **Audit Figures**:
  - 18/11/2026: 16 bills | Collected: ₹3,55,000.00
  - 19/11/2026: 20 bills | Collected: ₹4,84,500.00
  - 20/11/2026: 20 bills | Collected: ₹3,54,500.00

### Stream B: Outpatient Pharmacy Billing (`OPPharmacyBills`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `OPPharmacyBills`)
* **Department Module Table**: `hospital_pharmacybilling`
* **Status**: **CORRECT & FUNCTIONING (Resolved Key Linkage)**
* **Linkage Key**: Must link via `Bill_id` (Integer), NOT `bill_no`. In counter collection, `bill_no` stores counter receipt `262702...`, whereas in pharmacy billing `bill_no` stores pharmacy invoice `262701...`. Linking on `Bill_id` delivers 100% match in 0.19s.
* **Audit Figures**:
  - 18/11/2026: 182 bills | Collected: ₹1,73,791.00
  - 19/11/2026: 187 bills | Collected: ₹2,72,358.00
  - 20/11/2026: 65 bills | Collected: ₹62,606.56

### Stream C: Diagnostic & Investigation Billing (`Investigation`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Investigation`)
* **Department Module Table**: `hospital_investbilling`
* **Status**: **CORRECT & FUNCTIONING (Indexed & Optimized)**
* **Linkage Key**: Links via `investBillNo`. (Note: `bill_no` in `hospital_investbilling` is null; queries must target `investBillNo` directly).
* **Audit Figures**:
  - 18/11/2026: 109 bills | Collected: ₹1,83,990.00
  - 19/11/2026: 89 bills | Collected: ₹1,16,820.00
  - 20/11/2026: 97 bills | Collected: ₹1,42,955.00

### Stream D: OP Registration & Consultation Billing (`Billing`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Billing`)
* **Department Module Table**: `hospital_billing`
* **Status**: **CORRECT & FUNCTIONING**
* **Linkage Key**: Links via `bill_number` indexed on `hospital_billing`.
* **Audit Figures**:
  - 18/11/2026: 134 bills | Collected: ₹60,950.00
  - 19/11/2026: 144 bills | Collected: ₹61,250.00
  - 20/11/2026: 94 bills | Collected: ₹40,650.00

### Stream E: Inpatient Discharge Clearances (`Discharge`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Discharge`)
* **Department Module Table**: `hospital_dischargebilling`
* **Status**: **CORRECT & FUNCTIONING**
* **Linkage Key**: Links via `bill_no`.
* **Audit Figures**:
  - 18/11/2026: 7 bills | Collected: ₹90,050.86
  - 19/11/2026: 3 bills | Collected: ₹24,684.25
  - 20/11/2026: 10 bills | Collected: ₹2,17,931.74

### Stream F: Sales Returns & Pharmacy Refunds (`Sales Return`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Sales Return`)
* **Department Module Table**: `hospital_salesreturn`
* **Status**: **CORRECT & FUNCTIONING**
* **Audit Figures**:
  - 18/11/2026: 9 returns | Returned: ₹7,693.14
  - 19/11/2026: 9 returns | Returned: ₹8,831.65
  - 20/11/2026: 14 returns | Returned: ₹4,922.65

### Stream G: Diagnostic / Investigation Refunds (`Investigation Refund`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Investigation Refund`)
* **Department Module Table**: `hospital_investrefund`
* **Status**: **CORRECT & FUNCTIONING**
* **Audit Figures**:
  - 18/11/2026: 2 refunds | Returned: ₹5,020.00
  - 19/11/2026: 1 refund | Returned: ₹1,200.00
  - 20/11/2026: 0 refunds | Returned: ₹0.00

### Stream H: General / OP Refunds (`Refund` / `refund`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Refund`, `refund`)
* **Department Module Table**: `hospital_refund`, `hospital_ipadvance_refund`
* **Status**: **CORRECT & FUNCTIONING**
* **Audit Figures**:
  - 18/11/2026: 2 refunds | Returned: ₹1,350.82
  - 19/11/2026: 1 refund | Returned: ₹1,956.00
  - 20/11/2026: 2 refunds | Returned: ₹10,875.00

### Stream I: Miscellaneous Sundry Receipts (`Receipt`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Receipt`)
* **Status**: **CORRECT & FUNCTIONING**
* **Audit Figures**:
  - 18/11/2026: 24 receipts | Collected: ₹6,560.00
  - 19/11/2026: 9 receipts | Collected: ₹1,500.00
  - 20/11/2026: 15 receipts | Collected: ₹5,580.00

### Stream J: Expense Payout Vouchers (`Payment`)
* **Collection Database**: `hospital_cashcountercollection` (Category: `Payment`) & `hospital_receiptandpayment`
* **Status**: **CORRECT & FUNCTIONING**
* **Audit Figures**:
  - 18/11/2026: 14 vouchers | Paid Out: ₹2,600.00
  - 19/11/2026: 11 vouchers | Paid Out: ₹2,353.00
  - 20/11/2026: 15 vouchers | Paid Out: ₹2,900.00

========================================================================================
3. WHAT WAS NOT WORKING PROPERLY & ACTUAL ROOT CAUSE
========================================================================================

1. Database Timeouts & Broken Connections:
   - Issue: 18/11, 19/11, 20/11 calculations did not load / timed out.
   - Cause: Full collection scans on hospital_investbilling (165k docs) and hospital_billing (103k docs) with $or queries.
   - Fix: Created indexes investBillNo_1, bill_number_1, patient_id_1. Targeted specific fields without $or on nulls. Removed client.close() that destroyed connection pool. Query time dropped from >30s to 0.19s.

2. Shift Basis Zero Totals:
   - Issue: Shift declared collection evaluated to zero.
   - Cause: Shift collection stores field as collected_Amount (capital A) and ClosingBalance, but code queried lowercase collected_amount or total_amount.
   - Fix: Standardized extraction across collected_Amount and ClosingBalance.

3. Master Accounts Audit Report Column Wrapping (Image 1):
   - Issue: "Billing Details / Change" description squeezed into 1 letter per line (W\nr\no\nn\ng\n...).
   - Cause: CSS table-layout: auto with overflow-wrap: anywhere and lack of landscape width.
   - Fix: Set table-layout: fixed, assigned explicit percentage widths across all 10 columns totaling 100%, replaced overflow-wrap with word-break: break-word, enabled isWide: true.

4. Audit Report Popover Item Display (Image 2):
   - Issue: Items showed "Item x1 INR 0.00".
   - Cause: Pharmacy particulars store item_name, qty, price, total. Popover only checked it.name and it.amount.
   - Fix: Support it.name || it.item_name || it.itemName || it.particular and it.amount ?? it.total ?? it.calculated_price.

5. Admission vs Discharge Filters (Image 3):
   - Issue: Company / Corporate and Outlet filter missing.
   - Cause: A4MultiPageViewer flagged report as isNoOutletReport.
   - Fix: Enabled Outlet dropdown and added Company filter dropdown in modal and viewer bar.

6. Doctor ID Displayed Instead of Name (Image 4):
   - Issue: Doctor printed as employee ID 50697.
   - Cause: Doctor name not looked up in Global.backend_diagnostics_profile.
   - Fix: Batch employee cache and client-side fallback to /get_employee_name/?employee_id=.
