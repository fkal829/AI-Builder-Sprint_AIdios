import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (relativePath) =>
  readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("performance adapter covers upload, extraction, confirmation, correction, and aggregate read", async () => {
  const adapter = await source("src/lib/adapter.ts");
  const apiAdapter = adapter.slice(adapter.indexOf("class ApiAdapter"));

  for (const method of [
    "getContractPerformance",
    "uploadPerformanceReport",
    "extractPerformanceReport",
    "confirmPerformanceReport",
  ]) {
    assert.match(apiAdapter, new RegExp(`async ${method}\\(`), `${method} must use ApiAdapter`);
  }

  assert.match(apiAdapter, /\/performance-reports`/);
  assert.match(apiAdapter, /encodeURIComponent\(reportId\)\}\/extract/);
  assert.match(apiAdapter, /expected_revision: input\.expectedRevision/);
  assert.match(apiAdapter, /correction_reason: input\.correctionReason/);
  assert.match(apiAdapter, /"Idempotency-Key": crypto\.randomUUID\(\)/);
});

test("performance page uses evidence-backed API data and keeps inquiry delivery manual", async () => {
  const page = await source("src/app/contracts/[id]/performance/page.tsx");

  assert.match(page, /adapter\.getContractPerformance/);
  assert.match(page, /adapter\.uploadPerformanceReport/);
  assert.match(page, /adapter\.extractPerformanceReport/);
  assert.match(page, /adapter\.confirmPerformanceReport/);
  assert.match(page, /candidate\.sourcePage/);
  assert.match(page, /candidate\.sourceText/);
  assert.match(page, /candidate\.confidence/);
  assert.match(page, /setCorrectionReason/);
  assert.match(page, /기존 기록을\s*덮어쓰지 않고 새 버전으로 남습니다/);
  assert.match(page, /문의 문안은 자동 발송되지/);
  assert.doesNotMatch(page, /화면 목업 · 개발 예정/);
  assert.doesNotMatch(page, /const JULY_POSTS/);
});
