"""Charte graphique centralisée et sûre pour l'interface et les exports."""

from __future__ import annotations

import colorsys
import re


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_PALETTE = {
    "primary": "#3563AE",
    "secondary": "#244A8A",
    "accent": "#FFC83D",
    "light": "#EEF4FF",
    "text": "#1F2937",
    "success": "#198754",
    "warning": "#F59E0B",
    "danger": "#DC3545",
    "eleves": "#3563AE",
    "paiements": "#198754",
    "notes": "#7C3AED",
    "salaires": "#F59E0B",
    "bus": "#0EA5E9",
    "cantine": "#EC4899",
    "depenses": "#DC3545",
    "watermark_opacity": 0.08,
}

FIELD_MAP = {
    "primary": "couleur_principale",
    "secondary": "couleur_secondaire",
    "accent": "couleur_accent",
    "light": "couleur_fond_clair",
    "text": "couleur_texte",
    "success": "couleur_succes",
    "warning": "couleur_avertissement",
    "danger": "couleur_danger",
    "eleves": "couleur_carte_eleves",
    "paiements": "couleur_carte_paiements",
    "notes": "couleur_carte_notes",
    "salaires": "couleur_carte_salaires",
    "bus": "couleur_carte_bus",
    "cantine": "couleur_carte_cantine",
    "depenses": "couleur_carte_depenses",
}


def normalize_hex(value, fallback="#3563AE"):
    value = str(value or "").strip()
    if not HEX_COLOR_RE.fullmatch(value):
        value = fallback
    return value.upper()


def hex_to_rgb(value):
    value = normalize_hex(value).lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(channel))):02X}" for channel in rgb)


def mix_colors(color, other="#FFFFFF", ratio=0.5):
    ratio = max(0.0, min(1.0, float(ratio)))
    left = hex_to_rgb(color)
    right = hex_to_rgb(other)
    return rgb_to_hex(tuple(
        left[index] * (1 - ratio) + right[index] * ratio
        for index in range(3)
    ))


def relative_luminance(value):
    channels = []
    for channel in hex_to_rgb(value):
        normalized = channel / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.03928
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_text(background):
    return "#111827" if relative_luminance(background) > 0.45 else "#FFFFFF"


def get_school_palette(ecole=None):
    """Retourne toujours une palette complète, même sans école/configuration."""
    palette = dict(DEFAULT_PALETTE)
    if ecole is not None:
        for key, field_name in FIELD_MAP.items():
            value = getattr(ecole, field_name, None)
            palette[key] = normalize_hex(value, palette[key])
        try:
            opacity = float(getattr(ecole, "opacite_filigrane", palette["watermark_opacity"]))
            palette["watermark_opacity"] = max(0.0, min(0.25, opacity))
        except (TypeError, ValueError):
            pass

    palette.update({
        "primary_dark": mix_colors(palette["primary"], "#000000", 0.22),
        "primary_soft": mix_colors(palette["primary"], "#FFFFFF", 0.88),
        "secondary_soft": mix_colors(palette["secondary"], "#FFFFFF", 0.88),
        "accent_soft": mix_colors(palette["accent"], "#FFFFFF", 0.82),
        "success_soft": mix_colors(palette["success"], "#FFFFFF", 0.82),
        "warning_soft": mix_colors(palette["warning"], "#FFFFFF", 0.82),
        "danger_soft": mix_colors(palette["danger"], "#FFFFFF", 0.82),
        "primary_text": contrast_text(palette["primary"]),
        "secondary_text": contrast_text(palette["secondary"]),
        "accent_text": contrast_text(palette["accent"]),
        "success_text": contrast_text(palette["success"]),
        "warning_text": contrast_text(palette["warning"]),
        "danger_text": contrast_text(palette["danger"]),
    })
    palette["rgb"] = {
        key: ", ".join(str(channel) for channel in hex_to_rgb(palette[key]))
        for key in ("primary", "secondary", "accent", "success", "warning", "danger")
    }
    return palette


def extract_palette_from_logo(logo_path):
    """Extrait des couleurs franches d'un logo, en ignorant blancs et gris."""
    from PIL import Image

    image = Image.open(logo_path).convert("RGB")
    image.thumbnail((180, 180))
    quantized = image.quantize(colors=12, method=Image.Quantize.MEDIANCUT).convert("RGB")
    counts = quantized.getcolors(maxcolors=180 * 180) or []
    candidates = []
    for count, rgb in counts:
        red, green, blue = rgb
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if value < 0.18 or value > 0.96 or saturation < 0.18:
            continue
        candidates.append((count * (0.35 + saturation), hue, saturation, value, rgb))
    candidates.sort(reverse=True)

    primary_rgb = candidates[0][4] if candidates else (53, 99, 174)
    primary_hue = colorsys.rgb_to_hsv(*(channel / 255 for channel in primary_rgb))[0]
    secondary_rgb = None
    for _, hue, _, _, rgb in candidates[1:]:
        distance = min(abs(hue - primary_hue), 1 - abs(hue - primary_hue))
        if distance >= 0.10:
            secondary_rgb = rgb
            break
    secondary_rgb = secondary_rgb or tuple(channel * 0.72 for channel in primary_rgb)
    accent_rgb = candidates[2][4] if len(candidates) > 2 else (255, 200, 61)

    primary = rgb_to_hex(primary_rgb)
    secondary = rgb_to_hex(secondary_rgb)
    accent = rgb_to_hex(accent_rgb)
    return {
        "couleur_principale": primary,
        "couleur_secondaire": secondary,
        "couleur_accent": accent,
        "couleur_fond_clair": mix_colors(primary, "#FFFFFF", 0.90),
    }


def reportlab_color(ecole, key="primary"):
    from reportlab.lib import colors

    return colors.HexColor(get_school_palette(ecole)[key])


def excel_color(ecole, key="primary"):
    return get_school_palette(ecole)[key].lstrip("#")

