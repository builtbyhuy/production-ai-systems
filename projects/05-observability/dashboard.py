"""Generate the provisioned dashboard from the application's exact metric contract."""
import json
from pathlib import Path

PANELS = [
    ("Request volume", 'sum by (route) (rate(pais_requests_total{release=~"$release",route!="/api/metrics"}[2m]))', "reqps"),
    ("End to end p50 / p95 / p99", None, "s"),
    ("Protected first display p95", 'histogram_quantile(0.95,sum by(le)(rate(pais_first_display_seconds_bucket{release=~"$release"}[2m])))', "s"),
    ("Provider first token p95 (only when measured)", 'histogram_quantile(0.95,sum by(le)(rate(pais_provider_ttft_seconds_bucket{release=~"$release"}[2m])))', "s"),
    ("Provider attempts by outcome", 'sum by(model,outcome)(increase(pais_provider_attempts_total{release=~"$release"}[5m]))', "short"),
    ("Reported provider tokens", 'sum by(direction)(increase(pais_model_tokens_total{release=~"$release"}[5m]))', "short"),
    ("Ledger costs and unresolved reservations", 'sum by(kind)(pais_ledger_cost_microusd{release=~"$release"}) / 1000000', "currencyUSD"),
    ("Budget utilization", 'pais_budget_utilization_ratio{release=~"$release"}', "percentunit"),
    ("Queue depth", 'sum by(queue)(pais_queue_depth{release=~"$release"})', "short"),
    ("Retries and cache use", 'sum by(kind)(increase(pais_retries_total{release=~"$release"}[5m]))', "short"),
    ("Observed quality signals", 'sum by(kind,outcome)(increase(pais_quality_observations_total{release=~"$release"}[5m]))', "short"),
    ("Stages p95", 'histogram_quantile(0.95,sum by(le,stage)(rate(pais_stage_duration_seconds_bucket{release=~"$release"}[2m])))', "s"),
]


def generate(path: Path):
    panels = []
    for index, (title, expression, unit) in enumerate(PANELS):
        targets = [{"refId": "A", "expr": expression, "legendFormat": "{{route}}{{model}}{{outcome}}{{kind}}{{direction}}{{stage}}{{queue}}"}]
        if expression is None:
            targets = [{"refId": chr(65+i), "expr": f'histogram_quantile({q},sum by(le)(rate(pais_request_duration_seconds_bucket{{release=~"$release",route!="/api/metrics"}}[2m])))',
                        "legendFormat": f"p{int(q*100)}"} for i, q in enumerate((0.5, 0.95, 0.99))]
        panels.append({"id": index+1, "type": "timeseries", "title": title,
                       "datasource": {"type": "prometheus", "uid": "prometheus"},
                       "gridPos": {"x": (index % 2)*12, "y": (index//2)*7, "w": 12, "h": 7},
                       "targets": targets,
                       "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
                       "options": {"legend": {"displayMode": "list", "placement": "bottom"}}})
        if unit == "currencyUSD":
            panels[-1]["description"] = "Durable ledger totals, in USD. Native and fixture drills use illustrative simulated prices; these are not provider invoices."
            panels[-1]["fieldConfig"]["defaults"]["decimals"] = 6
    document = {"uid": "pais-operations", "title": "PAIS application reliability",
                "tags": ["pais", "measured-application-traffic"], "schemaVersion": 40, "version": 1,
                "refresh": "5s", "time": {"from": "now-30m", "to": "now"},
                "templating": {"list": [{"name": "release", "type": "query",
                                          "datasource": {"type": "prometheus", "uid": "prometheus"},
                                          "query": "label_values(pais_requests_total, release)",
                                          "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"}}]},
                "panels": panels}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2))


if __name__ == "__main__":
    generate(Path("infra/monitoring/dashboards/application.json"))
