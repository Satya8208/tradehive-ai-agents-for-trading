from __future__ import annotations

from pathlib import Path
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "generated_images"
SIZE = (1600, 900)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


TITLE_FONT = load_font(66)
SUBTITLE_FONT = load_font(26)
MICRO_FONT = load_font(18)


def vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    base = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    return base


def add_radial_glow(image: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int], alpha: int) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for step in range(radius, 0, -12):
        strength = (step / radius) ** 2
        fill = (*color, int(alpha * strength))
        x, y = center
        draw.ellipse((x - step, y - step, x + step, y + step), fill=fill)
    image.alpha_composite(layer)


def add_starfield(image: Image.Image, rng: random.Random, count: int, palette: list[tuple[int, int, int]]) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    width, height = image.size
    for _ in range(count):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        radius = rng.choice((1, 1, 1, 2, 2, 3))
        color = rng.choice(palette)
        alpha = rng.randint(100, 210)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
        if radius >= 2 and rng.random() > 0.65:
            draw.line((x - 6, y, x + 6, y), fill=(*color, alpha // 2), width=1)
            draw.line((x, y - 6, x, y + 6), fill=(*color, alpha // 2), width=1)
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.6)))


def add_grid(image: Image.Image, spacing: int, color: tuple[int, int, int], alpha: int) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    width, height = image.size
    for x in range(0, width, spacing):
        draw.line((x, 0, x, height), fill=(*color, alpha), width=1)
    for y in range(0, height, spacing):
        draw.line((0, y, width, y), fill=(*color, alpha), width=1)
    image.alpha_composite(layer)


def add_candles(image: Image.Image, rng: random.Random, baseline: int, left_pad: int, right_pad: int) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    width = image.size[0]
    x = left_pad
    while x < width - right_pad:
        candle_height = rng.randint(36, 190)
        wick_height = candle_height + rng.randint(18, 70)
        candle_width = rng.randint(10, 18)
        direction = rng.choice((-1, 1))
        open_y = baseline - rng.randint(0, 120)
        close_y = open_y - candle_height * direction * 0.4
        high_y = min(open_y, close_y) - (wick_height * 0.45)
        low_y = max(open_y, close_y) + (wick_height * 0.2)
        color = (55, 214, 171) if close_y < open_y else (255, 112, 85)
        draw.line((x + candle_width // 2, high_y, x + candle_width // 2, low_y), fill=(*color, 150), width=2)
        top = min(open_y, close_y)
        bottom = max(open_y, close_y)
        draw.rounded_rectangle((x, top, x + candle_width, bottom), radius=3, fill=(*color, 205))
        x += candle_width + rng.randint(6, 12)
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.3)))


def add_wave_paths(image: Image.Image, rng: random.Random, colors: list[tuple[int, int, int]]) -> None:
    width, height = image.size
    for index, color in enumerate(colors):
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        amplitude = 40 + index * 18
        frequency = 0.006 + index * 0.0018
        phase = rng.random() * math.pi * 2
        offset = height * (0.28 + index * 0.11)
        points = []
        for x in range(0, width + 25, 25):
            y = offset + math.sin(x * frequency + phase) * amplitude + math.cos(x * frequency * 0.45 + phase) * amplitude * 0.35
            points.append((x, y))
        draw.line(points, fill=(*color, 170), width=4)
        for px, py in points[::8]:
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=(*color, 220))
        image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2.2)))


def add_orbits(image: Image.Image, center: tuple[int, int], radii: list[int], color: tuple[int, int, int], alpha: int) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = center
    for idx, radius in enumerate(radii):
        box = (cx - radius, cy - int(radius * 0.62), cx + radius, cy + int(radius * 0.62))
        draw.ellipse(box, outline=(*color, max(alpha - idx * 25, 35)), width=3)
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.4)))


def add_halo_bars(image: Image.Image, rng: random.Random, center_y: int, color: tuple[int, int, int]) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    width = image.size[0]
    x = 130
    while x < width - 130:
        bar_height = rng.randint(30, 230)
        draw.rounded_rectangle((x, center_y - bar_height, x + 18, center_y + rng.randint(10, 30)), radius=6, fill=(*color, 90))
        x += rng.randint(28, 42)
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(4)))


def add_label(image: Image.Image, title: str, subtitle: str, accent: tuple[int, int, int]) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((110, 102), title, font=TITLE_FONT, fill=(*accent, 255))
    draw.text((112, 184), subtitle.upper(), font=SUBTITLE_FONT, fill=(220, 232, 238, 215))
    draw.text((112, 220), "tradehive-ai-agents / experimental visuals", font=MICRO_FONT, fill=(180, 196, 208, 145))
    shadow = layer.filter(ImageFilter.GaussianBlur(8))
    image.alpha_composite(shadow)
    image.alpha_composite(layer)


def add_corner_code(image: Image.Image, text: str, color: tuple[int, int, int]) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bbox = draw.textbbox((0, 0), text, font=MICRO_FONT)
    width = bbox[2] - bbox[0]
    x = image.size[0] - width - 60
    y = image.size[1] - 54
    draw.text((x, y), text, font=MICRO_FONT, fill=(*color, 180))
    image.alpha_composite(layer)


