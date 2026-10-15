#!/usr/bin/env python3
"""Require the 14 ACM-48176 cases to pass once in each direction's JUnit.

This checks required-case outcomes and supported Ginkgo suite metadata, not
artifact identity, admission, collector coverage, causality, or per-spec retry
attempts omitted by the pinned Ginkgo JUnit reporter. Additional cases are counted separately and do not substitute for
the required cases. XML system-out/system-err and local directories are not emitted.
"""

import argparse
import collections
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def inspect_report(path, names):
    result = {"report": path.name, "accepted": False, "problems": []}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        result["problems"].append({"kind": "unreadable_report", "error_type": type(exc).__name__})
        return result

    if root.tag not in ("testsuites", "testsuite"):
        result["problems"].append({"kind": "unexpected_xml_root"})
        return result

    cases = list(root.iter("testcase"))
    by_name = collections.defaultdict(list)
    for case in cases:
        by_name[case.get("name")].append(case)

    passed = 0
    for name in names:
        matches = by_name[name]
        if len(matches) != 1:
            result["problems"].append({"case": name, "kind": "occurrence_count", "actual": len(matches), "expected": 1})
            continue
        case = matches[0]
        forbidden = [tag for tag in ("skipped", "failure", "error") if case.find(tag) is not None]
        if case.get("status") != "passed" or forbidden:
            result["problems"].append({"case": name, "kind": "not_passed", "status": case.get("status"), "elements": forbidden})
            continue
        passed += 1

    additional = [case for case in cases if case.get("name") not in names]
    additional_bad = sum(case.find("failure") is not None or case.find("error") is not None
                         or case.get("status") not in ("passed", "skipped", "pending") for case in additional)
    result.update({
        "required_cases": len(names), "required_passed": passed,
        "additional_cases": len(additional),
        "additional_skipped": sum(case.find("skipped") is not None for case in additional),
        "additional_failures_or_errors": additional_bad,
    })
    # A successful target subset does not excuse a new failure elsewhere in the run.
    if additional_bad:
        result["problems"].append({"kind": "additional_failures_or_errors", "actual": additional_bad})
    # Ginkgo can report recovered attempts as flakes even when final status passes.
    flakes = [node for tag in ("flakyFailure", "flakyError", "rerunFailure", "rerunError") for node in root.iter(tag)]
    if flakes:
        result["problems"].append({"kind": "flaky_attempts", "actual": len(flakes)})
    for prop in root.iter("property"):
        if prop.get("name") == "FlakeAttempts":
            try:
                attempts = int(prop.get("value", ""))
                if attempts not in (0, 1):
                    raise ValueError
            except ValueError:
                result["problems"].append({"kind": "flake_retries_enabled_or_invalid"})
    suites = list(root.iter("testsuite"))
    if root.tag == "testsuites":
        suites.append(root)
    if not list(root.iter("testsuite")):
        result["problems"].append({"kind": "missing_test_suite"})
    for suite in suites:
        if suite.tag == "testsuite":
            # These fields are emitted by the pinned Ginkgo v2.27.5 reporter.
            # Dry runs mark every spec passed; testcase outcomes alone cannot
            # establish that their bodies ran. Require one unambiguous value.
            properties = collections.defaultdict(list)
            for prop in suite.findall("properties/property"):
                properties[prop.get("name")].append(prop.get("value"))
            required = {"SuiteSucceeded": "true", "DryRun": "false",
                        "SuiteHasProgrammaticFocus": "false", "SpecialSuiteFailureReason": ""}
            for name, expected in required.items():
                if properties[name] != [expected]:
                    result["problems"].append({"kind": "invalid_suite_property", "property": name})
            attempts = properties["FlakeAttempts"]
            if attempts not in (["0"], ["1"]):
                result["problems"].append({"kind": "flake_retries_enabled_or_invalid"})
            # Not emitted by v2.27.5; reject truncation if another producer
            # supplies this marker, without pretending it is a pinned field.
            if "ReportWasTruncated" in properties and properties["ReportWasTruncated"] != ["false"]:
                result["problems"].append({"kind": "report_truncated_or_invalid"})
        # Suite-level infrastructure failures may have no testcase element.
        for field in ("failures", "errors"):
            raw = suite.get(field, "0")
            try:
                count = int(raw)
                if count < 0:
                    raise ValueError
            except ValueError:
                result["problems"].append({"kind": "invalid_suite_counter", "counter": field})
                continue
            if count:
                result["problems"].append({"kind": "suite_failures_or_errors", "counter": field, "actual": count})
    result["accepted"] = not result["problems"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True, help="published attachment-analysis.json")
    parser.add_argument("--reports", type=Path, nargs=2, required=True, metavar=("A_TO_B", "B_TO_A"))
    args = parser.parse_args()
    try:
        analysis = json.loads(args.expected.read_text())
        names = [failure["test"] for failure in analysis["failures"]]
        if len(names) != 14 or any(not isinstance(name, str) or not name for name in names) or len(set(names)) != 14:
            raise ValueError("expected exactly 14 unique nonempty testcase names")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"accepted": False, "problem": "invalid_expected_cases", "error_type": type(exc).__name__}, indent=2))
        return 1
    if args.reports[0].resolve() == args.reports[1].resolve():
        print(json.dumps({"accepted": False, "problem": "reports_must_be_distinct_files"}, indent=2))
        return 1
    reports = [inspect_report(path, names) for path in args.reports]
    accepted = all(report["accepted"] for report in reports)
    print(json.dumps({"accepted": accepted, "reports": reports}, indent=2, sort_keys=True))
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
