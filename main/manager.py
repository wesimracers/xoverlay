# manager.py — Overlay Manager Controller
import os, sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QStatusBar,
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QSizePolicy, QScrollArea, QLineEdit,
    QTabWidget, QFrame, QComboBox, QGridLayout, QFileDialog, QRadioButton, QButtonGroup,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette, QColor, QFont

import core
from sector_timing import SECTOR_COLUMNS
from weather_columns import WEATHER_COLUMNS, weather_columns
from rpm_state import RPM_WINDOW_DEFAULTS, RPM_UPDATE_MS, car_key, finite_number, resolve_max_rpm
from race_review import RaceMonitor
from race_review_ui import DriverReviewDialog

APP_NAME = "Overlay Manager"
VERSION  = "1.2"


# ── Dark theme ────────────────────────────────────────────────────────────────

def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(35,  35,  35))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.Base,            QColor(22,  22,  22))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(44,  44,  44))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(50,  50,  50))
    pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.Text,            QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.Button,          QColor(52,  52,  52))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.BrightText,      QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(42,  130, 218))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.Link,            QColor(100, 170, 255))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       QColor(90, 90, 90))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(90, 90, 90))
    app.setPalette(pal)
    app.setStyleSheet("""
        QMainWindow, QDialog  { background: #232323; }
        QWidget               { background: transparent; }
        QListWidget           { border: 1px solid #444; background: #1e1e1e; }
        QListWidget::item     { padding: 0px; border-bottom: 1px solid #3a3a3a; background: transparent; }
        QListWidget::item:selected { background: #2a5a8a; }
        QGroupBox             { border: 1px solid #555; border-radius: 4px; margin-top: 8px;
                                font-weight: bold; background: transparent; }
        QGroupBox::title      { subcontrol-origin: margin; padding: 0 4px; }
        QScrollArea           { border: 1px solid #3a3a3a; background: #1a1a1a; }
        QTabWidget::pane      { border: 1px solid #555; }
        QTabBar::tab          { background: #3a3a3a; color: #aaa; padding: 4px 14px;
                                border: 1px solid #555; border-bottom: none; }
        QTabBar::tab:selected { background: #484848; color: #fff; }
        QPushButton           { border: 1px solid #555; border-radius: 3px; padding: 3px 10px;
                                background: #484848; color: #ddd; }
        QPushButton:hover     { background: #585858; }
        QPushButton:pressed   { background: #383838; }
        QPushButton#btnToggleOn   { background: #2a6e2a; color: #fff; border: 1px solid #3a9e3a;
                                    font-weight: bold; min-width: 44px; }
        QPushButton#btnToggleOn:hover  { background: #3a7e3a; }
        QPushButton#btnToggleOff  { background: #404040; color: #888; border: 1px solid #555;
                                    min-width: 44px; }
        QPushButton#btnToggleOff:hover { background: #505050; }
        QPushButton#btnConfig     { background: #3a3a3a; color: #ccc; border: 1px solid #555;
                                    min-width: 56px; }
        QPushButton#btnConfig:hover    { background: #4a4a4a; }
        QPushButton#btnGeneral    { background: #2e2e50; color: #aaf; border: 1px solid #4444aa;
                                    min-width: 90px; }
        QPushButton#btnGeneral:hover   { background: #3e3e70; }
        QPushButton#btnMove       { background: #333; border: 1px solid #555;
                                    padding: 0px; min-width: 20px; max-width: 20px;
                                    min-height: 18px; max-height: 18px; font-size: 9px; }
        QSpinBox, QDoubleSpinBox  { background: #2a2a2a; color: #e0e0e0; border: 1px solid #555;
                                    padding: 2px 4px; }
        QLineEdit                 { background: #2a2a2a; color: #e0e0e0; border: 1px solid #555;
                                    padding: 2px 4px; }
        QCheckBox::indicator      { width: 14px; height: 14px; }
        QStatusBar                { background: #1e1e1e; color: #aaa; border-top: 1px solid #444; }
        QLabel#labelEnabled       { color: #aaa; padding: 3px 6px; }
        QLabel#labelConn          { color: #44cc44; }
        QLabel#labelDisconn       { color: #cc4444; }
    """)


# ── Master column catalogue ───────────────────────────────────────────────────
# Superset of every column id each window supports.
# The config dialog merges this with whatever is already saved in overlay.json.

ALL_COLUMNS = {
    "longest_sector": SECTOR_COLUMNS,
    "info": [
        {"id": "laps",     "label": "LAPS",    "width": 130},
        {"id": "time",     "label": "TIME",    "width": 90},
        {"id": "simtime",  "label": "SimTime", "width": 80},
        {"id": "realtime", "label": "RealTime","width": 80},
        {"id": "inc",      "label": "INC",     "width": 80},
    ],
    "weather": WEATHER_COLUMNS,
    "fuel": [
        {"id": "last",   "label": "LAST", "width": 80},
        {"id": "avg",    "label": "AVG",  "width": 80},
        {"id": "fuel",   "label": "F",    "width": 180},
        {"id": "cons",   "label": "C",    "width": 60},
        {"id": "refuel", "label": "R",    "width": 70},
    ],
    "standings": [
        {"id": "pos",     "label": "POS",  "width": 24},
        {"id": "num",     "label": "#",    "width": 25},
        {"id": "brand",   "label": "BR",   "width": 25},
        {"id": "ir",      "label": "SDr",  "width": 38},
        {"id": "gap",     "label": "GAP",  "width": 36},
        {"id": "int",     "label": "INT",  "width": 36},
        {"id": "best",    "label": "BEST", "width": 51},
        {"id": "avg",     "label": "AVG",  "width": 40},
        {"id": "last",    "label": "LAST", "width": 58},
        {"id": "inc",     "label": "INC",  "width": 24},
        {"id": "pen",     "label": "PEN",  "width": 40},
        {"id": "tire",    "label": "T",    "width": 14},
        {"id": "lppit",   "label": "LPIT", "width": 35},
        {"id": "pittime", "label": "PIT",  "width": 50},
    ],
    "relative": [
        {"id": "pos",    "label": "POS",  "width": 24},
        {"id": "num",    "label": "#",    "width": 25},
        {"id": "brand",  "label": "BR",   "width": 25},
        {"id": "ir",     "label": "SDr",  "width": 38},
        {"id": "gap",    "label": "GAP",  "width": 36},
        {"id": "flag",   "label": "FLAG", "width": 35},
        {"id": "p",      "label": "P",    "width": 16},
        {"id": "best",   "label": "BEST", "width": 51},
        {"id": "avg",    "label": "AVG",  "width": 40},
        {"id": "last",   "label": "LAST", "width": 51},
        {"id": "inc",    "label": "INC",  "width": 24},
        {"id": "pen",    "label": "PEN",  "width": 40},
        {"id": "tire",   "label": "T",    "width": 14},
        {"id": "lppit",  "label": "LPIT", "width": 35},
        {"id": "report", "label": "RPT",  "width": 22},
    ],
}


# ── Widget metadata ───────────────────────────────────────────────────────────

