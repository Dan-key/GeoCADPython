"""
Модуль размеров чертежа по ГОСТ 2.307-2011 (ЕСКД).

Иерархия классов:
    Dimension (базовый)
        ├── LinearDimension   — линейный (горизонтальный/вертикальный/выровненный)
        ├── RadialDimension   — радиальный (R / Ø)
        └── AngularDimension  — угловой

Каждый размер хранит:
  * измеряемые геометрические данные (точки, центр, радиус и т.п.);
  * параметры оформления (стрелки, шрифт, цвет, выходы выносных линий);
  * необязательную ассоциативную ссылку assoc — список словарей вида
    {'point_key': <ключ внутри размера>,
     'prim_id':   <id примитива-источника>,
     'src_key':   <ключ точки в исходном примитиве>}.

Сами параметры сериализуются в обычный dict (см. to_params / from_params),
что позволяет хранить размеры в общем массиве примитивов приложения.
"""

import math


# ---------- стрелка по ЕСКД ----------
def arrow_polygon(tip, direction, size, ratio=0.25):
    """Возвращает 3 мировые точки треугольной (закрашенной) стрелки.

    tip       — точка-острие (мировые координаты),
    direction — единичный вектор направления стрелки (от хвоста к острию),
    size      — длина стрелки в мировых единицах,
    ratio     — отношение полуширины основания к длине (по ЕСКД ~1:3).
    """
    dx, dy = direction
    px, py = -dy, dx                      # перпендикуляр
    bx = tip[0] - dx * size
    by = tip[1] - dy * size
    half = size * ratio
    return [tip,
            (bx + px * half, by + py * half),
            (bx - px * half, by - py * half)]


# ====================================================================
#                         БАЗОВЫЙ КЛАСС
# ====================================================================
class Dimension:
    """Базовый класс размера. Содержит общие параметры оформления."""
    KIND = 'dim'

    DEFAULTS = dict(
        text_override = None,
        arrow_size    = 0.30,    # длина стрелки (мировые единицы)
        text_height   = 0.35,    # высота шрифта подписи
        ext_overshoot = 0.15,    # выход выносной линии за размерную
        ext_offset    = 0.05,    # зазор между геометрией и началом выносной
        dim_extension = 0.00,    # выход размерной линии за выносные
        precision     = 2,       # знаков после точки
        arrow_filled  = True,
        text_color    = '#FFFFFF',
        line_color    = '#FFFFFF',
        ext_style     = 'Сплошная тонкая',
        dim_style     = 'Сплошная тонкая',
        with_shelf    = False,   # полка-выноска под надпись (для радиальных)
    )

    def __init__(self, **style):
        for k, v in self.DEFAULTS.items():
            setattr(self, k, style.get(k, v))
        # ассоциативные привязки (могут отсутствовать)
        self.assoc = list(style.get('assoc', []))

    # --- API, переопределяемое наследниками ---
    def measure(self):
        """Числовое значение размера (длина / угол / диаметр)."""
        raise NotImplementedError

    def geometry(self):
        """Геометрические данные, нужные для отрисовки."""
        raise NotImplementedError

    def to_params(self):
        """Сериализация параметров (без типа) в dict."""
        d = {k: getattr(self, k) for k in self.DEFAULTS}
        d['assoc'] = list(self.assoc)
        return d

    # --- общая логика подписи ---
    def label(self):
        if self.text_override:
            return str(self.text_override)
        return f"{self.measure():.{self.precision}f}"


# ====================================================================
#                       ЛИНЕЙНЫЙ РАЗМЕР
# ====================================================================
class LinearDimension(Dimension):
    """Линейный размер по ГОСТ 2.307-2011 п.4.

    Поддерживает три ориентации:
      * 'horizontal' — горизонтальная размерная линия (Δx);
      * 'vertical'   — вертикальная (Δy);
      * 'aligned'    — выровненная по линии p1-p2 (истинная длина).
    """
    KIND = 'dim_linear'

    ORIENT_HORIZONTAL = 'horizontal'
    ORIENT_VERTICAL   = 'vertical'
    ORIENT_ALIGNED    = 'aligned'

    def __init__(self, p1, p2, dim_pos, orientation='aligned', **style):
        super().__init__(**style)
        self.p1 = tuple(p1)
        self.p2 = tuple(p2)
        self.dim_pos = tuple(dim_pos)
        self.orientation = orientation

    # --- направление и нормаль размерной линии ---
    def direction(self):
        if self.orientation == self.ORIENT_HORIZONTAL:
            return (1.0, 0.0)
        if self.orientation == self.ORIENT_VERTICAL:
            return (0.0, 1.0)
        dx = self.p2[0] - self.p1[0]
        dy = self.p2[1] - self.p1[1]
        L = math.hypot(dx, dy)
        if L < 1e-12:
            return (1.0, 0.0)
        return (dx / L, dy / L)

    def normal(self):
        dx, dy = self.direction()
        return (-dy, dx)

    def project(self, pt):
        """Проецирует pt на линию через dim_pos в направлении direction()."""
        dx, dy = self.direction()
        ox = pt[0] - self.dim_pos[0]
        oy = pt[1] - self.dim_pos[1]
        t = ox * dx + oy * dy
        return (self.dim_pos[0] + t * dx, self.dim_pos[1] + t * dy)

    # --- обязательные методы ---
    def measure(self):
        e1 = self.project(self.p1)
        e2 = self.project(self.p2)
        return math.hypot(e2[0] - e1[0], e2[1] - e1[1])

    def geometry(self):
        e1 = self.project(self.p1)
        e2 = self.project(self.p2)
        return dict(e1=e1, e2=e2, p1=self.p1, p2=self.p2,
                    direction=self.direction(), normal=self.normal())

    def to_params(self):
        d = super().to_params()
        d.update(p1=self.p1, p2=self.p2,
                 dim_pos=self.dim_pos, orientation=self.orientation)
        return d

    @classmethod
    def from_params(cls, p):
        keys = ('p1', 'p2', 'dim_pos', 'orientation')
        style = {k: v for k, v in p.items() if k not in keys}
        return cls(p['p1'], p['p2'], p['dim_pos'],
                   orientation=p.get('orientation', 'aligned'), **style)


