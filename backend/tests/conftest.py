from pathlib import Path

import pytest

from analysis.infer import load_fees
from analysis.parsers import parse_statement

REPO_DIR = Path(__file__).resolve().parents[2]
DEMO_CSV = REPO_DIR / "data" / "demo_card_2026.csv"
LABELS_CSV = REPO_DIR / "data" / "demo_labels.csv"
FEES_CSV = REPO_DIR / "docs" / "service fee modified.csv"


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    # 테스트는 외부 API 를 호출하지 않는다.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(scope="session")
def demo_transactions():
    return parse_statement(DEMO_CSV.name, DEMO_CSV.read_bytes())


@pytest.fixture(scope="session")
def fees():
    return load_fees(FEES_CSV)
