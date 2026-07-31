import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { publicRouteHeaders } from "../public-route-headers.mjs";

test("public token pages prevent referrer, cache, and crawler exposure", () => {
  const [rule] = publicRouteHeaders();
  const headers = Object.fromEntries(
    rule.headers.map(({ key, value }) => [key.toLowerCase(), value]),
  );

  assert.equal(rule.source, "/r/:path*");
  assert.equal(headers["referrer-policy"], "no-referrer");
  assert.equal(headers["cache-control"], "no-store");
  assert.equal(headers["x-robots-tag"], "noindex, nofollow");
});

test("evidence page does not claim a fixed deliverable or due date", async () => {
  const source = await readFile(
    new URL("../src/app/r/[token]/evidence/page.tsx", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(source, /인스타그램 게시물 4건/);
  assert.doesNotMatch(source, /2026-08-20/);
  assert.match(source, /요청받은 대표 산출물/);
  assert.match(source, /사장님이 승인하면/);
  assert.doesNotMatch(source, /사장님이 확인하면/);
});
