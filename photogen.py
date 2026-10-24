#!/usr/bin/env python3
"""Local server for the viewer, with the Generate Photo Spot endpoints.

    python3 photogen.py [port]          # serves this folder on http://127.0.0.1:8000
    python3 photogen.py --dry-run       # same, but "generates" by echoing the model view (no API calls)

Generate Photo Spot (Walk view) sends an untextured clay screenshot of the model (matte grey shapes, glass
see-through, lights white) from the framed camera, a plan of the room it looks at, drawn from the DWG, and the
view's numbers. This turns them into an OpenAI image edit that keeps the screenshot's angle and shapes and only
paints the real finishes on them, using a material board cropped from the designer's renders, a few of the
renders themselves (this room's; another room's in shot only when both are wet or both dry) and the
finishes written out in photogen-brief.json; the earlier renders (designer's and approved AI spots) that show
the furniture of this room go too, so the pieces keep their real design (never another room's furniture: a bed
seen through the en-suite door would come in). The screenshot alone says what the room has (walls, doors,
windows, niches, furniture); the other images lend only surfaces and designs. Comments re-run it on the attempt
shown.
Approving copies the image into renders/ and adds the spot to spots.json, like a designer render (or to
the plan version's spots file the page is showing, e.g. spots-bigger-bedroom.json).

The key comes from OPENAI_API_KEY, or a line OPENAI_API_KEY=... in .env next to this file (git-ignored).
OPENAI_IMAGE_MODEL picks the model (default gpt-image-2). Drafts are kept in renders/drafts/.
PHOTOSPOT_PASSWORD, when set, has to come with every generate, approve, edit, delete and name (the page asks once).
PHOTOGEN_MOCK=1 (or --dry-run) makes no OpenAI calls: generate echoes the view, edit the render, name says "view".

The Renders screen edits a saved render in words (edit: the render as image 1 with the board and the furniture
renders, saved as a new spot "of" its first version with the next "version" number; the old one stays) and
deletes generated ones (delete: image and spot entry; on Vercel also a marker, renders/ai-deleted/<file>/<id>.json,
which hides a spot kept in git and keeps its id from being reused). A new spot with no named furniture piece
in frame is named from its first attempt by a cheap vision model (name, OPENAI_NAME_MODEL, default gpt-4.1-nano).

On Vercel api/photospot.py runs these same endpoints. There renders/ can't be written, so drafts, approved
images and their spots go to Vercel Blob (photogen_blob.py, on when BLOB_READ_WRITE_TOKEN is set) under the
same paths; an approved spot is kept as renders/ai-spots/<spots file>/<id>.json and the page adds those to
the spots file it loads. publish_renders.sh puts the renders, their reference copies and the board there.
"""
import base64, hashlib, hmac, json, os, re, secrets, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import photogen_blob

ROOT = Path(__file__).resolve().parent
RENDERS = ROOT / "renders"
DRAFTS = RENDERS / "drafts"
SPOTS_FILE = re.compile(r"^spots(-[a-z0-9-]+)?\.json$")  # spots.json and the plan versions' spots-<id>.json
MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
SIZE = "1536x1024"  # 3:2 landscape, the shape the viewer crops its screenshot to
DRY = "--dry-run" in sys.argv or os.environ.get("PHOTOGEN_MOCK") == "1"  # PHOTOGEN_MOCK=1: tests, no OpenAI calls
NAME_MODEL = os.environ.get("OPENAI_NAME_MODEL", "gpt-4.1-nano")  # names a spot from its image when the model can't
# USD per million tokens, OpenAI's list prices for gpt-image-1 (text in, image in, image out); gpt-image-2 is
# assumed to cost the same until OpenAI's price page says otherwise. Only used to log what a call cost.
PRICE = {"text": 5.0, "image": 10.0, "output": 40.0}
# Whole designer renders sent for colour and light (more invites copying their layout): those of this room and the
# rooms in shot up to MAX_REFS; renders of rooms not in shot only to make up SAME_ROOM, as their doors and windows
# are elsewhere and leak into the photo (a living-room door appeared at the edge of a dining view).
SAME_ROOM, MAX_REFS = 2, 4
MAX_FURNITURE, MAX_IMAGES = 6, 16  # extra renders sent for their furniture; OpenAI edits take at most 16 images
SOFT = {"LIVING ROOM", "RECEPTION", "MASTER BEDROOM", "DINING"}  # the rooms that show the fabrics and art best
REF_PX = 1024  # long side of a whole render as sent; the board carries the close-up detail
TILE, LABEL, COLS = 384, 46, 4  # material board: square swatches with a caption strip, four across
STAND_IN = {"HALLWAY": "ENTRANCE"}
DRAFT_ID = re.compile(r"^d\d+-[0-9a-f]{6}$")
BLOB = bool(photogen_blob.token())  # on Vercel: renders/ lives in Vercel Blob
CACHE = Path(tempfile.gettempdir()) / "photogen"  # Blob copies of references and the board, per instance

