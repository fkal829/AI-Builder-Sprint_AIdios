import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (relativePath) =>
  readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("owner navigation keeps integrated management and aggregate performance adjacent", async () => {
  const header = await source("src/components/SiteHeader.tsx");
  const manageIndex = header.indexOf('key: "manage"');
  const performanceIndex = header.indexOf('key: "performance"');
  const renewalIndex = header.indexOf('key: "renewal"');

  assert.ok(manageIndex < performanceIndex);
  assert.ok(performanceIndex < renewalIndex);
  assert.match(header, /key: "manage"[^]*href: "\/manage"/);
  assert.match(header, /adapter\.getDashboard\(\)/);
  assert.match(header, /pathname\.startsWith\("\/manage"\)/);
  assert.match(header, /pathname\.startsWith\("\/performance"\)/);
  assert.match(header, /href: "\/performance"/);
  assert.match(header, /<AuthControl \/>/);
  assert.match(header, /aria-current=\{on \? "page" : undefined\}/);
  assert.match(header, /overflow-x-auto pb-2 md:hidden/);
  assert.match(header, /hidden items-center gap-1 md:flex/);
});

test("integrated management lets the owner choose an eligible contract before upload", async () => {
  const [manage, contractPage] = await Promise.all([
    source("src/app/manage/page.tsx"),
    source("src/app/contracts/[id]/performance/page.tsx"),
  ]);

  assert.match(manage, /adapter\.getDashboard\(\)/);
  assert.match(manage, /adapter\.getContractPerformance\(contract\.id\)/);
  assert.match(manage, /adapter\.getObligation\(contract\.id\)/);
  assert.match(manage, /Promise\.allSettled/);
  assert.match(manage, /PERFORMANCE_WRITE_STATUSES/);
  for (const status of ["SIGNED", "IN_PROGRESS", "RENEWAL_DUE", "COMPLETED"]) {
    assert.match(manage, new RegExp(`"${status}"`));
  }
  assert.match(manage, /관리할 계약/);
  assert.match(manage, /산출물 이행/);
  assert.match(manage, /광고 리포트/);
  assert.match(manage, /performance#obligation/);
  assert.match(manage, /performance#reports/);
  assert.match(manage, /산출물 확인하기/);
  assert.match(manage, /서명 완료 후 가능/);
  assert.match(contractPage, /backHref="\/manage"/);
  assert.match(contractPage, /dashboard\.contracts\.find/);
  assert.match(contractPage, /contract\.counterpartyName/);
});

test("develop-style comparison keeps independent left and right font controls", async () => {
  const viewer = await source("src/app/contracts/[id]/page.tsx");

  assert.match(viewer, /const \[fontScale, setFontScale\]/);
  assert.match(viewer, /const \[reqFontScale, setReqFontScale\]/);
  assert.match(viewer, /<FontScaleButtons onChange=\{setFontScale\}/);
  assert.match(viewer, /<FontScaleButtons onChange=\{setReqFontScale\}/);
  assert.match(viewer, /계약서 원문/);
  assert.match(viewer, /조정 요청 작성/);
  assert.match(viewer, /단디 설명 더 보기/);
  assert.match(viewer, /explainClauseMeaning\(clause\)/);
  assert.match(viewer, /이 조항의 의미/);
  assert.match(viewer, /내가 알고 있던 내용과 무엇이 다른가/);
  assert.match(viewer, /내가 답한 \{comparison\.label\}/);
  assert.match(viewer, /계약서 원문/);
  assert.match(viewer, /왜 확인이 필요한가/);
  assert.match(viewer, /확인 기준 · \{signal\.officialBasis\}/);
  assert.match(viewer, /understoodComparisonFor/);
  assert.match(viewer, /relatedSignals=\{related\}/);
  assert.match(viewer, /icon: "!"/);
  assert.match(viewer, /icon: "⋯"/);
  assert.match(viewer, /icon: "✓"/);
  assert.match(viewer, /aria-label="조항 메뉴 열기"/);
  assert.match(viewer, /\{menu\.icon\}/);
  assert.match(viewer, /fixed inset-0 z-40/);
  assert.doesNotMatch(viewer, /자동 비교에서 이 조항/);
  assert.match(viewer, /handleClauseAction/);
  assert.match(viewer, /Object\.keys\(drafts\)\.length === 0/);
  assert.match(viewer, /style=\{\{ fontSize: `\$\{reqFontScale\}rem` \}\}/);
});

test("live clause detail reuses the develop clause card without inventing source pages", async () => {
  const [page, card] = await Promise.all([
    source("src/app/contracts/[id]/clauses/[clauseId]/page.tsx"),
    source("src/components/ClauseCard.tsx"),
  ]);

  assert.match(page, /liveReviewItemToClause\(item\)/);
  assert.match(page, /<ClauseCard/);
  assert.match(card, /clause\.original\.page > 0/);
  assert.match(card, /① 원문 근거 미확인/);
});

test("live contract review keeps the five answers beside original-clause evidence", async () => {
  const [viewer, understood, viewModel] = await Promise.all([
    source("src/app/contracts/[id]/page.tsx"),
    source("src/lib/understood.ts"),
    source("src/lib/reviewViewModel.ts"),
  ]);

  assert.match(viewer, /adapter\.getLiveContractReview\(contractId\)/);
  assert.match(viewer, /from "@\/lib\/reviewViewModel"/);
  assert.match(viewer, /liveReviewToDashboard\(state\.data\)/);
  assert.match(viewer, /<ViewerBody/);
  assert.match(viewer, /내가 이해한 조건 요약/);
  for (const [key, label] of [
    ["durationText", "계약 기간"],
    ["monthlyAmount", "매달 내는 금액"],
    ["totalAmount", "총 계약금액"],
    ["refundText", "환불 조건"],
    ["terminationText", "중도 해지"],
  ]) {
    assert.match(viewModel, new RegExp(key));
    assert.match(understood, new RegExp(label));
  }
  assert.match(viewer, /계약서 원문/);
  assert.match(viewer, /조정 요청 작성/);
  assert.match(viewModel, /item\.sourceText/);
  assert.match(viewModel, /item\.sourcePage/);
  assert.match(viewModel, /item\.sourceConfidence/);
  assert.match(viewer, /persistReviewSelection\(c\.id, draft\.choice\)/);
  assert.match(viewer, /persistReviewSelection\(clauseId, choice\)/);
  assert.match(viewer, /await selectionQueue\.current/);
});

test("understood answers only compare against their structured extracted field", async () => {
  const [viewer, adapter, viewModel] = await Promise.all([
    source("src/app/contracts/[id]/page.tsx"),
    source("src/lib/adapter.ts"),
    source("src/lib/reviewViewModel.ts"),
  ]);

  assert.match(adapter, /related_extracted_term_ids/);
  assert.match(adapter, /extractedFieldById/);
  assert.match(viewModel, /UNDERSTOOD_KEY_BY_EXTRACTED_FIELD/);
  assert.match(viewModel, /item\.type !== "MISMATCH"/);
  assert.match(viewModel, /item\.relatedExtractedFields/);
  assert.match(viewer, /signal\.understoodKey/);
  assert.doesNotMatch(viewer, /signal\.title[^;]*clause\.body/);
  assert.doesNotMatch(viewer, /const candidates: Array<\[UnderstoodKey, RegExp\]>/);
});

test("public adjustment response renders the stored original clause text", async () => {
  const [adapter, landingPage, respondPage, types] = await Promise.all([
    source("src/lib/adapter.ts"),
    source("src/app/r/[token]/page.tsx"),
    source("src/app/r/[token]/respond/page.tsx"),
    source("src/lib/types.ts"),
  ]);

  assert.match(adapter, /before_text: string \| null/);
  assert.match(adapter, /source_page: number \| null/);
  assert.match(adapter, /beforeText: item\.before_text \?\? undefined/);
  assert.match(adapter, /sourcePage: item\.source_page \?\? undefined/);
  assert.match(landingPage, /item\.beforeText/);
  assert.match(landingPage, /원계약 해당 문구/);
  assert.match(landingPage, /원계약 \{item\.sourcePage\}쪽/);
  assert.match(landingPage, /item\.requestText/);
  assert.match(respondPage, /it\.beforeText/);
  assert.match(respondPage, /원본 계약서/);
  assert.match(types, /조정 요청과 직접 관련된 원계약 문구/);
  assert.doesNotMatch(adapter, /file_url[^]*ApiPublicAdjustment/);
});

test("live comparison shows every parsed clause on the left and selected requests on the right", async () => {
  const [viewer, request] = await Promise.all([
    source("src/app/contracts/[id]/page.tsx"),
    source("src/app/contracts/[id]/request/page.tsx"),
  ]);

  assert.match(viewer, /doc\.clauses\.map/);
  assert.match(viewer, /data\.clauses\.filter\(\(clause\) => drafts\[clause\.id\]\)/);
  assert.match(viewer, /왼쪽 원문에서 조항을 선택해주세요/);
  assert.match(viewer, /goToClause/);
  assert.match(viewer, /disabled=\{requestCount === 0\}/);
  assert.doesNotMatch(viewer, /requestCount > 4/);
  assert.doesNotMatch(viewer, /한 요청서에는 최대 4건만 담을 수 있어요/);
  assert.doesNotMatch(viewer, /<iframe/);
  assert.doesNotMatch(viewer, /contract-pdf-viewer/);
  assert.match(request, /const manualItems = Object\.entries\(draft \?\? \{\}\)/);
  assert.match(request, /return \[\.\.\.automaticItems, \.\.\.manualItems\]/);
});

test("live contract text decodes escaped quotation marks without rendering HTML", async () => {
  const [
    viewModel,
    textFormatter,
    revisionPage,
    landingPage,
    respondPage,
    performancePage,
  ] = await Promise.all([
    source("src/lib/reviewViewModel.ts"),
    source("src/lib/displayText.ts"),
    source("src/app/contracts/[id]/revision/page.tsx"),
    source("src/app/r/[token]/page.tsx"),
    source("src/app/r/[token]/respond/page.tsx"),
    source("src/app/contracts/[id]/performance/page.tsx"),
  ]);

  assert.match(textFormatter, /String\.fromCodePoint/);
  assert.match(textFormatter, /quot: '\"'/);
  assert.match(textFormatter, /pass < 2/);
  assert.match(viewModel, /displayText\(clause\.sourceText\)/);
  assert.match(viewModel, /displayText\(item\.sourceText\)/);
  assert.match(revisionPage, /displayText\(item\.sourceText\)/);
  assert.match(landingPage, /displayText\(item\.beforeText\)/);
  assert.match(respondPage, /displayText\(it\.beforeText\)/);
  assert.match(performancePage, /displayText\(candidate\.sourceText\)/);
  assert.match(performancePage, /displayText\(basis\.sourceText\)/);
  assert.match(performancePage, /displayText\(obligation\.sourceText\)/);
  for (const page of [viewModel, revisionPage, landingPage, respondPage, performancePage]) {
    assert.doesNotMatch(page, /dangerouslySetInnerHTML/);
  }
});

test("public adjustment links are restored, copied explicitly, and never auto-sent", async () => {
  const [requestPage, responsesPage, card, storage] = await Promise.all([
    source("src/app/contracts/[id]/request/page.tsx"),
    source("src/app/contracts/[id]/responses/page.tsx"),
    source("src/components/PublicLinkCard.tsx"),
    source("src/lib/publicLink.ts"),
  ]);

  assert.match(requestPage, /savePublicLink\(id, link\)/);
  assert.match(requestPage, /loadPublicLink\(id\)/);
  assert.match(responsesPage, /<SavedPublicLink/);
  assert.match(card, /onClick=\{\(\) => void copy\(\)\}/);
  assert.match(card, /navigator\.clipboard\.writeText\(url\)/);
  assert.match(card, /rel="noreferrer"/);
  assert.doesNotMatch(card, /useEffect\([^]*clipboard\.writeText/);
  assert.match(storage, /expiresAt <= Date\.now\(\)/);
  assert.match(storage, /parsed\.protocol === "http:"/);
  assert.doesNotMatch(requestPage, /fetch\([^]*sentLink/);
});

test("live adjustment responses keep the develop response dashboard layout", async () => {
  const responses = await source("src/app/contracts/[id]/responses/page.tsx");

  assert.match(responses, /function LiveResponseBody/);
  assert.match(responses, /응답 현황/);
  assert.match(responses, /역제안이 도착했어요/);
  assert.match(responses, /내 요청안/);
  assert.match(responses, /대행사 역제안/);
  assert.match(responses, /<ResolutionButtons/);
});
