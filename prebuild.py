#!/usr/bin/env python3
"""
Pre-build script for Zola photo gallery.
Scans photos/original/, extracts EXIF dates, generates thumbnails,
and produces data/photos.json + per-photo static HTML pages.

Requires: pip install Pillow
"""

import json
import os
import sys
import shutil
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

SOURCE_DIR = Path("photos/original")
STATIC_DIR = Path("static")
STATIC_PHOTOS = STATIC_DIR / "photos"
STATIC_JS = STATIC_DIR / "js"
DATA_DIR = Path("data")

SIZES = {
    "large": (2048, 2048),
    "thumbnail": (640, 640),
}


def read_config():
    """Parse config.toml for site settings."""
    config = {}
    in_extra = False
    config_path = Path("config.toml")
    if not config_path.exists():
        return config
    for line in config_path.read_text().splitlines():
        stripped = line.strip()
        if stripped == "[extra]":
            in_extra = True
            continue
        if stripped.startswith("["):
            in_extra = False
            continue
        if "=" in stripped:
            key, val = stripped.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"')
            if val == "true":
                val = True
            elif val == "false":
                val = False
            if in_extra or not stripped.startswith("["):
                config[key] = val
    return config


def normalize_extensions():
    for ext in ("*.JPG", "*.JPEG"):
        for path in SOURCE_DIR.glob(ext):
            new_path = path.with_suffix(path.suffix.lower())
            if path != new_path:
                path.rename(new_path)
                print(f"  Renamed: {path.name} -> {new_path.name}")


