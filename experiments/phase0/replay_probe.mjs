import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';

const MAX = (1n << 63n) - 1n;
const MIN = -(1n << 63n);

function checked(value) {
  if (value < MIN || value > MAX) throw new RangeError('signed BIGINT overflow');
  return value;
}

function replay(events) {
  const ordered = events.toSorted((a, b) => {
    if (a.instant !== b.instant) return a.instant < b.instant ? -1 : 1;
    return a.seq < b.seq ? -1 : a.seq > b.seq ? 1 : 0;
  });
  const deltas = new Map();
  const receivables = new Map();
  let balance = 0n;
  for (const event of ordered) {
    if (event.target !== undefined) {
      deltas.set(event.seq, checked(event.target - balance));
      balance = checked(event.target);
    } else {
      balance = checked(balance + event.cash);
    }
    if (event.borrower !== undefined) {
      const outstanding = checked((receivables.get(event.borrower) ?? 0n) + event.receivable);
      if (outstanding < 0n) throw new RangeError('negative receivable prefix');
      receivables.set(event.borrower, outstanding);
    }
  }
  return { balance, deltas, receivables };
}

const early = { instant: 1n, seq: 4n, cash: -7n };
const opening = { instant: 2n, seq: 1n, target: 0n };
const tied = { instant: 2n, seq: 2n, cash: 23n };
const adjustment = { instant: 3n, seq: 3n, target: 30n };
const after = { instant: 4n, seq: 5n, cash: -5n };
const history = [after, adjustment, tied, opening, early];
assert.equal(replay([early]).balance, -7n);
assert.equal(replay(history).balance, 25n);
assert.deepEqual([...replay(history).deltas], [[1n, 7n], [3n, 7n]]);
const edited = replay([after, adjustment, { ...tied, cash: 21n }, opening, { ...early, cash: -9n }]);
assert.equal(edited.balance, 25n);
assert.deepEqual([...edited.deltas], [[1n, 9n], [3n, 9n]]);

const loan = { instant: 2n, seq: 1n, cash: 0n, borrower: 'profile-1', receivable: 9n };
const payment = { ...loan, seq: 2n, receivable: -8n };
assert.equal(replay([payment, loan]).receivables.get('profile-1'), 1n);
assert.equal(replay([loan]).balance, 0n);
assert.throws(() => replay([{ ...payment, instant: 1n }, loan]), /negative receivable prefix/);
assert.throws(() => replay([loan, { ...payment, borrower: 'profile-2' }]), /negative receivable prefix/);
assert.equal(replay([{ ...early, cash: 9007199254740993n }]).balance, 9007199254740993n);
assert.throws(() => replay([{ ...early, cash: MIN }, opening]), /BIGINT overflow/);
assert.throws(() => replay([{ ...early, cash: MAX }, tied]), /BIGINT overflow/);

console.log('Replay assertions OK');
for (const size of [1_000, 10_000, 100_000]) {
  const events = Array.from({ length: size }, (_, i) => ({
    instant: BigInt((i * 37) % size), seq: BigInt(i + 1), cash: 1n,
  }));
  const started = performance.now();
  assert.equal(replay(events).balance, BigInt(size));
  console.log(`${size} in-memory events: ${(performance.now() - started).toFixed(1)} ms`);
}
