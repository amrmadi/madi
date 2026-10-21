"""Tests for the AI capability endpoints.

These verify the honest behaviour the project promises:

* the API states, in a machine-readable way, that no model is loaded;
* it never returns a fabricated prediction;
* asking a predictor to run returns 503 `MODEL_NOT_LOADED`;
* an unknown predictor name is a 404, not a silent placeholder;
* an unauthenticated caller is rejected like everywhere else.

No dataset, no trained model, and no network access is required.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.identity import User
from backend.tests.conftest import auth_headers, create_user


def _headers(client: TestClient, caregiver_user: User) -> dict[str, str]:
    return auth_headers(client, caregiver_user.email)


# ---------------------------------------------------------------------------
# Listing capabilities
# ---------------------------------------------------------------------------


def test_listing_predictors_is_consistent_with_readiness(
    client: TestClient, caregiver_user: User
) -> None:
    """The list must describe all three problems and not contradict itself.

    Fall detection has a trained model, but the model file is git-ignored, so a
    fresh checkout reports it as not ready. Both states are honest; what must
    never happen is a predictor claiming to be ready with no metrics, or
    reporting metrics while insisting it is not ready.
    """
    response = client.get("/api/v1/ai/predictors", headers=_headers(client, caregiver_user))

    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["predictors"]) == 3
    assert body["any_ready"] is any(entry["is_ready"] for entry in body["predictors"])

    for entry in body["predictors"]:
        if entry["is_ready"]:
            assert entry["metrics"] is not None, f"{entry['name']} ready but no metrics"
            assert entry["model_version"], f"{entry['name']} ready but no version"
        else:
            assert entry["metrics"] is None, f"{entry['name']} not ready but has metrics"


def test_untrained_predictors_report_not_ready_with_no_metrics(
    client: TestClient, caregiver_user: User
) -> None:
    """Activity recognition and anomaly detection have no model implementation."""
    response = client.get("/api/v1/ai/predictors", headers=_headers(client, caregiver_user))
    by_name = {entry["name"]: entry for entry in response.json()["predictors"]}

    for name in ("activity_recognition", "anomaly_detection"):
        entry = by_name[name]
        assert entry["is_ready"] is False
        assert entry["metrics"] is None
        assert entry["model_version"] is None
        assert entry["trained_at"] is None


def test_listing_names_the_planned_dataset_for_each_problem(
    client: TestClient, caregiver_user: User
) -> None:
    response = client.get("/api/v1/ai/predictors", headers=_headers(client, caregiver_user))
    by_name = {entry["name"]: entry for entry in response.json()["predictors"]}

    assert by_name["fall_detection"]["dataset"] == "SisFall"
    assert by_name["activity_recognition"]["dataset"] == "UCI HAR"
    assert by_name["anomaly_detection"]["dataset"] == "CASAS"


def test_listing_carries_a_plain_language_note(
    client: TestClient, caregiver_user: User
) -> None:
    """A human reading the response should understand the status immediately.

    The note must be consistent with `any_ready`: never claim no model exists
    while a model is loaded, and never claim one is loaded when it is not.
    """
    response = client.get("/api/v1/ai/predictors", headers=_headers(client, caregiver_user))
    body = response.json()
    note = body["note"].lower()

    if body["any_ready"]:
        assert "loaded" in note
    else:
        assert "no ai model" in note
        assert "do not return predictions" in note


def test_listing_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/ai/predictors")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Reading one capability
# ---------------------------------------------------------------------------


def test_reading_one_predictor_is_consistent(
    client: TestClient, caregiver_user: User
) -> None:
    response = client.get(
        "/api/v1/ai/predictors/fall_detection", headers=_headers(client, caregiver_user)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "fall_detection"
    assert body["dataset"] == "SisFall"
    # Ready and metrics must agree; see the listing test for the reasoning.
    if body["is_ready"]:
        assert body["metrics"] is not None
        assert body["model_version"]
    else:
        assert body["metrics"] is None


def test_unknown_predictor_is_a_404_not_a_placeholder(
    client: TestClient, caregiver_user: User
) -> None:
    response = client.get(
        "/api/v1/ai/predictors/fortune_telling", headers=_headers(client, caregiver_user)
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    # The error should list what *is* available, so the caller can correct itself.
    assert "fall_detection" in body["error"]["details"]["known_predictors"]


# ---------------------------------------------------------------------------
# Asking a predictor to run
# ---------------------------------------------------------------------------


def test_checking_an_untrained_predictor_returns_503_model_not_loaded(
    client: TestClient, caregiver_user: User
) -> None:
    """The 'no model' path must be real and verifiable, not just documented.

    Activity recognition and anomaly detection have no predictor implementation,
    so this always holds for them.
    """
    for name in ("activity_recognition", "anomaly_detection"):
        response = client.post(
            f"/api/v1/ai/predictors/{name}/check",
            headers=_headers(client, caregiver_user),
        )

        assert response.status_code == 503, f"{name} returned {response.status_code}"
        body = response.json()
        assert body["error"]["code"] == "MODEL_NOT_LOADED"
        assert body["error"]["details"]["predictor"] == name
        assert body["error"]["details"]["reason"]


def test_checking_fall_detection_agrees_with_readiness(
    client: TestClient, caregiver_user: User
) -> None:
    """`check` and `is_ready` must never disagree.

    When the model file is present the check returns a real result flagged as
    research data; when it is absent the check is an honest 503. Both are
    correct, but a 200 without a model is not.
    """
    headers = _headers(client, caregiver_user)
    status = client.get("/api/v1/ai/predictors/fall_detection", headers=headers).json()

    response = client.post("/api/v1/ai/predictors/fall_detection/check", headers=headers)

    if status["is_ready"]:
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kind"] == "fall_detection"
        assert isinstance(body["is_fall"], bool)
        assert 0.0 <= body["confidence"] <= 1.0
        # SisFall is public research data, so it must never look like a live
        # reading of this resident.
        assert body["is_simulated"] is True
    else:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MODEL_NOT_LOADED"


def test_checking_a_predictor_never_returns_a_fabricated_label(
    client: TestClient, caregiver_user: User
) -> None:
    """A prediction is only ever returned together with an honest provenance.

    Guards against a future change that starts returning plausible-looking
    results with no model behind them: an untrained predictor must be a 503, and
    a returned result must name its model and its source.
    """
    for name in ("activity_recognition", "anomaly_detection"):
        response = client.post(
            f"/api/v1/ai/predictors/{name}/check", headers=_headers(client, caregiver_user)
        )
        assert response.status_code == 503, f"{name} returned {response.status_code}"
        assert "is_fall" not in response.json()

    response = client.post(
        "/api/v1/ai/predictors/fall_detection/check",
        headers=_headers(client, caregiver_user),
    )
    if response.status_code == 200:
        body = response.json()
        assert body["model_version"]
        assert "source" in body


def test_checking_an_unknown_predictor_is_a_404(
    client: TestClient, caregiver_user: User
) -> None:
    response = client.post(
        "/api/v1/ai/predictors/fortune_telling/check",
        headers=_headers(client, caregiver_user),
    )
    assert response.status_code == 404


def test_checking_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/ai/predictors/fall_detection/check")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Any signed-in role may see capabilities (no personal data is involved)
# ---------------------------------------------------------------------------


def test_resident_role_can_see_capabilities(
    client: TestClient, db_session: Session
) -> None:
    """This endpoint exposes no personal data, so it is not role-restricted."""
    from backend.app.models.enums import UserRole

    create_user(db_session, email="resident-ai@example.com", role=UserRole.ELDERLY)
    headers = auth_headers(client, "resident-ai@example.com")

    response = client.get("/api/v1/ai/predictors", headers=headers)

    assert response.status_code == 200, response.text
