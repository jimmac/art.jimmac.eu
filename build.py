#!/usr/bin/env python3
"""
Build script for art.jimmac.eu picture gallery.
Scans pictures/original/, extracts EXIF dates, generates thumbnails,
and produces a complete static site in public/.

Requires: pip install Pillow
"""

import os
import sys
import shutil
import re
import subprocess
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
from html import escape as html_escape

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

SOURCE_DIR = Path("pictures/original")
STATIC_DIR = Path("static")
OUTPUT_DIR = Path("public")

SIZES = {
    "large": (2048, 2048),
    "thumbnail": (640, 640),
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif", ".avif", ".heic", ".heif",
}

VIDEO_EXTENSIONS = {".mp4", ".webm", ".avi", ".mov"}


CONFIG = {
    "base_url": "https://art.jimmac.eu",
    "title": "art.jimmac.eu",
    "description": "Art by @jimmac",
    "author_name": "Jakub Steiner",
    "author_email": "jimmac@gmail.com",
    "author_website": "https://jimmac.eu",
    "allow_indexing": True,
    "allow_image_sharing": True,
    "allow_original_download": False,
    "mastodon_username": "jimmac",
    "github_username": "jimmac",
    "instagram_username": "jimmacfx",
    "pixelfed_username": "jimmac",
    "custom_link_name": "jimmac",
    "custom_link_url": "https://jimmac.eu",
}


