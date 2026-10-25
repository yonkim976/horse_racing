const assert = require("node:assert/strict");
const test = require("node:test");
const { pickRace, createFollower } = require("../src/horse_racing/web/static/js/race-follow.js");
const start = 1000000;
const races = [
  { id: 1, start, status: "scheduled" },
  { id: 2, start: start + 1800000, status: "scheduled" },
  { id: 3, start: start + 3600000, status: "scheduled" },
];

test("advance at exactly one minute even without any result", () => {
  assert.equal(pickRace(races, start + 59999).id, 1);
  assert.equal(pickRace(races, start + 60000).id, 2);
  assert.equal(pickRace(races.map(r => ({ ...r, status: "completed" })), start + 60000).id, 2);
  assert.equal(pickRace(races, start + 9999999).id, 3);
  assert.equal(pickRace([{ id: 1, start: null }], start), null);
});

test("skip cancellation and use officially delayed start time", () => {
  assert.equal(pickRace([races[0], { ...races[1], status: "cancelled" }, races[2]], start + 60000).id, 3);
  assert.equal(pickRace([{ ...races[0], start: start + 300000 }, races[1]], start + 60000).id, 1);
  assert.equal(pickRace([races[2], races[0], races[1]], start + 60000).id, 2);
});

test("open page advances by time; a manual selection stays pinned until resumed", async () => {
  let clock = start, calls = [];
  const follower = createFollower({ now: () => clock, races: () => races, initialId: 1,
    select: id => { calls.push(id); return true; } });
  await follower.tick();
  assert.deepEqual(calls, []);
  clock = start + 60000;
  await follower.tick();
  assert.deepEqual(calls, [2]);
  follower.pin(true, 1);
  clock = start + 3660000;
  await follower.tick();
  assert.deepEqual(calls, [2]);
  follower.pin(false, null);
  await follower.tick();
  assert.deepEqual(calls, [2, 3]);
});

test("failed next-panel requests retry without overlapping or losing manual selection", async () => {
  let clock = start + 60000, calls = [], finish;
  const follower = createFollower({ now: () => clock, races: () => races, initialId: 1,
    select: id => { calls.push(id); return new Promise(resolve => { finish = resolve; }); } });
  const pending = follower.tick();
  await follower.tick();
  assert.deepEqual(calls, [2]);
  finish(false); await pending;
  clock += 14999; await follower.tick();
  assert.deepEqual(calls, [2]);
  clock++; const retry = follower.tick();
  follower.pin(true, 1);
  finish(true); await retry;
  clock += 3600000; await follower.tick();
  assert.equal(follower.pinned, true);
  assert.deepEqual(calls, [2, 2]);
});