def render_agent_swarm() -> Image.Image:
    rng = random.Random(7)
    base = vertical_gradient(SIZE, (6, 12, 28), (4, 8, 14)).convert("RGBA")
    add_radial_glow(base, (440, 290), 250, (255, 200, 112), 95)
    add_radial_glow(base, (1150, 250), 280, (45, 164, 255), 75)
    add_starfield(base, rng, 170, [(255, 210, 135), (162, 220, 255), (255, 255, 255)])
    add_grid(base, 80, (30, 64, 104), 32)
    add_orbits(base, (520, 360), [130, 220, 320], (255, 195, 118), 145)
    add_candles(base, rng, baseline=760, left_pad=110, right_pad=80)

    moon = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(moon)
    draw.ellipse((360, 180, 640, 460), fill=(255, 207, 126, 245))
    draw.ellipse((450, 170, 700, 455), fill=(9, 13, 28, 245))
    base.alpha_composite(moon.filter(ImageFilter.GaussianBlur(2.2)))

    nodes = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(nodes)
    cx, cy = 530, 360
    points = []
    for radius in (130, 220, 320):
        for step in range(0, 360, 45):
            ang = math.radians(step + rng.randint(-8, 8))
            x = cx + math.cos(ang) * radius
            y = cy + math.sin(ang) * radius * 0.62
            points.append((x, y))
    for x, y in points:
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(132, 223, 255, 225))
        draw.line((cx, cy, x, y), fill=(76, 156, 214, 88), width=2)
    base.alpha_composite(nodes.filter(ImageFilter.GaussianBlur(0.7)))

    add_label(base, "TradeHive Agent Swarm", "autonomous signal constellation", (255, 214, 146))
    add_corner_code(base, "docs/generated_images/tradehive-agent-swarm.png", (132, 223, 255))
    return base.convert("RGB")


def render_signal_storm() -> Image.Image:
    rng = random.Random(17)
    base = vertical_gradient(SIZE, (7, 16, 18), (2, 7, 10)).convert("RGBA")
    add_radial_glow(base, (260, 180), 240, (41, 212, 176), 65)
    add_radial_glow(base, (1280, 300), 290, (255, 150, 94), 70)
    add_grid(base, 72, (34, 86, 96), 34)
    add_starfield(base, rng, 120, [(165, 255, 238), (255, 206, 155), (255, 255, 255)])
    add_wave_paths(base, rng, [(51, 241, 186), (82, 176, 255), (255, 144, 104)])
    add_candles(base, rng, baseline=780, left_pad=100, right_pad=95)
    add_halo_bars(base, rng, 740, (255, 164, 114))
    add_label(base, "Solana Signal Storm", "latency, liquidity, momentum", (135, 255, 224))
    add_corner_code(base, "docs/generated_images/solana-signal-storm.png", (255, 176, 124))
    return base.convert("RGB")


def render_risk_guardian() -> Image.Image:
    rng = random.Random(31)
    base = vertical_gradient(SIZE, (14, 10, 26), (6, 6, 12)).convert("RGBA")
    add_radial_glow(base, (800, 340), 300, (255, 94, 120), 60)
    add_radial_glow(base, (790, 330), 200, (255, 214, 119), 55)
    add_grid(base, 90, (82, 46, 72), 26)
    add_starfield(base, rng, 115, [(255, 202, 129), (255, 132, 155), (255, 255, 255)])

    shield = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shield)
    shield_points = [(800, 150), (980, 220), (950, 510), (800, 650), (650, 510), (620, 220)]
    draw.polygon(shield_points, fill=(255, 194, 116, 55), outline=(255, 214, 146, 165))
    draw.polygon([(800, 220), (912, 265), (895, 468), (800, 572), (705, 468), (688, 265)], fill=(255, 107, 142, 70))
    draw.line((800, 230, 800, 560), fill=(255, 235, 188, 160), width=5)
    draw.line((720, 392, 880, 392), fill=(255, 235, 188, 160), width=5)
    base.alpha_composite(shield.filter(ImageFilter.GaussianBlur(3.2)))

    rings = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(rings)
    for radius, alpha in ((160, 120), (250, 80), (340, 50)):
        draw.ellipse((800 - radius, 340 - radius * 0.72, 800 + radius, 340 + radius * 0.72), outline=(255, 158, 178, alpha), width=3)
    for ang in range(0, 360, 30):
        rad = math.radians(ang)
        x = 800 + math.cos(rad) * 340
        y = 340 + math.sin(rad) * 340 * 0.72
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(255, 219, 150, 220))
        draw.line((800, 340, x, y), fill=(255, 123, 150, 64), width=2)
    base.alpha_composite(rings.filter(ImageFilter.GaussianBlur(1.2)))

    add_wave_paths(base, rng, [(255, 132, 150), (255, 203, 122)])
    add_label(base, "Risk-First Orchestrator", "circuit breakers before conviction", (255, 219, 146))
    add_corner_code(base, "docs/generated_images/risk-first-orchestrator.png", (255, 150, 168))
    return base.convert("RGB")


def save_image(filename: str, image: Image.Image) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_DIR / filename, quality=96)


def main() -> None:
    save_image("tradehive-agent-swarm.png", render_agent_swarm())
    save_image("solana-signal-storm.png", render_signal_storm())
    save_image("risk-first-orchestrator.png", render_risk_guardian())
    print(f"generated 3 images in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
