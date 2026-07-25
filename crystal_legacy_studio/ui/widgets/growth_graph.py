from __future__ import annotations
import tkinter as tk
from crystal_legacy_studio.ui.theme import DARK

class GrowthGraph(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            bg=DARK["panel2"],
            highlightthickness=1,
            highlightbackground=DARK["border"],
            height=300,
            **kwargs,
        )
        self.points: list[tuple[int, int]] = []
        self.title = "Growth"
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_series(self, points: list[tuple[int, int]], title: str) -> None:
        self.points = points
        self.title = title
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 200)
        height = max(self.winfo_height(), 160)
        margin_left, margin_right, margin_top, margin_bottom = 52, 18, 30, 38

        self.create_text(
            margin_left, 12, text=self.title, anchor="w",
            fill=DARK["fg"], font=("Segoe UI", 10, "bold")
        )
        if not self.points:
            self.create_text(
                width / 2, height / 2, text="No curve data",
                fill=DARK["muted"]
            )
            return

        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(0, min(ys)), max(1, max(ys))

        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        def px(x):
            return margin_left + ((x - min_x) / max(1, max_x - min_x)) * plot_w

        def py(y):
            return margin_top + plot_h - ((y - min_y) / max(1, max_y - min_y)) * plot_h

        # Grid and axes.
        self.create_line(margin_left, margin_top, margin_left, margin_top + plot_h, fill=DARK["border"])
        self.create_line(margin_left, margin_top + plot_h, margin_left + plot_w, margin_top + plot_h, fill=DARK["border"])

        for step in range(6):
            value = round(min_y + (max_y - min_y) * step / 5)
            y = py(value)
            self.create_line(margin_left, y, margin_left + plot_w, y, fill=DARK["border"], dash=(2, 4))
            self.create_text(margin_left - 7, y, text=str(value), anchor="e", fill=DARK["muted"])

        for step in range(6):
            value = round(min_x + (max_x - min_x) * step / 5)
            x = px(value)
            self.create_text(x, margin_top + plot_h + 18, text=str(value), fill=DARK["muted"])

        coordinates = []
        for x, y in self.points:
            coordinates.extend((px(x), py(y)))
        if len(coordinates) >= 4:
            self.create_line(*coordinates, fill=DARK["accent"], width=2, smooth=True)
        for x, y in self.points:
            if x in (min_x, max_x) or x % 10 == 0:
                self.create_oval(px(x)-2, py(y)-2, px(x)+2, py(y)+2, fill=DARK["accent"], outline="")
