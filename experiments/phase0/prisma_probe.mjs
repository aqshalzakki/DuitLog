import assert from 'node:assert/strict';
import { PrismaClient } from '@prisma/client';

const url = new URL(process.env.DUIT_PROBE_URL);
assert.equal(url.hostname, '127.0.0.1');
assert.equal(url.pathname, '/duit_probe');
const prisma = new PrismaClient();
const id = 4;
const transaction = (fn) => prisma.$transaction(fn, { timeout: 10_000 });
async function deduct(amount) {
  await transaction(async (tx) => {
    const [row] = await tx.$queryRaw`SELECT balance,next_seq FROM account WHERE id=${id} FOR UPDATE`;
    await tx.$executeRaw`UPDATE account SET balance=${row.balance - amount},
      next_seq=${row.next_seq + 1n} WHERE id=${id}`;
    await tx.$executeRaw`INSERT INTO audit VALUES (${id},${row.next_seq})`;
  });
}

try {
  await Promise.all([deduct(2n), deduct(3n)]);
  assert.deepEqual(await prisma.account.findUnique({ where: { id } }),
    { id, balance: 9007199254740988n, next_seq: 3n });
  await assert.rejects(transaction(async (tx) => {
    await tx.$queryRaw`SELECT id FROM account WHERE id=${id} FOR UPDATE`;
    await tx.$executeRaw`UPDATE account SET balance=0 WHERE id=${id}`;
    await tx.$executeRaw`INSERT INTO audit VALUES (${id},1)`;
  }), (error) => error.code === 'P2010' && String(error.meta?.code) === '1062');
  assert.equal((await prisma.account.findUnique({ where: { id } })).balance, 9007199254740988n);
  assert.deepEqual(await prisma.$queryRaw`SELECT seq FROM audit WHERE owner=${id} ORDER BY seq`,
    [{ seq: 1n }, { seq: 2n }]);
  console.log('Prisma 6.19.3 concurrent lock, BIGINT and rollback OK');
} finally {
  await prisma.$disconnect();
}
