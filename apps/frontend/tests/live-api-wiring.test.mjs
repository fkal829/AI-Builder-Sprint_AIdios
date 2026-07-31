import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (relativePath) =>
  readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("ApiAdapter implements every remaining P0 owner workflow", async () => {
  const adapter = await source("src/lib/adapter.ts");
  const apiAdapter = adapter.slice(adapter.indexOf("class ApiAdapter"));

  for (const method of [
    "getAdjustmentPreview",
    "getAdjustmentDetail",
    "getSignatureView",
    "getObligation",
    "createObligationEvidenceLink",
    "reviewObligation",
    "getRenewalView",
    "saveRenewalDecision",
  ]) {
    assert.match(apiAdapter, new RegExp(`async ${method}\\(`), `${method} must use the API adapter`);
  }
});

test("adjustment link creation remains a manual delivery boundary", async () => {
  const page = await source("src/app/contracts/[id]/request/page.tsx");

  assert.match(page, /const link = await adapter\.sendAdjustmentDraft/);
  assert.match(page, /setSentLink\(link\)/);
  assert.match(page, /아직 자동 발송되지 않았습니다/);
  assert.match(page, /응답 대기 화면으로/);
});

test("counteroffers require an explicit owner resolution", async () => {
  const [adapter, page] = await Promise.all([
    source("src/lib/adapter.ts"),
    source("src/app/contracts/[id]/responses/page.tsx"),
  ]);
  const apiAdapter = adapter.slice(adapter.indexOf("class ApiAdapter"));

  assert.doesNotMatch(apiAdapter, /response\.decision === "COUNTER"/);
  assert.match(page, /ACCEPT_COUNTERPROPOSAL/);
  assert.match(page, /역제안 반영/);
  assert.match(page, /원안 유지/);
  assert.match(page, /disabled=\{confirming \|\| !canConfirm\}/);
});

test("obligation and renewal decisions persist through their APIs", async () => {
  const [obligation, renewal] = await Promise.all([
    source("src/app/contracts/[id]/obligations/page.tsx"),
    source("src/app/contracts/[id]/renewal/page.tsx"),
  ]);

  assert.match(obligation, /adapter\.createObligationEvidenceLink/);
  assert.match(obligation, /adapter\.reviewObligation/);
  assert.match(renewal, /adapter\.saveRenewalDecision/);
  assert.match(renewal, /자동으로 시작되지 않습니다/);
});

test("dashboard routes each persisted contract status to its live workflow", async () => {
  const dashboard = await source("src/app/dashboard/page.tsx");

  assert.doesNotMatch(dashboard, /DEMO_CONTRACT_ID/);
  assert.match(dashboard, /status === "NEGOTIATING"/);
  assert.match(dashboard, /\/responses/);
  assert.match(dashboard, /status === "READY_TO_SIGN"/);
  assert.match(dashboard, /\/signature/);
  assert.match(dashboard, /status === "IN_PROGRESS"/);
  assert.match(dashboard, /\/obligations/);
  assert.match(dashboard, /status === "RENEWAL_DUE"/);
  assert.match(dashboard, /\/renewal/);
});
