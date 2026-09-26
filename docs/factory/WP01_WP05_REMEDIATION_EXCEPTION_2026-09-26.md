# WP-01 / WP-05 remediation exception — 2026-09-26

The product owner explicitly directed the Factory to fix the independently reviewed WP-01 and WP-05 failures before continuing product work.

The WP-01 failure could not be corrected without changing `src/App.tsx`: WP-11's current surface registry describes URL, identity, and persistence metadata, but it has no component-rendering slot for the existing in-app Organize view. The unreachable duplicate Review implementation therefore had to be removed and its resolution control mounted in the existing Organize component.

This record authorizes that narrow remediation exception only:

- mount the WP-01 resolution control in the existing Organize/Review view;
- remove the unreachable duplicate Review surface;
- preserve WP-11's route registry and all unrelated application-shell behavior;
- restore WP-05's Canvas exit callback;
- add focused regression coverage for the integrated Review and Canvas shells.

It does not relax the general single-writer rule for `src/App.tsx`, authorize unrelated shell changes, merge the work, or replace the independent exact-commit review requirement.

A separate WP-11 follow-up should add a typed render/composition boundary before another feature package needs to mount a new in-app surface without editing `src/App.tsx`.
