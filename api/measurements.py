"""Site measurements on Vercel: site_measurements.py's /api/measurements as one function, stored in Vercel Blob under
site-measurements/<version>/."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import site_measurements  # noqa: E402


class handler(site_measurements.Handler):
    pass
