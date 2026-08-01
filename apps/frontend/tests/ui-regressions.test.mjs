import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (relativePath) =>
  readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("owner navigation keeps obligation and performance adjacent on a valid route", async () => {
  const header = await source("src/components/SiteHeader.tsx");
  const obligationIndex = header.indexOf('key: "obligations"');
  const performanceIndex = header.indexOf('key: "performance"');
  const renewalIndex = header.indexOf('key: "renewal"');

  assert.ok(obligationIndex < performanceIndex);
  assert.ok(performanceIndex < renewalIndex);
  assert.match(header, /href: `\/contracts\/\$\{DEMO_CONTRACT_ID\}\/performance`/);
  assert.match(header, /pathname\.includes\("\/performance"\)/);
  assert.doesNotMatch(header, /href: "\/performance"/);
});

test("request editor exposes independent font controls and matching evidence signal", async () => {
  const viewer = await source("src/app/contracts/[id]/page.tsx");

  assert.match(viewer, /const \[reqFontScale, setReqFontScale\]/);
  assert.match(viewer, /<FontScaleButtons onChange=\{setFontScale\}/);
  assert.match(viewer, /<FontScaleButtons onChange=\{setReqFontScale\}/);
  assert.match(viewer, /CLAUSE_MENU_STYLE\.unconfirmed\.bg/);
  assert.match(viewer, /style=\{\{ fontSize: `\$\{reqFontScale\}rem` \}\}/);
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
