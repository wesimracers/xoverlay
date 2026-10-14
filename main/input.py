# input
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QFont
from PyQt6.QtCore import Qt, QRect, QRectF
from collections import deque
import core
from base import BaseWin

_CLR_BG          = QColor(10,  10,  10)
_CLR_GRID        = QColor(90,  90,  90)
_CLR_BORDER      = QColor(60,  60,  60)
_CLR_THROTTLE    = QColor(40,  210, 40)
_CLR_THROTTLE_F  = QColor(15,  35,  15,  80)
_CLR_BRAKE       = QColor(220, 45,  45)
_CLR_BRAKE_F     = QColor(35,  12,  12,  80)
_CLR_ABS         = QColor(240, 210, 0)
_CLR_ABS_F       = QColor(35,  30,  10,  80)
_CLR_IDLE        = QColor(80,  80,  80)
_CLR_LABEL_T     = QColor(40,  200, 40)
_CLR_LABEL_B     = QColor(200, 50,  50)


class Input(BaseWin):
    def __init__(self):
        super().__init__("input")
        s = core.cfg.get("input_settings") or {}
        self.fps            = int(s.get("fps", 120))
        self.window_seconds = float(s.get("window_seconds", 12.0))
        self.smoothing      = int(s.get("smoothing", 3))
        self.pen_width      = int(s.get("pen_width", 2))
        self.maxlen = max(10, int(round(max(1, self.fps) * max(0.5, self.window_seconds))))

        self.th       = deque(maxlen=self.maxlen)
        self.br       = deque(maxlen=self.maxlen)
        self.abs_hist = deque(maxlen=self.maxlen)

        self._last_payload = {}
        self._abs_counter   = 0
        self._abs_threshold = 3

    def update_data(self):
        # if core.connect():
        if core.begin_frame():  # 261001_CURSOR
            try:
                # core.ir.freeze_var_buffer_latest()

                thv = float(core.sg("Throttle", 0.0) or 0.0)
                brv = float(core.sg("Brake",    0.0) or 0.0)

                # ABS detection
                abs_var = core.sg("BrakeABSactive", None)
                if abs_var is not None:
                    abs_active = bool(abs_var)
                else:
                    wheel_speed = core.sg("WheelSpeed", [])
                    car_speed   = core.sg("Speed", 0)
                    abs_now = False
                    if wheel_speed and len(wheel_speed) >= 4:
                        avg_w = sum(float(x) for x in wheel_speed[:4]) / 4.0
                        if car_speed > 15 and avg_w < car_speed * 0.85:
                            abs_now = True
                    self._abs_counter = min(self._abs_threshold, self._abs_counter + 1) if abs_now \
                        else max(0, self._abs_counter - 1)
                    abs_active = self._abs_counter >= self._abs_threshold

                self.th.append(thv)
                self.br.append(brv)
                self.abs_hist.append(abs_active)
                self._last_payload = {"throttle": thv, "brake": brv}
                core.update_state_and_debug_dump(extra={"input": self._last_payload})

            except Exception as ex:
                core._log(f"Input update error: {ex!r}")

        self.update()

    def _smooth(self, arr):
        k = max(1, int(self.smoothing))
        if k <= 1 or len(arr) < k:
            return list(arr)
        out, s, q = [], 0.0, deque()
        for v in arr:
            q.append(float(v))
            s += float(v)
            if len(q) > k:
                s -= q.popleft()
            out.append(s / len(q))
        return out

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()

        # ── Background ──────────────────────────────────────────
        p.fillRect(self.rect(), _CLR_BG)

        # ── Grid ────────────────────────────────────────────────
        pen_grid = QPen(_CLR_GRID, 1)
        pen_grid.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen_grid)
        for pct in (0.25, 0.5, 0.75):
            y = int(h * (1.0 - pct))
            p.drawLine(0, y, w, y)

        # ── No data ─────────────────────────────────────────────
        if len(self.th) < 2:
            p.setPen(_CLR_IDLE)
            p.setFont(QFont("Consolas", 9))
            p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "INPUT")
            p.setPen(QPen(_CLR_BORDER, 1))
            p.drawRect(0, 0, w - 1, h - 1)
            return

        th = self._smooth(self.th)
        br = self._smooth(self.br)
        n  = min(len(th), len(br))
        if n < 2:
            return

        step = (w - 1) / max(1, n - 1)

        # ── Throttle filled area ─────────────────────────────────
        path_th = QPainterPath()
        path_th.moveTo(0.0, float(h))
        for i, v in enumerate(th):
            path_th.lineTo(i * step, h - v * h)
        path_th.lineTo((n - 1) * step, float(h))
        path_th.closeSubpath()
        p.fillPath(path_th, _CLR_THROTTLE_F)

        # ── Brake filled area ────────────────────────────────────
        abs_list = list(self.abs_hist)
        path_br_n = QPainterPath()
        path_br_a = QPainterPath()
        path_br_n.moveTo(0.0, float(h))
        path_br_a.moveTo(0.0, float(h))
        for i, v in enumerate(br):
            x = i * step
            y = h - v * h
            abs_now = abs_list[i] if i < len(abs_list) else False
            if abs_now:
                path_br_a.lineTo(x, y)
            else:
                path_br_n.lineTo(x, y)
        path_br_n.lineTo((n - 1) * step, float(h))
        path_br_n.closeSubpath()
        path_br_a.lineTo((n - 1) * step, float(h))
        path_br_a.closeSubpath()
        p.fillPath(path_br_n, _CLR_BRAKE_F)
        p.fillPath(path_br_a, _CLR_ABS_F)

        # ── Brake outline ────────────────────────────────────────
        pw = max(1, self.pen_width)
        prev_abs = abs_list[0] if abs_list else False
        seg_start = 0
        for i in range(1, n + 1):
            cur_abs = abs_list[i] if i < len(abs_list) else prev_abs
            if cur_abs != prev_abs or i == n:
                col = _CLR_ABS if prev_abs else _CLR_BRAKE
                pen = QPen(col, pw)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                for j in range(seg_start + 1, i):
                    p.drawLine(
                        int((j - 1) * step), int(h - br[j - 1] * h),
                        int(j * step),        int(h - br[j] * h),
                    )
                seg_start = i - 1
                prev_abs = cur_abs

        # ── Throttle outline ─────────────────────────────────────
        pen_th = QPen(_CLR_THROTTLE, pw)
        pen_th.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen_th.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen_th)
        for i in range(1, n):
            p.drawLine(
                int((i - 1) * step), int(h - th[i - 1] * h),
                int(i * step),        int(h - th[i] * h),
            )

        # ── Current value indicators (right edge) ────────────────
        cur_th = th[-1] if th else 0.0
        cur_br = br[-1] if br else 0.0
        abs_now_cur = abs_list[-1] if abs_list else False

        ty = int(h - cur_th * h)
        by = int(h - cur_br * h)

        # Throttle tick
        p.setPen(QPen(_CLR_THROTTLE, 2))
        p.drawLine(w - 10, ty, w - 1, ty)

        # Brake tick
        br_cur_col = _CLR_ABS if abs_now_cur else _CLR_BRAKE
        p.setPen(QPen(br_cur_col, 2))
        p.drawLine(w - 10, by, w - 1, by)

        # ── Labels T / B at current position ─────────────────────
        lbl_font = QFont("Consolas", 8)
        p.setFont(lbl_font)

        # Throttle label
        p.setPen(_CLR_LABEL_T)
        t_rect = QRect(2, max(0, ty - 10), 12, 12)
        p.drawText(t_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "T")

        # Brake label (avoid overlap)
        b_y_label = max(0, by - 10)
        if abs(b_y_label - (ty - 10)) < 10:
            b_y_label = ty - 10 + 12
        p.setPen(_CLR_LABEL_B)
        b_rect = QRect(2, b_y_label, 12, 12)
        p.drawText(b_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "B")

        # ── Border ───────────────────────────────────────────────
        p.setPen(QPen(_CLR_BORDER, 1))
        p.drawRect(0, 0, w - 1, h - 1)


# if correct reply yes, else return solutions that are mandatory to work
