import pytest

pytestmark = pytest.mark.unit


def _post_metric(client, headers=None):
    return client.post(
        "/api/telemetry/metrics",
        json={"service": "svc", "metric_name": "cpu_usage", "value": 0.5},
        headers=headers or {},
    )


def test_ingestion_open_by_default(api_client):
    assert _post_metric(api_client).status_code == 200


def test_ingestion_requires_token_when_configured(api_client, monkeypatch):
    monkeypatch.setenv("NIRIKSHAN_INGEST_TOKEN", "s3cr3t-collector-key")
    from nirikshan.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert _post_metric(api_client).status_code == 401
        assert _post_metric(api_client, {"X-Ingest-Token": "wrong"}).status_code == 401
        assert _post_metric(api_client, {"X-Ingest-Token": "s3cr3t-collector-key"}).status_code == 200
    finally:
        get_settings.cache_clear()
