"""Turns test results into a requirement-by-requirement table mapped to docs/TEST_PLAN.md.

Inputs (in --reports): backend.xml (pytest), frontend.xml (vitest), e2e.xml (Playwright),
steps.txt ("name=pass|fail" lines written by scripts/proof.sh / e2e.sh).

For every row of every table in TEST_PLAN.md it resolves each referenced test
(`file::name`, `::name` = same file as the previous ref, `name[param]`, `<placeholder>`,
`::*`) and the words "smoke" / "stress" (pipeline steps), then reports:
  PASS     every referenced test/step ran and passed
  FAIL     at least one failed
  MISSING  a referenced test was not found in any result file (doc drift or not run)
  MANUAL   the row references nothing automatable
Exit code 1 on any FAIL or MISSING, so `make proof` can't claim more than it ran."""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    where: str  # classname + suite name, used to match the file
    name: str
    status: str  # pass | fail | skip


def load_cases(reports: Path) -> list[Case]:
    cases: list[Case] = []
    for xml in ("backend.xml", "frontend.xml", "e2e.xml"):
        path = reports / xml
        if not path.exists():
            continue
        for suite in ET.parse(path).getroot().iter("testsuite"):
            for tc in suite.iter("testcase"):
                status = "pass"
                if tc.find("failure") is not None or tc.find("error") is not None:
                    status = "fail"
                elif tc.find("skipped") is not None:
                    status = "skip"
                where = f"{tc.get('classname', '')} {suite.get('name', '')} {tc.get('file', '')}"
                cases.append(Case(where, tc.get("name", ""), status))
    return cases


def load_steps(reports: Path) -> dict[str, str]:
    steps: dict[str, str] = {}
    path = reports / "steps.txt"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.strip().split("=", 1)
                steps[k] = v
    return steps


def name_pattern(ref: str) -> re.Pattern[str]:
    if ref == "*":
        return re.compile(r".*")
    parts = [re.escape(p) for p in re.split(r"<[^>]+>", ref)]
    core = ".+".join(parts)
    # exact, parametrized (pytest [..]), or nested under describe blocks (" > ", " › ")
    return re.compile(rf"^(?:.*(?: > | › ))?{core}(?:\[.*\])?$")


def file_key(file: str) -> str:
    stem = Path(file).name
    for ext in (".spec.ts", ".test.tsx", ".test.ts", ".py"):
        if stem.endswith(ext):
            return stem[: -len(ext)] + (".spec" if ext == ".spec.ts" else "")
    return stem


def find(cases: list[Case], file: str, name: str) -> str:
    key = file_key(file)
    pattern = name_pattern(name)
    hits = [c for c in cases if key.replace(".spec", "") in c.where and pattern.match(c.name)]
    if not hits:
        return "MISSING"
    if any(c.status == "fail" for c in hits):
        return "FAIL"
    if all(c.status == "skip" for c in hits):
        return "MISSING"
    return "PASS"


REF = re.compile(r"`([^`]+)`")


# Pipeline steps a row can reference (in backticks or plain text) -> step name in steps.txt.
STEP_WORDS = {
    "smoke": "smoke",
    "stress": "stress",
    "concurrency-loop": "concurrency_loop",
    "make e2e": "e2e",
}


def step_result(step: str, steps: dict[str, str]) -> tuple[str, str]:
    state = steps.get(step)
    return step, "PASS" if state == "pass" else "FAIL" if state else "MISSING"


def evaluate(cell: str, cases: list[Case], steps: dict[str, str]) -> tuple[str, list[str]]:
    results: list[tuple[str, str]] = []
    last_file = ""
    if "make proof" in cell:  # "the whole pipeline passed"
        results += [step_result(s, steps) for s in ("lint", "backend", "frontend", "concurrency_loop", "smoke", "e2e", "stress")]
    for raw in REF.findall(cell):
        ref = raw.strip()
        if "::" not in ref:
            for word, step in STEP_WORDS.items():
                if word in ref and not any(r[0] == step for r in results):
                    results.append(step_result(step, steps))
            continue
        file, name = ref.split("::", 1)
        file = file or last_file
        last_file = file or last_file
        if not file:
            continue
        results.append((f"{Path(file).name}::{name}", find(cases, file, name)))
    text = REF.sub("", cell).lower()
    for word, step in STEP_WORDS.items():
        if word in text and not any(r[0] == step for r in results):
            results.append(step_result(step, steps))
    if not results:
        return "MANUAL", []
    bad = [f"{ref} ({st})" for ref, st in results if st != "PASS"]
    if any(st == "FAIL" for _, st in results):
        return "FAIL", bad
    if bad:
        return "MISSING", bad
    return "PASS", [f"{len(results)} checks"]


def rows(plan: str) -> list[tuple[str, str, str]]:
    """(section, id, tests-cell) for every requirement row of every table."""
    out: list[tuple[str, str, str]] = []
    section, test_col = "", None
    for line in plan.splitlines():
        if line.startswith("## "):
            section, test_col = line[3:].strip(), None
            continue
        if not line.startswith("|"):
            test_col = None if not line.strip() else test_col
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if test_col is None:  # header row
            test_col = next((i for i, c in enumerate(cells) if c.lower().startswith("test")), None)
            continue
        if set("".join(cells)) <= set("-: "):  # separator row
            continue
        if test_col is not None and test_col < len(cells):
            out.append((section, cells[0], cells[test_col]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="/docs/TEST_PLAN.md")
    parser.add_argument("--reports", default="/reports")
    args = parser.parse_args()
    reports = Path(args.reports)
    cases = load_cases(reports)
    steps = load_steps(reports)

    print("\nPipeline steps")
    for name, state in steps.items():
        print(f"  {name:<18} {state.upper()}")
    totals = {k: sum(c.status == k for c in cases) for k in ("pass", "fail", "skip")}
    print(f"  {'test cases':<18} {totals['pass']} passed, {totals['fail']} failed, {totals['skip']} skipped (backend+frontend+e2e)")

    summary: dict[str, int] = {}
    current = None
    for section, rid, cell in rows(Path(args.plan).read_text()):
        if section != current:
            current = section
            print(f"\n{section}")
            print(f"  {'ID':<34} {'RESULT':<8} detail")
        status, detail = evaluate(cell, cases, steps)
        summary[status] = summary.get(status, 0) + 1
        label = (rid[:31] + "...") if len(rid) > 34 else rid
        print(f"  {label:<34} {status:<8} {'; '.join(detail)[:110]}")

    print("\nRequirements: " + ", ".join(f"{v} {k}" for k, v in sorted(summary.items())))
    failed_steps = [k for k, v in steps.items() if v != "pass"]
    ok = not summary.get("FAIL") and not summary.get("MISSING") and not failed_steps and totals["fail"] == 0
    print(f"PROOF {'PASS' if ok else 'FAIL'}" + ("" if ok else f" (failed steps: {failed_steps or '-'})"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
