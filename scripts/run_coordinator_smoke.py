from __future__ import annotations

import argparse
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TextIO

DEFAULT_SMOKE_COMMAND = [
    "uv",
    "run",
    "ctf-solve",
    "--platform",
    "lingxu-event-ctf",
    "--platform-url",
    "https://ctf.yunyansec.com",
    "--lingxu-event-id",
    "198",
    "--coordinator",
    "azure",
    "--models",
    "azure/gpt-5.4",
    "--models",
    "azure/gpt-5.4-mini",
    "--max-challenges",
    "3",
    "--all-solved-policy",
    "exit",
    "--writeup-mode",
    "confirmed",
    "--writeup-dir",
    "writeups",
    "--msg-port",
    "9400",
    "-v",
]

MARKER_GROUPS: dict[str, tuple[str, ...]] = {
    "startup": ("Coordinator starting:",),
    "activity": (
        "Policy action executed:",
        "Headless event:",
        "Azure coordinator event:",
        "Codex coordinator event:",
        "Claude coordinator event:",
    ),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a repeatable coordinator smoke command and assert required log markers.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=90,
        help="How long to keep the smoke process alive before the harness stops it.",
    )
    parser.add_argument(
        "--grace-period-seconds",
        type=int,
        default=10,
        help="How long to wait after SIGINT before escalating termination.",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="Optional path to persist merged child output.",
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to run after '--'. If omitted, the built-in Azure smoke preset is used.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def resolve_command(raw_cmd: Sequence[str]) -> list[str]:
    cmd = list(raw_cmd)
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    if cmd:
        return cmd
    return list(DEFAULT_SMOKE_COMMAND)


def evaluate_markers(lines: Iterable[str]) -> tuple[dict[str, str | None], list[str]]:
    matched: dict[str, str | None] = dict.fromkeys(MARKER_GROUPS, None)
    for line in lines:
        for group, markers in MARKER_GROUPS.items():
            if matched[group] is not None:
                continue
            for marker in markers:
                if marker in line:
                    matched[group] = marker
                    break
    missing = [group for group, marker in matched.items() if marker is None]
    return matched, missing


def _reader_worker(stream: TextIO, output_queue: queue.Queue[str | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            output_queue.put(line)
    finally:
        output_queue.put(None)


def _terminate_process(
    proc: subprocess.Popen[str],
    *,
    grace_period_seconds: int,
) -> None:
    if proc.poll() is not None:
        return

    pgid = os.getpgid(proc.pid)
    os.killpg(pgid, signal.SIGINT)
    deadline = time.monotonic() + grace_period_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    if proc.poll() is None:
        os.killpg(pgid, signal.SIGTERM)
        deadline = time.monotonic() + max(1, grace_period_seconds // 2)
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.1)

    if proc.poll() is None:
        os.killpg(pgid, signal.SIGKILL)


def _run_smoke(
    cmd: Sequence[str],
    *,
    duration_seconds: int,
    grace_period_seconds: int,
    log_handle: TextIO | None,
) -> tuple[list[str], int | None, bool]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
        env=env,
    )
    assert proc.stdout is not None

    output_queue: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_reader_worker, args=(proc.stdout, output_queue), daemon=True)
    reader.start()

    lines: list[str] = []
    deadline_reached = False
    reader_done = False
    deadline = time.monotonic() + duration_seconds

    while True:
        timeout = max(0.0, min(0.2, deadline - time.monotonic()))
        try:
            item = output_queue.get(timeout=timeout if not reader_done else 0.0)
        except queue.Empty:
            item = None

        if item is None:
            if not reader_done:
                reader_done = True
            else:
                pass
        else:
            lines.append(item)
            sys.stdout.write(item)
            sys.stdout.flush()
            if log_handle is not None:
                log_handle.write(item)
                log_handle.flush()

        if time.monotonic() >= deadline:
            deadline_reached = True
            break
        if reader_done and proc.poll() is not None and output_queue.empty():
            break

    if deadline_reached:
        _terminate_process(proc, grace_period_seconds=grace_period_seconds)

    proc.wait(timeout=max(5, grace_period_seconds))

    while True:
        try:
            item = output_queue.get_nowait()
        except queue.Empty:
            break
        if item is None:
            continue
        lines.append(item)
        sys.stdout.write(item)
        sys.stdout.flush()
        if log_handle is not None:
            log_handle.write(item)
            log_handle.flush()

    reader.join(timeout=1)
    return lines, proc.returncode, deadline_reached


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cmd = resolve_command(args.cmd)

    print(f"[smoke] duration={args.duration_seconds}s")
    print(f"[smoke] command={' '.join(cmd)}")

    log_handle: TextIO | None = None
    try:
        if args.log_file:
            log_path = Path(args.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("w", encoding="utf-8")

        lines, return_code, deadline_reached = _run_smoke(
            cmd,
            duration_seconds=args.duration_seconds,
            grace_period_seconds=args.grace_period_seconds,
            log_handle=log_handle,
        )
    finally:
        if log_handle is not None:
            log_handle.close()

    matched, missing = evaluate_markers(lines)
    for group, marker in matched.items():
        status = marker or "MISSING"
        print(f"[smoke] {group}: {status}")

    if missing:
        print(f"[smoke] missing marker groups: {', '.join(missing)}", file=sys.stderr)
        return 1

    if not deadline_reached and return_code not in (0, None):
        print(f"[smoke] child exited early with non-zero status: {return_code}", file=sys.stderr)
        return 1

    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
