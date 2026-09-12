#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SW = ROOT / "sw.js"

STYLE_DIR = ROOT / "styles" / "legacy"
SCRIPT_DIR = ROOT / "src" / "legacy"
AUDIO_DIR = ROOT / "assets" / "audio"
IMAGE_DIR = ROOT / "assets" / "images"
REPORT_DIR = ROOT / "reports"

for directory in (STYLE_DIR, SCRIPT_DIR, AUDIO_DIR, IMAGE_DIR, REPORT_DIR):
    directory.mkdir(parents=True, exist_ok=True)

original_html = INDEX.read_text(encoding="utf-8")
if "./src/legacy/script-01.js" in original_html:
    raise SystemExit("index.html already appears modularized; refusing to run the one-time migration again.")

# Keep the current startup behavior but cap the opening at 10 seconds.
old_timing = re.compile(
    r"//\s*Welcome file is ~16\.7s; this only protects against a stuck mobile media event\.\s*"
    r"setTimeout\(follow,\s*19000\s*\);",
    re.I,
)
new_timing = (
    "// Welcome audio is capped at 10 seconds; this also guards against a stuck mobile media event.\n"
    "      const welcomeMaxMs=window.DEATH_MATCH_CONFIG?.WELCOME_AUDIO_MAX_MS??10000;\n"
    "      setTimeout(()=>{try{welcome.pause();}catch(e){} follow();},welcomeMaxMs);"
)
html, timing_count = old_timing.subn(new_timing, original_html, count=1)
if timing_count != 1:
    raise SystemExit(f"Expected one welcome timing block, replaced {timing_count}.")

style_re = re.compile(r"<style\b(?P<attrs>[^>]*)>(?P<body>.*?)</style\s*>", re.I | re.S)
script_re = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.I | re.S)

style_files: list[Path] = []
script_files: list[Path] = []


def extract_style(match: re.Match[str]) -> str:
    number = len(style_files) + 1
    rel = Path("styles/legacy") / f"style-{number:02d}.css"
    path = ROOT / rel
    path.write_text(match.group("body").strip() + "\n", encoding="utf-8")
    style_files.append(path)
    attrs = match.group("attrs")
    return f'<link rel="stylesheet" href="./{rel.as_posix()}"{attrs}>'


def script_is_javascript(attrs: str) -> bool:
    if re.search(r"\bsrc\s*=", attrs, re.I):
        return False
    mt = re.search(r"\btype\s*=\s*([\"'])(.*?)\1", attrs, re.I | re.S)
    if not mt:
        return True
    return mt.group(2).strip().lower() in {
        "text/javascript", "application/javascript", "module",
        "text/ecmascript", "application/ecmascript",
    }


def extract_script(match: re.Match[str]) -> str:
    attrs = match.group("attrs")
    if not script_is_javascript(attrs):
        return match.group(0)
    number = len(script_files) + 1
    rel = Path("src/legacy") / f"script-{number:02d}.js"
    path = ROOT / rel
    path.write_text(match.group("body").strip() + "\n", encoding="utf-8")
    script_files.append(path)
    return f'<script{attrs} src="./{rel.as_posix()}"></script>'


html = style_re.sub(extract_style, html)
html = script_re.sub(extract_script, html)

if len(style_files) != 13:
    raise SystemExit(f"Expected 13 inline style blocks, extracted {len(style_files)}.")
if len(script_files) != 4:
    raise SystemExit(f"Expected 4 inline JavaScript blocks, extracted {len(script_files)}.")

# Central config loads before all body scripts. Future behavior constants belong here.
config_rel = Path("src/config.js")
config_path = ROOT / config_rel
config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(
    "window.DEATH_MATCH_CONFIG = Object.freeze({\n"
    "  WELCOME_AUDIO_MAX_MS: 10000,\n"
    "});\n",
    encoding="utf-8",
)
if "</head>" not in html:
    raise SystemExit("Could not locate </head> for config injection.")
