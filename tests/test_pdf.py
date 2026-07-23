import unittest
import os
from vcdiligence.pdf_generator import generate_report_pdf

class TestPDFGenerator(unittest.TestCase):
    def test_pdf_generation_flow(self):
        report_data = {
            "domain": "test_startup",
            "company_name": "Test Startup Inc.",
            "company_url": "https://teststartup.com",
            "score": 88,
            "recommendation": "GO",
            "sub_scores": {
                "market": 90,
                "team": 85,
                "product": 92,
                "traction": 88,
                "risk_legal_omissions": 75
            },
            "report_md": """
            # Executive Summary
            This is a test investment memo for Test Startup Inc.

            ## Core Moats
            - Strong API integration.
            - Low acquisition costs.

            ## Señales por Ausencia
            - No details on founder's previous background.
            - Pricing is not transparent.
            """
        }

        pdf_path = os.path.join("vcdiligence", "reports", "test_startup_memo.pdf")
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        res_path = generate_report_pdf(
            report_data=report_data,
            organization_name="Acme Capital Ltd",
            logo_path=None,
            output_filename=pdf_path
        )

        self.assertTrue(os.path.exists(res_path))
        self.assertEqual(res_path, pdf_path)
        print(f"Generated PDF file size: {os.path.getsize(res_path)} bytes")

if __name__ == "__main__":
    unittest.main()
