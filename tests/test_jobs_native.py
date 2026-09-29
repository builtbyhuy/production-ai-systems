from pais.jobs import native_demo


def test_real_redis_broker_celery_worker_crash_and_dead_letter_recovery(tmp_path):
    result = native_demo(tmp_path / "pipeline.db")
    assert result["real_celery_worker"]
    assert result["queue_before_restart"] == result["queue_after_restart"] == 1
    assert result["worker_crash_exit"] == 71
    assert result["effects_after_crash"] == result["effects_after_recovery"] == 1
    assert result["crash_job_attempts"] == 2
    assert result["dead_before_replay"] == "dead"
    assert result["dead_replay_status"] == result["unrelated_job_status"] == "succeeded"
    assert result["transient_attempts"] == 2
    assert result["visible_effects_total"] == 4
