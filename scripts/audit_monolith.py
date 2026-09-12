#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import html
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
REPORT_DIR = ROOT / "reports"
REPORT = REPORT_DIR / "monolith-audit.md"

text = INDEX.read_text(encoding="utf-8", errors="replace")
raw = INDEX.read_bytes()

style_re = re.compile(r"<style\b(?P<attrs>[^>]*)>(?P<body>.*?)</style\s*>", re.I | re.S)
script_re = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.I | re.S)
data_uri_re = re.compile(r"data:(?P<mime>[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=]+)")

styles = list(style_re.finditer(text))
scripts = list(script_re.finditer(text))
data_uris = list(data_uri_re.finditer(text))

mimes = Counter(m.group("mime").lower() for m in data_uris)


def script_kind(attrs: str) -> str:
    if re.search(r"\bsrc\s*=", attrs, re.I):
        return "external"
    mt = re.search(r"\btype\s*=\s*([\"'])(.*?)\1", attrs, re.I | re.S)
    if not mt:
        return "inline-js"
    typ = mt.group(2).strip().lower()
    if typ in {"text/javascript", "application/javascript", "module", "text/ecmascript", "application/ecmascript"}:
        return "inline-js"
    return f"inline-nonjs:{typ or 'empty'}"

script_kinds = Counter(script_kind(m.group("attrs")) for m in scripts)


def compact_context(pos: int, radius: int = 500) -> str:
    s = text[max(0, pos-radius): min(len(text), pos+radius)]
    # Redact base64 payloads and collapse whitespace so the report stays small.
    s = re.sub(r"(data:[^;,\s]+;base64,)[A-Za-z0-9+/=]+", r"\1<BASE64_REDACTED>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:1200]


def probe_duration(blob: bytes, suffix: str, idx: int) -> str:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return "ffprobe unavailable"
    tmp = ROOT / f".audit_audio_{idx}.{suffix}"
    try:
        tmp.write_bytes(blob)
        cp = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(tmp)],
            capture_output=True, text=True, timeout=20,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            try:
                return f"{float(cp.stdout.strip()):.3f} s"
            except ValueError:
                return cp.stdout.strip()
        return "unknown"
    finally:
        tmp.unlink(missing_ok=True)

lines = []
lines.append("# DEATH_MATCH monolith audit")
lines.append("")
lines.append("Generated automatically from the refactor branch. No runtime files were modified by this audit.")
lines.append("")
lines.append("## File overview")
lines.append("")
lines.append(f"- `index.html` bytes: **{len(raw):,}**")
lines.append(f"- Approximate lines: **{text.count(chr(10)) + 1:,}**")
lines.append(f"- Inline `<style>` blocks: **{len(styles)}**")
lines.append(f"- Total `<script>` blocks: **{len(scripts)}**")
for k, v in sorted(script_kinds.items()):
    lines.append(f"- Script kind `{k}`: **{v}**")
lines.append(f"- Base64 data URIs: **{len(data_uris)}**")
lines.append("")

lines.append("## Largest inline style blocks")
lines.append("")
if styles:
    for i, m in sorted(enumerate(styles, 1), key=lambda t: len(t[1].group('body')), reverse=True)[:10]:
        lines.append(f"- Style {i}: {len(m.group('body')):,} characters")
else:
    lines.append("- None")
lines.append("")

lines.append("## Largest inline JavaScript blocks")
lines.append("")
js_entries = [(i, m) for i, m in enumerate(scripts, 1) if script_kind(m.group('attrs')) == 'inline-js']
if js_entries:
    for i, m in sorted(js_entries, key=lambda t: len(t[1].group('body')), reverse=True)[:15]:
        lines.append(f"- Script {i}: {len(m.group('body')):,} characters; attrs `{html.escape(m.group('attrs').strip()) or '(none)'}`")
else:
    lines.append("- None")
lines.append("")

lines.append("## Embedded data URI inventory")
lines.append("")
if mimes:
    for mime, count in sorted(mimes.items()):
        lines.append(f"- `{mime}`: **{count}**")
else:
    lines.append("- None")
lines.append("")

lines.append("## Embedded audio")
lines.append("")
audio_num = 0
for m in data_uris:
    mime = m.group('mime').lower()
    if not mime.startswith('audio/'):
        continue
    audio_num += 1
    payload = m.group('data')
    try:
        blob = base64.b64decode(payload, validate=False)
        subtype = mime.split('/', 1)[1].replace('mpeg', 'mp3').replace('x-wav', 'wav')
        duration = probe_duration(blob, subtype, audio_num)
        digest = hashlib.sha256(blob).hexdigest()[:12]
        size = f"{len(blob):,} bytes"
    except Exception as exc:
        duration = f"decode error: {type(exc).__name__}"
        digest = "n/a"
        size = "n/a"
    lines.append(f"### Audio {audio_num}")
    lines.append("")
    lines.append(f"- MIME: `{mime}`")
    lines.append(f"- Decoded size: {size}")
    lines.append(f"- Duration: **{duration}**")
    lines.append(f"- SHA-256 prefix: `{digest}`")
    lines.append(f"- Nearby source context: `{html.escape(compact_context(m.start()))}`")
    lines.append("")
if audio_num == 0:
    lines.append("- No embedded audio data URIs found.")
    lines.append("")

lines.append("## Welcome / timing clues")
lines.append("")
patterns = [
    r"welcome", r"intro", r"16700", r"16\.7", r"17000", r"10_?000",
    r"setTimeout", r"currentTime", r"\.pause\(\)", r"\.play\(\)",
]
seen = set()
for pat in patterns:
    for mt in re.finditer(pat, text, re.I):
        key = (pat, max(0, mt.start() // 250))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- `{pat}` near char {mt.start():,}: `{html.escape(compact_context(mt.start(), 350))}`")
        if sum(1 for line in lines if line.startswith('- `') and 'near char' in line) >= 40:
            break
    if sum(1 for line in lines if line.startswith('- `') and 'near char' in line) >= 40:
        break
if not seen:
    lines.append("- No obvious timing keywords found.")
lines.append("")

lines.append("## Recommended first split")
lines.append("")
lines.append("1. Preserve the DOM markup and script execution order.")
lines.append("2. Move each ordinary inline JavaScript block to `src/legacy/inline-###.js` and replace it in-place with a `src` reference.")
lines.append("3. Move inline CSS to `styles/legacy/inline-###.css` and replace it in-place with a stylesheet link.")
lines.append("4. Leave non-JavaScript `<script>` data blocks inline until their consumers are identified.")
lines.append("5. Externalize large base64 media after identifying each asset, beginning with the welcome MP3.")
lines.append("6. Centralize the welcome duration in `src/config.js` as `WELCOME_AUDIO_MAX_MS = 10000`.")

REPORT_DIR.mkdir(parents=True, exist_ok=True)
REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote {REPORT.relative_to(ROOT)}")
