"""Phase 6 evidence against real MySQL and a real S3 server (SeaweedFS in Docker): upload after the
financial commit, quarantine then worker verification, download headers, one active file per activity,
retry identity, refusals, owner isolation, removal, deleted activities, and AC-21 (storage down after the
commit: the transaction stays confirmed and a retry of the same upload creates nothing new)."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import http.client
import json
import subprocess
import time
from urllib.parse import quote
import urllib.error
import urllib.request
import uuid
import zlib

from phase1_auth import DB, available_port, check, wait_for
from phase2_financial import activity, operation, signed_in

IMAGE = "chrislusf/seaweedfs:4.53"
BUCKET = "duit-evidence"


@contextmanager
def object_storage(work):
    """A private S3 endpoint on 127.0.0.1 with one signed identity; anonymous access is refused."""
    port, name = available_port(), f"duit-s3-{uuid.uuid4().hex[:8]}"
    access, secret = "duit" + uuid.uuid4().hex[:16], uuid.uuid4().hex + uuid.uuid4().hex
    config = work / "s3.json"
    config.write_text(json.dumps({"identities": [{"name": "duit", "credentials": [
        {"accessKey": access, "secretKey": secret}], "actions": ["Admin", "Read", "Write", "List"]}]}))
    subprocess.run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8333",
                    "-v", f"{config}:/etc/duit-s3.json:ro", IMAGE, "server", "-s3", "-s3.config=/etc/duit-s3.json"],
                   check=True, capture_output=True, timeout=120)
    env = {"DUIT_S3_ENDPOINT": f"http://127.0.0.1:{port}", "DUIT_S3_BUCKET": BUCKET,
           "DUIT_S3_ACCESS_KEY": access, "DUIT_S3_SECRET_KEY": secret}
    try:
        storage_ready(port)
        yield {"env": env, "name": name, "port": port}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


def storage_ready(port, timeout=60):
    def answer():
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
        except urllib.error.HTTPError:
            return True  # any S3 answer (403 for an unsigned request) means it is serving
        except OSError:
            return None
        return True
    wait_for(answer, timeout)


def init_bucket(api, env):
    def attempt():  # the filer behind the S3 gateway may still be starting
        return True if subprocess.run([api, "init-storage"], env=env, capture_output=True, timeout=30).returncode == 0 else None
    wait_for(attempt, 60)


def png(width=2, height=2):
    """A real, decodable RGB PNG (the browser preview test shows it)."""
    def chunk(kind, data):
        return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")
    raw = b"".join(b"\x00" + b"\x2e\x8b\x57" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def put_file(client, activity_id, upload, name, body, content_type, status):
    headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in client.cookies.items()), "Origin": client.origin,
               "X-Duit-CSRF": "1", "X-Duit-File-Name": quote(name, safe="")}
    if content_type:
        headers["Content-Type"] = content_type
    conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=40)
    try:
        conn.request("PUT", f"/api/v1/activities/{activity_id}/evidence/{upload}", body, headers)
        response = conn.getresponse()
        value = json.loads(response.read() or b"null")
        if isinstance(status, tuple):
            check(response.status in status, True)
        else:
            check(response.status, status)
        check(response.headers["Cache-Control"], "no-store")
        return value
    finally:
        conn.close()


def get_raw(client, path):
    conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=30)
    try:
        conn.request("GET", "/api/v1" + path, headers={"Cookie": "; ".join(f"{k}={v}" for k, v in client.cookies.items())})
        response = conn.getresponse()
        return response.status, response.headers, response.read()  # case-insensitive
    finally:
        conn.close()


def s3_request(storage, key, method, body=b""):
    env, host = storage["env"], f"127.0.0.1:{storage['port']}"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = hashlib.sha256(body).hexdigest()
    path = f"/{BUCKET}/{key}"
    canonical = f"{method}\n{path}\n\nhost:{host}\nx-amz-content-sha256:{payload}\nx-amz-date:{stamp}\n\nhost;x-amz-content-sha256;x-amz-date\n{payload}"
    scope = f"{stamp[:8]}/us-east-1/s3/aws4_request"
    to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    key_bytes = ("AWS4" + env["DUIT_S3_SECRET_KEY"]).encode()
    for part in (stamp[:8], "us-east-1", "s3", "aws4_request"):
        key_bytes = hmac.new(key_bytes, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key_bytes, to_sign.encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(env["DUIT_S3_ENDPOINT"] + path, body if method == "PUT" else None, method=method, headers={
        "x-amz-date": stamp, "x-amz-content-sha256": payload, "Authorization":
        f"AWS4-HMAC-SHA256 Credential={env['DUIT_S3_ACCESS_KEY']}/{scope}, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature={signature}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as reply:
        return reply.code, reply.read()


def status_of(client, activity_id):
    value = client.request("GET", f"/activities/{activity_id}/evidence", 200)
    return value and value["status"]


def until(client, activity_id, wanted):
    wait_for(lambda: True if status_of(client, activity_id) == wanted else None, 30)


def evidence_test(database, mail, api_port, origin, storage):
    alice = signed_in(mail, api_port, origin, "ev-alice")
    bob = signed_in(mail, api_port, origin, "ev-bob")
    operation(alice, "/onboarding/skip-opening-balance")
    past = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    spent = operation(alice, "/activities", activity("DEDUCT", 25000, past, title="Makan"))["resourceId"]
    before = alice.request("GET", "/financial-state", 200)
    check(alice.request("GET", f"/activities/{spent}/evidence", 200), None)

    # Upload: QUARANTINED first, AVAILABLE only after the worker re-reads and re-checks the stored object.
    first, image = str(uuid.uuid4()), png()
    view = put_file(alice, spent, first, "struk makan.png", image, "image/png", 202)
    check((view["id"], view["fileName"], view["contentType"], view["size"]), (first, "struk makan.png", "image/png", len(image)))
    assert view["status"] in ("QUARANTINED", "AVAILABLE")
    status, _, _ = get_raw(alice, f"/activities/{spent}/evidence/content")
    assert status in (404, 200)  # 404 while quarantined: never served before verification
    until(alice, spent, "AVAILABLE")
    status, headers, body = get_raw(alice, f"/activities/{spent}/evidence/content")
    check((status, body), (200, image))
    check((headers["Content-Type"], headers["X-Content-Type-Options"], headers["Cache-Control"]), ("image/png", "nosniff", "no-store"))
    check(headers["Content-Security-Policy"], "sandbox; default-src 'none'")
    check(headers["Content-Disposition"], "attachment; filename=\"bukti.png\"; filename*=UTF-8''struk%20makan%2Epng")
    check(put_file(alice, spent, first, "struk makan.png", image, "image/png", 200)["id"], first)  # same upload: no second file
    check(database.rows(f"USE {DB}; SELECT COUNT(*) FROM evidence WHERE id='{first}';"), ["1"])
    check(alice.request("GET", "/financial-state", 200), before)  # evidence never touches money
    print("Evidence: upload after commit, quarantine then AVAILABLE, exact bytes and safe download headers, "
          "same upload id stored once, financial state unchanged", flush=True)

    # Refusals by content, not by the client's claim; nothing is stored.
    rows = database.rows(f"USE {DB}; SELECT COUNT(*) FROM evidence;")
    for name, body, ctype, reason in [
        ("virus.png", b"MZ\x90\x00" + b"\x00" * 64, "image/png", "TYPE"),
        ("foto.jpg", image, "image/jpeg", "TYPE"),
        ("foto.jpg", image, "", "NAME"),
        ("potong.png", image[:30], "image/png", "STRUCTURE"),
        ("kosong.pdf", b"", "application/pdf", "EMPTY"),
    ]:
        refused = put_file(alice, spent, str(uuid.uuid4()), name, body, ctype, 422)
        check((refused["code"], refused["conflictDetails"]["reason"]), ("EVIDENCE_REJECTED", reason))
    # Over 10 MB is refused from the declared length before the body is read (the read itself is capped too).
    conn = http.client.HTTPConnection("127.0.0.1", alice.port, timeout=30)
    conn.putrequest("PUT", f"/api/v1/activities/{spent}/evidence/{uuid.uuid4()}")
    for header, value in {"Cookie": "; ".join(f"{k}={v}" for k, v in alice.cookies.items()), "Origin": origin,
                          "X-Duit-CSRF": "1", "X-Duit-File-Name": "besar.pdf", "Content-Type": "application/pdf",
                          "Content-Length": str(10 * 1024 * 1024 + 1)}.items():
        conn.putheader(header, value)
    conn.endheaders()
    response = conn.getresponse()
    check((response.status, json.loads(response.read())["conflictDetails"]["reason"]), (422, "TOO_LARGE"))
    conn.close()
    check(database.rows(f"USE {DB}; SELECT COUNT(*) FROM evidence;"), rows)
    check(status_of(alice, spent), "AVAILABLE")
    print("Evidence refusals: wrong signature, claim/extension mismatch, truncated, over 10 MB, empty; nothing stored", flush=True)

    # Replace: one active file per activity, the old one REMOVED (kept, not purged).
    second = str(uuid.uuid4())
    put_file(alice, spent, second, "nota.pdf", PDF, "application/pdf", 202)
    until(alice, spent, "AVAILABLE")
    check(alice.request("GET", f"/activities/{spent}/evidence", 200)["id"], second)
    check(database.rows(f"USE {DB}; SELECT id, status FROM evidence WHERE activity_id='{spent}' ORDER BY created_at;"),
          [f"{first}\tREMOVED", f"{second}\tAVAILABLE"])

    # Owner isolation: another account gets the same 404 as a missing activity, for every operation.
    missing = str(uuid.uuid4())
    for target in (spent, missing):
        check(bob.request("GET", f"/activities/{target}/evidence", 404)["code"], "NOT_FOUND")
        check(get_raw(bob, f"/activities/{target}/evidence/content")[0], 404)
        check(bob.request("DELETE", f"/activities/{target}/evidence", 404)["code"], "NOT_FOUND")
        check(put_file(bob, target, str(uuid.uuid4()), "x.png", image, "image/png", 404)["code"], "NOT_FOUND")
    check(put_file(bob, spent, second, "x.png", image, "image/png", 404)["code"], "NOT_FOUND")  # reused upload id
    print("Evidence: replace keeps one active file; another owner gets 404 for read, download, upload and delete", flush=True)

    # A stored object that changed is never served, and a re-check rejects it.
    key = database.rows(f"USE {DB}; SELECT object_key FROM evidence WHERE id='{second}';")[0]
    check(s3_request(storage, key, "PUT", PDF.replace(b"Catalog", b"Katalog"))[0], 200)
    check(get_raw(alice, f"/activities/{spent}/evidence/content")[0], 500)
    database.query(f"USE {DB}; UPDATE evidence SET status='QUARANTINED', next_run_at=0 WHERE id='{second}';")
    until(alice, spent, "REJECTED")
    check(get_raw(alice, f"/activities/{spent}/evidence/content")[0], 404)
    print("Evidence: a changed stored object is refused on download and REJECTED by the worker re-check", flush=True)

    # Removal: detached and audited; the transaction itself is untouched.
    put_file(alice, spent, str(uuid.uuid4()), "nota.pdf", PDF, "application/pdf", 202)
    until(alice, spent, "AVAILABLE")
    alice.request("DELETE", f"/activities/{spent}/evidence", 204)
    check(alice.request("GET", f"/activities/{spent}/evidence", 200), None)  # the earlier refused file was superseded
    alice.request("DELETE", f"/activities/{spent}/evidence", 404)
    actions = [item["action"] for item in alice.request("GET", f"/audit?resourceId={spent}", 200)["items"]]
    for action, count in [("EVIDENCE_ATTACHED", 3), ("EVIDENCE_VERIFIED", 3), ("EVIDENCE_REJECTED", 1), ("EVIDENCE_REMOVED", 1)]:
        check(actions.count(action), count)
    check(alice.request("GET", f"/activities/{spent}", 200)["deleted"], False)

    # AC-21: storage down after the financial commit.
    count = len(alice.request("GET", "/activities", 200)["items"])
    bought = operation(alice, "/activities", activity("DEDUCT", 7000, past, title="Parkir"))["resourceId"]
    confirmed = alice.request("GET", "/financial-state", 200)
    subprocess.run(["docker", "stop", "-t", "2", storage["name"]], check=True, capture_output=True, timeout=60)
    retry = str(uuid.uuid4())
    try:
        down = put_file(alice, bought, retry, "parkir.png", image, "image/png", 503)
        check((down["code"], down["retryable"]), ("TEMPORARY_FAILURE", True))
        check(alice.request("GET", f"/activities/{bought}", 200)["deleted"], False)
        check(alice.request("GET", "/financial-state", 200), confirmed)
        check(alice.request("GET", f"/activities/{bought}/evidence", 200), None)
    finally:
        subprocess.run(["docker", "start", storage["name"]], check=True, capture_output=True, timeout=60)
    storage_ready(storage["port"])
    wait_for(lambda: True if put_file_quiet(alice, bought, retry, image) else None, 60)
    until(alice, bought, "AVAILABLE")
    check(len(alice.request("GET", "/activities", 200)["items"]), count + 1)
    check(alice.request("GET", "/financial-state", 200), confirmed)
    print("Evidence AC-21: storage down after commit gives a retryable 503, the transaction stays confirmed; the "
          "same upload id succeeds later with no new transaction", flush=True)

    cleanup_test(database, storage, alice, bought, retry, image, confirmed)

    # A deleted activity keeps its evidence readable but takes no new file.
    version = alice.request("GET", f"/activities/{bought}", 200)["version"]
    operation(alice, f"/activities/{bought}", {"expectedVersion": version}, "DELETE")
    check(put_file(alice, bought, str(uuid.uuid4()), "x.png", image, "image/png", 409)["code"], "INVALID_ACTIVITY_STATE")
    check(status_of(alice, bought), "AVAILABLE")
    check(get_raw(alice, f"/activities/{bought}/evidence/content")[0], 200)
    print("Evidence: removal audited; a deleted activity keeps readable evidence and refuses new files", flush=True)


def cleanup_test(database, storage, client, activity_id, previous_upload, image, confirmed):
    def keys():
        return set(database.rows(f"USE {DB}; SELECT object_key FROM evidence_cleanup;"))

    before = keys()
    upload = str(uuid.uuid4())
    database.query(f"""USE {DB}; CREATE TRIGGER fixture_evidence_failure BEFORE INSERT ON evidence
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture: fail after PUT';""")
    try:
        check(put_file(client, activity_id, upload, "parkir.png", image, "image/png", 500)["code"],
              "INTERNAL_ERROR")
    finally:
        database.query(f"USE {DB}; DROP TRIGGER fixture_evidence_failure;")
    orphan, = keys() - before
    check(s3_request(storage, orphan, "GET"), (200, image))
    check(client.request("GET", f"/activities/{activity_id}/evidence", 200)["id"], previous_upload)

    put_file(client, activity_id, upload, "parkir.png", image, "image/png", 202)
    until(client, activity_id, "AVAILABLE")
    retained, = database.rows(f"USE {DB}; SELECT object_key FROM evidence WHERE id='{previous_upload}';")
    check(keys(), before | {orphan})

    # An unknown DELETE outcome keeps a sealed job eligible for another worker attempt.
    subprocess.run(["docker", "stop", "-t", "2", storage["name"]], check=True, capture_output=True, timeout=60)
    try:
        database.query(f"USE {DB}; UPDATE evidence_cleanup SET next_run_at=0 WHERE object_key='{orphan}';")
        wait_for(lambda: True if database.rows(
            f"USE {DB}; SELECT sealed,attempts FROM evidence_cleanup WHERE object_key='{orphan}';") == ["1\t1"] else None, 30)
    finally:
        subprocess.run(["docker", "start", storage["name"]], check=True, capture_output=True, timeout=60)

    storage_ready(storage["port"])
    database.query(f"USE {DB}; UPDATE evidence_cleanup SET next_run_at=0 WHERE object_key='{orphan}';")
    wait_for(lambda: True if orphan not in keys() else None, 30)
    check(s3_request(storage, orphan, "GET")[0], 404)
    check(s3_request(storage, retained, "GET"), (200, image))
    check(get_raw(client, f"/activities/{activity_id}/evidence/content")[2], image)
    check(client.request("GET", "/financial-state", 200), confirmed)
    print("Evidence cleanup: rolled-back PUT is removed after S3 recovers; confirmed and removed evidence survive", flush=True)


