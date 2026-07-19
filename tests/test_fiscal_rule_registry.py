from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from finradar.domain.fiscal import FiscalRuleStatus, PercentageFiscalRule
from finradar.infrastructure.database import migrate_database
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry


def make_candidate(version: int, rate: str) -> PercentageFiscalRule:
    return PercentageFiscalRule(
        rule_id="fictional-tax",
        version=version,
        title="Fictional obligation",
        jurisdiction="XX",
        tax_regimes=frozenset({"fictional"}),
        effective_from=date(2026, 1, 1),
        effective_to=None,
        base_metric_code="fictional_base",
        rate=Decimal(rate),
        payment_days_after_period_end=10,
        obligation_category="fictional_tax",
        source_reference=f"fictional-source-v{version}",
        status=FiscalRuleStatus.CANDIDATE,
    )


def make_registry(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rules.db'}")
    migrate_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, SqlAlchemyFiscalRuleRegistry(session_factory)


def advance_to_active(
    registry: SqlAlchemyFiscalRuleRegistry,
    version: int,
) -> None:
    registry.transition(
        "fictional-tax", version, FiscalRuleStatus.VALIDATED, reason="Schema checked"
    )
    registry.transition(
        "fictional-tax", version, FiscalRuleStatus.REVIEWED, reason="Human reviewed"
    )
    registry.transition(
        "fictional-tax", version, FiscalRuleStatus.ACTIVE, reason="Approved"
    )


def test_rule_requires_full_lifecycle_before_activation(tmp_path: Path) -> None:
    _, registry = make_registry(tmp_path)
    registry.register_candidate(make_candidate(1, "0.10"), reason="AI extraction")

    with pytest.raises(ValueError, match="candidate -> active"):
        registry.transition(
            "fictional-tax", 1, FiscalRuleStatus.ACTIVE, reason="Unsafe shortcut"
        )

    advance_to_active(registry, 1)

    active = registry.load_active()
    assert len(active) == 1
    assert active[0].status is FiscalRuleStatus.ACTIVE
    assert active[0].rate == Decimal("0.10")


def test_new_active_version_supersedes_previous_version(tmp_path: Path) -> None:
    _, registry = make_registry(tmp_path)
    registry.register_candidate(make_candidate(1, "0.10"), reason="First version")
    advance_to_active(registry, 1)
    registry.register_candidate(make_candidate(2, "0.20"), reason="Changed source")
    advance_to_active(registry, 2)

    active = registry.load_active()

    assert len(active) == 1
    assert active[0].version == 2
    assert registry.lifecycle("fictional-tax", 1)[-1] is FiscalRuleStatus.SUPERSEDED


def test_rule_definition_is_immutable_in_database(tmp_path: Path) -> None:
    engine, registry = make_registry(tmp_path)
    registry.register_candidate(make_candidate(1, "0.10"), reason="Candidate")

    with pytest.raises(DatabaseError, match="fiscal_rule_versions is immutable"):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE fiscal_rule_versions SET content_json = '{}'"),
            )


def test_only_candidate_can_be_registered(tmp_path: Path) -> None:
    _, registry = make_registry(tmp_path)

    with pytest.raises(ValueError, match="registered as candidates"):
        registry.register_candidate(
            replace(make_candidate(1, "0.10"), status=FiscalRuleStatus.ACTIVE),
            reason="Invalid input",
        )

