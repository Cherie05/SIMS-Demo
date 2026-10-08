#!/usr/bin/env python3
"""Regression checks for accepted styles, unexpected findings and incomplete ZAP output."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-zap-report.py")
SPEC = importlib.util.spec_from_file_location("zap_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def alert(reference: str, risk: str = "2") -> dict:
    return {
        "pluginid": reference.split("-", 1)[0],
        "alertRef": reference,
        "riskcode": risk,
    }


def report(*alerts: dict) -> dict:
    return {
        "@programName": "ZAP",
        "site": [{"@name": "http://localhost:3000", "alerts": list(alerts)}],
    }


class ReportGateTests(unittest.TestCase):
    def test_documented_style_warning_is_accepted_and_still_reported(self):
        failures, accepted = GATE.check_report(
            report(alert("10055-6")), {"10055": "WARN"}
        )
        self.assertEqual(failures, [])
        self.assertEqual(accepted, ["10055-6"])

    def test_other_csp_findings_and_unknown_rules_fail_alongside_style_warning(self):
        for reference in ["10055-5", "10055-4", "10055-10", "10021", "99999"]:
            with self.subTest(reference=reference):
                failures, _ = GATE.check_report(
                    report(alert("10055-6"), alert(reference)), {"10055": "WARN"}
                )
                self.assertEqual(failures, [reference])

    def test_configured_failure_and_escalated_style_risk_are_not_accepted(self):
        self.assertEqual(
            GATE.check_report(report(alert("10055-6")), {"10055": "FAIL"})[0],
            ["10055-6"],
        )
        self.assertEqual(
            GATE.check_report(report(alert("10055-6", "3")), {"10055": "WARN"})[0],
            ["10055-6"],
        )

    def test_existing_configured_ignores_are_retained(self):
        self.assertEqual(
            GATE.check_report(report(alert("10049-3", "0")), {"10049": "IGNORE"}),
            ([], []),
        )

    def test_complete_report_without_findings_passes(self):
        self.assertEqual(GATE.check_report(report(), {}), ([], []))

    def test_missing_site_alerts_and_invalid_alerts_fail_closed(self):
        invalid = [
            {},
            {"@programName": "ZAP", "site": []},
            {"@programName": "ZAP", "site": [{"@name": "http://localhost:3000"}]},
            report({}),
            report({"pluginid": "10055", "alertRef": "10021", "riskcode": "2"}),
            report({"pluginid": "10055", "alertRef": "10055-6", "riskcode": "invalid"}),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                GATE.check_report(value, {})

    def test_missing_or_malformed_report_file_fails_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            for content in [
                None,
                "{invalid",
                json.dumps({"@programName": "ZAP", "site": []}),
            ]:
                if content is not None:
                    path.write_text(content, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("verification failed", result.stderr)

    def test_invalid_or_duplicate_rules_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.tsv"
            for content in ["10055\tACCEPT\n", "10055\tWARN\n10055\tIGNORE\n"]:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    GATE.load_rules(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
