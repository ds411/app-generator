import assert from "node:assert/strict";

import { migrate } from "drizzle-orm/pglite/migrator";

import { GET } from "../app/api/live/route";
import { hereTaskPresenceAction, leaveTaskPresenceAction } from "@/entities/task/api/task-actions";
import { taskRepository } from "@/entities/task/server";
import type { ActionResult } from "@/shared/api";
import { makeToken } from "@/shared/auth/session";
import { getDb } from "@/shared/db/client";
import {
  Broker,
  type Change,
  type LiveEvent,
  liveBroker,
  type PresentUser,
  type Subscription,
  type Viewer,
} from "@/shared/db/live";
import { personTable, personTeamsTable, projectTable, teamTable } from "@/shared/db/schema";

/** The longest time from a change to its event (the exit criteria of M37). */
const LIMIT_MS = 2_000;
/** The time to wait for an event that must not come. The events of a change are in the queues at once. */
const QUIET_MS = 200;
/** The time after the last call of a page when the broker forgets its user (PRESENCE_MS of the broker). */
const PRESENCE_MS = 15_000;

const redisUrl = process.env.APPGEN_LIVE_REDIS_URL ?? "";
const jar: Map<string, string> = ((globalThis as { appgenCookies?: Map<string, string> }).appgenCookies ??= new Map());
/** The names of the records in the events, by ID. */
const names = new Map<string, string>();

/** Return the names of users on a record, with their typing, as text. */
function who(users: PresentUser[]): string {
  return users.map((user) => (user.typing ? `${user.name} (typing)` : user.name)).join(", ") || "nobody";
}

function text(event: LiveEvent | undefined): string {
  if (event === undefined) return "none";
  if (event.type === "presence") return `presence ${names.get(event.id) ?? event.id}: ${who(event.users)}`;
  return "id" in event ? `${event.type} ${names.get(event.id) ?? event.id}` : event.type;
}

