#!/usr/bin/env python3
"""
Pre-build script for Zola photo gallery.
Replaces Jekyll plugins: photo_filter, photo_pages, rename_photos,
destroy_originals, strip_extension, uri_escape.

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

# Configuration
SOURCE_DIR = Path("photos/original")
STATIC_DIR = Path("static")
STATIC_PHOTOS = STATIC_DIR / "photos"
STATIC_JS = STATIC_DIR / "js"
DATA_DIR = Path("data")

SIZES = {
    "large": (2048, 2048),
    "thumbnail": (640, 640),
    "tint": (1, 1),
}


def read_config():
    """Parse config.toml [extra] section for feature flags."""
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
        if stripped.startswith("[") and stripped != "[extra]":
            in_extra = False
            continue
        if in_extra and "=" in stripped:
            key, val = stripped.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"')
            if val == "true":
                config[key] = True
            elif val == "false":
                config[key] = False
            else:
                config[key] = val
    return config


def normalize_extensions():
    """Rename .JPG/.JPEG to .jpg/.jpeg."""
    for ext in ("*.JPG", "*.JPEG"):
        for path in SOURCE_DIR.glob(ext):
            new_path = path.with_suffix(path.suffix.lower())
            if path != new_path:
                path.rename(new_path)
                print(f"  Renamed: {path.name} -> {new_path.name}")


def get_exif_date(filepath):
    """Extract DateTimeOriginal from EXIF, fall back to file mtime."""
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
    """Get image width and height."""
    with Image.open(filepath) as img:
        return img.width, img.height


def slugify(name):
    """Convert filename to URL slug."""
    slug = Path(name).stem.lower()
    slug = re.sub(r'[^a-z0-9\-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def process_image(src_path, slug):
    """Generate large, thumbnail, and tint versions of an image."""
    for size_name, max_dims in SIZES.items():
        out_dir = STATIC_PHOTOS / size_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slug}.jpg"

        if out_path.exists() and out_path.stat().st_mtime > src_path.stat().st_mtime:
            continue

        with Image.open(src_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")

            if size_name == "tint":
                resized = img.resize((1, 1), Image.Resampling.LANCZOS)
            else:
                img.thumbnail(max_dims, Image.Resampling.LANCZOS)
                resized = img

            resized.save(out_path, "JPEG", quality=85)


def generate_photo_html(photo, index, photos, config):
    """Generate the HTML for a single photo <li> element."""
    slug = photo["slug"]
    filename = photo["filename"]
    safe_name = quote(filename)
    width = photo["width"]
    height = photo["height"]

    parts = []
    parts.append(f'<li class="item " id="id-{slug}" '
                 f"style=\"background-image: url('/photos/tint/{safe_name}')\" "
                 f'title="{slug}">')
    parts.append(f'    <img class="lazyload" '
                 f'data-src="/photos/thumbnail/{safe_name}" '
                 f'src="/photos/tint/{safe_name}" '
                 f'height="{height}" width="{width}" />')
    parts.append(f'    <span class="full">')
    parts.append(f"        <span style=\"background-image: url('/photos/large/{safe_name}')\"></span>")
    parts.append(f'    </span>')
    parts.append(f'    <a class="open" href="/{slug}/" data-target="id-{slug}">Open</a>')
    parts.append(f'    <a class="close" href="/">Close</a>')

    if index > 0:
        prev = photos[index - 1]
        parts.append(f'    <a href="/{prev["slug"]}/" data-target="id-{prev["slug"]}" '
                     f'class="previous" title="Go to previous photo">')
        parts.append(f'        <span>Previous</span>')
        parts.append(f'    </a>')

    if index < len(photos) - 1:
        nxt = photos[index + 1]
        parts.append(f'    <a href="/{nxt["slug"]}/" data-target="id-{nxt["slug"]}" '
                     f'class="next" title="Go to next photo">')
        parts.append(f'        <span>Next</span>')
        parts.append(f'    </a>')

    parts.append(f'    <ul class="links top photodetail-links">')
    if config.get("allow_image_sharing"):
        parts.append(f"        <li class=\"share\"><a onClick=\"shareImage('{slug}','/{slug}/');\""
                     f' title="Share this photo">Share</a></li>')
    if config.get("allow_original_download"):
        parts.append(f'        <li class="download"><a href="/photos/original/{safe_name}" '
                     f'download="{safe_name}" class="" title="Download this image">Download</a></li>')
    parts.append(f'    </ul>')

    parts.append(f'    <ul class="meta">')
    if config.get("allow_image_sharing"):
        parts.append(f"        <li><a onClick=\"shareImage('{slug}', '/{slug}/')\" "
                     f'class="gridview-button share" title="Share this image">Share</a></li>')
    if config.get("allow_original_download"):
        parts.append(f'        <li><a href="/photos/original/{safe_name}" '
                     f'download="{safe_name}" class="gridview-button download" '
                     f'title="Download this image">Download</a></li>')
    parts.append(f'    </ul>')
    parts.append(f'</li>')

    return "\n".join(parts)


def generate_photos_js(photos, config):
    """Generate static/js/photos.js with embedded HTML grid."""
    all_html_parts = []
    for i, photo in enumerate(photos):
        html = generate_photo_html(photo, i, photos, config)
        all_html_parts.append(html)

    grid_html = "\n".join(all_html_parts)
    grid_html_escaped = grid_html.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    js_content = f"""(function(html) {{
  const id = document.currentScript.getAttribute('data-photo-id');
  const url = document.currentScript.getAttribute('data-photo-url');
  const target = document.currentScript.getAttribute('data-target-id');
  const container = document.querySelector(`#${{target}}`);
  container.innerHTML = html;
  openPhoto("id-"+id, url);
  lazyload();
}})(`{grid_html_escaped}`);
"""
    STATIC_JS.mkdir(parents=True, exist_ok=True)
    (STATIC_JS / "photos.js").write_text(js_content)


def generate_data_file(photos):
    """Generate data/photos.json for Zola's load_data()."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {"photos": []}
    for i, p in enumerate(photos):
        prev_slug = photos[i - 1]["slug"] if i > 0 else ""
        next_slug = photos[i + 1]["slug"] if i < len(photos) - 1 else ""
        data["photos"].append({
            "slug": p["slug"],
            "filename": p["filename"],
            "width": p["width"],
            "height": p["height"],
            "prev_slug": prev_slug,
            "next_slug": next_slug,
        })

    (DATA_DIR / "photos.json").write_text(json.dumps(data, indent=2))


