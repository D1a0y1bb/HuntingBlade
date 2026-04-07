"""Codex advisor adapter over the shared coordinator event loop."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.config import Settings
from backend.control.advisor import (
    ADVISOR_SYSTEM_PROMPT,
    AdvisorContext,
    AdvisorSuggestion,
    parse_advisor_suggestions_json,
    render_advisor_prompt,
)

logger = logging.getLogger(__name__)

_rpc_counter = itertools.count(1)


class CodexCoordinatorAdvisor:
    """Codex app-server advisor adapter without dynamic business tools."""

    def __init__(self, model: str = "gpt-5.4") -> None:
        self.model = model
        self._proc: asyncio.subprocess.Process | None = None
        self._pending_responses: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._turn_done: asyncio.Event = asyncio.Event()
        self._turn_error: str | None = None
        self._output_text: str = ""

    async def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = await asyncio.create_subprocess_exec(
            "codex",
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        await self._rpc(
            "initialize",
            {
                "clientInfo": {"name": "ctf-coordinator-advisor", "version": "2.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self._send_notification("initialized", {})

    async def suggest(self, context: AdvisorContext) -> list[AdvisorSuggestion]:
        if self._proc is None:
            await self.start()

        thread_id = await self._start_thread()
        try:
            output_text = await self._run_turn(
                thread_id=thread_id,
                prompt=render_advisor_prompt(context),
            )
        finally:
            await self._archive_thread(thread_id)

        return parse_advisor_suggestions_json(
            output_text,
            default_challenge=context.challenge_name,
        )

    async def _start_thread(self) -> str:
        resp = await self._rpc(
            "thread/start",
            {
                "model": self.model,
                "personality": "pragmatic",
                "baseInstructions": ADVISOR_SYSTEM_PROMPT,
                "cwd": ".",
                "approvalPolicy": "on-request",
                "sandbox": "read-only",
            },
        )
        return str(resp.get("result", {}).get("thread", {}).get("id", "")).strip()

    async def _run_turn(self, *, thread_id: str, prompt: str) -> str:
        self._turn_done.clear()
        self._turn_error = None
        self._output_text = ""
        await self._rpc(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
            },
        )
        try:
            await asyncio.wait_for(self._turn_done.wait(), timeout=120)
        except TimeoutError:
            logger.warning("Codex advisor turn timed out")
            return ""

        if self._turn_error:
            logger.warning("Codex advisor turn error: %s", self._turn_error)
            return ""
        return self._output_text

    async def _archive_thread(self, thread_id: str) -> None:
        if not thread_id:
            return
        try:
            await self._rpc("thread/archive", {"threadId": thread_id})
        except Exception:
            logger.warning("Codex advisor thread archive failed: %s", thread_id, exc_info=True)

    async def stop(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        assert self._proc and self._proc.stdin
        msg_id = next(_rpc_counter)
        msg: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending_responses[msg_id] = future

        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout=300)
        finally:
            self._pending_responses.pop(msg_id, None)

    async def _send_notification(self, method: str, params: dict | None = None) -> None:
        assert self._proc and self._proc.stdin
        msg: dict[str, Any] = {"method": method}
        if params:
            msg["params"] = params
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                self._turn_done.set()
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_id = msg.get("id")
            if msg_id is not None and ("result" in msg or "error" in msg):
                future = self._pending_responses.pop(msg_id, None)
                if future and not future.done():
                    if "error" in msg:
                        future.set_exception(RuntimeError(f"Codex RPC error: {msg['error']}"))
                    else:
                        future.set_result(msg)
                continue

            method = msg.get("method", "")
            params = msg.get("params", {})
            if method == "item/completed":
                item = params.get("item", params)
                if item.get("type") == "agentMessage":
                    text = str(item.get("text", "")).strip()
                    if text:
                        self._output_text = text
            elif method == "turn/completed":
                turn = params.get("turn", {})
                if turn.get("status") == "failed":
                    self._turn_error = str(turn.get("error", "unknown"))
                self._turn_done.set()


async def run_codex_coordinator(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    coordinator_model: str | None = None,
    msg_port: int = 0,
) -> dict[str, Any]:
    """Run the Codex advisor provider on top of the shared event loop."""
    ctfd, cost_tracker, deps = build_deps(
        settings, model_specs, challenges_root, no_submit,
    )
    deps.msg_port = msg_port

    resolved_model = coordinator_model or "gpt-5.4"
    advisor = CodexCoordinatorAdvisor(model=resolved_model)

    async def event_sink(message: str) -> None:
        logger.debug("Codex coordinator event: %s", message[:240])

    try:
        await advisor.start()
        return await run_event_loop(
            deps,
            ctfd,
            cost_tracker,
            event_sink=event_sink,
            advisor=advisor,
        )
    finally:
        await advisor.stop()