/** Wait for a promise, or give undefined after a time. */
async function within<T>(promise: Promise<T>, ms: number): Promise<T | undefined> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<undefined>((resolve) => {
    timer = setTimeout(() => resolve(undefined), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/** A client of the route `/api/live`: it reads the events of the response. */
class Stream {
  private readonly reader: ReadableStreamDefaultReader<Uint8Array>;
  private readonly decoder = new TextDecoder();
  private buffer = "";
  private reading: Promise<ReadableStreamReadResult<Uint8Array>> | undefined;
  /** True after the end of the response. */
  ended = false;

  constructor(
    response: Response,
    private readonly leave: AbortController,
  ) {
    assert.ok(response.body, "the response has no body");
    this.reader = response.body.getReader();
  }

  /** Return the next event, or undefined if none comes in the time or the stream ends. */
  async next(ms = LIMIT_MS): Promise<LiveEvent | undefined> {
    const deadline = Date.now() + ms;
    for (;;) {
      const end = this.buffer.indexOf("\n\n");
      if (end >= 0) {
        const block = this.buffer.slice(0, end);
        this.buffer = this.buffer.slice(end + 2);
        // A comment (a ping) is not an event.
        if (block.startsWith("data: ")) return JSON.parse(block.slice("data: ".length)) as LiveEvent;
        continue;
      }
      if (this.ended) return undefined;
      // A read that the time stopped stays open for the next call.
      this.reading ??= this.reader.read();
      const result = await within(this.reading, Math.max(deadline - Date.now(), 0));
      if (result === undefined) return undefined;
      this.reading = undefined;
      if (result.done) {
        this.ended = true;
      } else {
        this.buffer += this.decoder.decode(result.value, { stream: true });
      }
    }
  }

  /** Return the events that the stream has now, as text. */
  async events(): Promise<string[]> {
    const found: string[] = [];
    for (let event = await this.next(QUIET_MS); event !== undefined; event = await this.next(QUIET_MS)) {
      found.push(text(event));
    }
    return found;
  }

  close(): void {
    this.leave.abort();
  }
}

/** Sign in a user for the next calls, or sign out. */
function signIn(user: string | null): void {
  if (user) jar.set("session", makeToken(user));
  else jar.delete("session");
}

/** Call the route as a user (or without a session), and return the response. */
async function get(user: string | null, query = "", leave = new AbortController()): Promise<Response> {
  signIn(user);
  return GET(new Request(`http://localhost/api/live${query}`, { signal: leave.signal }));
}

/** Open the stream of a user: the first event is `open`. */
async function open(user: string, query = ""): Promise<Stream> {
  const leave = new AbortController();
  const response = await get(user, query, leave);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream; charset=utf-8");
  assert.equal(response.headers.get("cache-control"), "no-cache, no-transform");
  const stream = new Stream(response, leave);
  assert.equal(text(await stream.next()), "open");
  return stream;
}

/** A reader of a subscription of a broker, as the route reads it: one call of `next()` at a time. */
class Feed {
  private reading: Promise<LiveEvent | null | undefined> | undefined;

  constructor(private readonly subscription: Subscription) {}

  /** Return the next event as text, or "none" after the time. */
  async next(ms = LIMIT_MS): Promise<string> {
    // A call that the time stopped stays open for the next call.
    this.reading ??= this.subscription.next();
    const event = await within(this.reading, ms);
    if (event === undefined) return "none";
    this.reading = undefined;
    return event === null ? "ping" : text(event);
  }

  /** Read the events that the subscription has now. */
  async drain(): Promise<void> {
    while ((await this.next(QUIET_MS)) !== "none");
  }
}

const steps: [string, () => Promise<void>][] = [];
function step(name: string, run: () => Promise<void>): void {
  steps.push([name, run]);
}

const db = getDb();
const users: Record<string, string> = {};
const projects: Record<string, string> = {};
const streams: Record<string, Stream> = {};

/** Check the events of each stream after a change. */
async function expectEvents(expected: Record<string, string[]>): Promise<void> {
  for (const [name, events] of Object.entries(expected)) {
    assert.deepEqual(await streams[name]?.events(), events, `the events of ${name}`);
  }
}

step("the route opens a stream for a user that may read an entity, else 400 or 401", async () => {
  await migrate(db, { migrationsFolder: "drizzle" });
  const people = await db
    .insert(personTable)
    .values([
      { name: "Ada Admin", email: "ada@example.com", role: "admin" },
      { name: "Ben Member", email: "ben@example.com", role: "member" },
      { name: "Cy Member", email: "cy@example.com", role: "member" },
      { name: "Dee Reviewer", email: "dee@example.com", role: "reviewer" },
    ])
    .returning();
  for (const person of people) users[person.email.split("@")[0] ?? ""] = person.id;
  const teams = await db.insert(teamTable).values([{ name: "Red" }, { name: "Blue" }]).returning();
  const [red, blue] = teams.map((team) => team.id);
  assert.ok(red && blue);
  await db.insert(personTeamsTable).values([
    { personId: users.ben ?? "", teamId: red },
    { personId: users.cy ?? "", teamId: blue },
  ]);
  const rows = await db
    .insert(projectTable)
    .values([
      { name: "Red project", teamId: red },
      { name: "Blue project", teamId: blue },
    ])
    .returning();
  projects.red = rows[0]?.id ?? "";
  projects.blue = rows[1]?.id ?? "";

  assert.equal((await get(null)).status, 401);
  assert.equal((await get(null, "?entity=Task")).status, 401);
  // Project is not a live entity.
  assert.equal((await get(users.ada ?? "", "?entity=Project")).status, 400);
  assert.equal((await get(users.ada ?? "", "?entity=Task&entity=Nothing")).status, 400);
  for (const name of ["ada", "ben", "cy", "dee"]) {
    streams[name] = await open(users[name] ?? "", name === "ben" ? "?entity=Task" : "");
  }
});

step("a new open task goes to the admin and to the members of the team of its project", async () => {
  const task = await taskRepository.create({ title: "Paint", projectId: projects.red ?? "", status: "open" });
  names.set(task.id, "Paint");
  await expectEvents({ ada: ["created Paint"], ben: ["created Paint"], cy: [], dee: [] });
});

step("a done task leaves the members and goes to the reviewer: both get the change", async () => {
  const [paint] = [...names].find(([, name]) => name === "Paint") ?? [];
  await taskRepository.update(paint ?? "", { status: "done" });
  await expectEvents({ ada: ["changed Paint"], ben: ["changed Paint"], cy: [], dee: ["changed Paint"] });
  await taskRepository.update(paint ?? "", { title: "Paint the wall" });
  names.set(paint ?? "", "Paint the wall");
  await expectEvents({ ada: ["changed Paint the wall"], ben: [], cy: [], dee: ["changed Paint the wall"] });
});

step("the events of a task of another team go only to the members of that team", async () => {
  const task = await taskRepository.create({ title: "Sweep", projectId: projects.blue ?? "", status: "in_progress" });
  names.set(task.id, "Sweep");
  const [paint] = [...names].find(([, name]) => name === "Paint the wall") ?? [];
  await taskRepository.remove(paint ?? "");
  await expectEvents({
    ada: ["created Sweep", "deleted Paint the wall"],
    ben: [],
    cy: ["created Sweep"],
    dee: ["deleted Paint the wall"],
  });
  await taskRepository.remove(task.id);
  await expectEvents({ ada: ["deleted Sweep"], ben: [], cy: ["deleted Sweep"], dee: [] });
});

step("a client that leaves has no subscription: the next changes go to the others", async () => {
  streams.cy?.close();
  const task = await taskRepository.create({ title: "Mop", projectId: projects.blue ?? "", status: "open" });
  names.set(task.id, "Mop");
  await expectEvents({ ada: ["created Mop"], ben: [], dee: [] });
});

step("the users on the page of a task see the other users that may read the task (ADR 0052)", async () => {
  /** Note a user on the page of a task, as the page does, and return the other users or the error. */
  const here = async (user: string | null, id: string, typing = false): Promise<string> => {
    signIn(user === null ? null : (users[user] ?? ""));
    const result: ActionResult<PresentUser[]> = await hereTaskPresenceAction(id, typing);
    return result.ok ? who(result.data) : `error ${result.error.name}`;
  };
  const task = await taskRepository.create({ title: "Plan", projectId: projects.red ?? "", status: "open" });
  names.set(task.id, "Plan");
  await expectEvents({ ada: ["created Plan"], ben: ["created Plan"], dee: [] });

  // Ben opens the page of the task, then Ada: each one gets the other user.
  assert.equal(await here("ben", task.id), "nobody");
  await expectEvents({ ada: [], ben: [], dee: [] });
  assert.equal(await here("ada", task.id), "Ben Member");
  await expectEvents({ ada: [], ben: ["presence Plan: Ada Admin"], dee: [] });

  // Ada types in a form: Ben gets her typing. A heartbeat without a change gives no event.
  assert.equal(await here("ada", task.id, true), "Ben Member");
  await expectEvents({ ada: [], ben: ["presence Plan: Ada Admin (typing)"], dee: [] });
  assert.equal(await here("ada", task.id, true), "Ben Member");
  assert.equal(await here("ben", task.id), "Ada Admin (typing)");
  await expectEvents({ ada: [], ben: [], dee: [] });

  // The reviewer may read only the done tasks, and a member only the tasks of the teams of the member.
  assert.equal(await here("dee", task.id), "error NotFoundError");
  assert.equal(await here("cy", task.id), "error NotFoundError");
  assert.equal(await here(null, task.id), "error Error");
  await expectEvents({ ada: [], ben: [], dee: [] });

  // Ada leaves the page: Ben gets nobody.
  signIn(users.ada ?? "");
  const left: ActionResult<null> = await leaveTaskPresenceAction(task.id);
  assert.ok(left.ok, `the leave failed: ${JSON.stringify(left)}`);
  await expectEvents({ ada: [], ben: ["presence Plan: nobody"], dee: [] });

  // Ada opens the page again after Ben. Without a call of Ben, the broker forgets Ben, and tells Ada.
  assert.equal(await here("ben", task.id), "nobody");
  const after = Date.now();
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(await here("ada", task.id), "Ben Member");
  await expectEvents({ ada: [], ben: ["presence Plan: Ada Admin"], dee: [] });
  // Ben's call ended before `after`, and Ada's call started after it.
  liveBroker().forget(after + PRESENCE_MS);
  await expectEvents({ ada: ["presence Plan: nobody"], ben: [], dee: [] });
  assert.deepEqual(
    liveBroker()
      .users("Task", task.id)
      .map((user) => user.name),
    ["Ada Admin"],
  );
  liveBroker().forget(Date.now() + PRESENCE_MS);
  assert.deepEqual(liveBroker().users("Task", task.id), []);
  await expectEvents({ ada: [], ben: [], dee: [] });
});

step("with Redis, the brokers of two replicas give each change to the streams of both", async () => {
  if (!redisUrl) {
    console.log("live-test: no APPGEN_LIVE_REDIS_URL, so no check of Redis");
    return;
  }
  const viewer: Viewer = { entities: new Set(["Task"]), user: users.ada ?? "", role: "admin" };
  const first = new Broker(redisUrl);
  const second = new Broker(redisUrl);
  const near = new Feed(first.subscribe(viewer));
  const far = new Feed(second.subscribe(viewer));
  try {
    // The subscribers connect: send a first change until the second replica gets it.
    names.set("probe", "probe");
    const probe: Change = { entity: "Task", id: "probe", action: "changed", audiences: null };
    let ready = false;
    for (let tries = 0; tries < 100 && !ready; tries += 1) {
      first.publish([probe]);
      ready = (await far.next(100)) === "changed probe";
    }
    assert.ok(ready, "the second replica got no change through Redis");
    await near.drain();
    await far.drain();

    for (const [from, id] of [
      [first, "one"],
      [second, "two"],
    ] as const) {
      names.set(id, id);
      const start = Date.now();
      from.publish([{ entity: "Task", id, action: "created", audiences: null }]);
      assert.equal(await near.next(), `created ${id}`);
      assert.equal(await far.next(), `created ${id}`);
      assert.ok(Date.now() - start < LIMIT_MS, `the change ${id} took ${Date.now() - start} ms`);
    }

    // The calls of the record pages go through Redis too: each replica knows the users of both.
    names.set("board", "board");
    const ben = new Feed(second.subscribe({ entities: new Set(["Task"]), user: users.ben ?? "", role: "member" }));
    assert.deepEqual(second.here("Task", "board", users.ben ?? "", "Ben Member", false), []);
    const known = () => first.users("Task", "board").length > 0 && second.users("Task", "board").length > 0;
    for (let tries = 0; tries < 100 && !known(); tries += 1) {
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.ok(known(), "the brokers did not get the user of the second broker through Redis");
    const start = Date.now();
    const others = first.here("Task", "board", users.ada ?? "", "Ada Admin", true);
    assert.equal(who(others), "Ben Member", "the first replica did not get the user of the second");
    assert.equal(await ben.next(), "presence board: Ada Admin (typing)");
    assert.ok(Date.now() - start < LIMIT_MS, `the presence took ${Date.now() - start} ms`);
    first.leave("Task", "board", users.ada ?? "");
    assert.equal(await ben.next(), "presence board: nobody");
  } finally {
    await Promise.all([first.close(), second.close()]);
  }
});

step("without Redis at the URL, a broker logs a warning and gives its changes to its own streams", async () => {
  const warnings: string[] = [];
  const warn = console.warn;
  console.warn = (...args: unknown[]) => void warnings.push(args.map(String).join(" "));
  // No Redis listens on port 1.
  const broker = new Broker("redis://127.0.0.1:1");
  try {
    const feed = new Feed(broker.subscribe({ entities: new Set(["Task"]), user: null, role: "admin" }));
    names.set("alone", "alone");
    for (const action of ["created", "changed"] as const) {
      broker.publish([{ entity: "Task", id: "alone", action, audiences: null }]);
      assert.equal(await feed.next(), `${action} alone`);
    }
    assert.equal(warnings.filter((line) => line.startsWith("The Redis of the live events is not available")).length, 1);
  } finally {
    console.warn = warn;
    await broker.close();
  }
});

step("at the stop of the server, the open streams end, and a new stream ends at once", async () => {
  liveBroker().endStreams();
  for (const name of ["ada", "ben", "dee"]) {
    assert.equal(await streams[name]?.next(), undefined);
    assert.ok(streams[name]?.ended, `the stream of ${name} did not end`);
  }
  const late = await open(users.ada ?? "");
  assert.equal(await late.next(), undefined);
  assert.ok(late.ended, "the new stream did not end");
});

let failures = 0;
for (const [name, run] of steps) {
  try {
    await run();
    console.log(`live-test: ok: ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`live-test: FAILED: ${name}`);
    console.log(error);
  }
}
process.exit(failures > 0 ? 1 : 0);
