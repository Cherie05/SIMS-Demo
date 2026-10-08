#!/usr/bin/env python3
"""Reject ZAP findings except configured ignores and the documented MUI style alert."""

import argparse
import json
import sys
from pathlib import Path


def check_report(report: object, rules: dict[str, str]) -> tuple[list[str], list[str]]:
    if not isinstance(report, dict) or report.get("@programName") != "ZAP":
        raise ValueError("Expected a ZAP JSON report")
    sites = report.get("site")
    if not isinstance(sites, list) or not sites:
        raise ValueError("The report must contain a scanned site")
    failures: list[str] = []
    accepted: list[str] = []
    for site in sites:
        if not isinstance(site, dict) or not site.get("@name"):
            raise ValueError("The scanned site is missing its name")
        alerts = site.get("alerts")
        if not isinstance(alerts, list):
            raise TypeError("The scanned site is missing its alerts list")
        for alert in alerts:
            if not isinstance(alert, dict):
                raise TypeError("Invalid alert object")
            rule = alert.get("pluginid")
            reference = alert.get("alertRef")
            risk = alert.get("riskcode")
            if (
                not isinstance(rule, str)
                or not rule.isdecimal()
                or not isinstance(reference, str)
                or reference.split("-", 1)[0] != rule
                or risk not in {"0", "1", "2", "3"}
            ):
                raise ValueError(
                    "An alert is missing valid rule, reference or risk fields"
                )
            disposition = rules.get(rule, "WARN")
            if disposition == "IGNORE":
                continue
            # A rule-level ignore for 10055 would also hide script/CSP weaknesses.
            # Accept only its style sub-alert, already recorded in the threat model.
            if disposition == "WARN" and reference == "10055-6" and risk == "2":
                accepted.append(reference)
            else:
                failures.append(reference)
    return failures, accepted


def load_rules(path: Path) -> dict[str, str]:
    rules: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t", 2)
        if (
            len(fields) < 2
            or not fields[0].isdecimal()
            or fields[1] not in {"IGNORE", "WARN", "FAIL"}
        ):
            raise ValueError("Invalid baseline rule configuration")
        if fields[0] in rules:
            raise ValueError("Duplicate baseline rule configuration")
        rules[fields[0]] = fields[1]
    return rules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--rules", type=Path, default=Path(".zap/rules.tsv"))
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        failures, accepted = check_report(report, load_rules(args.rules))
    except (OSError, ValueError, TypeError) as error:
        print(f"DAST report verification failed: {error}", file=sys.stderr)
        return 1
    if failures:
        print(
            f"DAST rejected unaccepted findings: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    if accepted:
        print(
            "DAST accepted documented MUI style warning 10055-6; see docs/security/threat-model.md"
        )
    print("DAST report gate passed: no unaccepted findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
