import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from pais.contracts import Principal, TraceContext
from pais.jobs import (
    JobBusy,
    JobService,
    PermanentJobError,
    RetryableJobError,
    UncertainOutcome,
    create_celery_app,
    publish_outbox,
    sign_webhook,
)


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    principal = Principal(subject="owner", tenant_id="a", roles=["admin"])
    service = JobService(tmp_path / "jobs.db", clock=lambda: now[0], jitter=lambda: 0.5,
                         allow_stored_principal=True, lease_seconds=3)
    service.capability_flags.set(principal, "agent.execute", True, reason="explicit fixture setup")
    return service, principal, now


def accept(service, principal, key="event-1", note="reviewed"):
    body = json.dumps({"event_id": key, "tool": "record_note", "arguments": {"note": note},
                       "context_version": "v1"}).encode()
    signature = sign_webhook(body, "secret", int(service.clock()))
    return service.accept_webhook(principal, body, signature, "secret",
                                  TraceContext(traceparent="00-" + "1" * 32 + "-" + "2" * 16 + "-01"))


def test_signed_duplicate_and_tampered_webhooks(setup):
    service, principal, _now = setup
    original = accept(service, principal)
    assert accept(service, principal).job_id == original.job_id
    with pytest.raises(ValueError, match="different payload"):
        accept(service, principal, note="changed")
    body = b'{"event_id":"bad"}'
    with pytest.raises(PermissionError):
        service.accept_webhook(principal, body, sign_webhook(body, "wrong", 1000), "secret")
    with pytest.raises(PermissionError, match="validity window"):
        service.accept_webhook(principal, body, sign_webhook(body, "secret", 1), "secret")


def test_outbox_crash_after_publish_recovers_same_job(setup):
    service, principal, now = setup
    job = accept(service, principal)
    published = []

    def crash():
        raise RuntimeError("publisher crashed")

    with pytest.raises(RuntimeError):
        service.dispatch(lambda job_id, carrier: published.append((job_id, carrier)), after_publish=crash)
    assert published[0][0] == job.job_id
    assert published[0][1]["traceparent"].startswith("00-")
    now[0] += 4
    service.dispatch(lambda job_id, carrier: published.append((job_id, carrier)))
    assert len(published) == 2
    assert published[0][0] == published[1][0]
    service.execute(principal, job.job_id)
    service.execute(principal, job.job_id)
    assert service.effects.count(principal) == 1


def test_retry_backoff_exhaustion_dead_letter_and_safe_replay(setup):
    service, principal, now = setup
    job = accept(service, principal)

    def broken(*_):
        raise RetryableJobError("provider unavailable")

    for attempt in range(service.max_attempts):
        result = service.execute(principal, job.job_id, broken, downstream_idempotent=True)
        assert result.attempts == attempt + 1
        if attempt < service.max_attempts - 1:
            assert result.status == "retry"
            with pytest.raises(JobBusy):
                service.execute(principal, job.job_id, broken, downstream_idempotent=True)
        now[0] += 100
    assert result.status == "dead"
    replay = service.replay_dead(principal, job.job_id, "provider recovered and replay reviewed")
    assert replay.attempts == 0 and replay.status == "retry"
    assert service.execute(principal, job.job_id).status == "succeeded"


def test_crash_after_external_commit_and_lease_recovery(setup):
    service, principal, now = setup
    job = accept(service, principal)

    def crash():
        raise RuntimeError("worker killed")

    with pytest.raises(RuntimeError):
        service.execute(principal, job.job_id, after_effect=crash)
    assert service.effects.count(principal) == 1
    assert service.get(principal, job.job_id).status == "running"
    now[0] += 4
    assert service.recover_expired() == 1
    assert service.execute(principal, job.job_id).status == "succeeded"
    assert service.effects.count(principal) == 1


def test_uncertain_external_outcome_never_automatically_replayed(setup):
    service, principal, _now = setup
    job = accept(service, principal)

    def unsafe(*_):
        raise UncertainOutcome("network closed after request sent")

    result = service.execute(principal, job.job_id, unsafe, downstream_idempotent=False)
    assert result.status == "uncertain"
    assert service.execute(principal, job.job_id).status == "uncertain"
    with pytest.raises(ValueError, match="uncertain"):
        service.replay_dead(principal, job.job_id, "attempting dangerous replay")


def test_tenant_worker_authorization_and_revocation(setup):
    service, principal, _now = setup
    job = accept(service, principal)
    other = principal.model_copy(update={"tenant_id": "b"})
    with pytest.raises(LookupError):
        service.execute(other, job.job_id)
    locked = JobService(service.db.path)
    with pytest.raises(PermissionError, match="membership authorizer"):
        locked.worker_execute(job.job_id)
    revoked = JobService(service.db.path, authorizer=lambda p: p.model_copy(update={"roles": ["reader"]}))
    with pytest.raises(PermissionError):
        revoked.worker_execute(job.job_id)


def test_cancellation_poison_job_does_not_halt_others(setup):
    service, principal, _now = setup
    cancelled = accept(service, principal, "cancelled")
    service.cancel(principal, cancelled.job_id)
    assert service.execute(principal, cancelled.job_id).status == "cancelled"
    poison = accept(service, principal, "poison")
    healthy = accept(service, principal, "healthy")

    def permanent(*_):
        raise PermanentJobError("invalid downstream input")

    assert service.execute(principal, poison.job_id, permanent).status == "dead"
    assert service.execute(principal, healthy.job_id).status == "succeeded"
    assert service.effects.count(principal) == 1


def test_real_celery_eager_adapter_and_nonpersistent_broker_rejection(setup):
    service, principal, _now = setup
    job = accept(service, principal)
    with pytest.raises(ValueError, match="persistent"):
        create_celery_app(service, "memory://")
    app = create_celery_app(service, "memory://", eager=True)
    assert publish_outbox(service, app) == 1
    assert service.get(principal, job.job_id).status == "succeeded"
    assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost


def test_concurrent_duplicate_acceptance_and_feature_disable(setup):
    service, principal, _now = setup
    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(lambda _: accept(service, principal), range(8)))
    assert len({x.job_id for x in jobs}) == 1
    service.capability_flags.set(principal, "agent.execute", False, reason="emergency disable test")
    with pytest.raises(PermissionError):
        service.execute(principal, jobs[0].job_id)
