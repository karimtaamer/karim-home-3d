"""Implementation notes (A4, plain language, English with Arabic site terms) issued with the finishing package.

    ~/.dwg-tools/bin/python tools/finishing-package/impl_notes.py --out DIR

Writes DIR/Al Lotus - Implementation Notes - Main - <rev>.html and prints it to PDF with headless Chrome.
Facts come from package_data.yaml (meta, plumbing) and the R1 sheets; best practice from the apartment-architect KB.
"""
import argparse
import html
import shutil
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

CSS = """
@page { size: A4; margin: 14mm 13mm 16mm 13mm; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 9.2pt; line-height: 1.38; color: #111; }
h1 { font-size: 19pt; margin: 0 0 2mm 0; }
h2 { font-size: 12.5pt; margin: 6mm 0 2mm 0; padding: 1.2mm 2mm; background: #111; color: #fff; break-after: avoid; }
h2 .ar { float: right; font-weight: normal; }
h3 { font-size: 10pt; margin: 3.5mm 0 1mm 0; color: #e8590c; break-after: avoid; }
p { margin: 1mm 0 1.6mm 0; }
ul { margin: 0.5mm 0 1.6mm 0; padding-left: 5mm; }
li { margin: 0.4mm 0; }
table { border-collapse: collapse; width: 100%; margin: 1.5mm 0 2.5mm 0; font-size: 8.4pt; break-inside: avoid; }
th, td { border: 0.25pt solid #777; padding: 0.9mm 1.4mm; vertical-align: top; text-align: left; }
th { background: #eee; }
.ar { font-family: 'DejaVu Sans', Arial, sans-serif; direction: rtl; unicode-bidi: embed; }
.warn { border-left: 2.2mm solid #e8590c; background: #fff4ec; padding: 1.5mm 2.5mm; margin: 2mm 0; break-inside: avoid; }
.check { border-left: 2.2mm solid #111; background: #f3f3f3; padding: 1.5mm 2.5mm; margin: 2mm 0; break-inside: avoid; }
.small { font-size: 8pt; color: #444; }
.tc { color: #e8590c; font-weight: bold; }
.cover { border-bottom: 0.6pt solid #111; padding-bottom: 3mm; margin-bottom: 3mm; }
"""

TC = '<span class="tc">TO CONFIRM</span>'


def ar(t):
    return f'<span class="ar">{html.escape(t)}</span>'