def get_video_info(filepath):
    """Get duration and dimensions of a video file via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(filepath)],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(result.stdout)
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                w = int(s["width"])
                h = int(s["height"])
                duration = float(info.get("format", {}).get("duration", s.get("duration", "0")))
                return w, h, duration
    except Exception:
        pass
    return 640, 640, 0.0


def extract_video_thumbnail(src_path, out_path, max_dims, duration):
    """Extract a thumbnail from the middle of a video."""
    timestamp = duration / 2 if duration > 0 else 0
    scale = f"scale='min({max_dims[0]},iw)':'min({max_dims[1]},ih)':force_original_aspect_ratio=decrease"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(timestamp), "-i", str(src_path),
         "-vframes", "1", "-vf", scale, str(out_path)],
        capture_output=True, timeout=30,
    )


def normalize_extensions():
    for path in SOURCE_DIR.iterdir():
        if path.suffix.lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS) and path.suffix != path.suffix.lower():
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


def inline_markdown(text):
    """Convert inline markdown (links, code, bold, italic) to HTML."""
    text = html_escape(text)
    # inline code: `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # links: [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    # bold: **text** or __text__
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    # italic: *text* or _text_
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<em>\1</em>', text)
    return text


def strip_markdown(text):
    """Strip markdown formatting to plain text (for meta tags)."""
    # Extract link text from [text](url)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Remove bold markers
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    # Remove italic markers
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', text)
    return text


def parse_sidecar(sidecar_path):
    """Parse a markdown sidecar file with optional YAML-like front matter."""
    text = sidecar_path.read_text(encoding="utf-8")
    meta = {}
    body = text

    # Extract front matter between --- delimiters
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            current_key = None
            for line in parts[1].strip().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                # List item (  - value)
                if stripped.startswith("- ") and current_key:
                    meta.setdefault(current_key, []).append(stripped[2:].strip())
                elif ":" in stripped:
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    current_key = key
                    if val:
                        meta[key] = val
            body = parts[2].strip()

    # Extract title from first # heading, rest is description
    title = None
    description_lines = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
        elif title is not None:
            description_lines.append(line)

    description = "\n".join(description_lines).strip()

    # Normalize software to list
    software = meta.get("software", [])
    if isinstance(software, str):
        software = [software]

    year = meta.get("year")
    if year is not None:
        try:
            year = int(year)
        except (ValueError, TypeError):
            year = None

    return {
        "title": title,
        "description": description if description else None,
        "author": meta.get("author"),
        "software": software,
        "year": year,
        "tags": meta.get("tags", []) if isinstance(meta.get("tags"), list) else [meta["tags"]] if "tags" in meta else [],
        "has_metadata": True,
    }


def scan_and_sort_pictures():
    """Scan source directory and return sorted picture list."""
    all_files = sorted(
        p for p in SOURCE_DIR.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    )
    if not all_files:
        print("   No image/video files found!")
        sys.exit(1)

    pictures = []
    for filepath in all_files:
        slug = slugify(filepath.name)
        suffix = filepath.suffix.lower()
        is_video = suffix in VIDEO_EXTENSIONS

        if is_video:
            width, height, duration = get_video_info(filepath)
            exif_date = datetime.fromtimestamp(os.path.getmtime(filepath))
            video_ext = suffix if suffix in (".mp4", ".webm") else ".mp4"
            pictures.append({
                "slug": slug,
                "filename": f"{slug}.webp",
                "video_src": f"{slug}{video_ext}",
                "width": width,
                "height": height,
                "duration": duration,
                "exif_date": exif_date,
                "source_path": filepath,
                "is_video": True,
            })
        else:
            exif_date = get_exif_date(filepath)
            width, height = get_dimensions(filepath)
            ext = ".gif" if suffix == ".gif" else ".webp"
            pictures.append({
                "slug": slug,
                "filename": f"{slug}{ext}",
                "width": width,
                "height": height,
                "exif_date": exif_date,
                "source_path": filepath,
                "is_video": False,
            })

        # Check for sidecar metadata file
        sidecar_path = filepath.with_suffix(".md")
        if sidecar_path.exists():
            pictures[-1].update(parse_sidecar(sidecar_path))
        else:
            pictures[-1].update({"has_metadata": False, "title": None, "description": None})

    def sort_key(p):
        d = p["exif_date"]
        year = p.get("year")
        if year is not None:
            d = d.replace(year=year)
        return d
    pictures.sort(key=sort_key, reverse=True)
    return pictures


def process_image(pic):
    src_path = pic["source_path"]
    slug = pic["slug"]

    if pic.get("is_video"):
        duration = pic.get("duration", 0)
        suffix = src_path.suffix.lower()
        needs_transcode = suffix in (".avi", ".mov")
        video_ext = ".mp4" if needs_transcode else suffix
        # Copy or transcode video to large/
        large_dir = OUTPUT_DIR / "pictures" / "large"
        large_dir.mkdir(parents=True, exist_ok=True)
        video_dst = large_dir / f"{slug}{video_ext}"
        if not video_dst.exists() or video_dst.stat().st_mtime < src_path.stat().st_mtime:
            if needs_transcode:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src_path),
                     "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                     "-c:a", "aac", "-movflags", "+faststart", str(video_dst)],
                    capture_output=True, timeout=300,
                )
            else:
                shutil.copy2(src_path, video_dst)
        # Generate thumbnail for grid
        for size_name, max_dims in SIZES.items():
            out_dir = OUTPUT_DIR / "pictures" / size_name
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{slug}.webp"
            if out_path.exists() and out_path.stat().st_mtime > src_path.stat().st_mtime:
                continue
            extract_video_thumbnail(src_path, out_path, max_dims, duration)
        return

    is_gif = src_path.suffix.lower() == ".gif"
    for size_name, max_dims in SIZES.items():
        out_dir = OUTPUT_DIR / "pictures" / size_name
        out_dir.mkdir(parents=True, exist_ok=True)

        if is_gif:
            out_path = out_dir / f"{slug}.gif"
            if out_path.exists() and out_path.stat().st_mtime > src_path.stat().st_mtime:
                continue
            shutil.copy2(src_path, out_path)
        else:
            out_path = out_dir / f"{slug}.webp"
            if out_path.exists() and out_path.stat().st_mtime > src_path.stat().st_mtime:
                continue
            with Image.open(src_path) as img:
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if img.mode in ("LA", "PA") or "transparency" in img.info else "RGB")
                img.thumbnail(max_dims, Image.Resampling.LANCZOS)
                img.save(out_path, "WEBP", quality=85)


def copy_static_assets():
    """Copy static assets (CSS, icons, favicons) to public/."""
    for subdir in ("css", "img"):
        src = STATIC_DIR / subdir
        dst = OUTPUT_DIR / subdir
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    for filename in ("favicon.png", "social-preview.png", "touch-icon-iphone.png"):
        src = STATIC_DIR / filename
        if src.exists():
            shutil.copy2(src, OUTPUT_DIR / filename)


def copy_originals(pictures):
    """Copy original pictures for download."""
    orig_dir = OUTPUT_DIR / "pictures" / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    for pic in pictures:
        src = pic["source_path"]
        dst = orig_dir / src.name
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dst)


def generate_picture_html(pic, index, pictures, config):
    """Generate the HTML for a single picture <li> element."""
    slug = pic["slug"]
    safe_name = quote(pic["filename"])
    w, h = pic["width"], pic["height"]
    is_video = pic.get("is_video", False)
    has_meta = pic.get("has_metadata", False)
    display_name = html_escape(pic.get("title") or slug)

    extra_attrs = ""
    if is_video:
        video_src = quote(pic["video_src"])
        extra_attrs += f' data-video="/pictures/large/{video_src}"'
    if has_meta:
        extra_attrs += ' data-has-meta="true"'

    lines = [
        f'      <li class="item" id="id-{slug}" title="{display_name}"{extra_attrs}>',
        f'        <figure>',
        f'          <img loading="lazy"',
        f'               src="/pictures/thumbnail/{safe_name}"',
        f'               srcset="/pictures/thumbnail/{safe_name} 640w, /pictures/large/{safe_name} 2048w"',
        f'               sizes="(min-width: 900px) 33vw, (min-width: 600px) 50vw, 100vw"',
        f'               width="{w}" height="{h}" alt="{display_name}">',
    ]

    if has_meta:
        lines.append(f'          <figcaption class="caption">')
        pin_btn = '<button class="caption-pin" aria-label="Pin caption" title="Pin caption"></button>'
        if pic.get("title"):
            lines.append(f'            <strong class="caption-title">{html_escape(pic["title"])}{pin_btn}</strong>')
        elif pic.get("description"):
            lines.append(f'            {pin_btn}')
        if pic.get("description"):
            lines.append(f'            <span class="caption-desc">{inline_markdown(pic["description"])}</span>')
        year = pic.get("year") or (pic["exif_date"].year if pic.get("exif_date") else None)
        software = pic.get("software")
        if year or software:
            meta_parts = ""
            if year:
                meta_parts += f'<span class="caption-year">{year}</span>'
            if software:
                meta_parts += "".join(f'<span class="badge">{html_escape(s)}</span>' for s in software)
            lines.append(f'            <span class="caption-meta">{meta_parts}</span>')
        lines.append(f'          </figcaption>')

    lines.append(f'        </figure>')
    lines.append(f'        <a class="open" href="#{slug}" data-target="id-{slug}">Open</a>')

    if index > 0:
        ps = pictures[index - 1]["slug"]
        lines.append(f'        <a href="#{ps}" class="previous" title="Previous"><span class="button large">Previous</span></a>')

    if index < len(pictures) - 1:
        ns = pictures[index + 1]["slug"]
        lines.append(f'        <a href="#{ns}" class="next" title="Next"><span class="button large">Next</span></a>')

    lines.append(f'        <div class="actions">')
    if config.get("allow_image_sharing"):
        lines.append(f'          <a class="button share" href="#" data-share-slug="{slug}" data-share-title="{display_name}" title="Share">Share</a>')
    if config.get("allow_original_download"):
        orig_name = quote(pic["source_path"].name)
        lines.append(f'          <a class="button download" href="/pictures/original/{orig_name}" download="{orig_name}" title="Download">Download</a>')
    lines.append(f'          <a class="button close" href="#" title="Close">Close</a>')
    lines.append(f'        </div>')
    lines.append(f'      </li>')

    return "\n".join(lines)


def generate_javascript(config):
    """Generate the inline JavaScript for the gallery."""
    site_title = config.get("title", "art.jimmac.eu")

    return f"""<script>
  const TARGET_CLASS = 'target';

  let xDown = null;
  document.addEventListener('touchstart', (e) => {{
    if (currentId()) xDown = e.touches[0].clientX;
  }});
  document.addEventListener('touchmove', (e) => {{
    if (!xDown) return;
    e.preventDefault();
    const diff = xDown - e.touches[0].clientX;
    if (Math.abs(diff) < 30) return;
    if (diff > 0) {{ navDirection = 'next'; clickNav('.next'); }}
    else {{ navDirection = 'prev'; clickNav('.previous'); }}
    xDown = null;
  }}, {{ passive: false }});

  const showToast = (msg) => {{
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    document.body.appendChild(el);
    el.addEventListener('animationend', () => el.remove());
  }};

  const shareImage = (title, slug) => {{
    const url = window.location.origin + '/' + slug + '/';
    if (navigator.canShare) {{
      navigator.share({{ title, url }});
    }} else {{
      navigator.clipboard.writeText(url).then(() => showToast('Link copied to clipboard'));
    }}
  }};

  const currentId = () => {{
    const hash = location.hash.slice(1);
    return hash ? 'id-' + hash : null;
  }};

  const clickNav = (cls) => {{
    const id = currentId();
    if (id) {{
      const btn = document.querySelector('#' + CSS.escape(id) + ' ' + cls);
      btn?.click();
    }}
  }};

  const tintCanvas = document.createElement('canvas');
  const tintCtx = tintCanvas.getContext('2d', {{ willReadFrequently: true }});

  const avgColor = (img) => {{
    try {{
      const w = Math.min(img.naturalWidth, 64);
      const h = Math.min(img.naturalHeight, 64);
      tintCanvas.width = w;
      tintCanvas.height = h;
      tintCtx.drawImage(img, 0, 0, w, h);
      const data = tintCtx.getImageData(0, 0, w, h).data;
      let r = 0, g = 0, b = 0, n = 0;
      for (let x = 0; x < w; x++) {{
        for (const y of [0, h - 1]) {{
          const i = (y * w + x) * 4;
          r += data[i]; g += data[i+1]; b += data[i+2]; n++;
        }}
      }}
      for (let y = 1; y < h - 1; y++) {{
        for (const x of [0, w - 1]) {{
          const i = (y * w + x) * 4;
          r += data[i]; g += data[i+1]; b += data[i+2]; n++;
        }}
      }}
      return `rgb(${{Math.round(r/n)}},${{Math.round(g/n)}},${{Math.round(b/n)}})`;
    }} catch (e) {{ return null; }}
  }};

  let navDirection = null;
  let captionTimer = null;
  let captionPinned = false;
  let captionManuallyHidden = false;

  const showCaption = (item, animate) => {{
    const caption = item.querySelector('.caption');
    if (!caption) return;
    caption.classList.remove('faded');
    const kids = caption.querySelectorAll(':scope > *');
    if (animate) {{
      kids.forEach(c => {{ c.style.animation = 'none'; c.offsetHeight; c.style.animation = ''; }});
    }} else {{
      kids.forEach(c => c.style.animation = 'none');
    }}

    // Show pager and action buttons
    const previous = item.querySelector('.previous');
    const next = item.querySelector('.next');
    const actions = item.querySelector('.actions');
    if (previous) previous.classList.remove('faded');
    if (next) next.classList.remove('faded');
    if (actions) actions.classList.remove('faded');

    clearTimeout(captionTimer);
    if (!captionPinned) {{
      // Calculate dynamic timeout based on caption text length
      const title = caption.querySelector('.caption-title');
      const desc = caption.querySelector('.caption-desc');
      let charCount = 0;
      if (title) charCount += title.textContent.length;
      if (desc) charCount += desc.textContent.length;

      // Base calculation: ~32 characters per second (roughly 6.4 words/sec)
      // Min: 2s for very short captions, Max: 6s for very long captions
      const baseTimeout = charCount * (1000 / 32);
      const timeout = Math.max(2000, Math.min(6000, baseTimeout));

      captionTimer = setTimeout(() => {{
        caption.classList.add('faded');
        if (previous) previous.classList.add('faded');
        if (next) next.classList.add('faded');
        if (actions) actions.classList.add('faded');
      }}, timeout);
    }}
  }};

  const hideCaption = (item) => {{
    const caption = item.querySelector('.caption');
    if (!caption) return;
    caption.classList.add('faded');

    // Hide pager and action buttons
    const previous = item.querySelector('.previous');
    const next = item.querySelector('.next');
    const actions = item.querySelector('.actions');
    if (previous) previous.classList.add('faded');
    if (next) next.classList.add('faded');
    if (actions) actions.classList.add('faded');

    clearTimeout(captionTimer);
  }};

  const toggleCaption = () => {{
    const id = currentId();
    if (!id) return;
    const item = document.getElementById(id);
    if (!item) return;
    const caption = item.querySelector('.caption');
    if (!caption) return;
    if (caption.classList.contains('faded')) {{
      captionManuallyHidden = false;
      showCaption(item);
    }} else {{
      captionManuallyHidden = true;
      captionPinned = false;
      item.querySelectorAll('.caption-pin.pinned').forEach(p => p.classList.remove('pinned'));
      hideCaption(item);
    }}
  }};

  const setMeta = (prop, content) => {{
    const el = document.querySelector('meta[property="' + prop + '"],meta[name="' + prop + '"]');
    if (el) el.setAttribute('content', content);
  }};

  const updateMeta = (slug, imgUrl) => {{
    const url = window.location.origin + '/' + slug + '/';
    setMeta('og:title', slug);
    setMeta('og:url', url);
    setMeta('og:image', imgUrl);
    setMeta('twitter:title', slug);
    setMeta('twitter:image', imgUrl);
    setMeta('thumbnail', imgUrl);
  }};

  const resetMeta = () => {{
    const t = document.querySelector('title');
    const title = t.dataset.title;
    const origin = window.location.origin;
    const preview = origin + '/social-preview.png';
    setMeta('og:title', title);
    setMeta('og:url', origin + '/');
    setMeta('og:image', preview);
    setMeta('twitter:title', title);
    setMeta('twitter:image', preview);
    setMeta('thumbnail', preview);
  }};

  const openPhoto = (id) => {{
    const photo = document.getElementById(id);
    if (!photo) return;
    removeTargetClass();
    captionPinned = false;
    captionManuallyHidden = false;
    document.querySelectorAll('.caption-pin.pinned').forEach(p => p.classList.remove('pinned'));
    document.body.style.overflow = 'hidden';
    photo.classList.add(TARGET_CLASS);
    if (navDirection) {{
      photo.classList.add(navDirection === 'next' ? 'slide-next' : 'slide-prev');
      photo.addEventListener('animationend', () => {{
        photo.classList.remove('slide-next', 'slide-prev');
      }}, {{ once: true }});
      navDirection = null;
    }}
    const videoSrc = photo.dataset.video;
    const img = photo.querySelector('img');
    if (img) {{
      const tint = avgColor(img);
      if (tint) photo.style.backgroundColor = tint;
      updateMeta(photo.title, img.src);
    }}
    if (videoSrc) {{
      const video = document.createElement('video');
      video.src = videoSrc;
      video.autoplay = true;
      video.loop = true;
      video.muted = true;
      video.playsInline = true;
      video.className = 'lightbox-video';
      const figure = photo.querySelector('figure');
      if (figure) {{
        if (img) img.style.display = 'none';
        figure.appendChild(video);
      }}
    }} else if (img) {{
      img.dataset.thumb = img.src;
      img.dataset.srcset = img.getAttribute('srcset') || '';
      img.dataset.sizes = img.getAttribute('sizes') || '';
      img.removeAttribute('srcset');
      img.removeAttribute('sizes');
      img.src = img.dataset.thumb.replace('/pictures/thumbnail/', '/pictures/large/');
    }}
    showCaption(photo, true);
    document.title = photo.title;

    // Force cursor update after navigation
    setTimeout(() => {{
      if (window.lastMouseX !== undefined && window.lastMouseY !== undefined) {{
        const element = document.elementFromPoint(window.lastMouseX, window.lastMouseY);
        if (element) {{
          const computedStyle = window.getComputedStyle(element);
          document.body.style.cursor = computedStyle.cursor;
          setTimeout(() => {{ document.body.style.cursor = ''; }}, 10);
        }}
      }}
    }}, 50);
  }};

  const closePhoto = () => {{
    clearTimeout(captionTimer);
    captionPinned = false;
    document.querySelectorAll('.caption-pin.pinned').forEach(p => p.classList.remove('pinned'));
    removeTargetClass();
    document.body.style.overflow = '';
    document.title = document.querySelector('title').dataset.title;
    resetMeta();
  }};

  const removeTargetClass = () => {{
    document.querySelectorAll('.' + TARGET_CLASS).forEach(el => {{
      const video = el.querySelector('.lightbox-video');
      if (video) {{
        video.pause();
        video.remove();
        const img = el.querySelector('img');
        if (img) img.style.display = '';
      }}
      const img = el.querySelector('img[data-thumb]');
      if (img) {{
        img.src = img.dataset.thumb;
        if (img.dataset.srcset) img.setAttribute('srcset', img.dataset.srcset);
        if (img.dataset.sizes) img.setAttribute('sizes', img.dataset.sizes);
        delete img.dataset.thumb;
        delete img.dataset.srcset;
        delete img.dataset.sizes;
      }}
      el.style.backgroundColor = '';
      el.classList.remove(TARGET_CLASS);
    }});
  }};

  const handleHash = () => {{
    const hash = location.hash.slice(1);
    if (hash) openPhoto('id-' + hash);
    else closePhoto();
  }};

  window.addEventListener('hashchange', handleHash);

  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape')     {{ location.hash = ''; e.preventDefault(); }}
    if (e.key === 'ArrowRight') {{ navDirection = 'next'; clickNav('.next'); e.preventDefault(); }}
    if (e.key === 'ArrowLeft')  {{ navDirection = 'prev'; clickNav('.previous'); e.preventDefault(); }}
    if (e.key === 'i' || e.key === 'I') {{ toggleCaption(); e.preventDefault(); }}
  }});

  document.addEventListener('mousemove', (e) => {{
    window.lastMouseX = e.clientX;
    window.lastMouseY = e.clientY;
    if (captionManuallyHidden) return;
    const id = currentId();
    if (!id) return;
    const item = document.getElementById(id);
    if (item) showCaption(item);
  }});

  document.addEventListener('click', (e) => {{
    const nav = e.target.closest('.previous[href], .next[href]');
    if (nav) {{
      e.preventDefault();
      navDirection = nav.classList.contains('previous') ? 'prev' : 'next';
      location.hash = nav.getAttribute('href').slice(1);
      return;
    }}
    const t = e.target.closest('[data-target][href]');
    if (t) {{
      e.preventDefault();
      location.hash = t.getAttribute('href').slice(1);
      return;
    }}
    const c = e.target.closest('.close[href]');
    if (c) {{
      e.preventDefault();
      history.replaceState(null, '', location.pathname);
      closePhoto();
      return;
    }}
    const pin = e.target.closest('.caption-pin');
    if (pin) {{
      e.preventDefault();
      e.stopPropagation();
      captionPinned = !captionPinned;
      pin.classList.toggle('pinned', captionPinned);
      pin.animate([
        {{ transform: 'scale(1)' }},
        {{ transform: 'scale(1.5)' }},
        {{ transform: 'scale(1)' }}
      ], {{ duration: 300, easing: 'cubic-bezier(.22, 1.07, .36, 1)' }});
      if (captionPinned) {{
        clearTimeout(captionTimer);
      }} else {{
        const id = currentId();
        if (id) {{
          const item = document.getElementById(id);
          if (item) showCaption(item);
        }}
      }}
      return;
    }}
    const s = e.target.closest('[data-share-slug]');
    if (s) {{
      e.preventDefault();
      shareImage(s.dataset.shareTitle, s.dataset.shareSlug);
      return;
    }}
    // Click on empty canvas area toggles caption/buttons visibility
    if (currentId() && e.target.closest('.' + TARGET_CLASS)) {{
      toggleCaption();
    }}
  }});

  if (location.hash) handleHash();
