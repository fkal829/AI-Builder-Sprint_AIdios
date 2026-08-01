import { NextResponse } from "next/server";
import { getSupabaseServerClient } from "@/lib/supabase/server";

function safeNextPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/dashboard";
  }
  return value;
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");

  if (code) {
    try {
      const supabase = await getSupabaseServerClient();
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error) {
        return NextResponse.redirect(
          new URL(safeNextPath(url.searchParams.get("next")), url.origin),
        );
      }
    } catch {
      // 설정 오류와 인증 실패를 외부 응답에서 구분하지 않는다.
    }
  }

  const flow = url.searchParams.get("flow");
  const errorPath = flow === "signup"
    ? "/signup?error=callback"
    : flow === "recovery"
      ? "/forgot-password?error=callback"
      : "/login?error=callback";
  return NextResponse.redirect(new URL(errorPath, url.origin));
}
