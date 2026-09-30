#!/usr/bin/env python3
"""
scripts/generate_og_image.py

Generates the Open Graph (OG) social preview card (1200 x 630 px) for the
Fields of Mistria Companion & Gift Planner web application.

Design Language:
- Dimensions: 1200 x 630 pixels, RGBA.
- Typography: Authentic in-game TrueType pixel font (Nosutaru / fnt_nosutaru.ttf).
- Palette: Warm stone & parchment theme matching the web design system:
  * Page background gradient: #fffdf7 to #f7f0e3
  * Plaque borders: 3px outline #c4a882 with dark framing #44382e
  * Accent highlights: Amber #d97706, Gold #f59e0b
  * Inks: Dark text #44382e, Muted text #8a7968
- Left Section:
  * Eyebrow tagline: "FIELDS OF MISTRIA" with wheat game sprite
  * Main title: "GIFT PLANNER & COMPANION"
  * Subtitle: "Daily Gift Bag Optimizer • Relationship Tracker • Crafting Trees"
  * Plaque feature pills: Optimal Daily Gifts, Interactive Craft Trees,
    Relationship Tracker, 100% Emoji-Free UI, and Live Save Auto-Sync.
- Right Section:
  * Showcase plaque featuring 4 key NPC portraits (Adeline, March, Celine, Balor)
    scaled with nearest-neighbor interpolation.
  * Favorite gift item badges with loved heart icons.
  * Seasonal corner badges (Spring, Summer, Fall, Winter).
  * Centerpiece gift box badge.
- Footer:
  * Unofficial Fan Tool disclaimer & repository URL.
"""

import argparse
import os
from pathlib import Path
import sys
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


def get_repo_root() -> Path:
    """Resolve repository root directory."""
    return Path(__file__).resolve().parent.parent


def resolve_font_path(custom_path: Optional[str] = None) -> Path:
    """Find fnt_nosutaru.ttf font file."""
    if custom_path and Path(custom_path).is_file():
        return Path(custom_path)
    
    candidates = [
        get_repo_root() / "companion" / "static" / "fonts" / "fnt_nosutaru.ttf",
        Path("/home/tyrell/Downloads/assets/fonts/fnt_nosutaru.ttf"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("Could not locate fnt_nosutaru.ttf. Please specify with --font.")


def load_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont:
    """Load TrueType font at specified point size."""
    return ImageFont.truetype(str(font_path), size)


def scale_nearest(img: Image.Image, scale: float) -> Image.Image:
    """Scale pixel art sprite preserving crisp nearest-neighbor edges."""
    w, h = img.size
    resample_filter = getattr(Image, "Resampling", Image).NEAREST
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return img.resize((new_w, new_h), resample=resample_filter)


def draw_vertical_gradient(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    color_top: Tuple[int, int, int],
    color_bottom: Tuple[int, int, int],
) -> None:
    """Fill a rectangular region with a smooth vertical linear gradient."""
    x0, y0, x1, y1 = box
    h = max(1, y1 - y0)
    r1, g1, b1 = color_top[:3]
    r2, g2, b2 = color_bottom[:3]
    for y in range(y0, y1 + 1):
        ratio = (y - y0) / h
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(x0, y), (x1, y)], fill=(r, g, b, 255))