</script>"""


def generate_index_html(pictures, config):
    """Generate the complete single-page HTML."""
    site_title = config.get("title", "art.jimmac.eu")
    description = config.get("description", "")
    base_url = config.get("base_url", "")
    mastodon = config.get("mastodon_username", "")

    noindex = ""
    if not config.get("allow_indexing", True):
        noindex = '\n    <meta name="robots" content="noindex">'

    mastodon_link = ""
    if mastodon:
        mastodon_link = f'\n    <link rel="me" href="https://mastodon.social/@{mastodon}">'

    picture_items = "\n".join(
        generate_picture_html(p, i, pictures, config)
        for i, p in enumerate(pictures)
    )

    social = []
    if mastodon:
        social.append(f'        <li class="mastodon"><a class="button" rel="me" href="https://mastodon.social/@{mastodon}" title="Mastodon">Mastodon</a></li>')
    github = config.get("github_username", "")
    if github:
        social.append(f'        <li class="github"><a class="button" rel="me" href="https://github.com/{github}" title="Github">Github</a></li>')
    instagram = config.get("instagram_username", "")
    if instagram:
        social.append(f'        <li class="instagram"><a class="button" rel="me" href="https://instagram.com/{instagram}" title="Instagram">Instagram</a></li>')
    pixelfed = config.get("pixelfed_username", "")
    if pixelfed:
        social.append(f'        <li class="pixelfed"><a class="button" rel="me" href="https://pixelfed.social/{pixelfed}" title="Pixelfed">Pixelfed</a></li>')
    cname = config.get("custom_link_name", "")
    curl = config.get("custom_link_url", "")
    if cname and curl:
        social.append(f'        <li class="avatar"><a class="button" rel="me" href="{curl}" title="{cname}"><img src="/img/avatar.svg" alt="{cname}" /></a></li>')
    social.append(f'        <li class="rss"><a class="button" href="{base_url}/feed.xml" title="RSS Feed">RSS</a></li>')
    social_html = "\n".join(social)

    js = generate_javascript(config)

    return f"""<!doctype html>
