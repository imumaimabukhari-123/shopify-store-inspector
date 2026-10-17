"""
Builds static/shopify-store-inspector.zip (the extension users download from the website),
pointing the extension at the live API.

Usage:  python tools/build_zip.py https://your-site.vercel.app
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "extension")
OUT = os.path.join(ROOT, "static", "shopify-store-inspector.zip")


def main(api: str) -> None:
    api = api.rstrip("/")
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _, files in os.walk(SRC):
            for name in sorted(files):
                path = os.path.join(folder, name)
                arc = os.path.join("shopify-store-inspector", os.path.relpath(path, SRC))
                if name == "config.js":
                    z.writestr(arc, f'// Where the inspector\'s API lives.\nwindow.SSI_API = "{api}";\n')
                else:
                    z.write(path, arc)
    print(f"Built {OUT} for {api}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
