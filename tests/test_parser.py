import unittest
from vcdiligence.parser import parse_report_meta

class TestParser(unittest.TestCase):
    def test_parse_report_meta_standard(self):
        sample_md = """
        INVESTMENT_SCORE: 92
        RECOMMENDATION: GO
        SUB_SCORES: {"market": 95, "team": 90, "product": 88, "traction": 85, "risk_legal_omissions": 78}

        # Executive Summary
        Some text...
        """
        score, recommendation, sub_scores = parse_report_meta(sample_md)
        self.assertEqual(score, 92)
        self.assertEqual(recommendation, "GO")
        self.assertEqual(sub_scores["market"], 95)
        self.assertEqual(sub_scores["team"], 90)
        self.assertEqual(sub_scores["risk_legal_omissions"], 78)

    def test_parse_report_meta_fallback(self):
        sample_md = """
        INVESTMENT_SCORE: 75
        RECOMMENDATION: CONDITIONAL
        market: 70
        team: 72
        product: 78
        traction: 71
        risk_legal_omissions: 65
        """
        score, recommendation, sub_scores = parse_report_meta(sample_md)
        self.assertEqual(score, 75)
        self.assertEqual(recommendation, "CONDITIONAL")
        self.assertEqual(sub_scores["market"], 70)
        self.assertEqual(sub_scores["risk_legal_omissions"], 65)

if __name__ == "__main__":
    unittest.main()