<html lang="en" class="notranslate" translate="no">
<head>
    <meta charset="utf-8">
    <meta name="google" content="notranslate">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">{noindex}
    <title data-title="{site_title}">{site_title}</title>
    <link rel="alternate" type="application/atom+xml" title="Atom Feed" href="{base_url}/feed.xml">
    <meta property="og:title" content="{site_title}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{base_url}/">
    <meta property="og:image" content="{base_url}/social-preview.png">
    <meta property="og:site_name" content="{site_title}">
    <meta property="og:description" content="{description}">
    <meta name="thumbnail" content="{base_url}/social-preview.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{site_title}">
    <meta name="twitter:description" content="{description}">
    <meta name="twitter:image" content="{base_url}/social-preview.png">
    <meta name="description" content="{description}">{mastodon_link}
    <link rel="stylesheet" href="/css/master.css">
    <link rel="icon" type="image/png" href="/favicon.png">
    <link rel="apple-touch-icon" href="/touch-icon-iphone.png">
</head>
<body>
  <main>
    <ul class="grid" id="grid" role="list">
{picture_items}
    </ul>
  </main>
  <nav aria-label="Social links">
    <ul class="links">
{social_html}
    </ul>
  </nav>
{js}
</body>
</html>
"""


def generate_404_html(config):
    """Generate the 404 error page."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Not Even a Stopped Clock</title>
  <link rel="stylesheet" href="/css/master.css">
  <link rel="icon" type="image/png" href="/favicon.png">
