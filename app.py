import streamlit as st
import pandas as pd
import pdfplumber
import re
import json
import os
from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)

# ---------------------------------------------------------
# InvoiceIQ | Accounts Payable Automation
# Candidate case study: PS-1 Finance / AP
# Developed by Muniya Vidushi
# ---------------------------------------------------------

st.set_page_config(
    page_title="InvoiceIQ | AP Automation",
    page_icon="🧾",
    layout="wide"
)

HISTORY_FILE = "run_history.json"
PO_FILE = "purchase_orders.csv"


# ------------------------- Helpers -------------------------

def money_to_float(value):
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(value).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def extract_invoice(pdf_file):
    """Extract key fields from a text-based PDF invoice."""
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += "\n" + (page.extract_text() or "")

    patterns = {
        "invoice_number": r"(?:Invoice\s*(?:No\.?|Number|#))\s*[:\-]?\s*([A-Za-z0-9\-\/]+)",
        "invoice_date": r"(?:Invoice\s*Date|Date)\s*[:\-]?\s*([0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
        "po_number": r"(?:PO\s*(?:No\.?|Number|#)|Purchase\s*Order)\s*[:\-]?\s*([A-Za-z0-9\-\/]+)",
        "vendor": r"(?:Vendor|Supplier|From)\s*[:\-]?\s*([A-Za-z0-9&.,()\- ]+)",
        "total": r"(?:Grand\s*Total|Invoice\s*Total|Total\s*Due|Total)\s*[:\-]?\s*(?:INR|Rs\.?|₹|\$)?\s*([0-9,]+(?:\.[0-9]{1,2})?)"
    }

    fields = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        fields[key] = match.group(1).strip(" .") if match else None

    fields["total"] = money_to_float(fields.get("total"))
    fields["raw_text"] = text.strip()
    return fields


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(history[-200:], file, indent=2)


def validate_invoice(invoice, po_df, history):
    """Apply deterministic AP rules and return status, reasons and check details."""
    required_fields = {
        "invoice_number": "Invoice number",
        "invoice_date": "Invoice date",
        "po_number": "PO number",
        "vendor": "Vendor",
        "total": "Invoice total"
    }

    missing = [
        label for key, label in required_fields.items()
        if invoice.get(key) in (None, "")
    ]

    checks = {
        "Required fields": "PASS" if not missing else "FAIL",
        "Duplicate check": "NOT RUN",
        "PO match": "NOT RUN",
        "Vendor match": "NOT RUN",
        "Vendor approval": "NOT RUN",
        "Amount tolerance": "NOT RUN"
    }

    if missing:
        return "PENDING", ["Missing required information: " + ", ".join(missing) + "."], checks

    duplicate_found = any(
        str(item.get("invoice_number", "")).strip().lower()
        == str(invoice["invoice_number"]).strip().lower()
        for item in history
    )
    if duplicate_found:
        checks["Duplicate check"] = "FAIL"
        return "REJECTED", ["Duplicate invoice number already exists in processing history."], checks

    checks["Duplicate check"] = "PASS"

    matches = po_df[
        po_df["po_number"].astype(str).str.strip().str.lower()
        == str(invoice["po_number"]).strip().lower()
    ]

    if matches.empty:
        checks["PO match"] = "FAIL"
        return "PENDING", ["No matching purchase order found. Route to AP for manual PO resolution."], checks

    checks["PO match"] = "PASS"
    po = matches.iloc[0]

    vendor_match = (
        str(po["vendor"]).strip().lower()
        == str(invoice["vendor"]).strip().lower()
    )
    checks["Vendor match"] = "PASS" if vendor_match else "FAIL"

    if not vendor_match:
        return "REJECTED", [
            f"Vendor mismatch: invoice says '{invoice['vendor']}', "
            f"PO lists '{po['vendor']}'."
        ], checks

    vendor_approved = str(po["approved"]).strip().lower() in [
        "yes", "true", "1", "approved"
    ]
    checks["Vendor approval"] = "PASS" if vendor_approved else "FAIL"

    if not vendor_approved:
        return "REJECTED", [
            "Vendor is not marked as approved in the purchase-order master."
        ], checks

    po_amount = float(po["po_amount"])
    tolerance_pct = float(po.get("tolerance_pct", 2.0))
    variance_pct = (
        abs(float(invoice["total"]) - po_amount) / po_amount * 100
        if po_amount else 100.0
    )

    within_tolerance = variance_pct <= tolerance_pct
    checks["Amount tolerance"] = "PASS" if within_tolerance else "FAIL"

    if not within_tolerance:
        return "PENDING", [
            f"Amount variance is {variance_pct:.2f}%, above the allowed "
            f"{tolerance_pct:.2f}% tolerance. Manual review required."
        ], checks

    return "APPROVED", [
        f"Vendor and PO matched. Amount variance is {variance_pct:.2f}%, "
        f"within the allowed {tolerance_pct:.2f}% tolerance."
    ], checks


