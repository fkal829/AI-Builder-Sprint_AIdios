import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the product landing page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>안심홍보계약<\/title>/i);
  assert.match(html, /읽지 못한 계약을 읽어주고/);
  assert.match(html, /계약 검토 시작/);
});

test("keeps owner and public routes separated", async () => {
  const [ownerLayout, adjustmentPage, obligationPage, apiClient] =
    await Promise.all([
      readFile(new URL("../app/(owner)/layout.tsx", import.meta.url), "utf8"),
      readFile(
        new URL(
          "../app/public/adjustment-requests/[token]/page.tsx",
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL("../app/public/obligations/[token]/page.tsx", import.meta.url),
        "utf8",
      ),
      readFile(new URL("../lib/api/client.ts", import.meta.url), "utf8"),
    ]);

  assert.match(ownerLayout, /대시보드/);
  assert.match(adjustmentPage, /수락·거절·역제안/);
  assert.match(obligationPage, /산출물 URL/);
  assert.match(apiClient, /NEXT_PUBLIC_API_BASE_URL/);
});
