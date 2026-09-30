from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QPushButton


def _luminance(color: str) -> float:
    c = QColor(color)
    if not c.isValid():
        return 0.0
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


class ShimmerButton(QPushButton):
    """带流光忙碌态的按钮。

    QSS 表达不了动画,所以由 paintEvent 在原生绘制之上叠加一条循环扫过的亮带,
    用来表达「正在下载/同步」。set_flowing(False) 后完全回落到原生 QSS 绘制。
    """

    # 与 AppRunner 里 QSS 的 border-radius: 7px 保持一致,用于把流光裁进圆角
    BORDER_RADIUS = 7
    BAND_WIDTH = 120  # 扫光带宽度(px)
    STEP = 7  # 每帧推进(px)
    INTERVAL_MS = 20
    BAND_ALPHA = 0.34

    # 由 AppRunner 在切换深浅色主题时注入
    _theme = {"primary": "#2864DC", "button": "#FFFFFF"}

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._flowing = False
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

    @classmethod
    def apply_theme(cls, colors: dict):
        cls._theme = dict(colors)

    def set_flowing(self, flowing: bool):
        flowing = bool(flowing)
        if flowing == self._flowing:
            return
        self._flowing = flowing
        if flowing:
            self._offset = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def is_flowing(self) -> bool:
        return self._flowing

    def _on_tick(self):
        span = self.width() + self.BAND_WIDTH
        if span <= 0:
            return
        self._offset = (self._offset + self.STEP) % span
        self.update()

    def _band_color(self) -> QColor:
        """底色偏暗就用白色扫光,偏亮就用主题主色扫光,保证深浅主题都看得见。"""
        if self.objectName() == "primaryButton":
            base = self._theme.get("primary", "#2864DC")
        else:
            base = self._theme.get("button", "#FFFFFF")

        if _luminance(base) < 150:
            color = QColor("#FFFFFF")
            color.setAlphaF(self.BAND_ALPHA)
        else:
            color = QColor(self._theme.get("primary", "#2864DC"))
            color.setAlphaF(self.BAND_ALPHA * 0.9)
        return color

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._flowing:
            return

        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return

        span = width + self.BAND_WIDTH
        color = self._band_color()
        if not color.isValid():
            return
        transparent = QColor(color)
        transparent.setAlphaF(0.0)

        painter = QPainter(self)
        try:
            path = QPainterPath()
            path.addRoundedRect(
                0.5,
                0.5,
                width - 1.0,
                height - 1.0,
                self.BORDER_RADIUS,
                self.BORDER_RADIUS,
            )
            painter.setClipPath(path)

            # 两条错开半周期的扫光带,让"流动"感更连续
            for shift, alpha_scale in ((0.0, 1.0), (span / 2.0, 0.55)):
                center = (self._offset + shift) % span
                gradient = QLinearGradient(
                    center - self.BAND_WIDTH, 0.0, center, 0.0
                )
                peak = QColor(color)
                peak.setAlphaF(color.alphaF() * alpha_scale)
                gradient.setColorAt(0.0, transparent)
                gradient.setColorAt(0.5, peak)
                gradient.setColorAt(1.0, transparent)
                painter.fillRect(0, 0, width, height, gradient)
        finally:
            painter.end()
