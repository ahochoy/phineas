from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from phineas.api import create_app
from phineas.jobs import InMemoryJobStore, QuestionJobService, QuestionWorker
from phineas.sessions import InMemorySessionStore
from phineas.web import create_web_app


def test_web_serves_only_its_assets_with_private_response_headers() -> None:
    with TestClient(create_web_app(create_app())) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Interface preview" not in response.text
        assert "SYNTHETIC DATA ONLY" in response.text
        assert 'type="module" src="app.mjs"' in response.text
        for path in ("/", "/styles.css", "/app.mjs", "/client.mjs", "/api/health"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        for path in ("/terraform.tfvars", "/terraform.tfstate", "/.git/config", "/src/phineas/api.py", "/api/nonexistent", "/preview-data.json"):
            assert client.get(path).status_code == 404


def test_web_uses_existing_session_job_grounding_and_purge_services() -> None:
    sessions = InMemorySessionStore()
    jobs = InMemoryJobStore(sessions)
    provider = Mock()
    provider.explain.return_value = '{"paragraphs":[{"text":"Your statement includes fees totaling USD 9.00. The aggregate does not establish its cause or whether it repeats.","fact_ids":["fee"]}]}'
    worker = QuestionWorker(sessions, jobs, provider)
    queue = Mock()
    # Complete delivery immediately in this test only; production remains SQS.
    queue.enqueue.side_effect = worker.process
    service = QuestionJobService(sessions, jobs, queue)
    api = create_app(sessions, provider, service)
    with TestClient(create_web_app(api)) as client:
        created = client.post("/api/sessions", json={"sample_id": "analysis-demo"})
        assert created.status_code == 201
        session_id = created.json()["session_id"]
        path = f"/api/sessions/{session_id}"
        report = client.get(f"{path}/report")
        assert report.status_code == 200
        assert report.json()["analysis"]["summary"]["total_outflow"] == "1736.17"
        fee = next(fact for fact in report.json()["facts"] if fact["fact_id"] == "fee")
        assert fee["text"] == "3 outflow fee transaction(s) total USD 9.00."
        for forbidden in ("Example Streaming", "Sample Shop", "original_description", "evidence_transaction_ids"):
            assert forbidden not in report.text
        provider.explain.assert_not_called()
        request = {"request_id": str(uuid4()), "question": "Explain fees"}
        submitted = client.post(f"{path}/question-jobs", json=request)
        assert submitted.status_code == 202
        job_path = f"{path}/jobs/{submitted.json()['job_id']}"
        completed = client.get(job_path).json()
        assert completed["state"] == "succeeded"
        assert completed["result"]["narrative"]["highlights"] == [fee]
        assert completed["result"]["explanation"]["status"] == "generated"
        paragraph = completed["result"]["explanation"]["paragraphs"][0]
        assert paragraph["fact_ids"] == ["fee"]
        assert paragraph["text"] != fee["text"]
        assert client.post(f"{path}/question-jobs", json=request).status_code == 202
        assert provider.explain.call_count == 1
        assert client.delete(path).status_code == 204
        assert client.get(f"{path}/report").json() == {"detail": "session_unavailable"}
        assert client.get(job_path).status_code == 404


def test_report_rejects_nonexistent_session_and_no_async_fallback() -> None:
    with TestClient(create_web_app(create_app())) as client:
        assert client.get("/api/sessions/nonexistent/report").status_code == 404
        response = client.post("/api/sessions/nonexistent/question-jobs", json={
            "request_id": str(uuid4()), "question": "Explain fees",
        })
        assert response.status_code == 503
        assert response.json()["detail"] == "async_questions_not_configured"


def test_browser_code_has_no_persistence_or_html_injection_sinks() -> None:
    directory = Path(__file__).resolve().parents[1] / "web"
    for name in ("app.mjs", "client.mjs"):
        script = (directory / name).read_text()
        for unsafe in ("localStorage", "sessionStorage", "innerHTML", "console.log", "preview-data.json"):
            assert unsafe not in script


def test_v1_ui_has_guided_buttons_without_free_text_composer() -> None:
    directory = Path(__file__).resolve().parents[1] / "web"
    html = (directory / "index.html").read_text()
    script = (directory / "app.mjs").read_text()
    assert 'id="suggestions"' in html
    assert 'role="group" aria-label="Analysis questions"' in html
    assert "not custom chat" in html
    for removed in ('id="question-form"', 'id="question"', 'id="send"'):
        assert removed not in html
    for selector in ('$("#question-form")', '$("#question")', '$("#send")'):
        assert selector not in script
    assert 'button.type = "button"' in script
    assert "workspace.ask(question)" in script
    client_script = (directory / "client.mjs").read_text()
    assert "type one below" not in client_script
    assert "Choose a question button" in client_script