def get_exif_date(filepath):
    try:
        img = Image.open(filepath)
        exif = img._getexif()
        if exif:
            dto = exif.get(36867) or exif.get(36868)
            if dto:
                return datetime.strptime(dto, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.fromtimestamp(os.path.getmtime(filepath))


def get_dimensions(filepath):
    with Image.open(filepath) as img:
        return img.width, img.height


def slugify(name):
    slug = Path(name).stem.lower()
    slug = re.sub(r'[^a-z0-9\-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def process_image(src_path, slug):
    for size_name, max_dims in SIZES.items():
        out_dir = STATIC_PHOTOS / size_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slug}.jpg"

        if out_path.exists() and out_path.stat().st_mtime > src_path.stat().st_mtime:
            continue

        with Image.open(src_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail(max_dims, Image.Resampling.LANCZOS)
            img.save(out_path, "JPEG", quality=85)


def generate_photo_html(photo, index, photos, config):
    """Generate the HTML for a single photo <li> element."""
    slug = photo["slug"]
    safe_name = quote(photo["filename"])
    w, h = photo["width"], photo["height"]

    lines = [
        f'<li class="item" id="id-{slug}" title="{slug}">',
        f'    <img loading="lazy"',
        f'         src="/photos/thumbnail/{safe_name}"',
        f'         srcset="/photos/thumbnail/{safe_name} 640w, /photos/large/{safe_name} 2048w"',
        f'         sizes="(min-width: 900px) 33vw, (min-width: 600px) 50vw, 100vw"',
        f'         width="{w}" height="{h}" alt="{slug}" />',
        f'    <a class="open" href="/{slug}/" data-target="id-{slug}">Open</a>',
        f'    <a class="close" href="/">Close</a>',
    ]

    if index > 0:
        ps = photos[index - 1]["slug"]
        lines.append(f'    <a href="/{ps}/" data-target="id-{ps}" class="previous" title="Previous"><span>Previous</span></a>')

    if index < len(photos) - 1:
        ns = photos[index + 1]["slug"]
        lines.append(f'    <a href="/{ns}/" data-target="id-{ns}" class="next" title="Next"><span>Next</span></a>')

    lines.append(f'    <div class="actions">')
    if config.get("allow_image_sharing"):
        lines.append(f'        <a class="share" href="#" data-share-slug="/{slug}/" data-share-title="{slug}" title="Share">Share</a>')
    if config.get("allow_original_download"):
        lines.append(f'        <a class="download" href="/photos/original/{safe_name}" download="{safe_name}" title="Download">Download</a>')
    lines.append(f'    </div>')
    lines.append(f'</li>')

    return "\n".join(lines)


def generate_photos_js(photos, config):
    """Generate static/js/photos.js — embeds full grid HTML for direct-link pages."""
    all_html = "\n".join(
        generate_photo_html(p, i, photos, config) for i, p in enumerate(photos)
    )
    escaped = all_html.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    js = f"""(function(html) {{
  const id = document.currentScript.getAttribute('data-photo-id');
  const url = document.currentScript.getAttribute('data-photo-url');
  const target = document.currentScript.getAttribute('data-target-id');
  document.querySelector(`#${{target}}`).innerHTML = html;
  openPhoto("id-" + id, url);
}})(`{escaped}`);
"""
    STATIC_JS.mkdir(parents=True, exist_ok=True)
    (STATIC_JS / "photos.js").write_text(js)


def generate_data_file(photos):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {"photos": []}
    for i, p in enumerate(photos):
        data["photos"].append({
            "slug": p["slug"],
            "filename": p["filename"],
            "width": p["width"],
            "height": p["height"],
            "prev_slug": photos[i - 1]["slug"] if i > 0 else "",
            "next_slug": photos[i + 1]["slug"] if i < len(photos) - 1 else "",
        })
    (DATA_DIR / "photos.json").write_text(json.dumps(data, indent=2))


def generate_photo_page(photo, index, photos, config, output_base):
    """Generate a static HTML page for direct-link access to a photo."""
    slug = photo["slug"]
    safe_name = quote(photo["filename"])
    site_title = config.get("title", "art.jimmac.eu")
    description = config.get("description", "")
    base_url = config.get("base_url", "")
    og_image = f"{base_url}/photos/large/{safe_name}"
    mastodon = config.get("mastodon_username", "")

    photo_html = generate_photo_html(photo, index, photos, config)
    photo_html = photo_html.replace(
        f'<li class="item" id="id-{slug}"',
        f'<li class="item target" id="id-{slug}"', 1
    )

    # Social links
    social = []
    if mastodon:
        social.append(f'<li class="mastodon"><a rel="me" href="https://mastodon.social/@{mastodon}" title="Mastodon">Mastodon</a></li>')
    github = config.get("github_username", "")
    if github:
        social.append(f'<li class="github"><a rel="me" href="https://github.com/{github}" title="Github">Github</a></li>')
    instagram = config.get("instagram_username", "")
    if instagram:
        social.append(f'<li class="instagram"><a rel="me" href="https://instagram.com/{instagram}" title="Instagram">Instagram</a></li>')
    cname = config.get("custom_link_name", "")
    curl = config.get("custom_link_url", "")
    if cname and curl:
        social.append(f'<li class="link"><a rel="me" href="{curl}" title="{cname}">{cname}</a></li>')
    social_html = "\n\t\t".join(social)

    noindex = ""
    if not config.get("allow_indexing", True):
        noindex = '\n\t<meta name="robots" content="noindex" />'

    share_text = f"Check out this photo at {site_title}!"

    page = f"""<!doctype html>
<html class="notranslate" translate="no">
<head>
\t<meta charset="utf-8">
\t<meta name="google" content="notranslate" />
\t<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">{noindex}
\t<title data-title="{site_title}">{slug}</title>
\t<link rel="alternate" type="application/rss+xml" title="RSS Feed" href="{base_url}/feed.xml">
\t<meta property="og:title" content="{slug}">
\t<meta property="og:type" content="website">
\t<meta property="og:url" content="{base_url}/{slug}/">
\t<meta property="og:image" content="{og_image}">
\t<meta property="og:site_name" content="{site_title}">
\t<meta property="og:description" content="{description}">
\t<meta name="thumbnail" content="{og_image}">
\t<meta name="twitter:card" content="summary_large_image">
\t<meta name="twitter:title" content="{slug}">
\t<meta name="twitter:description" content="{description}">
\t<meta name="twitter:image" content="{og_image}">
\t<meta name="description" content="{description}">
\t<link rel="stylesheet" type="text/css" media="screen" href="/css/master.css" />
\t<link rel="shortcut icon" type="image/svg+xml" href="/favicon.svg" />
\t<link rel="shortcut icon" type="image/png" href="/favicon.png" />
\t<link rel="apple-touch-icon" href="/touch-icon-iphone.png" />
\t<link rel="mask-icon" href="/favicon.svg" />
\t<link rel="me" href="https://mastodon.social/@{mastodon}">
</head>
<body>
\t<ul class="grid" id="grid">
{photo_html}
\t</ul>
\t<ul class="links">
\t\t{social_html}
\t</ul>
<script>
  const TARGET_CLASS = 'target';
  let xDown = null;
  document.addEventListener('touchstart', (e) => {{ xDown = e.touches[0].clientX; }});
  document.addEventListener('touchmove', (e) => {{
    if (!xDown) return;
    const diff = xDown - e.touches[0].clientX;
    if (diff > 0) clickNav('.next'); else clickNav('.previous');
    xDown = null;
  }});
  const shareImage = (title, url) => {{
    const text = '{share_text}';
    if (navigator.canShare) {{ navigator.share({{ title, text, url }}); }}
    else {{ navigator.clipboard.writeText(`${{text}}\\n\\n${{window.location.origin}}${{url}}`); }}
  }};
  const clickNav = (cls) => {{
    const id = window.history.state?.id;
    if (id) {{ const btn = document.querySelector(`#${{id}} ${{cls}}`); btn?.click(); }}
  }};
  const openPhoto = (id, href) => {{
    const photo = document.getElementById(id);
    removeTargetClass();
    photo.classList.add(TARGET_CLASS);
    const img = photo.querySelector('img');
    if (img) {{
      img.dataset.thumb = img.src;
      img.dataset.srcset = img.getAttribute('srcset') || '';
      img.dataset.sizes = img.getAttribute('sizes') || '';
      img.removeAttribute('srcset');
      img.removeAttribute('sizes');
      img.src = img.dataset.thumb.replace('/photos/thumbnail/', '/photos/large/');
    }}
    document.title = photo.title;
    if (href) window.history.pushState({{ id }}, '', href);
  }};
  const closePhoto = (href) => {{
    document.querySelectorAll(`.${{TARGET_CLASS}} img[data-thumb]`).forEach(img => {{
      img.src = img.dataset.thumb;
      if (img.dataset.srcset) img.setAttribute('srcset', img.dataset.srcset);
      if (img.dataset.sizes) img.setAttribute('sizes', img.dataset.sizes);
      delete img.dataset.thumb; delete img.dataset.srcset; delete img.dataset.sizes;
    }});
    removeTargetClass();
    document.title = document.querySelector('title').dataset.title;
    if (href) window.history.pushState({{}}, '', href);
  }};
  const removeTargetClass = () => {{
    document.querySelectorAll(`.${{TARGET_CLASS}}`).forEach(el => el.classList.remove(TARGET_CLASS));
  }};
  window.onpopstate = (e) => {{
    if (e.state?.id) openPhoto(e.state.id, null); else closePhoto(null);
  }};
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape') {{ clickNav('.close'); e.preventDefault(); }}
    if (e.key === 'ArrowRight') {{ clickNav('.next'); e.preventDefault(); }}
    if (e.key === 'ArrowLeft') {{ clickNav('.previous'); e.preventDefault(); }}
  }});
  document.addEventListener('click', (e) => {{
    const t = e.target.closest('[data-target][href]');
    if (t) {{ e.preventDefault(); openPhoto(t.dataset.target, t.getAttribute('href')); return; }}
    if (e.target.matches('.close[href]')) {{ e.preventDefault(); closePhoto(e.target.getAttribute('href')); return; }}
    const s = e.target.closest('[data-share-slug]');
    if (s) {{ e.preventDefault(); shareImage(s.dataset.shareTitle, s.dataset.shareSlug); }}
  }});
</script>
\t<script src="/js/photos.js" data-photo-id="{slug}" data-photo-url="/{slug}/" data-target-id="grid"></script>
</body>
</html>
"""
    out_dir = output_base / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page)


def scan_and_sort_photos():
    """Scan source directory and return sorted photo list."""
    jpg_files = sorted(SOURCE_DIR.glob("*.jpg"))
    if not jpg_files:
        print("   No JPG files found!")
        sys.exit(1)

    photos = []
    for filepath in jpg_files:
        slug = slugify(filepath.name)
        exif_date = get_exif_date(filepath)
        width, height = get_dimensions(filepath)
        photos.append({
            "slug": slug,
            "filename": filepath.name,
            "width": width,
            "height": height,
            "exif_date": exif_date,
            "source_path": filepath,
        })

    photos.sort(key=lambda p: p["exif_date"], reverse=True)
    return photos


def main():
    if not SOURCE_DIR.exists():
        print(f"Error: Source directory '{SOURCE_DIR}' not found.")
        sys.exit(1)

    config = read_config()

    # --pages mode: only generate photo pages into public/
    if len(sys.argv) > 1 and sys.argv[1] == "--pages":
        output_base = Path("public")
        print("=== Generating photo pages into public/ ===\n")
        photos = scan_and_sort_photos()
        print(f"   Found {len(photos)} photos")
        for i, photo in enumerate(photos):
            generate_photo_page(photo, i, photos, config, output_base)
        print(f"   Generated {len(photos)} photo pages")
        return

    # Normal pre-build mode
    print("=== Zola Pre-build Script ===\n")

    print("1. Normalizing file extensions...")
    normalize_extensions()

    print("2. Scanning photos and extracting EXIF data...")
    photos = scan_and_sort_photos()
    print(f"   Found {len(photos)} photos")

    print("3. Processing images...")
    for i, photo in enumerate(photos):
        sys.stdout.write(f"\r   Processing {i+1}/{len(photos)}: {photo['filename']}...")
        sys.stdout.flush()
        process_image(photo["source_path"], photo["slug"])
    print("\n   Done!")

    if config.get("allow_original_download"):
        print("4. Copying originals for download...")
        orig_dir = STATIC_PHOTOS / "original"
        orig_dir.mkdir(parents=True, exist_ok=True)
        for photo in photos:
            src = photo["source_path"]
            dst = orig_dir / photo["filename"]
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(src, dst)
    else:
        print("4. Skipping originals (download disabled)")

    print("5. Generating data/photos.json...")
    generate_data_file(photos)

    print("6. Generating photos.js...")
    generate_photos_js(photos, config)

    print(f"\n=== Pre-build complete: {len(photos)} photos processed ===")


if __name__ == "__main__":
    main()
