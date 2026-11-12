# InvoiceIQ — Zamp ASA Case Study (PS-1)

## What it does
A runnable Accounts Payable workflow that accepts an invoice PDF, extracts key fields, matches it against a purchase-order master, applies validation rules, and returns an explainable decision:
- **APPROVED** — vendor and PO match, vendor is approved, amount is within tolerance.
- **PENDING** — missing information, missing PO, unreadable/scanned PDF, or amount variance above tolerance.
- **REJECTED** — duplicate invoice number, vendor mismatch, or unapproved vendor.

The app includes a live run result, run history dashboard, decision reasons, extracted-text view, and CSV export.

## Run locally
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run: `pip install -r requirements.txt`
4. Run: `streamlit run app.py`
5. Open the local URL printed in the terminal (usually http://localhost:8501).

## Files
- `app.py` — Streamlit workflow and validation logic.
- `purchase_orders.csv` — sample PO master data.
- `sample_invoices/` — test invoices for happy path and edge cases.
- `run_history.json` — created automatically after processing.

## Test plan
1. `happy_path_invoice.pdf` → APPROVED (PO amount matches).
2. `amount_variance_invoice.pdf` → PENDING (variance exceeds tolerance).
3. `vendor_mismatch_invoice.pdf` → REJECTED (vendor on invoice differs from PO).
4. `missing_po_invoice.pdf` → PENDING (no matching PO).
5. Process the happy-path invoice twice → second run is REJECTED as duplicate.

## Assumptions and limitations
- The prototype uses text extraction from digital PDFs, not an external LLM or OCR service.
- Scanned/image-only PDFs are safely routed to PENDING rather than guessed.
- The PO master is a CSV for demonstration; production would connect to the procurement/ERP system.
- Amount tolerance is configured per PO in `purchase_orders.csv`.
- This is a decision-support workflow. Payment is never initiated automatically; AP retains control.

## Architecture
PDF upload → text extraction → required-field validation → duplicate check → PO/vendor match → vendor approval check → amount tolerance check → decision + audit history.

## Edge cases demonstrated
- Amount outside tolerance: pending for human review.
- Vendor name mismatch: rejected with a specific reason.
- Missing PO: pending rather than silently approving.
- Duplicate invoice: rejected based on prior processing history.
