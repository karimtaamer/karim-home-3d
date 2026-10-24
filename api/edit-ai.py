"""Edit AI on Vercel: edit_ai.py's endpoints as one function (vercel.json sends /api/edit-ai/* here); the live
overrides are kept in Vercel Blob under edit-ai-live/."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit_ai  # noqa: E402


class handler(edit_ai.Handler):
    pass
