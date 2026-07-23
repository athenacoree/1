import os
import re
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from vcdiligence.logging_config import logger

def generate_report_pdf(
    report_data: dict,
    organization_name: str,
    logo_path: str = None,
    output_filename: str = None
) -> str:
    """
    Generates a beautiful white-labeled investment memo PDF report using ReportLab.
    Returns the absolute or relative path to the generated PDF.
    """
    if not output_filename:
        # Save in reports folder
        reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        domain = report_data.get("domain", "unknown_startup")
        output_filename = os.path.join(reports_dir, f"{domain}_memo.pdf")

    # Ensure target parent directory exists
    output_dir = os.path.dirname(output_filename)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    doc = SimpleDocTemplate(
        output_filename,
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Define custom colors
    primary_color = colors.HexColor("#06b6d4") # Cyan
    secondary_color = colors.HexColor("#10b981") # Emerald
    dark_bg = colors.HexColor("#0f172a") # Slate 900
    text_color = colors.HexColor("#334155") # Slate 700

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=15
    )

    h1_style = ParagraphStyle(
        'DocH1',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=15,
        spaceAfter=10,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=text_color,
        spaceAfter=8
    )

    meta_label_style = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#64748b")
    )

    meta_val_style = ParagraphStyle(
        'MetaValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#1e293b")
    )

    story = []

    # 1. Header (White-label Logo & Organization Name)
    header_data = []
    org_title_p = Paragraph(f"<b>{organization_name.upper()}</b><br/><font size=8 color='#64748b'>VENTURE CAPITAL DUE DILIGENCE</font>", title_style)

    if logo_path and os.path.exists(logo_path):
        try:
            # Load and scale logo
            img = Image(logo_path, width=1.2*inch, height=0.4*inch)
            header_data = [[org_title_p, img]]
        except Exception as e:
            logger.error(f"Error loading logo image: {str(e)}")
            header_data = [[org_title_p, ""]]
    else:
        header_data = [[org_title_p, ""]]

    header_table = Table(header_data, colWidths=[4.0*inch, 3.0*inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(header_table)

    # Decorative thin line
    divider = Table([[""]], colWidths=[7.0*inch], rowHeights=[2])
    divider.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), primary_color),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(divider)
    story.append(Spacer(1, 15))

    # 2. Startup Profile & Scores Summary Box
    score = report_data.get("score", 80)
    rec = report_data.get("recommendation", "GO")
    company_name = report_data.get("company_name", "Startup")
    url = report_data.get("company_url", "")

    sub_scores = report_data.get("sub_scores", {})
    sub_scores_str = ", ".join([f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in sub_scores.items()])

    summary_data = [
        [Paragraph("<b>Company Name:</b>", meta_label_style), Paragraph(company_name, meta_val_style),
         Paragraph("<b>Deal Score:</b>", meta_label_style), Paragraph(f"<font color='#10b981'><b>{score}/100</b></font>", meta_val_style)],
        [Paragraph("<b>Website:</b>", meta_label_style), Paragraph(url, meta_val_style),
         Paragraph("<b>Recommendation:</b>", meta_label_style), Paragraph(f"<b>{rec}</b>", meta_val_style)],
        [Paragraph("<b>Category Scores:</b>", meta_label_style), Paragraph(sub_scores_str, meta_val_style), "", ""]
    ]

    summary_table = Table(summary_data, colWidths=[1.5*inch, 2.2*inch, 1.3*inch, 2.0*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#e2e8f0")),
        ('PADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('SPAN', (1,2), (3,2)),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 20))

    # 3. Report Body (Parse the Markdown and add paragraphs/headings)
    report_md = report_data.get("report_md", "")

    # Simple parsing: split by lines, convert headings and bullet points
    lines = report_md.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip UI metadata parsing tags
        if stripped.startswith("INVESTMENT_SCORE:") or stripped.startswith("RECOMMENDATION:") or stripped.startswith("SUB_SCORES:"):
            continue

        if stripped.startswith("### "):
            story.append(Paragraph(stripped[4:], h1_style))
        elif stripped.startswith("## "):
            story.append(Paragraph(stripped[3:], h1_style))
        elif stripped.startswith("# "):
            story.append(Paragraph(stripped[2:], h1_style))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            story.append(Paragraph(f"&bull; {stripped[2:]}", body_style))
        else:
            # Check for bold tag conversion
            formatted_line = stripped
            formatted_line = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", formatted_line)
            formatted_line = re.sub(r"\*(.*?)\*", r"<i>\1</i>", formatted_line)
            story.append(Paragraph(formatted_line, body_style))

    # Page numbering function
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(colors.HexColor("#94a3b8"))
        canvas.drawString(54, 30, f"White-Label Intelligence | Generated by {organization_name}")
        canvas.drawRightString(612-54, 30, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    logger.info(f"PDF report generated at {output_filename}")
    return output_filename
