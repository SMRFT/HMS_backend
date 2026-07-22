# Functionality Overview

This document summarizes the business logic implemented by the HMS backend — what each part of the system does for the hospital, not how the code is structured. See `CLAUDE.md` for architecture/dev-workflow notes.

The system covers front-office/patient registration, inpatient admission & billing, pharmacy & procurement, clinical departments (radiology, OT, diet, diagnosis coding), a standalone retail pharmacy unit ("Velavan"), hospital operations (assets, stores, insurance, compliance), and HR/reporting.

---

## 1. Patient Registration & Front Office

OP (outpatient) registration auto-generates a UHID using a financial-year prefix (April–March FY, e.g. `S0YY/00001`) by scanning existing records and incrementing the highest suffix — not an atomic sequence, so it's theoretically race-prone under concurrent registrations. Submitting a UHID on the registration form updates that patient instead of creating a duplicate. Every registration automatically creates a companion registration/consulting-fee `Billing` record, with `bill_type` currently hard-coded per outlet rather than driven by configuration.

A QR-code "self-registration" kiosk flow lets patients pre-fill their own details (`TempPatientRegistration`), which staff later review and convert into a real patient record. `CustomerType` (General/Insurance/Corporate…) and `InsuranceProvider` (auto-numbered `COMPnnn`) are reference masters used to categorize billing. `ReferenceDoctor` is a free-text-backed master of external referring doctors.

Registration bills can be edited (with a mandatory change reason and audit history) while unpaid, or refunded once paid — refunds are capped so cumulative refunds can never exceed what was paid, and the bill flips to "Refunded" once fully refunded.

## 2. Admission (Inpatient) & Room/Ward Management

Admitting a patient converts them to inpatient status with its own FY-scoped IP number sequence. A patient cannot have two simultaneously-active admissions. Each admission tracks an initial room/bed assignment plus a history of room transfers, each carrying open/closed and clean/dirty flags that act as a lightweight room state machine. Editing or cancelling an admission requires a mandatory reason and is fully audited; cancelling closes out any open room segments.

Room/bed **master data** (blocks, categories, nursing stations, kit items) are simple soft-deletable lookup tables. Actual bed occupancy is *derived* on the fly by combining admission room-history with room bookings (pre-reservations) — there are two parallel implementations of this occupancy logic in the codebase that don't fully agree, suggesting incomplete consolidation after a bug fix. Room bookings prevent double-booking a bed that's already reserved and not yet used.

**IP advances** (deposits) are tracked as a JSON list on the admission, using a hospital-wide (not per-admission) FY-scoped bill-number counter — explicitly fixed in-code after a prior bug caused numbers to restart per admission. Advances move Pending → Paid → Cancelled/Refunded/Edited; refunds are full-amount only (no partial refunds) and are also recorded in an independent `IpAdvance_Refund` ledger.

**Discharge** is modeled as an Estimate → Bill workflow: a discharge record can be created as an editable "Estimate" or a locked "Bill"; once billed it can never be edited again, only converted-from-estimate, preserving the estimate number for audit. The discharge screen aggregates the patient, latest admission, and any unpaid investigation bills.

## 3. Billing & Accounts

Four billing flows sit on shared conventions (FY/bill-type sequential numbering, mandatory edit/delete reasons, full audit history, soft-delete instead of hard delete):

- **OP/Investigation billing** — the main money-taking flow for lab/radiology/procedures. Refunds are partial: a cashier selects specific line items off a paid bill, and refunded items are automatically excluded from that bill's report so nothing double-counts.
- **Estimate billing** — pre-quotes a patient; converting an estimate to a real bill deactivates the estimate.
- **Discharge billing** — the IP settlement flow (see above).
- **Bill Type Master / Investigation Price** — pricing configuration: bill types are system-numbered (never client-supplied) and carry behavior flags (allows discount, IP-only, triggers pharmacy dispatch); investigation prices are a per-bill-type price matrix, edited item-by-item without disturbing other bill types' prices.

**Cash counters & shifts**: a cashier's counter is derived from their employee profile, not chosen manually, and only one active shift per counter/outlet is allowed at a time. Every payment collected anywhere in the system (registration, investigation, discharge, pharmacy, IP advances, refunds) must reference an active shift. Closing a shift recomputes the actual collected total from the underlying ledger (not client-supplied numbers) and calculates closing balance as opening + collected − remitted − submitted − handover, writing remittance/submission entries back into a central collection ledger for auditability.

**Accounts reporting** all reads from that same central collection ledger rather than re-deriving figures per module — bill-wise reports, shift-basis reports, and shift close-out summaries are the main outputs, plus supplementary reports for pending collections and deleted/cancelled bills.

