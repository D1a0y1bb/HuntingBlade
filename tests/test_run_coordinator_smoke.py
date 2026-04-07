from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_smoke_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_coordinator_smoke.py"
    )
    spec = importlib.util.spec_from_file_location("run_coordinator_smoke", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_smoke_command_targets_shared_azure_coordinator_path() -> None:
    smoke = _load_smoke_module()

    cmd = smoke.resolve_command([])

    assert cmd[:3] == ["uv", "run", "ctf-solve"]
    assert "--coordinator" in cmd
    assert cmd[cmd.index("--coordinator") + 1] == "azure"
    assert "--all-solved-policy" in cmd
    assert cmd[cmd.index("--all-solved-policy") + 1] == "exit"
    assert "--models" in cmd


def test_evaluate_markers_accepts_startup_and_provider_activity() -> None:
    smoke = _load_smoke_module()

    matched, missing = smoke.evaluate_markers(
        [
            "[10:20:43] INFO Coordinator starting: 2 models, 6 challenges, 0 solved",
            "[10:20:44] DEBUG Azure coordinator event: CTF is LIVE. 6 challenges, 0 solved.",
        ]
    )

    assert matched["startup"] == "Coordinator starting:"
    assert matched["activity"] == "Azure coordinator event:"
    assert missing == []


def test_evaluate_markers_reports_missing_activity_group() -> None:
    smoke = _load_smoke_module()

    matched, missing = smoke.evaluate_markers(
        [
            "[10:20:43] INFO Coordinator starting: 2 models, 6 challenges, 0 solved",
        ]
    )

    assert matched["startup"] == "Coordinator starting:"
    assert matched["activity"] is None
    assert missing == ["activity"]
