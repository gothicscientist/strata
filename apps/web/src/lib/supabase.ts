"use client";

import type { SupabaseClient } from "@supabase/supabase-js";

const URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const supabaseConfigured = URL.length > 0 && KEY.length > 0;

let client: Promise<SupabaseClient> | null = null;

/** Lazily load supabase-js only when auth is configured, keeping guest-only builds small. */
export function getSupabase(): Promise<SupabaseClient> | null {
  if (!supabaseConfigured) return null;
  client ??= import("@supabase/supabase-js").then(({ createClient }) =>
    createClient(URL, KEY, { auth: { persistSession: true, detectSessionInUrl: true } }),
  );
  return client;
}