# ====================================================================
#                        РАДИАЛЬНЫЙ РАЗМЕР
# ====================================================================
class RadialDimension(Dimension):
    """Радиальный размер: радиус (R) или диаметр (Ø)
    по ГОСТ 2.307-2011 п.6, п.7."""
    KIND = 'dim_radial'

    KIND_RADIUS   = 'radius'
    KIND_DIAMETER = 'diameter'

    def __init__(self, cx, cy, r, angle_deg, kind='radius',
                 text_pos=None, **style):
        super().__init__(**style)
        self.cx = float(cx)
        self.cy = float(cy)
        self.r = float(r)
        self.angle_deg = float(angle_deg)
        self.kind = kind
        self.text_pos = tuple(text_pos) if text_pos is not None else None

    def measure(self):
        return self.r * (2.0 if self.kind == self.KIND_DIAMETER else 1.0)

    def label(self):
        if self.text_override:
            return str(self.text_override)
        prefix = '⌀' if self.kind == self.KIND_DIAMETER else 'R'
        return f"{prefix}{self.measure():.{self.precision}f}"

    def geometry(self):
        a = math.radians(self.angle_deg)
        on_circle = (self.cx + self.r * math.cos(a),
                     self.cy + self.r * math.sin(a))
        opp = (self.cx - self.r * math.cos(a),
               self.cy - self.r * math.sin(a))
        return dict(center=(self.cx, self.cy),
                    on_circle=on_circle, opposite=opp,
                    angle_rad=a, r=self.r, kind=self.kind,
                    text_pos=self.text_pos)

    def to_params(self):
        d = super().to_params()
        d.update(cx=self.cx, cy=self.cy, r=self.r,
                 angle_deg=self.angle_deg, kind=self.kind,
                 text_pos=self.text_pos)
        return d

    @classmethod
    def from_params(cls, p):
        keys = ('cx', 'cy', 'r', 'angle_deg', 'kind', 'text_pos')
        style = {k: v for k, v in p.items() if k not in keys}
        return cls(p['cx'], p['cy'], p['r'], p['angle_deg'],
                   kind=p.get('kind', 'radius'),
                   text_pos=p.get('text_pos'), **style)


# ====================================================================
#                         УГЛОВОЙ РАЗМЕР
# ====================================================================
class AngularDimension(Dimension):
    """Угловой размер по ГОСТ 2.307-2011 п.5.

    Угол измеряется между лучами vertex→p1 и vertex→p2;
    дуга размера проводится радиусом arc_radius."""
    KIND = 'dim_angular'

    def __init__(self, vertex, p1, p2, arc_radius, **style):
        super().__init__(**style)
        self.vertex = tuple(vertex)
        self.p1 = tuple(p1)
        self.p2 = tuple(p2)
        self.arc_radius = float(arc_radius)

    def angles(self):
        a1 = math.atan2(self.p1[1] - self.vertex[1],
                        self.p1[0] - self.vertex[0])
        a2 = math.atan2(self.p2[1] - self.vertex[1],
                        self.p2[0] - self.vertex[0])
        return a1, a2

    def measure(self):
        a1, a2 = self.angles()
        d = (a2 - a1) % (2 * math.pi)
        if d > math.pi:
            d = 2 * math.pi - d
        return math.degrees(d)

    def label(self):
        if self.text_override:
            return str(self.text_override)
        return f"{self.measure():.{self.precision}f}°"

    def geometry(self):
        a1, a2 = self.angles()
        d = a2 - a1
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        mid = a1 + d / 2
        sign = 1.0 if d >= 0 else -1.0
        return dict(vertex=self.vertex,
                    a1=a1, a2=a2, mid=mid, sign=sign,
                    arc_radius=self.arc_radius,
                    p1=self.p1, p2=self.p2)

    def to_params(self):
        d = super().to_params()
        d.update(vertex=self.vertex, p1=self.p1, p2=self.p2,
                 arc_radius=self.arc_radius)
        return d

    @classmethod
    def from_params(cls, p):
        keys = ('vertex', 'p1', 'p2', 'arc_radius')
        style = {k: v for k, v in p.items() if k not in keys}
        return cls(p['vertex'], p['p1'], p['p2'], p['arc_radius'], **style)


# ====================================================================
#                              ФАБРИКА
# ====================================================================
def make_dimension(prim_type, params):
    """Восстановление объекта-размера из (тип, параметры)."""
    if prim_type == LinearDimension.KIND:
        return LinearDimension.from_params(params)
    if prim_type == RadialDimension.KIND:
        return RadialDimension.from_params(params)
    if prim_type == AngularDimension.KIND:
        return AngularDimension.from_params(params)
    raise ValueError(f"Unknown dimension type: {prim_type}")


def is_dimension_type(prim_type):
    return prim_type in (LinearDimension.KIND,
                         RadialDimension.KIND,
                         AngularDimension.KIND)
