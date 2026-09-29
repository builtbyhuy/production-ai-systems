"""Isolated, credential-free DeepEval and RAGAS metric execution."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import sys
from pathlib import Path

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
os.environ["RAGAS_DO_NOT_TRACK"] = "true"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import ExactMatch, NonLLMStringSimilarity


class SourceSupportMetric(BaseMetric):
    """Strict deterministic validation of source-backed extractive claims, not an LLM judge."""

    def __init__(self):
        self.threshold = 1.0
        self.async_mode = False
        self.strict_mode = True
        self.error = None
        self.evaluation_model = "exact-source-span-v1"

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        checks = (test_case.metadata or {}).get("source_checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError("Missing required source validation evidence")
        self.score = sum(check is True for check in checks) / len(checks)
        self.success = self.score >= self.threshold
        self.reason = f"{sum(check is True for check in checks)}/{len(checks)} exact source checks"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.error is None and self.score >= self.threshold

    @property
    def __name__(self) -> str:
        return "Source span support"


async def score(rows: list[dict]) -> dict:
    exact, similarity = ExactMatch(), NonLLMStringSimilarity()
    result = {}
    for row in rows:
        metric = SourceSupportMetric()
        case = LLMTestCase(
            input=row.get("question", row["id"]),
            actual_output=row.get("actual_text", ""),
            metadata={"source_checks": row["source_checks"]},
        )
        support = metric.measure(case)
        sample = SingleTurnSample(
            response=row.get("actual_reference", ""), reference=row.get("expected_reference", "")
        )
        result[row["id"]] = {
            "deepeval_source_support": support,
            "ragas_reference_exact_match": await exact.single_turn_ascore(sample),
            "ragas_reference_similarity": await similarity.single_turn_ascore(sample),
        }
    return {
        "results": result,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ["deepeval", "ragas", "langchain", "langchain-community"]
        },
        "judge": "none; deterministic source validation and string/reference metrics",
    }


if __name__ == "__main__":
    inputs, outputs = map(Path, sys.argv[1:3])
    report = asyncio.run(score(json.loads(inputs.read_text())))
    outputs.write_text(json.dumps(report, indent=2) + "\n")