def draw_rounded_plaque(
    canvas: Image.Image,
    box: Tuple[int, int, int, int],
    radius: int,
    color_top: Tuple[int, int, int],
    color_bottom: Tuple[int, int, int],
    border_color: Tuple[int, int, int],
    border_width: int = 2,
    shadow_offset: int = 3,
    shadow_color: Optional[Tuple[int, int, int]] = None,
) -> None:
    """Render a game-styled plaque card with 3D bottom shadow and gradient fill."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0

    # 3D Depth / Bottom outline shadow
    if shadow_offset > 0 and shadow_color:
        sdraw = ImageDraw.Draw(canvas)
        sdraw.rounded_rectangle(
            [x0, y0 + shadow_offset, x1, y1 + shadow_offset],
            radius=radius,
            fill=(*shadow_color[:3], 255),
        )

    # Gradient surface patch
    patch = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(patch)
    for y in range(h):
        ratio = y / max(1, h - 1)
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        pdraw.line([(0, y), (w, y)], fill=(r, g, b, 255))

    # Rounded mask
    mask = Image.new("L", (w, h), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    canvas.paste(patch, (x0, y0), mask)

    # Outline border & top inset highlight
    bdraw = ImageDraw.Draw(canvas)
    if border_width > 0 and border_color:
        bdraw.rounded_rectangle(
            [x0, y0, x1, y1],
            radius=radius,
            outline=(*border_color[:3], 255),
            width=border_width,
        )
        if radius >= 2 and h > 4:
            bdraw.line(
                [(x0 + radius, y0 + 1), (x1 - radius, y0 + 1)],
                fill=(255, 255, 255, 180),
                width=1,
            )


def draw_text_centered(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int, int],
) -> None:
    """Draw text horizontally centered around center_x."""
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0]
    draw.text((center_x - w // 2, y), text, font=font, fill=fill)


def draw_text_right(
    draw: ImageDraw.ImageDraw,
    right_x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int, int],
) -> None:
    """Draw text right-aligned against right_x."""
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0]
    draw.text((right_x - w, y), text, font=font, fill=fill)


def generate_og_image(
    output_path: Optional[Path] = None,
    font_path: Optional[Path] = None,
    assets_dir: Optional[Path] = None,
) -> Image.Image:
    """
    Generate the 1200 x 630 RGBA social preview card and save to output_path.
    """
    repo_root = get_repo_root()
    if output_path is None:
        output_path = repo_root / "companion" / "static" / "icons" / "og-image.png"
    if font_path is None:
        font_path = resolve_font_path()
    if assets_dir is None:
        assets_dir = repo_root / "companion" / "static" / "icons"

    W, H = 1200, 630
    # Outer dark stone rim frame
    img = Image.new("RGBA", (W, H), (62, 50, 40, 255))
    draw = ImageDraw.Draw(img)

    # Font sizing scale
    font_title = load_font(font_path, 48)
    font_eyebrow = load_font(font_path, 26)
    font_sub = load_font(font_path, 16)
    font_section = load_font(font_path, 18)
    font_pill_title = load_font(font_path, 17)
    font_pill_desc = load_font(font_path, 13)
    font_npc_name = load_font(font_path, 16)
    font_item_name = load_font(font_path, 13)
    font_footer = load_font(font_path, 15)

    # 1. Main Parchment Plaque Surface
    margin = 12
    draw_vertical_gradient(
        draw,
        (margin, margin, W - margin, H - margin),
        color_top=(255, 253, 247),
        color_bottom=(247, 240, 227),
    )

    # Outer Plaque Border: 3px outline #c4a882, dark border #44382e
    draw.rectangle([margin, margin, W - margin, H - margin], outline=(68, 56, 46, 255), width=2)
    draw.rectangle([margin + 2, margin + 2, W - margin - 2, H - margin - 2], outline=(196, 168, 130, 255), width=3)
    draw.rectangle([margin + 5, margin + 5, W - margin - 5, H - margin - 5], outline=(255, 255, 255, 140), width=1)

    # -------------------------------------------------------------------------
    # 2. Left Section: Branding & Features (x = 50 to 650)
    # -------------------------------------------------------------------------

    # Eyebrow / Tagline: "FIELDS OF MISTRIA" in amber #d97706
    wheat_path = assets_dir / "ui" / "icon_wheat.png"
    if wheat_path.is_file():
        wheat_sprite = scale_nearest(Image.open(wheat_path), 2.0)
        img.paste(wheat_sprite, (50, 48), wheat_sprite)
    draw.text((94, 54), "FIELDS OF MISTRIA", font=font_eyebrow, fill=(217, 119, 6, 255))

    # Main Title: "GIFT PLANNER & COMPANION" in dark ink #44382e
    draw.text((50, 96), "GIFT PLANNER & COMPANION", font=font_title, fill=(68, 56, 46, 255))

    # Subtitle: "Daily Gift Bag Optimizer • Relationship Tracker • Crafting Trees" in muted #8a7968
    draw.text(
        (50, 158),
        "Daily Gift Bag Optimizer • Relationship Tracker • Crafting Trees",
        font=font_sub,
        fill=(138, 121, 104, 255),
    )

    # Amber decorative divider bar
    draw_vertical_gradient(draw, (50, 192, 645, 195), (217, 119, 6), (245, 158, 11))

    # Plaque Feature Pills (2x2 grid)
    pills = [
        {
            "box": (50, 222, 335, 307),
            "icon": assets_dir / "ui" / "icon_gift.png",
            "icon_scale": 3.0,
            "title": "Optimal Daily Gifts",
            "desc": "Maximize hearts per bag slot",
        },
        {
            "box": (355, 222, 640, 307),
            "icon": assets_dir / "ui" / "icon_tree.png",
            "icon_scale": 2.2,
            "title": "Interactive Craft Trees",
            "desc": "Trace blocker recipe DAGs",
        },
        {
            "box": (50, 327, 335, 412),
            "icon": assets_dir / "ui" / "heart_loved.png",
            "icon_scale": 2.6,
            "title": "Relationship Tracker",
            "desc": "All 35+ Mistria townsfolk",
        },
        {
            "box": (355, 327, 640, 412),
            "icon": assets_dir / "ui" / "icon_check.png",
            "icon_scale": 3.2,
            "title": "100% Emoji-Free UI",
            "desc": "Authentic game pixel sprites",
        },
    ]

    for pill in pills:
        draw_rounded_plaque(
            img,
            pill["box"],
            radius=8,
            color_top=(255, 253, 249),
            color_bottom=(246, 239, 226),
            border_color=(196, 168, 130),
            border_width=2,
            shadow_offset=3,
            shadow_color=(196, 168, 130),
        )
        bx0, by0, bx1, by1 = pill["box"]
        if Path(pill["icon"]).is_file():
            p_icon = scale_nearest(Image.open(pill["icon"]), pill["icon_scale"])
            iw, ih = p_icon.size
            ix = bx0 + 16 + (36 - iw) // 2
            iy = by0 + (by1 - by0 - ih) // 2
            img.paste(p_icon, (ix, iy), p_icon)

        tx = bx0 + 60
        ty1 = by0 + 20
        ty2 = by0 + 46
        draw.text((tx, ty1), pill["title"], font=font_pill_title, fill=(68, 56, 46, 255))
        draw.text((tx, ty2), pill["desc"], font=font_pill_desc, fill=(138, 121, 104, 255))

    # Feature Banner below pills: Live Save Auto-Sync
    banner_box = (50, 432, 640, 502)
    draw_rounded_plaque(
        img,
        banner_box,
        radius=8,
        color_top=(251, 247, 238),
        color_bottom=(237, 230, 216),
        border_color=(196, 168, 130),
        border_width=2,
        shadow_offset=3,
        shadow_color=(196, 168, 130),
    )
    save_icon_path = assets_dir / "ui" / "icon_save.png"
    if save_icon_path.is_file():
        save_icon = scale_nearest(Image.open(save_icon_path), 2.2)
        iw, ih = save_icon.size
        img.paste(save_icon, (66, 432 + (70 - ih) // 2), save_icon)

    draw.text((115, 445), "Live Save File Auto-Sync", font=font_pill_title, fill=(68, 56, 46, 255))
    draw.text((115, 470), "Instant reactive re-planning upon in-game sleep / save", font=font_pill_desc, fill=(138, 121, 104, 255))

    # Vertical divider line between left and right sections
    draw.line([(665, 45), (665, 535)], fill=(223, 208, 190, 255), width=2)
    draw.line([(666, 45), (666, 535)], fill=(255, 255, 255, 120), width=1)

    # -------------------------------------------------------------------------
    # 3. Right Section: Game Sprite Showcase (x = 685 to 1150)
    # -------------------------------------------------------------------------
    showcase_box = (685, 45, 1150, 535)
    draw_rounded_plaque(
        img,
        showcase_box,
        radius=10,
        color_top=(252, 248, 239),
        color_bottom=(238, 226, 207),
        border_color=(196, 168, 130),
        border_width=2,
        shadow_offset=4,
        shadow_color=(196, 168, 130),
    )

    # Section Header inside Showcase Box
    draw_text_centered(draw, 917, 62, "VILLAGERS & FAVORITE GIFTS", font=font_section, fill=(68, 56, 46, 255))

    # Four Season Corner Badges
    seasons = [
        {"file": "season_spring.png", "box": (697, 56, 737, 96), "border": (236, 72, 153), "bg": (255, 245, 248)},
        {"file": "season_summer.png", "box": (1098, 56, 1138, 96), "border": (245, 158, 11), "bg": (255, 251, 235)},
        {"file": "season_fall.png", "box": (697, 484, 737, 524), "border": (234, 88, 12), "bg": (255, 247, 237)},
        {"file": "season_winter.png", "box": (1098, 484, 1138, 524), "border": (2, 132, 199), "bg": (240, 249, 255)},
    ]
    for s in seasons:
        sbx0, sby0, sbx1, sby1 = s["box"]
        draw.rounded_rectangle([sbx0, sby0, sbx1, sby1], radius=6, fill=s["bg"], outline=s["border"], width=2)
        s_path = assets_dir / "ui" / s["file"]
        if s_path.is_file():
            s_icon = scale_nearest(Image.open(s_path), 3.2)
            siw, sih = s_icon.size
            img.paste(s_icon, (sbx0 + (40 - siw) // 2, sby0 + (40 - sih) // 2), s_icon)

    # 4 NPC Showcase Cards (2x2 grid)
    npcs = [
        {
            "name": "ADELINE",
            "box": (707, 108, 907, 286),
            "portrait": assets_dir / "npcs" / "spr_ui_item_sub_npc_adeline.png",
            "item_icon": assets_dir / "items" / "spr_ui_item_cupoftea.png",
            "item_name": "Cup of Tea",
        },
        {
            "name": "MARCH",
            "box": (927, 108, 1127, 286),
            "portrait": assets_dir / "npcs" / "spr_ui_item_sub_npc_march.png",
            "item_icon": assets_dir / "items" / "spr_ui_item_gold_ingot.png",
            "item_name": "Gold Ingot",
        },
        {
            "name": "CELINE",
            "box": (707, 298, 907, 476),
            "portrait": assets_dir / "npcs" / "spr_ui_item_sub_npc_celine.png",
            "item_icon": assets_dir / "items" / "spr_ui_item_crystal_rose.png",
            "item_name": "Crystal Rose",
        },
        {
            "name": "BALOR",
            "box": (927, 298, 1127, 476),
            "portrait": assets_dir / "npcs" / "spr_ui_item_sub_npc_balor.png",
            "item_icon": assets_dir / "items" / "spr_ui_item_duck_feather_gold.png",
            "item_name": "Gold Feather",
        },
    ]

    heart_path = assets_dir / "ui" / "heart_loved.png"
    heart_img = scale_nearest(Image.open(heart_path), 1.6) if heart_path.is_file() else None

    for npc in npcs:
        nbx0, nby0, nbx1, nby1 = npc["box"]
        draw_rounded_plaque(
            img,
            npc["box"],
            radius=8,
            color_top=(255, 253, 249),
            color_bottom=(247, 241, 230),
            border_color=(196, 168, 130),
            border_width=2,
            shadow_offset=2,
            shadow_color=(196, 168, 130),
        )

        nc_x = (nbx0 + nbx1) // 2

        # NPC Portrait (24x20 scaled 3.6x -> 86x72)
        if Path(npc["portrait"]).is_file():
            port = scale_nearest(Image.open(npc["portrait"]), 3.6)
            pw, ph = port.size
            img.paste(port, (nc_x - pw // 2, nby0 + 10), port)

        # Name
        draw_text_centered(draw, nc_x, nby0 + 90, npc["name"], font=font_npc_name, fill=(68, 56, 46, 255))

        # Loved Gift Pill
        item_icon_path = Path(npc["item_icon"])
        item_img = scale_nearest(Image.open(item_icon_path), 1.4) if item_icon_path.is_file() else None
        
        # Calculate contents width for centered pill alignment
        heart_w = heart_img.size[0] if heart_img else 20
        item_w = item_img.size[0] if item_img else 22
        tbbox = font_item_name.getbbox(npc["item_name"])
        text_w = tbbox[2] - tbbox[0]
        
        gap = 6
        content_w = heart_w + gap + item_w + gap + text_w
        pill_w = max(164, content_w + 20)
        
        pw_box = (nc_x - pill_w // 2, nby0 + 120, nc_x + pill_w // 2, nby0 + 154)
        draw.rounded_rectangle(pw_box, radius=5, fill=(237, 230, 216, 255), outline=(196, 168, 130, 255), width=1)

        start_x = nc_x - content_w // 2
        # Paste heart
        if heart_img:
            img.paste(heart_img, (start_x, nby0 + 128), heart_img)
        # Paste item
        item_x = start_x + heart_w + gap
        if item_img:
            img.paste(item_img, (item_x, nby0 + 124), item_img)
        # Draw item name
        text_x = item_x + item_w + gap
        draw.text((text_x, nby0 + 128), npc["item_name"], font=font_item_name, fill=(68, 56, 46, 255))

    # Centerpiece Gift Badge at 4-card intersection
    cg_x, cg_y = 917, 292
    cr = 25
    draw.ellipse([cg_x - cr, cg_y - cr, cg_x + cr, cg_y + cr], fill=(255, 253, 249, 255), outline=(217, 119, 6, 255), width=2)
    gift_icon_path = assets_dir / "ui" / "icon_gift.png"
    if gift_icon_path.is_file():
        gift_icon = scale_nearest(Image.open(gift_icon_path), 2.8)
        gw, gh = gift_icon.size
        img.paste(gift_icon, (cg_x - gw // 2, cg_y - gh // 2), gift_icon)

    # -------------------------------------------------------------------------
    # 4. Bottom Section: Disclaimer & Credits
    # -------------------------------------------------------------------------
    draw.line([(40, 562), (W - 40, 562)], fill=(223, 208, 190, 255), width=2)
    draw.text(
        (50, 580),
        "Unofficial Fan Tool • Not Affiliated with NPC Studio",
        font=font_footer,
        fill=(138, 121, 104, 255),
    )
    draw_text_right(
        draw,
        W - 50,
        580,
        "https://github.com/chupachupbum/fom-gift-planner",
        font=font_footer,
        fill=(163, 145, 125, 255),
    )

    # Ensure parent output directory exists and save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), format="PNG")
    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OG Social Preview Card image.")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Destination path for the generated PNG image (default: companion/static/icons/og-image.png)",
    )
    parser.add_argument(
        "--font",
        type=Path,
        default=None,
        help="Path to fnt_nosutaru.ttf (default: auto-detect)",
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=None,
        help="Path to icons directory (default: companion/static/icons)",
    )
    args = parser.parse_args()

    out_file = args.output or (get_repo_root() / "companion" / "static" / "icons" / "og-image.png")
    image = generate_og_image(
        output_path=out_file,
        font_path=args.font,
        assets_dir=args.assets_dir,
    )
    print(f"Successfully generated OG preview image: {out_file} ({image.size[0]}x{image.size[1]} {image.mode})")


if __name__ == "__main__":
    main()