html = html.replace("</head>", '<script src="./src/config.js"></script>\n</head>', 1)
INDEX.write_text(html, encoding="utf-8")

# Externalize all remaining base64 media from the now-smaller source files.
data_uri_re = re.compile(
    r"data:(?P<mime>[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=]+)"
)
asset_by_digest: dict[str, Path] = {}
asset_records: list[tuple[str, str, int, str]] = []
audio_counter = 0
image_counter = 0
welcome_duration = "unknown"


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "audio"


def relative_url(source_path: Path, asset_path: Path) -> str:
    rel = os.path.relpath(asset_path, start=source_path.parent).replace(os.sep, "/")
    if not rel.startswith("."):
        rel = "./" + rel
    return rel


def ffprobe_duration(path: Path) -> str:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return "ffprobe unavailable"
    cp = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if cp.returncode == 0 and cp.stdout.strip():
        try:
            return f"{float(cp.stdout.strip()):.3f} s"
        except ValueError:
            return cp.stdout.strip()
    return "unknown"


def trim_welcome(blob: bytes, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to trim the welcome MP3 but was not found.")
    tmp = ROOT / ".welcome-original.mp3"
    tmp.write_bytes(blob)
    try:
        cp = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(tmp),
                "-af", "atrim=duration=10,asetpts=N/SR/TB",
                "-map_metadata", "-1",
                "-c:a", "libmp3lame", "-b:a", "192k",
                str(output),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if cp.returncode != 0:
            raise SystemExit("ffmpeg failed trimming welcome MP3: " + cp.stderr[-1200:])
    finally:
        tmp.unlink(missing_ok=True)


def infer_audio_name(content: str, start: int, source_path: Path) -> tuple[str, bool]:
    before = content[max(0, start - 1200):start]
    is_welcome = source_path == INDEX and "dtWelcomeAudio" in before[-1000:]
    if is_welcome:
        return "welcome", True
    matches = list(re.finditer(r"name\s*:\s*([\"'])(.*?)\1\s*,\s*src\s*:\s*([\"'])\s*$", before, re.I | re.S))
    if matches:
        return slugify(matches[-1].group(2)), False
    return "audio", False


def externalize_file(source_path: Path) -> None:
    nonlocal_holder = {"audio": 0, "image": 0}
    content = source_path.read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        nonlocal audio_counter, image_counter, welcome_duration
        mime = match.group("mime").lower()
        blob = base64.b64decode(match.group("data"), validate=False)
        digest = hashlib.sha256(blob).hexdigest()

        if mime.startswith("audio/"):
            name, is_welcome = infer_audio_name(content, match.start(), source_path)
            if is_welcome:
                asset_path = AUDIO_DIR / "welcome.mp3"
                trim_welcome(blob, asset_path)
                welcome_duration = ffprobe_duration(asset_path)
                final_blob = asset_path.read_bytes()
                final_digest = hashlib.sha256(final_blob).hexdigest()
                asset_by_digest[final_digest] = asset_path
                asset_records.append((source_path.relative_to(ROOT).as_posix(), asset_path.relative_to(ROOT).as_posix(), len(final_blob), mime))
                return relative_url(source_path, asset_path)

            if digest in asset_by_digest:
                return relative_url(source_path, asset_by_digest[digest])
            audio_counter += 1
            ext = "mp3" if mime in {"audio/mpeg", "audio/mp3"} else mime.split("/", 1)[1].replace("x-", "")
            candidate = AUDIO_DIR / f"{name}.{ext}"
            if candidate.exists():
                candidate = AUDIO_DIR / f"{name}-{audio_counter:02d}.{ext}"
            candidate.write_bytes(blob)
            asset_by_digest[digest] = candidate
            asset_records.append((source_path.relative_to(ROOT).as_posix(), candidate.relative_to(ROOT).as_posix(), len(blob), mime))
            return relative_url(source_path, candidate)

        if mime.startswith("image/"):
            if digest in asset_by_digest:
                return relative_url(source_path, asset_by_digest[digest])
            image_counter += 1
            subtype = mime.split("/", 1)[1].lower()
            ext = {"jpeg": "jpg", "svg+xml": "svg"}.get(subtype, subtype)
            candidate = IMAGE_DIR / f"embedded-{image_counter:02d}.{ext}"
            candidate.write_bytes(blob)
            asset_by_digest[digest] = candidate
            asset_records.append((source_path.relative_to(ROOT).as_posix(), candidate.relative_to(ROOT).as_posix(), len(blob), mime))
            return relative_url(source_path, candidate)

        return match.group(0)

    updated = data_uri_re.sub(replace, content)
    source_path.write_text(updated, encoding="utf-8")


for source in [INDEX, *style_files, *script_files]:
    externalize_file(source)

# Identify the externalized script that still carries the LEVELS marker used by the PWA data sync.
levels_script = next((p for p in script_files if "const LEVELS = " in p.read_text(encoding="utf-8")), None)
if levels_script is None:
    raise SystemExit("Could not locate the script containing `const LEVELS = `.")
levels_script_url = "./" + levels_script.relative_to(ROOT).as_posix()
levels_script_pathname = "/" + levels_script.relative_to(ROOT).as_posix()

# Update the service worker so Master 666 injection follows the externalized game script rather than index.html.
sw = SW.read_text(encoding="utf-8")
sw = re.sub(
    r"const CACHE_NAME = ['\"][^'\"]+['\"];",
    "const CACHE_NAME = 'death-trails-v5-modular-master666';",
    sw,
    count=1,
)

shell_paths = [
    "./", "./index.html", "./manifest.webmanifest", "./master666.json", "./src/config.js",
    *["./" + p.relative_to(ROOT).as_posix() for p in style_files],
    *["./" + p.relative_to(ROOT).as_posix() for p in script_files],
]
for _, asset, _, _ in asset_records:
    shell_paths.append("./" + asset)
shell_paths = list(dict.fromkeys(shell_paths))
app_shell = "const APP_SHELL = [\n" + "\n".join(f"  {path!r}," for path in shell_paths) + "\n];"
sw, shell_count = re.subn(r"const APP_SHELL = \[.*?\];", app_shell, sw, count=1, flags=re.S)
if shell_count != 1:
    raise SystemExit("Could not update service worker APP_SHELL.")

new_master_function = f'''async function master666ScriptResponse(request){{
  const [scriptResponse,masterResponse]=await Promise.all([
    fetch(request,{{cache:'no-store'}}),
    fetch('./master666.json',{{cache:'no-store'}})
  ]);
  if(!scriptResponse.ok||!masterResponse.ok) return scriptResponse;
  const [source,master]=await Promise.all([scriptResponse.text(),masterResponse.json()]);
  const updated=replaceLevels(source,makeLevels(master));
  const headers=new Headers(scriptResponse.headers);
  headers.set('content-type','application/javascript; charset=utf-8');
  headers.set('cache-control','no-cache');
  headers.delete('content-length');
  const response=new Response(updated,{{status:scriptResponse.status,statusText:scriptResponse.statusText,headers}});
  const cache=await caches.open(CACHE_NAME);
  await cache.put(request,response.clone());
  return response;
}}'''
sw, master_count = re.subn(
    r"async function master666Response\(request\)\{.*?\n\}\n\nself\.addEventListener\('install'",
    new_master_function + "\n\nself.addEventListener('install'",
    sw,
    count=1,
    flags=re.S,
)
if master_count != 1:
    raise SystemExit("Could not replace master666Response in service worker.")

new_navigation = f'''if(url.pathname.endsWith('{levels_script_pathname}')){{
    event.respondWith(
      master666ScriptResponse(request)
        .catch(()=>caches.match(request))
    );
    return;
  }}

  if(request.mode==='navigate'){{
    event.respondWith(
      fetch(request,{{cache:'no-store'}})
        .then(async response=>{{
          if(response&&response.ok){{
            const cache=await caches.open(CACHE_NAME);
            await cache.put('./index.html',response.clone());
          }}
          return response;
        }})
        .catch(()=>caches.match('./index.html'))
    );
    return;
  }}'''
sw, nav_count = re.subn(
    r"if\(request\.mode==='navigate'\)\{.*?\n  \}\n\n  if\(url\.origin===self\.location\.origin\)",
    new_navigation + "\n\n  if(url.origin===self.location.origin)",
    sw,
    count=1,
    flags=re.S,
)
if nav_count != 1:
    raise SystemExit("Could not update service worker navigation/data routing.")
SW.write_text(sw, encoding="utf-8")

# Lightweight human-readable workflow guide.
(ROOT / "DEVELOPMENT.md").write_text(
    """# DEATH_MATCH development workflow\n\n"
    "The app is now split into small static files while remaining GitHub Pages friendly. No npm or build step is required.\n\n"
    "## Branch workflow\n\n"
    "1. Keep `main` as the stable/deployed branch.\n"
    "2. Create a feature branch for each change.\n"
    "3. Make the change in the smallest relevant source file.\n"
    "4. Run the validation workflow / smoke checks.\n"
    "5. Review the diff in a pull request, then merge to `main`.\n\n"
    "## Where to edit\n\n"
    "- `index.html` — page structure only.\n"
    "- `styles/legacy/` — CSS extracted from the former monolith, kept in original cascade order.\n"
    "- `src/legacy/` — JavaScript extracted in original execution order.\n"
    "- `src/config.js` — small behavior constants, including the 10-second welcome limit.\n"
    "- `master666.json` — approved question/answer content.\n"
    "- `assets/audio/` and `assets/images/` — media; do not embed base64 back into HTML/JS/CSS.\n"
    "- `sw.js` — PWA cache and Master 666 runtime sync.\n\n"
    "## First-pass refactor rule\n\n"
    "This split intentionally preserves existing DOM structure, CSS order, and JavaScript execution order. Refactor `src/legacy/` into named feature modules gradually after the modular build is verified.\n"
    """,
    encoding="utf-8",
)

# Sanity checks before committing.
final_index = INDEX.read_text(encoding="utf-8")
if "data:" in final_index and ";base64," in final_index:
    raise SystemExit("Base64 data URI remains in index.html.")
for p in [*style_files, *script_files]:
    s = p.read_text(encoding="utf-8")
    if ";base64," in s:
        raise SystemExit(f"Base64 data URI remains in {p.relative_to(ROOT)}.")
if "WELCOME_AUDIO_MAX_MS: 10000" not in config_path.read_text(encoding="utf-8"):
    raise SystemExit("Welcome config did not write correctly.")
if not (AUDIO_DIR / "welcome.mp3").exists():
    raise SystemExit("Trimmed welcome.mp3 was not created.")

new_size = INDEX.stat().st_size
report = [
    "# Modular refactor result",
    "",
    f"- Original `index.html`: **{len(original_html.encode('utf-8')):,} bytes**",
    f"- Modular `index.html`: **{new_size:,} bytes**",
    f"- Inline style blocks externalized: **{len(style_files)}**",
    f"- Inline JavaScript blocks externalized: **{len(script_files)}**",
    f"- Media assets externalized: **{len(asset_records)}**",
    f"- Welcome MP3 trimmed target: **10.0 seconds**",
    f"- Welcome MP3 probed duration: **{welcome_duration}**",
    f"- Master 666 runtime source: `{levels_script_url}`",
    "",
    "## Externalized media",
    "",
]
for source, asset, size, mime in asset_records:
    report.append(f"- `{asset}` — {size:,} bytes, `{mime}`, from `{source}`")
(REPORT_DIR / "modular-refactor.md").write_text("\n".join(report) + "\n", encoding="utf-8")

print("Modular refactor complete.")
print(f"index.html: {len(original_html.encode('utf-8')):,} -> {new_size:,} bytes")
print(f"styles: {len(style_files)}, scripts: {len(script_files)}, assets: {len(asset_records)}")
print(f"welcome duration: {welcome_duration}")