def generate_photo_page(photo, config):
    """Generate a static HTML page for a single photo at static/{slug}/index.html."""
    slug = photo["slug"]
    filename = photo["filename"]
    safe_name = quote(filename)
    title = slug
    site_title = config.get("title", "art.jimmac.eu")
    description = config.get("description", "")
    base_url = config.get("base_url", "")
    og_image = f"{base_url}/photos/large/{safe_name}"
    mastodon = config.get("mastodon_username", "")
    twitter = config.get("twitter_username", "")
    github = config.get("github_username", "")
    instagram = config.get("instagram_username", "")
    custom_link_name = config.get("custom_link_name", "")
    custom_link_url = config.get("custom_link_url", "")

    # Build the single photo <li> with target class
    photo_html = generate_photo_html(photo, photo["_index"], photo["_all_photos"], config)
    # Set target class on this photo
    photo_html = photo_html.replace(f'<li class="item " id="id-{slug}"',
                                    f'<li class="item target" id="id-{slug}"', 1)

    # Social links
    social_links = []
    if config.get("allow_order_sort_change"):
        social_links.append('<li class="sort"><a rel="me" href="#" title="Reverse sort order">Sort</a></li>')
    if config.get("show_rss_feed"):
        social_links.append(f'<li class="rss"><a rel="alternate" type="application/rss+xml" href="{base_url}/feed.xml" title="RSS Feed">RSS Feed</a></li>')
    if twitter:
        social_links.append(f'<li class="twitter"><a rel="me" href="https://twitter.com/{twitter}" title="@{twitter} on Twitter">Twitter</a></li>')
    if mastodon:
        social_links.append(f'<li class="mastodon"><a rel="me" href="https://mastodon.social/@{mastodon}" title="@{mastodon} on Mastodon">Mastodon</a></li>')
    if github:
        social_links.append(f'<li class="github"><a rel="me" href="https://github.com/{github}" title="@{github} on Github">Github</a></li>')
    if instagram:
        social_links.append(f'<li class="instagram"><a rel="me" href="https://instagram.com/{instagram}" title="@{instagram} on Instagram">Instagram</a></li>')
    if custom_link_url and custom_link_name:
        social_links.append(f'<li class="link"><a rel="me" href="{custom_link_url}" title="{custom_link_name}">{custom_link_name}</a></li>')
    social_html = "\n\t\t\t".join(social_links)

    # Inline JS (same as templates/javascript.html)
    allow_sort_js = ""
    if config.get("allow_order_sort_change"):
        allow_sort_js = """var parent = document.getElementById('target');
    for (var i = 1; i < parent.childNodes.length; i++){
        parent.insertBefore(parent.childNodes[i], parent.firstChild);
    }"""

    share_text = f"I found a cool photo over at {site_title}! Check it out!"

    noindex = ""
    if not config.get("allow_indexing", True):
        noindex = '\n\t<meta name="robots" content="noindex" />'

    page_html = f"""<!doctype html>
<html class="notranslate" translate="no">
<head>
\t<meta charset="utf-8">
\t<meta name="google" content="notranslate" />
\t<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">{noindex}
\t<title data-title="{site_title}">{title}</title>
\t<link rel="alternate" type="application/rss+xml" title="RSS Feed" href="{base_url}/feed.xml">
\t<meta property="og:title" content="{title}">
\t<meta property="og:type" content="website">
\t<meta property="og:url" content="{base_url}/{slug}/">
\t<meta property="og:image" content="{og_image}">
\t<meta property="og:site_name" content="{site_title}">
\t<meta property="og:description" content="{description}">
\t<meta name="thumbnail" content="{og_image}">
\t<meta name="twitter:card" content="summary_large_image">
\t<meta name="twitter:site" content="{twitter}">
\t<meta name="twitter:title" content="{title}">
\t<meta name="twitter:description" content="{description}">
\t<meta name="twitter:image:src" content="{og_image}">
\t<meta name="description" content="{description}">
\t<script type="text/javascript" src="/js/lazy-loading.js"></script>
\t<link rel="stylesheet" type="text/css" media="screen" href="/css/master.css" />
\t<link rel="stylesheet" type="text/css" href="/css/toastify.min.css">
\t<link rel="shortcut icon" type="image/svg+xml" href="/favicon.svg" />
\t<link rel="shortcut icon" type="image/png" href="/favicon.png" />
\t<link rel="apple-touch-icon" href="/touch-icon-iphone.png" />
\t<link rel="mask-icon" href="/favicon.svg" />
\t<link rel="me" href="https://mastodon.social/@{mastodon}">
</head>
<body>
\t<ul class="grid" id="target">
{photo_html}
\t</ul>
\t<ul class="links bottom">
\t\t\t{social_html}
\t\t</ul>
<script>
  const ESCAPE = 27;
  const RIGHT = 39;
  const LEFT = 37;
  const UP = 38;
  const DOWN = 40;
  const TARGET_CLASS = 'target';

  document.addEventListener('touchstart', handleTouchStart, false);
  document.addEventListener('touchmove', handleTouchMove, false);

  var xDown = null;

  function getTouches(evt) {{
      return evt.touches || evt.originalEvent.touches;
  }}

  function handleTouchStart(evt) {{
      const firstTouch = getTouches(evt)[0];
      xDown = firstTouch.clientX;
  }};

  function handleTouchMove(evt) {{
      if ( ! xDown ) {{ return; }}
      var xUp = evt.touches[0].clientX;
      var xDiff = xDown - xUp;
      if ( xDiff > 0 ) {{ clickNavigationButton('.next'); }}
      else {{ clickNavigationButton('.previous'); }}
      xDown = null;
      yDown = null;
  }};

  const shareImage = (title, url) => {{
    if (navigator.canShare) {{
      navigator.share({{ title: title, text: '{share_text}', url: url }})
    }} else {{
      navigator.clipboard.writeText(`{share_text}\\n\\n${{window.location.origin}}${{url}}`);
      Toastify({{ text: "Copied to clipboard", duration: 3000, style: {{ background: "rgba(0, 0, 0, 0.7)" }} }}).showToast();
    }}
  }}

  const clickNavigationButton = (buttonClass) => {{
    const id = window.history.state && window.history.state.id;
    if (id) {{
      const selector = `#${{id}} ${{buttonClass}}`;
      const button = document.querySelector(selector);
      button && button.click();
    }}
  }}

  const openPhoto = (id, href) => {{
    const photo = document.getElementById(id);
    const title = photo.getAttribute('title');
    removeTargetClass();
    photo.classList.add(TARGET_CLASS);
    document.title = title;
    if (href) {{ window.history.pushState({{id: id}}, '', href); }}
  }}

  const closePhoto = (href) => {{
    const title = document.querySelector('head title').getAttribute('data-title');
    removeTargetClass();
    document.title = title;
    if (href) {{ window.history.pushState({{}}, '', href); }}
  }}

  const removeTargetClass = () => {{
    let targets = document.querySelectorAll(`.${{TARGET_CLASS}}`);
    targets.forEach((target) => {{ target.classList.remove(TARGET_CLASS); }});
  }}

  const handleClick = (selector, event, callback) => {{
    if (event.target.matches(selector)) {{ callback(); event.preventDefault(); }}
  }}

  const handleKey = (keyCode, event, callback) => {{
    if (event.keyCode === keyCode) {{ callback(); event.preventDefault(); }}
  }}

  const reverseSorting = () => {{
    {allow_sort_js}
  }}

  window.onpopstate = function(event) {{
    if (event.state && event.state.id) {{ openPhoto(event.state.id, null); }}
    else {{ closePhoto(null); }}
  }}

  document.addEventListener('keydown', (event) => {{
    handleKey(ESCAPE, event, () => {{ clickNavigationButton('.close'); }});
    handleKey(RIGHT, event, () => {{ clickNavigationButton('.next'); }});
    handleKey(LEFT, event, () => {{ clickNavigationButton('.previous'); }});
    handleKey(UP, event, () => {{ reverseSorting(); }});
    handleKey(DOWN, event, () => {{ reverseSorting(); }});
  }});

  document.addEventListener('click', (event) => {{
    handleClick('[data-target][href]', event, () => {{
      const id = event.target.getAttribute('data-target');
      const href = event.target.getAttribute('href');
      openPhoto(id, href);
    }});
    handleClick('[href].close', event, () => {{
      const href = event.target.getAttribute('href');
      closePhoto(href);
    }});
    handleClick('ul.links li.sort a', event, () => {{ reverseSorting(); }});
  }});

  lazyload();
</script>
\t\t<script type="text/javascript" src="/js/toastify.js"></script>
\t\t<script src="/js/photos.js" data-photo-id="{slug}" data-photo-url="/{slug}/" data-target-id="target"></script>
</body>
</html>
"""
    out_dir = STATIC_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page_html)


