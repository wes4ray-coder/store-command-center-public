# TODO List

- [ ] **Analysis**
    - [ ] Identify navigation handler script (likely in `lib-core.js` or `index.html`).
    - [ ] Check `dashboard_views.js` for syntax errors preventing registration of render functions.
    - [ ] Verify how `data-view` attributes are mapped to function calls.

- [ ] **Fixes - Store UI**
    - [ ] Fix navigation mapping for: `image-gen`, `videos`, `cults3d`, `resell`, `library`.
    - [ ] Ensure `renderEtsyPrintify` is correctly mapped (it seems to be defined but check).
    - [ ] Verify `renderNetworkSecurity` (Pihole) logic.

- [ ] **Fixes - Settings & Security**
    - [ ] Locate "Security" setting in Settings.
    - [ ] Remove/Correct the Pihole-related security context from this setting.

- [ ] **Fixes - AI Assistant**
    - [ ] Investigate "Received message is corrupt" error.
    - [ ] Check logs or API responses for the assistant tab.

- [ ] **Cleanup**
    - [ ] Verify all tabs render correctly in the UI.
    - [ ] Update `GOAL.md` and `TODO.md` as tasks complete.
