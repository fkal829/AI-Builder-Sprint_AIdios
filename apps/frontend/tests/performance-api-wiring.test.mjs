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
  assert.match(page, /계약서를 기준으로 확인해요/);
  assert.match(page, /border-2 border-dashed border-neutral300/);
  assert.match(page, /① 대행사 리포트 올리기/);
  assert.match(page, /setCorrectionReason/);
  assert.match(page, /기존 기록을\s*덮어쓰지 않고 새 버전으로 남습니다/);
  assert.match(page, /문의 문안은 자동 발송되지/);
  assert.doesNotMatch(page, /화면 목업 · 개발 예정/);
  assert.doesNotMatch(page, /const JULY_POSTS/);
});

test("aggregate performance and integrated obligation use live adapter data", async () => {
  const [aggregate, contractPage] = await Promise.all([
    source("src/app/performance/page.tsx"),
    source("src/app/contracts/[id]/performance/page.tsx"),
  ]);

  assert.match(aggregate, /adapter\.getDashboard/);
  assert.match(aggregate, /adapter\.getContractPerformance/);
  assert.match(aggregate, /월별 노출 추이 — 전체 계약 합계/);
  assert.match(aggregate, /<MonthlyChart months=\{months\}/);
  assert.match(aggregate, /<SectionTitle>계약별 성과<\/SectionTitle>/);
  assert.match(aggregate, /<SectionTitle>짚어볼 점<\/SectionTitle>/);
  assert.doesNotMatch(aggregate, /const CONTRACTS|화면 목업 · 개발 예정|reportDemo/);
  assert.match(contractPage, /adapter\.getObligation/);
  assert.match(contractPage, /adapter\.createObligationEvidenceLink/);
  assert.match(contractPage, /obligation\.status === "SUBMITTED"/);
  assert.doesNotMatch(contractPage, /obligation\.status === "PENDING" \|\|/);
});
