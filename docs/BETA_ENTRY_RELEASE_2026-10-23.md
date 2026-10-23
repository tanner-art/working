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

## Cloud-to-ground journey follow-up

This supersedes the finite opening animation described above. The landing page now follows native scrolling from a cloud-framed sky and glass wordmark through a mountain horizon to a tree-left meadow with grass/soil occupying approximately the bottom fifth of the final scene. The product mockup, feature grid, repeated story sections and long FAQ were removed; essential beta/privacy information remains in one disclosure beside the signup flow. Authentication, account persistence and signed-in installation behavior are unchanged.

Motion is driven by passive scroll/resize events, coalesced into at most one pending animation frame, with cleanup on unmount. It updates CSS transforms/opacity without React rerenders, a perpetual animation loop, scroll hijacking, video, WebGL or new dependencies. Reduced motion uses a static landscape. Decorative overflow is clipped on the chapter layer without creating a scroll container that breaks the sticky scene. Forced-colors mode removes decorative art and restores system text/link colors.

Verification: 116 suites / 1,074 tests, production build and API typecheck passed. Independent reviewer `/root/mobile_polish_review` approved with no remaining blockers after mobile overflow correction. Desktop and 390×844 screenshots inspected; 390×500 short-viewport preview signup successfully opens the installation instructions. These are synthetic viewport tests, not a physical keyboard or phone frame-rate measurement. Ground and cloud assets together with the original sky total less than 1.5 MB. Existing large application-bundle warning remains.

Additional generated assets, optimized from built-in image generation (no third-party reference assets copied):

- `public/images/beta-grounded-meadow.jpg` (~425 KB). Prompt: “Use case: photorealistic-natural. Asset type: full-screen final ground scene for a scroll-driven Threadline landing page, landscape 1536x1024. Original cinematic photograph with a clear luminous alpine blue sky occupying the TOP 75 PERCENT of the image. A distant pale blue-gray alpine mountain peak and subtle mountain range confined around 70-85 percent down the image, atmospheric and soft. A single graceful leafy green deciduous tree at x=20 percent, rooted in the meadow, canopy extends upward to around 45 percent image height; tree must fit fully in image. Foreground is a narrow horizontal strip of vivid fresh grass beginning at y=85 percent, and a beautifully detailed natural dark brown soil cross-section at the very bottom y=93-100 percent, a few fine roots visible beneath turf. STRICT COMPOSITION: ground/grass/soil occupies only bottom 15 percent. Sky remains vast, bright and mostly clear, a few delicate clouds top left and top right. Calm golden late-morning sunlight from upper left. Sophisticated believable natural photography, not illustration or cartoon. No people, buildings, roads, typography, logos, UI or watermark. The center area at x=35-75 percent and y=20-70 percent must be uncluttered open pale blue sky for live text and a signup form. Warm sunlit meadow green, pine shade, mist white, alpine blue.”
- `public/images/beta-cloud-layer.png` (~599 KB, transparent). Prompt: “Use case: photorealistic-natural. Asset type: transparent foreground cloud layer for a premium scroll-driven website. Generate a wide 1536x1024 PNG with genuinely transparent background and soft semitransparent feathered edges. Two luminous realistic white cumulus cloud banks entering from the left edge and right edge and a soft thin mist along the lower edge, leaving a very large clear transparent opening across the central half for a wordmark. Sunlight from upper left, fine realistic vapor detail, delicate cool pale-blue shadows, airy rather than stormy. Clouds occupy at most 35 percent of canvas; avoid opaque uniform fog. No sky or background color, no ground, no mountains, no text, no frame, no logos.”

## Reference documentation

- [Supabase passwordless signup and email codes](https://supabase.com/docs/guides/auth/auth-email-passwordless)
- [Apple: turn a website into an app](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios)
- [Chrome: use web apps](https://support.google.com/chrome/answer/9658361)
