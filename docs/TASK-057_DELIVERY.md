# TASK-057 Delivery — Installed-app email code login

## Result

Threadline's existing email request now supports two explicit sign-in paths from the same
message:

- the existing confirmation link continues to sign a user into the browser that opens it;
- a six-digit email code can be entered inside the installed home-screen app, creating the
  session in that app's own storage context.

The code input is labelled and uses numeric input, `one-time-code` autofill, a six-digit
pattern and a six-character limit. Threadline remains signed out when a code is malformed,
expired, rejected, or accepted without a session. Provider errors are not shown to the user.
This task does not read, migrate, clear or otherwise change local or account data.

## Required Supabase email-template update

After this code is independently reviewed, update the **Magic Link** email template in the
existing Threadline Supabase project to include both `{{ .Token }}` and
`{{ .ConfirmationURL }}`. Use this exact body:

```html
<h2>Sign in to Threadline</h2>
<p>Enter this code in the Threadline app:</p>
<p style="font-size: 28px; font-weight: 700; letter-spacing: 0.18em;">{{ .Token }}</p>
<p>Or use this link to sign in in your browser:</p>
<p><a href="{{ .ConfirmationURL }}">Sign in to Threadline</a></p>
<p>If you did not request this email, you can ignore it.</p>
```

Do not replace the template before the reviewed application change is ready for a Preview;
the current production UI does not yet offer code entry. Do not place a real address, project
identifier, browser key, service-role key or provider response in the template or repository.

## Validation

- Focused auth tests cover request options, provider code verification, malformed codes,
  rejected codes, a missing provider session and successful sign-in.
- `pnpm check` passed with 409 tests across 22 files, app and API TypeScript checks, and the
  production build. `git diff --check` passed. The existing nonblocking bundle-size warning
  remains.
- Mobile/desktop browser smoke testing and independent review remain required before merge.
- Preview validation requires a real email: request one message, confirm that it contains both
  choices, enter its code in the installed PWA, verify the PWA reports signed in, then sign out.
  Confirm separately that the link still signs in to the browser.

## Scope and limitations

- This is an authentication-session fix only. It does not activate account storage, import
  local data or imply cross-device synchronization.
- Email delivery, code expiry and rate limits remain controlled by Supabase.
- A browser link cannot reliably transfer its session into an iOS home-screen PWA; code entry
  is the supported installed-app path.
- The Supabase template change and real-device validation remain dashboard/deployment actions
  after code review. No production configuration or app deployment is included here.

## Build-in-public note

Threadline's installed phone app can now sign in with a six-digit code from the same email that
still supports browser sign-in. Account data remains untouched until the user explicitly
chooses the existing account-storage controls.

## Exact response to move forward

Independently review TASK-057, run the complete check, then update the Supabase Magic Link
template with the reviewed dual code/link body and validate both paths on a Preview before
production promotion.
