"""
Модуль экспорта внутренних данных приложения geomod в формат DXF.

Целевая версия формата: AutoCAD R12 (AC1009) — наиболее переносимая
версия DXF, открывается всеми распространёнными CAD-системами:
AutoCAD, nanoCAD, КОМПАС-3D, LibreCAD, QCAD, FreeCAD, BricsCAD.

Объекты внутренней модели (см. SegmentApp.primitives):
    {type, params, color (#RRGGBB), style_name, name}

Типы примитивов и их соответствие сущностям DXF:
    segment_mouse (отрезок) -> LINE
    polyline       (ломаная) -> POLYLINE/VERTEX/SEQEND
    circle         (окружность) -> CIRCLE
    arc            (дуга) -> ARC
    rect           (прямоугольник) -> замкнутый POLYLINE
    polygon        (многоугольник) -> замкнутый POLYLINE
    ellipse        (эллипс) -> POLYLINE-аппроксимация (нет ELLIPSE в R12)
    spline         (сплайн) -> POLYLINE-аппроксимация (нет SPLINE в R12)

Слои: формируются автоматически по уникальным style_name примитивов;
имя слоя = style_name, цвет = первый встреченный цвет, тип линии =
маппинг из style.type.
"""

import math
import os
import json

from dimensions import (LinearDimension, RadialDimension, AngularDimension,
                        make_dimension, is_dimension_type, arrow_polygon)


# Имя слоя, на который выгружается «развёрнутая» геометрия размеров.
# Имя выбрано читаемым, чтобы пользователь мог его быстро найти/спрятать
# в любой CAD-программе.
DIMENSIONS_LAYER = 'Размеры'


# --- Стандартная палитра AutoCAD ACI (выборка широко используемых цветов).
#     Подбор ближайшего цвета — по евклидову расстоянию в RGB.
_ACI_PALETTE = {
    1:  (255,   0,   0),  # red
    2:  (255, 255,   0),  # yellow
    3:  (  0, 255,   0),  # green
    4:  (  0, 255, 255),  # cyan
    5:  (  0,   0, 255),  # blue
    6:  (255,   0, 255),  # magenta
    7:  (255, 255, 255),  # white
    8:  (128, 128, 128),  # dark gray
    9:  (192, 192, 192),  # light gray
    10: (255,   0,   0),
    20: (255,  63,   0),
    30: (255, 127,   0),
    40: (255, 191,   0),
    50: (255, 255,   0),
    60: (191, 255,   0),
    70: (127, 255,   0),
    80: ( 63, 255,   0),
    90: (  0, 255,   0),
    100:(  0, 255,  63),
    110:(  0, 255, 127),
    120:(  0, 255, 191),
    130:(  0, 255, 255),
    140:(  0, 191, 255),
    150:(  0, 127, 255),
    160:(  0,  63, 255),
    170:(  0,   0, 255),
    180:( 63,   0, 255),
    190:(127,   0, 255),
    200:(191,   0, 255),
    210:(255,   0, 255),
    220:(255,   0, 191),
    230:(255,   0, 127),
    240:(255,   0,  63),
    250:( 51,  51,  51),
    251:( 80,  80,  80),
    252:(105, 105, 105),
    253:(130, 130, 130),
    254:(190, 190, 190),
    255:(255, 255, 255),
}


# Соответствие внутренних типов стилей именам DXF LTYPE.
# В DXF R12 определяются стандартные типы линий — задаём их в TABLES/LTYPE.
_LTYPE_MAP = {
    'solid':       'CONTINUOUS',
    'dashed':      'DASHED',
    'dashdot':     'DASHDOT',
    'dashdotdot':  'DIVIDE',
    'wavy':        'CONTINUOUS',  # нет аналога — сплошная
    'zigzag':      'CONTINUOUS',  # нет аналога — сплошная
}


# Описания типов линий (имя, описание, шаблон).
# Шаблон: (длина_паттерна, [сегменты]); + штрих, - пробел, 0 точка.
_LTYPE_DEFS = [
    ('CONTINUOUS', 'Solid line', 0.0, []),
    ('DASHED',     '__ __ __ __ __ __ __ __ __ __ __ __ _',
                   0.75, [0.5, -0.25]),
    ('DASHDOT',    '__ . __ . __ . __ . __ . __ . __ . __',
                   1.0,  [0.5, -0.25, 0.0, -0.25]),
    ('DIVIDE',     '__ . . __ . . __ . . __ . . __ . . __',
                   1.25, [0.5, -0.25, 0.0, -0.25, 0.0, -0.25]),
]


