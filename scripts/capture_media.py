"""Record the README media: docs/assets/screenshot-{light,dark}.png and demo.gif.

Runs `hbridge ui` against a throwaway demo home (fake harness binaries, dummy
keys) and drives it with Playwright, so no real configuration is involved.

    uv run --no-project --with playwright --with pillow python scripts/capture_media.py

Set CHROME=/path/to/chrome to use an installed browser instead of running
`playwright install chromium` first.
"""
import io, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
OUT = ROOT / "docs" / "assets"
CHROME = os.environ.get("CHROME")  # optional: use an installed Chrome instead of Playwright's
H = Path("/tmp/hbridge-demo/home")  # shown as ~ in the UI

def reset_home():
    shutil.rmtree(H.parent, ignore_errors=True)
    for sub in ("bin", ".claude", ".codex", ".pi/agent", ".hermes", ".config/hbridge"):
        (H / sub).mkdir(parents=True, exist_ok=True)
    for b in ("claude", "codex", "pi"):
        f = H / "bin" / b; f.write_text("#!/bin/sh\nexit 0\n"); f.chmod(0o755)
    f = H / "bin" / "hermes"
    f.write_text(f"""#!{sys.executable}
import json, os, sys
p = os.path.join(os.environ["HERMES_HOME"], "fake.json")
d = json.load(open(p)) if os.path.exists(p) else {{"model.provider": "opencode-go", "model.default": "deepseek-v4.1-flash"}}
a = sys.argv[1:]
if a[:2] == ["config", "set"]: d[a[2]] = a[3]; json.dump(d, open(p, "w"))
elif a[:2] == ["config", "get"]: print(d.get(a[2], ""))
"""); f.chmod(0o755)
    (H / ".codex/config.toml").write_text('model = "gpt-5.4"\nmodel_provider = "openai"\n')
    (H / ".pi/agent/settings.json").write_text(json.dumps({"defaultProvider": "openrouter", "defaultModel": "deepseek/deepseek-v4.1-flash"}))

def start_server():
    env = {"HOME": str(H), "PATH": f"{H}/bin:/usr/bin:/bin", "PYTHONPATH": SRC,
           "HERMES_HOME": str(H / ".hermes"), "OPENCODE_GO_API_KEY": "demo", "OPENROUTER_API_KEY": "demo"}
    proc = subprocess.Popen([sys.executable, "-m", "hbridge", "ui", "--no-open"], env=env, stdout=subprocess.PIPE, text=True)
    url = re.search(r"(http://\S+)", proc.stdout.readline()).group(1)
    return proc, url