**Known inconsistencies**: shift-summary and registration-bill report logic is duplicated near-verbatim between `cashcounter.py` and `AccountsReport/accounting_reports.py`, with the two versions sourcing numbers differently (could drift out of sync); some report endpoints have permission checks disabled or missing entirely; several numbering schemes use non-atomic "find max, add one" logic instead of an atomic counter.

## 4. Pharmacy & Procurement

**Dispensing** follows Estimate → Billed → Paid. Adding/removing/changing medicine lines on a bill doesn't touch real stock — it only places a `blocked_quantity` hold on the batch, with a full edit history. Stock is only actually deducted (`sold_quantity`) at the moment payment is collected. Deleting a paid bill reverses the sold quantity but is a soft delete. For IP patients, pharmacy charges are capped against that admission's paid advance balance.

Available stock is computed uniformly everywhere as: `total − sold − transferred_out − grn_returned − blocked + sales_returned`. Low stock triggers at ≤ reorder level; a daily job flags items expiring within 90 days (critical under 30) and stock below reorder level (critical under 30%).

**Procurement** is a three-document chain: Purchase Requisition → Purchase Order → GRN (Goods Receipt Note). PR status (Draft → Approved/Rejected → PO Initiated → Purchased → Restocked) is tracked purely for audit — nothing automatically creates a PO or touches stock when a PR advances. POs are simpler (Draft → Approved/Rejected) and can email the vendor a formatted purchase order. Both PR and PO lock once approved/rejected.

**GRN is the only place stock actually enters the system**, and only at the Draft → Verified transition (one-way, irreversible) — a Verified GRN creates brand-new stock batch rows with parsed expiry/MRP/tax. Editing a Draft GRN repeatedly never touches stock; stock is created exactly once, at verification.

**Stock transfer** between outlets only moves stock at approval time (creation just validates availability), so a pending transfer can theoretically be oversold elsewhere before approval re-checks availability. **Physical stock entry** records a manual count vs. system count as a variance, but approving it never actually adjusts stock — it's a logging/audit exercise only, with no reconciliation mechanism wired up.

**Returns**: Purchase returns (to vendor) are validated against a specific GRN's batch stock and require a cause, but their status progression never actually decrements the batch's `grn_return_quantity` despite that field being part of the availability formula — an apparently incomplete wiring. Sales returns (from patients) are allowed within 30 days of billing, tracked cumulatively per line, but explicitly do *not* restore sellable stock (`sales_return_quantity` is not updated) — meaning returned medicine doesn't automatically become available for resale.

## 5. Clinical Departments

**Radiology & lab reporting** covers CT/MRI/USG/X-Ray and a special ANC (antenatal) register. Reports carry a turn-around-time engine (check-in → scan start → completion vs. a configured target time per test) and appointment-slot punctuality tracking (early/late/no-show). Reports require approval before they can be dispatched to the patient. A separate register aggregates approved ANC/general reports for statutory reporting.

**OT & surgery scheduling** assigns each surgery an FY-based reference number and a status lifecycle (Scheduled → Confirmed → Completed, or Postponed/Cancelled). The listing enriches raw schedules with patient, OT, anesthesia, and surgeon/anaesthetist names (supporting a primary plus multiple "additional" doctors). Bundled into the same area: OT medicine ward requests (billed against pharmacy stock) and surgical implant requests, which re-evaluate from Pending to "Invoice Generated" once a matching paid sales invoice appears.

**Diet orders** for inpatients start as "Ordered" (editable only in that state) and progress through Received/Delivered/Cancelled, priced from a diet + extras catalog; a reporting view supports kitchen/dietary planning across date ranges.

**ICD-11 diagnosis coding** is a thin cached-token proxy to the WHO ICD-11 API for diagnosis search/lookup — it's a pure reference lookup with no visible code path that writes the selected code back onto a patient record, implying that link happens elsewhere or client-side.

**Doctor dashboards/reports** compute per-doctor KPIs (OP/IP volumes, revenue, trends) by matching doctor name strings across billing/admission records rather than a stable doctor ID — fragile if a doctor's name is entered inconsistently.

**Patient complaints** are a simple grievance tracker (reporter, assignee, department, status defaulting to "Pending"), with an admin view bucketing pending vs. completed complaints.

## 6. Velavan — Standalone Retail Pharmacy Unit

"Velavan" is a self-contained retail pharmacy/shop running inside the same backend, with its own vendor master, customer master, item catalog, and full purchase → sale → return cycle, independent of the hospital's main Stores/pharmacy inventory (separate vendor/customer collections with GSTIN/PAN/MSME fields typical of an external trading entity).

Workflow: a purchase invoice against a vendor must be approved before its lines become real stock batches; sales bills deduct from those batches; sales returns are allowed only within 30 days and can't exceed remaining quantity; purchase returns are checked against actual available stock. Duplicate invoice detection (vendor + invoice number) blocks double entry.