</head>
<body>
  <div class="four-oh-four">
    <h1>Not Even a Stopped Clock</h1>
    <p>404 - Page not found</p>
    <a href="/">Go home</a>
  </div>
</body>
</html>
"""


def generate_picture_stubs(pictures, config):
    """Generate lightweight stub pages for social media sharing."""
    base_url = config.get("base_url", "")
    site_title = config.get("title", "art.jimmac.eu")
    description = config.get("description", "")

    for pic in pictures:
        slug = pic["slug"]
        display_name = html_escape(pic.get("title") or slug)
        raw_desc = pic.get("description") or description
        pic_desc = html_escape(strip_markdown(raw_desc))
        safe_name = quote(pic["filename"])
        og_image = f"{base_url}/pictures/large/{safe_name}"
        out_dir = OUTPUT_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{display_name} - {site_title}</title>
  <meta property="og:title" content="{display_name}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{base_url}/{slug}/">
  <meta property="og:image" content="{og_image}">
  <meta property="og:site_name" content="{site_title}">
  <meta property="og:description" content="{pic_desc}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{display_name}">
  <meta name="twitter:description" content="{pic_desc}">
  <meta name="twitter:image" content="{og_image}">
  <script>location.replace('/#' + '{slug}');</script>
</head>
<body></body>
</html>
""")


