import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (relativePath) =>
  readFile(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("owner requests resolve a current Supabase session token", async () => {
  const [adapter, client] = await Promise.all([
    source("src/lib/adapter.ts"),
    source("src/lib/supabase/client.ts"),
  ]);
  const apiAdapter = adapter.slice(adapter.indexOf("class ApiAdapter"));

  assert.match(client, /auth\.getSession\(\)/);
  assert.match(client, /session\?\.access_token/);
  assert.match(apiAdapter, /await this\.ownerAccessTokenProvider\(\)/);
  assert.doesNotMatch(apiAdapter, /(?<!await )this\.ownerHeaders\(\)/);
  assert.match(apiAdapter, /Authorization: `Bearer \$\{accessToken\}`/);
});

test("email login uses an explicit PKCE callback and does not create users", async () => {
  const [login, callback] = await Promise.all([
    source("src/app/login/page.tsx"),
    source("src/app/auth/callback/route.ts"),
  ]);

  assert.match(login, /auth\.signInWithOtp/);
  assert.match(login, /emailRedirectTo: callbackUrl\.toString\(\)/);
  assert.match(login, /shouldCreateUser: false/);
  assert.match(callback, /exchangeCodeForSession\(code\)/);
  assert.match(callback, /value\.startsWith\("\/\/"\)/);
  assert.doesNotMatch(callback, /console\./);
});

test("logout only runs from the explicit header control", async () => {
  const authControl = await source("src/components/AuthControl.tsx");

  assert.match(authControl, /onClick=\{handleSignOut\}/);
  assert.match(authControl, /auth\.signOut\(\)/);
  assert.doesNotMatch(
    authControl,
    /useEffect\(\(\) => \{\s*void getSupabaseBrowserClient\(\)\.auth\.signOut/,
  );
});

test("dashboard authentication failures offer a login recovery path", async () => {
  const dashboard = await source("src/app/dashboard/page.tsx");

  assert.match(dashboard, /state\.status === "error"/);
  assert.match(dashboard, /href="\/login"/);
  assert.match(dashboard, /로그인 다시 하기/);
});

test("frontend configuration never accepts a service-role secret", async () => {
  const [config, envExample] = await Promise.all([
    source("src/lib/supabase/config.ts"),
    source(".env.example"),
  ]);
  const executableConfig = config
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");

  assert.match(executableConfig, /NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY/);
  assert.doesNotMatch(executableConfig, /SERVICE_ROLE|SECRET_KEY/);
  assert.doesNotMatch(envExample, /NEXT_PUBLIC_SUPABASE_SERVICE_ROLE/);
});