Despite being a separate ledger, Velavan bills also carry hospital-specific fields (IP number, patient name, surgeon, insurer) with a helper to resolve hospital patient/insurance/surgeon data by IP number — so its sales can still be attributed to a specific hospital patient episode. The module has notable unfinished-cleanup markers (manual re-serialization workarounds for ORM/JSON issues, and debug output flagged "remove once diagnosed" still present).

## 7. Hospital Operations

- **Asset management**: registers fixed assets with an auto-generated ID, logs periodic maintenance, and supports recycling/disposal — but recycling records don't actually flip the parent asset's active status, so retirement and deactivation are tracked as unlinked records rather than one lifecycle.
- **Stores/Inventory** (separate from pharmacy and Velavan): items organized under Department/Group/Category hierarchies, stocked via GRN (increments total quantity on approval), and issued to departments via "Stores Intents" (increments/reverses an approved-quantity reservation). Available stock to a department is total minus approved.
- **Insurance claims**: a simple Pending/Approved/Rejected status field with no enforced state machine, linked to a patient admission and the hospital's `InsuranceProvider` master.
- **Crash cart safety checks**: daily per-nursing-station verification that required emergency drugs are present and not expired, with a monthly compliance report reconstructing a full calendar of check/expiry status.
- **Licence & compliance tracking**: hospital regulatory licences with configurable reminder thresholds (90/60/30/7/1 days before expiry) — the automated expiry-check/reminder endpoint referenced in the views is currently commented out (dead code); only CRUD is active there (the actual reminder emails are sent by a separate scheduled command, see below).

## 8. HR, Communication & Reporting

**Internship program**: end-to-end management of student interns — registration, fee computation (monthly + hostel fee − discounts), installment tracking against a Pending/Partially Paid/Fully Paid balance, and a certificate workflow (template selection, edit, approval, send) cross-referenced against the communication log to confirm delivery. Intern IDs use an FY prefix (e.g. `25SHINT001`).

**Communication logging** is a shared audit layer for every outbound email/WhatsApp message (reports, discharge summaries, certificates, payment reminders) — sender, recipient, template, success/failure, and provider response — queryable as a delivery audit trail. WhatsApp goes through a third-party template API; email through SMTP with a branded template, optionally via a dedicated HR mailbox.

**Document OCR** auto-fills GRN/invoice entry forms from a scanned invoice (PDF or image): converts pages to images, tries a primary OCR engine with Tesseract as fallback, then regex-extracts invoice/vendor/tax/line-item data, pre-filling fields the pharmacist must confirm. This endpoint currently has authentication disabled (permission check commented out).

**Dashboards**: a basic dashboard (today's registrations/visits/trend) and an advanced executive dashboard (lifetime OP/IP counts, occupied beds, revenue by source, income-vs-expense trend, payment-method mix, top doctors, bed occupancy). Marketing reports aggregate registrations by area/zipcode with revenue for outreach targeting; room-occupancy reports show current or historical (as-of-date) bed occupancy.

**Scheduled email jobs** (run as long-lived daemon processes, not a task queue):
- Daily (~10:00 AM IST) HR email of interns with outstanding fee balances.
- Compliance licence expiry reminders at 90/60/30/7/1-day thresholds, marking each threshold sent so it never re-fires (this is the job that actually implements licence expiry alerting, separate from the dead code noted above).
- A cleanup job that deletes stale ("Estimate") pharmacy bills older than 24 hours, releasing their blocked stock back to inventory and archiving a deletion log — preventing abandoned draft estimates from permanently locking stock.

---

## Cross-Cutting Observations

- **Multi-tenancy**: nearly every record is scoped by `hospital_code`/`branch_code`/`outlet_code`, inherited from a shared `AuditModel` base.
- **Numbering conventions**: most business documents (UHID, IP number, bills, GRNs, POs, surgery references) use an Indian financial-year prefix (April–March) with a sequential suffix computed by scanning existing records rather than an atomic counter — a recurring, acknowledged source of race conditions, with at least one documented past bug (advance-payment numbering resetting per admission).
- **Soft delete over hard delete**: almost universally, "delete" sets `is_active=False` (or an equivalent flag) with a mandatory reason and audit stamp, rather than removing data.
- **Mandatory-reason audit trail**: edits and cancellations across billing, admissions, requisitions, and purchase documents consistently require a free-text reason and are appended to an in-record history array.
- **Incomplete stock reconciliation**: several workflows that *should* adjust stock quantities (physical stock verification, purchase returns, sales returns) currently only record status/audit data without completing the corresponding stock-ledger update — worth confirming with the business whether this is intentional or a gap.
- **Djongo/MongoDB friction**: multiple modules (Velavan, Admission) contain explicit workarounds for the Djongo ORM mishandling JSON array fields, including direct raw MongoDB writes after ORM saves.