def generate_photos_js(photos, config):
    """Generate static/js/photos.js with embedded HTML grid."""
    all_html_parts = []
    for i, photo in enumerate(photos):
        html = generate_photo_html(photo, i, photos, config)
        all_html_parts.append(html)

    grid_html = "\n".join(all_html_parts)
    grid_html_escaped = grid_html.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    js_content = f"""(function(html) {{
  const id = document.currentScript.getAttribute('data-photo-id');
  const url = document.currentScript.getAttribute('data-photo-url');
  const target = document.currentScript.getAttribute('data-target-id');
  const container = document.querySelector(`#${{target}}`);
  container.innerHTML = html;
  openPhoto("id-"+id, url);
  lazyload();
}})(`{grid_html_escaped}`);
"""
    STATIC_JS.mkdir(parents=True, exist_ok=True)
    (STATIC_JS / "photos.js").write_text(js_content)


def main():
    if not SOURCE_DIR.exists():
        print(f"Error: Source directory '{SOURCE_DIR}' not found.")
        sys.exit(1)

    config = read_config()
    # Also pass top-level config values for photo page generation
    config_path = Path("config.toml")
    if config_path.exists():
        for line in config_path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                break
            if "=" in stripped:
                key, val = stripped.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"')
                config[key] = val

    print("=== Zola Pre-build Script ===\n")

    # Step 1: Normalize extensions
    print("1. Normalizing file extensions...")
    normalize_extensions()

    # Step 2: Scan photos and extract metadata
    print("2. Scanning photos and extracting EXIF data...")
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
    print(f"   Found {len(photos)} photos")

    # Sort by EXIF date, newest first
    photos.sort(key=lambda p: p["exif_date"], reverse=True)

    # Step 3: Process images
    print("3. Processing images...")
    for i, photo in enumerate(photos):
        sys.stdout.write(f"\r   Processing {i+1}/{len(photos)}: {photo['filename']}...")
        sys.stdout.flush()
        process_image(photo["source_path"], photo["slug"])
    print("\n   Done!")

    # Step 4: Copy originals if downloads enabled
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

    # Step 5: Generate data file for Zola's load_data()
    print("5. Generating data/photos.json...")
    generate_data_file(photos)

    # Step 6: Generate photos.js
    print("6. Generating photos.js...")
    generate_photos_js(photos, config)

    # Step 7: Generate individual photo pages as static HTML
    print("7. Generating photo pages...")
    for i, photo in enumerate(photos):
        photo["_index"] = i
        photo["_all_photos"] = photos
        generate_photo_page(photo, config)
    print(f"   Generated {len(photos)} photo pages")

    print(f"\n=== Pre-build complete: {len(photos)} photos processed ===")


if __name__ == "__main__":
    main()
