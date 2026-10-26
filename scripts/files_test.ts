import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { CreateBucketCommand } from "@aws-sdk/client-s3";
import { migrate } from "drizzle-orm/pglite/migrator";

import { GET as documentFile } from "../app/files/document/[id]/[field]/route";
import {
  createDocumentAction,
  getDocumentAction,
  removeDocumentAction,
  removeDocumentFileAction,
  uploadDocumentFileAction,
} from "@/entities/document/api/document-actions";
import { createNoteAction, uploadNoteFileAction } from "@/entities/note/api/note-actions";
import { uploadPersonFileAction } from "@/entities/person/api/person-actions";
import type { ActionResult } from "@/shared/api";
import { makeToken } from "@/shared/auth/session";
import { getDb } from "@/shared/db";
import { seedDatabase } from "@/shared/db/seed";
import {
  allows,
  BucketStorage,
  fileName,
  makeStorage,
  mediaTypeOf,
  sizeText,
} from "@/shared/storage/storage";

const plan = JSON.parse(process.env.APPGEN_FILES_PLAN ?? "{}");
const folder = path.resolve(process.env[plan.folderEnv] ?? "");
const jar: Map<string, string> = ((globalThis as { appgenCookies?: Map<string, string> }).appgenCookies ??= new Map());
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP4//8/AAX+Av4zEpUUAAAAAElFTkSuQmCC",
  "base64",
);
const PDF = Buffer.from("%PDF-1.4\n%%EOF\n");

function signIn(userId: string | null): void {
  if (userId) jar.set("session", makeToken(userId));
  else jar.delete("session");
}

function form(name: string, content: Uint8Array, type: string): FormData {
  const data = new FormData();
  data.set("file", new File([new Uint8Array(content)], name, { type }));
  return data;
}

function ok<T>(result: ActionResult<T>): T {
  assert.ok(result.ok, `the action failed: ${JSON.stringify(result)}`);
  return result.data;
}

function failed<T>(result: ActionResult<T>, message: string): void {
  assert.ok(!result.ok, `the action did not fail: ${JSON.stringify(result)}`);
  assert.equal(result.error.message, message);
}

async function stored(): Promise<string[]> {
  const entries = await readdir(folder, { recursive: true, withFileTypes: true }).catch(() => []);
  return entries
    .filter((entry) => entry.isFile())
    .map((entry) => path.relative(folder, path.join(entry.parentPath, entry.name)).split(path.sep).join("/"))
    .sort();
}

async function get(id: string, field: string): Promise<Response> {
  const request = new Request(`http://localhost/files/document/${id}/${field}`);
  return documentFile(request, { params: Promise.resolve({ id, field }) });
}

async function body(response: Response): Promise<Buffer> {
  return Buffer.from(await response.arrayBuffer());
}

const steps: [string, () => Promise<void>][] = [];
function step(name: string, run: () => Promise<void>): void {
  steps.push([name, run]);
}

const { ada, ben, guide } = plan.ids;
let benDocument = "";

step("the seed saves the files of the seed records", async () => {
  await migrate(getDb(), { migrationsFolder: "drizzle" });
  await seedDatabase(getDb());
  assert.deepEqual(await stored(), Object.keys(plan.files).sort());
  for (const [key, content] of Object.entries(plan.files)) {
    assert.deepEqual(await readFile(path.join(folder, key)), Buffer.from(content as string, "base64"), key);
  }
});

step("a read gives the files with their URLs, and the route gives the files", async () => {
  signIn(ada);
  const document = ok(await getDocumentAction(guide));
  assert.ok(document.scan && document.cover);
  assert.equal(document.scan.name, "guide.pdf");
  assert.equal(document.scan.type, "application/pdf");
  assert.equal(document.scan.size, Buffer.from(plan.files[plan.keys.scan], "base64").length);
  assert.match(document.scan.url, new RegExp(`^/files/document/${guide}/scan\\?v=seed-[0-9a-f]{12}$`));
  const scan = await get(guide, "scan");
  assert.equal(scan.status, 200);
  assert.deepEqual(await body(scan), Buffer.from(plan.files[plan.keys.scan], "base64"));
  assert.equal(scan.headers.get("content-type"), "application/pdf");
  assert.equal(scan.headers.get("x-content-type-options"), "nosniff");
  assert.equal(scan.headers.get("content-disposition"), "inline; filename*=UTF-8''guide.pdf");
  assert.equal(scan.headers.get("content-security-policy"), null);
  const cover = await get(guide, "cover");
  assert.equal(cover.status, 200);
  assert.match(cover.headers.get("content-security-policy") ?? "", /sandbox/);
});

step("a new file replaces the old file", async () => {
  const before = ok(await getDocumentAction(guide));
  const after = ok(await uploadDocumentFileAction(guide, "cover", form("new.png", PNG, "image/png")));
  assert.equal(after.cover?.name, "new.png");
  assert.equal(after.cover?.size, PNG.length);
  assert.notEqual(after.cover?.url, before.cover?.url);
  const files = await stored();
  assert.ok(!files.includes(plan.keys.cover), "the old cover is still in the storage");
  assert.equal(files.filter((key) => key.startsWith(`document/${guide}/cover/`)).length, 1);
  assert.deepEqual(await body(await get(guide, "cover")), PNG);
});

