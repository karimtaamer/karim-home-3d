"""tests/move_stale_e2e.mjs: write an unrelated revision (a finishes-only change, like an Edit AI edit in another tab or
the live site's test loop) into a SANDBOX's live store: python tests/move_stale_bump.py SANDBOX_DIR"""
import sys, os
os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv[1])
os.environ.pop("BLOB_READ_WRITE_TOKEN", None); os.environ["EDIT_AI_GIT_SYNC"] = "0"
import edit_ai as E
ws = E.Workspace("karims-version")
ws.allow_as_built = False
ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = False, False, {}, {}, [], []
ws.write("materials.js", (ws.text("materials.js") + "\n// test bump\n").encode())
print(E.save(ws, "test: unrelated finishes change")["rev"])