def status_color(status):
    return {
        "APPROVED": "#15803d",
        "PENDING": "#b45309",
        "REJECTED": "#b91c1c"
    }.get(status, "#475569")


def build_decision_pdf(run_record):
    """Create a downloadable PDF decision report for one processed invoice."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontSize=21,
        leading=25,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#17365D"),
        spaceAfter=5
    ))
    styles.add(ParagraphStyle(
        name="SmallNote",
        parent=styles["BodyText"],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#64748B")
    ))
    styles.add(ParagraphStyle(
        name="Decision",
        parent=styles["Heading2"],
        fontSize=16,
        leading=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor(status_color(run_record.get("status", ""))),
        spaceBefore=8,
        spaceAfter=12
    ))

    story = [
        Paragraph("InvoiceIQ", styles["ReportTitle"]),
        Paragraph("Invoice Processing &amp; Validation Decision Report", styles["Heading2"]),
        Paragraph("Developed by Muniya Vidushi | AI Solutions Analyst — Candidate Case Study PS-1", styles["SmallNote"]),
        Spacer(1, 8),
        Paragraph(f"DECISION: {run_record.get('status', 'UNKNOWN')}", styles["Decision"]),
        Paragraph("1. Invoice summary", styles["Heading2"])
    ]

    total_value = run_record.get("total")
    total_text = f"INR {total_value:,.2f}" if isinstance(total_value, (int, float)) else "Not extracted"

    summary_rows = [
        ["Field", "Extracted value"],
        ["Invoice number", str(run_record.get("invoice_number", "Not extracted"))],
        ["Invoice date", str(run_record.get("invoice_date", "Not extracted"))],
        ["Vendor", str(run_record.get("vendor", "Not extracted"))],
        ["Purchase order", str(run_record.get("po_number", "Not extracted"))],
        ["Invoice total", total_text],
        ["Source file", str(run_record.get("file_name", "Not available"))],
        ["Processed at", str(run_record.get("timestamp", "Not available"))]
    ]

    summary_table = Table(summary_rows, colWidths=[48 * mm, 112 * mm], repeatRows=1)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F1F5F9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [summary_table, Spacer(1, 14), Paragraph("2. Validation checks", styles["Heading2"])]

    check_rows = [["Validation", "Result"]]
    for check_name, check_status in run_record.get("checks", {}).items():
        check_rows.append([str(check_name), str(check_status)])

    checks_table = Table(check_rows, colWidths=[100 * mm, 60 * mm], repeatRows=1)
    checks_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [checks_table, Spacer(1, 14), Paragraph("3. Decision reasoning", styles["Heading2"])]

    for reason in run_record.get("reasons", []):
        story.append(Paragraph("• " + str(reason), styles["BodyText"]))
        story.append(Spacer(1, 5))

    story += [
        Spacer(1, 12),
        Paragraph("4. Review and control note", styles["Heading2"]),
        Paragraph(
            "This report records the outcome of the InvoiceIQ prototype's automated checks. "
            "A REJECTED result indicates that one or more configured validation rules failed. "
            "A PENDING result requires review by the Accounts Payable team. This prototype "
            "does not initiate payments or replace the organisation's approval process.",
            styles["BodyText"]
        ),
    ]

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ------------------------- Styling -------------------------

st.markdown("""
<style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1450px;}
    .hero {
        padding: 1.35rem 1.5rem;
        border: 1px solid rgba(120,120,120,.22);
        border-radius: 16px;
        background: linear-gradient(120deg, rgba(59,130,246,.09), rgba(16,185,129,.05));
        margin-bottom: 1.2rem;
    }
    .hero-subtitle {color: #64748b; margin-top: -.45rem;}
    .metric-card {
        border: 1px solid rgba(120,120,120,.25);
        border-radius: 14px;
        padding: 1rem 1.1rem;
        min-height: 112px;
        background: rgba(128,128,128,.035);
    }
    .metric-label {font-size: .9rem; color: #64748b; margin-bottom: .25rem;}
    .metric-value {font-size: 2rem; font-weight: 700; line-height: 1.2;}
    .section-note {color: #64748b; font-size: .9rem;}
    div[data-testid="stFileUploader"] {border-radius: 12px;}
</style>
""", unsafe_allow_html=True)


# ------------------------- Header -------------------------

st.markdown("""
<div class="hero">
    <h1 style="margin-bottom:.35rem;">🧾 InvoiceIQ</h1>
    <h3 style="margin-top:0;">Intelligent Invoice Processing &amp; Validation</h3>
    <p style="margin-bottom:.25rem;"><b>Developed by Muniya Vidushi</b></p>
    <p class="hero-subtitle">AI Solutions Analyst — Candidate Case Study | PS-1 Finance / AP</p>
    <p style="margin-bottom:0;">
        Accounts Payable workflow for invoice extraction, purchase-order matching,
        validation and explainable decisions.
    </p>
</div>
""", unsafe_allow_html=True)

st.caption(
    "Prototype transparency: this version uses PDF text extraction and deterministic "
    "validation rules. Scanned/image-only PDFs require OCR and are routed to manual review."
)

if not os.path.exists(PO_FILE):
    st.error("purchase_orders.csv was not found. Keep it in the same folder as app.py.")
    st.stop()

po_df = pd.read_csv(PO_FILE)
history = load_history()

# ------------------------- KPI Dashboard -------------------------

total_runs = len(history)
approved_count = sum(row.get("status") == "APPROVED" for row in history)
pending_count = sum(row.get("status") == "PENDING" for row in history)
rejected_count = sum(row.get("status") == "REJECTED" for row in history)

st.subheader("Processing overview")

k1, k2, k3, k4 = st.columns(4)
metrics = [
    (k1, "Total processed", total_runs, "#334155"),
    (k2, "Approved", approved_count, "#15803d"),
    (k3, "Pending review", pending_count, "#b45309"),
    (k4, "Rejected", rejected_count, "#b91c1c")
]

for col, label, value, color in metrics:
    with col:
        st.markdown(
            f"""<div class="metric-card">
                <div class="metric-label">{label}</div>
                <div class="metric-value" style="color:{color};">{value}</div>
            </div>""",
            unsafe_allow_html=True
        )

st.divider()

# ------------------------- Main Workflow -------------------------

upload_col, rules_col = st.columns([1.15, 0.85], gap="large")

with upload_col:
    st.subheader("Process an invoice")
    st.write("Upload a digital PDF invoice to begin validation.")
    uploaded_file = st.file_uploader(
        "Choose invoice PDF",
        type=["pdf"],
        help="Use a digital/text-based PDF. Scanned PDFs need OCR."
    )

    process_clicked = st.button(
        "Run invoice validation",
        type="primary",
        disabled=uploaded_file is None,
        use_container_width=True
    )

    if process_clicked and uploaded_file is not None:
        with st.spinner("Extracting invoice details and running validation checks..."):
            try:
                invoice = extract_invoice(uploaded_file)

                if not invoice["raw_text"]:
                    status = "PENDING"
                    reasons = [
                        "No selectable text was found. The PDF may be scanned or image-only; OCR/manual review is required."
                    ]
                    checks = {
                        "PDF text extraction": "FAIL",
                        "Required fields": "NOT RUN",
                        "Duplicate check": "NOT RUN",
                        "PO match": "NOT RUN",
                        "Vendor match": "NOT RUN",
                        "Vendor approval": "NOT RUN",
                        "Amount tolerance": "NOT RUN"
                    }
                else:
                    status, reasons, checks = validate_invoice(invoice, po_df, history)

                run_record = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "file_name": uploaded_file.name,
                    "invoice_number": invoice.get("invoice_number") or "Not extracted",
                    "invoice_date": invoice.get("invoice_date") or "Not extracted",
                    "vendor": invoice.get("vendor") or "Not extracted",
                    "po_number": invoice.get("po_number") or "Not extracted",
                    "total": invoice.get("total"),
                    "status": status,
                    "reasons": reasons,
                    "checks": checks,
                    "raw_text": invoice.get("raw_text", "")
                }

                history.append(run_record)
                save_history(history)
                st.session_state["last_run"] = run_record
                st.rerun()

            except Exception as error:
                st.error(f"Processing could not be completed: {error}")

with rules_col:
    st.subheader("Validation workflow")
    st.markdown("""
    1. **Extract** invoice number, date, vendor, PO reference and total.
    2. **Check completeness** and detect previously processed invoice numbers.
    3. **Match** the PO number and vendor against the PO master.
    4. **Verify** that the vendor is approved.
    5. **Compare** invoice total with PO amount using the configured tolerance.
    6. **Decide**: approve, send for review, or reject — with reasons.
    """)
    st.info(
        "Payment is not initiated automatically. Pending and rejected invoices "
        "remain subject to AP team review."
    )

# ------------------------- Latest Result -------------------------

if "last_run" in st.session_state:
    result = st.session_state["last_run"]
    st.divider()
    st.subheader("Latest processing result")

    status = result["status"]
    st.markdown(
        f"<h2 style='color:{status_color(status)}; margin-bottom:.4rem;'>{status}</h2>",
        unsafe_allow_html=True
    )

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Invoice number", result["invoice_number"])
    d2.metric("Vendor", result["vendor"])
    d3.metric("PO reference", result["po_number"])
    total_display = (
        f"₹{result['total']:,.2f}" if isinstance(result["total"], (int, float))
        else "Not extracted"
    )
    d4.metric("Invoice total", total_display)

    st.markdown("**Decision explanation**")
    for reason in result["reasons"]:
        st.write("• " + reason)

    st.markdown("**Validation check breakdown**")
    check_cols = st.columns(3)
    for index, (check_name, check_status) in enumerate(result["checks"].items()):
        with check_cols[index % 3]:
            if check_status == "PASS":
                st.success(f"{check_name}: PASS")
            elif check_status == "FAIL":
                st.error(f"{check_name}: FAIL")
            else:
                st.info(f"{check_name}: {check_status}")

    safe_invoice_name = re.sub(
        r"[^A-Za-z0-9_-]+", "_",
        str(result.get("invoice_number", "invoice"))
    )
    pdf_filename = f"InvoiceIQ_{safe_invoice_name}_Decision_Report.pdf"
    pdf_bytes = build_decision_pdf(result)

    st.download_button(
        label="↓  Download report",
        data=pdf_bytes,
        file_name=pdf_filename,
        mime="application/pdf"
    )

    with st.expander("View extracted PDF text"):
        st.text(result.get("raw_text") or "No selectable text extracted.")

# ------------------------- Run History and Reset -------------------------

st.divider()
history_title_col, reset_col = st.columns([3, 1])
with history_title_col:
    st.subheader("Processing history")
    st.markdown(
        '<p class="section-note">A record of invoice runs processed in this session and previous local runs.</p>',
        unsafe_allow_html=True
    )

with reset_col:
    with st.popover("🗑️ Reset history", use_container_width=True):
        st.warning("This permanently clears the local processing history.")
        confirm_reset = st.checkbox("I understand — clear all history")
        if st.button("Confirm reset", type="primary", disabled=not confirm_reset):
            save_history([])
            st.session_state.pop("last_run", None)
            st.success("Processing history cleared.")
            st.rerun()

if history:
    history_df = pd.DataFrame([
        {
            "Timestamp": item.get("timestamp"),
            "File": item.get("file_name"),
            "Invoice number": item.get("invoice_number"),
            "Vendor": item.get("vendor"),
            "PO": item.get("po_number"),
            "Total (INR)": item.get("total"),
            "Decision": item.get("status")
        }
        for item in history
    ])

    filter_col, search_col = st.columns([1, 2])
    with filter_col:
        selected_status = st.selectbox(
            "Filter by decision",
            ["All", "APPROVED", "PENDING", "REJECTED"]
        )
    with search_col:
        search_term = st.text_input(
            "Search history",
            placeholder="Search invoice number, vendor or filename"
        )

    filtered = history_df.copy()
    if selected_status != "All":
        filtered = filtered[filtered["Decision"] == selected_status]
    if search_term.strip():
        term = search_term.strip().lower()
        searchable = (
            filtered["Invoice number"].fillna("").astype(str).str.lower().str.contains(term)
            | filtered["Vendor"].fillna("").astype(str).str.lower().str.contains(term)
            | filtered["File"].fillna("").astype(str).str.lower().str.contains(term)
        )
        filtered = filtered[searchable]

    st.dataframe(
        filtered.sort_values("Timestamp", ascending=False),
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        "Download processing history (CSV)",
        history_df.to_csv(index=False).encode("utf-8"),
        file_name="invoice_processing_history.csv",
        mime="text/csv"
    )
else:
    st.info("No invoices have been processed yet. Upload a PDF to create the first run.")

