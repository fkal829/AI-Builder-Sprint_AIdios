import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (relativePath) =>
  readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("ApiAdapter implements every remaining P0 owner workflow", async () => {
  const adapter = await source("src/lib/adapter.ts");
  const apiAdapter = adapter.slice(adapter.indexOf("class ApiAdapter"));

  for (const method of [
    "polishAdjustmentCopy",
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

test("tone polishing uses the owner API and requires explicit preview approval", async () => {
  const [adapter, viewer, requestPage] = await Promise.all([
    source("src/lib/adapter.ts"),
    source("src/app/contracts/[id]/page.tsx"),
    source("src/app/contracts/[id]/request/page.tsx"),
  ]);
  const apiAdapter = adapter.slice(adapter.indexOf("class ApiAdapter"));

  assert.match(apiAdapter, /async polishAdjustmentCopy\(contractId: string, text: string\)/);
  assert.match(apiAdapter, /\/adjustment-copy\/polish`/);
  assert.match(apiAdapter, /body: JSON\.stringify\(\{ text \}\)/);
  assert.match(viewer, /adapter\.polishAdjustmentCopy\(contractId, source\)/);
  assert.match(viewer, /AI가 다듬는 중…/);
  assert.match(viewer, /이 문구로 적용/);
  assert.match(viewer, /숫자와 핵심 조건이 그대로인지/);
  assert.doesNotMatch(viewer, /setPolished\(politen\(/);
  assert.doesNotMatch(requestPage, /function ToneBuffer/);
  assert.doesNotMatch(requestPage, /AI가 정중하게 바꿔드려요/);
});

test("adjustment link creation remains a manual delivery boundary", async () => {
  const [page, adapter] = await Promise.all([
    source("src/app/contracts/[id]/request/page.tsx"),
    source("src/lib/adapter.ts"),
  ]);

  assert.match(page, /const link = await adapter\.sendAdjustmentDraft/);
  assert.match(page, /setSentLink\(link\)/);
  assert.match(page, /Object\.fromEntries\(/);
  assert.match(page, /item\.id, item\.text/);
  assert.match(page, /filter\(\(item\) => item\.manual\)/);
  assert.match(page, /documentClauseId: item\.id/);
  assert.match(adapter, /manual_items: manualItems\.map/);
  assert.match(adapter, /document_clause_id: item\.documentClauseId/);
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
  const [obligation, legacyObligation, renewal] = await Promise.all([
    source("src/app/contracts/[id]/performance/page.tsx"),
    source("src/app/contracts/[id]/obligations/page.tsx"),
    source("src/app/contracts/[id]/renewal/page.tsx"),
  ]);

  assert.match(obligation, /adapter\.createObligationEvidenceLink/);
  assert.match(obligation, /adapter\.reviewObligation/);
  assert.match(legacyObligation, /redirect\(`\/contracts\/\$\{id\}\/performance`\)/);
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
  assert.match(dashboard, /\/performance/);
  assert.match(dashboard, /status === "RENEWAL_DUE"/);
  assert.match(dashboard, /\/renewal/);
});

test("failed contract analysis can be explicitly retried with the same documents", async () => {
  const [adapter, page] = await Promise.all([
    source("src/lib/adapter.ts"),
    source("src/app/contracts/[id]/analysis/page.tsx"),
  ]);

  assert.match(adapter, /supporting_document_ids: supportingDocumentIds/);
  assert.match(page, /task\.document_id/);
  assert.match(page, /task\.supporting_document_ids/);
  assert.match(page, /adapter\.startContractAnalysis/);
  assert.match(page, /같은 계약서 다시 분석하기/);
  assert.match(page, /문서 분량에 따라 1~3분/);
});

test("live review loads all parsed clauses and exposes the signed PDF only as a new-tab link", async () => {
  const [adapter, page, viewModel] = await Promise.all([
    source("src/lib/adapter.ts"),
    source("src/app/contracts/[id]/page.tsx"),
    source("src/lib/reviewViewModel.ts"),
  ]);

  assert.match(adapter, /encodeURIComponent\(task\.document_id\)\}\/access/);
  assert.match(adapter, /documentAccessUrl: documentAccess\.access_url/);
  assert.match(adapter, /task\.result\.document_clauses \?\? \[\]/);
  assert.match(viewModel, /review\.documentClauses\.map/);
  assert.match(viewModel, /findDocumentClause/);
  assert.match(page, /계약서 원문/);
  assert.match(page, /doc\.clauses\.map/);
  assert.match(page, /PDF 원본 보기/);
  assert.match(page, /target="_blank"/);
  assert.match(page, /rel="noopener noreferrer"/);
  assert.doesNotMatch(page, /<iframe/);
  assert.doesNotMatch(page, /localStorage[^]*documentAccessUrl/);
});