def ul(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def table(head, rows):
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{h}</tr>{b}</table>"


def stage(no, en, arabic, body):
    return f'<h2>{no}. {en} <span class="ar">{html.escape(arabic)}</span></h2>' + body


def build(meta):
    rev, date = meta["rev"], meta["date"]
    out = [f"<html><head><meta charset='utf-8'><title>Al Lotus - Implementation Notes - Main - {rev}</title><style>{CSS}</style></head><body>"]
    out.append(f"""<div class="cover"><div class="small">AL LOTUS, NEW CAIRO - KARIM TAMER APARTMENT (5TH FLOOR)</div>
<h1>Implementation notes - finishing works</h1>
<div>{ar('ملاحظات التنفيذ - أعمال التشطيب')}</div>
<p><b>Revision {rev} | {date}</b> | issued with the Finishing Package - Main - {rev} (46 sheets) | for Eng. Asmaa (site engineer)<br>
<span class="small">Source of truth: the Main 3D model (karim-home-3d, kareems-changes). The Lotus technical package (Samra Concepts, 1st issue 20-08-2026)
was used to fill gaps; where it differs from Main, <b>Main governs</b> and the difference is listed in section 11.</span></p></div>
<p>How to use this: read the stage before it starts on site. Each stage has <b>what to do</b>, <b>key numbers</b>, <b>what to check before
moving on</b> (hold point) and the <b>sheets</b> to have on site. Dimensions in cm unless marked; heights from the finished floor (FFL)
unless marked. Items marked {TC} are not fixed yet and must be agreed with Karim before that work.</p>
<div class="warn"><b>Structure.</b> No column, beam, slab or load-bearing wall may be cut, chased or loaded beyond the design without written approval from a
structural engineer. This includes the new masonry on the terrace (L-seat, planters, BBQ counter), heavy stone, wall-hung WC frames on
partitions, and any chase deeper than one third of a wall. {ar('أي تعديل إنشائي يحتاج موافقة مهندس إنشائي')}</div>""")

    out.append(stage(0, "Before anything starts", "قبل البدء", ul([
        "Fix one level datum (<b>FFL ±0.00</b>, laser) on every room wall at +100 and keep it until handover. All heights in the package come from it.",
        "Measure the <b>slab soffit</b> in every room. The Lotus TP implies about 296 cm (dining FCL 281 + 15). Main's flat ceiling at 260 leaves about 36 cm of void: confirm on site before ordering ceiling hangers.",
        "Decide the <b>floor build-up</b> (screed + adhesive + tile / HDF) per room so FFL is known. The electrical heights in E2xx are from the slab until this is fixed.",
        "Check every opening against the schedule (W01-W08, D01-D08) and photograph the as-found condition.",
        "Agree the open items in section 12 with Karim; late changes mean breaking finished work.",
    ])))

    out.append(stage(1, "Demolition & masonry", "هدم ومباني", f"""
<h3>What to do</h3>{ul([
        "Demolition and new walls follow the separately issued demolition / new-wall drawings (not in this package).",
        "Build the bathroom build-outs and boxes in masonry or steel stud + cement board: master shower build-out 21 deep (buries the column), WC frame box 30 deep to 112, guest niche build-out 30 deep (y 6.89-7.19), guest bath deck 95 wide x 55 high.",
        "Buffet block 48.7 (\"50\") deep x 70 run with a 10 x 10 chamfer on the corridor corner; panel over the sideboard 18.2 deep (D503).",
        "Terrace L-seat: 10 cm brick walls, rendered; seat 60 deep, back 50 above the cushion, coping 95, planter 20 behind; BBQ counter carcass in brick (D506-D508).",
    ])}
<h3>Key numbers</h3>{table(["Item", "Size / tolerance"], [
        ["Walls plumb / straight", "max 3 mm in 2 m; corners square within 3 mm over 1 m"],
        ["Lintels over new openings", "bearing at least 15-20 cm each side"],
        ["Ties new wall to old", "every 3-4 courses, or steel ties"],
        ["Niche openings", "guest 25 wide x 27 deep, 80-200; buffet 34 x 25 deep, 42-220; master 67 x 13.5"],
    ])}
<div class="warn"><b>Sequence:</b> terrace masonry (seat, planter, BBQ) goes on <b>after</b> the terrace membrane and its protection screed, never before; the membrane must run continuously under it and up the walls at least 20 cm (D506.2).</div>
<div class="check"><b>Hold point:</b> setting-out of every build-out and niche checked against D602 / D603 / D503 before plumbing starts.</div>"""))

    out.append(stage(2, "Plumbing & drainage", "سباكة وصرف", f"""
<h3>What to do</h3>{ul([
        "Supply in PPR (hot + cold) run in the ceiling void and dropped in the wall only at each fixture (Karim, 2 Nov 2026); avoid pipes buried in the floor. Access panels AP1-AP7 under joints and valves (C401-C402).",
        "Set concealed bodies (thermostatic mixers, diverters, wall spouts) to the <b>finished tile face</b> using the maker's depth guide: master shower mixer 100 / diverter 120 / rain arm 210; guest mixer plate 96-114, spout 66-69, head 225 (D602, D603).",
        "WC concealed frames: master in the 30 cm box, flush plate 92-108; guest is a low frame with the flush panel at 68-84 under the 90 cm sill - check the frame model fits before ordering.",
        f"Drains (Main and the Lotus TP do not give them; recommended, {TC}): uPVC 110 for WCs, 50 for floor drains / shower / washer / kitchen sink, 40 for basins; falls 1-2 % to the stack, no sags.",
        "Master shower: linear drain about 70 cm along the build-out (D602.2 S1). Guest bath: floor drain P10 near the door, bath waste at the north end with an access panel in the deck front (D603.4 S3). Laundry floor drain P16. Terrace drains P18.",
        "Heaters: master 7.5 kW instant heater inside the vanity (P02); laundry Ariston 9.5 kW in the upper cabinet (P15) - which fixtures it feeds is " + TC + ".",
        "AC condensate: a drain route for every wall split (living, master, dining buffet wall, reception) - " + TC + " with the AC installer.",
    ])}
<h3>Tests (hold point)</h3>{ul([
        "Pressure-test all supply at 1.5 x working pressure (about 10-15 bar) for at least 1-2 hours (24 h preferred) with a gauge, photographed, <b>before</b> walls are closed.",
        "Drain flow test with water at every point; check falls with a level.",
        "Cap every open pipe end; mark the pipe routes on photos with a tape measure in frame.",
    ])}"""))

    out.append(stage(3, "Electrical, low current & AC first fix", "كهرباء وتيار خفيف وتكييف", f"""
<h3>What to do</h3>{ul([
        "Points per E201-E209 (positions, heights, circuits). Switches 120 (stacked 125 + 113); general sockets 45; bedside 85.",
        "Cable sizes: lighting 1.5 mm², sockets 2.5 mm², heaters / AC / oven 4-6 mm² on their own breakers; 30 mA RCD on wet rooms and all outdoor circuits.",
        "Bathrooms: heater 7.5 kW dedicated circuit + isolator; fans on their own key / presence sensor (master S-175); no sockets inside the shower zone.",
        "LED drivers must stay reachable: buffet L-189 behind a removable panel in the block, L-190 behind the mirror, guest niche driver L-209 at 245 outside the wet zone, terrace feeds L-211 / L-212 in IP65 boxes at 30.",
        "Curtain motors: power P at 268 inside the 15 x 15 pockets (P-215, P-216).",
        "Backing (18 mm plywood or solid block) behind: TV brackets (living and reception), buffet mirror and AC, curtain tracks, towel rails, hooks, guest counter brackets, master medicine cabinet.",
        "AC: copper pipes insulated, flared joints; nitrogen pressure test and vacuum to 500 microns or less before charging; condensate with a continuous fall.",
    ])}
<div class="check"><b>Hold point:</b> continuity + insulation test of every circuit, photos of all wall chases with tape in frame, conduits to the TV walls (2 x 40 mm from console plate to TV plate).</div>"""))

    out.append(stage(4, "Gypsum board ceilings", "أسقف جبس بورد", f"""
<h3>What to do</h3>{ul([
        f"Main: one flat ceiling at <b>260</b> in every room (C401-C402). The Lotus TP has stepped levels (reception and guest bath about 236 for concealed ducted AC; others 276-281). Main uses wall splits, so the drops are not needed; confirm one level per room before starting.",
        "Boards: white 12.5 (C01) in dry rooms; green moisture-resistant 12.5 (C02) in bathrooms, kitchen, laundry. Terrace: slatted wood ceiling per the Lotus TP, level " + TC + ".",
        "Grid: galvanised profiles at least 0.4 mm; hangers (anchor + rod) at max 120 cm; furring 60/27 at 50 cm (40 cm in wet rooms) (C403 CS1).",
        "Curtain pockets 15 x 15 at the windows and 12 x 12 for the reception / dining divider; plywood backing for the tracks fixed to the slab; LED profile on the room-side lip; inside painted darker (C403 CS2-CS3).",
        "Access panels 60 x 60 with hidden frame and push-latch, AP1-AP7 (positions to suit the pipes as laid).",
        "Bathroom fans: duct 100 falling to outside with a back-draft flap (C404 CS4).",
    ])}
<div class="warn"><b>Sequence:</b> close a ceiling only after every service above it is installed and tested (pipes, AC pipes and drains, fans and ducts, cables, curtain power). In practice the wall plaster near the ceiling line is done first and the board is hung after; agree the order with the gypsum contractor.</div>
<div class="check"><b>Hold point:</b> grid inspected (hanger spacing, level within 3 mm over 3 m) before boarding; photos of the void.</div>"""))

    out.append(stage(5, "Plaster", "محارة / بياض", ul([
        "Cement plaster 1.5-2.5 cm on the dots and screeds (بؤج وأوتار); mesh over every joint between different materials and over chases; corner beads on all external corners.",
        "Tolerance: plumb and flat within 3 mm under a 2 m straight edge; corners square. Boxes flush with the finished surface.",
        "Moist-cure several days; no tiling or paint on green plaster.",
        "Where walls will be tiled with large format (120 x 60), the plaster must be flatter: check with a 2 m edge before tiling.",
    ])))

    out.append(stage(6, "Waterproofing, screed & tiling", "عزل وسيراميك / بورسلين", f"""
<h3>Waterproofing</h3>{ul([
        "Bathrooms: membrane on the whole floor with upstands 15-30 cm on all walls, and up to at least 200 (or above the head) inside the shower and bath zones; corners reinforced with tape; drain flanges clamped.",
        "Laundry and kitchen sink area: floor membrane with 15 cm upstands.",
        "Terrace: membrane with upstands at least 20 cm, turned up under the door frame; planters lined with a root-resistant membrane and drained (D506.2, D505.3).",
        "<b>Flood test 24-48 h</b> on every wet floor and the terrace, signed and photographed, before any screed or tile.",
    ])}
<h3>Screed & tiles</h3>{ul([
        "Screed to falls 1.5-2 % toward the drains, no flat spots (master shower falls to the linear drain; terrace falls at least 1.5 % away from the door).",
        "Guest bathroom walls: travertine-look porcelain 120 x 60 laid <b>vertical</b> between 80 and 200, an 80 strip below and a 60 strip above; set out from the joint at x 12.59 that splits the two niches (D603).",
        "Master bathroom: large-format stone-look porcelain; 60 x 120 setting-out drawn as a guide, " + TC + " with the tiler.",
        "Adhesive: C2TE S1 flexible; full bed (back-butter) - coverage at least 80 % dry areas, 95 % wet areas and large format; lippage max 1 mm; flatness 3 mm under 3 m; joints 2-3 mm aligned to the drawings.",
        "Thresholds: terrace slider W08 sill flush inside, terrace 2-3 cm lower with a slot drain " + TC + " (D505.3 S7).",
        "Approve a first area / mock-up before the tiler continues; tap-test for hollow tiles.",
    ])}"""))

    out.append(stage(7, "Carpentry & joinery", "نجارة وأعمال خشبية", ul([
        "Joinery is ordered to <b>site sizes</b> after plaster and tiles: measure, then produce shop drawings for Karim's approval.",
        "Buffet: walnut sideboard 197 x 50, 12-83, four push-open doors, recessed dark plinth; mirror 92 x 80 and AC 105 x 30 centred on the same line y 8.496 (D503).",
        "Bathrooms: master vanity 110 x 58 floating 30-80, marble top to 86, mirrored cabinet 80 x 75 x 30 at 132-207; guest walnut floating unit 20-50 with a travertine slab 72-85 (D602, D603).",
        "Living TV wall: walnut console 174 x 40, 45-72, stone top to 75; TV 160 x 85 at 110-195 (D502). Reception TV wall per D501.",
        "Terrace WPC: on aluminium battens with hidden clips, 5 mm expansion gaps; return lip under the cladding with the LED 5-6 cm off the floor; plinth recessed 6 (D506-D508).",
        "Doors: flush honey-oak leaves, slim oak frames, head 210; bathroom doors moisture-resistant with a 1 cm undercut.",
        "Gas grill (if gas): ventilated cabinet with low vents, approved hose, no WPC within 15 cm of the burner. Grill type " + TC + ".",
    ])))

    out.append(stage(8, "Paint", "دهانات", ul([
        "Walls: warm cream-beige limewash plaster (hand-troweled); living TV wall panel in limewash taupe. Ceilings: flat warm off-white. Products / colour codes " + TC + ".",
        "System (Jotun or equal): sealer, 2-3 coats of putty, sanding, primer, two finish coats; bathrooms and kitchen ceilings in anti-mould / moisture-resistant paint.",
        "Check under raking light before the last coat; final coats after joinery and fixtures are installed, then touch-up.",
    ])))

    out.append(stage(9, "Fixtures & final fix", "تركيبات وتشطيب نهائي", ul([
        "Sanitaryware heights: WC seat 40-42; master basin top 86; guest counter top 85 with vessel basin to 96; mirrors and cabinets as in the fixture schedules (D602.1, D603.1).",
        "Silicone (sanitary) joints at all tile-to-fixture joints; bath rim sealed with the bath full.",
        "Electrical final fix: every point tested and labelled at the board; RCDs tested.",
        "Commission: every mixer hot / cold the right way round, every drain flow-tested, AC run and drained, fans pulling, curtain motors set.",
        "Snag list with Karim, closed and re-inspected; keep warranties and manuals.",
    ])))

    out.append(stage(10, "Key dimensions on one page", "أهم المقاسات", table(["Where", "What", "Value"], [
        ["All rooms", "Ceiling (Main)", "260 flat; pockets 15 x 15, divider 12 x 12"],
        ["All rooms", "Door head / window head / slider head", "210 / 210 / 240"],
        ["All rooms", "Switches / sockets / bedside", "120 / 45 / 85"],
        ["Master bath", "Shower clear / entry / glass", "78.5 x 135 / 66 / 69 long x 200"],
        ["Master bath", "Mixer / diverter / rain head", "100 / 120 / 210 (arm 42)"],
        ["Master bath", "WC box / flush plate / seat", "30 deep to 112 / 92-108 / 42"],
        ["Guest bath", "Bath rim / deck", "55 / 95 wide, wall to wall"],
        ["Guest bath", "Tiles", "120 x 60 vertical 80-200; joint at x 12.59"],
        ["Guest bath", "Counter / mirror", "top 85, 230 long / 104 x 88 at 112-200"],
        ["Dining", "Buffet block / niche / sideboard", "48.7 x 70 run / 34 x 25, 42-220 / 197 x 50, top 83"],
        ["Dining", "Mirror / AC (same centre line)", "92 x 80 at 120-200 / 105 x 30, top 242"],
        ["Living", "TV / console", "160 x 85 at 110-195 / 174 x 40 at 45-75"],
        ["Terrace", "Slider W08 / window W07", "174 x 240 sill 0 / 206 x 240 sill 60"],
        ["Terrace", "L-seat", "60 deep, seat 45 with cushion, back 50 (coping 95), planter 20"],
        ["Terrace", "Seat front", "WPC 2 on 10 brick, lip with LED 5-6 off the floor, plinth recessed 6"],
        ["Terrace", "BBQ counter", "329 x 49, top 94, upstand 130, grill 80 x 40"],
    ])))

    out.append(stage(11, "Lotus technical package vs Main", "الباكدج الفني لوتس مقابل التصميم الرئيسي", table(["Topic", "Lotus TP", "Main (governs)"], [
        ["Ceilings (p.9)", "Stepped: reception and guest bath -600 (about 236) for concealed ducted AC; kitchen / laundry / master bath -200; others -150", "Flat 260 everywhere, wall split ACs"],
        ["Curtains", "Pockets 200 mm at windows", "Pockets 15 x 15 at windows, 12 x 12 divider, motorised"],
        ["HVAC (p.7)", "Ducted units in the reception and above the guest bath; splits in living and bedroom", "Wall splits: living, master, dining buffet wall, reception"],
        ["Sanitary (p.6)", "Supply setting-out only; shows a terrace basin; bathroom / laundry layouts differ", "Layouts per D602 / D603; terrace basin removed"],
        ["Dining wall (p.20)", "Wood cladding", "Niche block + sideboard + mirror + AC (D503)"],
        ["Terrace (p.9)", "Slatted wood ceiling 7550 x 3259", "Not modelled: used as reference, level " + TC],
        ["Board types (p.9)", "C01 white, C02 green, C03 red, C04 cement board", "Used: C01 dry, C02 wet rooms"],
    ]) + "<p class='small'>The Lotus TP gives no drain positions, falls or pipe sizes: those in this note and on the sheets are recommendations.</p>"))

    out.append(stage(12, "Open questions (to agree before the stage)", "أسئلة مفتوحة", ul([
        "Floor build-up per room and the resulting FFL; electrical heights then convert from slab to FFL.",
        "One ceiling level per room: Main 260 flat or a Lotus TP level.",
        "Drain positions and routes: master linear drain, guest floor drain P10, laundry P16, terrace P18; stack connections.",
        "Which fixtures the laundry 9.5 kW heater feeds.",
        "AC condensate route for each split.",
        "Tile sizes and products (master bath), stone for the terrace coping / counter, WPC colour, wall paint codes.",
        "Window W07 opening type, frame colour and glazing (double glazing recommended).",
        "Terrace finished level, threshold detail and the slatted ceiling level.",
        "Grill type (gas / charcoal / electric) and the cabinet ventilation that follows.",
        "Towel rail height (master) and whether the guest oak battens stay real oak in the splash zone.",
        "Structural engineer sign-off for terrace masonry loads and any chase in structure.",
    ])))
    out.append("</body></html>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=str(HERE / "package_data.yaml"))
    a = ap.parse_args()
    meta = yaml.safe_load(open(a.data, encoding="utf-8"))["meta"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"Al Lotus - Implementation Notes - Main - {meta['rev']}"
    h = out / f"{name}.html"
    h.write_text(build(meta), encoding="utf-8")
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    pdf = out / f"{name}.pdf"
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", h.as_uri()], check=True, capture_output=True)
    print("PDF", pdf)


if __name__ == "__main__":
    main()