# The design language, written from the designer's renders: one block for the whole flat, one per room.
BRIEF = ROOT / "photogen-brief.json"
# Drawn facts and the client's decisions that override the renders.
FACTS = """\
Ceilings are {ceiling} m high; door heads {doorHead} m; windows run from a {sill} m sill to {winHead} m;
glass sliders are {sliderHead} m high. Client decisions that override the designer's renders: the kitchen
door is on the kitchen's east wall, as in the architect's drawing; the terrace counter has no sink; the shoe
cabinet is the unit beside the front door."""
# Where the room comes from, in every prompt: the image named holds the architecture and what is in the room; the
# others lend only surfaces and designs, so nothing of theirs (a door at the edge of a render, say) comes in.
LOCK = """\
For this photo, {img} is the only authority for the architecture and for what is in the room: every wall, opening, door, window, \
niche, column, beam, ceiling feature, built-in, piece of furniture, light, plant, artwork and object, and where each \
one is. Do not add any door, opening, window, niche, furniture, decor or fixture that is not visible in {img}, and \
do not remove any that is. Where {img} shows plain wall, the photo shows plain wall. Keep everything at the edges \
of the frame exactly as {img} has it, and do not complete what is cut off there from another image. The other \
images lend only materials, colours, light and the design of pieces that are already in {img}; their walls, doors, \
windows, openings and layout belong to other rooms or angles and must not appear. Nothing from another image (a \
bed, a door, a piece of furniture, a whole room) appears unless {img} has its shape in that place; through a doorway \
or opening the photo shows only what {img} shows there."""


def save(path, data, mime):
    """Write path (relative to this folder, under renders/) on disk, or in Blob on Vercel."""
    if BLOB:
        photogen_blob.put(path, data, mime)
    else:
        (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / path).write_bytes(data)


def load(path):
    return photogen_blob.get(path) if BLOB else (ROOT / path).read_bytes()


def fetched(path):
    """A file publish_renders.sh put in Blob, as a local Path (cached for the instance), or None if it isn't there."""
    out = CACHE / path
    if not out.exists():
        try:
            data = photogen_blob.get(path)
        except urllib.error.HTTPError:
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return out


def blob_spots(name):
    """The spots approved on Vercel for a spots file (and, for a plan version, the file it extends), less the deleted."""
    if not BLOB:
        return []  # on disk they are in the file itself
    data = read(name)
    base = [] if isinstance(data, list) else [s for s in blob_spots(data["extends"]) if s["room"] not in data.get("replaces", [])]
    own = [json.loads(photogen_blob.get(p)) for p in sorted(photogen_blob.names(f"renders/ai-spots/{name}/"))]
    gone = deleted(name)
    return [s for s in base + own if s["id"] not in gone]


def deleted(name):
    """Ids deleted on Vercel from a spots file and the files it extends. Each leaves a marker, renders/ai-deleted/
    <file>/<id>.json, so a spot kept in git (which Vercel can't rewrite) stays hidden and its id is never reused."""
    if not BLOB:
        return set()  # on disk a deleted spot leaves its file
    return {Path(p).stem for f in chain(name) for p in photogen_blob.names(f"renders/ai-deleted/{f}/")}


def live_spots(name):
    """The page's extra spots: those approved on Vercel, plus {id, deleted} for each deleted one it should drop."""
    return blob_spots(name) + [{"id": i, "deleted": True} for i in sorted(deleted(name))]


def api_key():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "OPENAI_API_KEY":
                return v.strip().strip("\"'")
    return None


def spots_path(name):
    if not SPOTS_FILE.match(name or ""):
        raise ValueError("bad spots file")
    return ROOT / name


def read(name):
    path = spots_path(name)
    return json.loads(path.read_text()) if path.exists() else []


def own(name):
    """The spots a file lists itself (not those of the file it extends)."""
    data = read(name)
    return data if isinstance(data, list) else data["spots"]


def chain(name):
    """A spots file and the files it extends, nearest first."""
    out, data = [name], read(name)
    while isinstance(data, dict):
        out.append(data["extends"])
        data = read(data["extends"])
    return out


def spots(name="spots.json"):
    """A spots file as one list; a plan version's ({extends, replaces, spots}) is the file it extends,
    less the rooms it replaces, plus its own spots (as spots.js reads it)."""
    data = read(name)
    if isinstance(data, list):
        return data
    return [s for s in spots(data["extends"]) if s["room"] not in data.get("replaces", [])] + data["spots"]


