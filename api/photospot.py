"""Generate Photo Spot on Vercel: photogen.py's endpoints as one function (vercel.json sends /api/photospot/*
here), keeping renders/ in Vercel Blob."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import photogen  # noqa: E402


class handler(photogen.Handler):
    pass