WIDGET_DEFS = [
    {"key": "racechat", "label": "RaceChat", "settings_key": "racechat_settings", "has_columns": False, "fields": []},
    {
        "key": "longest_sector",
        "label": "Sectors",
        "settings_key": "longest_sector_settings",
        "has_columns": True,
        "fields": [("update_ms", "Update (ms)", "int", 10, 2000, 100)],
    },
    {
        "key": "relative",
        "label": "Relative",
        "settings_key": "relative_settings",
        "has_columns": True,
        "fields": [
            ("rows_ahead",  "Rows Ahead",  "int",   1,   20,   3),
            ("rows_behind", "Rows Behind", "int",   1,   20,   3),
            ("avg_laps",    "AVG Laps",    "int",   1,   30,   5),
            ("update_ms",   "Update (ms)", "int",  10, 2000, 100),
        ],
    },
    {
        "key": "standings",
        "label": "Standings",
        "settings_key": "standings_settings",
        "has_columns": True,
        "fields": [
            ("rows_ahead",         "Rows Ahead",         "int",   1,  30,   5),
            ("rows_behind",        "Rows Behind",        "int",   1,  30,   5),
            ("top_per_class",      "Top Per Class",      "int",   1,  10,   3),
            ("avg_laps",           "AVG Laps",           "int",   1,  30,   5),
            ("multiclass_headers", "Multiclass Headers", "bool",  0,   1,   1),
            ("show_top_last_laps", "Top 3 Last Laps", "bool", 0, 1, 1),
            ("update_ms",          "Update (ms)",        "int",  10, 2000, 100),
        ],
    },
    {
        "key": "info",
        "label": "Info",
        "settings_key": "info_settings",
        "has_columns": True,
        "fields": [
            ("update_ms", "Update (ms)", "int", 50, 5000, 250),
        ],
    },
    {
        "key": "weather",
        "label": "Weather",
        "settings_key": "weather_settings",
        "has_columns": True,
        "fields": [
            ("update_ms", "Update (ms)", "int", 50, 5000, 500),
        ],
    },
    {
        "key": "fuel",
        "label": "Fuel",
        "settings_key": "fuel_settings",
        "has_columns": True,
        "fields": [
            ("avg_window_laps",        "Avg Window (laps)",     "int",    1,  30,  5),
            ("max_lap_fuel",           "Max Lap Fuel (L)",      "float",  1, 500, 50.0),
            ("reserve_liters",         "Reserve (L)",           "float",  0,  30,  0.5),
            ("extra_consumption_pct",  "Extra Consumption (%)", "float",  0,  50,  3.0),
            ("consumption_percentile", "Consumption Percentile","int",    1, 100, 75),
            ("update_ms", "Update (ms)", "int", 50, 2000, 100),  # 261001_CURSOR
        ],
    },
    {
        "key": "rpm",
        "label": "RPM",
        "settings_key": "rpm_settings",
        "has_columns": False,
        "fields": [("update_ms", "Update (ms)", "int", 5, 2000, RPM_UPDATE_MS)],
    },
    {
        "key": "input",
        "label": "Input Trace",
        "settings_key": "input_settings",
        "has_columns": False,
        "fields": [
            ("fps",            "FPS",           "int",   10, 240,  120),
            ("window_seconds", "Window (sec)",  "float",  1,  60,  12.0),
            ("smoothing",      "Smoothing",     "int",    1,  20,   3),
            ("pen_width",      "Line Width",    "int",    1,   5,   2),
        ],
    },
    {
        "key": "tyres",
        "label": "Tyres",
        "settings_key": "tyre_settings",
        "has_columns": False,
        "fields": [
            ("update_ms",  "Update (ms)",       "int",   50, 5000, 250),
            ("cold_temp",  "Cold Temp (°C)",    "float",  0,  150,  60.0),
            ("warm_temp",  "Warm Temp (°C)",    "float",  0,  150,  75.0),
            ("ideal_high", "Ideal High (°C)",   "float",  0,  200,  95.0),
            ("hot_temp",   "Hot Temp (°C)",     "float",  0,  250, 105.0),
        ],
    },
    {
        "key": "alert",
        "label": "Alert",
        "settings_key": "alert_settings",
        "has_columns": False,
        "fields": [
            ("update_ms",       "Update (ms)",         "int",    20, 1000,  100),
            ("rate_threshold",  "Closing Rate (>=)",   "float",  0.1,  2.0,  0.8),
            ("gap_max_sec",     "Max Gap to Watch (s)","float",  1.0, 30.0,  5.0),
            ("history_seconds", "Rate Window (s)",     "float",  0.5,  5.0,  2.0),
            ("flash_hz",        "Flash Hz",            "float",  0.5, 10.0,  4.0),
            ("activation_delay_s", "Activation Delay (s)", "float", 0.0, 2.0, 0.25),
            ("priority_alert",  "Priority ALERT",      "int",    1,    9,    1),
            ("priority_yellow", "Priority Yellow",     "int",    1,    9,    2),
            ("priority_dirty",  "Priority Dirty Track","int",    1,    9,    3),
            ("priority_blue",   "Priority Blue",       "int",    1,    9,    4),
            ("show_border",     "Show Border",         "bool",   0,    1,    0),
        ],
    },
    {
        "key": "hr",
        "label": "HR",
        "settings_key": "heart_settings",
        "has_columns": False,
        "fields": [
            ("update_ms",     "Update (ms)",     "int",   50, 5000, 250),
            ("stale_seconds", "Stale (s)",       "int",    5,  600,  30),
            ("widget_url",    "Pulsoid URL",     "str",    "",   "",  ""),
            ("heart_font_size",   "Heart Font Size",     "int",    8,  96,  24),
            ("heart_text_color",  "Heart Text Color",    "str",    "",   "", "#FFFFFF"),
            ("heart_fill_color",  "Heart Fill Color",    "str",    "",   "", "#000000"),
            ("heart_border_color","Heart Border Color",  "str",    "",   "", "#FFFFFF"),
        ],
    },
    {
        "key": "garage",
        "label": "Garage Cover",
        "settings_key": "garage_settings",
        "has_columns": False,
        "fields": [
            ("update_ms",  "Update (ms)",          "int",  50, 5000,   250),
            ("bg_color",   "Background (#RRGGBB)", "str",  "",   "",  "#101010"),
            ("fg_color",   "Label color (#RRGGBB)","str",  "",   "",  "#FFFFFF"),
            ("label",      "Label text",           "str",  "",   "",  "GARAGE"),
            ("obs_url",    "OBS URL",              "str",  "",   "",  "http://127.0.0.1:8765/garage-cover"),
            ("show_label", "Show Label",           "bool",  0,    1,    1),
        ],
    },
    {
        "key": "wind",
        "label": "Wind",
        "settings_key": "wind_settings",
        "has_columns": False,
        "fields": [
            ("update_ms",   "Update (ms)",     "int",   50, 5000, 250),
            ("show_kmh",    "Show km/h",       "bool",   0,    1,   1),
            ("circle_color","Circle (#RRGGBB)","str",   "",   "",  "#101010"),
            ("border_color","Border (#RRGGBB)","str",   "",   "",  "#FFFFFF"),
            ("arrow_size",  "Arrow Size",      "float", 0.4,  1.6,  1.0),
            ("speed_box_color",  "Speed Box (#RRGGBB)",  "str",   "",   "",  "#000000"),
            ("speed_text_color", "Speed Text (#RRGGBB)", "str",   "",   "",  "#FFFFFF"),
            ("speed_box_width",  "Speed Box Width",      "float", 0.6,  2.5,  1.0),
            ("speed_box_height", "Speed Box Height",     "float", 0.6,  2.5,  1.0),
            ("arrow_color", "Arrow (#RRGGBB)", "str",   "",   "",  "#FFC800"),
        ],
    },
]

# Window geometry / show flags (shared across all windows)
# font_size = 0 → inherit the GENERAL font size; any non-zero value overrides
# it for THIS window only (user asked for per-window font sizing so a compact
# INFO bar can sit next to a larger STANDINGS table without one rule fitting
# all). The default 0 keeps existing setups untouched on upgrade.
WINDOW_FIELDS = [
    ("x",             "Position X",     "int",  -9999, 9999, 100),
    ("y",             "Position Y",     "int",  -9999, 9999, 100),
    ("width",         "Width",          "int",     50, 4000, 300),
    ("height",        "Height",         "int",     20, 4000, 200),
    ("font_size",     "Font Size (0=global)", "int", 0, 64, 0),
    ("show_in_garage","Show In Garage", "bool",     0,    1,   0),
]

# Global UI settings (under core.cfg["ui"])
GENERAL_FIELDS = [
    ("font_family", "Font Family",    "str",  "",  "",  "Consolas"),
    ("font_size",   "Font Size",      "int",   6,  32,  10),
    ("row_height",  "Row Height",     "int",  10,  60,  18),
    ("padding_x",   "Padding X",      "int",   0,  30,   3),
    ("padding_y",   "Padding Y",      "int",   0,  30,   3),
    ("update_ms",   "Base Update MS", "int",   1, 1000,  10),
]


# ── Config helpers ────────────────────────────────────────────────────────────

def _is_enabled(key: str) -> bool:
    return bool((core.cfg.get("windows") or {}).get(key, {}).get("enabled", key != "racechat"))


def _set_enabled(key: str, val: bool):
    core.cfg.setdefault("windows", {}).setdefault(key, {})["enabled"] = val
    core.save_cfg()


def _get_settings(skey: str) -> dict:
    return core.cfg.get(skey) or {}


def _get_window(key: str) -> dict:
    return (core.cfg.get("windows") or {}).get(key, {})


def _merged_columns(win_key: str) -> list:
    """Return ordered column list for win_key.

    Uses whatever is in overlay.json (preserving user order / enabled flags),
    then appends any master columns not yet present (disabled by default).
    """
    skey = next((d["settings_key"] for d in WIDGET_DEFS if d["key"] == win_key), None)
    cfg_cols = list((core.cfg.get(skey) or {}).get("columns") or [])
    if win_key == "weather":
        cfg_cols = weather_columns(cfg_cols)
    cfg_ids  = {c.get("id") for c in cfg_cols}
    for m in ALL_COLUMNS.get(win_key, []):
        if m["id"] not in cfg_ids:
            cfg_cols.append({"id": m["id"], "label": m["label"],
                             "width": m["width"], "enabled": False})
    return cfg_cols


# ── Columns editor ────────────────────────────────────────────────────────────