def hex_to_rgb(hex_color):
    """'#RRGGBB' -> (r, g, b) в диапазоне 0..255. Для некорректного входа -> белый."""
    if not isinstance(hex_color, str):
        return (255, 255, 255)
    s = hex_color.strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    if len(s) != 6:
        return (255, 255, 255)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def rgb_to_aci(rgb):
    """Подбор ближайшего индекса AutoCAD Color Index (1..255) для заданного RGB."""
    r, g, b = rgb
    best_idx = 7
    best_d2 = float('inf')
    for idx, (pr, pg, pb) in _ACI_PALETTE.items():
        d2 = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_idx = idx
    return best_idx


def sanitize_layer_name(name):
    """Ограничения R12: имя слоя — до 31 символа, без пробелов и спецсимволов.
    Запрещённые: < > / \\ " : ; ? * | = '. Заменяем на '_'."""
    if not name:
        return 'LAYER'
    bad = set('<>/\\":;?*|=\' \t\n\r')
    cleaned = ''.join('_' if c in bad else c for c in name)
    cleaned = cleaned[:31]
    return cleaned or 'LAYER'


# ----------------------------------------------------------------------
# Низкоуровневая запись DXF: пары (group_code, value).
# ----------------------------------------------------------------------

def _tag(out, code, value):
    """Записать пару group_code / value в формате DXF (по две строки)."""
    out.append(f'{code:>3d}')
    if isinstance(value, float):
        # 6 знаков после запятой достаточно для черчения; убираем хвостовые нули.
        out.append(f'{value:.6f}'.rstrip('0').rstrip('.') or '0')
    else:
        out.append(str(value))


def _section_begin(out, name):
    _tag(out, 0, 'SECTION')
    _tag(out, 2, name)


def _section_end(out):
    _tag(out, 0, 'ENDSEC')


# ----------------------------------------------------------------------
# Аппроксимация кривых (для эллипса и сплайна).
# ----------------------------------------------------------------------

def _ellipse_points(cx, cy, rx, ry, angle_deg, n=72):
    """Точки эллипса с поворотом главной оси на angle_deg (rx — главная ось)."""
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        x0 = rx * math.cos(t)
        y0 = ry * math.sin(t)
        # Поворот на angle и сдвиг в (cx, cy)
        pts.append((cx + x0 * ca - y0 * sa, cy + x0 * sa + y0 * ca))
    return pts


