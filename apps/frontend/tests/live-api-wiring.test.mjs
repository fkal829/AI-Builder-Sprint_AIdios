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
  assert.match(page, /if \(draft === null\) return true/);
  assert.match(page, /saved\?\.choice === "REQUEST" \|\| saved\?\.choice === "COMPROMISE"/);
  assert.match(page, /disabled=\{items\.length === 0\}/);
  assert.doesNotMatch(page, /items\.length > 4/);
  assert.doesNotMatch(page, /한 요청서에는 조정 항목을 최대 4건까지 담을 수 있습니다/);
  assert.doesNotMatch(adapter, /\.slice\(0, 4\)/);
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

test("audit timeline is rendered in Korean and distinguishes every signature status", async () => {
  const adapter = await source("src/lib/adapter.ts");

  // 저장된 summary는 기록 계층마다 언어·문체가 다르고, 서명 동기화는 진행/완료를
  // 같은 문장으로 남긴다. 화면 문구는 상태마다 값이 다른 event_type에서 만든다.
  assert.match(
    adapter,
    /label: auditEventLabel\(event\.event_type\) \?\? event\.summary\?\.trim\(\) \?\? event\.event_type/,
  );
  assert.doesNotMatch(adapter, /label: event\.summary\?\.trim\(\) \|\| auditEventLabel/);

  const labels = adapter.slice(
    adapter.indexOf("const AUDIT_EVENT_LABELS"),
    adapter.indexOf("function auditEventLabel"),
  );

  // 서명 4개 상태가 서로 다른 문구여야 타임라인에서 구분된다.
  const signatureLabels = ["SIGNATURE_STARTED", "SIGNATURE_COMPLETED", "SIGNATURE_ABORTED", "SIGNATURE_FAILED"]
    .map((type) => new RegExp(`${type}: "([^"]+)"`).exec(labels)?.[1]);
  assert.ok(signatureLabels.every(Boolean), "모든 서명 상태에 문구가 있어야 합니다");
  assert.equal(new Set(signatureLabels).size, signatureLabels.length, "서명 상태 문구가 서로 달라야 합니다");

  // 백엔드 AuditEventType 전부를 덮어야 영어 summary가 화면에 새지 않는다.
  const enums = await readFile(
    new URL("../../api/app/core/enums.py", import.meta.url),
    "utf8",
  );
  const afterClass = enums.slice(enums.indexOf("class AuditEventType"));
  const nextClass = afterClass.indexOf("\nclass ", 1);
  const block = nextClass === -1 ? afterClass : afterClass.slice(0, nextClass);
  const backendTypes = [...block.matchAll(/^\s{4}(\w+) = "/gm)].map((m) => m[1]);
  assert.ok(backendTypes.length > 20, "AuditEventType 파싱에 실패했습니다");
  const missing = backendTypes.filter((type) => !new RegExp(`\\n  ${type}: "`).test(labels));
  assert.deepEqual(missing, [], `문구가 없는 감사 이벤트: ${missing.join(", ")}`);

  for (const label of [...labels.matchAll(/: "([^"]+)"/g)].map((m) => m[1])) {
    assert.doesNotMatch(label, /[A-Za-z]{4,}/, `사용자 문구에 영어가 남아 있습니다: ${label}`);
  }
});

test("signature page keeps polling the timeline until Modusign reaches a terminal status", async () => {
  const page = await source("src/app/contracts/[id]/signature/page.tsx");

  // 모두싸인 서명은 웹훅(C-8)으로 비동기 진행되므로, 최초 1회 조회만으로는
  // 초안 생성 이후의 SIGNATURE_STARTED/COMPLETED 감사 이벤트를 화면이 볼 수 없다.
  // 진행 중(REQUEST_READY/REQUESTING/EDITING/SIGNING)일 때는 계속 다시 조회해야 한다.
  assert.match(page, /TERMINAL_SIGNATURE_STATUSES/);
  assert.match(page, /"COMPLETED"[^]*"ABORTED"[^]*"FAILED"/);
  assert.match(page, /setTimeout\(\(\) => \{\s*if \(alive\) void refreshView\(\);/);
  assert.match(page, /await adapter\.getSignatureView\(id\)/);

  // 렌더링은 최초 조회 스냅샷(state.data)이 아니라 매 폴링마다 갱신되는
  // liveView 기반 view를 사용해야 새 감사 이벤트가 화면에 반영된다.
  assert.match(page, /const view: LiveSignatureView \| null =\s*\n\s*liveView \?\?/);
  assert.match(page, /<Timeline events={view\.timeline} \/>/);
  assert.doesNotMatch(page, /Timeline events={state\.data\.timeline}/);

  // 초안 생성 직후에는 4초 폴링을 기다리지 않고 즉시 갱신한다.
  assert.match(page, /setEditorUrl\(draft\.editorUrl\);\s*\n\s*window\.localStorage\.removeItem\([^)]+\);\s*\n\s*await refreshView\(\);/);
});
