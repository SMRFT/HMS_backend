"""
Core Payment & Transaction Ledger Engine
Standardized transaction parsing, split-payment decomposition,
and shift reconciliation utilities for Shanmuga Hospital Limited HMS.

Accounting Standard:
- cash_amount: Physical cash / currency notes in cashier drawer.
- credit_amount: All non-cash collections (Card, POS, UPI, Cheque, Online, and Receivables/Credit).
- Granular breakdown (bank, card, upi, cheque) is preserved for specific reconciliation reports.
"""

from decimal import Decimal
import json
import ast
import re


def clean_numeric(val, default=0.0):
    """Safely converts numbers, Decimal, Decimal128, or string representations to float."""
    if val is None:
        return default
    if hasattr(val, 'to_decimal'):
        try:
            return float(val.to_decimal())
        except Exception:
            pass
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    try:
        s = str(val).strip().replace(',', '')
        return float(s)
    except Exception:
        return default


def parse_transaction_breakdown(doc_or_amt, total_amount_or_mode=0.0, payment_details=None):
    """
    Standardized payment breakdown extractor for all HMS modules.
    Handles Single Payment, Split / Multiple Payment, Advance Adjustment,
    and Credit/Insurance Claims.
    
    Accepts either:
      parse_transaction_breakdown(doc, total_amount=0.0)
      or
      parse_transaction_breakdown(total_amount, payment_mode="Cash", payment_details={...})

    Returns:
    {
        "cash_amount": float,        # Physical cash in drawer
        "credit_amount": float,      # ALL non-cash collections (Bank, Card, UPI, Cheque, Credit)
        "bank_amount": float,        # Bank total (Card + UPI + Cheque + NEFT)
        "card_amount": float,        # POS card swipe amount
        "upi_amount": float,         # UPI / QR amount
        "cheque_amount": float,      # Cheque / DD amount
        "credit_due_amount": float,  # Uncollected receivables / Insurance
        "advance_adjusted": float,   # Advance adjusted
        "primary_mode": str,         # "Cash", "Card", "UPI", "Multiple Payment", "Credit"
        "breakdown": list            # [{"method": "Cash", "amount": 9600.0}, ...]
    }
    """
    if isinstance(doc_or_amt, (int, float, Decimal)) or (isinstance(doc_or_amt, str) and not isinstance(doc_or_amt, dict)):
        tot = clean_numeric(doc_or_amt, default=0.0)
        p_mode = str(total_amount_or_mode or "").strip()
        pd = payment_details if isinstance(payment_details, dict) else {}
        doc = {"payment_mode": p_mode, "payment_details": pd, "amount": tot}
    else:
        doc = doc_or_amt if isinstance(doc_or_amt, dict) else {}
        tot = clean_numeric(total_amount_or_mode, default=0.0)

    if not isinstance(doc, dict):
        return {
            "cash_amount": tot,
            "credit_amount": 0.0,
            "bank_amount": 0.0,
            "card_amount": 0.0,
            "upi_amount": 0.0,
            "cheque_amount": 0.0,
            "credit_due_amount": 0.0,
            "advance_adjusted": 0.0,
            "primary_mode": "Cash",
            "breakdown": [{"method": "Cash", "amount": tot}] if tot > 0 else []
        }

    pd = doc.get("payment_details") or {}
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            try:
                pd = ast.literal_eval(pd)
            except Exception:
                pd = {}

    cash_amt = 0.0
    card_amt = 0.0
    upi_amt = 0.0
    cheque_amt = 0.0
    bank_other_amt = 0.0
    credit_due_amt = 0.0
    adv_adj_amt = 0.0
    breakdown_list = []
    primary_mode = None

    # 1. Inspect breakdown array in payment_details (Split / Multiple Payment)
    breakdown = pd.get("breakdown") if isinstance(pd, dict) else None
    if isinstance(breakdown, list) and len(breakdown) > 0:
        primary_mode = "Multiple Payment"
        for item in breakdown:
            if not isinstance(item, dict):
                continue
            m = str(item.get("method") or item.get("payment_mode") or "").strip().lower()
            amt = clean_numeric(item.get("Paid_amount") or item.get("amount") or item.get("paid_amount") or 0)
            if amt == 0.0:
                continue

            if "cash" in m:
                cash_amt += amt
                breakdown_list.append({"method": "Cash", "amount": amt})
            elif "card" in m or "pos" in m or "visa" in m or "master" in m:
                card_amt += amt
                breakdown_list.append({"method": "Card", "amount": amt, "ref_no": str(item.get("card_no") or "")})
            elif any(k in m for k in ["upi", "gpay", "phonepe", "paytm", "qr", "bhim"]):
                upi_amt += amt
                breakdown_list.append({"method": "UPI", "amount": amt, "ref_no": str(item.get("upi_id") or "")})
            elif any(k in m for k in ["cheque", "checque", "check", "chq", "dd", "demand draft"]):
                cheque_amt += amt
                breakdown_list.append({"method": "Cheque", "amount": amt, "ref_no": str(item.get("cheque_no") or "")})
            elif any(k in m for k in ["credit", "insurance", "tpa", "cghs", "echs", "railway", "scheme"]):
                credit_due_amt += amt
                breakdown_list.append({"method": "Credit", "amount": amt})
            elif "advance" in m:
                adv_adj_amt += amt
                breakdown_list.append({"method": "Advance Adjusted", "amount": amt})
            else:
                bank_other_amt += amt
                breakdown_list.append({"method": "Bank", "amount": amt})

        # Ratio adjustment if breakdown sum slightly differs from total
        split_sum = cash_amt + card_amt + upi_amt + cheque_amt + bank_other_amt + credit_due_amt + adv_adj_amt
        if tot > 0 and split_sum > 0 and abs(split_sum - tot) > 0.05:
            ratio = tot / split_sum
            cash_amt = round(cash_amt * ratio, 2)
            card_amt = round(card_amt * ratio, 2)
            upi_amt = round(upi_amt * ratio, 2)
            cheque_amt = round(cheque_amt * ratio, 2)
            bank_other_amt = round(bank_other_amt * ratio, 2)
            credit_due_amt = round(credit_due_amt * ratio, 2)
            adv_adj_amt = round(adv_adj_amt * ratio, 2)

    # 2. Single method in payment_details
    elif isinstance(pd, dict) and pd.get("method"):
        m = str(pd.get("method")).strip().lower()
        amt = clean_numeric(pd.get("Paid_amount") or pd.get("amount") or tot)
        if amt == 0.0 and tot > 0.0:
            amt = tot

        if "cash" in m:
            cash_amt = amt
            primary_mode = "Cash"
            breakdown_list.append({"method": "Cash", "amount": amt})
        elif "card" in m or "pos" in m:
            card_amt = amt
            primary_mode = "Card"
            breakdown_list.append({"method": "Card", "amount": amt, "ref_no": str(pd.get("card_no") or "")})
        elif any(k in m for k in ["upi", "gpay", "phonepe", "paytm", "qr"]):
            upi_amt = amt
            primary_mode = "UPI"
            breakdown_list.append({"method": "UPI", "amount": amt, "ref_no": str(pd.get("upi_id") or "")})
        elif any(k in m for k in ["cheque", "checque", "check", "chq", "dd"]):
            cheque_amt = amt
            primary_mode = "Cheque"
            breakdown_list.append({"method": "Cheque", "amount": amt, "ref_no": str(pd.get("cheque_no") or "")})
        elif any(k in m for k in ["credit", "insurance", "tpa", "scheme", "cghs", "echs"]):
            credit_due_amt = amt
            primary_mode = "Credit"
            breakdown_list.append({"method": "Credit", "amount": amt})
        elif "advance" in m:
            adv_adj_amt = amt
            primary_mode = "Advance"
            breakdown_list.append({"method": "Advance Adjusted", "amount": amt})
        else:
            bank_other_amt = amt
            primary_mode = "Bank"
            breakdown_list.append({"method": "Bank", "amount": amt})

    # 3. Fallback to document-level mode fields
    if not primary_mode:
        for k in ["payment_mode", "payment_method", "paymentMethod", "PaymentType", "mode_of_payment"]:
            val = str(doc.get(k) or "").strip().lower()
            if not val or val == "none":
                continue
            amt = tot
            if "cash" in val:
                cash_amt = amt
                primary_mode = "Cash"
                breakdown_list.append({"method": "Cash", "amount": amt})
                break
            elif "card" in val or "pos" in val:
                card_amt = amt
                primary_mode = "Card"
                breakdown_list.append({"method": "Card", "amount": amt})
                break
            elif any(term in val for term in ["upi", "gpay", "phonepe", "paytm", "qr"]):
                upi_amt = amt
                primary_mode = "UPI"
                breakdown_list.append({"method": "UPI", "amount": amt})
                break
            elif any(term in val for term in ["cheque", "chq", "dd"]):
                cheque_amt = amt
                primary_mode = "Cheque"
                breakdown_list.append({"method": "Cheque", "amount": amt})
                break
            elif any(term in val for term in ["credit", "insurance", "tpa", "cghs", "echs"]):
                credit_due_amt = amt
                primary_mode = "Credit"
                breakdown_list.append({"method": "Credit", "amount": amt})
                break
            elif any(term in val for term in ["bank", "online", "neft", "rtgs", "imps"]):
                bank_other_amt = amt
                primary_mode = "Bank"
                breakdown_list.append({"method": "Bank", "amount": amt})
                break

    # 4. Final default to Cash
    if not primary_mode:
        cash_amt = tot
        primary_mode = "Cash"
        if tot > 0:
            breakdown_list.append({"method": "Cash", "amount": tot})

    bank_total = round(card_amt + upi_amt + cheque_amt + bank_other_amt, 2)
    # USER ARCHITECTURAL ALIGNMENT: All non-cash collections fall under credit_amount
    all_credit_total = round(bank_total + credit_due_amt, 2)

    return {
        "cash_amount": round(cash_amt, 2),
        "credit_amount": all_credit_total,
        "bank_amount": bank_total,
        "card_amount": round(card_amt, 2),
        "upi_amount": round(upi_amt, 2),
        "cheque_amount": round(cheque_amt, 2),
        "credit_due_amount": round(credit_due_amt, 2),
        "advance_adjusted": round(adv_adj_amt, 2),
        "primary_mode": primary_mode,
        "breakdown": breakdown_list
    }


