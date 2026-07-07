from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _settings(tmp_path: Path, db_name: str = "test.db") -> Settings:
    return Settings(
        ai_provider="mock",
        queue_provider="inline",
        message_provider="mock",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / db_name).as_posix()}",
        storage_dir=tmp_path / "storage",
        upload_dir=tmp_path / "storage" / "uploads",
        page_image_dir=tmp_path / "storage" / "pages",
    )


def test_app_instances_use_isolated_databases(tmp_path: Path) -> None:
    first_app = create_app(_settings(tmp_path / "first"))
    second_app = create_app(_settings(tmp_path / "second"))

    with TestClient(first_app) as client:
        response = client.post("/api/v1/instructors", json={"name": "Teacher A"})
        assert response.status_code == 200
        assert response.json()["name"] == "Teacher A"

    with TestClient(second_app) as client:
        response = client.get("/api/v1/instructors")
        assert response.status_code == 200
        assert response.json() == []


def test_inline_queue_creates_completed_submission(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_render_pdf_pages(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
        del pdf_path, dpi
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / "page_001.png"
        image_path.write_bytes(b"fake-png")
        return [image_path]

    monkeypatch.setattr("app.services.jobs.render_pdf_pages", fake_render_pdf_pages)

    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        instructor = client.post("/api/v1/instructors", json={"name": "Teacher A"}).json()
        headers = {"X-Instructor-Id": instructor["id"]}
        class_room = client.post(
            "/api/v1/classes",
            json={"name": "Monday"},
            headers=headers,
        ).json()
        client.post(
            "/api/v1/students",
            json={"name": "Mock Student", "class_ids": [class_room["id"]]},
            headers=headers,
        )

        response = client.post(
            "/api/v1/jobs",
            headers=headers,
            data={
                "class_id": class_room["id"],
                "question_count": "2",
                "comments_json": json.dumps(["문항 1", "문항 2"], ensure_ascii=False),
            },
            files={"pdf": ("answers.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 202
        job = response.json()
        assert job["status"] == "completed"

        submissions = client.get(
            f"/api/v1/jobs/{job['job_id']}/submissions",
            headers=headers,
        ).json()
        assert len(submissions) == 1
        assert submissions[0]["status"] == "completed"
        assert submissions[0]["student_name"] == "Mock Student"
        assert submissions[0]["total_score"] == 2.0
