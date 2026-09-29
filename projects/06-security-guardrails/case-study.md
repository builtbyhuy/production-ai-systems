# Case study — Fail closed at the expensive boundary

Prompt-injection recognition is useful for review, but it cannot be an authorization system.
The measured corpus makes that visible: two malicious inputs passed the pattern checks and a
benign explanatory question was flagged. Consequently, the implementation always checks a
trusted principal, static tool permissions, and strict arguments at execution time. A model
can return a plausible tool request without acquiring the right to run it.

The same reasoning shaped output handling. Redacting each tiny provider chunk independently
would miss a credential split across chunks. The API buffers the protected answer, validates
it, redacts selected PII in answer/citation strings, and only then emits AI SDK text events.
This delays first display. It is a deliberate, measurable policy with a documented streaming
limitation, not a hidden streaming claim.

Guardrails runs a real validator. Its package tree is isolated so framework dependencies do
not silently rewrite the API's observability stack. A fixed trusted worker accepts bounded
JSON, disables metrics collection and reasks, and returns a checked result. Unknown result
shape, worker timeout, missing interpreter or validator rejection prevents protected delivery.
This worker is dependency isolation only; it supplies no boundary for arbitrary Python source.

The sandbox exposed the most important environment limitation. Bubblewrap existed, but an
actual namespace probe failed while creating a network-control socket. Treating binary presence
as successful isolation would have been a serious error. The code therefore remains disabled
until a separate runtime verifies the requested rootless container and resource controls.
The runnable adapter is useful engineering work, but file/network/resource-denial acceptance
remains incomplete until executed in that environment.

The tests also catch a subtler failure: disabling fixture authentication after a restart cannot
leave an old fixture credential authorized through the persistent credential table. Fixture
tokens are resolved in a separate startup-gated branch and never stored as normal credentials.
