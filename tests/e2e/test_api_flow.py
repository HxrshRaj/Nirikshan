"""End-to-end through the HTTP API with auth + RBAC."""

import pytest

pytestmark = pytest.mark.e2e


def test_api_incident_lifecycle(api_client, auth_headers):
    admin = auth_headers()
    assert api_client.post("/api/demo/seed", headers=admin).status_code == 200

    r = api_client.post("/api/demo/run-scenario", headers=admin,
                        json={"scenario": "db-exhaustion", "investigate": True, "propose_remediation": True})
    assert r.status_code == 200
    d = r.json()
    ref = d["incident_ref"]
    assert d["category_match"] is True

    detail = api_client.get(f"/api/incidents/{ref}", headers=admin).json()
    assert detail["root_cause"]
    assert detail["evidence"] and detail["hypotheses"]
    assert detail["hypotheses"][0]["is_selected"]

    rca = api_client.get(f"/api/incidents/{ref}/rca", headers=admin).json()
    assert rca["is_mock"] is True
    assert rca["confidence"] >= 0.6

    tl = api_client.get(f"/api/incidents/{ref}/timeline", headers=admin).json()
    assert any(e["kind"] == "investigation_started" for e in tl)

    # remediation loop
    drive = api_client.post("/api/demo/drive-remediation", headers=admin,
                            json={"incident_ref": ref, "scenario": "db-exhaustion"})
    assert drive.status_code == 200
    assert drive.json()["verified"] is True
    assert drive.json()["incident_status"] == "RESOLVED"


def test_rbac_viewer_cannot_mutate(api_client, auth_headers):
    admin = auth_headers()
    api_client.post("/api/demo/seed", headers=admin)
    # create a viewer
    api_client.post("/api/users", headers=admin,
                    json={"email": "viewer@nirikshan.dev", "password": "viewer12345", "role": "VIEWER"})
    viewer = auth_headers("viewer@nirikshan.dev", "viewer12345")

    assert api_client.get("/api/incidents", headers=viewer).status_code == 200
    r = api_client.post("/api/demo/run-scenario", headers=viewer, json={"scenario": "db-exhaustion"})
    assert r.status_code == 403
    assert api_client.get("/api/audit", headers=viewer).status_code == 403


def test_unauthenticated_is_rejected(api_client):
    assert api_client.get("/api/incidents").status_code == 401
    assert api_client.get("/api/overview").status_code == 401


def test_health_is_public(api_client):
    r = api_client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] in ("ok", "degraded")
