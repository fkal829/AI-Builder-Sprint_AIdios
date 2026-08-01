"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import {
  getSupabasePublicConfig,
  isSupabaseAuthConfigured,
} from "./config";

let browserClient: SupabaseClient | undefined;

export { isSupabaseAuthConfigured };

export function getSupabaseBrowserClient(): SupabaseClient {
  if (!browserClient) {
    const { url, publishableKey } = getSupabasePublicConfig();
    browserClient = createBrowserClient(url, publishableKey);
  }
  return browserClient;
}

export async function getOwnerAccessToken(): Promise<string | null> {
  if (!isSupabaseAuthConfigured()) return null;

  const { data, error } = await getSupabaseBrowserClient().auth.getSession();
  if (error) return null;
  return data.session?.access_token ?? null;
}
