const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabasePublishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export function isSupabaseAuthConfigured(): boolean {
  return Boolean(supabaseUrl && supabasePublishableKey);
}

export function getSupabasePublicConfig(): {
  url: string;
  publishableKey: string;
} {
  if (!supabaseUrl || !supabasePublishableKey) {
    throw new Error("Supabase Auth 공개 설정이 필요합니다.");
  }

  return { url: supabaseUrl, publishableKey: supabasePublishableKey };
}