class ColumnsEditor(QGroupBox):
    """Scrollable list of all columns for a window.

    Each row:  [✓ enabled]  [id]  [header label]  [width]  [▲][▼]
    Rows can be reordered with ▲/▼.  Saves back to overlay.json on OK.
    """

    _ROW_H = 26   # pixels per row

    def __init__(self, win_key: str, parent=None):
        super().__init__("Columns", parent)
        self._win_key = win_key
        self._data    = []   # list of dicts: {id, enabled, label, width}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 14, 6, 6)
        outer.setSpacing(4)

        # Column header labels
        hdr = QHBoxLayout()
        hdr.setSpacing(4)
        hdr.addSpacing(2)
        for text, w in [("On", 22), ("ID", 54), ("Header", 0), ("W", 46), ("", 44)]:
            lbl = QLabel(text)
            lbl.setStyleSheet("color:#888; font-size:9px;")
            if w:
                lbl.setFixedWidth(w)
            else:
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            hdr.addWidget(lbl)
        outer.addLayout(hdr)

        # Scroll area that holds all rows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(240)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._container = QWidget()
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(1)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

        # Load initial data from config
        for col in _merged_columns(win_key):
            self._data.append({
                "id":      col.get("id", ""),
                "enabled": bool(col.get("enabled", True)),
                "label":   col.get("label", col.get("id", "").upper()),
                "width":   int(col.get("width", 40)),
            })

        self._rebuild()

    # ── internal ──────────────────────────────────────────────────────────────

    def _collect_values(self):
        """Read current widget values back into self._data before a reorder."""
        for d, w in zip(self._data, self._widgets):
            d["enabled"] = w["check"].isChecked()
            label = w["lbl_edit"].text().strip()
            if self._win_key == "weather" and d["id"] == "condition":
                d["label"] = label
            else:
                d["label"] = label or d["id"].upper()
            d["width"]   = w["width_spin"].value()

    def _rebuild(self):
        """Clear and recreate all row widgets from self._data."""
        # Remove old widgets
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._widgets = []

        for idx, d in enumerate(self._data):
            row_w = QWidget()
            row_w.setFixedHeight(self._ROW_H)
            hl = QHBoxLayout(row_w)
            hl.setContentsMargins(2, 0, 2, 0)
            hl.setSpacing(4)

            check = QCheckBox()
            check.setChecked(d["enabled"])
            check.setFixedWidth(22)

            id_lbl = QLabel(d["id"])
            id_lbl.setFixedWidth(54)
            id_lbl.setStyleSheet("color:#777; font-size:9px;")

            lbl_edit = QLineEdit(d["label"])
            lbl_edit.setMinimumWidth(52)

            width_spin = QSpinBox()
            width_spin.setRange(8, 400)
            width_spin.setFixedWidth(46)
            width_spin.setValue(d["width"])

            btn_up = QPushButton("▲")
            btn_up.setObjectName("btnMove")
            btn_dn = QPushButton("▼")
            btn_dn.setObjectName("btnMove")

            hl.addWidget(check)
            hl.addWidget(id_lbl)
            hl.addWidget(lbl_edit, 1)
            hl.addWidget(width_spin)
            hl.addWidget(btn_up)
            hl.addWidget(btn_dn)

            btn_up.clicked.connect(lambda _, i=idx: self._move(i, -1))
            btn_dn.clicked.connect(lambda _, i=idx: self._move(i, +1))

            self._vbox.addWidget(row_w)
            self._widgets.append({
                "check": check, "lbl_edit": lbl_edit, "width_spin": width_spin,
            })

        self._vbox.addStretch()

    def _move(self, idx: int, direction: int):
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._data):
            return
        self._collect_values()
        self._data[idx], self._data[new_idx] = self._data[new_idx], self._data[idx]
        self._rebuild()

    # ── public ────────────────────────────────────────────────────────────────

    def get_columns(self) -> list:
        """Return column dicts in current display order."""
        self._collect_values()
        return [{"id": d["id"], "label": d["label"],
                 "width": d["width"], "enabled": d["enabled"]}
                for d in self._data]


# ── General config dialog ─────────────────────────────────────────────────────

