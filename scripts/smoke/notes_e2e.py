"""End-to-end smoke of every note operation against the live dev stack.

Needs the full stack up (`docker compose up`) with the dev seed users.
Exercises create, read, draft update, optimistic-lock conflict, versions,
diff, sharing (member / visibility / public link / anonymous read + PDF),
synthesis, PDF, search scoping, finalize, revert, amend, cancel and delete
as four different callers (author, another member, tenant_admin, a member
of another tenant, and an anonymous reader). Exit 1 on any failure.

    make smoke-notes
"""
import sys, json, time
import httpx

AUTH, NOTE = "http://localhost:8000", "http://localhost:8006"
PW = "dev-password"
results: list[tuple[str, bool, str]] = []

def check(name, ok, info=""):
    results.append((name, bool(ok), info))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {info}"))

def login(email):
    r = httpx.post(f"{AUTH}/auth/login", json={"email": email, "password": PW})
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = httpx.get(f"{AUTH}/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    return httpx.Client(base_url=NOTE, headers={"Authorization": f"Bearer {tok}"}, timeout=30), me["claims"]["sub"]

member, member_sub = login("member@tenant-a.example")
admin, admin_sub = login("admin@tenant-a.example")
viewer, viewer_sub = login("viewer@tenant-a.example")
other, _ = login("member@tenant-b.example")
anon = httpx.Client(base_url=NOTE, timeout=30)

# templates
tpls = member.get("/templates").json()
tpl = next(t for t in tpls if t["code"] == "meeting_notes")
check("templates listed (en + uk)", any(t["code"] == "meeting_notes_uk" for t in tpls), str([t["code"] for t in tpls]))

def content(title, discussion):
    return {"template_id": tpl["id"], "template_schema_version": tpl["schema_version"], "title": title,
            "sections": [{"section_key": "attendees", "text": "Alice — PM\nBob — Eng"},
                         {"section_key": "discussion", "text": discussion},
                         {"section_key": "action_items", "text": "Bob: ship the thing — Friday"}]}

# 1. create
r = member.post("/v1/notes", json={"content": content("E2E sharing note", "We discussed the quarterly roadmap and budget planning in detail.")})
check("create note", r.status_code == 201, r.text[:200]); nid = r.json()["id"]

# 2. read + private by default
r = member.get(f"/v1/notes/{nid}"); check("get note (author)", r.status_code == 200 and r.json()["visibility"] == "private", r.text[:200])
r = viewer.get(f"/v1/notes/{nid}", params={"purpose": "review"}); check("private note hidden from other member (404)", r.status_code == 404, r.text[:120])
r = admin.get(f"/v1/notes/{nid}", params={"purpose": "review"}); check("private note readable by tenant_admin with purpose", r.status_code == 200, r.text[:120])
r = other.get(f"/v1/notes/{nid}", params={"purpose": "review"}); check("cross-tenant read is 404", r.status_code == 404, r.text[:120])

# 3. draft update
r = member.put(f"/v1/notes/{nid}/draft", json={"expected_version": 1, "content": content("E2E sharing note", "We discussed the quarterly roadmap and budget planning in detail. Decision: hire two engineers.")})
check("update draft -> v2", r.status_code == 200 and r.json()["version_number"] == 2, r.text[:200])
time.sleep(5.2)  # autosave: 1 PUT per 5 s per draft
r = member.put(f"/v1/notes/{nid}/draft", json={"expected_version": 1, "content": content("x", "stale write")})
check("stale draft write conflicts (409/412)", r.status_code in (409, 412), r.text[:120])

# 4. versions + diff
r = member.get(f"/v1/notes/{nid}/versions"); check("list versions (2)", r.status_code == 200 and len(r.json()) == 2, r.text[:120])
r = member.get(f"/v1/notes/{nid}/versions/1"); check("get version 1", r.status_code == 200, r.text[:120])
r = member.get(f"/v1/notes/{nid}/diff", params={"from": 1, "to": 2}); check("diff v1..v2", r.status_code == 200, r.text[:120])

# 5. sharing
r = member.get(f"/v1/notes/{nid}/sharing"); check("get sharing", r.status_code == 200 and r.json()["can_manage"], r.text[:200])
r = viewer.get(f"/v1/notes/{nid}/sharing"); check("sharing hidden from non-viewer", r.status_code == 404, r.text[:120])
r = member.post(f"/v1/notes/{nid}/share", json={"email": "viewer@tenant-a.example"})
check("share with member", r.status_code == 200 and any(m["sub"] == viewer_sub for m in r.json()["shared_with"]), r.text[:200])
r = viewer.get(f"/v1/notes/{nid}"); check("sharee can read without purpose", r.status_code == 200, r.text[:120])
r = viewer.put(f"/v1/notes/{nid}/visibility", json={"visibility": "workspace"}); check("sharee cannot manage (403)", r.status_code == 403, r.text[:120])
r = member.post(f"/v1/notes/{nid}/share", json={"email": "nobody@example.org"}); check("share with outsider -> 404 not_a_member", r.status_code == 404 and "not_a_member" in r.text, r.text[:120])
r = member.delete(f"/v1/notes/{nid}/share/{viewer_sub}"); check("unshare", r.status_code == 200 and r.json()["shared_with"] == [], r.text[:120])
r = viewer.get(f"/v1/notes/{nid}", params={"purpose": "review"}); check("unshared member loses access", r.status_code == 404, r.text[:120])
r = member.put(f"/v1/notes/{nid}/visibility", json={"visibility": "workspace"}); check("set workspace visibility", r.status_code == 200 and r.json()["visibility"] == "workspace", r.text[:120])
r = viewer.get(f"/v1/notes/{nid}", params={"purpose": "review"}); check("workspace note readable by any member (with purpose)", r.status_code == 200, r.text[:120])
r = viewer.get(f"/v1/notes/{nid}"); check("non-author without purpose -> 422", r.status_code == 422, r.text[:120])
r = member.put(f"/v1/notes/{nid}/visibility", json={"visibility": "private"}); check("back to private", r.json()["visibility"] == "private", r.text[:120])

# 6. public link
r = member.post(f"/v1/notes/{nid}/public-link"); check("create public link", r.status_code == 200 and r.json()["public_link"], r.text[:200])
token = r.json()["public_link"]["token"]
r2 = member.post(f"/v1/notes/{nid}/public-link"); check("public link idempotent", r2.json()["public_link"]["token"] == token, r2.text[:120])
r = anon.get(f"/v1/shared/{token}"); check("anonymous read via link", r.status_code == 200 and r.json()["title"] == "E2E sharing note" and len(r.json()["sections"]) == 3, r.text[:200])
r = anon.get(f"/v1/shared/{token}/pdf"); check("anonymous pdf via link", r.status_code == 200 and r.content[:4] == b"%PDF", r.text[:120])
r = anon.get(f"/v1/shared/{'x'*43}"); check("bogus token -> 404", r.status_code == 404, r.text[:120])
r = member.get(f"/v1/notes/{nid}/sharing"); check("view count recorded", r.json()["public_link"]["view_count"] >= 2, r.text[:200])
r = member.delete(f"/v1/notes/{nid}/public-link"); check("revoke public link", r.status_code == 200 and r.json()["public_link"] is None, r.text[:120])
r = anon.get(f"/v1/shared/{token}"); check("revoked link -> 404", r.status_code == 404, r.text[:120])

# 7. synthesize, pdf, search
r = member.post(f"/v1/notes/{nid}/synthesize", json={"language": "en"}); check("synthesize", r.status_code == 200, r.text[:200])
r = member.get(f"/v1/notes/{nid}/pdf"); check("author pdf", r.status_code == 200 and r.content[:4] == b"%PDF", r.text[:120])
r = member.get("/v1/notes/search", params={"q": "quarterly roadmap"}); check("search finds it (author)", r.status_code == 200 and any(h["note_id"] == nid for h in r.json()["hits"]), r.text[:200])
r = viewer.get("/v1/notes/search", params={"q": "quarterly roadmap"}); check("search hides private from others", r.status_code == 200 and not any(h["note_id"] == nid for h in r.json()["hits"]), r.text[:200])

# 8. finalize / amend / revert
r = member.post(f"/v1/notes/{nid}/finalize", json={"expected_version": 2}); check("finalize", r.status_code == 200 and r.json()["status"] == "finalized", r.text[:200])
time.sleep(5.2)
r = member.put(f"/v1/notes/{nid}/draft", json={"expected_version": 2, "content": content("x", "y")}); check("draft write on finalized rejected", r.status_code in (409, 422), r.text[:120])
r = member.post(f"/v1/notes/{nid}/revert-to-draft"); check("revert to draft", r.status_code == 200 and r.json()["status"] == "draft", r.text[:120])
r = member.post(f"/v1/notes/{nid}/finalize", json={"expected_version": 2}); check("finalize again", r.status_code == 200, r.text[:120])
r = member.post(f"/v1/notes/{nid}/amend", json={"amendment_type": "correction", "amendment_reason": "typo in decision", "content": content("E2E sharing note", "We discussed the quarterly roadmap. Decision: hire three engineers.")})
check("amend", r.status_code in (200, 201) and r.json()["note_status"] == "amended", r.text[:200])
r = member.get(f"/v1/notes/{nid}/pdf", params={"variant": "clean"}); check("clean pdf after amend", r.status_code == 200, r.text[:120])
r = member.get(f"/v1/notes/{nid}/versions"); check("versions grew (3)", len(r.json()) == 3, r.text[:120])

# 9. cancel (on a fresh draft)
r = member.post("/v1/notes", json={"content": content("E2E cancel note", "throwaway")}); nid2 = r.json()["id"]
r = member.post(f"/v1/notes/{nid2}/cancel", json={"reason": "duplicate"}); check("cancel", r.status_code == 200 and r.json()["status"] == "cancelled", r.text[:120])
r = member.get(f"/v1/notes/{nid2}/pdf"); check("cancelled note has no pdf (409)", r.status_code == 409, r.text[:120])

# 10. delete
r = viewer.delete(f"/v1/notes/{nid}"); check("stranger cannot delete (404)", r.status_code == 404, r.text[:120])
r = member.post("/v1/notes", json={"content": content("E2E delete note", "to be deleted")}); nid3 = r.json()["id"]
member.post(f"/v1/notes/{nid3}/public-link")
r = member.delete(f"/v1/notes/{nid3}"); check("delete", r.status_code == 200, r.text[:120])
r = member.get(f"/v1/notes/{nid3}"); check("deleted note gone (404)", r.status_code == 404, r.text[:120])
r = member.get("/v1/notes/search", params={"q": "to be deleted"}); check("deleted note not in search", not any(h["note_id"] == nid3 for h in r.json()["hits"]), r.text[:200])
r = admin.delete(f"/v1/notes/{nid}"); check("admin can delete another author's note", r.status_code == 200, r.text[:120])
r = member.delete(f"/v1/notes/{nid2}"); check("author deletes cancelled note", r.status_code == 200, r.text[:120])

failed = [x for x in results if not x[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
