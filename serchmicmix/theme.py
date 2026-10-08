"""Paleta y hoja de estilo de Serch MicMix (tema oscuro moderno)."""

from __future__ import annotations

# ------------------------------------------------------------------ colores
BG = "#0A0D16"
BG_ALT = "#0E1220"
SURFACE = "#131829"
CARD = "#171D30"
CARD_HOVER = "#1C2340"
CARD_ON = "#18253C"
BORDER = "#242C46"
BORDER_SOFT = "#1B2237"

TEXT = "#E9EDF9"
TEXT_DIM = "#8B94B0"
TEXT_MUTE = "#5C6480"

ACCENT = "#6D8BFF"
ACCENT_2 = "#45E3D1"
ACCENT_DEEP = "#3B54C9"

SUCCESS = "#3DDC97"
WARNING = "#FFC14D"
DANGER = "#FF6B7A"
INFO = "#55B9FF"

FONT_STACK = ["Segoe UI Variable Display", "Segoe UI", "Inter", "Arial"]


def rgba(hex_color: str, alpha: float) -> str:
    """Convierte '#RRGGBB' + alfa a 'rgba(r,g,b,a)' para QSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"


def mix(c1: str, c2: str, t: float) -> str:
    """Mezcla dos colores hex (t=0 -> c1, t=1 -> c2)."""
    t = max(0.0, min(1.0, t))
    a, b = c1.lstrip("#"), c2.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va, vb = int(a[i : i + 2], 16), int(b[i : i + 2], 16)
        out.append(int(round(va + (vb - va) * t)))
    return "#{:02X}{:02X}{:02X}".format(*out)


def qss() -> str:
    """Hoja de estilo global de la aplicacion."""
    return f"""
    QWidget {{
        color: {TEXT};
        font-family: "Segoe UI Variable Display", "Segoe UI", "Inter", Arial;
    }}
    QMainWindow, #Root {{
        background-color: {BG};
    }}
    #Header {{
        background-color: {BG_ALT};
        border-bottom: 1px solid {BORDER_SOFT};
    }}
    #Footer {{
        background-color: {BG_ALT};
        border-top: 1px solid {BORDER_SOFT};
    }}
    #PanelTitle {{
        color: {TEXT_DIM};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1.4px;
    }}
    #AppTitle {{
        font-size: 17px;
        font-weight: 700;
    }}
    #Subtle {{ color: {TEXT_DIM}; font-size: 12px; }}
    #Micro {{ color: {TEXT_MUTE}; font-size: 11px; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px 2px 2px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER}; border-radius: 5px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {ACCENT_DEEP}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSlider::groove:horizontal {{
        height: 5px; border-radius: 2px; background: {BORDER};
    }}
    QSlider::sub-page:horizontal {{
        height: 5px; border-radius: 2px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_DEEP}, stop:1 {ACCENT});
    }}
    QSlider::handle:horizontal {{
        background: {TEXT}; width: 13px; height: 13px;
        margin: -5px 0; border-radius: 6px;
    }}
    QSlider::handle:horizontal:hover {{ background: {ACCENT_2}; }}

    QPushButton {{
        background: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 9px; padding: 7px 14px; font-size: 12px;
    }}
    QPushButton:hover {{ background: {CARD_HOVER}; border-color: {ACCENT_DEEP}; }}
    QPushButton:pressed {{ background: {CARD}; }}
    QPushButton:disabled {{ color: {TEXT_MUTE}; border-color: {BORDER_SOFT}; }}

    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {ACCENT}, stop:1 {ACCENT_DEEP});
        border: none; color: #0A0D16; font-weight: 700;
    }}
    QPushButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {ACCENT_2}, stop:1 {ACCENT});
    }}
    QPushButton#Primary:disabled {{ background: {BORDER}; color: {TEXT_MUTE}; }}

    QPushButton#Ghost, QToolButton#Ghost {{
        background: transparent; border: 1px solid transparent;
        color: {TEXT_DIM}; padding: 6px 10px; border-radius: 9px;
        font-size: 15px; font-weight: 700;
    }}
    QPushButton#Ghost:hover, QToolButton#Ghost:hover {{
        color: {TEXT}; background: {SURFACE}; border-color: {BORDER};
    }}
    QToolButton#Ghost::menu-indicator {{ image: none; width: 0; }}

    QMenu {{
        background: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 12px; padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 26px 8px 14px; border-radius: 8px; font-size: 12px;
    }}
    QMenu::item:selected {{ background: {rgba(ACCENT, 0.22)}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 10px; }}

    QPushButton#Mini {{
        background: transparent; border: 1px solid {BORDER};
        border-radius: 7px; padding: 2px 9px; font-size: 11px; color: {TEXT_MUTE};
    }}
    QPushButton#Mini:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
    QPushButton#Mini:checked {{
        background: {rgba(ACCENT, 0.22)}; border-color: {ACCENT};
        color: {TEXT}; font-weight: 600;
    }}

    QLabel#CardTitle {{ font-size: 13px; font-weight: 600; }}

    QPushButton#Chip {{
        background: {SURFACE}; border: 1px solid {BORDER};
        border-radius: 14px; padding: 6px 14px; font-size: 12px;
    }}
    QPushButton#Chip:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
    QPushButton#Chip:checked {{
        background: {rgba(ACCENT, 0.18)}; border-color: {ACCENT}; color: {TEXT};
    }}

    QToolTip {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER}; padding: 6px 8px; border-radius: 6px;
    }}

    QDialog {{ background: {BG}; }}
    QProgressBar {{
        background: {BORDER_SOFT}; border: none; border-radius: 6px;
        height: 8px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{
        border-radius: 6px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_DEEP}, stop:1 {ACCENT_2});
    }}
    QMessageBox {{ background: {SURFACE}; }}
    """
