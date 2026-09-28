"""End-to-end with real VTU papers (skipped when data/raw isn't present)."""

from server.tests.conftest import ADMIN, real_paper, upload


def _upload_and_confirm(client, drain, name, **overrides):
    created = upload(client, real_paper(name), name).json()
    headers = {"X-Upload-Token": created["token"]}
    drain()
    s = client.get(f"/api/uploads/{created['id']}", headers=headers).json()
    assert s["status"] == "awaiting_confirmation", s
    assert s["questionCount"] >= 8 and len(s["preview"]) == 3
    body = {"subjectCode": s["subjectCode"] or "BCS502", "examYear": s["examYear"],
            "examMonth": s["examMonth"], "paperType": s["paperType"], **overrides}
    r = client.post(f"/api/uploads/{created['id']}/confirm", json=body, headers=headers)
    assert r.status_code == 200, r.text
    drain()
    return created["id"], client.get(f"/api/uploads/{created['id']}", headers=headers).json()


def test_papers_publish_and_duplicates_go_to_review(client, drain):
    jan_id, jan = _upload_and_confirm(client, drain, "JAN 2025 BCS502.pdf")
    assert jan["status"] == "approved"
    _, jul = _upload_and_confirm(client, drain, "july 2025 BCS502.pdf")
    assert jul["status"] == "approved"

    # Published snapshot
    subject = client.get("/api/subjects/bcs502").json()
    assert subject["code"] == "BCS502" and subject["paperCount"] == 2
    assert [s["label"] for s in subject["sessions"]] == ["Jul 2025", "Jan 2025"]
    topic = subject["modules"][0]["topics"][0]
    assert topic["key"] and topic["label"] and topic["wordings"]
    keys_before = {t["key"] for m in subject["modules"] for t in m["topics"]}

    assert client.get("/api/subjects/BCS502/cheatsheet.pdf").content.startswith(b"%PDF")
    assert "Question Text" in client.get("/api/subjects/BCS502/questions.csv").text
    assert any(s["code"] == "BCS502" for s in client.get("/api/subjects").json())

    # A different scan of the January 2025 exam: same session → held for review
    dup_id, dup = _upload_and_confirm(client, drain, "DecJan_2025_-_Scheme  CN-1-2.pdf", subjectCode="BCS502")
    assert dup["status"] == "review"
    assert "already have the Jan 2025 paper" in dup["reason"]
    assert client.get("/api/subjects/BCS502").json()["paperCount"] == 2   # nothing changed publicly

    detail = client.get(f"/api/admin/papers/{dup_id}", headers=ADMIN).json()
    assert detail["comparison"]["against"]["id"] == jan_id
    assert detail["comparison"]["pairs"]

    # Approving would clash with the live session; replacing swaps them
    assert client.post(f"/api/admin/papers/{dup_id}/approve", headers=ADMIN).status_code == 400
    r = client.post(f"/api/admin/papers/{dup_id}/replace", json={"replaces": jan_id}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    drain()
    assert client.get(f"/api/admin/papers/{jan_id}", headers=ADMIN).json()["status"] == "rejected"

    # Topic keys survive the rebuild for topics that still exist
    after = client.get("/api/subjects/BCS502").json()
    keys_after = {t["key"] for m in after["modules"] for t in m["topics"]}
    assert len(keys_before & keys_after) >= len(keys_before) // 2

    # Taking a live paper down republishes the subject
    client.post(f"/api/admin/papers/{dup_id}/reject", json={"reason": "test"}, headers=ADMIN)
    drain()
    assert client.get("/api/subjects/BCS502").json()["paperCount"] == 1
