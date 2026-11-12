# 5-minute demo narration

**0:00–0:30 — Introduce the problem**
"Invoice processing is repetitive and error-prone. InvoiceIQ automates the first-pass AP checks while keeping a human in control of exceptions."

**0:30–1:30 — Happy path**
"First, I upload a digital invoice PDF. The system extracts invoice number, date, vendor, PO reference and total. It then checks the PO master, vendor approval, duplicate history and amount tolerance. This invoice is approved because all checks pass."

**1:30–2:30 — Amount variance**
"Now I upload the BluePeak invoice. The amount is above the PO tolerance, so the workflow marks it Pending and explains the variance. It does not auto-approve an uncertain invoice."

**2:30–3:30 — Vendor mismatch / missing PO**
"Here the invoice vendor does not match the vendor on the PO, so it is Rejected with the mismatch reason. A missing PO is routed to Pending for AP resolution."

**3:30–4:30 — Dashboard and audit trail**
"Every run is recorded with timestamp, filename, extracted fields, status and reasoning. I can inspect extracted text and export the run history."

**4:30–5:00 — Design choices**
"I chose deterministic validation rules for financial decisions because they are explainable. In production, I would add OCR for scanned PDFs, ERP integration, role-based approvals and secure audit storage. The system never initiates payment; it prepares a decision for the AP team."