def put_file_quiet(client, activity_id, upload, image):
    try:
        result = put_file(client, activity_id, upload, "parkir.png", image, "image/png", (200, 202, 503))
    except TimeoutError:
        return None  # unknown response; the same upload id is safe to check by retry
    return result.get("code") != "TEMPORARY_FAILURE"


def set_file(page, selector, path):
    target = page.cdp("Runtime.evaluate", expression=f"document.querySelector({json.dumps(selector)})")["result"]
    page.cdp("DOM.setFileInputFiles", files=[str(path)], objectId=target["objectId"])


def evidence_ui_test(chrome, origin, api_port, mail):
    """Through the real UI: a file chosen in the entry form is uploaded after the save, the detail shows
    its status until the worker verifies it, then preview, client-side refusal, and removal."""
    import tempfile
    from pathlib import Path
    from phase4_offline import login
    from phase5_ui import link, result, save, user

    client, email = user(api_port, origin, mail, "ui-evidence")
    operation(client, "/onboarding/skip-opening-balance")
    folder = Path(tempfile.mkdtemp(prefix="duit-evidence-"))
    picture, text = folder / "struk belanja.png", folder / "catatan.txt"
    picture.write_bytes(png(8, 8))
    text.write_text("bukan bukti")
    try:
        with chrome.run() as page:
            login(page, origin, email)
            link(page, "Pengeluaran")
            page.js("document.querySelector('details').open = true")
            set_file(page, "#evidence", picture)
            page.see("document.querySelector('#evidence-hint')?.textContent.startsWith('struk belanja.png')")
            page.fill("#amount", "15000")
            page.fill("#title", "Belanja dengan struk")
            save(page)
            result(page, "Transaksi berhasil dicatat")
            page.see("document.querySelector('[data-entry-evidence]')?.textContent.includes('sedang diperiksa')")
            print("Evidence UI: file chosen in the form is uploaded after the transaction is confirmed", flush=True)

            link(page, "Transaksi")
            link(page, "Belanja dengan struk")
            page.see("document.querySelector('[data-evidence-status]')?.dataset.evidenceStatus === 'AVAILABLE'", 40)
            check(page.js("document.querySelector('[data-evidence] strong').textContent"), "struk belanja.png")
            page.click("Lihat")
            page.see("document.querySelector('.evidence-preview')?.naturalWidth === 8")
            page.see("document.querySelector('[data-related-audit] [data-action=EVIDENCE_VERIFIED]')?.textContent"
                     ".includes('Bukti lolos pemeriksaan')")
            set_file(page, "[data-evidence-input]", text)
            page.see("document.querySelector('[data-evidence-error]')?.textContent.includes('Jenis berkas tidak didukung')")
            check(page.js("document.querySelector('[data-evidence-status]').dataset.evidenceStatus"), "AVAILABLE")
            page.click("Hapus bukti")
            page.click("Ya, hapus bukti")
            page.see("document.querySelector('[data-evidence-notice]')?.textContent.includes('dilepas') && "
                     "document.querySelector('[data-evidence]').textContent.includes('Belum ada bukti')")
            page.see("!!document.querySelector('[data-related-audit] [data-action=EVIDENCE_REMOVED]')")
            check(page.js("!!document.querySelector('.evidence-preview')"), False)
            print("Evidence UI: detail shows quarantine then AVAILABLE, image preview from a blob, unsupported file "
                  "refused before upload, removal confirmed and audited", flush=True)
    finally:
        for file in (picture, text):
            file.unlink(missing_ok=True)
        folder.rmdir()