def _catmull_rom(points, samples_per_segment=20):
    """Аппроксимация сплайна Catmull-Rom через точки. Возвращает список (x, y)."""
    n = len(points)
    if n < 2:
        return list(points)
    if n == 2:
        return list(points)
    # Дополняем фиктивными концевыми точками для краевых сегментов.
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(len(pts) - 3):
        p0, p1, p2, p3 = pts[i], pts[i+1], pts[i+2], pts[i+3]
        for s in range(samples_per_segment):
            t = s / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * ((2 * p1[0]) +
                       (-p0[0] + p2[0]) * t +
                       (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) +
                       (-p0[1] + p2[1]) * t +
                       (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(points[-1])
    return out


# ----------------------------------------------------------------------
# Запись HEADER.
# ----------------------------------------------------------------------

# Соответствие миллиметров и кодов $INSUNITS (DXF R2000+, R12 игнорирует, но запись допустима).
_INSUNITS_CODES = {
    'mm':       4,
    'cm':       5,
    'm':        6,
    'in':       1,
    'ft':       2,
    'unitless': 0,
}


def _write_header(out, extents, units='mm'):
    _section_begin(out, 'HEADER')
    _tag(out, 9, '$ACADVER')
    _tag(out, 1, 'AC1009')
    _tag(out, 9, '$INSUNITS')
    _tag(out, 70, _INSUNITS_CODES.get(units, 0))
    xmin, ymin, xmax, ymax = extents
    _tag(out, 9, '$EXTMIN')
    _tag(out, 10, float(xmin))
    _tag(out, 20, float(ymin))
    _tag(out, 30, 0.0)
    _tag(out, 9, '$EXTMAX')
    _tag(out, 10, float(xmax))
    _tag(out, 20, float(ymax))
    _tag(out, 30, 0.0)
    # Текущий слой по умолчанию.
    _tag(out, 9, '$CLAYER')
    _tag(out, 8, '0')
    _section_end(out)


# ----------------------------------------------------------------------
# Запись TABLES (LTYPE и LAYER — обязательны для R12).
# ----------------------------------------------------------------------

def _write_tables(out, layers):
    _section_begin(out, 'TABLES')

    # --- LTYPE
    _tag(out, 0, 'TABLE')
    _tag(out, 2, 'LTYPE')
    _tag(out, 70, len(_LTYPE_DEFS))
    for name, descr, total_len, segs in _LTYPE_DEFS:
        _tag(out, 0, 'LTYPE')
        _tag(out, 2, name)
        _tag(out, 70, 0)
        _tag(out, 3, descr)
        _tag(out, 72, 65)  # 'A' — alignment
        _tag(out, 73, len(segs))
        _tag(out, 40, total_len)
        for s in segs:
            _tag(out, 49, s)
    _tag(out, 0, 'ENDTAB')

    # --- LAYER
    _tag(out, 0, 'TABLE')
    _tag(out, 2, 'LAYER')
    _tag(out, 70, len(layers) + 1)  # +1 на слой '0'
    # Обязательный слой '0'.
    _tag(out, 0, 'LAYER')
    _tag(out, 2, '0')
    _tag(out, 70, 0)
    _tag(out, 62, 7)
    _tag(out, 6, 'CONTINUOUS')
    # Пользовательские слои, образованные из стилей.
    for layer_name, info in layers.items():
        _tag(out, 0, 'LAYER')
        _tag(out, 2, layer_name)
        _tag(out, 70, 0)            # флаги
        _tag(out, 62, info['aci'])  # цвет
        _tag(out, 6,  info['ltype'])
    _tag(out, 0, 'ENDTAB')

    # --- STYLE (текстовый стиль для TEXT-сущностей надписей размеров)
    _tag(out, 0, 'TABLE')
    _tag(out, 2, 'STYLE')
    _tag(out, 70, 1)
    _tag(out, 0, 'STYLE')
    _tag(out, 2, 'STANDARD')
    _tag(out, 70, 0)
    _tag(out, 40, 0.0)        # фиксированная высота (0 — берётся из TEXT)
    _tag(out, 41, 1.0)        # коэффициент ширины
    _tag(out, 50, 0.0)        # наклон
    _tag(out, 71, 0)          # генерация
    _tag(out, 42, 2.5)        # последняя использованная высота
    _tag(out, 3, 'txt')       # имя файла шрифта
    _tag(out, 4, '')          # большой шрифт
    _tag(out, 0, 'ENDTAB')

    _section_end(out)


# ----------------------------------------------------------------------
# Запись BLOCKS — для R12 секция обязана присутствовать, может быть пустой.
# ----------------------------------------------------------------------

def _write_blocks(out):
    _section_begin(out, 'BLOCKS')
    _section_end(out)


# ----------------------------------------------------------------------
# Запись отдельных сущностей.
# ----------------------------------------------------------------------

def _emit_common(out, etype, layer, color_aci):
    """Заголовок сущности: тип + слой + цвет."""
    _tag(out, 0, etype)
    _tag(out, 8, layer)
    if color_aci is not None:
        _tag(out, 62, color_aci)


def _emit_point(out, layer, color, x, y):
    _emit_common(out, 'POINT', layer, color)
    _tag(out, 10, float(x))
    _tag(out, 20, float(y))
    _tag(out, 30, 0.0)


def _emit_line(out, layer, color, x1, y1, x2, y2):
    _emit_common(out, 'LINE', layer, color)
    _tag(out, 10, float(x1))
    _tag(out, 20, float(y1))
    _tag(out, 30, 0.0)
    _tag(out, 11, float(x2))
    _tag(out, 21, float(y2))
    _tag(out, 31, 0.0)


def _emit_circle(out, layer, color, cx, cy, r):
    _emit_common(out, 'CIRCLE', layer, color)
    _tag(out, 10, float(cx))
    _tag(out, 20, float(cy))
    _tag(out, 30, 0.0)
    _tag(out, 40, float(r))


def _emit_arc(out, layer, color, cx, cy, r, start_deg, end_deg):
    _emit_common(out, 'ARC', layer, color)
    _tag(out, 10, float(cx))
    _tag(out, 20, float(cy))
    _tag(out, 30, 0.0)
    _tag(out, 40, float(r))
    # В DXF дуга идёт против часовой стрелки от start к end.
    _tag(out, 50, float(start_deg) % 360.0)
    _tag(out, 51, float(end_deg) % 360.0)


def _emit_text(out, layer, color, x, y, height, text, rotation_deg=0.0,
               halign=1, valign=2):
    """TEXT-сущность DXF R12. halign=1 (centered), valign=2 (middle)."""
    _emit_common(out, 'TEXT', layer, color)
    _tag(out, 7, 'STANDARD')
    _tag(out, 10, float(x))
    _tag(out, 20, float(y))
    _tag(out, 30, 0.0)
    _tag(out, 40, float(height))
    _tag(out, 1,  str(text))
    if abs(rotation_deg) > 1e-9:
        _tag(out, 50, float(rotation_deg) % 360.0)
    _tag(out, 41, 1.0)
    _tag(out, 51, 0.0)
    _tag(out, 71, 0)
    _tag(out, 72, int(halign))
    _tag(out, 11, float(x))     # alignment point (используется при halign>0)
    _tag(out, 21, float(y))
    _tag(out, 31, 0.0)
    _tag(out, 73, int(valign))


def _emit_solid_triangle(out, layer, color, p1, p2, p3):
    """Закрашенный треугольник через SOLID (R12). Поддерживается всеми CAD."""
    _emit_common(out, 'SOLID', layer, color)
    # Внимание: SOLID ожидает 4 точки в zigzag-порядке (10,11,12,13);
    # для треугольника четвёртая точка = третья.
    _tag(out, 10, float(p1[0])); _tag(out, 20, float(p1[1])); _tag(out, 30, 0.0)
    _tag(out, 11, float(p2[0])); _tag(out, 21, float(p2[1])); _tag(out, 31, 0.0)
    _tag(out, 12, float(p3[0])); _tag(out, 22, float(p3[1])); _tag(out, 32, 0.0)
    _tag(out, 13, float(p3[0])); _tag(out, 23, float(p3[1])); _tag(out, 33, 0.0)


def _emit_polyline(out, layer, color, points, closed=False):
    """R12 POLYLINE + последовательность VERTEX + SEQEND."""
    if len(points) < 2:
        # 1 точка: вырождаемся в POINT.
        if len(points) == 1:
            _emit_point(out, layer, color, points[0][0], points[0][1])
        return
    _emit_common(out, 'POLYLINE', layer, color)
    _tag(out, 66, 1)            # vertices follow flag (R12)
    _tag(out, 10, 0.0)          # «опорная» точка (всегда 0,0,0 для 2D)
    _tag(out, 20, 0.0)
    _tag(out, 30, 0.0)
    _tag(out, 70, 1 if closed else 0)
    for x, y in points:
        _tag(out, 0, 'VERTEX')
        _tag(out, 8, layer)
        _tag(out, 10, float(x))
        _tag(out, 20, float(y))
        _tag(out, 30, 0.0)
    _tag(out, 0, 'SEQEND')
    _tag(out, 8, layer)


# ----------------------------------------------------------------------
# Преобразование одного примитива внутренней модели в сущности DXF.
# ----------------------------------------------------------------------

def _emit_dim_arrow(out, layer, color, tip, direction, size, filled=True):
    tri = arrow_polygon(tip, direction, size)
    if filled:
        _emit_solid_triangle(out, layer, color, tri[0], tri[1], tri[2])
    else:
        _emit_polyline(out, layer, color,
                        [tri[0], tri[1], tri[2]], closed=True)


def _readable_text_angle(angle_deg):
    """Нормализует угол поворота текста в (-90, 90] чтобы текст не был перевёрнут."""
    while angle_deg > 90.0:
        angle_deg -= 180.0
    while angle_deg <= -90.0:
        angle_deg += 180.0
    return angle_deg


def _emit_dim_linear(out, dim, layer, color):
    g = dim.geometry()
    e1, e2 = g['e1'], g['e2']
    p1, p2 = g['p1'], g['p2']
    nrm = g['normal']

    L = math.hypot(e2[0]-e1[0], e2[1]-e1[1])
    if L < 1e-9:
        return
    dir_ = ((e2[0]-e1[0])/L, (e2[1]-e1[1])/L)

    # 1) Выносные линии
    for src, foot in ((p1, e1), (p2, e2)):
        vx = foot[0] - src[0]
        vy = foot[1] - src[1]
        vl = math.hypot(vx, vy)
        if vl < 1e-9:
            vx, vy = nrm; vl = 1.0
        ux, uy = vx/vl, vy/vl
        start = (src[0] + ux*dim.ext_offset, src[1] + uy*dim.ext_offset)
        end   = (foot[0] + ux*dim.ext_overshoot, foot[1] + uy*dim.ext_overshoot)
        _emit_line(out, layer, color, start[0], start[1], end[0], end[1])

    # 2) Размерная линия
    ext = dim.dim_extension
    d1 = (e1[0] - dir_[0]*ext, e1[1] - dir_[1]*ext)
    d2 = (e2[0] + dir_[0]*ext, e2[1] + dir_[1]*ext)
    _emit_line(out, layer, color, d1[0], d1[1], d2[0], d2[1])

    # 3) Стрелки
    _emit_dim_arrow(out, layer, color, e1,
                     (-dir_[0], -dir_[1]), dim.arrow_size, dim.arrow_filled)
    _emit_dim_arrow(out, layer, color, e2,
                     dir_, dim.arrow_size, dim.arrow_filled)

    # 4) Текст (над размерной линией, со стороны, противоположной геометрии)
    mid = ((e1[0]+e2[0])/2.0, (e1[1]+e2[1])/2.0)
    avg_geom = ((p1[0]+p2[0])/2.0, (p1[1]+p2[1])/2.0)
    side = (avg_geom[0]-mid[0])*nrm[0] + (avg_geom[1]-mid[1])*nrm[1]
    text_nrm = nrm if side < 0 else (-nrm[0], -nrm[1])
    offset = dim.text_height * 0.7
    tx = mid[0] + text_nrm[0]*offset
    ty = mid[1] + text_nrm[1]*offset
    # Текст ПАРАЛЛЕЛЬНО размерной линии (ЕСКД ГОСТ 2.307-2011 п.4.6).
    # В DXF Y направлена вверх (как в нашем мире), нормализуем угол в (-90,90].
    angle = _readable_text_angle(math.degrees(math.atan2(dir_[1], dir_[0])))
    _emit_text(out, layer, color, tx, ty, dim.text_height,
                dim.label(), rotation_deg=angle)


def _emit_dim_radial(out, dim, layer, color):
    g = dim.geometry()
    cx, cy = g['center']
    on_circle = g['on_circle']
    opp = g['opposite']
    text_pos = g['text_pos'] or on_circle
    kind = g['kind']

    # Размерная линия + стрелки
    if kind == RadialDimension.KIND_DIAMETER:
        _emit_line(out, layer, color, opp[0], opp[1], on_circle[0], on_circle[1])
        d1 = (on_circle[0]-cx, on_circle[1]-cy)
        l1 = math.hypot(*d1) or 1.0
        _emit_dim_arrow(out, layer, color, on_circle,
                         (d1[0]/l1, d1[1]/l1), dim.arrow_size, dim.arrow_filled)
        d2 = (opp[0]-cx, opp[1]-cy)
        l2 = math.hypot(*d2) or 1.0
        _emit_dim_arrow(out, layer, color, opp,
                         (d2[0]/l2, d2[1]/l2), dim.arrow_size, dim.arrow_filled)
    else:
        _emit_line(out, layer, color, cx, cy, on_circle[0], on_circle[1])
        d1 = (on_circle[0]-cx, on_circle[1]-cy)
        l1 = math.hypot(*d1) or 1.0
        _emit_dim_arrow(out, layer, color, on_circle,
                         (d1[0]/l1, d1[1]/l1), dim.arrow_size, dim.arrow_filled)

    # Линия-выноска до позиции текста
    d_text_to_center = math.hypot(text_pos[0]-cx, text_pos[1]-cy)
    text_outside = d_text_to_center > dim.r * 1.05
    if text_outside:
        _emit_line(out, layer, color,
                    on_circle[0], on_circle[1], text_pos[0], text_pos[1])

    label = dim.label()
    with_shelf = bool(getattr(dim, 'with_shelf', False)) and text_outside
    if with_shelf:
        shelf_len = max(len(label) * dim.text_height * 0.7,
                         dim.text_height * 2.0)
        sign = 1.0 if text_pos[0] >= cx else -1.0
        shelf_end = (text_pos[0] + sign*shelf_len, text_pos[1])
        _emit_line(out, layer, color,
                    text_pos[0], text_pos[1], shelf_end[0], shelf_end[1])
        tx = (text_pos[0] + shelf_end[0]) / 2.0
        ty = text_pos[1] + dim.text_height * 0.5
        _emit_text(out, layer, color, tx, ty, dim.text_height,
                    label, rotation_deg=0.0)
    else:
        tx, ty = text_pos[0], text_pos[1] + dim.text_height
        _emit_text(out, layer, color, tx, ty, dim.text_height,
                    label, rotation_deg=0.0)


def _emit_dim_angular(out, dim, layer, color):
    g = dim.geometry()
    v = g['vertex']
    a1, a2 = g['a1'], g['a2']
    R = g['arc_radius']
    p1, p2 = g['p1'], g['p2']

    # Выносные лучи
    for ray_pt in (p1, p2):
        dx = ray_pt[0]-v[0]; dy = ray_pt[1]-v[1]
        l = math.hypot(dx, dy) or 1.0
        ux, uy = dx/l, dy/l
        ext_start = (v[0] + ux*(l + dim.ext_offset),
                      v[1] + uy*(l + dim.ext_offset))
        arc_end   = (v[0] + ux*(R + dim.ext_overshoot),
                      v[1] + uy*(R + dim.ext_overshoot))
        _emit_line(out, layer, color,
                    ext_start[0], ext_start[1], arc_end[0], arc_end[1])

    # Размерная дуга — DXF ARC всегда CCW от start к end
    d = a2 - a1
    while d >  math.pi: d -= 2*math.pi
    while d < -math.pi: d += 2*math.pi
    if d >= 0:
        start_deg, end_deg = math.degrees(a1), math.degrees(a2)
    else:
        start_deg, end_deg = math.degrees(a2), math.degrees(a1)
    _emit_arc(out, layer, color, v[0], v[1], R, start_deg, end_deg)

    # Стрелки касательно к дуге
    end1 = (v[0] + R*math.cos(a1), v[1] + R*math.sin(a1))
    end2 = (v[0] + R*math.cos(a2), v[1] + R*math.sin(a2))
    s = 1.0 if d >= 0 else -1.0
    tan1 = (-math.sin(a1)*s,  math.cos(a1)*s)
    tan2 = ( math.sin(a2)*s, -math.cos(a2)*s)
    _emit_dim_arrow(out, layer, color, end1,
                     (-tan1[0], -tan1[1]), dim.arrow_size, dim.arrow_filled)
    _emit_dim_arrow(out, layer, color, end2,
                     (-tan2[0], -tan2[1]), dim.arrow_size, dim.arrow_filled)

    # Текст по середине дуги, ПАРАЛЛЕЛЬНО касательной (ЕСКД).
    mid = a1 + d/2.0
    tx = v[0] + (R + dim.text_height*0.7)*math.cos(mid)
    ty = v[1] + (R + dim.text_height*0.7)*math.sin(mid)
    tan_deg = _readable_text_angle(math.degrees(mid) + 90.0)
    _emit_text(out, layer, color, tx, ty, dim.text_height,
                dim.label(), rotation_deg=tan_deg)


def _emit_dimension(out, prim, layer, color):
    """Развёртывает размер в стандартные DXF-сущности (LINE/ARC/SOLID/TEXT)."""
    try:
        dim = make_dimension(prim['type'], prim['params'])
    except Exception:
        return
    if isinstance(dim, LinearDimension):
        _emit_dim_linear(out, dim, layer, color)
    elif isinstance(dim, RadialDimension):
        _emit_dim_radial(out, dim, layer, color)
    elif isinstance(dim, AngularDimension):
        _emit_dim_angular(out, dim, layer, color)


def _convert_primitive(out, prim, layer, color_aci, layer_color_aci):
    """color_aci — цвет конкретного примитива; если совпадает с цветом слоя,
    группу 62 не пишем (равнозначно BYLAYER → код 256, что и есть значение по умолчанию)."""
    eff_color = None if color_aci == layer_color_aci else color_aci

    t = prim['type']
    p = prim['params']

    if t == 'segment_mouse':
        x1, y1 = p['p1']
        x2, y2 = p['p2']
        _emit_line(out, layer, eff_color, x1, y1, x2, y2)

    elif t == 'polyline':
        _emit_polyline(out, layer, eff_color, p['points'], closed=False)

    elif t == 'circle':
        _emit_circle(out, layer, eff_color, p['cx'], p['cy'], p['r'])

    elif t == 'arc':
        _emit_arc(out, layer, eff_color,
                  p['cx'], p['cy'], p['r'],
                  p['start_angle'], p['end_angle'])

    elif t == 'rect':
        _emit_polyline(out, layer, eff_color, p['points'], closed=True)

    elif t == 'polygon':
        verts = p.get('vertices') or []
        if verts:
            _emit_polyline(out, layer, eff_color, verts, closed=True)

    elif t == 'ellipse':
        # R12 не имеет сущности ELLIPSE — аппроксимируем замкнутой полилинией.
        pts = _ellipse_points(p['cx'], p['cy'], p['rx'], p['ry'],
                              p.get('angle', 0.0), n=72)
        _emit_polyline(out, layer, eff_color, pts, closed=True)

    elif t == 'spline':
        pts = p.get('points') or []
        # Сплайн внутренней модели — Catmull-Rom через контрольные точки.
        approx = _catmull_rom(pts, samples_per_segment=20)
        _emit_polyline(out, layer, eff_color, approx, closed=False)

    elif is_dimension_type(t):
        # Размеры всегда экспортируются на специальный слой и в виде
        # стандартных сущностей — это гарантирует совместимость со всеми
        # CAD-программами и не требует поддержки DIMENSION/DIMSTYLE.
        _emit_dimension(out, prim, DIMENSIONS_LAYER, eff_color)

    # Неизвестные типы тихо пропускаем.


# ----------------------------------------------------------------------
# Расчёт extents для $EXTMIN/$EXTMAX.
# ----------------------------------------------------------------------

def _accumulate_extent(prim, acc):
    """Расширяет [xmin,ymin,xmax,ymax] на габариты примитива."""
    t = prim['type']
    p = prim['params']
    pts = []
    if t == 'segment_mouse':
        pts = [p['p1'], p['p2']]
    elif t in ('polyline', 'spline'):
        pts = list(p.get('points') or [])
    elif t == 'circle':
        cx, cy, r = p['cx'], p['cy'], p['r']
        pts = [(cx - r, cy - r), (cx + r, cy + r)]
    elif t == 'arc':
        cx, cy, r = p['cx'], p['cy'], p['r']
        pts = [(cx - r, cy - r), (cx + r, cy + r)]
    elif t == 'rect':
        pts = list(p.get('points') or [])
    elif t == 'polygon':
        pts = list(p.get('vertices') or [])
    elif t == 'ellipse':
        # Грубая, но безопасная оценка через max(rx, ry).
        cx, cy = p['cx'], p['cy']
        m = max(p['rx'], p['ry'])
        pts = [(cx - m, cy - m), (cx + m, cy + m)]
    elif t == 'dim_linear':
        pts = [p.get('p1', (0, 0)), p.get('p2', (0, 0)),
               p.get('dim_pos', (0, 0))]
    elif t == 'dim_radial':
        cx, cy, r = p.get('cx', 0), p.get('cy', 0), p.get('r', 0)
        pts = [(cx - r, cy - r), (cx + r, cy + r)]
        if p.get('text_pos'):
            pts.append(p['text_pos'])
    elif t == 'dim_angular':
        v = p.get('vertex', (0, 0))
        R = p.get('arc_radius', 1.0)
        pts = [(v[0] - R, v[1] - R), (v[0] + R, v[1] + R)]

    for x, y in pts:
        if acc[0] is None or x < acc[0]: acc[0] = x
        if acc[1] is None or y < acc[1]: acc[1] = y
        if acc[2] is None or x > acc[2]: acc[2] = x
        if acc[3] is None or y > acc[3]: acc[3] = y


# ----------------------------------------------------------------------
# Публичная функция экспорта.
# ----------------------------------------------------------------------

def export_to_dxf(filepath, primitives, line_styles=None, units='mm',
                  default_color='#FFFFFF'):
    """Экспортировать список примитивов внутренней модели в DXF-файл.

    Параметры
    ---------
    filepath : str
        Путь к создаваемому .dxf файлу.
    primitives : list[dict]
        Список примитивов в формате SegmentApp.primitives.
    line_styles : dict | None
        Отображение style_name -> {'type': solid|dashed|..., 'width': ...}.
        Используется для назначения LTYPE слоям. Если None — все слои
        будут CONTINUOUS.
    units : str
        Единицы измерения: 'mm', 'cm', 'm', 'in', 'ft', 'unitless'.
    default_color : str
        Цвет, если у примитива не задан 'color'.

    Возвращает
    ----------
    dict со статистикой: {'entities': N, 'layers': M, 'path': filepath}
    """
    if line_styles is None:
        line_styles = {}

    # 1) Собираем уникальные слои по style_name.
    #    Цвет слоя = первый встреченный цвет среди примитивов этого стиля.
    layers = {}                 # layer_name -> {'aci', 'ltype', 'rgb'}
    style_to_layer = {}         # style_name -> layer_name
    for prim in primitives:
        # Размеры всегда уходят на отдельный слой (не на слой их style_name)
        if is_dimension_type(prim['type']):
            continue
        style_name = prim.get('style_name') or 'Сплошная основная'
        layer_name = sanitize_layer_name(style_name)
        style_to_layer[style_name] = layer_name
        if layer_name not in layers:
            style = line_styles.get(style_name, {'type': 'solid'})
            ltype = _LTYPE_MAP.get(style.get('type', 'solid'), 'CONTINUOUS')
            color_hex = prim.get('color') or default_color
            rgb = hex_to_rgb(color_hex)
            layers[layer_name] = {
                'aci':   rgb_to_aci(rgb),
                'ltype': ltype,
                'rgb':   rgb,
            }

    # Регистрируем слой 'Размеры', если есть размеры.
    has_dims = any(is_dimension_type(p['type']) for p in primitives)
    if has_dims:
        dim_color = next((p.get('color')
                          for p in primitives if is_dimension_type(p['type'])),
                          default_color) or default_color
        dim_rgb = hex_to_rgb(dim_color)
        layers[DIMENSIONS_LAYER] = {
            'aci':   rgb_to_aci(dim_rgb),
            'ltype': 'CONTINUOUS',
            'rgb':   dim_rgb,
        }

    # 2) Расчёт габаритов.
    extent = [None, None, None, None]
    for prim in primitives:
        _accumulate_extent(prim, extent)
    if extent[0] is None:
        extent = [0.0, 0.0, 100.0, 100.0]

    # 3) Сборка тела файла.
    out = []
    _write_header(out, extent, units=units)
    _write_tables(out, layers)
    _write_blocks(out)

    # ENTITIES
    _section_begin(out, 'ENTITIES')
    n_entities = 0
    for prim in primitives:
        style_name = prim.get('style_name') or 'Сплошная основная'
        layer_name = style_to_layer.get(style_name, '0')
        layer_color = layers.get(layer_name, {}).get('aci', 7)
        color_hex = prim.get('color') or default_color
        color_aci = rgb_to_aci(hex_to_rgb(color_hex))
        _convert_primitive(out, prim, layer_name, color_aci, layer_color)
        n_entities += 1
    _section_end(out)

    _tag(out, 0, 'EOF')

    # 4) Запись на диск (CRLF — стандарт DXF).
    text = '\r\n'.join(out) + '\r\n'
    # Каталог должен существовать; не создаём его молча.
    folder = os.path.dirname(os.path.abspath(filepath))
    if folder and not os.path.isdir(folder):
        raise FileNotFoundError(f'Каталог не существует: {folder}')
    with open(filepath, 'w', encoding='cp1251', errors='replace', newline='') as f:
        f.write(text)

    # 5) Сайдкар-файл для размеров (.dim.json).
    #    DXF содержит только развёрнутую геометрию размеров — для других CAD.
    #    Чтобы наше приложение могло восстановить редактируемые размеры
    #    при следующем открытии, сохраняем их параметры рядом с DXF.
    #    Файл с расширением .dim.json не мешает другим программам.
    sidecar_n = _write_dim_sidecar(filepath, primitives)

    return {
        'entities': n_entities,
        'layers':   len(layers),
        'path':     filepath,
        'dim_sidecar': sidecar_n,
    }


# ----------------------------------------------------------------------
# Сайдкар-файл с описаниями размеров.
# ----------------------------------------------------------------------

def _dim_sidecar_path(dxf_path):
    base, _ = os.path.splitext(dxf_path)
    return base + '.dim.json'


def _write_dim_sidecar(dxf_path, primitives):
    """Сохраняет размеры в JSON рядом с DXF. Возвращает число записанных размеров.
    Если размеров нет — старый файл удаляется (если был)."""
    dims = [p for p in primitives if is_dimension_type(p['type'])]
    sidecar_path = _dim_sidecar_path(dxf_path)
    if not dims:
        try:
            if os.path.isfile(sidecar_path):
                os.remove(sidecar_path)
        except OSError:
            pass
        return 0

    payload = {
        'format':  'geomod-dimensions',
        'version': 1,
        'dimensions': [
            {
                'type':       p['type'],
                'name':       p.get('name', ''),
                'color':      p.get('color', '#FFFFFF'),
                'style_name': p.get('style_name', 'Сплошная тонкая'),
                'id':         p.get('id'),
                'params':     p['params'],
            }
            for p in dims
        ],
    }
    with open(sidecar_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return len(dims)
