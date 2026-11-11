---
name: chatgpt-render-kit
description: Build a ready-to-paste ChatGPT (or any image model) render kit from a floor plan, so the render matches the real plan's layout, proportions, fixture positions, door swings and finishes. Produces a clean dimensioned plan image, a style reference, an optional marked-up reference, one main prompt and two follow-up prompts. The user runs the render in ChatGPT; never generate it yourself unless asked. Use when the user says "ChatGPT render", "render kit", "prompt for ChatGPT", "make a render prompt from the plan", "visualise this room in ChatGPT", or asks for images to paste into an image model for a specific room or plan version.
---

# ChatGPT render kit from a floor plan

Goal: give the user everything to paste into ChatGPT (or any image model) so the render matches the actual plan: correct layout, proportions, fixture positions, door swings and finishes. Never generate the render yourself unless asked; the user runs it in ChatGPT.

## Inputs to gather
- The plan source: DWG/DXF (convert with ODA + ezdxf if needed) or a PDF/image. Always work on copies; never modify the original file.
- Which space and which version/proposal is being visualized.
- Existing renders or photos of the project (e.g. a "Final renders" page or folder) to use as the style/finish reference.
- Any finishes the user has already chosen (tiles, colours, fixtures, wood). Don't invent finishes you can't see; mark any guess as a guess.

## Steps
1. **Plan reference image.** Render a clean, cropped plan of only the target space from the real geometry:
   - Big readable dimensions in cm (overall size, each zone, openings).
   - Simple labels for every element (bed, wardrobe, WC, shower, vanity, window, door, etc.).
   - Door swings and window positions clearly shown.
   - No clutter: hide unrelated layers, show at most a hint of the adjoining rooms.
   - Present proposals as one clean plan (no 'new/removed' or before/after labels).
   - Check the image by eye before using it.
2. **Style reference.** Pick the existing render/photo that best shows this space or the project's finishes. Say which one and what finishes it shows. If none shows this space, pick the best overall style match and say so.
3. **Optional marked-up reference.** If an existing render shows the same space from a usable angle, mark on a copy what changes (walls moved, door added, etc.) so the model can edit it rather than invent.
4. **Main prompt** (English, one block, ready to paste), including:
   - What to make: a photorealistic interior render, eye-level, of this exact space.
   - "Match the attached plan's layout and proportions exactly."
   - The real dimensions in cm: overall size, zones, each fixture/furniture size and position relative to walls, window and door positions and swing direction, ceiling height (state it, or say 'assume ~280 cm').
   - Finishes taken from the style reference (materials, colours, lighting style).
   - Camera: where it stands and what it looks toward (e.g. in the doorway looking toward the window), lens (about 24 mm, no fisheye).
   - Lighting and time of day.
   - Guardrails: "Do not add, remove or move fixtures or furniture; keep the proportions; no extra windows or doors; no text in the image."
   - Which images to attach and in what order (plan first, then style reference).
5. **Two follow-up prompts**: one for another camera angle, one for a variation (e.g. a different finish or lighting), each reminding the model to keep the same layout.
6. **Deliver:** send the plan image and the reference image(s) as images, then the prompt in a code block for easy copying, then the follow-ups. Add a note that the render is a visual aid only; dimensions must be verified on site.

## Quality checks
- Every dimension in the prompt comes from the real geometry, not estimates.
- The plan image and the prompt agree (same numbers, same labels).
- Fixture positions are described relative to named walls (window wall, door wall), not just left/right.
- No changes to original files; new outputs get clear new names.

## In this repo
- **Plan source:** each version's DXF in `dwg/` (Main = `dwg/kareems-changes.dxf`; see README §4 for the others). No conversion needed. Render crops with `~/.dwg-tools/bin/python dwgtool.py render <dxf> --bbox x1,y1,x2,y2 --layers ... --note ... -o out.png` (DWG metres; see `DWG_EDITING.md` §1). Write outputs to `/tmp` or another scratch folder, never into `dwg/`.
- **Furniture sizes and positions** that the DXF doesn't draw (curtains, pockets, built-ins) live in the version's `furnish-<version>.js`; quote those numbers, converted to cm.
- **Ceiling height:** 260 cm (fixed in `build_geometry.py`); window sill 90 cm, door head 210 cm, slider head 240 cm unless the version overrides one.
- **Style references:** the designer's renders and approved AI renders listed in that version's `spots-<version>.json` (files in `renders/`, served from Blob live); finishes text in `photogen-brief.json`. Client decisions in README §5 override the renders.
- **Credits:** this kit spends nothing. The in-app Generate Photo Spot (`photogen.py`, OpenAI) does; don't run it unprompted (test with `python3 photogen.py --dry-run`).
