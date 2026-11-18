"""Генерация 3D-аватаров ReduxShop.

Запуск: python scripts/make_avatars.py
Результат: assets/avatars/*.png (1024×1024) и контактный лист.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "avatars"
SIZE = 1024
SS = 2
W = SIZE * SS

NAVY = (5, 6, 14)
PURPLE = (124, 92, 255)
PURPLE_DEEP = (42, 22, 96)
CYAN = (128, 240, 252)
CYAN_DEEP = (26, 150, 170)
WHITE = (247, 247, 255)
LAVENDER = (199, 188, 255)

FONT_BOLD = Path("C:/Windows/Fonts/segoeuib.ttf")
FONT_BLACK = Path("C:/Windows/Fonts/ariblk.ttf")


# ---------------------------------------------------------------------------
# Градиенты и цвет
# ---------------------------------------------------------------------------


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def multi_gradient_v(size: int, stops: list[tuple[float, tuple[int, int, int]]]) -> Image.Image:
    column = Image.new("RGB", (1, size))
    px = column.load()
    stops = sorted(stops)
    for y in range(size):
        t = y / max(1, size - 1)
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if p0 <= t <= p1:
                k = 0 if p1 == p0 else (t - p0) / (p1 - p0)
                px[0, y] = _mix(c0, c1, k)
                break
        else:
            px[0, y] = stops[-1][1]
    return column.resize((size, size), Image.BICUBIC)


def multi_gradient_h(size: int, stops: list[tuple[float, tuple[int, int, int]]]) -> Image.Image:
    row = Image.new("RGB", (size, 1))
    px = row.load()
    stops = sorted(stops)
    for x in range(size):
        t = x / max(1, size - 1)
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if p0 <= t <= p1:
                k = 0 if p1 == p0 else (t - p0) / (p1 - p0)
                px[x, 0] = _mix(c0, c1, k)
                break
        else:
            px[x, 0] = stops[-1][1]
    return row.resize((size, size), Image.BICUBIC)


def radial(
    size: int,
    inner: tuple[int, int, int],
    outer: tuple[int, int, int],
    cx: float = 0.5,
    cy: float = 0.5,
    radius: float = 0.8,
    power: float = 1.6,
) -> Image.Image:
    small = 200
    img = Image.new("RGB", (small, small))
    px = img.load()
    icx, icy = cx * small, cy * small
    maxd = radius * small
    for y in range(small):
        for x in range(small):
            d = min(1.0, math.hypot(x - icx, y - icy) / maxd) ** power
            px[x, y] = _mix(inner, outer, d)
    return img.resize((size, size), Image.BICUBIC)


def blob(
    size: int,
    cx: float,
    cy: float,
    radius: float,
    color: tuple[int, int, int],
    strength: float = 1.0,
    power: float = 2.2,
) -> Image.Image:
    small = 160
    img = Image.new("RGB", (small, small))
    px = img.load()
    icx, icy = cx * small, cy * small
    maxd = max(1.0, radius * small)
    for y in range(small):
        for x in range(small):
            d = min(1.0, math.hypot(x - icx, y - icy) / maxd)
            k = (1 - d) ** power * strength
            px[x, y] = tuple(int(c * k) for c in color)
    return img.resize((size, size), Image.BICUBIC)


def screen(base: Image.Image, layer: Image.Image) -> Image.Image:
    """Screen-наложение; RGBA-слой сначала сплющивается на чёрный."""
    if layer.mode == "RGBA":
        flat = Image.new("RGB", layer.size, (0, 0, 0))
        flat.paste(layer, (0, 0), layer)
        layer = flat
    if base.mode != "RGB":
        base = base.convert("RGB")
    return ImageChops.screen(base, layer)


def add(base: Image.Image, layer: Image.Image) -> Image.Image:
    return Image.alpha_composite(base, layer)


def gradient_map(mask: Image.Image, stops: list[tuple[float, tuple[int, int, int]]]) -> Image.Image:
    return Image.composite(multi_gradient_v(W, stops), Image.new("RGB", (W, W)), mask)


def rgba_color(mask: Image.Image, color: tuple[int, int, int], opacity: float = 1.0) -> Image.Image:
    m = mask.point(lambda v: int(v * opacity))
    layer = Image.new("RGBA", (W, W), color + (0,))
    layer.putalpha(m)
    return layer


def palette(mask: Image.Image, stops: list[tuple[float, tuple[int, int, int]]], opacity: float = 1.0) -> Image.Image:
    rgb = gradient_map(mask, stops)
    layer = rgb.convert("RGBA")
    layer.putalpha(mask.point(lambda v: int(v * opacity)))
    return layer


def shadow(
    mask: Image.Image,
    dx: float,
    dy: float,
    blur: float,
    opacity: float,
    color: tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
    m = Image.new("L", (W, W), 0)
    m.paste(mask, (int(dx), int(dy)))
    m = m.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * opacity))
    layer = Image.new("RGBA", (W, W), color + (0,))
    layer.putalpha(m)
    return layer


def shifted(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    return ImageChops.offset(mask, dx, dy)


def glow(mask: Image.Image, color: tuple[int, int, int], radius: int, strength: float = 0.8) -> Image.Image:
    blurred = mask.filter(ImageFilter.GaussianBlur(radius))
    return rgba_color(blurred, color, strength)


def text_mask(
    text: str,
    font_path: Path,
    size: int,
    cx: float = 0.5,
    cy: float = 0.5,
) -> Image.Image:
    mask = Image.new("L", (W, W), 0)
    draw = ImageDraw.Draw(mask)
    fnt = ImageFont.truetype(str(font_path), size)
    bbox = draw.textbbox((0, 0), text, font=fnt)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = W * cx - width / 2 - bbox[0]
    y = W * cy - height / 2 - bbox[1]
    draw.text((x, y), text, font=fnt, fill=255)
    return mask


# ---------------------------------------------------------------------------
# 3D-объекты
# ---------------------------------------------------------------------------


def text_object(
    text: str,
    font_path: Path,
    font_size: int,
    center: tuple[float, float],
    depth: int,
    side_stops: list[tuple[float, tuple[int, int, int]]],
    face_stops: list[tuple[float, tuple[int, int, int]]],
    dirx: float = 0.40,
    diry: float = 0.92,
    bevel: int = 7 * SS,
    rim_color: tuple[int, int, int] | None = None,
) -> tuple[Image.Image, Image.Image]:
    """Экструдированная монограмма: боковины, фаска, глянец и тени."""
    mask = text_mask(text, font_path, font_size, center[0], center[1])

    side = Image.new("L", (W, W), 0)
    for i in range(depth, 0, -1):
        f = i / depth
        ox = int(dirx * depth * f)
        oy = int(diry * depth * f)
        side = ImageChops.lighter(side, shifted(mask, ox, oy))
    side = ImageChops.lighter(side, mask)

    side_rgb = gradient_map(side, side_stops)
    side_rgb = ImageChops.multiply(
        side_rgb,
        multi_gradient_h(
            W,
            [
                (0.0, (255, 255, 255)),
                (0.55, (220, 210, 245)),
                (1.0, (120, 100, 175)),
            ],
        ),
    )

    face_rgb = gradient_map(mask, face_stops)
    face_rgb = screen(face_rgb, blob(W, 0.38, 0.26, 0.55, (56, 44, 80), 0.55))
    face = face_rgb.convert("RGBA")
    face.putalpha(mask)

    light_edge = ImageChops.subtract(mask, shifted(mask, bevel, bevel))
    light_edge = light_edge.filter(ImageFilter.GaussianBlur(2 * SS))
    dark_edge = ImageChops.subtract(mask, shifted(mask, -bevel, -bevel))
    dark_edge = dark_edge.filter(ImageFilter.GaussianBlur(2 * SS))

    face = add(face, rgba_color(dark_edge, (14, 6, 34), 0.65))
    face = add(face, rgba_color(light_edge, (255, 255, 255), 0.72))

    # Мягкий глянцевый блик в верхней части буквы
    gloss = Image.new("L", (W, W), 0)
    gd = ImageDraw.Draw(gloss)
    gx, gy = W * center[0], W * center[1]
    gd.ellipse(
        (gx - 320 * SS, gy - 370 * SS, gx + 150 * SS, gy - 40 * SS),
        fill=255,
    )
    gloss = gloss.filter(ImageFilter.GaussianBlur(40 * SS))
    gloss = ImageChops.multiply(gloss, mask)
    face = add(face, rgba_color(gloss, (255, 255, 255), 0.16))

    # Тонкий световой кант с нижней правой стороны
    if rim_color is not None:
        rim = ImageChops.subtract(mask, shifted(mask, -4 * SS, -4 * SS))
        rim = rim.filter(ImageFilter.GaussianBlur(2 * SS))
        face = add(face, rgba_color(rim, rim_color, 0.35))

    side_layer = side_rgb.convert("RGBA")
    side_layer.putalpha(side)
    side_layer = add(side_layer, rgba_color(light_edge, (210, 190, 255), 0.25))

    obj = add(side_layer, face)

    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    layer = add(layer, shadow(obj.getchannel("A"), 26 * SS, 40 * SS, 46 * SS, 0.55))
    layer = add(layer, shadow(obj.getchannel("A"), 8 * SS, 12 * SS, 10 * SS, 0.55))
    layer = add(layer, obj)
    return layer, mask


def ball(
    radius: int,
    inner: tuple[int, int, int],
    outer: tuple[int, int, int],
    rim: tuple[int, int, int] | None = None,
    spec: float = 0.9,
    hotspot: tuple[float, float] = (0.34, 0.28),
) -> Image.Image:
    """Глянцевый 3D-шар с бликом и световым кантом."""
    n = radius * 2
    img = Image.new("RGB", (n, n))
    px = img.load()
    hx, hy = hotspot[0] * n, hotspot[1] * n
    maxd = n * 0.80
    for y in range(n):
        for x in range(n):
            d = min(1.0, math.hypot(x - hx, y - hy) / maxd) ** 1.25
            color = _mix(inner, outer, d)

            rc = math.hypot(x - n / 2, y - n / 2) / (n / 2)
            if rim is not None and rc > 0.80:
                k = min(1.0, (rc - 0.80) / 0.20) ** 2 * 0.7
                color = _mix(color, rim, k)

            sd = math.hypot(x - n * 0.33, y - n * 0.25) / (n * 0.14)
            if sd < 1:
                color = _mix(color, (255, 255, 255), (1 - sd) ** 2 * spec)
            px[x, y] = color

    big = 512
    alpha = Image.new("L", (big, big), 0)
    ImageDraw.Draw(alpha).ellipse((0, 0, big - 1, big - 1), fill=255)
    alpha = alpha.resize((n, n), Image.LANCZOS)
    disc = img.convert("RGBA")
    disc.putalpha(alpha)
    return disc


def ring(
    rx: int,
    ry: int,
    angle: float,
    width: int,
    stops: list[tuple[float, tuple[int, int, int]]],
) -> tuple[Image.Image, Image.Image]:
    """Металлическое кольцо-орбита с бликом; возвращает слой и маску."""
    mask = Image.new("L", (W, W), 0)
    draw = ImageDraw.Draw(mask)
    box = (W / 2 - rx, W / 2 - ry, W / 2 + rx, W / 2 + ry)
    draw.ellipse(box, outline=255, width=width)

    base = gradient_map(mask, stops).convert("RGBA")
    base.putalpha(mask)

    highlight = Image.new("L", (W, W), 0)
    hd = ImageDraw.Draw(highlight)
    hd.arc(box, start=170, end=340, fill=255, width=max(2, width // 3))
    highlight = highlight.filter(ImageFilter.GaussianBlur(2 * SS))
    highlight = ImageChops.multiply(highlight, mask)
    base = add(base, rgba_color(highlight, (255, 255, 255), 0.55))

    dark = Image.new("L", (W, W), 0)
    dd = ImageDraw.Draw(dark)
    dd.arc(box, start=350, end=165, fill=255, width=max(2, width // 4))
    dark = dark.filter(ImageFilter.GaussianBlur(2 * SS))
    dark = ImageChops.multiply(dark, mask)
    base = add(base, rgba_color(dark, (18, 8, 40), 0.55))

    base = base.rotate(angle, center=(W / 2, W / 2), resample=Image.BICUBIC)
    mask = mask.rotate(angle, center=(W / 2, W / 2), resample=Image.BICUBIC)
    return base, mask


def half_mask(angle: float, lower: bool = True) -> Image.Image:
    m = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(m)
    if lower:
        d.rectangle((0, int(W / 2) - 2, W, W), fill=255)
    else:
        d.rectangle((0, 0, W, int(W / 2) + 2), fill=255)
    return m.rotate(angle, center=(W / 2, W / 2), resample=Image.BICUBIC)


def polygon_mask(points: list[tuple[float, float]]) -> Image.Image:
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def hex_points(r: float, rotation: float = 90) -> list[tuple[float, float]]:
    return [
        (
            W / 2 + r * math.cos(math.radians(rotation + 60 * i)),
            W / 2 + r * math.sin(math.radians(rotation + 60 * i)),
        )
        for i in range(6)
    ]


# ---------------------------------------------------------------------------
# Фон
# ---------------------------------------------------------------------------


def background(seed: int, hue: str = "purple") -> Image.Image:
    bg = radial(W, (26, 19, 52), NAVY, cy=0.46, radius=0.74)
    bg = screen(bg, blob(W, 0.22, 0.80, 0.62, (70, 38, 168), 0.8))
    bg = screen(bg, blob(W, 0.82, 0.18, 0.52, (22, 120, 150), 0.6))
    if hue == "magenta":
        bg = screen(bg, blob(W, 0.78, 0.74, 0.42, (90, 22, 120), 0.45))
    bg = screen(bg, blob(W, 0.50, 0.08, 0.4, (40, 30, 90), 0.5))

    rng = random.Random(seed)
    bokeh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bokeh)
    palette_colors = [(188, 176, 255), (128, 232, 250), (90, 70, 190)]
    for _ in range(22):
        x = rng.uniform(0.08, 0.92) * W
        y = rng.uniform(0.08, 0.92) * W
        r = rng.uniform(4, 18) * SS
        color = rng.choice(palette_colors)
        alpha = rng.randint(18, 46)
        bd.ellipse((x - r, y - r, x + r, y + r), fill=color + (alpha,))
    bokeh = bokeh.filter(ImageFilter.GaussianBlur(6 * SS))
    bg = add(bg.convert("RGBA"), bokeh)

    for _ in range(14):
        x = rng.uniform(0.12, 0.88) * W
        y = rng.uniform(0.12, 0.88) * W
        r = rng.uniform(1.2, 2.6) * SS
        dot = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        ImageDraw.Draw(dot).ellipse(
            (x - r, y - r, x + r, y + r), fill=(220, 235, 255, rng.randint(90, 170))
        )
        bg = add(bg, dot)

    # Виньетка
    vig = radial(W, (255, 255, 255), (60, 55, 85), radius=0.62, power=1.4)
    bg = ImageChops.multiply(bg.convert("RGB"), vig).convert("RGBA")
    return bg


def ground_shadow(cx: float, cy: float, rx: float, ry: float, opacity: float, blur: float) -> Image.Image:
    m = Image.new("L", (W, W), 0)
    ImageDraw.Draw(m).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(blur))
    return rgba_color(m, (0, 0, 0), opacity)


# ---------------------------------------------------------------------------
# Вариант 1: объёмная монограмма R
# ---------------------------------------------------------------------------


def avatar_neon() -> Image.Image:
    bg = background(11)
    bg = add(bg, ground_shadow(W / 2, 850 * SS, 300 * SS, 44 * SS, 0.5, 44 * SS))

    # Кольцо за буквой
    torus, torus_mask = ring(420 * SS, 185 * SS, -17, 26 * SS, [
        (0.0, (224, 214, 255)),
        (0.45, (150, 112, 255)),
        (0.78, (96, 70, 225)),
        (1.0, (82, 218, 244)),
    ])
    bg = add(bg, shadow(torus_mask, 20 * SS, 44 * SS, 36 * SS, 0.55))
    bg = screen(bg.convert("RGB"), glow(torus_mask, PURPLE, 28 * SS, 0.45)).convert("RGBA")
    bg = add(bg, torus)

    layer, mask = text_object(
        "R",
        FONT_BOLD,
        700 * SS,
        (0.5, 0.495),
        56 * SS,
        side_stops=[
            (0.0, (132, 98, 242)),
            (0.45, (80, 48, 175)),
            (1.0, (24, 10, 60)),
        ],
        face_stops=[
            (0.0, (247, 243, 255)),
            (0.42, (190, 178, 255)),
            (0.72, (132, 231, 250)),
            (1.0, (76, 196, 235)),
        ],
        rim_color=CYAN,
    )
    bg = screen(bg.convert("RGB"), glow(mask, PURPLE, 42 * SS, 0.4)).convert("RGBA")
    bg = add(bg, layer)

    # 3D-шары
    for radius, pos, colors, rim in (
        (34 * SS, (0.175, 0.70), ((226, 250, 255), (22, 110, 130)), CYAN),
        (22 * SS, (0.815, 0.335), ((240, 232, 255), (58, 32, 120)), LAVENDER),
        (15 * SS, (0.78, 0.66), ((255, 255, 255), (70, 58, 110)), None),
    ):
        disc = ball(radius, colors[0], colors[1], rim)
        x = int(pos[0] * W - radius)
        y = int(pos[1] * W - radius)
        sm = Image.new("L", (W, W), 0)
        sm.paste(disc.getchannel("A"), (x, y))
        bg = add(bg, shadow(sm, 6 * SS, 16 * SS, 14 * SS, 0.6))
        bg.alpha_composite(disc, (x, y))

    return bg


# ---------------------------------------------------------------------------
# Вариант 2: 3D-глобус с орбитами
# ---------------------------------------------------------------------------


def avatar_orbit() -> Image.Image:
    bg = background(23, hue="magenta")
    bg = add(bg, ground_shadow(W / 2, 830 * SS, 280 * SS, 46 * SS, 0.62, 30 * SS))

    r = 226 * SS
    disc = ball(
        r,
        (216, 194, 255),
        (24, 14, 64),
        rim=(70, 225, 245),
        spec=0.75,
        hotspot=(0.33, 0.27),
    )
    core_layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    core_layer.alpha_composite(disc, (int(W / 2 - r), int(W / 2 - r)))
    disc_mask = core_layer.getchannel("A")

    # Сетка меридианов на глобусе
    grid = Image.new("L", (W, W), 0)
    gd = ImageDraw.Draw(grid)
    for k in (0.30, 0.62):
        gd.ellipse(
            (W / 2 - r * k, W / 2 - r, W / 2 + r * k, W / 2 + r),
            outline=110,
            width=2 * SS,
        )
    gd.ellipse((W / 2 - r, W / 2 - r, W / 2 + r, W / 2 + r), outline=90, width=2 * SS)
    for dy in (-0.62, -0.30, 0.30, 0.62):
        hw = math.sqrt(max(0.0, 1 - dy * dy)) * r
        yy = dy * r
        gd.ellipse(
            (W / 2 - hw, W / 2 + yy - r * 0.16, W / 2 + hw, W / 2 + yy + r * 0.16),
            outline=90,
            width=2 * SS,
        )
    grid = ImageChops.multiply(grid, disc_mask)
    grid = grid.filter(ImageFilter.GaussianBlur(1 * SS))
    core_layer = add(core_layer, rgba_color(grid, (150, 235, 255), 0.20))

    # Две орбиты: задняя половина за шаром, передняя — поверх
    orbits = [
        (400 * SS, 285 * SS, -16, 18 * SS),
        (330 * SS, 235 * SS, 27, 10 * SS),
    ]
    ring_layers = []
    for rx, ry, angle, width in orbits:
        rl, rm = ring(rx, ry, angle, width, [
            (0.0, (232, 224, 255)),
            (0.42, (168, 130, 255)),
            (0.74, (110, 84, 232)),
            (1.0, (105, 230, 246)),
        ])
        ring_layers.append((rl, rm, angle))

    for rl, rm, angle in ring_layers:
        bg = add(bg, shadow(rm, 12 * SS, 34 * SS, 26 * SS, 0.45))
        back = rl.copy()
        back.putalpha(ImageChops.multiply(back.getchannel("A"), half_mask(angle, lower=False)))
        bg = add(bg, back)
        bg = screen(bg.convert("RGB"), glow(rm, PURPLE, 20 * SS, 0.35)).convert("RGBA")

    bg = add(bg, core_layer)

    for rl, rm, angle in ring_layers:
        front_mask = ImageChops.multiply(rm, half_mask(angle, lower=True))
        bg = add(bg, shadow(front_mask, 0, 5 * SS, 7 * SS, 0.45))
        front = rl.copy()
        front.putalpha(ImageChops.multiply(front.getchannel("A"), half_mask(angle, lower=True)))
        bg = add(bg, front)

    # Спутник на передней орбите
    t = math.radians(28)
    rx, ry, angle = orbits[0][0], orbits[0][1], math.radians(orbits[0][2])
    px = W / 2 + rx * math.cos(t) * math.cos(angle) - ry * math.sin(t) * math.sin(angle)
    py = W / 2 + rx * math.cos(t) * math.sin(angle) + ry * math.sin(t) * math.cos(angle)
    sat_r = 20 * SS
    sat = ball(sat_r, (240, 252, 255), (26, 92, 120), CYAN)
    sx, sy = int(px - sat_r), int(py - sat_r)
    sm = Image.new("L", (W, W), 0)
    sm.paste(sat.getchannel("A"), (sx, sy))
    bg = add(bg, shadow(sm, 0, 14 * SS, 12 * SS, 0.55))
    bg = screen(bg.convert("RGB"), glow(sm, CYAN, 16 * SS, 0.5)).convert("RGBA")
    bg.alpha_composite(sat, (sx, sy))

    return bg


# ---------------------------------------------------------------------------
# Вариант 3: объёмный гексагон-бейдж
# ---------------------------------------------------------------------------


def avatar_hex() -> Image.Image:
    bg = background(37)

    cx = cy = W / 2
    r = 372 * SS
    depth = 34 * SS
    face = hex_points(r, 90)
    face_mask = polygon_mask(face)

    side = Image.new("L", (W, W), 0)
    for i in range(depth, 0, -1):
        shift_y = int(0.93 * i)
        shift_x = int(0.36 * i)
        side.paste(face_mask, (shift_x, shift_y), face_mask)
    side = ImageChops.lighter(side, face_mask)

    bg = add(bg, ground_shadow(cx, cy + r * 0.98, r * 0.86, 38 * SS, 0.6, 40 * SS))

    side_rgb = gradient_map(side, [
        (0.0, (118, 88, 230)),
        (0.55, (58, 32, 132)),
        (1.0, (18, 8, 44)),
    ])
    side_layer = side_rgb.convert("RGBA")
    side_layer.putalpha(side)
    bg = add(bg, shadow(side, 20 * SS, 34 * SS, 30 * SS, 0.5))
    bg = add(bg, side_layer)

    # Стеклянная лицевая пластина
    plate = radial(W, (46, 32, 96), (10, 9, 26), cx=0.42, cy=0.34, radius=0.42, power=1.4)
    plate = screen(plate, blob(W, 0.68, 0.74, 0.34, (22, 84, 110), 0.55))
    plate_layer = plate.convert("RGBA")
    plate_layer.putalpha(face_mask)

    # Внутренняя тень по краю
    eroded = face_mask.filter(ImageFilter.MinFilter(41))
    inner_edge = ImageChops.subtract(face_mask, eroded)
    inner_edge = inner_edge.filter(ImageFilter.GaussianBlur(7 * SS))
    plate_layer = add(plate_layer, rgba_color(inner_edge, (4, 3, 12), 0.75))

    # Диагональный блик стекла
    glass = Image.new("L", (W, W), 0)
    gd = ImageDraw.Draw(glass)
    gd.polygon(
        [
            (cx - 520 * SS, cy + 40 * SS),
            (cx - 300 * SS, cy - 520 * SS),
            (cx + 40 * SS, cy - 560 * SS),
            (cx - 180 * SS, cy + 80 * SS),
        ],
        fill=255,
    )
    glass = glass.filter(ImageFilter.GaussianBlur(36 * SS))
    glass = ImageChops.multiply(glass, face_mask)
    plate_layer = add(plate_layer, rgba_color(glass, (255, 255, 255), 0.07))

    bg = add(bg, plate_layer)

    # Градиентная кромка
    border_mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(border_mask).line(
        face + [face[0]], fill=255, width=11 * SS, joint="curve"
    )
    border = palette(border_mask, [
        (0.0, (238, 232, 255)),
        (0.45, (172, 138, 255)),
        (1.0, (100, 228, 246)),
    ])
    bg = screen(bg.convert("RGB"), glow(border_mask, PURPLE, 24 * SS, 0.55)).convert("RGBA")
    bg = screen(bg.convert("RGB"), glow(border_mask, CYAN, 8 * SS, 0.35)).convert("RGBA")
    bg = add(bg, border)

    # 3D-монограмма
    r_layer, r_mask = text_object(
        "R",
        FONT_BLACK,
        530 * SS,
        (0.5, 0.49),
        32 * SS,
        side_stops=[
            (0.0, (146, 116, 248)),
            (0.50, (78, 46, 170)),
            (1.0, (22, 9, 54)),
        ],
        face_stops=[
            (0.0, (255, 255, 255)),
            (0.55, (236, 244, 255)),
            (1.0, (168, 234, 250)),
        ],
        rim_color=CYAN,
    )
    bg = screen(bg.convert("RGB"), glow(r_mask, CYAN, 30 * SS, 0.25)).convert("RGBA")
    bg = add(bg, r_layer)

    # Металлические заклёпки
    for index in (0, 2, 4):
        angle = math.radians(90 + 60 * index)
        rr = 322 * SS
        x = cx + rr * math.cos(angle)
        y = cy + rr * math.sin(angle)
        rv = ball(11 * SS, (242, 240, 255), (80, 76, 110), (200, 190, 255), spec=0.7)
        rx0, ry0 = int(x - 11 * SS), int(y - 11 * SS)
        sm = Image.new("L", (W, W), 0)
        sm.paste(rv.getchannel("A"), (rx0, ry0))
        bg = add(bg, shadow(sm, 2 * SS, 5 * SS, 5 * SS, 0.55))
        bg.alpha_composite(rv, (rx0, ry0))

    return bg


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------


def save(name: str, image: Image.Image) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    image.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(path, "PNG", optimize=True)
    return path


def contact_sheet(paths: list[Path]) -> Path:
    cell = 384
    pad = 28
    width = pad * 2 + cell * len(paths)
    height = 560
    sheet = Image.new("RGB", (width, height), (6, 7, 14))
    draw = ImageDraw.Draw(sheet)
    fnt = ImageFont.truetype(str(FONT_BOLD), 22)

    for i, path in enumerate(paths):
        im = Image.open(path).resize((cell, cell), Image.LANCZOS)
        x = pad + i * cell
        y = 36
        mask = Image.new("L", (cell, cell), 0)
        ImageDraw.Draw(mask).ellipse((4, 4, cell - 4, cell - 4), fill=255)
        sheet.paste(im, (x, y), mask)
        small = im.resize((64, 64), Image.LANCZOS)
        small_mask = Image.new("L", (64, 64), 0)
        ImageDraw.Draw(small_mask).ellipse((0, 0, 64, 64), fill=255)
        sheet.paste(small, (x + cell - 72, y + cell - 56), small_mask)
        label = path.stem.replace("avatar-", "").replace("-", " ")
        draw.text((x + 4, y + cell + 22), label, font=fnt, fill=(190, 190, 215))

    path = OUT / "preview.png"
    sheet.save(path, "PNG", optimize=True)
    return path


def main() -> None:
    paths = [
        save("avatar-1-neon-r.png", avatar_neon()),
        save("avatar-2-orbit.png", avatar_orbit()),
        save("avatar-3-hex.png", avatar_hex()),
    ]
    preview = contact_sheet(paths)
    for path in (*paths, preview):
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
