"""Parser wyników pytest w formacie JUnit XML (`--junitxml`).

Ustrukturyzowany wynik (który test, jaki status, jaki komunikat) zamiast parsowania
tekstu z konsoli - deterministycznie i odporniej na zmiany formatu wyjścia.
"""

import xml.etree.ElementTree as ET
from typing import Literal

from pydantic import BaseModel, Field

TestStatus = Literal["passed", "failed", "skipped"]


class TestCaseResult(BaseModel):
    id: str
    """`moduł[.Klasa]::nazwa`, np. "tests.contract.test_login::test_ok"."""
    status: TestStatus
    message: str = ""


class JUnitReport(BaseModel):
    cases: dict[str, TestCaseResult] = Field(default_factory=dict)

    @property
    def passed(self) -> set[str]:
        return {i for i, c in self.cases.items() if c.status == "passed"}

    @property
    def failed(self) -> set[str]:
        return {i for i, c in self.cases.items() if c.status == "failed"}

    @property
    def ids(self) -> set[str]:
        return set(self.cases)


def module_of(path: str) -> str:
    """ "tests/contract/test_login.py" -> "tests.contract.test_login"."""
    return path.removesuffix(".py").replace("/", ".")


def ids_in_files(ids: set[str], files: list[str]) -> set[str]:
    modules = [module_of(f) for f in files if f.endswith(".py")]
    return {
        i
        for i in ids
        if any(i == m or i.startswith(m + ".") or i.startswith(m + "::") for m in modules)
    }


def parse_junit(xml_text: str) -> JUnitReport:
    report = JUnitReport()
    root = ET.fromstring(xml_text)
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        test_id = f"{classname}::{name}" if classname else name
        status: TestStatus = "passed"
        message = ""
        for child in case:
            if child.tag in ("failure", "error"):
                status = "failed"
                message = (child.get("message") or child.text or "").strip()[:300]
                break
            if child.tag == "skipped":
                status = "skipped"
        report.cases[test_id] = TestCaseResult(id=test_id, status=status, message=message)
    return report
