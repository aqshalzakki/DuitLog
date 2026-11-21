"""Phase 2 cases called by the disposable MySQL / HTTP fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
import subprocess
import uuid

from phase1_auth import Client, DB, PASSWORD, ROOT, check, mail_token, wait_for


def request_body(**fields):
    return {"attemptId": str(uuid.uuid4()), "clientActivityId": str(uuid.uuid4()), **fields}


def operation(client, path, fields=None, method="POST", status=200, code=None):
    result = client.request(method, path, status, data=request_body(**(fields or {})))
    if code:
        check(result["code"], code)
    else:
        check(result["status"], "CONFIRMED")
    return result


def signed_in(mail, port, origin, label):
    client = Client(port, origin)
    email = f"{label.lower()}@example.test"  # server stores emails lowercased
    client.request("POST", "/auth/register", 202, data={"name": label, "email": email, "password": PASSWORD})
    client.login(email)
    client.request("GET", "/financial-state", 403)
    token = mail_token(mail, email, "Verifikasi")
    client.request("POST", "/auth/verify-email", 204, data={"token": token})
    return client


def activity(kind, amount, effective_at, **fields):
    return {"kind": kind, "amount": str(amount), "effectiveAt": effective_at, **fields}


def use_db(database, sql):
    database.query(f"USE {DB}; {sql}")


def financial_test(database, env, mail, port, origin):
    alice = signed_in(mail, port, origin, "Finance-A")
    bob = signed_in(mail, port, origin, "Finance-B")
    aid = alice.request("GET", "/me", 200)["id"]
    bid = bob.request("GET", "/me", 200)["id"]
    early = "2020-01-01T00:00:00Z"
    input_a = activity("DEDUCT", 7, early)
    operation(alice, "/activities", input_a, status=409, code="OPENING_REQUIRED")
    check(alice.request("GET", "/financial-state", 200)["opening"], "pending")
    opening = operation(alice, "/onboarding/opening-balance", {"targetBalance": "0"})
    check(opening["balance"], "0")
    operation(alice, "/onboarding/skip-opening-balance", status=409, code="OPENING_ALREADY_DECIDED")
    operation(bob, "/onboarding/skip-opening-balance")
    check(bob.request("GET", "/activities", 200)["items"], [])
    check(operation(bob, "/activities", input_a)["balance"], "-7")

    backdate = operation(alice, "/activities", input_a)
    check(backdate["balance"], "0")
    open_path = "/activities/" + opening["resourceId"]
    check(alice.request("GET", open_path, 200)["snapshotDelta"], "7")
    tied = operation(alice, "/activities", activity("INCREASE", 23, opening["effectiveAt"]))
    check(tied["balance"], "23")
    check(tied["financialSequence"], 3)
    adjustment = operation(alice, "/balance-adjustments", {"targetBalance": "30"})
    adj_path = "/activities/" + adjustment["resourceId"]
    back_path = "/activities/" + backdate["resourceId"]
    tied_path = "/activities/" + tied["resourceId"]
    check(operation(alice, back_path, {**input_a, "amount": "9", "expectedVersion": 1}, "PATCH")["balance"], "30")
    check(operation(alice, tied_path, {**activity("INCREASE", 21, opening["effectiveAt"]), "expectedVersion": 1}, "PATCH")["financialSequence"], 3)
    check(alice.request("GET", open_path, 200)["snapshotDelta"], "9")
    check(alice.request("GET", adj_path, 200)["targetBalance"], "30")
    check(alice.request("GET", adj_path, 200)["snapshotDelta"], "9")
    stale = operation(alice, back_path, {**input_a, "expectedVersion": 1}, "PATCH", 409, "VERSION_CONFLICT")
    check(stale["conflictDetails"]["currentVersion"], 2)
    audit = alice.request("GET", "/audit", 200)["items"]
    assert any(item["details"]["snapshotChanges"] == [{
        "id": adjustment["resourceId"], "targetBalance": "30", "beforeDelta": "7", "afterDelta": "9",
    }] for item in audit)
    bob.request("GET", back_path, 404)

    category = operation(alice, "/categories", {"name": "Personal"})
    cat_id = category["resourceId"]
    cat_activity = operation(alice, "/activities", activity("INCREASE", 4, early, categoryId=cat_id))
    cat_path = "/activities/" + cat_activity["resourceId"]
    operation(alice, f"/categories/{cat_id}/archive", {"expectedVersion": 1})
    operation(alice, "/activities", activity("INCREASE", 3, early, categoryId=cat_id), status=409, code="CATEGORY_ARCHIVED")
    operation(alice, cat_path, {**activity("INCREASE", 5, early, categoryId=cat_id), "expectedVersion": 1}, "PATCH")
    operation(alice, cat_path, {"expectedVersion": 2, "reason": "fixture"}, "DELETE")
    check(alice.request("GET", "/activities?deleted=true", 200)["items"][0]["id"], cat_activity["resourceId"])
    operation(alice, cat_path + "/restore", {"expectedVersion": 3})
    check(alice.request("GET", cat_path, 200)["categoryId"], cat_id)
    check(alice.request("GET", "/categories", 200)[0]["archived"], True)

    borrower = operation(alice, "/borrowers", {"name": "Same name", "phone": "123"})
    second = operation(alice, "/borrowers", {"name": "Same name"})
    assert second["resourceId"] != borrower["resourceId"]
    borrower_id = borrower["resourceId"]
    borrower_path = "/borrowers/" + borrower_id
    bob.request("GET", borrower_path, 404)
    loan_input = activity("LOAN", 9, "2021-01-01T00:00:00Z", borrowerId=borrower_id, affectCashBalance=False)
    loan = operation(alice, "/activities", loan_input)
    check((loan["balance"], loan["receivables"]), ("30", "9"))
    failed = operation(alice, "/activities", activity("REPAYMENT", 2, early, borrowerId=borrower_id),
                       status=409, code="RECEIVABLE_NEGATIVE")
    check(alice.request("GET", "/operations/" + failed["attemptId"], 200)["status"], "REJECTED")
    check(alice.request("GET", "/financial-state", 200)["receivables"], "9")
    operation(alice, borrower_path + "/archive", {"expectedVersion": 1}, status=409, code="BORROWER_OUTSTANDING")
    repay = operation(alice, "/activities", activity("REPAYMENT", 9, "2022-01-01T00:00:00Z",
                      borrowerId=borrower_id, affectCashBalance=False, dependsOn=[loan["resourceId"]]))
    operation(alice, "/activities/" + loan["resourceId"], {"expectedVersion": 1}, "DELETE", 409, "DEPENDENCY_BLOCKED")
    operation(alice, borrower_path + "/archive", {"expectedVersion": 1})
    operation(alice, "/activities", loan_input, status=409, code="BORROWER_ARCHIVED")
    repay_path = "/activities/" + repay["resourceId"]
    operation(alice, repay_path, {"expectedVersion": 1}, "DELETE")
    account = alice.request("GET", borrower_path, 200)
    check((account["outstanding"], account["archived"], account["version"]), ("9", False, 3))
    operation(alice, repay_path + "/restore", {"expectedVersion": 2})
    audit = alice.request("GET", "/audit", 200)["items"]
    assert any(any(item["automaticallyReactivated"] for item in log["details"]["borrowerChanges"]) for log in audit)
    check(alice.request("GET", borrower_path, 200)["status"], "PAID")

    later = datetime.now(UTC).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    operation(alice, "/activities", activity("INCREASE", 4, future), status=422, code="INVALID_FUTURE_EFFECTIVE_TIME")
    operation(alice, "/activities", activity("INCREASE", 0, early), status=422, code="INVALID_AMOUNT")
    operation(alice, "/activities", activity("INCREASE", 9_223_372_036_854_775_807, later), status=422, code="AMOUNT_OVERFLOW")
    http_attempt = request_body(**activity("DEDUCT", 2, later))
    accepted = alice.request("POST", "/activities", 200, data=http_attempt)
    check(alice.request("GET", "/operations/" + http_attempt["attemptId"], 200), accepted)
    check(alice.request("POST", "/activities", 200, data=http_attempt), accepted)
    different = alice.request("POST", "/activities", 409, data={**http_attempt, "amount": "3"})
    check(different["code"], "IDEMPOTENCY_PAYLOAD_MISMATCH")
    second_try = alice.request("POST", "/activities", 409, data={**http_attempt, "attemptId": str(uuid.uuid4())})
    check(second_try["code"], "ALREADY_CONFIRMED_ACTIVITY")
    bob.request("GET", "/operations/" + http_attempt["attemptId"], 404)
    before = alice.request("GET", "/financial-state", 200)
    def deduct(amount):
        client = Client(port, origin)
        client.cookies = dict(alice.cookies)
        return operation(client, "/activities", activity("DEDUCT", amount, later))["financialSequence"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        seq = sorted(pool.map(deduct, [3, 4]))
    check(seq[1], seq[0] + 1)
    check(alice.request("GET", "/financial-state", 200)["balance"], str(int(before["balance"]) - 7))
    after = alice.request("GET", "/financial-state", 200)

    use_db(database, "CREATE TRIGGER fixture_audit_reject BEFORE INSERT ON financial_audit FOR EACH ROW "
                    "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture atomicity check';")
    blocked = request_body(**activity("DEDUCT", 4, later))
    try:
        alice.request("POST", "/activities", 500, data=blocked)
        alice.request("GET", "/operations/" + blocked["attemptId"], 404)
        check(alice.request("GET", "/financial-state", 200), after)
    finally:
        use_db(database, "DROP TRIGGER fixture_audit_reject;")
    accepted = alice.request("POST", "/activities", 200, data=blocked)
    check(accepted["financialSequence"], seq[1] + 1)

    use_db(database, f"UPDATE financial_accounts SET balance=balance+1 WHERE owner_id='{aid}';")
    operation(alice, "/activities", input_a, status=423, code="FINANCIAL_INTEGRITY_FROZEN")
    check(alice.request("GET", "/integrity-status", 200), {"frozen": True, "recoveryActive": False})
    check(operation(bob, "/activities", input_a)["balance"], "-14")
    operator = ROOT / "target/debug/finance_operator.exe"
    operator_env = dict(env, DUIT_FINANCE_OPERATOR_DATABASE_URL=env["DATABASE_URL"],
                        DUIT_FINANCE_OPERATOR_ACTOR="fixture", DUIT_FINANCE_OPERATOR_REASON="verification fixture")
    def run_operator(action, owner=aid):
        return subprocess.run([operator, action, owner], env=operator_env, check=True,
                              capture_output=True, text=True, timeout=15).stdout.strip()
    check(run_operator("unfreeze"), "frozen=true")
    use_db(database, f"UPDATE financial_accounts SET balance=balance-1 WHERE owner_id='{aid}';")
    check(run_operator("unfreeze"), "frozen=false")
    check(alice.request("GET", "/integrity-status", 200)["frozen"], False)
    from phase2_stress import stress_test
    stress_test(database, mail, port, origin, bob, run_operator)
    from phase3_sync import sync_test
    sync_test(database, alice, bob, run_operator)
    use_db(database, "UPDATE financial_recovery SET active=TRUE WHERE id=1;")
    operation(alice, "/activities", input_a, status=503, code="FINANCIAL_RECOVERY_ACTIVE")
    operation(bob, "/activities", input_a, status=503, code="FINANCIAL_RECOVERY_ACTIVE")
    check(alice.request("GET", "/operations/" + blocked["attemptId"], 200), accepted)
    check(alice.request("GET", "/integrity-status", 200), {"frozen": False, "recoveryActive": True})
    check(database.rows(f"USE {DB}; SELECT COUNT(*) FROM financial_accounts WHERE owner_id IN ('{aid}','{bid}');"), ["2"])
    print("Financial Core MySQL: snapshots, history, receivable prefixes, categories, owner scope, "
          "parallel writes, idempotency, audit rollback and recovery/integrity guards OK", flush=True)
    use_db(database, "UPDATE financial_recovery SET active=FALSE WHERE id=1;")  # later suites share this database
