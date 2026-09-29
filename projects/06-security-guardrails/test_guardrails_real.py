"""Required real-framework gate. Run using this project's isolated interpreter."""
from importlib.metadata import version

import pytest
from pais.security import GuardrailsEnforcer, SecurityPolicy, SecurityViolation


def test_actual_guardrails_validates_and_rejects():
    guard = GuardrailsEnforcer()
    assert version("guardrails-ai") == "0.6.8"
    assert guard.validate("Deployment timeout is 30 seconds") == "Deployment timeout is 30 seconds"
    with pytest.raises(SecurityViolation):
        guard.validate("-----BEGIN PRIVATE KEY----- fixture-only-not-a-real-key")


def test_actual_framework_is_in_the_policy_enforcement_path():
    policy = SecurityPolicy(require_guardrails=True)
    assert policy.validator_profile == "guardrails-ai"
    assert policy.filter_output("Contact person@example.com") == "Contact [REDACTED_EMAIL]"
    with pytest.raises(SecurityViolation):
        policy.filter_output("sk-"+"x"*30)


def test_framework_validation_failure_never_returns_protected_text(monkeypatch):
    policy = SecurityPolicy(require_guardrails=True)
    def broken(*args, **kwargs):
        raise RuntimeError("raw protected email person@example.com")
    monkeypatch.setattr(type(policy.guardrails.guard), "validate", broken)
    with pytest.raises(SecurityViolation) as failure:
        policy.filter_output("protected content")
    assert "person@example.com" not in str(failure.value)