def write_spots(name, items):
    path, data = spots_path(name), read(name)
    lines = "[\n  " + ",\n  ".join(json.dumps(s, ensure_ascii=False) for s in items) + "\n]"
    if isinstance(data, list):
        path.write_text(lines + "\n")
    else:  # keep the version's header, one spot per line as in spots.json
        head = json.dumps({k: v for k, v in data.items() if k != "spots"}, ensure_ascii=False, indent=2)[:-2]
        path.write_text(head + ',\n  "spots": ' + lines.replace("\n", "\n  ") + "\n}\n")


def add_spot(name, spot):
    write_spots(name, own(name) + [spot])


def find(name, sid):
    """-> (spot, the file that holds it) for a spot the page shows in this spots file."""
    gone = deleted(name)
    for f in chain(name):
        for s in own(f) + ([json.loads(photogen_blob.get(p)) for p in photogen_blob.names(f"renders/ai-spots/{f}/{sid}.json")] if BLOB else []):
            if s["id"] == sid and sid not in gone:
                return s, f
    raise ValueError("no such render")


def next_id():
    """ai-NN, numbered across every version's file, so images never share a name in renders/ (nor, on Vercel,
    with a deleted one the Blob cache may still hold)."""
    ids = {s["id"] for f in ROOT.glob("spots*.json") if SPOTS_FILE.match(f.name) for s in spots(f.name)}
    if BLOB:
        ids |= {Path(p).stem for p in photogen_blob.names("renders/ai-spots/") + photogen_blob.names("renders/ai-deleted/")}
    n = 1 + max((int(i[3:]) for i in ids if re.fullmatch(r"ai-\d+", i)), default=0)
    return f"ai-{n:02d}"


def small(path):
    """A designer render shrunk to REF_PX JPEG (macOS sips) so uploads stay light; the original if that fails."""
    out = DRAFTS / "refs" / f"{path.stem}-{REF_PX}.jpg"
    if BLOB:
        return fetched(str(out.relative_to(ROOT))) or path
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["sips", "-Z", str(REF_PX), "-s", "format", "jpeg", str(path), "--out", str(out)], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            return path
    return out


def wet(r):
    return bool(re.search(r"toilet|bath|wc|shower|laundry", r, re.I))


def references(room, seen, name):
    """Designer renders on disk: this room's, then one of each other room in shot that is wet only if this room is
    (a bathroom's for a bathroom, a dry room's for a dry room: a bedroom edge seen from the en-suite sends no bedroom),
    up to MAX_REFS; then, only while there are fewer than SAME_ROOM, one each from rooms of the same sort (bathrooms
    for a bathroom, the terrace for the terrace, living spaces otherwise). All for colour and light only."""
    have = [s for s in spots(name) if not s.get("ai") and (BLOB or (ROOT / s["photo"]).exists())]
    refs = [s for s in have if s["room"] == room][:SAME_ROOM]
    out = lambda r: r == "TERRACE"
    seen = [STAND_IN.get(r, r) for r in seen]  # rooms with no render of their own borrow a neighbour's
    other = sorted({s["room"] for s in have} - {room, *seen}, key=lambda r: (out(r) != out(room), wet(r) != wet(room), r not in SOFT, r))
    seen = [r for r in seen if wet(r) == wet(room)]
    for r, most in [(r, MAX_REFS) for r in seen] + [(r, SAME_ROOM) for r in other]:
        pick = next((s for s in have if s["room"] == r), None)
        if pick and pick not in refs and len(refs) < most:
            refs.append(pick)
    return refs


def furniture(room, name):
    """Earlier renders that show the real pieces of this room (and of the room it borrows renders from, STAND_IN),
    never of the other rooms in shot: their furniture is not in the VIEW, and sending it brings it in (a bed through
    the en-suite door). The designer's ones named in photogen-brief.json's furniture list (this room's first, most
    pieces first), then the approved AI spots of this room, newest first. -> [(spot, [where, ..])]"""
    items = json.loads(BRIEF.read_text()).get("furniture", []) if BRIEF.exists() else []
    rooms = list(dict.fromkeys([room, STAND_IN.get(room, room)]))
    try:
        later, gone = blob_spots(name), deleted(name)
    except Exception as e:  # without them the designer's renders still go
        print(f"[photogen] no approved spots from Blob: {e}", flush=True)
        later, gone = [], set()
    have = {s["photo"]: s for s in spots(name) + later if s["id"] not in gone}  # every previous render of this plan version
    rank = lambda s: rooms.index(s["room"]) if s["room"] in rooms else len(rooms)
    shown = {}
    for f in items:
        p = "renders/" + f["render"]
        if p in have and (f["room"] in rooms or set(f.get("rooms", [])) & set(rooms)) and (BLOB or (ROOT / p).exists()):
            shown.setdefault(p, []).append(f["where"])
    out = sorted(((have[p], w) for p, w in shown.items()), key=lambda x: (rank(x[0]), -len(x[1])))
    ai = [s for s in reversed(list(have.values())) if s.get("ai") and s["room"] in rooms]
    return out + [(s, []) for s in sorted(ai, key=rank)]


