#!/usr/bin/env python3
"""Exercise the checker with the actual Jira XML and independently mutated XML.

Usage: python3 check_discovery_junit_selftest.py EXPECTED_JSON ATTACHED_JUNIT
Only case labels and exit codes are published; raw XML stays in a temp directory.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def main():
    expected, attached = map(Path, sys.argv[1:])
    checker = Path(__file__).with_name("check_discovery_junit.py")
    names = {row["test"] for row in json.loads(expected.read_text())["failures"]}
    original = ET.parse(attached).getroot()
    failed = {case.get("name") for case in original.iter("testcase") if case.find("failure") is not None}
    assert len(failed) == 14 and failed == names, "expected names do not match actual archived failures"
    passed = copy.deepcopy(original)
    passed.set("failures", "0")
    passed.set("errors", "0")
    for suite in passed.iter("testsuite"):
        suite.set("failures", "0")
        suite.set("errors", "0")
    for case in passed.iter("testcase"):
        if case.get("name") in failed:
            case.set("status", "passed")
            for tag in ("failure", "error", "skipped"):
                for node in case.findall(tag):
                    case.remove(node)

    # This is an explicitly synthetic passing fixture: clear the original
    # failing run's suite-success metadata as well as testcase failures.
    for prop in passed.iter("property"):
        if prop.get("name") == "SuiteSucceeded":
            prop.set("value", "true")
        if prop.get("name") == "SpecialSuiteFailureReason":
            prop.set("value", "")

    checks = []
    with tempfile.TemporaryDirectory(prefix="acm48176-junit-check-") as temporary:
        directory = Path(temporary)

        def write(label, root):
            path = directory / (label + ".xml")
            ET.ElementTree(root).write(path)
            return path

        good_a = write("direction-a", passed)
        good_b = write("direction-b", passed)

        def check(label, first, second, accepts, expected_input=expected):
            result = subprocess.run([sys.executable, str(checker), "--expected", str(expected_input),
                                     "--reports", str(first), str(second)], capture_output=True, text=True)
            output = json.loads(result.stdout)
            actual_accepts = result.returncode == 0 and output["accepted"] is True
            checks.append({"case": label, "expected_accept": accepts, "accepted": actual_accepts,
                           "exit_code": result.returncode, "passed": actual_accepts == accepts})

        check("actual_archived_14_failures", attached, good_b, False)
        check("all_required_pass_with_original_unrelated_skips", good_a, good_b, True)

        def variant(label, mutate):
            root = copy.deepcopy(passed)
            target = next(case for case in root.iter("testcase") if case.get("name") in failed)
            parent = next(parent for parent in root.iter() if target in list(parent))
            mutate(root, parent, target)
            check(label, write(label, root), good_b, False)

        variant("missing_case", lambda root, parent, case: parent.remove(case))
        variant("duplicate_passing_case", lambda root, parent, case: parent.append(copy.deepcopy(case)))
        variant("renamed_case_substitution", lambda root, parent, case: case.set("name", case.get("name") + " substitute"))
        variant("skipped_element_despite_passed_status", lambda root, parent, case: ET.SubElement(case, "skipped"))
        variant("failure_element_despite_passed_status", lambda root, parent, case: ET.SubElement(case, "failure"))
        variant("error_element_despite_passed_status", lambda root, parent, case: ET.SubElement(case, "error"))
        variant("failed_status_without_child", lambda root, parent, case: case.set("status", "failed"))
        variant("missing_status", lambda root, parent, case: case.attrib.pop("status"))
        variant("suite_infrastructure_error", lambda root, parent, case: next(root.iter("testsuite")).set("errors", "1"))
        variant("additional_new_failure", lambda root, parent, case: ET.SubElement(parent, "testcase", name="new regression", status="failed").append(ET.Element("failure")))
        variant("additional_failed_status_without_child", lambda root, parent, case: ET.SubElement(parent, "testcase", name="new regression", status="failed"))
        variant("root_infrastructure_error", lambda root, parent, case: root.set("errors", "1"))
        variant("recovered_flaky_failure", lambda root, parent, case: ET.SubElement(case, "flakyFailure"))
        variant("suite_flake_retries_enabled", lambda root, parent, case: ET.SubElement(ET.SubElement(next(root.iter("testsuite")), "properties"), "property", name="FlakeAttempts", value="2"))
        def mutate_property(root, name, value=None, remove=False, duplicate=False):
            suite = next(root.iter("testsuite"))
            group = suite.find("properties")
            prop = next((p for p in group.findall("property") if p.get("name") == name), None)
            if remove:
                if prop is not None:
                    group.remove(prop)
            elif duplicate:
                ET.SubElement(group, "property", name=name, value=value)
            elif prop is None:
                ET.SubElement(group, "property", name=name, value=value)
            else:
                prop.set("value", value)

        for name in ("SuiteSucceeded", "DryRun", "SuiteHasProgrammaticFocus", "SpecialSuiteFailureReason", "FlakeAttempts"):
            variant("missing_property_" + name,
                    lambda root, parent, case, name=name: mutate_property(root, name, remove=True))
            variant("duplicate_property_" + name,
                    lambda root, parent, case, name=name: mutate_property(root, name, "false", duplicate=True))
        for name, value in (("SuiteSucceeded", "false"), ("DryRun", "true"), ("DryRun", "garbage"),
                            ("SuiteHasProgrammaticFocus", "true"), ("SpecialSuiteFailureReason", "infrastructure failure"),
                            ("FlakeAttempts", "2"), ("FlakeAttempts", "garbage"), ("ReportWasTruncated", "true")):
            variant("bad_property_" + name + "_" + value.replace(" ", "_"),
                    lambda root, parent, case, name=name, value=value: mutate_property(root, name, value))
        check("second_direction_still_fails", good_a, attached, False)
        check("same_report_given_twice", good_a, good_a, False)
        check("missing_report_file", directory / "absent.xml", good_b, False)
        malformed = directory / "malformed.xml"
        malformed.write_text("<testsuites>")
        check("malformed_xml", malformed, good_b, False)
        incomplete = directory / "incomplete-expected.json"
        incomplete.write_text(json.dumps({"failures": [{"test": name} for name in sorted(names)[:13]]}))
        check("incomplete_expected_name_list", good_a, good_b, False, incomplete)

    success = all(check["passed"] for check in checks)
    print(json.dumps({"passed": success, "checks": checks}, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