class GeneralConfigDialog(QDialog):
    """Edit global UI settings (font, row height, padding, update rate, debug)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("General Config")
        self.setMinimumWidth(300)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # UI group
        grp_ui = QGroupBox("UI / Fonts / Layout")
        form   = QFormLayout(grp_ui)
        form.setSpacing(6)
        ui = core.cfg.get("ui") or {}
        self._inputs = {}
        for fkey, flabel, ftype, fmin, fmax, fdef in GENERAL_FIELDS:
            val = ui.get(fkey, fdef)
            w   = self._make_input(ftype, fmin, fmax, val)
            self._inputs[fkey] = w
            form.addRow(flabel, w)
        layout.addWidget(grp_ui)

        # Debug group
        grp_dbg = QGroupBox("Debug")
        fd = QFormLayout(grp_dbg)
        fd.setSpacing(6)
        self._cmb_debug = QComboBox()
        self._cmb_debug.addItems(["DISABLE", "ENABLE"])
        cur = str(core.cfg.get("debug", "DISABLE")).upper()
        self._cmb_debug.setCurrentIndex(1 if cur == "ENABLE" else 0)
        fd.addRow("Debug Mode", self._cmb_debug)
        note_dbg = QLabel(
            "ENABLE: records telemetry to data_YYYYMMDD_HHMMSS.json each session.\n"
            "DISABLE: no file is written, no logging."
        )
        note_dbg.setWordWrap(True)
        note_dbg.setStyleSheet("color:#888; font-size:9px;")
        fd.addRow("", note_dbg)
        layout.addWidget(grp_dbg)

        note = QLabel("* Font Family and Row Height changes require a restart to fully apply.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#777; font-size:9px;")
        layout.addWidget(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _make_input(self, ftype, fmin, fmax, val):
        if ftype == "str":
            le = QLineEdit(str(val or ""))
            return le
        elif ftype == "float":
            sb = QDoubleSpinBox()
            sb.setDecimals(2)
            sb.setRange(float(fmin), float(fmax))
            try:    sb.setValue(float(val))
            except: sb.setValue(float(fmin))
            return sb
        else:
            sb = QSpinBox()
            sb.setRange(int(fmin), int(fmax))
            try:    sb.setValue(int(float(val)))
            except: sb.setValue(int(fmin))
            return sb

    def _save_and_close(self):
        ui = core.cfg.setdefault("ui", {})
        for fkey, flabel, ftype, fmin, fmax, fdef in GENERAL_FIELDS:
            w = self._inputs.get(fkey)
            if w is None:
                continue
            if isinstance(w, QLineEdit):
                ui[fkey] = w.text().strip() or fdef
            elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                ui[fkey] = w.value()

        debug_val = "ENABLE" if self._cmb_debug.currentIndex() == 1 else "DISABLE"
        core.cfg["debug"] = debug_val
        core.save_cfg()

        # Apply in-memory immediately (no restart needed for numeric values)
        try:
            core.PAD_X     = int(ui.get("padding_x",  3))
            core.PAD_Y     = int(ui.get("padding_y",  3))
            core.ROW_H     = int(ui.get("row_height", 18))
            core.UPDATE_MS = int(ui.get("update_ms",  10))
            core.DEBUG     = (str(core.cfg.get("debug", "DISABLE")).upper() == "ENABLE")
            # When enabling debug mid-session, stamp a new data file from this moment
            if core.DEBUG:
                import time as _t
                _ts = _t.strftime("%Y%m%d_%H%M%S")
                core.DATA_FILE = os.path.join(
                    core.DEBUG_ARCHIVE_DIR, f"data_{_ts}.json"
                )
            fam = ui.get("font_family", "Consolas")
            fsz = int(ui.get("font_size", 10))
            core.FONT_NORMAL = QFont(fam, fsz)
            core.FONT_BOLD   = QFont(fam, fsz)
            core.FONT_BOLD.setBold(True)
        except Exception:
            pass

        self.accept()


# ── Widget config dialog ──────────────────────────────────────────────────────

class AllowedApplicationsDialog(QDialog):
    """Exceptions and deliberate launches; discovery never launches an app."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("Pop-up Protection — Allowed applications")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        note = QLabel("Allow mode keeps these apps visible and preserves their focus.\n"
                      "Block all suspends every saved exception without deleting this list.\n"
                      "Save this list, then Save Config to apply your changes.\n"
                      "Console hosts are shared by several programs; their exceptions allow all hosted consoles.\n"
                      "Open selected uses the currently saved protection mode and normal Windows activation; it never approves administrative access.")
        note.setWordWrap(True); layout.addWidget(note)
        self._list = QListWidget(); self._list.setMinimumHeight(180); layout.addWidget(self._list)
        from allowed_applications import normalize
        self._entries = normalize(owner._allowed_apps)
        self._render()
        controls = QHBoxLayout()
        for label, callback in (("Add executable…", self._add_executable), ("Remove selected", self._remove), ("Open selected", self._open)):
            button = QPushButton(label); button.clicked.connect(callback); controls.addWidget(button)
        layout.addLayout(controls)
        self._find = QPushButton("Find installed apps")
        self._find.clicked.connect(self._discover); layout.addWidget(self._find)
        self._installed = QComboBox(); layout.addWidget(self._installed)
        add = QPushButton("Allow selected installed app"); add.clicked.connect(self._add_installed); layout.addWidget(add)
        self._status = QLabel("Installed apps are queried only when you choose Find installed apps.")
        self._status.setWordWrap(True); layout.addWidget(self._status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self._catalog_result = None
        self._timer = QTimer(self); self._timer.timeout.connect(self._poll_catalog); self._timer.start(250)

    def _render(self):
        self._list.clear()
        for entry in self._entries:
            item = QListWidgetItem(entry["label"])
            item.setToolTip(entry["path"] or "Process name: " + entry["process"])
            self._list.addItem(item)
        if self._entries:
            self._list.setCurrentRow(0)

    def _add_executable(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose an application to allow", "", "Windows applications (*.exe)")
        if path:
            from allowed_applications import from_executable, normalize
            self._entries = normalize([*self._entries, from_executable(path)])
            self._render()

    def _remove(self):
        row = self._list.currentRow()
        if row >= 0:
            self._entries.pop(row); self._render()

    def _discover(self):
        if not self._find.isEnabled():
            return
        self._find.setEnabled(False); self._status.setText("Reading the current user's installed apps…")
        import threading
        def query():
            try:
                from allowed_applications import installed_apps
                self._catalog_result = (installed_apps(), "")
            except Exception:
                self._catalog_result = ([], "Installed app discovery is unavailable; add an executable instead.")
        threading.Thread(target=query, name="Overlay installed app inventory", daemon=True).start()

    def _poll_catalog(self):
        if self._catalog_result is None:
            return
        entries, error = self._catalog_result; self._catalog_result = None
        self._installed.clear()
        for entry in entries:
            self._installed.addItem(entry["label"], entry)
        self._find.setEnabled(True)
        self._status.setText(error or f"{len(entries)} installed apps found; no app was opened.")

    def _add_installed(self):
        entry = self._installed.currentData()
        if entry:
            from allowed_applications import normalize
            # Replace a matching broad preset with the installed app's exact path.
            self._entries = normalize([*[existing for existing in self._entries if existing["label"].lower() != entry["label"].lower()], entry])
            self._render()

    def _apply(self):
        from allowed_applications import normalize
        self.owner._allowed_apps = normalize(self._entries)
        self.owner._update_allowed_summary()

    def _open(self):
        row = self._list.currentRow()
        if row < 0:
            return
        try:
            from allowed_applications import launch
            self._apply()
            launch(self._entries[row])
            self._status.setText("Open requested through Windows using the saved protection mode. Save Config to apply list changes. Approval remains personal.")
        except (OSError, ValueError):
            self._status.setText("App launch was not confirmed. Select its installed entry or executable; Windows may require recovery.")

    def _save(self):
        self._apply(); self.accept()


class ProtectionConfigDialog(QDialog):
    """Protection options and current component states in one place."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("Pop-up Protection — Config")
        self.setMinimumWidth(680)
        layout = QVBoxLayout(self)
        status_group = QGroupBox("Component status")
        status_layout = QVBoxLayout(status_group)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label)
        layout.addWidget(status_group)
        from race_protection import DEFAULTS, monitors
        protection_settings = {**DEFAULTS, **(core.cfg.get("race_protection") or {})}
        from allowed_applications import normalize
        self._allowed_apps = normalize(protection_settings["allowed_apps"])
        grp_protection = QGroupBox("Pop-up Protection")
        fp = QFormLayout(grp_protection)
        self._protection_inputs = {}
        for key, label in (("enabled", "Start with OverlayApp"), ("mute_toasts", "Mute app toasts"),
                           ("focus_timeout", "Reduce automatic focus changes"),
                           ("firewall_notifications", "Mute firewall prompts"),
                           ("redirect_always", "Route alerts while the app is open")):
            checkbox = QCheckBox()
            checkbox.setChecked(bool(protection_settings[key]))
            self._protection_inputs[key] = checkbox
            fp.addRow(label, checkbox)
        grace = QSpinBox()
        grace.setRange(2000, 15000)
        grace.setSuffix(" ms")
        grace.setValue(int(protection_settings["input_grace_ms"]))
        self._protection_inputs["input_grace_ms"] = grace
        fp.addRow("Grace period after Alt-Tab/click", grace)
        self._alert_monitor = QComboBox()
        self._alert_monitor.addItem("Hide temporarily", "")
        for display in monitors():
            self._alert_monitor.addItem(display["label"], display.get("id", display["device"]))
        destination = protection_settings.get("alert_monitor", "auto")
        if destination == "auto":
            destination = next((d.get("id", d["device"]) for d in monitors() if d["upper"]), "")
        index = self._alert_monitor.findData(destination)
        if destination and index < 0:
            self._alert_monitor.addItem("Selected display disconnected", destination)
            index = self._alert_monitor.count() - 1
        self._alert_monitor.setCurrentIndex(max(0, index))
        fp.addRow("Alert display", self._alert_monitor)
        protection_note = QLabel("Mute notifications and firewall prompts only while a supported game is open.\n"
                                 "Route new common alerts according to the option above.\n"
                                 "Switch shortcuts are preserved; an alert may appear briefly.\n"
                                 "Required helpers are installed/updated here after personal Windows approval.\n"
                                 "It lasts until the app closes; denied apps can still display errors.\n"
                                 "Toasts and firewall prompts may require one-time administrator setup.\n"
                                 "Component status is shown above.")
        protection_note.setWordWrap(True)
        protection_note.setMinimumHeight(protection_note.fontMetrics().lineSpacing() * 9)
        fp.addRow(protection_note)
        layout.addWidget(grp_protection)
        mode_group = QGroupBox("Application mode")
        mode_layout = QVBoxLayout(mode_group)
        modes = QHBoxLayout()
        self._mode_buttons = QButtonGroup(self)
        self._allow_mode = QRadioButton("Allow")
        gate = QRadioButton("Block all")
        self._protection_inputs["block_elevation"] = gate
        self._mode_buttons.addButton(self._allow_mode)
        self._mode_buttons.addButton(gate)
        for radio, description in ((self._allow_mode, "Allowed applications"),
                                   (gate, "Block new interactive elevations globally (experimental)")):
            column = QVBoxLayout()
            column.addWidget(radio)
            label = QLabel(description)
            label.setWordWrap(True)
            column.addWidget(label)
            modes.addLayout(column, 1)
        mode_layout.addLayout(modes)
        self._allow_mode.setChecked(not bool(protection_settings["block_elevation"]))
        gate.setChecked(bool(protection_settings["block_elevation"]))
        gate.setToolTip("Suspend every saved application exception. Existing elevated processes and security/consent surfaces remain outside this experimental gate.")
        self._mode_summary = QLabel()
        self._mode_summary.setWordWrap(True)
        mode_layout.addWidget(self._mode_summary)
        self._allowed_button = QPushButton()
        self._allowed_button.clicked.connect(lambda: AllowedApplicationsDialog(self).exec())
        mode_layout.addWidget(self._allowed_button)
        scope = QLabel("Block all applies to new interactive elevations, not all running applications.\n"
                       "Save Config requests any required personal Windows approval/setup in the app.\n"
                       "UAC status above confirms actual blocking separately from the selected mode.\n"
                       "The global gate is experimental and has not passed live acceptance. Save Config to apply.")
        scope.setWordWrap(True)
        mode_layout.addWidget(scope)
        gate.toggled.connect(self._update_allowed_summary)
        self._update_allowed_summary()
        layout.addWidget(mode_group)
        administrative_buttons = QHBoxLayout()
        self._retry_setup = QPushButton("Retry administrative setup")
        self._remove_helpers = QPushButton("Remove administrative helpers")
        self._retry_setup.clicked.connect(self._retry_administrative)
        self._remove_helpers.clicked.connect(self._remove_administrative)
        administrative_buttons.addWidget(self._retry_setup)
        administrative_buttons.addWidget(self._remove_helpers)
        layout.addLayout(administrative_buttons)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(500)
        self._refresh_status()

    def _update_allowed_summary(self):
        self._allowed_button.setText(f"Manage allowed applications… ({len(self._allowed_apps)} saved)")
        gate = self._protection_inputs["block_elevation"]
        self._mode_summary.setText(
            f"Selected: Block all — {len(self._allowed_apps)} saved exceptions suspended after Save."
            if gate.isChecked() else f"Selected: Allow — {len(self._allowed_apps)} saved exceptions restored after Save.")

    def _refresh_status(self):
        self.owner._refresh_protection()
        self._status_label.setText(self.owner._protection_label.text())
        self._status_label.setToolTip(self.owner._protection_label.toolTip())
        protection = self.owner._protection
        administrative = getattr(protection, "administrative", None)
        pending = bool(getattr(administrative, "pending", False)) if administrative is not None else False
        self._retry_setup.setEnabled(protection is not None and not pending)
        self._remove_helpers.setEnabled(protection is not None and not pending)

    def _retry_administrative(self):
        if self.owner._protection is not None:
            self.owner._protection.retry_administrative_setup()
            self._refresh_status()

    def _remove_administrative(self):
        if self.owner._protection is not None:
            settings = core.cfg.setdefault("race_protection", {})
            for key in ("mute_toasts", "firewall_notifications", "block_elevation"):
                settings[key] = False
                if key == "block_elevation":
                    self._allow_mode.setChecked(True)
                else:
                    self._protection_inputs[key].setChecked(False)
            core.save_cfg()
            self.owner._protection.configure(settings)
            self.owner._protection.remove_administrative_helpers()
            self._refresh_status()

    def _save_and_close(self):
        from race_protection import DEFAULTS
        settings = {**DEFAULTS, **(core.cfg.get("race_protection") or {})}
        settings.update({key: (widget.isChecked() if isinstance(widget, (QCheckBox, QRadioButton)) else widget.value())
                         for key, widget in self._protection_inputs.items()})
        settings["alert_monitor"] = self._alert_monitor.currentData()
        settings["allowed_apps"] = self._allowed_apps
        core.cfg["race_protection"] = settings
        core.save_cfg()
        if self.owner._protection is not None:
            if settings["enabled"] and settings["block_elevation"]:
                self.owner._protection.configure(settings, request_setup=True)
            else:
                self.owner._protection.configure(settings)
        self.owner._refresh_protection()
        self.accept()


class WidgetConfigDialog(QDialog):
    """Config dialog for one overlay window.

    Windows with columns (Standings, Relative) get two tabs: Settings | Columns.
    Other windows show settings directly.
    """

    def __init__(self, parent, meta: dict, widget_obj, timer_obj=None):
        super().__init__(parent)
        self._meta   = meta
        self._widget = widget_obj
        self._timer  = timer_obj
        self._inputs = {}   # key -> QWidget
        self._col_ed = None
        self._win_fields_touched = set()
        self._rpm_car_key = None
        self._rpm_max_input = None

        self.setWindowTitle(f"Config — {meta['label']}")
        self.setMinimumWidth(400)
        self.setModal(False)   # non-modal so the user can drag the widget
                                # while the Config dialog stays open

        # When this dialog is for a widget that supports positioning-outline
        # (currently ALERT — transparent and otherwise invisible), force the
        # outline ON for the duration of the dialog so the user can see what
        # they're configuring on screen. Reset on close.
        if widget_obj is not None and hasattr(widget_obj, "_force_outline"):
            try:
                widget_obj._force_outline = True
                widget_obj.update()
            except Exception:
                pass

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if meta.get("has_columns"):
            # Two-tab layout: Settings  |  Columns
            tabs = QTabWidget()

            tab_s = QWidget()
            tsl   = QVBoxLayout(tab_s)
            tsl.setSpacing(8)
            self._build_window_group(tsl, meta)
            self._build_settings_group(tsl, meta)
            tsl.addStretch()
            tabs.addTab(tab_s, "Settings")

            tab_c = QWidget()
            tcl   = QVBoxLayout(tab_c)
            tcl.setSpacing(4)
            self._col_ed = ColumnsEditor(meta["key"])
            tcl.addWidget(self._col_ed)
            tabs.addTab(tab_c, "Columns")

            layout.addWidget(tabs)
        else:
            self._build_window_group(layout, meta)
            self._build_settings_group(layout, meta)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self._reject_and_close)
        layout.addWidget(btns)

    def _reject_and_close(self):
        """Cancel button — also clear any temporary outline forcing."""
        self._clear_force_outline()
        self.reject()

    def closeEvent(self, e):
        # Make sure the temporary outline is removed even if the user closes
        # the dialog via the window's X button.
        self._clear_force_outline()
        super().closeEvent(e)

    def _clear_force_outline(self):
        if self._widget is not None and hasattr(self._widget, "_force_outline"):
            try:
                self._widget._force_outline = False
                self._widget.update()
            except Exception:
                pass

    # ── group builders ────────────────────────────────────────────────────────

    def _build_window_group(self, layout, meta):
        grp  = QGroupBox("Window Position && Size")
        form = QFormLayout(grp)
        form.setSpacing(6)
        wcfg = _get_window(meta["key"])
        for fkey, flabel, ftype, fmin, fmax, fdef in WINDOW_FIELDS:
            if meta["key"] == "rpm":
                if fkey == "font_size":
                    continue
                fdef = RPM_WINDOW_DEFAULTS.get(fkey, fdef)
                if fkey in ("width", "height"):
                    fmin = 1
            val = wcfg.get(fkey, fdef)
            w   = self._make_input(ftype, fmin, fmax, val)
            self._inputs[f"_win_{fkey}"] = w
            self._track_window_input(fkey, w)
            form.addRow(flabel, w)
        layout.addWidget(grp)

        if meta["key"] == "rpm":
            self._build_rpm_max_group(layout, _get_settings(meta["settings_key"]))

    def _build_rpm_max_group(self, layout, settings):
        grp = QGroupBox("Maximum RPM for this car")
        form = QFormLayout(grp)
        connected = bool(getattr(getattr(core, "ir", None), "is_connected", False))
        info = core.sg("DriverInfo", {}) if connected else {}
        self._rpm_car_key = car_key(info)
        overrides = settings.get("max_rpm_by_car") or {}
        saved = finite_number(overrides.get(self._rpm_car_key)) if isinstance(overrides, dict) else None
        self._rpm_max_input = self._make_input("int", 0, 50000, int(saved or 0))
        self._rpm_max_input.setEnabled(self._rpm_car_key is not None)
        self._rpm_max_input.setSpecialValueText("Auto (car redline)")
        form.addRow("Override (0=auto)", self._rpm_max_input)
        maximum, _ = resolve_max_rpm(info, {})
        message = f"Car: {self._rpm_car_key or 'unavailable'}\n"
        message += (f"Automatic redline: {maximum:g} RPM." if maximum else
                    "Redline unavailable: set this car's maximum to enable the fill.")
        if self._rpm_car_key is None:
            message += "\nConnect to iRacing with a car, then reopen Config to set an override."
        note = QLabel(message)
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(grp)

    def _build_settings_group(self, layout, meta):
        if not meta.get("fields"):
            return
        grp  = QGroupBox("Settings")
        form = QFormLayout(grp)
        form.setSpacing(6)
        scfg = _get_settings(meta["settings_key"])
        for fkey, flabel, ftype, fmin, fmax, fdef in meta["fields"]:
            val = scfg.get(fkey, fdef)
            w   = self._make_input(ftype, fmin, fmax, val)
            self._inputs[f"_cfg_{fkey}"] = w
            form.addRow(flabel, w)
        layout.addWidget(grp)

    def _make_input(self, ftype, fmin, fmax, val):
        if ftype == "bool":
            cb = QCheckBox()
            cb.setChecked(bool(val))
            return cb
        elif ftype == "float":
            sb = QDoubleSpinBox()
            sb.setDecimals(2)
            try: sb.setRange(float(fmin), float(fmax))
            except Exception: sb.setRange(0.0, 1e9)
            try:    sb.setValue(float(val))
            except: pass
            return sb
        elif ftype == "str":
            # Free-form text field (e.g. Pulsoid widget URL). Without this
            # branch the dialog used to fall through to QSpinBox and crash
            # the app on int("") of an empty min/max bound.
            le = QLineEdit("" if val is None else str(val))
            le.setMinimumWidth(220)
            return le
        else:
            sb = QSpinBox()
            try: sb.setRange(int(fmin), int(fmax))
            except Exception: sb.setRange(-1_000_000, 1_000_000)
            try:    sb.setValue(int(float(val)))
            except: pass
            return sb

    def _track_window_input(self, fkey, widget):
        """Mark geometry fields the user explicitly changed in the dialog."""
        if isinstance(widget, QCheckBox):
            widget.toggled.connect(lambda _checked, k=fkey: self._win_fields_touched.add(k))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(lambda _val, k=fkey: self._win_fields_touched.add(k))
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(lambda _txt, k=fkey: self._win_fields_touched.add(k))

    # ── save ──────────────────────────────────────────────────────────────────

    def _save_and_close(self):
        key  = self._meta["key"]
        skey = self._meta["settings_key"]

        # Window geometry
        wins = core.cfg.setdefault("windows", {})
        wcfg = wins.setdefault(key, {})
        for fkey, *_ in WINDOW_FIELDS:
            w = self._inputs.get(f"_win_{fkey}")
            if w is not None:
                wcfg[fkey] = w.isChecked() if isinstance(w, QCheckBox) else w.value()
        # If the user dragged the live overlay while this config dialog was open,
        # preserve the live position unless X/Y was edited directly in the form.
        if self._widget is not None:
            try:
                live_pos = self._widget.pos()
                if "x" not in self._win_fields_touched:
                    wcfg["x"] = int(live_pos.x())
                if "y" not in self._win_fields_touched:
                    wcfg["y"] = int(live_pos.y())
            except Exception:
                pass

        # Widget settings
        scfg = core.cfg.setdefault(skey, {})
        for fkey, flabel, ftype, fmin, fmax, fdef in self._meta.get("fields", []):
            w = self._inputs.get(f"_cfg_{fkey}")
            if w is None:
                continue
            if isinstance(w, QCheckBox):
                scfg[fkey] = w.isChecked()
            elif isinstance(w, QLineEdit):
                scfg[fkey] = w.text().strip()
            else:
                scfg[fkey] = w.value()

        if key == "rpm" and self._rpm_car_key is not None:
            overrides = scfg.setdefault("max_rpm_by_car", {})
            maximum = self._rpm_max_input.value()
            if maximum > 0:
                overrides[self._rpm_car_key] = maximum
            else:
                overrides.pop(self._rpm_car_key, None)

        # Columns (if this window has them)
        if self._col_ed is not None:
            new_cols = self._col_ed.get_columns()
            scfg["columns"] = new_cols
            # Push immediately to the overlay widget so draw() sees the new list
            if self._widget is not None:
                try:
                    self._widget.columns = new_cols
                except Exception:
                    pass

        core.save_cfg()

        # Apply geometry immediately
        if self._widget:
            try:
                self._widget.setGeometry(
                    wcfg.get("x", 100), wcfg.get("y", 100),
                    wcfg.get("width", 300), wcfg.get("height", 200))
                self._widget._max_h = wcfg.get("height", 200)
                self._widget._max_w = wcfg.get("width", 300)
            except Exception:
                pass
            # Live-refresh per-widget font in case the user changed
            # font_size. Without this the widget would only pick up the
            # new size on next overlay restart.
            try:
                if hasattr(self._widget, "apply_font"):
                    self._widget.apply_font()
                    self._widget.update()
            except Exception:
                pass

        # Apply settings live
        if key == "relative" and self._widget:
            try:
                self._widget.ahead  = scfg.get("rows_ahead",  3)
                self._widget.behind = scfg.get("rows_behind", 3)
                self._widget.avg_laps = scfg.get("avg_laps", 5)
            except Exception:
                pass
        elif key == "standings" and self._widget:
            try:
                self._widget.ahead    = scfg.get("rows_ahead",    5)
                self._widget.behind   = scfg.get("rows_behind",   5)
                self._widget.top      = scfg.get("top_per_class", 3)
                self._widget.avg_laps = scfg.get("avg_laps",      5)
                self._widget.multiclass_headers = bool(scfg.get("multiclass_headers", True))
                self._widget.show_top_last_laps = bool(scfg.get("show_top_last_laps", True))
            except Exception:
                pass
        elif key == "longest_sector" and self._widget:
            self._widget.apply_settings(scfg)
        elif key == "rpm" and self._widget:
            self._widget.apply_settings(scfg)
        elif key == "fuel" and self._widget:
            try:
                self._widget.avg_window   = scfg.get("avg_window_laps", 5)
                self._widget.max_lap_fuel = scfg.get("max_lap_fuel", 50.0)
                self._widget.reserve      = scfg.get("reserve_liters", 0.5)
                self._widget.extra_pct    = scfg.get("extra_consumption_pct", 3.0)
                self._widget.percentile   = scfg.get("consumption_percentile", 75)
            except Exception:
                pass
        elif key == "tyres" and self._widget:
            try:
                self._widget.ranges = {
                    "cold":     scfg.get("cold_temp",  60.0),
                    "warm":     scfg.get("warm_temp",  75.0),
                    "ideal_hi": scfg.get("ideal_high", 95.0),
                    "hot":      scfg.get("hot_temp",  105.0),
                }
            except Exception:
                pass
        elif key == "alert" and self._widget:
            try:
                if hasattr(self._widget, "apply_settings"):
                    self._widget.apply_settings(scfg)
                else:
                    self._widget.rate_threshold = float(scfg.get("rate_threshold", 0.8))
                    self._widget.gap_max        = float(scfg.get("gap_max_sec",    5.0))
                    self._widget.history_s      = float(scfg.get("history_seconds",2.0))
                    self._widget.flash_hz       = float(scfg.get("flash_hz",       4.0))
                    self._widget.show_border    = bool(scfg.get("show_border", False))
            except Exception:
                pass
        elif key == "hr":
            try:
                if self._widget is not None and hasattr(self._widget, "apply_settings"):
                    self._widget.apply_settings(scfg)
            except Exception:
                pass
            # When the URL changes, force the Pulsoid worker to discard its
            # cached ramielUrl so the next iteration re-fetches against the
            # new widget UUID. The worker tolerates a None state — its loop
            # will refresh the access_token + WS URL on the next tick.
            try:
                import heart as _heart
                _heart._LAST_RAMIEL_URL = None
                _heart._LAST_RAMIEL_FETCH_T = 0.0
            except Exception:
                pass
        elif key in ("garage", "wind") and self._widget is not None:
            # Both new widgets expose apply_settings(dict) — give them the
            # fresh sub-cfg so colours / labels update without a restart.
            try:
                if hasattr(self._widget, "apply_settings"):
                    self._widget.apply_settings(scfg)
            except Exception:
                pass

        # Update timer interval
        if self._timer:
            if key == "rpm":
                self._timer.setInterval(max(5, int(scfg.get("update_ms", RPM_UPDATE_MS))))
            elif key in ("relative", "standings", "longest_sector"):
                try: self._timer.setInterval(max(1, int(scfg.get("update_ms", 100))))
                except Exception: pass
            elif key in ("info", "tyres", "hr", "garage", "wind"):
                try: self._timer.setInterval(max(1, int(scfg.get("update_ms", 250))))
                except Exception: pass
            elif key == "alert":
                try: self._timer.setInterval(max(1, int(scfg.get("update_ms", 100))))
                except Exception: pass
            elif key == "fuel":  # 261001_CURSOR
                try: self._timer.setInterval(max(50, int(scfg.get("update_ms", 100))))  # 261001_CURSOR
                except Exception: pass  # 261001_CURSOR

        # Clear any temporary positioning outline before closing
        self._clear_force_outline()
        self.accept()


# ── Widget list row ───────────────────────────────────────────────────────────

class WidgetRowItem(QWidget):
    """One row: [Name label]  [Config button]  [ON/OFF toggle]"""

    def __init__(self, parent_panel, meta: dict, widget_obj, timer_obj=None):
        super().__init__(parent_panel)
        self._panel  = parent_panel
        self._meta   = meta
        self._widget = widget_obj
        self._timer  = timer_obj

        self.setFixedHeight(28)

        lbl = QLabel(meta["label"])
        lbl.setMinimumWidth(110)

        self._btn_cfg = QPushButton("Config")
        self._btn_cfg.setObjectName("btnConfig")
        self._btn_cfg.setFixedWidth(62)
        self._btn_cfg.clicked.connect(self._open_config)

        self._btn_toggle = QPushButton("")
        self._btn_toggle.setFixedWidth(48)
        self._btn_toggle.clicked.connect(self._toggle)
        self._refresh_toggle()

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(6)
        row.addWidget(lbl, 1)
        row.addWidget(self._btn_cfg)
        row.addWidget(self._btn_toggle)

    def _refresh_toggle(self):
        on = self.is_enabled()
        self._btn_toggle.setText("ON" if on else "OFF")
        self._btn_toggle.setObjectName("btnToggleOn" if on else "btnToggleOff")
        self._btn_toggle.style().unpolish(self._btn_toggle)
        self._btn_toggle.style().polish(self._btn_toggle)

    def is_enabled(self):
        return _is_enabled(self._meta["key"])

    def set_enabled(self, enabled):
        _set_enabled(self._meta["key"], enabled)
        self._refresh_toggle()

    def _toggle(self):
        self.set_enabled(not self.is_enabled())
        if self._panel:
            self._panel.refresh_label()

    def _open_config(self):
        # Use .show() not .exec() so the dialog is non-blocking — the user can
        # drag/resize the underlying overlay widget while the dialog stays
        # open. Keep a reference on self so Qt doesn't garbage-collect it.
        dlg = WidgetConfigDialog(self, self._meta, self._widget, self._timer)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._cfg_dialog = dlg   # keep alive
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()


class RaceChatRow(WidgetRowItem):
    def __init__(self, owner, meta):
        self.owner = owner
        super().__init__(None, meta, None)

    def set_enabled(self, enabled):
        super().set_enabled(enabled)
        self.owner._apply_race_chat_enabled(enabled)

    def _open_config(self):
        self.owner._open_race_chat()


class ProtectionRow(WidgetRowItem):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(None, {"key": "race_protection", "label": "Pop-up Protection"}, None)

    def is_enabled(self):
        if self.owner._protection is not None:
            return not self.owner._protection.pause_file.exists()
        from race_protection import DEFAULTS
        return bool((core.cfg.get("race_protection") or {}).get("enabled", DEFAULTS["enabled"]))

    def set_enabled(self, enabled):
        self.owner._set_protection_enabled(enabled)
        self._refresh_toggle()

    def _open_config(self):
        self._cfg_dialog = ProtectionConfigDialog(self.owner)
        self._cfg_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._cfg_dialog.show()


# ── Widget list panel ─────────────────────────────────────────────────────────

class WidgetListPanel(QWidget):
    """All toggle rows visible, with compact columns on shorter displays."""

    def __init__(self, parent, rows: list):
        super().__init__(parent)
        self._rows = rows

        self._label = QLabel("")
        self._label.setObjectName("labelEnabled")

        self._row_container = QWidget(self)
        self._row_grid = QGridLayout(self._row_container)
        self._row_grid.setContentsMargins(0, 0, 0, 0)
        self._row_grid.setHorizontalSpacing(8)
        self._row_grid.setVerticalSpacing(1)
        self._columns = 1
        self.arrange_rows(1)

        btn_enable  = QPushButton("Enable All")
        btn_disable = QPushButton("Disable All")
        btn_enable.clicked.connect(self._enable_all)
        btn_disable.clicked.connect(self._disable_all)

        btn_general = QPushButton("General Config")
        btn_general.setObjectName("btnGeneral")
        btn_general.clicked.connect(self._open_general)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addWidget(btn_enable)
        btn_row.addWidget(btn_disable)
        btn_row.addStretch()
        btn_row.addWidget(btn_general)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self._label)
        layout.addWidget(self._row_container)
        layout.addStretch()
        layout.addLayout(btn_row)
        btn_review = QPushButton("Review race drivers / marked IDs")
        btn_review.clicked.connect(parent.open_race_review_manager)
        layout.addWidget(btn_review)

        self.refresh_label()

    def arrange_rows(self, columns):
        self._columns = max(1, columns)
        while self._row_grid.count():
            self._row_grid.takeAt(0)
        import math
        per_column = math.ceil(len(self._rows) / self._columns)
        for index, row in enumerate(self._rows):
            self._row_grid.addWidget(row, index % per_column, index // per_column)

    def refresh_label(self):
        total   = len(self._rows)
        enabled = sum(1 for r in self._rows if r.is_enabled())
        self._label.setText(f"Enabled: <b>{enabled}/{total}</b>")

    def _enable_all(self):
        for r in self._rows:
            r.set_enabled(True)
        self.refresh_label()

    def _disable_all(self):
        for r in self._rows:
            r.set_enabled(False)
        self.refresh_label()

    def _open_general(self):
        GeneralConfigDialog(self).exec()


# ── Status bar ────────────────────────────────────────────────────────────────

class ManagerStatusBar(QStatusBar):
    def __init__(self, parent):
        super().__init__(parent)
        self._lbl = QLabel("Disconnected")
        self._lbl.setObjectName("labelDisconn")
        self.addWidget(self._lbl)

    def refresh(self):
        connected = getattr(core.ir, "is_connected", False)
        if connected:
            self._lbl.setText("Connected: iRacing")
            self._lbl.setObjectName("labelConn")
        else:
            self._lbl.setText("Disconnected")
            self._lbl.setObjectName("labelDisconn")
        self._lbl.style().unpolish(self._lbl)
        self._lbl.style().polish(self._lbl)


# ── Main window ───────────────────────────────────────────────────────────────

class ManagerWindow(QMainWindow):
    def __init__(self, widget_instances: dict, timers: dict, race_monitor=None, protection=None):
        super().__init__()
        self._overlay_widgets = widget_instances
        self._timers = timers
        self._race_monitor = race_monitor
        self._review_dialog = None
        self._closing = False
        self._protection = protection

        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setMinimumSize(340, 320)
        self.resize(380, 400)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)

        self._status = ManagerStatusBar(self)
        self.setStatusBar(self._status)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._status.refresh)
        self._status_timer.start(500)

        self._race_chat = None
        rows = []
        for meta in WIDGET_DEFS:
            key = meta["key"]
            if key == "racechat":
                rows.append(RaceChatRow(self, meta))
                continue
            rows.append(WidgetRowItem(
                None, meta,
                widget_instances.get(key),
                timers.get(key),
            ))

        self._protection_row = ProtectionRow(self)
        rows.append(self._protection_row)
        panel = WidgetListPanel(self, rows)
        for r in rows:
            r._panel = panel

        self.setCentralWidget(panel)

        self._protection_label = QLabel(self)
        self._protection_label.hide()
        self._status_timer.timeout.connect(self._refresh_protection)
        self._refresh_protection()
        self._fit_rows_to_screen()

        self._race_review_timer = QTimer(self)
        if self._race_monitor is not None:
            self._race_review_timer.timeout.connect(self._poll_race_review)
            self._race_review_timer.start(500)

        if _is_enabled("racechat"):
            QTimer.singleShot(0, lambda: self._apply_race_chat_enabled(True))

    def _fit_rows_to_screen(self, available=None):
        import math
        available = available or self.screen().availableGeometry()
        panel = self.centralWidget()
        row_space = max(150, available.height() - 180)
        columns = max(1, math.ceil(len(panel._rows) * 29 / row_space))
        columns = min(columns, max(1, available.width() // 360))
        panel.arrange_rows(columns)
        panel.layout().activate()
        height = panel.sizeHint().height() + self._status.sizeHint().height() + 4
        width = max(380, panel.minimumSizeHint().width())
        self.resize(min(width, available.width() - 24), min(height, available.height() - 60))

    def _set_protection_enabled(self, enabled):
        settings = core.cfg.setdefault("race_protection", {})
        settings["enabled"] = enabled
        core.save_cfg()
        if self._protection is not None:
            self._protection.configure(settings)

    def _refresh_protection(self):
        status = self._protection.status() if self._protection is not None else {"Mode": "helper unavailable"}
        mode = status.get("Mode", "not confirmed")
        self._protection_label.setText(f"Protection: {mode} · Firewall: {status.get('Firewall', 'not confirmed')}")
        if status.get("Windows"):
            self._protection_label.setText(
                f"Protection: {mode}\nWindows: {status['Windows']} · Routing: {status.get('Routing', 'not confirmed')}\n"
                f"Toasts: {status.get('Toasts', 'not confirmed')}\nFocus: {status.get('Focus', 'not confirmed')}\n"
                f"Firewall: {status.get('Firewall', 'not confirmed')}")
        if status.get("Pending"):
            self._protection_label.setText(self._protection_label.text() + " · restoration pending")
        from race_protection import UAC_STATUS
        self._protection_label.setText(self._protection_label.text() + f"\nUAC: {status.get('UAC', UAC_STATUS)}")
        if status.get("ApplicationMode"):
            self._protection_label.setText(self._protection_label.text() + f"\nApplication mode: {status['ApplicationMode']}")
        if status.get("Setup"):
            self._protection_label.setText(self._protection_label.text() + f"\nAdministrative setup: {status['Setup']}")
        if self._protection is not None:
            self._protection_label.setToolTip(self._protection.diagnostic_text())
        self._protection_row.setToolTip(self._protection_label.toolTip())
        self._protection_row._refresh_toggle()
        self.centralWidget().refresh_label()

    def _ensure_race_chat(self):
        if self._race_chat is None:
            try:
                from racechat import ChatWindow
                self._race_chat = ChatWindow(self)
                self._race_chat.manager_enabled = _is_enabled("racechat")
            except Exception:
                import traceback
                from pathlib import Path
                report = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OverlayApp" / "Logs" / "racechat-startup-error.txt"
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(traceback.format_exc(), encoding="utf-8")
                self.statusBar().showMessage("RaceChat could not open; startup diagnostics were saved.")
                raise
        return self._race_chat

    def _apply_race_chat_enabled(self, enabled):
        if not enabled and self._race_chat is None:
            return
        chat = self._ensure_race_chat()
        chat.manager_enabled = enabled
        if enabled:
            chat.connect_live()
        else:
            chat.start_demo()
            chat.panel.hide()

    def _open_race_chat(self):
        chat = self._ensure_race_chat()
        chat.show()
        chat.raise_()
        chat.activateWindow()

    def _poll_race_review(self):
        try:
            connected = bool(core.connect())
            if connected:
                try:
                    core.ir.freeze_var_buffer_latest()
                except Exception:
                    pass
                signature = core._session_signature()
                state = core.sg("SessionState", None)
                info = core.sg("DriverInfo", {}) or {}
                drivers = info.get("Drivers", []) if isinstance(info, dict) else []
            else:
                signature, state, drivers = None, None, []
            self._race_monitor.poll(connected, signature, state, drivers)
            if self._race_monitor.last_error:
                self.statusBar().showMessage("The race review state needs to be repaired.")
                return
        except Exception as exc:
            core._log(f"Race review poll error: {exc!r}")

    def _show_review(self, event):
        if self._review_dialog is not None:
            self._review_dialog.raise_()
            self._review_dialog.activateWindow()
            return
        try:
            dialog = DriverReviewDialog(core.blacklist_store, event,
                                        self._on_review_saved, self)
        except (OSError, ValueError) as exc:
            core._log(f"Race review dialog error: {exc!r}")
            self.statusBar().showMessage("Repair blacklist.json before opening the driver list.")
            return
        self._review_dialog = dialog
        dialog.finished.connect(self._review_closed)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _review_closed(self, _result):
        self._review_dialog = None

    def _on_review_saved(self, event):
        if event is not None and self._race_monitor is not None:
            self._race_monitor.mark_reviewed(event["key"])
        relative_widget = self._overlay_widgets.get("relative")
        if relative_widget is not None:
            relative_widget.update_data()

    def open_race_review_manager(self):
        event = self._race_monitor.review_event() if self._race_monitor else None
        self._show_review(event)

    def closeEvent(self, event):
        self._closing = True
        if self._protection is not None:
            self._protection.close()
        self._race_review_timer.stop()
        if self._review_dialog is not None:
            self._review_dialog.close()
        if self._race_chat is not None:
            self._race_chat.shutdown()
        for w in self._overlay_widgets.values():
            try: w.close()
            except Exception: pass
        for t in list(self._timers.values()) + [self._status_timer]:
            try: t.stop()
            except Exception: pass
        event.accept()
        QApplication.quit()


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def run():
    Path(core.BASE_DIR).mkdir(parents=True, exist_ok=True)
    core._prepare_debug_archive()
    core._reset_jsonl_file()
    core._SESSION_SIG[0] = None
    core._LAST_SNAP_T[0] = 0.0

    app = QApplication.instance() or QApplication(sys.argv)
    apply_dark_theme(app)
    from race_protection import RaceProtection
    protection = RaceProtection(core.cfg.get("race_protection"))
    protection.recover()
    protection.configure(protection.settings)
    app.aboutToQuit.connect(protection.close)

    # Boot the Pulsoid heart-rate poller. Background daemon thread that keeps
    # a websocket / http loop open against the configured widget URL; INFO
    # widget reads the latest BPM via heart.latest_bpm() each paint tick.
    try:
        import heart as _heart
        _heart.start()
    except Exception as _e:
        try:
            core._log(f"heart-rate worker failed to start: {_e!r}")
        except Exception:
            pass

    from relative  import Relative
    from standings import Standings
    from longest_sector import LongestSector
    from fuel      import Fuel
    from info      import Info
    from weather   import Weather
    from input     import Input
    from rpm       import RPM
    from tyres     import Tyres
    from alert     import Alert
    from hr        import HR
    from garage    import GarageCover
    from wind      import Wind

    rel  = Relative()
    std  = Standings()
    sector = LongestSector()
    fuel = Fuel()
    info = Info()
    weather = Weather()
    inp  = Input()
    rpm  = RPM()
    tyr  = Tyres()
    alr  = Alert()
    hr   = HR()
    gar  = GarageCover()
    wnd  = Wind()

    for w in (rel, std, sector, fuel, info, weather, inp, rpm, tyr, alr, hr, gar, wnd):
        if core.cfg.get("_fresh_factory_layout"):
            available = app.primaryScreen().availableGeometry()
            width, height = min(w.width(), available.width()), min(w.height(), available.height())
            w.resize(width, height)
            if hasattr(w, "_max_w"):
                w._max_w, w._max_h = width, height
            w.move(max(available.left(), min(w.x(), available.right() - width + 1)),
                   max(available.top(), min(w.y(), available.bottom() - height + 1)))
            core.cfg.setdefault("windows", {}).setdefault(w._key, {}).update(
                x=w.x(), y=w.y(), width=width, height=height)
        w.show()
    if core.cfg.pop("_fresh_factory_layout", False):
        core.save_cfg()

    rel_ms   = max(1, int((core.cfg.get("relative_settings")  or {}).get("update_ms", 100)))
    std_ms   = max(1, int((core.cfg.get("standings_settings") or {}).get("update_ms", 100)))
    info_ms  = max(1, int((core.cfg.get("info_settings")      or {}).get("update_ms", 250)))
    weath_ms = max(1, int((core.cfg.get("weather_settings")   or {}).get("update_ms", 500)))
    tyre_ms  = max(1, int((core.cfg.get("tyre_settings")      or {}).get("update_ms", 250)))
    alert_ms = max(1, int((core.cfg.get("alert_settings")     or {}).get("update_ms", 100)))
    hr_ms    = max(1, int((core.cfg.get("heart_settings")     or {}).get("update_ms", 250)))
    gar_ms   = max(1, int((core.cfg.get("garage_settings")    or {}).get("update_ms", 250)))
    wnd_ms   = max(1, int((core.cfg.get("wind_settings")      or {}).get("update_ms", 250)))
    fps      = max(1, int((core.cfg.get("input_settings")     or {}).get("fps", 120)))
    in_ms    = max(1, int(round(1000.0 / fps)))

    t_rel  = QTimer(); t_rel.timeout.connect(rel.update_data);  t_rel.start(rel_ms)
    t_std  = QTimer(); t_std.timeout.connect(std.update_data);  t_std.start(std_ms)
    t_sector = QTimer(); t_sector.timeout.connect(sector.update_data)
    t_sector.start(max(1, int((core.cfg.get("longest_sector_settings") or {}).get("update_ms", 100))))
    # t_fuel = QTimer(); t_fuel.timeout.connect(
    #     lambda: (fuel.update_data(), info.update_data()))
    # t_fuel.start(core.UPDATE_MS)
    fuel_ms = max(50, int((core.cfg.get("fuel_settings") or {}).get("update_ms", 100)))  # 261001_CURSOR
    t_fuel = QTimer(); t_fuel.timeout.connect(fuel.update_data); t_fuel.start(fuel_ms)  # 261001_CURSOR
    t_fuel_sample = QTimer(fuel)  # 261001_CURSOR
    t_fuel_sample.timeout.connect(fuel.sample_fast)  # 261001_CURSOR
    t_fuel_sample.start(max(5, int(core.UPDATE_MS)))  # 261001_CURSOR
    t_info = QTimer(); t_info.timeout.connect(info.update_data); t_info.start(info_ms)
    t_weath= QTimer(); t_weath.timeout.connect(weather.update_data); t_weath.start(weath_ms)
    t_inp  = QTimer(); t_inp.timeout.connect(inp.update_data);   t_inp.start(in_ms)
    t_rpm = QTimer(); t_rpm.timeout.connect(rpm.update_data)
    t_rpm.start(max(5, int((core.cfg.get("rpm_settings") or {}).get("update_ms", RPM_UPDATE_MS))))
    t_tyr  = QTimer(); t_tyr.timeout.connect(tyr.update_data);   t_tyr.start(tyre_ms)
    t_alr  = QTimer(); t_alr.timeout.connect(alr.update_data);   t_alr.start(alert_ms)
    t_hr   = QTimer(); t_hr.timeout.connect(hr.update_data);     t_hr.start(hr_ms)
    t_gar  = QTimer(); t_gar.timeout.connect(gar.update_data);   t_gar.start(gar_ms)
    t_wnd  = QTimer(); t_wnd.timeout.connect(wnd.update_data);   t_wnd.start(wnd_ms)

    timers = {
        "relative":  t_rel,
        "standings": t_std,
        "longest_sector": t_sector,
        "fuel":      t_fuel,  # 261001_CURSOR
        "info":      t_info,
        "weather":   t_weath,
        "input":     t_inp,
        "rpm":       t_rpm,
        "tyres":     t_tyr,
        "alert":     t_alr,
        "hr":        t_hr,
        "garage":    t_gar,
        "wind":      t_wnd,
    }
    widget_instances = {
        "relative":  rel,
        "standings": std,
        "longest_sector": sector,
        "fuel":      fuel,
        "info":      info,
        "weather":   weather,
        "input":     inp,
        "rpm":       rpm,
        "tyres":     tyr,
        "alert":     alr,
        "hr":        hr,
        "garage":    gar,
        "wind":      wnd,
    }

    race_monitor = RaceMonitor(os.path.join(core.BASE_DIR, "race_review_state.json"))
    mgr = ManagerWindow(widget_instances, timers, race_monitor, protection)
    mgr.show()

    sys.exit(app.exec())
