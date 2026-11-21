"""Phase 2 evidence beyond the scripted cases: randomized history vs an independent model,
many concurrent writers, and a held account lock (MySQL error 1205) against real MySQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Thread
import os
import random
import time

from phase1_auth import DB, Client, check, wait_for
from phase2_financial import activity, reconcile, request_body, signed_in

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SEED = int(os.environ.get("DUIT_FIN_SEED", "20261121"))
STEPS = 60


def micros(text):
    return (datetime.fromisoformat(text) - EPOCH) // timedelta(microseconds=1)


def now_iso():
    return datetime.now(UTC).isoformat()


def model(entries):
    """Expected (balance, receivables per borrower, snapshot deltas) or None if any prefix goes negative."""
    balance, owed, deltas = 0, {}, {}
    for e in sorted((e for e in entries.values() if not e["deleted"]), key=lambda e: (e["eff"], e["seq"])):
        if e["target"] is not None:
            deltas[e["id"]] = e["target"] - balance
            balance = e["target"]
            continue
        sign = 1 if e["kind"] in ("INCREASE", "REPAYMENT") else -1
        if e["borrower"]:
            owed[e["borrower"]] = owed.get(e["borrower"], 0) - sign * e["amount"]
            if owed[e["borrower"]] < 0:
                return None
        if e["cash"]:
            balance += sign * e["amount"]
    return balance, owed, deltas


def payload(e):
    extra = {"borrowerId": e["borrower"], "affectCashBalance": e["cash"]} if e["borrower"] else {}
    return activity(e["kind"], e["amount"], e["eff_text"], **extra)


def clone(client):
    copy = Client(client.port, client.origin)
    copy.cookies = dict(client.cookies)
    return copy


def randomized_history(carol, run_operator, cid):
    rng = random.Random(SEED)
    entries, stats = {}, {}
    state = lambda: carol.request("GET", "/financial-state", 200)

    def expect_state(expected):
        current = state()
        check((current["balance"], current["receivables"]), (str(expected[0]), str(sum(expected[1].values()))))

    def mutate(method, path, fields, candidate):
        expected = model(candidate)
        status, body = carol.request(method, path, (200, 409), data=request_body(**fields), full=True)
        if expected is None:
            check((status, body["code"]), (409, "RECEIVABLE_NEGATIVE"))
            stats["rejected"] = stats.get("rejected", 0) + 1
            expect_state(model(entries))
            return None
        check(status, 200)
        check((body["balance"], body["receivables"]), (str(expected[0]), str(sum(expected[1].values()))))
        entries.clear()
        entries.update(candidate)
        return body

    def backdated():
        snapshots = [e for e in entries.values() if e["target"] is not None]
        if snapshots and rng.random() < 0.2:
            return rng.choice(snapshots)["eff_text"]  # same instant as a snapshot: sequence breaks the tie
        moment = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=rng.randrange(5 * 365 * 86400))
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def created(body, **fields):
        e = {"id": body["resourceId"], "seq": body["financialSequence"], "eff_text": body["effectiveAt"],
             "eff": micros(body["effectiveAt"]), "version": body.get("version"), "deleted": False,
             "target": None, "borrower": None, "cash": True, "amount": None, **fields}
        entries[e["id"]] = e

    def create(kind, eff_text, borrower=None, cash=True):
        e = {"id": "?", "seq": 1 << 62, "eff_text": eff_text, "eff": micros(eff_text), "deleted": False,
             "target": None, "kind": kind, "amount": rng.randint(1, 5000), "borrower": borrower, "cash": cash}
        body = mutate("POST", "/activities", payload(e), {**entries, "?": e})
        if body:
            entries.pop("?")
            created(body, kind=kind, amount=e["amount"], borrower=borrower, cash=cash)

    opening = carol.request("POST", "/onboarding/opening-balance", 200,
                            data=request_body(targetBalance=str(rng.randint(-20000, 20000))))
    created(opening, kind="OPENING", target=int(opening["balance"]))
    borrowers = [carol.request("POST", "/borrowers", 200, data=request_body(name="Random"))["resourceId"]
                 for _ in range(2)]
    for step in range(STEPS):
        movable = [e for e in entries.values() if e["target"] is None and not e["deleted"]]
        deleted = [e for e in entries.values() if e["deleted"]]
        action = rng.choices(["back", "now", "adjust", "loan", "repay", "edit", "delete", "restore"],
                             [30, 10, 8, 12, 12, 12, 8, 8])[0]
        if action in ("edit", "delete") and not movable or action == "restore" and not deleted:
            action = "back"
        stats[action] = stats.get(action, 0) + 1
        try:
            if action == "back":
                create(rng.choice(["INCREASE", "DEDUCT"]), backdated())
            elif action == "now":
                create(rng.choice(["INCREASE", "DEDUCT"]), now_iso())
            elif action in ("loan", "repay"):
                create("LOAN" if action == "loan" else "REPAYMENT", backdated(),
                       rng.choice(borrowers), rng.random() < 0.5)
            elif action == "adjust":
                target = rng.randint(-50000, 50000)
                body = carol.request("POST", "/balance-adjustments", 200,
                                     data=request_body(targetBalance=str(target)))
                check(body["balance"], str(target))
                created(body, kind="ADJUSTMENT", target=target)
                expect_state(model(entries))
            else:
                e = rng.choice(movable if action != "restore" else deleted)
                changed = dict(e)
                path = "/activities/" + e["id"]
                if action == "edit":
                    changed.update(amount=rng.randint(1, 5000), eff_text=backdated())
                    changed["eff"] = micros(changed["eff_text"])
                    if e["borrower"]:
                        changed["cash"] = rng.random() < 0.5
                    fields, method = {**payload(changed), "expectedVersion": e["version"]}, "PATCH"
                else:
                    changed["deleted"] = action == "delete"
                    fields, method = {"expectedVersion": e["version"]}, "DELETE" if action == "delete" else "POST"
                    path += "" if action == "delete" else "/restore"
                body = mutate(method, path, fields, {**entries, e["id"]: changed})
                if body:
                    entries[e["id"]]["version"] = body["version"]
        except Exception:
            print(f"Randomized history failed: DUIT_FIN_SEED={SEED} step={step} action={action}", flush=True)
            raise

    expected = model(entries)
    expect_state(expected)
    for borrower in borrowers:
        check(carol.request("GET", "/borrowers/" + borrower, 200)["outstanding"], str(expected[1].get(borrower, 0)))
    for snapshot_id, delta in expected[2].items():
        stored = carol.request("GET", "/activities/" + snapshot_id, 200)
        check((stored["targetBalance"], stored["snapshotDelta"]),
              (str(entries[snapshot_id]["target"]), str(delta)))
    check(run_operator("reconcile", cid), "frozen=false")
    return stats


def concurrent_writers(carol, run_operator, cid):
    temporary = [0]

    def retrying(body, path="/activities"):
        client = clone(carol)
        for _ in range(8):
            status, value = client.request("POST", path, (200, 409, 503), data=body, full=True)
            if status != 503:
                return status, value
            check(value["code"], "TEMPORARY_FAILURE")  # retry the same attemptId, never a new one
            temporary[0] += 1
            time.sleep(0.2)
        raise AssertionError("Write stayed temporary after 8 tries")

    balance = lambda: int(carol.request("GET", "/financial-state", 200)["balance"])
    rng = random.Random(SEED + 1)

    start = balance()
    amounts = [rng.randint(1, 50) for _ in range(40)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda a: retrying(request_body(**activity("DEDUCT", a, now_iso()))), amounts))
    check({status for status, _ in results}, {200})
    seqs = sorted(body["financialSequence"] for _, body in results)
    check(seqs, list(range(seqs[0], seqs[0] + 40)))
    check(balance(), start - sum(amounts))

    start = balance()
    same = request_body(**activity("INCREASE", 77, now_iso()))
    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(lambda _: retrying(same), range(6)))
    check({status for status, _ in replies}, {200})
    check(all(body == replies[0][1] for _, body in replies), True)
    check(balance(), start + 77)

    borrower = carol.request("POST", "/borrowers", 200, data=request_body(name="Race"))["resourceId"]
    carol.request("POST", "/activities", 200, data=request_body(**activity("LOAN", 10, now_iso(), borrowerId=borrower)))
    with ThreadPoolExecutor(max_workers=6) as pool:
        repaid = list(pool.map(lambda _: retrying(request_body(**activity(
            "REPAYMENT", 3, now_iso(), borrowerId=borrower))), range(6)))
    check(sorted(status for status, _ in repaid), [200] * 3 + [409] * 3)
    check({body["code"] for status, body in repaid if status == 409}, {"RECEIVABLE_NEGATIVE"})
    check(carol.request("GET", "/borrowers/" + borrower, 200)["outstanding"], "1")
    check(run_operator("reconcile", cid), "frozen=false")
    return temporary[0]


def held_lock(database, carol, bob, cid):
    hold = f"USE {DB}; START TRANSACTION; SELECT owner_id FROM financial_accounts WHERE owner_id='{cid}' FOR UPDATE; SELECT SLEEP(8); ROLLBACK;"
    holder = Thread(target=database.query, args=(hold,))
    before = carol.request("GET", "/financial-state", 200)
    blocked = request_body(**activity("DEDUCT", 5, now_iso()))
    holder.start()
    try:
        wait_for(lambda: True if database.rows(
            "SELECT COUNT(*) FROM information_schema.innodb_trx WHERE trx_query LIKE 'SELECT SLEEP(8)%';") == ["1"] else None)
        bob.request("POST", "/activities", 200, data=request_body(**activity("INCREASE", 1, now_iso())))
        started = time.monotonic()
        status, body = carol.request("POST", "/activities", (503,), data=blocked, full=True)
        assert time.monotonic() - started >= 3.5, "expected two 2s lock waits before giving up"
        check((body["code"], body.get("retryable")), ("TEMPORARY_FAILURE", True))
        carol.request("GET", "/operations/" + blocked["attemptId"], 404)
        check(carol.request("GET", "/financial-state", 200), before)
    finally:
        holder.join()
    accepted = carol.request("POST", "/activities", 200, data=blocked)
    check(accepted["balance"], str(int(before["balance"]) - 5))
    check(carol.request("GET", "/operations/" + blocked["attemptId"], 200), accepted)
    check(carol.request("POST", "/activities", 200, data=blocked), accepted)


def stress_test(database, mail, port, origin, bob, run_operator):
    carol = signed_in(mail, port, origin, "Finance-C")
    cid = carol.request("GET", "/me", 200)["id"]
    stats = randomized_history(carol, run_operator, cid)
    print(f"Randomized history vs model OK (seed {SEED}, {STEPS} steps: {stats})", flush=True)
    retries = concurrent_writers(carol, run_operator, cid)
    print(f"Concurrent writers OK: 40 parallel deducts, 6x same attempt, 6 racing repayments "
          f"({retries} retryable 503s retried with the same attemptId)", flush=True)
    held_lock(database, carol, bob, cid)
    reconcile(carol)  # after randomized history and concurrent writers
    print("Held account lock: 503 TEMPORARY_FAILURE, no partial write, other user unaffected, same attempt applies once", flush=True)
