import httpx
import pytest
import yaml

from backend.ctfd import SubmitResult
from backend.platforms.lingxu_event_ctf import LingxuEventCTFClient
from backend.prompts import ChallengeMeta


@pytest.mark.asyncio
async def test_fetch_challenge_stubs_and_solved_names_use_cookie_session() -> None:
    seen_cookies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookies.append(request.headers["cookie"])
        assert request.url.path == "/event/42/ctf/"
        return httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {"id": 137, "name": "签到", "classify": "misc", "score": 100, "is_parse": True},
                    {"id": 204, "name": "Web1", "classify": "web", "score": 300, "is_parse": False},
                ],
            },
        )

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        stubs = await client.fetch_challenge_stubs()
        solved = await client.fetch_solved_names()
    finally:
        await client.close()

    assert seen_cookies == [
        "sessionid=sid123; csrftoken=csrf456",
        "sessionid=sid123; csrftoken=csrf456",
    ]
    assert stubs == [
        {"id": 137, "name": "签到", "category": "misc", "value": 100},
        {"id": 204, "name": "Web1", "category": "web", "value": 300},
    ]
    assert solved == {"签到"}


@pytest.mark.asyncio
async def test_validate_access_fails_without_event_permission() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(RuntimeError, match="赛事 CTF 接口"):
            await client.validate_access()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_validate_access_accepts_session_cookie_without_csrf() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        assert request.url.path == "/event/42/ctf/"
        return httpx.Response(200, json={"results": []})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.validate_access()
    finally:
        await client.close()

    assert [headers["cookie"] for headers in seen_headers] == ["sessionid=sid123"]


@pytest.mark.asyncio
async def test_validate_access_fails_without_session_cookie() -> None:
    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="csrftoken=csrf456",
    )

    try:
        with pytest.raises(RuntimeError, match="赛事 CTF 接口"):
            await client.validate_access()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_pull_challenge_writes_extended_metadata_and_downloads_attachment(tmp_path) -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/event/42/ctf/137/info/":
            return httpx.Response(
                200,
                json={
                    "desc": "<p>题目描述</p>",
                    "score": 500,
                    "link_path": "nc chall.example.com 31337",
                    "parse_count": 12,
                    "task_type": 1,
                    "answer_mode": 1,
                    "attachment": "/media/files/task.bin",
                },
            )
        if request.url.path == "/media/files/task.bin":
            return httpx.Response(200, content=b"binary-data")
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        challenge_dir = await client.pull_challenge(
            {"id": 137, "name": "Warmup Task", "category": "misc", "value": 100},
            str(tmp_path),
        )
    finally:
        await client.close()

    metadata_path = tmp_path / "warmup-task-137" / "metadata.yml"
    attachment_path = tmp_path / "warmup-task-137" / "distfiles" / "task.bin"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    meta = ChallengeMeta.from_yaml(metadata_path)

    assert challenge_dir == str(tmp_path / "warmup-task-137")
    assert seen_paths == ["/event/42/ctf/137/info/", "/media/files/task.bin"]
    assert attachment_path.read_bytes() == b"binary-data"
    assert metadata["name"] == "Warmup Task"
    assert metadata["category"] == "misc"
    assert metadata["description"].strip() == "题目描述"
    assert metadata["value"] == 500
    assert metadata["connection_info"] == ""
    assert metadata["solves"] == 12
    assert metadata["platform"] == "lingxu-event-ctf"
    assert metadata["platform_url"] == "https://lx.example.com"
    assert metadata["event_id"] == 42
    assert metadata["platform_challenge_id"] == 137
    assert metadata["test_type"] == 1
    assert metadata["answer_mode"] == 1
    assert metadata["requires_env_start"] is True
    assert metadata["unsupported_reason"] == ""
    assert meta.platform == "lingxu-event-ctf"
    assert meta.platform_challenge_id == 137
    assert meta.requires_env_start is True


