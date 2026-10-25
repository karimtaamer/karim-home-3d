# One version's change stays in that version

Karim, 26 Oct 2026: *"From now on, any change in any version is only for that version."*

`furnish.js` and `materials.js` are shared by every plan version, so an Edit AI change has to be split:

* **A value on a shared line:** `version === "kareems-changes" ? newValue : oldValue`. Every other version must
  build exactly what it did before.
* **A whole piece:** an `if (version === "kareems-changes") { ... }` branch.
* **A colour / finish:** add a NEW material to `materials.js` and pick it with the ternary above. Never change an
  existing material (`walnut`, `linenSlate`, ...) in place: other versions use it.

Only when the user says so ("in all versions", "everywhere", "both versions") may a change reach every version.

## How it is enforced (`edit_ai.py`)

* `SYSTEM` tells the model the rule, and that an edit breaking it is refused.
* `version_leak()` runs before saving. It builds `furnish.js` as each OTHER version runs it (`for_version()`: other
  versions' branches dropped, `version === "x"` and `const KC = version === "x"` folded, `true ? a : b` resolved)
  before and after the edit; if any differ, or an existing material changed, `review()` sends the model back to
  wrap its change, and the last gate in `chat()` discards the edit with a clear reply if it still leaks.
* Tests: `python3 tests/test_edit_ai.py`.

## Undo

Undo restores the file the edit started from (`pre_url` / `base_url` in the revision), taken back off the deployed
file, never plain `deployed()`: after git sync the deployed file *is* the edit (26 Oct, `0dfc896`: an empty Undo of
the black armchair). The page checks the served files after an Undo and reports an error if they are still the edit's.
