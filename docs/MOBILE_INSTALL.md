# Installing Threadline on a Phone

Threadline is a standards-based installable web app (PWA). It has no native
app store listing; it is installed straight from the browser.

## Requirements

- Threadline must be served over HTTPS (or `localhost` during development).
  Browsers refuse to install a manifest or register a service worker over
  plain HTTP.
- The site must serve `index.html`, `manifest.webmanifest`, and `sw.js` from
  the same origin, unmodified by the host (no HTML injection, no stripped
  headers).

## iPhone (Safari)

1. Open the Threadline URL in **Safari**. Modern third-party iOS browsers may
   also offer Add to Home Screen, but Safari is the simplest documented path.
2. Tap the **Share** icon (square with an upward arrow), which may be inside
   the **More** menu depending on your Safari layout.
3. Scroll down and tap **Add to Home Screen**.
4. Confirm the name (defaults to "Threadline"). If **Open as Web App** is shown,
   leave it on, then tap **Add**.
5. Threadline now launches from the home screen icon in standalone mode (no
   Safari address bar or browser chrome), using the theme and background
   colors declared in `manifest.webmanifest`.

To remove it later, long-press the home screen icon and choose **Remove App**
like any other app.

## Android (Chrome)

1. Open the Threadline URL in Chrome.
2. Chrome may show an **Install app** prompt automatically; otherwise open
   the **⋮** menu and choose **Install app** (or **Add to Home screen**).
3. Confirm the install. Threadline opens in standalone mode from the app
   drawer/home screen.

## Desktop (Chrome, Edge)

Look for the install icon in the address bar, or use the browser menu's
**Install Threadline...** option.

## What "installable" gives you here

- A home-screen/app-launcher icon and standalone window (no browser chrome),
  per `manifest.webmanifest` (`display: "standalone"`).
- A minimal same-origin service worker (`public/sw.js`) that lets the app
  shell keep working if the network drops after at least one successful
  visit. It only caches successful, same-origin `GET` responses; it never
  caches API calls, cross-origin requests, or failed responses, and it never
  reads or writes `localStorage` — Threadline's saved captures and canvas
  state are untouched by installation or offline mode.
- HTML is always requested fresh from the network first when online, so an
  installed app never gets stuck showing a stale version indefinitely; the
  cached shell is only served as a fallback when the device is offline.

## What this does **not** include: push notifications

Threadline does **not** implement push notifications. Installing the app to
a home screen does not enable reminders, morning digest delivery, or any
other notification. There is no notification prompt in the app, and none
should appear — implementing one without the required delivery mechanism
would create fake or non-functional notifications.

Real push notifications require, at minimum, all of the following, none of
which exist yet:

1. A `Notification`/`PushManager` permission request and subscription flow
   in the client.
2. A server-side endpoint to store push subscriptions per user/device.
3. A server-side scheduler that decides when a reminder, commitment, or the
   7 AM morning digest (see `docs/NORTH_STAR.md`) is due.
4. A server-side sender that pushes to the browser's push service (e.g. via
   Web Push/VAPID) so the service worker can display the notification even
   when the app is closed.

This is future, separately scoped work — see `docs/ARCHITECTURE.md`'s
Reminder instruction entity and `docs/NORTH_STAR.md`'s Morning Digest
section for the product requirements it would need to satisfy. It is not
part of this installability task.

## App icons

The manifest and HTML include 192×192 and 512×512 PNG app icons plus a
180×180 Apple touch icon. The maskable declaration uses the 512×512 asset,
whose mark stays inside the central safe area.

## In-app guidance (TASK-039)

A compact, nonmodal guide appears on the first browser visit at a viewport width
of 720px or less. It introduces Capture and Organize and provides expandable
home-screen instructions. Desktop and already-standalone launches skip the
automatic guide (including Safari's legacy standalone signal).

**Dismiss install help** remembers the choice in this browser using a separate
`threadline-mobile-install-v1` preference. If storage is blocked, dismissal still
works for the visit and a message explains that it may return on reload. Unknown
preference values show help without rewriting data. No profile schema migration
is needed. A full export includes the preference; confirmed Clear local data
removes it. Reset local profile leaves this preference alone.

On any device, open **Settings → Mobile install → Show home screen install help**
to reopen it. Keyboard focus moves to the guide heading and returns to the
Settings button when dismissed. Installation is manual; the app does not infer
that installation succeeded or request notification permission.

The layout uses the browser's safe-area insets in both browser and standalone
modes, including sticky navigation, canvas controls, object-panel overlays and
storage recovery screens. Zero insets preserve normal desktop spacing.

Safari steps follow [Apple's iPhone web-app guide](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios).
Labels and menu placement can vary by iOS version.

### Device smoke checks for review

- At 320px and 390px widths, expand the guide, dismiss, reload, and reopen from
  Settings. Confirm Capture and Organize remain reachable.
- On a real iPhone, repeat in Safari and from the home-screen icon, in portrait
  and landscape. Check navigation after scrolling, canvas tools and the object
  panel close control against the camera/Dynamic Island and home indicator.
- At desktop width, confirm no automatic guide and that Settings can open and
  dismiss it using keyboard navigation.
- With preference writes blocked, confirm dismissal closes the guide and shows
  the persistence warning without interrupting capture.

Real-device installation and physical safe-area checks remain required; unit
checks of preference behavior do not validate Safari rendering or OS install UI.