def generate_feed_xml(pictures, config):
    """Generate an Atom feed."""
    site_title = config.get("title", "art.jimmac.eu")
    description = config.get("description", "")
    base_url = config.get("base_url", "")
    author_name = config.get("author_name", "")
    author_email = config.get("author_email", "")
    author_website = config.get("author_website", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    author_block = ""
    if author_name or author_email or author_website:
        parts = []
        if author_name:
            parts.append(f"      <name>{html_escape(author_name)}</name>")
        if author_email:
            parts.append(f"      <email>{html_escape(author_email)}</email>")
        if author_website:
            parts.append(f"      <uri>{html_escape(author_website)}</uri>")
        author_block = "  <author>\n" + "\n".join(parts) + "\n  </author>\n"

    entries = []
    for pic in pictures[:20]:
        slug = pic["slug"]
        display_name = html_escape(pic.get("title") or slug)
        safe_name = quote(pic["filename"])
        date = pic["exif_date"].strftime("%Y-%m-%dT%H:%M:%S+00:00")
        entry_url = f"{base_url}/{slug}/"
        img_url = f"{base_url}/pictures/large/{safe_name}"

        desc_html = ""
        if pic.get("description"):
            desc_html = f"<p>{html_escape(pic['description'])}</p>"

        entry_author = ""
        if author_name:
            a_parts = []
            if author_name:
                a_parts.append(f"        <name>{html_escape(author_name)}</name>")
            if author_email:
                a_parts.append(f"        <email>{html_escape(author_email)}</email>")
            if author_website:
                a_parts.append(f"        <uri>{html_escape(author_website)}</uri>")
            entry_author = "    <author>\n" + "\n".join(a_parts) + "\n    </author>\n"

        entries.append(f"""  <entry>
    <title type="html">{display_name}</title>
    <link href="{entry_url}" rel="alternate" type="text/html" title="{display_name}" />
    <published>{date}</published>
    <updated>{date}</updated>
    <id>{entry_url}</id>
    <content type="html"><![CDATA[{desc_html}<figure><a href="{entry_url}"><img src="{img_url}" alt="{display_name}" /></a></figure>]]></content>
{entry_author}    <media:thumbnail xmlns:media="http://search.yahoo.com/mrss/" url="{img_url}" />
    <media:content medium="image" url="{img_url}" xmlns:media="http://search.yahoo.com/mrss/" />
  </entry>""")

    entries_xml = "\n".join(entries)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link href="{base_url}/feed.xml" rel="self" type="application/atom+xml" />
  <link href="{base_url}/" rel="alternate" type="text/html" />
  <updated>{now}</updated>
  <id>{base_url}/feed.xml</id>
  <title type="html"><![CDATA[{html_escape(site_title)}]]></title>
  <subtitle><![CDATA[{html_escape(description)}]]></subtitle>
{author_block}{entries_xml}
</feed>
"""


def main():
    if not SOURCE_DIR.exists():
        print(f"Error: Source directory '{SOURCE_DIR}' not found.")
        sys.exit(1)

    config = CONFIG

    clean = "--clean" in sys.argv
    if clean and OUTPUT_DIR.exists():
        print("Cleaning output directory...")
        shutil.rmtree(OUTPUT_DIR)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Building site ===\n")

    print("1. Normalizing file extensions...")
    normalize_extensions()

    print("2. Scanning pictures and extracting EXIF data...")
    pictures = scan_and_sort_pictures()
    print(f"   Found {len(pictures)} pictures")

    print("3. Processing images...")
    for i, pic in enumerate(pictures):
        sys.stdout.write(f"\r   Processing {i+1}/{len(pictures)}: {pic['source_path'].name}...")
        sys.stdout.flush()
        process_image(pic)
    print("\n   Done!")

    if config.get("allow_original_download"):
        print("4. Copying originals for download...")
        copy_originals(pictures)
    else:
        print("4. Skipping originals (download disabled)")

    print("5. Copying static assets...")
    copy_static_assets()

    print("6. Generating index.html...")
    (OUTPUT_DIR / "index.html").write_text(generate_index_html(pictures, config))

    print("7. Generating 404.html...")
    (OUTPUT_DIR / "404.html").write_text(generate_404_html(config))

    print("8. Generating feed.xml...")
    (OUTPUT_DIR / "feed.xml").write_text(generate_feed_xml(pictures, config))

    print("9. Generating share stubs...")
    generate_picture_stubs(pictures, config)
    print(f"   Generated {len(pictures)} stubs")

    print(f"\n=== Build complete: {len(pictures)} pictures ===")


if __name__ == "__main__":
    main()
