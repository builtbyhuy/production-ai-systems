from compare_local import CASES, prepare_conditions, seed_memory
from pais.contracts import Principal
from pais.memory import MemoryService, local_redis


def test_comparison_retrieves_only_current_relevant_high_confidence_facts(tmp_path):
    with local_redis(tmp_path / "redis") as server:
        service = MemoryService(tmp_path / "comparison.db", server.url)
        principal = Principal(subject="operator", tenant_id="comparison", roles=["admin"])
        try:
            seed_memory(service, principal)
            rows = prepare_conditions(service, principal)
            assert len(rows) == 4
            for case in CASES:
                pair = [row for row in rows if row["case_id"] == case["id"]]
                assert {row["question"] for row in pair} == {case["question"]}
                assert {row["expected"] for row in pair} == {case["expected"]}
                enabled = next(row for row in pair if row["condition"] == "memory_enabled")
                disabled = next(row for row in pair if row["condition"] == "memory_disabled")
                assert enabled["memory_ids"] == [case["id"]]
                assert disabled["memory_ids"] == [] and disabled["context"] == ""
                assert case["expected"] in enabled["context"]
                assert "purple-nine" not in enabled["context"]
                assert "19:45" not in enabled["context"]
                assert "Cats" not in enabled["context"]
                assert enabled["messages"][0] == disabled["messages"][0]
        finally:
            service.close()
