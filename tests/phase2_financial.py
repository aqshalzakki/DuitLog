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


def reconcile(client):
    """Reports agree with the Financial Core: a running year closes at the materialized balance, and
    each borrower closes at its stored outstanding."""
    state = client.request("GET", "/financial-state", 200)
    year = client.request("GET", "/reports/balance-movement?period=year", 200)
    check((year["range"]["running"], year["closing"]), (True, state["balance"]))
    owed = client.request("GET", "/reports/receivables?period=year", 200)
    check(owed["closing"], state["receivables"])
    for row in owed["borrowers"]:
        check(row["closing"], client.request("GET", "/borrowers/" + row["borrowerId"], 200)["outstanding"])


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
    # Borrower history filter: only that borrower's activity, owner-scoped, deleted kept apart.
    mine = alice.request("GET", "/activities?borrowerId=" + borrower_id, 200)
    check([a["id"] for a in mine["items"]], [repay["resourceId"], loan["resourceId"]])
    check(alice.request("GET", "/activities?borrowerId=" + second["resourceId"], 200)["items"], [])
    check(bob.request("GET", "/activities?borrowerId=" + borrower_id, 200)["items"], [])
    check(alice.request("GET", f"/activities?borrowerId={borrower_id}&before={mine['items'][0]['sequence']}", 200)["items"][0]["id"],
          loan["resourceId"])
    for bad in ("/activities?borrowerId=not-a-uuid", "/activities?deleted=maybe", "/audit?before=x"):
        check(alice.request("GET", bad, 422)["code"], "VALIDATION_ERROR")  # API error shape, not plain text

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

    reconcile(alice)
    use_db(database, f"UPDATE financial_accounts SET balance=balance+1 WHERE owner_id='{aid}';")
    operation(alice, "/activities", input_a, status=423, code="FINANCIAL_INTEGRITY_FROZEN")
    # An unverified ledger gives no official report.
    check(alice.request("GET", "/reports/balance-movement?period=month", 423)["code"], "FINANCIAL_INTEGRITY_FROZEN")
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
    report_test(alice, bob)
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


def report_test(alice, bob):
    """Reports on fixed historical days: WIB day boundary, the three families, comparison and isolation."""
    food = operation(bob, "/categories", {"name": "Makan"})["resourceId"]
    tono = operation(bob, "/borrowers", {"name": "Tono"})["resourceId"]
    for kind, amount, at, extra in [
        ("INCREASE", 1000, "2021-03-10T16:59:59.999999Z", {}),  # 23:59:59 WIB, still 10 March
        ("INCREASE", 500, "2021-03-10T17:00:00Z", {}),  # 00:00 WIB, 11 March
        ("DEDUCT", 300, "2021-03-11T05:00:00Z", {"categoryId": food}),
        ("LOAN", 200, "2021-03-11T06:00:00Z", {"borrowerId": tono}),
        ("REPAYMENT", 50, "2021-03-11T07:00:00Z", {"borrowerId": tono}),
        ("LOAN", 70, "2021-03-11T08:00:00Z", {"borrowerId": tono, "affectCashBalance": False}),
    ]:
        operation(bob, "/activities", activity(kind, amount, at, **extra))
    gone = operation(bob, "/activities", activity("INCREASE", 999, "2021-03-11T09:00:00Z"))
    operation(bob, "/activities/" + gone["resourceId"], {"expectedVersion": 1}, "DELETE")

    day = bob.request("GET", "/reports/income-expense?period=day&date=2021-03-11", 200)
    check(day["range"], {"from": "2021-03-11", "to": "2021-03-11", "start": "2021-03-10T17:00:00Z",
                         "end": "2021-03-11T17:00:00Z", "period": "day", "running": False})
    check((day["timezone"], day["comparison"]["from"], day["comparison"]["to"]), ("Asia/Jakarta", "2021-03-10", "2021-03-10"))
    # Loans, repayments, the off-ledger loan and the deleted income are not income or expense.
    check(day["current"], {"income": "500", "expense": "300", "net": "200"})
    check(day["previous"], {"income": "1000", "expense": "0", "net": "1000"})
    check(day["change"], {"income": {"state": "PERCENT", "percent": "-50.0"}, "expense": {"state": "NEW"},
                          "net": {"state": "PERCENT", "percent": "-80.0"}})
    check([(c["categoryId"], c["name"], c["income"], c["expense"]) for c in day["categories"]],
          [(None, None, "500", "0"), (food, "Makan", "0", "300")])
    month = bob.request("GET", "/reports/income-expense?period=month&date=2021-03-01", 200)
    check((len(month["series"]), month["series"][9], month["series"][10]),
          (31, {"label": "2021-03-10", "income": "1000", "expense": "0"}, {"label": "2021-03-11", "income": "500", "expense": "300"}))
    check(month["comparison"]["from"], "2021-02-01")

    move = bob.request("GET", "/reports/balance-movement?period=day&date=2021-03-11", 200)
    before = int(move["opening"])
    check({k: move[k] for k in ("income", "expense", "loansOut", "repaymentsIn", "snapshotDelta")},
          {"income": "500", "expense": "300", "loansOut": "200", "repaymentsIn": "50", "snapshotDelta": "0"})
    check((move["closing"], move["series"]), (str(before + 50), [{"label": "2021-03-11", "closing": str(before + 50)}]))
    check(bob.request("GET", "/reports/balance-movement?period=day&date=2021-03-10", 200)["closing"], move["opening"])

    owed = bob.request("GET", "/reports/receivables?period=day&date=2021-03-11", 200)
    check(owed["borrowers"], [{"borrowerId": tono, "name": "Tono", "archived": False, "opening": "0",
                               "loans": "270", "repayments": "50", "closing": "220"}])
    check(alice.request("GET", "/reports/income-expense?period=day&date=2021-03-11", 200)["current"],
          {"income": "0", "expense": "0", "net": "0"})  # nothing of bob's leaks into alice's report
    check(tono in [b["borrowerId"] for b in alice.request("GET", "/reports/receivables?period=day&date=2021-03-11", 200)["borrowers"]], False)
    for bad in ("income-expense?period=custom&from=2021-03-01", "income-expense?period=week&date=2099-01-01",
                "income-expense?period=hour", "income-expense?period=custom&from=2021-03-02&to=2021-03-01",
                "receivables?period=day&date=2021-3-1"):
        check(bob.request("GET", "/reports/" + bad, 422)["code"], "VALIDATION_ERROR")
    bob.request("GET", "/reports/unknown?period=day", 404)
    reconcile(alice)
    reconcile(bob)
    print("Reports: WIB day boundary, income/expense excludes receivables and deleted, balance movement and "
          "receivables reconcile with the core, comparison states, owner isolation, freeze refuses", flush=True)
