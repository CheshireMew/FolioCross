from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from openai import APIConnectionError, APITimeoutError

from foliocross.application.service import FolioCrossService
from foliocross.domain.models import DesiredState, JobConfig, ModelProfile
from foliocross.infrastructure.llm import ModelResponse, ModelUsage
from foliocross.worker.engine import CancelRequested, LLMRuntime, PauseRequested, WorkerEventEmitter


def make_runtime(workspace, tmp_path, **options):
    source = tmp_path / "source.txt"
    source.write_text("One paragraph", encoding="utf-8")
    service = FolioCrossService(workspace)
    config = JobConfig(
        profile=ModelProfile(provider="fake"),
        translation_start_concurrency=1,
        translation_max_concurrency=1,
        **options,
    )
    job_id = service.import_book(str(source), config)["job_id"]
    service.repository.set_desired_state(job_id, DesiredState.RUN)
    return LLMRuntime(service.repository, job_id, config, WorkerEventEmitter(service.repository))


@pytest.mark.parametrize(
    "control,exception",
    [(DesiredState.PAUSE, PauseRequested), (DesiredState.CANCEL, CancelRequested)],
)
def test_queued_request_does_not_dispatch_after_control(workspace, tmp_path, control, exception):
    runtime = make_runtime(workspace, tmp_path)
    entered, release, queued = Event(), Event(), Event()
    calls = []

    class Client:
        def complete(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            assert release.wait(5)
            return ModelResponse("{}", ModelUsage())

    runtime.client = Client()
    check = runtime.check_control

    def observed_check():
        check()
        if entered.is_set():
            queued.set()

    runtime.check_control = observed_check
    arguments = dict(stage="translate", model="fake", system="", payload={})
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(runtime.call_json, **arguments)
        assert entered.wait(5)
        second = pool.submit(runtime.call_json, **arguments)
        assert queued.wait(5)
        runtime.repository.set_desired_state(runtime.job_id, control)
        release.set()
        assert first.result(5) == {}
        with pytest.raises(exception):
            second.result(5)
    assert len(calls) == 1


@pytest.mark.parametrize("error_type", [APITimeoutError, APIConnectionError])
def test_sdk_transport_errors_retry_and_account(workspace, tmp_path, monkeypatch, error_type):
    runtime = make_runtime(workspace, tmp_path, max_retries=2)
    calls = []

    class Client:
        def complete(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise error_type(request=None)
            return ModelResponse("{}", ModelUsage(prompt_tokens=10, completion_tokens=2))

    runtime.client = Client()
    monkeypatch.setattr(runtime, "_controlled_wait", lambda delay: None)
    assert runtime.call_json(stage="translate", model="fake", system="", payload={}) == {}
    with workspace.session() as connection:
        requests = connection.execute(
            "SELECT status,attempt FROM llm_requests ORDER BY attempt"
        ).fetchall()
        assert [tuple(row) for row in requests] == [("failed", 1), ("succeeded", 2)]
        assert connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 1


def test_queued_request_checks_cost_committed_by_previous_request(workspace, tmp_path):
    runtime = make_runtime(workspace, tmp_path, hard_budget=0.5)
    entered, release, waiting = Event(), Event(), Event()
    calls = []

    class Client:
        def complete(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            assert release.wait(5)
            return ModelResponse("{}", ModelUsage(prompt_tokens=100))

    runtime.client = Client()
    runtime._cost = lambda usage: 1.0
    check = runtime.check_control

    def observe():
        check()
        if entered.is_set():
            waiting.set()

    runtime.check_control = observe
    arguments = dict(stage="translate", model="fake", system="", payload={})
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(runtime.call_json, **arguments)
        assert entered.wait(5)
        second = pool.submit(runtime.call_json, **arguments)
        assert waiting.wait(5)
        release.set()
        assert first.result(5) == {}
        with pytest.raises(PauseRequested):
            second.result(5)
    assert len(calls) == 1
    assert runtime.repository.get_job(runtime.job_id)["actual_cost"] == 1.0


def test_authentication_failure_is_not_retried(workspace, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from openai import AuthenticationError

    runtime = make_runtime(workspace, tmp_path, max_retries=3)
    calls = []

    class Client:
        def complete(self, **kwargs):
            calls.append(kwargs)
            raise AuthenticationError(
                "Invalid credential 429 is just text",
                response=SimpleNamespace(status_code=401, headers={}, request=None),
                body=None,
            )

    runtime.client = Client()
    monkeypatch.setattr(
        runtime, "_controlled_wait", lambda delay: pytest.fail("auth must not retry")
    )
    with pytest.raises(AuthenticationError):
        runtime.call_json(stage="translate", model="fake", system="", payload={})
    assert len(calls) == 1
