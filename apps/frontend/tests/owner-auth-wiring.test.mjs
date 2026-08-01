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
  assert.match(apiAdapter, /this\.demoBearerToken \|\|/);
  assert.doesNotMatch(apiAdapter, /this\.demoBearerToken \?\?/);
  assert.doesNotMatch(apiAdapter, /(?<!await )this\.ownerHeaders\(\)/);
  assert.match(apiAdapter, /Authorization: `Bearer \$\{accessToken\}`/);
});

test("owners sign up and log in with Supabase email and password", async () => {
  const [signup, login, callback, passwordPolicy, authErrors] = await Promise.all([
    source("src/app/signup/page.tsx"),
    source("src/app/login/page.tsx"),
    source("src/app/auth/callback/route.ts"),
    source("src/lib/authPassword.ts"),
    source("src/lib/authErrors.ts"),
  ]);

  assert.match(signup, /auth\.signUp/);
  assert.match(signup, /email: email\.trim\(\)/);
  assert.match(signup, /password,/);
  assert.match(signup, /emailRedirectTo: callbackUrl\.toString\(\)/);
  assert.match(signup, /callbackUrl\.searchParams\.set\("flow", "signup"\)/);
  assert.match(login, /auth\.signInWithPassword/);
  assert.match(login, /email: email\.trim\(\)/);
  assert.match(login, /password,/);
  assert.doesNotMatch(`${signup}\n${login}`, /signInWithOtp|shouldCreateUser|localStorage/);
  assert.match(passwordPolicy, /PASSWORD_MIN_LENGTH = 8/);
  assert.match(signup, /getSignupErrorMessage\(authError\)/);
  assert.match(signup, /finally\s*\{\s*set(?:Submitting|Busy)\(false\)/);
  assert.match(authErrors, /over_email_send_rate_limit/);
  assert.match(authErrors, /user_already_exists/);
  assert.match(authErrors, /weak_password/);
  assert.match(authErrors, /error\?\.status === 429/);
  assert.doesNotMatch(signup, /console\./);
  assert.match(callback, /exchangeCodeForSession\(code\)/);
  assert.match(callback, /value\.startsWith\("\/\/"\)/);
  assert.match(callback, /"\/signup\?error=callback"/);
  assert.doesNotMatch(callback, /console\./);
});

test("password recovery sends a scoped email link and updates only an authenticated user", async () => {
  const [forgot, reset, callback] = await Promise.all([
    source("src/app/forgot-password/page.tsx"),
    source("src/app/reset-password/page.tsx"),
    source("src/app/auth/callback/route.ts"),
  ]);

  assert.match(forgot, /auth\.resetPasswordForEmail/);
  assert.match(forgot, /callbackUrl\.searchParams\.set\("flow", "recovery"\)/);
  assert.match(forgot, /redirectTo: callbackUrl\.toString\(\)/);
  assert.match(reset, /auth\.getSession\(\)/);
  assert.match(reset, /auth\.updateUser\(\{ password \}\)/);
  assert.match(callback, /"\/forgot-password\?error=callback"/);
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

test("owner route guard follows Supabase sessions without restoring mock password auth", async () => {
  const [guard, useSession, demoAuth] = await Promise.all([
    source("src/components/RequireAuth.tsx"),
    source("src/lib/useSession.ts"),
    source("src/lib/auth.ts"),
  ]);

  assert.match(guard, /useSession\(\)/);
  assert.match(guard, /useSyncExternalStore\(/);
  assert.match(guard, /isPreviewBypass,/);
  assert.match(guard, /getServerPreview/);
  assert.match(useSession, /supabase\.auth\.getSession\(\)/);
  assert.match(useSession, /supabase\.auth\.onAuthStateChange/);
  assert.match(useSession, /isUsingMock/);
  assert.match(useSession, /isUsingDemoOwnerToken/);
  assert.doesNotMatch(demoAuth, /password|dandi:users|signUp|signIn\(/i);
});

test("login and public landing expose the real signup path", async () => {
  const [login, landing] = await Promise.all([
    source("src/app/login/page.tsx"),
    source("src/app/page.tsx"),
  ]);

  assert.match(login, /`\/signup\?next=\$\{encodeURIComponent\(next(?:Path)?\)\}`/);
  assert.match(login, /href=\{signupHref\}/);
  assert.match(landing, /href="\/signup"/);
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
