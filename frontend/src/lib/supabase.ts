import { createClient, type SupabaseClient } from '@supabase/supabase-js'

// Public values: the publishable key only identifies the project to Supabase Auth.
// Newsforge data is never read through Supabase's Data API (those tables are locked down).
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined

/** null when the app is built without Supabase: it then falls back to API-key sign-in. */
export const supabase: SupabaseClient | null =
  url && publishableKey
    ? createClient(url, publishableKey, {
        auth: { flowType: 'pkce', persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
      })
    : null

export const authMode: 'accounts' | 'apikey' = supabase ? 'accounts' : 'apikey'

/** Where Supabase email links (confirm sign-up, reset password) send people back to. */
export const appUrl = () => window.location.origin
