"""Phase 3 server sync: Partial Sync (AC-15), client references, lost responses, concurrent
tabs and holds, against real MySQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Thread
import http.client
import json
import time
import uuid

from phase1_auth import DB, check, wait_for
from phase2_financial import activity, use_db
from phase2_stress import clone, now_iso


def ids():
    return {"attemptId": str(uuid.uuid4()), "clientActivityId": str(uuid.uuid4())}


def act(kind, amount, eff=None, **fields):
    return {**ids(), "type": "ACTIVITY", **activity(kind, amount, eff or now_iso()), **fields}


def borrower(name):
    return {**ids(), "type": "BORROWER", "name": name}


def owner(client):
    return client.request("GET", "/me", 200)["id"]


def sync(client, items, status=200, as_owner=None):
    data = {"owner": as_owner or owner(client), "items": items}
    return client.request("POST", "/sync/items", status, data=data)


def totals(client):
    state = client.request("GET", "/financial-state", 200)
    return int(state["balance"]), int(state["receivables"])


def partial_sync(alice, run_operator):
    b0, r0 = totals(alice)
    b = borrower("Offline friend")
    loan = act("LOAN", 10, borrowerClientId=b["clientActivityId"])
    repay = act("REPAYMENT", 4, borrowerClientId=b["clientActivityId"], dependsOn=[loan["clientActivityId"]])
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    conflict = act("DEDUCT", 6, future)
    child = act("INCREASE", 3, dependsOn=[conflict["clientActivityId"]])
    invalid = act("ADJUSTMENT", 1)
    orphan = act("INCREASE", 1, dependsOn=[invalid["clientActivityId"]])
    missing = act("INCREASE", 1, dependsOn=[str(uuid.uuid4())])
    x, y = act("INCREASE", 5), act("INCREASE", 2)
    # Children listed before parents: the server orders by dependency.
    batch = [repay, loan, x, conflict, child, b, invalid, orphan, missing, y]
    results = sync(alice, batch)["results"]
    check([r["clientActivityId"] for r in results], [i["clientActivityId"] for i in batch])
    got = {r["clientActivityId"]: r for r in results}
    status = lambda item: (got[item["clientActivityId"]]["status"], got[item["clientActivityId"]].get("code"))
    for item in (b, loan, repay, x, y):
        check(status(item)[0], "CONFIRMED")
    check(status(conflict), ("REJECTED", "INVALID_FUTURE_EFFECTIVE_TIME"))
    check(status(child), ("BLOCKED", "DEPENDENCY_BLOCKED"))
    check(got[child["clientActivityId"]]["blockedBy"], [conflict["clientActivityId"]])
    check(status(invalid), ("INVALID", "VALIDATION_ERROR"))
    check(status(orphan), ("BLOCKED", "DEPENDENCY_BLOCKED"))
    check(status(missing), ("BLOCKED", "DEPENDENCY_BLOCKED"))
    # x is ready first; loan waits for the borrower, repayment for the loan; y last in request order.
    seq = [got[i["clientActivityId"]]["financialSequence"] for i in (x, loan, repay, y)]
    assert seq == sorted(seq), f"unexpected processing order {seq}"
    check(totals(alice), (b0 - 10 + 4 + 5 + 2, r0 + 6))
    for item in (conflict,):
        check(alice.request("GET", "/operations/" + item["attemptId"], 200), {
            k: v for k, v in got[item["clientActivityId"]].items() if k != "clientActivityId"})
    for item in (child, invalid, orphan, missing):
        alice.request("GET", "/operations/" + item["attemptId"], 404)
    stored = alice.request("GET", "/activities/" + got[repay["clientActivityId"]]["resourceId"], 200)
    check(stored["dependsOn"], [got[loan["clientActivityId"]]["resourceId"]])
    check(stored["borrowerId"], got[b["clientActivityId"]]["resourceId"])
    check(run_operator("reconcile"), "frozen=false")

    # Resending the whole batch changes nothing: recorded items replay, blocked ones block again.
    again = sync(alice, batch)["results"]
    for first, second in zip(results, again):
        if first["status"] in ("CONFIRMED", "REJECTED"):
            check(second, first)
    check(totals(alice), (b0 + 1, r0 + 6))

    # User corrects the conflict: new attempt, same logical activity; the child keeps its attempt.
    # The fixed parent must still precede its child chronologically, or the child is rejected.
    fixed = {**conflict, "attemptId": str(uuid.uuid4()), "effectiveAt": "2024-06-01T00:00:00Z"}
    after = {r["clientActivityId"]: r for r in sync(alice, [child, fixed])["results"]}
    check([(after[i["clientActivityId"]]["status"], after[i["clientActivityId"]].get("code")) for i in (fixed, child)],
          [("CONFIRMED", None), ("CONFIRMED", None)])
    # Alice has a later balance adjustment: the 2024 deduct only shifts that snapshot's delta.
    check(totals(alice), (b0 + 1 + 3, r0 + 6))
    return b


def lost_response(database, alice, aid, slow):
    start = totals(alice)
    batch = [act("DEDUCT", 2), act("DEDUCT", 3), act("INCREASE", 11)]
    holder = None
    if slow:  # keep the batch busy inside the server (under the 2s lock wait) while the client leaves
        holder = Thread(target=database.query, args=(
            f"USE {DB}; START TRANSACTION; SELECT owner_id FROM financial_accounts WHERE owner_id='{aid}' "
            "FOR UPDATE; SELECT SLEEP(1.5); ROLLBACK;",))
        holder.start()
        wait_for(lambda: True if database.rows("SELECT COUNT(*) FROM information_schema.innodb_trx "
                                               "WHERE trx_query LIKE 'SELECT SLEEP(1.5)%';") == ["1"] else None)
    conn = http.client.HTTPConnection("127.0.0.1", alice.port, timeout=10)
    conn.request("POST", "/api/v1/sync/items", json.dumps({"owner": aid, "items": batch}), {
        "Cookie": "; ".join(f"{k}={v}" for k, v in alice.cookies.items()), "Origin": alice.origin,
        "X-Duit-CSRF": "1", "Content-Type": "application/json"})
    if slow:
        time.sleep(0.5)
    conn.close()  # the client never sees a response: outcome unknown
    if holder:
        holder.join()
    time.sleep(1.5)
    seen = {}
    for item in batch:
        status, body = alice.request("GET", "/operations/" + item["attemptId"], (200, 404), full=True)
        seen[item["attemptId"]] = body if status == 200 else None
    results = sync(alice, batch)["results"]
    check([r["status"] for r in results], ["CONFIRMED"] * 3)
    for item, result in zip(batch, results):
        if seen[item["attemptId"]]:
            check({k: v for k, v in result.items() if k != "clientActivityId"}, seen[item["attemptId"]])
    check(totals(alice), (start[0] + 6, start[1]))
    return sum(1 for value in seen.values() if value)


def concurrent_tabs(alice):
    start = totals(alice)
    batch = [act("DEDUCT", 1), act("DEDUCT", 2), act("INCREASE", 20)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: sync(clone(alice), batch)["results"], range(4)))
    check(all(reply == replies[0] for reply in replies), True)
    check({r["status"] for r in replies[0]}, {"CONFIRMED"})
    check(totals(alice), (start[0] + 17, start[1]))

    logical = act("INCREASE", 9)
    attempts = [{**logical, "attemptId": str(uuid.uuid4())} for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda item: sync(clone(alice), [item])["results"][0], attempts))
    check(sorted((o["status"], o.get("code")) for o in outcomes),
          [("CONFIRMED", None)] + [("REJECTED", "ALREADY_CONFIRMED_ACTIVITY")] * 3)
    check(totals(alice), (start[0] + 26, start[1]))


def envelope_and_scope(alice, bob, alice_borrower):
    check(sync(alice, [], 422)["code"], "VALIDATION_ERROR")
    item = act("INCREASE", 1)
    sync(alice, [item, {**item, "attemptId": str(uuid.uuid4())}], 422)
    sync(alice, [act("INCREASE", 1) for _ in range(51)], 422)
    sync(alice, [{**act("INCREASE", 1), "attemptId": "not-a-uuid"}], 422)
    sync(alice, [{**act("INCREASE", 1), "title": "x" * 70000}], 413)
    alice.request("GET", "/operations/" + item["attemptId"], 404)

    bob_start = totals(bob)
    by_client = act("LOAN", 5, borrowerClientId=alice_borrower["clientActivityId"])
    alice_id = alice.request("GET", "/operations/" + alice_borrower["attemptId"], 200)["resourceId"]
    by_server = act("LOAN", 5, borrowerId=alice_id)
    result = sync(bob, [by_client, by_server])["results"]
    check((result[0]["status"], result[0]["code"]), ("BLOCKED", "DEPENDENCY_BLOCKED"))
    check((result[1]["status"], result[1]["code"]), ("REJECTED", "NOT_FOUND"))
    check(totals(bob), bob_start)

    # The cookie belongs to the browser: a vault of Alice syncing while Bob is signed in commits nothing.
    stray = act("INCREASE", 7)
    check(sync(bob, [stray], 409, as_owner=owner(alice))["code"], "SESSION_OWNER_MISMATCH")
    alice.request("POST", "/sync/items", 422, data={"items": [act("INCREASE", 1)]})
    check(totals(bob), bob_start)
    bob.request("GET", "/operations/" + stray["attemptId"], 404)
    alice.request("GET", "/operations/" + stray["attemptId"], 404)


def holds(database, alice):
    item = act("INCREASE", 1)
    use_db(database, "UPDATE financial_recovery SET active=TRUE WHERE id=1;")
    try:
        check(sync(alice, [item], 503)["code"], "FINANCIAL_RECOVERY_ACTIVE")
    finally:
        use_db(database, "UPDATE financial_recovery SET active=FALSE WHERE id=1;")
    alice.request("GET", "/operations/" + item["attemptId"], 404)


def sync_test(database, alice, bob, run_operator):
    aid = alice.request("GET", "/me", 200)["id"]
    alice_borrower = partial_sync(alice, run_operator)
    print("Partial Sync (AC-15): dependency order, client borrower refs, conflict, blocked children, "
          "invalid item, missing ref, resend and correction OK", flush=True)
    early = lost_response(database, alice, aid, slow=False)
    landed = lost_response(database, alice, aid, slow=True)
    check(landed, 3)  # the spawned batch finishes after the client is gone
    print(f"Lost response: disconnect before processing ({early}/3 landed) and during processing (3/3 landed); "
          "lookup matched, resend confirmed each exactly once", flush=True)
    concurrent_tabs(alice)
    print("Concurrent tabs: identical batch x4 and same activity x4 attempts produce one effect each", flush=True)
    envelope_and_scope(alice, bob, alice_borrower)
    holds(database, alice)
    check(run_operator("reconcile"), "frozen=false")
    print("Sync envelope limits, owner scope and recovery hold OK", flush=True)