step("the rules of the fields stop wrong files", async () => {
  const files = await stored();
  const large = Buffer.concat([PNG, Buffer.alloc(1024 * 1024)]);
  failed(await uploadPersonFileAction(ada, "avatar", form("large.png", large, "image/png")), "The file is larger than 1 MB.");
  const html = Buffer.from("<script>alert(1)</script>");
  failed(
    await uploadDocumentFileAction(guide, "cover", form("page.html", html, "text/html")),
    "The type text/html is not allowed. Use one of: image/png, image/jpeg, image/gif, image/webp.",
  );
  failed(
    await uploadDocumentFileAction(guide, "cover", form("page.png", html, "image/png")),
    "The type application/octet-stream is not allowed. Use one of: image/png, image/jpeg, image/gif, image/webp.",
  );
  failed(await uploadDocumentFileAction(guide, "scan", new FormData()), "Select a file.");
  failed(
    await uploadDocumentFileAction(guide, "title" as "scan", form("a.pdf", PDF, "application/pdf")),
    "Document has no file field title.",
  );
  assert.deepEqual(await stored(), files);
});

step("the delete of a file removes it", async () => {
  const document = ok(await removeDocumentFileAction(guide, "scan"));
  assert.equal(document.scan, null);
  assert.ok(!(await stored()).includes(plan.keys.scan));
  assert.equal((await get(guide, "scan")).status, 404);
});

step("the route gives 404 for an unknown record or field", async () => {
  assert.equal((await get("not-a-uuid", "cover")).status, 404);
  assert.equal((await get(ben, "cover")).status, 404);
  assert.equal((await get(guide, "title")).status, 404);
  assert.equal((await get(guide, "constructor")).status, 404);
});

step("a member reads the files of others, and changes only the own files", async () => {
  signIn(ben);
  assert.equal((await get(guide, "cover")).status, 200);
  const result = await uploadDocumentFileAction(guide, "scan", form("a.pdf", PDF, "application/pdf"));
  assert.ok(!result.ok && result.error.name === "NotFoundError", JSON.stringify(result));
  benDocument = ok(await createDocumentAction({ title: "The notes of Ben", ownerId: ben })).id;
  const own = ok(await uploadDocumentFileAction(benDocument, "scan", form("notes.pdf", PDF, "application/pdf")));
  assert.equal(own.scan?.type, "application/pdf");
  const note = ok(await createNoteAction({ text: "See the scan.", documentId: benDocument }));
  const attached = ok(await uploadNoteFileAction(note.id, "attachment", form("notes.txt", Buffer.from("text"), "text/plain")));
  assert.equal(attached.attachment?.type, "text/plain");
});

step("without a session, the route gives 404 and an upload fails", async () => {
  signIn(null);
  assert.equal((await get(benDocument, "scan")).status, 404);
  failed(await uploadDocumentFileAction(benDocument, "scan", form("a.pdf", PDF, "application/pdf")), "Sign in to do this.");
});

step("the delete of a record removes its files, and a second seed adds them again", async () => {
  signIn(ada);
  ok(await removeDocumentAction(guide));
  assert.ok(!(await stored()).some((key) => key.startsWith(`document/${guide}/`)));
  assert.equal(await seedDatabase(getDb()), 1);
  const files = await stored();
  assert.ok(files.includes(plan.keys.scan) && files.includes(plan.keys.cover), files.join(", "));
});

step("the bucket saves, reads, and deletes a file", async () => {
  const storage = makeStorage({ ...process.env, ...plan.bucket });
  assert.ok(storage instanceof BucketStorage);
  await storage.client.send(new CreateBucketCommand({ Bucket: storage.bucket }));
  await storage.save("notes/1/file/abc", Buffer.from("hello"), "text/plain");
  assert.deepEqual(Buffer.from((await storage.read("notes/1/file/abc")) ?? []), Buffer.from("hello"));
  await storage.delete("notes/1/file/abc");
  assert.equal(await storage.read("notes/1/file/abc"), null);
});

step("the helpers of the storage", async () => {
  const cases: [Uint8Array, string | null, string][] = [
    [Buffer.from("\x89PNG\r\n\x1a\n...", "latin1"), "text/plain", "image/png"],
    [Buffer.from("%PDF-1.7"), null, "application/pdf"],
    [Buffer.from("RIFF\x0c\x00\x00\x00WEBPVP8 ", "latin1"), "image/png", "image/webp"],
    [Buffer.from("<html></html>"), "image/png", "application/octet-stream"],
    [Buffer.from("a,b"), "text/csv; charset=utf-8", "text/csv"],
    [Buffer.from("data"), null, "application/octet-stream"],
  ];
  for (const [content, given, expected] of cases) {
    assert.equal(mediaTypeOf(content, given), expected);
  }
  assert.ok(allows({ maxSize: 10, types: ["image/*", "application/pdf"] }, "image/png"));
  assert.ok(!allows({ maxSize: 10, types: ["image/*"] }, "text/html"));
  assert.ok(allows({ maxSize: 10, types: [] }, "text/html"));
  assert.equal(fileName("C:\\Users\\me\\photo.png"), "photo.png");
  assert.equal(fileName("../../etc/passwd"), "passwd");
  assert.equal(fileName(null), "file");
  assert.deepEqual([512, 1536, 5 * 1024 * 1024].map(sizeText), ["512 B", "1.5 KB", "5 MB"]);
  await assert.rejects(makeStorage({ ...process.env, [plan.bucketEnv]: "" }).read("../secret"));
});

let failures = 0;
for (const [name, run] of steps) {
  try {
    await run();
    console.log(`files-test: ok: ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`files-test: FAILED: ${name}`);
    console.log(error);
  }
}
process.exit(failures > 0 ? 1 : 0);