CURSOR = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.id = 'demo-cursor';
  c.innerHTML = '<svg width="22" height="26" viewBox="0 0 22 26"><path d="M2 2 L2 21 L7 16.5 L10.5 24 L14 22.5 L10.6 15.2 L17.5 15.2 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, {position:'fixed', left:'0', top:'0', zIndex:99999, pointerEvents:'none', transform:'translate(-2px,-2px)'});
  document.body.appendChild(c);
  const move = (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; };
  document.addEventListener('pointermove', move, true);
  document.addEventListener('mousemove', move, true);
  document.addEventListener('pointerdown', () => c.style.transform = 'translate(-2px,-2px) scale(.88)', true);
  document.addEventListener('pointerup', () => c.style.transform = 'translate(-2px,-2px)', true);
});
"""

def ease(t): return t * t * (3 - 2 * t)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()

    # --- Screenshots -------------------------------------------------------
    for scheme in ("light", "dark"):
        reset_home(); proc, url = start_server()
        page = browser.new_page(viewport={"width": 1100, "height": 760}, device_scale_factor=2, color_scheme=scheme)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url); page.wait_for_selector(".tool"); time.sleep(0.5)
        page.screenshot(path=str(OUT / f"screenshot-{scheme}.png"), full_page=True)
        print(scheme, "errors:", errors)
        page.close(); proc.terminate(); proc.wait()

    # --- GIF -----------------------------------------------------------------
    reset_home(); proc, url = start_server()
    page = browser.new_page(viewport={"width": 1100, "height": 1000}, color_scheme="light")
    page.add_init_script(CURSOR)
    page.goto(url); page.wait_for_selector(".tool"); time.sleep(0.4)
    frames = []
    def snap(ms):
        frames.append((Image.open(io.BytesIO(page.screenshot())).convert("RGB"), ms))
    pos = [900, 860]
    def glide(x, y, steps=18, ms=40):
        x0, y0 = pos
        for i in range(1, steps + 1):
            t = ease(i / steps)
            page.mouse.move(x0 + (x - x0) * t, y0 + (y - y0) * t); snap(ms)
        pos[:] = [x, y]
    def center(sel, dx=0.5, dy=0.5):
        b = page.locator(sel).bounding_box(); return b["x"] + b["width"] * dx, b["y"] + b["height"] * dy

    page.mouse.move(*pos); snap(1400)
    # 1. Drag Codex onto OpenCode Go
    glide(*center('.tool[data-tool="codex"]', 0.82)); snap(300)
    page.mouse.down(); snap(150)
    glide(*center('.provider[data-provider="go"]', 0.18), steps=28, ms=45); snap(500)
    page.mouse.up()
    page.wait_for_function("document.querySelector('#toast').classList.contains('show')"); time.sleep(0.25)
    snap(1700)
    # 2. Click Claude Code, read the command table, then click OpenRouter
    glide(*center('.tool[data-tool="claude"]', 0.6)); page.mouse.down(); page.mouse.up(); time.sleep(0.3); snap(1800)
    glide(*center('.provider[data-provider="openrouter"]', 0.5), steps=22)
    page.mouse.down(); page.mouse.up()
    page.wait_for_function("document.querySelector('#toast').textContent.includes('Claude')"); time.sleep(0.3)
    snap(1800)
    # 3. Hover Kilo (not installed), then Hermes to highlight its route
    glide(*center('.tool[data-tool="kilo"]', 0.6), steps=14); snap(900)
    glide(*center('.tool[data-tool="hermes"]', 0.6), steps=14); time.sleep(0.2); snap(2200)
    proc.terminate(); proc.wait(); browser.close()

# Crop to the content, scale down, and write an optimised GIF.
images = []
width = 880
for img, ms in frames:
    img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    images.append((img, ms))
# One palette for the whole animation, sampled from frames across it.
sample = [img for img, _ in images[:: max(1, len(images) // 12)]]
mosaic = Image.new("RGB", (sample[0].width, sample[0].height * len(sample)))
for i, img in enumerate(sample):
    mosaic.paste(img, (0, i * img.height))
# Guarantee the UI's brand colours survive quantisation: small swatches are
# otherwise outvoted by the large neutral areas.
brand = ["#c96442", "#0e9f6e", "#2563eb", "#7c3aed", "#b45309", "#fef3c7", "#15803d", "#1c1b19", "#ffffff", "#f6f5f2"]
strip = Image.new("RGB", (sample[0].width, 400 * len(brand)))
for i, colour in enumerate(brand):
    strip.paste(Image.new("RGB", (sample[0].width, 400), colour), (0, i * 400))
full = Image.new("RGB", (mosaic.width, mosaic.height + strip.height))
full.paste(mosaic, (0, 0)); full.paste(strip, (0, mosaic.height))
palette = full.quantize(colors=224, method=Image.Quantize.MEDIANCUT)
quantized = [img.quantize(palette=palette, dither=Image.Dither.NONE) for img, _ in images]
quantized[0].save(OUT / "demo.gif", save_all=True, append_images=quantized[1:],
                  duration=[ms for _, ms in images], loop=0, optimize=True, disposal=1)
for name in ("screenshot-light.png", "screenshot-dark.png", "demo.gif"):
    print(f"{name}: {(OUT / name).stat().st_size // 1024} KiB")
