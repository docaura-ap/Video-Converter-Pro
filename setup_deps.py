"""
Download React, ReactDOM and Babel into frontend/lib/ for offline use.
Run once before building: python setup_deps.py
"""
import os
import urllib.request

LIB_DIR = os.path.join(os.path.dirname(__file__), "frontend", "lib")
os.makedirs(LIB_DIR, exist_ok=True)

LIBS = [
    (
        "react.production.min.js",
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
    ),
    (
        "react-dom.production.min.js",
        "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
    ),
    (
        "babel.min.js",
        "https://unpkg.com/@babel/standalone@7.29.0/babel.min.js",
    ),
]

for filename, url in LIBS:
    dest = os.path.join(LIB_DIR, filename)
    if os.path.exists(dest):
        print(f"  OK {filename} already present")
        continue
    print(f"  Downloading {filename} ...", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest) / 1024
        print(f"OK ({size:.0f} KB)")
    except Exception as e:
        print(f"FAILED: {e}")

print("\nDone. You can now run the app or build the EXE.")
