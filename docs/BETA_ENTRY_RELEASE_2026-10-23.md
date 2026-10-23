# Beta landing and account entry

## Delivered behavior

- `/beta` is a shareable landing/signup entry. New configured visitors at `/` also see it; existing app/local users keep their normal entry.
- `/preview/landing` is a non-authenticating design replay, including install instructions. It never sends emails or initializes an account.
- Email signup/sign-in uses the existing Supabase boundary. Landing requests use the same-origin `/?welcome=1` callback. Existing Settings sign-in keeps its original redirect behavior.
- Email/code form state survives loading, provider errors and retries. The installed app can accept an email code without following a browser link.
- Successful sign-in shows home-screen instructions for iPhone/iPad, Android and computer, with an optional browser continuation.
- “Open Threadline” reads an existing account or inserts an empty account with the existing ownership/revision guards. It never imports local content or the demo seed. A concurrent creator wins; the losing attempt reads the winner, never overwrites it.
- An authenticated fresh root/standalone window with no account row is routed to setup even without a browser onboarding marker. Existing local records, including malformed records, retain their recovery route.
- Only a versioned navigation marker is stored for signup resumption; no email, token or workspace is stored by the onboarding UI.

## Verification

- Full check: 113 suites / 1,063 tests, production build and API typecheck passed. No configured lint. Existing large-bundle warning remains.
- Independent reviewer: `/root/mobile_polish_review`, approved after fixing the authenticated-root/empty-account handoff; 91 focused tests / 8 suites.
- Actual App hook-render tests exercise signup loading/error continuity, authenticated root without marker, explicit blank-account opening, and preservation of malformed local records.
- Synthetic component tests exercise email/code retention, preview non-mutation and opening failure/retry. Account tests cover initialization, existing data, concurrent insertion, failed/corrupt reads, wrong owner and sign-out.
- Browser: desktop and 390px viewport landing/setup inspected; join anchor, preview setup and device instruction switching exercised. No horizontal overflow on setup. No real account writes or emails sent.

## Required before inviting external testers

1. Confirm the Threadline Supabase project `leivyuqzojaxenumyasw` permits new email signups and uses an email sender that can deliver to arbitrary tester addresses. Old September notes reported built-in sender limitations; current settings remain unverified because the admin browser is signed out.
2. Confirm Site URL uses the intended stable app origin. Allow the exact production callback `https://working-ten-rust.vercel.app/?welcome=1` and retain existing legitimate callbacks. A new custom domain needs matching auth configuration; installing on different origins creates separate browser storage.
3. Confirm the email template contains both the one-time code and browser confirmation link. Verify one fresh tester mailbox through each path; never put codes or tokens in reports.
4. On a physical phone: signup → instructions → Add to Home Screen → launch → sign in again if needed using a fresh code → Open Threadline → capture → sign in on laptop → same capture. Testers should use nonsensitive data.
5. Review/publish the approved branch to the current Vercel `working` project. The legacy zippy project's GitHub deployment status is not proof of deployment to `working-ten-rust.vercel.app`.

This is a web-app beta, not an Apple TestFlight binary. No domain purchase, production auth setting, email sender, database policy, Factory component, or real capture data was changed. Physical keyboard, native install and email delivery are not claimed verified by synthetic tests. Feedback currently goes back to the person who invited the tester; no new feedback backend was added.

## Immersive nature follow-up

Owner's October 23 screen recording established a full-screen photographic scene and floating glass-like wordmark as the visual direction, beyond the earlier palette-only revision. The new `BetaSkyHero` is decorative and isolated from authentication. Signup is available immediately. The scene uses a short, finite transform animation (at most 4.5 seconds), disabled under reduced motion; no video, WebGL, timers or scroll listeners were added. Existing signed-in installation instructions do not load the hero image.

The original background asset is `public/images/beta-alpine-sky.jpg` (about 321 KB), generated with the built-in image-generation tool and compressed for the page. The reference website's assets and logo were not copied. Final generation prompt:

> Use case: photorealistic-natural. Asset type: original full-bleed background photograph for Threadline's immersive landing page. Generate a landscape 1536x1024 image, no text or logos. A luminous alpine blue sky with soft three-dimensional white cumulus clouds drifting around the outer edges, large serene open sky in the middle for a live glass wordmark. At the very bottom edge, subtle distant green alpine meadow ridgeline and pine silhouettes, with warm pale yellow-green sunlight. Fresh saturated sky blue, mist white, meadow green, pine green. Dreamy but genuinely photographic, delicate atmospheric depth, no heavy vignette. Clouds have beautiful light and detail but not stormy. Keep central 60 percent mostly open blue sky; preserve a beautiful centered crop for portrait mobile. No UI, no typography, no watermarks. This is a background asset, not a website screenshot.

Tests cover one meaningful heading, immediate signup and story anchors, decorative media semantics, absence of the scene in signed-in setup, safe preview labels, reduced-motion CSS, finite motion and a 400 KB image budget. Physical-phone frame-rate and external signup checks remain unverified.

## Reference documentation

- [Supabase passwordless signup and email codes](https://supabase.com/docs/guides/auth/auth-email-passwordless)
- [Apple: turn a website into an app](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios)
- [Chrome: use web apps](https://support.google.com/chrome/answer/9658361)
