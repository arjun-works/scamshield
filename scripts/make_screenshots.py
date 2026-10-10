"""Renders the synthetic scam messages as phone-style screenshots (PNG).

Run from the repo root:
    uv run --project backend python scripts/make_screenshots.py

Reads backend/tests/fixtures/scam_messages.json and writes one PNG per message
to backend/tests/fixtures/screenshots/. Use them to try the screenshot upload.
"""

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIXTURES = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
WIDTH, MARGIN, BUBBLE_PADDING = 720, 32, 24


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render(message: dict, path: Path) -> None:
    header_font, body_font, small_font = load_font(30), load_font(28), load_font(22)
    lines = textwrap.wrap(message["text"], width=44)
    line_height = 40
    bubble_height = len(lines) * line_height + 2 * BUBBLE_PADDING
    height = 120 + bubble_height + 90

    image = Image.new("RGB", (WIDTH, height), "#ECE5DD" if message["channel"] == "WhatsApp" else "#F2F2F7")
    draw = ImageDraw.Draw(image)

    # Header bar with the sender, like a messaging app.
    draw.rectangle([0, 0, WIDTH, 96], fill="#075E54" if message["channel"] == "WhatsApp" else "#FFFFFF")
    header_colour = "#FFFFFF" if message["channel"] == "WhatsApp" else "#000000"
    draw.text((MARGIN, 18), message["sender"], font=header_font, fill=header_colour)
    draw.text((MARGIN, 58), message["channel"], font=small_font, fill=header_colour)

    # The message bubble.
    top = 120
    draw.rounded_rectangle([MARGIN, top, WIDTH - MARGIN, top + bubble_height], radius=22, fill="#FFFFFF")
    for index, line in enumerate(lines):
        draw.text((MARGIN + BUBBLE_PADDING, top + BUBBLE_PADDING + index * line_height), line, font=body_font, fill="#111111")
    draw.text((WIDTH - MARGIN - 90, top + bubble_height + 12), "10:42 AM", font=small_font, fill="#666666")

    image.save(path)


def main() -> None:
    data = json.loads((FIXTURES / "scam_messages.json").read_text(encoding="utf-8"))
    out_dir = FIXTURES / "screenshots"
    out_dir.mkdir(exist_ok=True)
    for message in [*data["messages"], data["prompt_injection"]]:
        render(message, out_dir / f"{message['id']}.png")
        print(f"wrote {out_dir / (message['id'] + '.png')}")


if __name__ == "__main__":
    main()
