Read README.md first. It covers the file map, local server, DWG builds, plan versions, editing, photo spots and deploy.
Before changing a plan drawing (DWG/DXF), read DWG_EDITING.md.

Rules worth repeating:
- Dimensions come only from the DWG. Never regenerate main `model.js` / `drawing.json` unasked.
- A plan version may differ from Main only in the rooms it changes. Flag any other DWG difference.
- Client decisions in README §5 override the designer's renders.
- Don't spend OpenAI or Meshy credits unprompted. Test Generate Photo Spot with `python3 photogen.py --dry-run`.
- Answer drawing questions with a marked-up crop from `dwgtool.py render`, sizes in cm. Quick dimension questions get numbers only.
- Keep everything in `index.html`: no side pages or experiment folders.
- **Quick changes vs big jobs.** An easy one-piece tweak (e.g. swap a mirror for a medicine cabinet, nudge a nightstand, change a finish) → edit `furnish.js` directly, and if the piece is drawn on the plan, the matching `2furni` outline in that version's DXF. Run `check_furnish.py` for the version(s) you touched. Do **not** spin up a full multi-file rebuild / screenshot / report session for that. Save the heavy pass for real layout changes (walls, doors, room moves, new rooms).
- **Headless tests must not hang.** Every `node` / puppeteer / chrome / `http.server` test goes under `timeout` (≤90 s for a single case, ≤3 min for a whole suite). Prefer `waitUntil: "domcontentloaded"` (never `networkidle`). If SwiftShader is slow or a test flakes, **stop after one attempt**, write what passed/failed in REPORT.md, and finish the job — do **not** re-run, resume, or sit waiting on a test. Never leave a background test with no timeout.
- Git commit/push, Vercel env writes and Blob uploads are blocked for Claude here. Hand the user a one-line command instead.
- **Live Edit AI edits are Karim's work, often in Blob only** (Vercel has no `EDIT_AI_GITHUB_TOKEN`, so they never reach git by themselves). Before committing anything that touches `furnish.js`, `materials.js`, a tour or a plan version, run `python3 edit_ai_pull.py <version>` (or no args for all), check `git diff`, and commit those edits with yours. **Never `POST /api/edit-ai/reset`** to make a push show up: a pushed file is merged under the live edit automatically, and reset now refuses while live edits remain. On 25 Oct 2026 two resets (18:37 and 18:49 Cairo) wiped the porcelain vanity, fold-down desks, bronze wardrobe glass and more.
