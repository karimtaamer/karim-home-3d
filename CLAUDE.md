Read README.md first. It covers the file map, local server, DWG builds, plan versions, editing, photo spots and deploy.

Rules worth repeating:
- Dimensions come only from the DWG. Never regenerate main `model.js` / `drawing.json` unasked.
- A plan version may differ from Main only in the rooms it changes. Flag any other DWG difference.
- Client decisions in README §5 override the designer's renders.
- Don't spend OpenAI or Meshy credits unprompted. Test Generate Photo Spot with `python3 photogen.py --dry-run`.
- Keep everything in `index.html`: no side pages or experiment folders.
- Git commit/push, Vercel env writes and Blob uploads are blocked for Claude here. Hand the user a one-line command instead.
