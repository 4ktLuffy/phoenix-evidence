"""A short animated walk-through: Phoenix's compare view, the patched one, then the CLI on real data.

    uv run --extra phoenix --with pillow python bench/demo_frames.py

Frames 1-2 are screenshots already in results/screenshots (released Phoenix at :6006, patched
branch at :6007). The terminal frames run the real commands at build time against the local
Phoenix at :6006 (compare, doctor on the dataset bench/doctor_live.py uploaded, price) and print
the stored real canary result (results/canary_real.json). Writes results/screenshots/demo.gif and
the frames as demo_<n>.png.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / 'results' / 'screenshots'
CLI = [str(ROOT / '.venv' / 'bin' / 'phoenix-evidence'), '--url', 'http://localhost:6006']
W, H = 1280, 720
FONT = '/System/Library/Fonts/Menlo.ttc'


def run(args: list[str]) -> str:
    done = subprocess.run(CLI + args, capture_output=True, text=True, timeout=120)
    return (done.stdout + done.stderr).strip()


def wrap(text: str, width: int) -> list[str]:
    lines = []
    for line in text.splitlines():
        while len(line) > width:
            cut = line.rfind(' ', 0, width)
            cut = cut if cut > width // 2 else width
            lines.append(line[:cut])
            line = '    ' + line[cut:].lstrip()
        lines.append(line)
    return lines


def caption(img: Image.Image, text: str) -> Image.Image:
    out = Image.new('RGB', (W, H), '#111418')
    body = img.copy()
    body.thumbnail((W, H - 70))
    out.paste(body, ((W - body.width) // 2, 70))
    draw = ImageDraw.Draw(out)
    draw.text((24, 20), text, font=ImageFont.truetype(FONT, 24), fill='#f5c542')
    return out


def terminal(command: str, output: str) -> Image.Image:
    img = Image.new('RGB', (W, H - 70), '#0b0e11')
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 15)
    y = 16
    for k, line in enumerate(wrap(f'$ {command}\n{output}', 128)):
        if y > H - 100:
            break
        draw.text((18, y), line, font=font, fill='#7ee787' if k == 0 else '#d6dde5')
        y += 21
    return img


def main() -> None:
    doctor_set = json.loads((ROOT / 'results' / 'doctor_live.json').read_text())
    canary = json.loads((ROOT / 'results' / 'canary_real.json').read_text())
    canary_text = '\n'.join(f'{x["label"]}: {x["flips"]} flips in {x["checks"]}; evidence {x["evidence"]:.2f}'
                            for x in canary['looks']) + '\n' + canary['summary']  # fmt: skip
    dataset = sys.argv[1] if len(sys.argv) > 1 else None
    frames = [
        caption(Image.open(SHOTS / 'phoenix_compare_fragile.jpg'),
                '1. Phoenix: the version that crashes on 10 hard cases looks better'),
        caption(Image.open(SHOTS / 'phoenix_with_evidence.jpg'),
                '2. Patched Phoenix: crashes count, and an evidence line says if the gap is real'),
        caption(terminal('phoenix-evidence compare baseline fragile --fail-on-regression',
                         run(['compare', 'RXhwZXJpbWVudDo5', 'RXhwZXJpbWVudDoxMQ==', '--fail-on-regression'])),
                '3. The same check in CI: a paired test, Holm-corrected, exit 1 on a regression'),
        caption(terminal('uv run --extra phoenix python bench/canary_real.py   # the canary on real Codex labels', canary_text),
                '4. Drift canary, real labels: an effort change stays within noise; daily looks are safe'),
        caption(terminal('phoenix-evidence doctor <dataset> --splits train,test',
                         run(['doctor', dataset, '--splits', 'train,test']) if dataset else
                         '\n'.join(doctor_set['problems'])),
                '5. Dataset doctor: copies, conflicting labels, test examples leaking into train'),
        caption(terminal('phoenix-evidence price --traces 10000 --width 0.1 --judge-cost 0.002 --human-cost 0.5 --disagreement 0.05',
                         run(['price', '--traces', '10000', '--width', '0.1', '--judge-cost', '0.002',
                              '--human-cost', '0.5', '--disagreement', '0.05'])),
                '6. Price of certainty: 402 human labels alone, or 107 with the judge'),
    ]  # fmt: skip
    for k, frame in enumerate(frames, 1):
        frame.save(SHOTS / f'demo_{k}.png')
    frames[0].save(SHOTS / 'demo.gif', save_all=True, append_images=frames[1:], duration=4500, loop=0)
    print(f'{len(frames)} frames -> {SHOTS / "demo.gif"}')


if __name__ == '__main__':
    main()