def get_shift_aliases(shift_no):
    """
    Generates all canonical string and integer variants of a shift number
    to prevent orphaned bills caused by formatting differences (slashed vs unslashed).
    e.g. "2627/01/000060" -> ["2627/01/000060", "262701000060", 262701000060]
    """
    s = str(shift_no or "").strip()
    if not s or s.lower() == "none":
        return []
    aliases = {s}
    unslashed = s.replace("/", "")
    aliases.add(unslashed)
    try:
        aliases.add(int(unslashed))
    except (ValueError, TypeError):
        pass

    # Unslashed to slashed conversions
    if "/" not in s:
        if len(s) == 12:
            # 262701000060 -> 2627/01/000060
            aliases.add(f"{s[:4]}/{s[4:6]}/{s[6:]}")
        elif len(s) == 10:
            # 2627000060 -> 2627/000060
            aliases.add(f"{s[:4]}/{s[4:]}")

    return list(aliases)


def is_cash_return_or_refund(doc):
    """
    Checks if a return or refund resulted in physical cash leaving the cashier's drawer.
    Returns True only if refund mode was Cash or unspecified cash return.
    Returns False if refunded via Bank Transfer, NEFT, Cheque, or Credit Note.
    """
    if not isinstance(doc, dict):
        return True

    pd = doc.get("payment_details") or {}
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            try:
                pd = ast.literal_eval(pd)
            except Exception:
                pd = {}

    m = ""
    if isinstance(pd, dict):
        m = str(pd.get("method") or pd.get("payment_mode") or "").strip().lower()
    if not m:
        for k in ["PaymentType", "payment_mode", "payment_method", "refund_mode", "refund_type"]:
            val = str(doc.get(k) or "").strip().lower()
            if val and val != "none":
                m = val
                break

    if not m:
        return True  # Standard counter return defaults to cash payout

    # If explicitly non-cash (NEFT, Bank, Credit Note, Card Reversal), not from cash drawer
    if any(k in m for k in ["bank", "neft", "rtgs", "online", "card", "upi", "credit", "note", "cheque"]):
        return False

    return True