@pytest.mark.asyncio
async def test_prepare_challenge_prefers_public_target_over_internal_addr(tmp_path) -> None:
    challenge_dir = tmp_path / "web-task-137"
    challenge_dir.mkdir()
    metadata_path = challenge_dir / "metadata.yml"
    metadata_path.write_text(
        yaml.dump(
            {
                "name": "Web Task",
                "platform": "lingxu-event-ctf",
                "event_id": 42,
                "platform_challenge_id": 137,
                "requires_env_start": True,
                "connection_info": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event/42/ctf/137/begin/":
            return httpx.Response(200, json={"status": 2, "msg": "您已经开启该题目"})
        if request.url.path == "/event/42/ctf/137/run/":
            return httpx.Response(200, json={"status": 2, "msg": "启动成功"})
        if request.url.path == "/event/42/ctf/137/addr/":
            return httpx.Response(
                200,
                json={
                    "domain_addr": "http://b744b16e.clsadp.com/",
                    "ext_id": "192.168.10.20:51416",
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.prepare_challenge(str(challenge_dir))
    finally:
        await client.close()

    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    assert metadata["connection_info"] == "http://b744b16e.clsadp.com/"


@pytest.mark.asyncio
async def test_prepare_challenge_prefers_public_nc_target_over_internal_addr(tmp_path) -> None:
    challenge_dir = tmp_path / "pwn-task-137"
    challenge_dir.mkdir()
    metadata_path = challenge_dir / "metadata.yml"
    metadata_path.write_text(
        yaml.dump(
            {
                "name": "Pwn Task",
                "platform": "lingxu-event-ctf",
                "event_id": 42,
                "platform_challenge_id": 137,
                "requires_env_start": True,
                "connection_info": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event/42/ctf/137/begin/":
            return httpx.Response(200, json={"status": 2, "msg": "您已经开启该题目"})
        if request.url.path == "/event/42/ctf/137/run/":
            return httpx.Response(200, json={"status": 2, "msg": "启动成功"})
        if request.url.path == "/event/42/ctf/137/addr/":
            return httpx.Response(
                200,
                json={
                    "ext_id": [
                        "192.168.10.20:51415",
                        "gamebox.yunyansec.com:25375",
                    ],
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.prepare_challenge(str(challenge_dir))
    finally:
        await client.close()

    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    assert metadata["connection_info"] == "nc gamebox.yunyansec.com 25375"


@pytest.mark.asyncio
async def test_pull_challenge_marks_check_mode_as_unsupported(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/204/info/"
        return httpx.Response(
            200,
            json={
                "desc": "<p>check me</p>",
                "score": 250,
                "link_path": "",
                "parse_count": 3,
                "task_type": 3,
                "answer_mode": 2,
                "attachment": "",
            },
        )

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        challenge_dir = await client.pull_challenge(
            {"id": 204, "name": "Check Mode", "category": "web", "value": 100},
            str(tmp_path),
        )
    finally:
        await client.close()

    metadata = yaml.safe_load((tmp_path / "check-mode-204" / "metadata.yml").read_text(encoding="utf-8"))

    assert challenge_dir == str(tmp_path / "check-mode-204")
    assert metadata["answer_mode"] == 2
    assert metadata["requires_env_start"] is False
    assert metadata["unsupported_reason"] == "check mode is not supported in v1"


@pytest.mark.asyncio
async def test_prepare_challenge_starts_env_and_updates_connection_info_with_csrf(tmp_path) -> None:
    challenge_dir = tmp_path / "warmup-task-137"
    challenge_dir.mkdir()
    metadata_path = challenge_dir / "metadata.yml"
    metadata_path.write_text(
        yaml.dump(
            {
                "name": "Warmup Task",
                "platform": "lingxu-event-ctf",
                "event_id": 42,
                "platform_challenge_id": 137,
                "requires_env_start": True,
                "connection_info": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    seen_requests: list[tuple[str, str, str | None, bytes, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(
            (
                request.method,
                request.url.path,
                request.headers.get("x-csrftoken"),
                request.content,
                request.headers.get("content-type"),
            )
        )
        if request.url.path == "/event/42/ctf/137/begin/":
            assert request.method == "POST"
            return httpx.Response(200, json={"status": 2, "msg": "您已经开启该题目"})
        if request.url.path == "/event/42/ctf/137/run/":
            assert request.method == "POST"
            return httpx.Response(200, json={"status": 2, "msg": "启动成功"})
        if request.url.path == "/event/42/ctf/137/addr/":
            assert request.method == "GET"
            return httpx.Response(200, json={"ext_id": "10.10.10.10:31337"})
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.prepare_challenge(str(challenge_dir))
    finally:
        await client.close()

    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    assert metadata["connection_info"] == "nc 10.10.10.10 31337"
    assert seen_requests == [
        ("POST", "/event/42/ctf/137/begin/", "csrf456", b"", None),
        ("POST", "/event/42/ctf/137/run/", "csrf456", b"", None),
        ("GET", "/event/42/ctf/137/addr/", None, b"", None),
    ]


@pytest.mark.asyncio
async def test_prepare_challenge_omits_csrf_header_when_cookie_has_no_token(tmp_path) -> None:
    challenge_dir = tmp_path / "warmup-task-137"
    challenge_dir.mkdir()
    metadata_path = challenge_dir / "metadata.yml"
    metadata_path.write_text(
        yaml.dump(
            {
                "name": "Warmup Task",
                "platform": "lingxu-event-ctf",
                "event_id": 42,
                "platform_challenge_id": 137,
                "requires_env_start": True,
                "connection_info": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    seen_requests: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.method, request.url.path, request.headers.get("x-csrftoken")))
        if request.url.path == "/event/42/ctf/137/begin/":
            return httpx.Response(200, json={"status": 2, "msg": "您已经开启该题目"})
        if request.url.path == "/event/42/ctf/137/run/":
            return httpx.Response(200, json={"status": 2, "msg": "启动成功"})
        if request.url.path == "/event/42/ctf/137/addr/":
            return httpx.Response(200, json={"ext_id": "10.10.10.10:31337"})
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.prepare_challenge(str(challenge_dir))
    finally:
        await client.close()

    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    assert metadata["connection_info"] == "nc 10.10.10.10 31337"
    assert seen_requests == [
        ("POST", "/event/42/ctf/137/begin/", None),
        ("POST", "/event/42/ctf/137/run/", None),
        ("GET", "/event/42/ctf/137/addr/", None),
    ]


@pytest.mark.asyncio
async def test_submit_flag_accepts_challenge_meta_and_normalizes_correct() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.method == "POST"
        assert request.headers["x-csrftoken"] == "csrf456"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"flag=FLAG%7Breal%7D"
        return httpx.Response(200, json={"status": 1, "score": 500})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )
    meta = ChallengeMeta(
        name="Warmup Task",
        platform="lingxu-event-ctf",
        platform_url="https://lx.example.com",
        event_id=42,
        platform_challenge_id=137,
    )

    try:
        result = await client.submit_flag(meta, "FLAG{real}")
    finally:
        await client.close()

    assert seen_paths == ["/event/42/ctf/137/flag/"]
    assert result == SubmitResult(
        status="correct",
        message="",
        display='CORRECT — "FLAG{real}" accepted.',
    )


@pytest.mark.asyncio
async def test_submit_flag_omits_csrf_header_when_cookie_has_no_token() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        assert request.url.path == "/event/42/ctf/137/flag/"
        assert request.method == "POST"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"flag=FLAG%7Breal%7D"
        return httpx.Response(200, json={"status": 1})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123",
        transport=httpx.MockTransport(handler),
    )

    try:
        result = await client.submit_flag({"platform_challenge_id": 137}, "FLAG{real}")
    finally:
        await client.close()

    assert "x-csrftoken" not in seen_headers[0]
    assert result == SubmitResult(
        status="correct",
        message="",
        display='CORRECT — "FLAG{real}" accepted.',
    )


@pytest.mark.asyncio
async def test_submit_flag_normalizes_status_2_as_incorrect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/flag/"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"flag=FLAG%7Bbad%7D"
        return httpx.Response(200, json={"status": 2})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        result = await client.submit_flag({"platform_challenge_id": 137}, "FLAG{bad}")
    finally:
        await client.close()

    assert result == SubmitResult(
        status="incorrect",
        message="",
        display='INCORRECT — "FLAG{bad}" rejected.',
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error_message", ["FLAG错误", "Flag错误"])
async def test_submit_flag_normalizes_wrong_flag_from_http_400(error_message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/flag/"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"flag=FLAG%7Bbad%7D"
        return httpx.Response(400, json={"error": error_message})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        result = await client.submit_flag({"platform_challenge_id": 137}, "FLAG{bad}")
    finally:
        await client.close()

    assert result == SubmitResult(
        status="incorrect",
        message=error_message,
        display=f'INCORRECT — "FLAG{{bad}}" rejected. {error_message}',
    )


@pytest.mark.asyncio
async def test_submit_flag_normalizes_already_solved_from_http_400() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/flag/"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"flag=FLAG%7Breal%7D"
        return httpx.Response(400, json={"error": "您已提交了正确的Flag"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        result = await client.submit_flag({"platform_challenge_id": 137}, "FLAG{real}")
    finally:
        await client.close()

    assert result == SubmitResult(
        status="already_solved",
        message="您已提交了正确的Flag",
        display='ALREADY SOLVED — "FLAG{real}" accepted. 您已提交了正确的Flag',
    )


@pytest.mark.asyncio
async def test_release_challenge_env_posts_release_with_csrf_header_for_challenge_meta() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        assert request.method == "POST"
        assert request.url.path == "/event/84/ctf/137/release/"
        return httpx.Response(200, json={"msg": "释放成功"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )
    meta = ChallengeMeta(
        name="Warmup Task",
        platform="lingxu-event-ctf",
        event_id=84,
        platform_challenge_id=137,
    )

    try:
        await client.release_challenge_env(meta)
    finally:
        await client.close()

    assert len(seen_headers) == 1
    assert seen_headers[0]["x-csrftoken"] == "csrf456"


@pytest.mark.asyncio
async def test_release_challenge_env_omits_csrf_header_when_cookie_has_no_token() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        assert request.method == "POST"
        assert request.url.path == "/event/42/ctf/137/release/"
        return httpx.Response(200, json={"msg": "释放成功"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.release_challenge_env({"platform_challenge_id": 137})
    finally:
        await client.close()

    assert len(seen_headers) == 1
    assert "x-csrftoken" not in seen_headers[0]


@pytest.mark.asyncio
async def test_release_challenge_env_accepts_dict_ref_with_explicit_event_id() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"message": "释放成功"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.release_challenge_env({"event_id": 99, "platform_challenge_id": 204})
    finally:
        await client.close()

    assert seen_paths == ["/event/99/ctf/204/release/"]


@pytest.mark.asyncio
async def test_release_challenge_env_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/release/"
        return httpx.Response(500, json={"msg": "释放失败"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(RuntimeError, match="释放失败"):
            await client.release_challenge_env({"platform_challenge_id": 137})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_release_challenge_env_raises_on_payload_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/release/"
        return httpx.Response(200, json={"error": "释放失败"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(RuntimeError, match="释放失败"):
            await client.release_challenge_env({"platform_challenge_id": 137})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_release_challenge_env_raises_on_status_1() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/release/"
        return httpx.Response(200, json={"status": 1, "msg": "开始释放"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(RuntimeError, match="开始释放"):
            await client.release_challenge_env({"platform_challenge_id": 137})
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["该环境正在释放", "没有运行的环境"])
async def test_release_challenge_env_accepts_idempotent_status_3_messages(message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/release/"
        return httpx.Response(200, json={"status": 3, "msg": message})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        await client.release_challenge_env({"platform_challenge_id": 137})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_release_challenge_env_raises_on_non_idempotent_status_3_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/event/42/ctf/137/release/"
        return httpx.Response(200, json={"status": 3, "msg": "释放失败"})

    client = LingxuEventCTFClient(
        base_url="https://lx.example.com",
        event_id=42,
        cookie="sessionid=sid123; csrftoken=csrf456",
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(RuntimeError, match="释放失败"):
            await client.release_challenge_env({"platform_challenge_id": 137})
    finally:
        await client.close()
