from dataclasses import dataclass

import pytest

from tools.frozen_boundary import assert_analysis_boundary


@dataclass
class FakeAnalysis:
    pure: list[tuple[str, str, str]]
    binaries: list[tuple[str, str, str]]


def test_frozen_boundary_accepts_neutral_contract_prefix() -> None:
    analysis = FakeAnalysis(
        pure=[
            ("finradar_contracts", "contracts.py", "PYMODULE"),
            ("finradar_monitor", "monitor.py", "PYMODULE"),
        ],
        binaries=[],
    )

    assert_analysis_boundary(
        analysis,
        artifact_name="Monitor",
        required_modules={"finradar_contracts", "finradar_monitor"},
        forbidden_modules={"finradar"},
    )


def test_frozen_boundary_rejects_forbidden_module_and_binary() -> None:
    analysis = FakeAnalysis(
        pure=[
            ("finradar", "core.py", "PYMODULE"),
            ("socket", "socket.py", "PYMODULE"),
        ],
        binaries=[("_socket.pyd", "C:/Python/_socket.pyd", "BINARY")],
    )

    with pytest.raises(RuntimeError, match="forbidden modules: socket") as error:
        assert_analysis_boundary(
            analysis,
            artifact_name="Core",
            required_modules={"finradar"},
            forbidden_modules={"socket"},
            forbidden_binary_fragments={"_socket"},
        )

    assert "forbidden binaries: _socket" in str(error.value)
