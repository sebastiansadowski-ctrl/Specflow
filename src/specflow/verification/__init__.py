"""Weryfikacja (ADR-0001, ADR-0006).

Kolejność: kontrole deterministyczne (raport, diff z gita, pliki chronione, testy
uruchamiane w środowisku agenta bez modelu, regresje, TDD, checkpoint historyjki)
→ recenzent LLM (F01) → akceptacja użytkownika. Tylko weryfikacja ustawia Done.
"""

from specflow.verification.junit import JUnitReport, TestCaseResult, ids_in_files, parse_junit
from specflow.verification.verifier import (
    JUNIT_PATH,
    CheckResult,
    TaskUnderTest,
    VerificationPolicy,
    VerificationResult,
    Verifier,
)

__all__ = [
    "JUNIT_PATH",
    "CheckResult",
    "JUnitReport",
    "TaskUnderTest",
    "TestCaseResult",
    "VerificationPolicy",
    "VerificationResult",
    "Verifier",
    "ids_in_files",
    "parse_junit",
]