def picture(s):
    """A render as sent: a designer render's 1024 px copy; an approved AI spot as it is (fetched from Blob on
    Vercel, where it has no reference copy). None if it can't be had."""
    if s.get("ai") and BLOB:
        return fetched(s["photo"])
    p = small(ROOT / s["photo"])
    return p if p.exists() else None


def brief(rooms):
    b = json.loads(BRIEF.read_text()) if BRIEF.exists() else {"all": [], "rooms": {}}
    return b["all"], [(r, b["rooms"][r]) for r in rooms if r in b["rooms"]]


def board():
    """The swatches in photogen-brief.json as one labelled JPEG (needs Pillow), rebuilt when the list changes."""
    sw = json.loads(BRIEF.read_text()).get("swatches", []) if BRIEF.exists() else []
    if not sw:
        return None
    out = DRAFTS / "refs" / f"board-{hashlib.md5(json.dumps(sw, sort_keys=True).encode()).hexdigest()[:8]}.jpg"
    if BLOB:  # built and uploaded by publish_renders.sh
        return fetched(str(out.relative_to(ROOT)))
    if out.exists():
        return out
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[photogen] no Pillow: sending no material board", flush=True)
        return None
    missing = [w["render"] for w in sw if not (ROOT / "renders" / w["render"]).exists()]
    if missing:
        print(f"[photogen] board renders missing ({', '.join(missing)}): sending no material board", flush=True)
        return None
    rows = -(-len(sw) // COLS)
    img = Image.new("RGB", (TILE * COLS, rows * (TILE + LABEL)), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 17)
    except OSError:
        font = ImageFont.load_default()
    for i, w in enumerate(sw):
        src = Image.open(ROOT / "renders" / w["render"]).convert("RGB")
        x0, y0, x1, y1 = w["box"]
        c = src.crop((int(x0 * src.width), int(y0 * src.height), int(x1 * src.width), int(y1 * src.height)))
        k = max(TILE / c.width, TILE / c.height)  # cover the tile, centred
        c = c.resize((max(TILE, round(c.width * k)), max(TILE, round(c.height * k))))
        c = c.crop(((c.width - TILE) // 2, (c.height - TILE) // 2, (c.width + TILE) // 2, (c.height + TILE) // 2))
        x, y = (i % COLS) * TILE, (i // COLS) * (TILE + LABEL)
        img.paste(c, (x, y))
        draw.text((x + 8, y + TILE + 6), w["label"], fill="black", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=90)
    return out


def prompt(ctx, refs, comments, revising, has_board):
    """The images go in this order: PREVIOUS (revisions only), VIEW, PLAN, BOARD, then whole renders, each
    (spot, None) for colour and light or (spot, [where, ..]) for its furniture too. The image model holds
    closest to the first one, so that is the model screenshot for a first attempt and the last attempt for a
    revision: the angle and every object stay, and only their surfaces change."""
    v, r, seen = ctx["view"], ctx["room"], ctx.get("seen", [])
    allrooms, rooms = brief([r["name"]] + [s["name"] for s in seen])
    n = iter(range(1, 99))
    first = "PREVIOUS" if revising else "VIEW"
    furn = any(w is not None for _, w in refs)
    lines = [
        f"Edit image 1 ({first}) into a photorealistic interior photograph, as if it were one more render in "
        "the interior designer's set for this apartment. This is a re-surfacing job, not a new design: keep "
        "exactly the same camera, angle, lens, framing and composition, and keep every wall, opening, door, "
        "window, piece of furniture, light and object in the same place, with the same shape and size. "
        + ("Do not add, remove or move anything, and do not borrow the layout of any other image or any object "
           "that is not in the VIEW. Change only the materials, colours, textures and light so they match the "
           "designer's finishes, and give each piece of furniture its real design from the FURNITURE images. "
           if furn else
           "Do not add, remove, move or redesign anything, and do not borrow the layout or objects of any other "
           "image. Change only the materials, colours, textures and light so they match the designer's finishes. ")
        + "No text, no labels, no people.",
        "",
        LOCK.format(img="the VIEW"),
        "",
        "Images, in order:",
    ]
    if revising:
        lines.append(f"{next(n)}. PREVIOUS - your last attempt at this view. Keep it exactly, except where the "
                     "comments below ask for a change, and except that anything in it the VIEW does not have (a "
                     "door, opening, window, niche, piece of furniture or fixture) is a mistake: put back what the "
                     "VIEW shows there.")
    lines += [
        f"{next(n)}. VIEW - an untextured clay render of the 3D model from the exact camera spot, drawn from the "
        "architect's DWG. Its grey shapes are the exact architecture, furniture and objects: every one stays, "
        "with its outline, size and place, and nothing is added. Resurface them only with the finishes from the "
        "brief, the BOARD and the references; do not add, remove, move or reshape anything. Grey is not a colour "
        "to keep: every surface gets its real finish. Its faint blue-grey see-through panes are glass (windows, "
        "glass doors, screens and shelves); the bright white strips and shades are lights.",
        f"{next(n)}. PLAN - the room from above, from the DWG: walls black, glazing blue, door openings brown, "
        "furniture outlines grey, the camera a red dot with its field of view in red. North is up. Use it to "
        "understand the room beyond the frame and where daylight comes from; do not draw it.",
    ]
    if has_board:
        lines.append(f"{next(n)}. BOARD - the designer's materials, cropped from their renders, each labelled with "
                     "what it is for. Give each surface in the VIEW the matching swatch: walls the limewash "
                     "plaster, the ceiling its warm off-white, the floor the honey oak, any door leaves and frames "
                     "the VIEW shows the flush honey oak, the headboard the cream boucle, bedding, rugs and cushions "
                     "their fabrics, bathroom walls the oak slats and stone, corridor walls and trim the corridor "
                     "finishes. Copy their colour, grain, weave, texture and sheen closely. The board is materials "
                     "only: a swatch is not an object to add (the door swatches do not mean this view has a door).")
    lines += [ref_line(next(n), s, w, r["name"], [x["name"] for x in seen]) for s, w in refs]
    if furn:
        lines += ["", "Use the EXACT furniture shown in the FURNITURE reference images (same design, shape, fabric, "
                  "colour, wood and details) for the pieces standing where the VIEW's grey shapes are; do not substitute "
                  "other designs. Do not copy those images' layout or camera: positions and sizes come from the VIEW, "
                  "and a piece that is not in the VIEW stays out, even when a FURNITURE image lists it for this room."]
    lines += [
        "",
        f"Room: {r['caption']} (DWG label {r['name']}), about {r['width']:.2f} m east-west by {r['depth']:.2f} m "
        f"north-south, {r['area']:.1f} m2, floor finish {r['finish']}."
        + (f" Also in shot: {', '.join(s['caption'] for s in seen)}." if seen else ""),
        f"Camera: {v['height']:.2f} m above the floor, looking {v['facing']}, tilted {v['tilt']}, horizontal "
        f"field of view {v['hfov']:.0f} degrees (vertical {v['vfov']:.0f}).",
        "",
        "Finishes of the whole apartment (from the designer's renders; they say how what the VIEW shows should look, "
        "never what to add):",
        *[f"- {x}" for x in allrooms],
        *[f"{captionish(name)}: {text}" for name, text in rooms],
        "",
        FACTS.format(**ctx["heights"]),
    ]
    if revising:
        lines += ["", "This is a revision of the PREVIOUS image. Only these comments can add or remove something "
                  "the VIEW has or lacks. Where a comment says a part is wrong, inaccurate or should not be there, "
                  "make that part match the VIEW exactly (a door or opening the VIEW lacks is removed, and plain "
                  "wall goes back), and do not redraw it more clearly. Fix these client comments now: " + comments[-1]]
        if len(comments) > 1:
            lines.append("Earlier comments, already fixed - keep them fixed: " + " | ".join(comments[:-1]))
    return "\n".join(lines)


def ref_line(k, s, w, room, seen, base="the VIEW"):
    """Image k's line in a prompt: a whole render (s), sent for colour and light (w None) or its furniture too.
    base names the image that holds the room's architecture and objects."""
    here = (" (this room)" if s["room"] == room else " (a room in shot)" if s["room"] in seen
            else f" (another room, the {captionish(s['room']).lower()}, not in this view)")
    rest = (f"do not copy its layout, its camera, its walls, doors, windows, openings or niches, or any object "
            f"{base} does not have.")
    # A render of the same space shows the walls the photo shows, but as an earlier design drew them: its doors
    # and openings can be gone from the plan (a door right of the reception's TV wall kept coming back).
    same = (f" It was drawn for an earlier design of this space: where its walls, doors, openings, niches or windows "
            f"differ from {base} (for example a door beside the TV wall or the lit niches), {base} is right and that "
            "door or opening does not exist." if s["room"] == room or s["room"] in seen else "")
    rest += same
    if w is None:
        return (f"{k}. RENDER - the designer's render \"{s['caption']}\"{here}, from another angle. "
                "Use it only for the colour palette, the warmth and softness of the light and the render "
                f"quality; ignore its layout, architecture and objects: they are not in {base}." + same)
    if s.get("ai"):
        return (f"{k}. FURNITURE - render \"{s['caption']}\"{here}, an approved earlier photo of this "
                f"apartment from another angle, shows its furniture as already chosen. Keep the designs of "
                f"those pieces that are in {base}, and the render quality; " + rest)
    return (f"{k}. FURNITURE - the designer's render \"{s['caption']}\"{here}, from another angle, "
            f"shows {'; '.join(w)}. Keep the designs of those pieces that are in {base}, and use it for the "
            "colour palette, the light and the render quality; " + rest)


def edit_prompt(s, refs, instruction, earlier, has_board):
    """A saved render revised in words: RENDER first (held closest), then BOARD and the FURNITURE renders."""
    n = iter(range(2, 99))
    lines = [
        "Edit image 1 (RENDER), a finished photo of this apartment, as the client asks below. Change only what "
        "the request asks for. Keep everything else exactly as it is: the same camera, angle, lens, framing and "
        "composition, and every wall, opening, door, window, piece of furniture, light and object in the same "
        "place with the same shape, size, material and colour. Keep the photorealistic render quality. No text, "
        "no labels, no people.",
        "",
        LOCK.format(img="image 1") + " Only the client's request below can add or remove something.",
        "",
        "Images, in order:",
        f"1. RENDER - \"{s['caption']}\", the photo to revise.",
    ]
    if has_board:
        lines.append(f"{next(n)}. BOARD - the designer's materials, cropped from their renders, each labelled with "
                     "what it is for. Use these finishes for anything the request changes.")
    lines += [ref_line(next(n), x, w, s["room"], [], "image 1") for x, w in refs]
    if any(w is not None for _, w in refs):
        lines += ["", "A piece the request names takes its EXACT design from the FURNITURE images; do not copy their "
                  "layout or camera."]
    lines += ["", f"Room: {captionish(s['room'])}.", "", "The client's revision, to make now: " + instruction]
    if earlier:
        lines.append("Earlier revisions, already made - keep them: " + " | ".join(earlier))
    return "\n".join(lines)


def captionish(name):
    return {"TOILET 1": "Master bathroom", "TOILET 2": "Guest bathroom"}.get(name, name.capitalize())


def multipart(fields, files):
    boundary = "----photogen" + secrets.token_hex(8)
    out = bytearray()
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for name, data, mime in files:
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="{name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def cost(usage):
    """An images/edits usage block -> estimated USD (PRICE), or None without one."""
    if not usage:
        return None
    d = usage.get("input_tokens_details") or {}
    text, image = d.get("text_tokens", 0), d.get("image_tokens", usage.get("input_tokens", 0))
    return round((text * PRICE["text"] + image * PRICE["image"] + usage.get("output_tokens", 0) * PRICE["output"]) / 1e6, 4)


def edit(images, text):
    """-> (PNG bytes, usage) from OpenAI image edit; the usage is logged with its estimated cost."""
    body, ctype = multipart({"model": MODEL, "prompt": text, "size": SIZE, "quality": "high", "n": "1"}, images)
    req = urllib.request.Request("https://api.openai.com/v1/images/edits", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {api_key()}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=290 if BLOB else 600) as res:  # Vercel stops a call at 300 s
            out = json.load(res)
            usage = out.get("usage")
            print(f"[photogen] {MODEL} usage {json.dumps(usage)} ≈ ${cost(usage)}", flush=True)
            return base64.b64decode(out["data"][0]["b64_json"]), usage
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e)["error"]["message"]
        except Exception:
            msg = e.reason
        raise RuntimeError(f"OpenAI {e.code}: {msg}") from None


def data_url(s):
    """data:image/jpeg;base64,... -> (bytes, mime, extension)"""
    head, _, body = s.partition(",")
    mime = "image/jpeg" if "jpeg" in head else "image/png"
    return base64.b64decode(body), mime, "jpg" if mime == "image/jpeg" else "png"


def request(ctx, view, vmime, vext, plan, comments, prev, name):
    """The edit to send: (prompt, [(filename, bytes, mime)], [(spot, None or [where, ..])] for the renders, board)."""
    room, seen = ctx["room"]["name"], [s["name"] for s in ctx.get("seen", [])]
    refs = references(room, seen, name)
    mats = board()
    images = [("previous.png", load(f"renders/drafts/{prev}.png"), "image/png")] if prev else []
    images += [(f"view.{vext}", view, vmime), ("plan.png", plan, "image/png")]
    if mats:
        images.append((mats.name, mats.read_bytes(), "image/jpeg"))
    furn = furniture(room, name)
    shows = {s["photo"]: w for s, w in furn}
    sent = [(s, shows.get(s["photo"])) for s in refs]  # a whole render that shows furniture serves both
    sent += [(s, w) for s, w in furn if s["photo"] not in {x["photo"] for x in refs}][:max(0, min(MAX_FURNITURE, MAX_IMAGES - len(images) - len(refs)))]
    used = []
    for s, w in sent:
        p = picture(s)
        if p:
            images.append((p.name, p.read_bytes(), "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"))
            used.append((s, w))
    return prompt(ctx, used, comments, bool(prev), bool(mats)), images, used, mats


def generate(req):
    """{view, plan: data URLs, ctx, comments: [..], previous: draft id?} -> {draft, src}"""
    prev = req.get("previous")
    if prev and not DRAFT_ID.match(prev):
        raise ValueError("bad draft id")
    comments = [c for c in req.get("comments", []) if c.strip()]
    if prev and not comments:
        raise ValueError("write a comment to revise with")
    ctx = req["ctx"]
    draft = f"d{int(time.time())}-{secrets.token_hex(3)}"
    (view, vmime, vext), (plan, _, _) = data_url(req["view"]), data_url(req["plan"])
    save(f"renders/drafts/{draft}-view.{vext}", view, vmime)
    save(f"renders/drafts/{draft}-plan.png", plan, "image/png")
    text, images, refs, mats = request(ctx, view, vmime, vext, plan, comments, prev, req.get("spots", "spots.json"))
    print(f"[photogen] {draft}: {ctx['room']['caption']}, {len(images)} images{' (revision)' if prev else ''}", flush=True)
    out, usage = (view, None) if DRY else edit(images, text)
    save(f"renders/drafts/{draft}.png", out, vmime if DRY else "image/png")
    save(f"renders/drafts/{draft}.json", json.dumps({"previous": prev, "comments": comments, "ctx": ctx, "cam": req.get("cam"),
                                                    "references": [s["photo"] for s, _ in refs],
                                                    "furniture": [s["photo"] for s, w in refs if w is not None],
                                                    "board": mats and mats.name, "prompt": text,
                                                    "usage": usage, "usd": cost(usage)}, indent=1).encode(), "application/json")
    return {"draft": draft, "src": f"renders/drafts/{draft}.png"}


def revise(req):
    """{spots, id, instruction} -> {spot, usd}: a saved render edited in words, saved as its next version (a new
    spot with the same room, caption and camera, "of" its first version), the earlier versions kept."""
    name = req.get("spots", "spots.json")
    s, home = find(name, req.get("id", ""))
    instruction = (req.get("instruction") or "").strip()
    if not instruction:
        raise ValueError("write what should change")
    first = s.get("of") or s["id"]
    family = [x for x in spots(home) + blob_spots(home) if (x.get("of") or x["id"]) == first]
    src = picture(s)
    if not src:
        raise ValueError("the render's image can't be read")
    mime = "image/jpeg" if src.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    images = [(f"render{src.suffix.lower()}", src.read_bytes(), mime)]
    mats = board()
    if mats:
        images.append((mats.name, mats.read_bytes(), "image/jpeg"))
    used = []
    for x, w in furniture(s["room"], name):
        if x["photo"] == s["photo"] or len(used) >= MAX_FURNITURE or len(images) >= MAX_IMAGES:
            continue
        p = picture(x)
        if p:
            images.append((p.name, p.read_bytes(), "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"))
            used.append((x, w))
    earlier = [x["edit"] for x in sorted(family, key=lambda x: x.get("version", 1)) if x.get("edit")]
    text = edit_prompt(s, used, instruction, earlier, bool(mats))
    print(f"[photogen] edit {s['id']}: {len(images)} images", flush=True)
    out, usage = (images[0][1], None) if DRY else edit(images, text)
    sid = next_id()
    ext, omime = (src.suffix.lower().lstrip(".") or "png", mime) if DRY else ("png", "image/png")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", s["caption"]).strip("_") or "View"
    version = 1 + max(x.get("version", 1) for x in family)
    photo = f"renders/{sid}-{slug}-v{version}.{ext}"
    save(photo, out, omime)
    spot = {"id": sid, "room": s["room"], "caption": s["caption"], **({"cam": s["cam"]} if s.get("cam") else {}),
            "photo": photo, "ai": True, "of": first, "version": version, "edit": instruction}
    if BLOB:
        save(f"renders/ai-spots/{home}/{sid}.json", json.dumps(spot, ensure_ascii=False).encode(), "application/json")
    else:
        add_spot(home, spot)
    save(f"renders/drafts/{sid}-edit.json", json.dumps({"from": s["id"], "prompt": text, "references": [x["photo"] for x, _ in used],
                                                        "usage": usage, "usd": cost(usage)}, indent=1).encode(), "application/json")
    print(f"[photogen] edited {s['id']} as {photo}", flush=True)
    return {"spot": spot, "usd": cost(usage)}


def delete(req):
    """{spots, id} -> {deleted: id}: a generated render gone for good, its image and its spot entry, on disk or in
    Blob (where a marker also hides a spot kept in git). Designer renders can't be deleted here."""
    name = req.get("spots", "spots.json")
    s, home = find(name, req.get("id", ""))
    if not s.get("ai"):
        raise ValueError("designer renders can't be deleted here, only generated ones")
    if BLOB:
        save(f"renders/ai-deleted/{home}/{s['id']}.json", json.dumps(s, ensure_ascii=False).encode(), "application/json")
        photogen_blob.delete([s["photo"]] + photogen_blob.names(f"renders/ai-spots/{home}/{s['id']}.json"))
    else:
        write_spots(home, [x for x in own(home) if x["id"] != s["id"]])
        (ROOT / s["photo"]).unlink(missing_ok=True)
    print(f"[photogen] deleted {s['id']} ({s['photo']})", flush=True)
    return {"deleted": s["id"]}


def name_from_image(req):
    """{draft} -> {word}: what a generated view shows, in a word or two, from a cheap vision model (NAME_MODEL).
    The page asks only when no named furniture piece is in frame."""
    if not DRAFT_ID.match(req.get("draft", "")):
        raise ValueError("bad draft id")
    if DRY:
        return {"word": "view"}
    data = base64.b64encode(load(f"renders/drafts/{req['draft']}.png")).decode()
    body = json.dumps({"model": NAME_MODEL, "max_tokens": 10, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "This is an interior photo of an apartment. Name the main piece of furniture or fixture "
                                 "it is framed on, in one or two lowercase words (e.g. bed, wardrobe, dresser, sofa, "
                                 "vanity, shower, window). Reply with the words only."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}", "detail": "low"}}]}]}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as res:
        text = json.load(res)["choices"][0]["message"]["content"]
    return {"word": " ".join(re.sub(r"[^a-z ]", "", text.lower()).split()[:2])[:20] or "view"}


def approve(req):
    """{draft, room, caption, cam} -> the new spots.json entry"""
    if not DRAFT_ID.match(req.get("draft", "")):
        raise ValueError("bad draft id")
    name = req.get("spots", "spots.json")
    spots_path(name)
    sid = next_id()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", req["caption"]).strip("_") or "View"
    photo = f"renders/{sid}-{slug}.png"
    save(photo, load(f"renders/drafts/{req['draft']}.png"), "image/png")
    spot = {"id": sid, "room": req["room"], "caption": req["caption"], "cam": [round(c, 3) for c in req["cam"]],
            "photo": photo, "ai": True}
    if BLOB:
        save(f"renders/ai-spots/{name}/{sid}.json", json.dumps(spot, ensure_ascii=False).encode(), "application/json")
    else:
        add_spot(name, spot)
    print(f"[photogen] approved {req['draft']} as {photo}", flush=True)
    return spot


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")  # spots.json changes while the page is open
        super().end_headers()

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def action(self):
        """/api/photospot/<action>, or ?action= after vercel.json's rewrite to the one function; None if not the API."""
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path.rstrip("/") == "/api/photospot":
            return q.get("action", ["status"])[0], q
        if url.path.startswith("/api/photospot/"):
            return url.path.split("/")[3], q
        return None, q

    def do_GET(self):
        act, q = self.action()
        if act == "status":
            return self.reply(200, {"ok": DRY or bool(api_key()), "model": "dry run" if DRY else MODEL,
                                    "locked": bool(os.environ.get("PHOTOSPOT_PASSWORD"))})
        if act == "spots":
            try:
                return self.reply(200, live_spots(q.get("file", ["spots.json"])[0]))
            except ValueError as e:
                return self.reply(400, {"error": str(e)})
        if act:
            return self.reply(404, {"error": "not found"})
        super().do_GET()

    def do_POST(self):
        routes = {"generate": generate, "approve": approve, "edit": revise, "delete": delete, "name": name_from_image}
        act, _ = self.action()
        if act not in routes:
            return self.reply(404, {"error": "not found"})
        want = os.environ.get("PHOTOSPOT_PASSWORD")
        if want and not hmac.compare_digest(self.headers.get("X-Photospot-Password", "").encode(), want.encode()):
            return self.reply(401, {"error": "wrong password"})
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.reply(200, routes[act](req))
        except Exception as e:  # shown to the user in the panel
            print(f"[photogen] {act}: {e}", flush=True)
            self.reply(400 if isinstance(e, (ValueError, KeyError)) else 502, {"error": str(e)})


if __name__ == "__main__":
    port = next((int(a) for a in sys.argv[1:] if a.isdigit()), 8000)
    print(f"Serving http://127.0.0.1:{port}  ·  photo spots: {'dry run' if DRY else MODEL}"
          f"{'' if DRY or api_key() else '  (no OPENAI_API_KEY: generating is off)'}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
