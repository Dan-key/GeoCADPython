"""
Модуль импорта DXF (Autodesk Drawing Exchange Format) во внутренние
структуры данных приложения geomod.

Поддерживается ASCII-формат DXF (R12 / AC1009 и совместимые версии,
сгенерированные другими CAD). При обнаружении двоичного DXF выдаётся
понятное сообщение об ошибке.

Что обрабатывается:
    Секция HEADER  — $ACADVER, $INSUNITS, $EXTMIN/$EXTMAX
    Секция TABLES  — таблицы LTYPE и LAYER
    Секция BLOCKS  — определения блоков (для разворачивания INSERT-ов)
    Секция ENTITIES (а также сущности из BLOCKS, вставленные через INSERT):
        LINE         -> primitive 'segment_mouse'
        CIRCLE       -> primitive 'circle'
        ARC          -> primitive 'arc'
        ELLIPSE      -> primitive 'ellipse'
        LWPOLYLINE   -> 'polyline' / 'rect' / 'polygon'
        POLYLINE     -> 'polyline' / 'rect' / 'polygon'
        SPLINE       -> primitive 'spline'
        POINT        -> игнорируется (нет аналога во внутренней модели)
        INSERT       -> разворачивание содержимого BLOCK-а

Системы координат:
    Сущности с группой 210/220/230 (extrusion direction), отличной от
    (0, 0, 1), пересчитываются из OCS в WCS по «Arbitrary Axis
    Algorithm» спецификации DXF.

Цвета:
    Поддерживается ACI (1..255). TrueColor (группа 420) считывается
    напрямую как 0xRRGGBB. BYLAYER и BYBLOCK заменяются цветом слоя.

Типы линий:
    LTYPE-имена сопоставляются с внутренними типами стилей:
        CONTINUOUS         -> 'solid'
        *DASHDOTDOT*/DIVIDE-> 'dashdotdot'
        *DASHDOT*          -> 'dashdot'
        *DASH*/HIDDEN/...  -> 'dashed'
        иначе              -> 'solid'

Внешний интерфейс — единственная функция import_from_dxf().
"""

import math
import os
import json

# Имя слоя, на который dxf_export выгружает развёрнутую геометрию размеров.
# При наличии сайдкара сущности этого слоя при импорте пропускаются,
# чтобы не дублировать геометрию.
DIMENSIONS_LAYER = 'Размеры'


# ---------------------------------------------------------------------------
# Палитра ACI (фрагмент стандартной палитры AutoCAD).
# Для индексов, не описанных в таблице, генерируем оттенок программно.
# ---------------------------------------------------------------------------

_ACI_PALETTE = {
    1:  (255,   0,   0),   2:  (255, 255,   0),   3:  (  0, 255,   0),
    4:  (  0, 255, 255),   5:  (  0,   0, 255),   6:  (255,   0, 255),
    7:  (255, 255, 255),   8:  (128, 128, 128),   9:  (192, 192, 192),
    10: (255,   0,   0),   20: (255,  63,   0),   30: (255, 127,   0),
    40: (255, 191,   0),   50: (255, 255,   0),   60: (191, 255,   0),
    70: (127, 255,   0),   80: ( 63, 255,   0),   90: (  0, 255,   0),
    100:(  0, 255,  63),   110:(  0, 255, 127),   120:(  0, 255, 191),
    130:(  0, 255, 255),   140:(  0, 191, 255),   150:(  0, 127, 255),
    160:(  0,  63, 255),   170:(  0,   0, 255),   180:( 63,   0, 255),
    190:(127,   0, 255),   200:(191,   0, 255),   210:(255,   0, 255),
    220:(255,   0, 191),   230:(255,   0, 127),   240:(255,   0,  63),
    250:( 51,  51,  51),   251:( 80,  80,  80),   252:(105, 105, 105),
    253:(130, 130, 130),   254:(190, 190, 190),   255:(255, 255, 255),
}


def aci_to_rgb(aci):
    """Преобразовать индекс цвета AutoCAD (1..255) в кортеж (r, g, b).
    Для индексов между опорными узлами палитры — линейная интерполяция."""
    if aci is None:
        return (255, 255, 255)
    try:
        aci = int(aci)
    except (TypeError, ValueError):
        return (255, 255, 255)
    if aci in _ACI_PALETTE:
        return _ACI_PALETTE[aci]
    # Линейная интерполяция между ближайшими опорными индексами.
    keys = sorted(_ACI_PALETTE.keys())
    lo = max((k for k in keys if k <= aci), default=keys[0])
    hi = min((k for k in keys if k >= aci), default=keys[-1])
    if lo == hi:
        return _ACI_PALETTE[lo]
    t = (aci - lo) / (hi - lo)
    r1, g1, b1 = _ACI_PALETTE[lo]
    r2, g2, b2 = _ACI_PALETTE[hi]
    return (int(r1 + (r2 - r1) * t),
            int(g1 + (g2 - g1) * t),
            int(b1 + (b2 - b1) * t))


def rgb_to_hex(rgb):
    r, g, b = rgb
    return f'#{r:02X}{g:02X}{b:02X}'


def truecolor_to_hex(value):
    """Группа 420 — 24-битный true color, упакованный в одно целое."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return f'#{(v >> 16) & 0xFF:02X}{(v >> 8) & 0xFF:02X}{v & 0xFF:02X}'


# ---------------------------------------------------------------------------
# Сопоставление LTYPE → внутренний тип стиля.
# Ключевые слова из имён LTYPE распространённых CAD-систем.
# ---------------------------------------------------------------------------

def ltype_to_style_type(ltype_name):
    if not ltype_name:
        return 'solid'
    name = ltype_name.upper()
    if name in ('CONTINUOUS', 'BYLAYER', 'BYBLOCK', '') or 'CONTIN' in name:
        return 'solid'
    if 'DIVIDE' in name or 'DASHDOTDOT' in name or 'DASH2DOT' in name:
        return 'dashdotdot'
    if 'DASHDOT' in name or 'DASH_DOT' in name or 'CENTER' in name:
        return 'dashdot'
    if 'DASH' in name or 'HIDDEN' in name or 'DOTTED' in name or 'DOT' in name:
        return 'dashed'
    return 'solid'


# Имя внутреннего стиля по умолчанию для каждого типа.
_STYLE_BY_TYPE = {
    'solid':      'Сплошная основная',
    'dashed':     'Штриховая',
    'dashdot':    'Штрихпунктирная тонкая',
    'dashdotdot': 'Штрихпунктирная с двумя точками',
}


# ---------------------------------------------------------------------------
# Низкоуровневое чтение тегов DXF.
# ---------------------------------------------------------------------------

_BINARY_SIGNATURE = b'AutoCAD Binary DXF'


def _read_text(path):
    """Прочитать ASCII DXF в виде строки. Бинарный — отвергнуть с понятной
    ошибкой. Кодировка определяется по BOM и/или $DWGCODEPAGE; в простом
    случае пробуем cp1251 (типично для русскоязычных CAD), затем utf-8."""
    with open(path, 'rb') as f:
        head = f.read(22)
        rest = f.read()
    blob = head + rest
    if blob.startswith(_BINARY_SIGNATURE):
        raise ValueError(
            'Двоичный (Binary) DXF не поддерживается. '
            'Сохраните файл как ASCII DXF и повторите импорт.'
        )
    # BOM UTF-8?
    if blob.startswith(b'\xef\xbb\xbf'):
        return blob[3:].decode('utf-8', errors='replace')
    # cp1251 — наиболее вероятная кодировка для DXF в кириллице.
    for enc in ('cp1251', 'utf-8', 'latin-1'):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            continue
    return blob.decode('latin-1', errors='replace')


def _tokenize(text):
    """Преобразовать содержимое ASCII DXF в список пар (code:int, value:str).

    Формат: чередование двух строк — код группы и значение. Код группы
    может содержать ведущие пробелы. Лишние пустые строки пропускаются."""
    lines = text.splitlines()
    tags = []
    i = 0
    n = len(lines)
    while i < n - 1:
        code_str = lines[i].strip()
        i += 1
        if not code_str:
            continue
        try:
            code = int(code_str)
        except ValueError:
            # Повреждённая строка — пропускаем.
            continue
        if i >= n:
            break
        value = lines[i]
        i += 1
        # Значение может содержать пробелы; убираем только CR и хвостовые \r.
        if value.endswith('\r'):
            value = value[:-1]
        tags.append((code, value))
    return tags


def _coerce(code, value):
    """Привести значение к типу, согласно диапазону кода группы."""
    # Координаты и вещественные параметры — float.
    if (10 <= code <= 59) or (110 <= code <= 149) or (210 <= code <= 239) \
            or (1010 <= code <= 1059):
        try:
            return float(value)
        except ValueError:
            return 0.0
    # Целые: 60..79, 90..99, 170..179, 270..289, 370..389, 400..409, 420..429.
    if (60 <= code <= 79) or (90 <= code <= 99) or (170 <= code <= 179) \
            or (270 <= code <= 289) or (370 <= code <= 389) \
            or (400 <= code <= 409) or (420 <= code <= 429):
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return 0
    return value


# ---------------------------------------------------------------------------
# Группировка тегов в блоки сущностей.
# ---------------------------------------------------------------------------

def _split_sections(tags):
    """Разделить поток тегов на словарь section_name -> список под-токенов."""
    sections = {}
    i = 0
    n = len(tags)
    while i < n:
        code, value = tags[i]
        if code == 0 and value == 'SECTION':
            i += 1
            # Следом должен идти код 2 — имя секции.
            if i < n and tags[i][0] == 2:
                name = tags[i][1]
                i += 1
                body = []
                while i < n:
                    c, v = tags[i]
                    if c == 0 and v == 'ENDSEC':
                        i += 1
                        break
                    body.append((c, v))
                    i += 1
                sections[name] = body
                continue
        i += 1
    return sections


def _split_entities(body):
    """Разделить тело секции (ENTITIES/BLOCKS) на список сущностей,
    каждая сущность — список тегов, начинающийся с (0, ETYPE)."""
    entities = []
    current = None
    for code, value in body:
        if code == 0:
            if current is not None:
                entities.append(current)
            current = [(code, value)]
        else:
            if current is not None:
                current.append((code, value))
    if current is not None:
        entities.append(current)
    return entities


# ---------------------------------------------------------------------------
# Извлечение значений по коду группы из набора тегов одной сущности.
# ---------------------------------------------------------------------------

def _get(tags, code, default=None):
    for c, v in tags:
        if c == code:
            return _coerce(c, v)
    return default


def _get_all(tags, code):
    return [_coerce(c, v) for c, v in tags if c == code]


# ---------------------------------------------------------------------------
# OCS -> WCS (Arbitrary Axis Algorithm).
# ---------------------------------------------------------------------------

def _arbitrary_axis(extrusion):
    """Построить базис OCS->WCS по вектору экструзии. Возвращает (Wx, Wy, Wz)."""
    n = extrusion
    nx, ny, nz = n
    # Проверка близости к оси Z с порогом 1/64.
    if abs(nx) < (1.0 / 64.0) and abs(ny) < (1.0 / 64.0):
        ax = (ny, -nx, 0.0)  # Wy ось, но возьмём верное направление ниже
        # Корректная формула: если |nx|<1/64 и |ny|<1/64, Ax = Y x N
        ax = (1.0 * nz - 0.0 * ny, 0.0 * nx - 1.0 * nz, 1.0 * ny - 0.0 * nx)
    else:
        # Ax = Z x N
        ax = (0.0 * nz - 1.0 * ny, 1.0 * nx - 0.0 * nz, 0.0 * ny - 0.0 * nx)
    # Нормализуем Ax
    al = math.sqrt(ax[0] ** 2 + ax[1] ** 2 + ax[2] ** 2) or 1.0
    Wx = (ax[0] / al, ax[1] / al, ax[2] / al)
    # Wy = N x Wx
    Wy = (ny * Wx[2] - nz * Wx[1],
          nz * Wx[0] - nx * Wx[2],
          nx * Wx[1] - ny * Wx[0])
    return Wx, Wy, n


def _ocs_to_wcs(point_ocs, extrusion):
    """Перевести 3D-точку из OCS в WCS по вектору экструзии."""
    if extrusion is None:
        return point_ocs
    nx, ny, nz = extrusion
    if abs(nx) < 1e-12 and abs(ny) < 1e-12 and abs(nz - 1.0) < 1e-12:
        return point_ocs
    Wx, Wy, Wz = _arbitrary_axis(extrusion)
    px, py, pz = point_ocs
    return (px * Wx[0] + py * Wy[0] + pz * Wz[0],
            px * Wx[1] + py * Wy[1] + pz * Wz[1],
            px * Wx[2] + py * Wy[2] + pz * Wz[2])


def _entity_extrusion(tags):
    """Извлечь вектор экструзии 210/220/230. По умолчанию — (0, 0, 1)."""
    ex = _get(tags, 210, None)
    ey = _get(tags, 220, None)
    ez = _get(tags, 230, None)
    if ex is None and ey is None and ez is None:
        return (0.0, 0.0, 1.0)
    return (ex or 0.0, ey or 0.0, ez or 1.0)


# ---------------------------------------------------------------------------
# Парсинг таблиц LAYER и LTYPE.
# ---------------------------------------------------------------------------

def _parse_tables(body):
    layers = {}     # name -> {'aci', 'ltype'}
    ltypes = {}     # name -> {'description', 'pattern'}
    # Тело TABLES — последовательность подтаблиц TABLE…ENDTAB.
    i = 0
    n = len(body)
    while i < n:
        c, v = body[i]
        if c == 0 and v == 'TABLE':
            i += 1
            # Имя таблицы — следующий код 2.
            tname = None
            while i < n and body[i][0] != 0:
                if body[i][0] == 2 and tname is None:
                    tname = body[i][1]
                i += 1
            # Читаем записи до ENDTAB.
            while i < n:
                c2, v2 = body[i]
                if c2 == 0 and v2 == 'ENDTAB':
                    i += 1
                    break
                if c2 == 0 and v2 == tname:
                    # Начало записи таблицы — собираем теги до следующего c==0.
                    rec = [(c2, v2)]
                    i += 1
                    while i < n and body[i][0] != 0:
                        rec.append(body[i])
                        i += 1
                    if tname == 'LAYER':
                        name = _get(rec, 2, '0')
                        aci = _get(rec, 62, 7)
                        ltype = _get(rec, 6, 'CONTINUOUS')
                        # Отрицательный ACI = слой выключен; берём абсолют.
                        try:
                            aci = abs(int(aci))
                        except (TypeError, ValueError):
                            aci = 7
                        layers[name] = {'aci': aci, 'ltype': str(ltype)}
                    elif tname == 'LTYPE':
                        name = _get(rec, 2, 'CONTINUOUS')
                        descr = _get(rec, 3, '')
                        pattern = _get_all(rec, 49)
                        ltypes[name] = {'description': descr, 'pattern': pattern}
                else:
                    i += 1
        else:
            i += 1
    # Гарантируем существование слоя '0' и LTYPE 'CONTINUOUS'.
    if '0' not in layers:
        layers['0'] = {'aci': 7, 'ltype': 'CONTINUOUS'}
    if 'CONTINUOUS' not in ltypes:
        ltypes['CONTINUOUS'] = {'description': 'Solid line', 'pattern': []}
    return layers, ltypes


# ---------------------------------------------------------------------------
# Парсинг блоков (для INSERT).
# ---------------------------------------------------------------------------

def _parse_blocks(body):
    """Разобрать секцию BLOCKS в словарь имя_блока -> {base_point, entities}."""
    blocks = {}
    entities = _split_entities(body)
    current = None
    for ent in entities:
        etype = ent[0][1] if ent and ent[0][0] == 0 else None
        if etype == 'BLOCK':
            name = _get(ent, 2, '')
            base = (_get(ent, 10, 0.0) or 0.0,
                    _get(ent, 20, 0.0) or 0.0,
                    _get(ent, 30, 0.0) or 0.0)
            current = {'base': base, 'entities': []}
            blocks[name] = current
        elif etype == 'ENDBLK':
            current = None
        elif current is not None:
            current['entities'].append(ent)
    return blocks


# ---------------------------------------------------------------------------
# Конвертация одной DXF-сущности во внутренний примитив.
# ---------------------------------------------------------------------------

def _convert_line(tags):
    x1 = _get(tags, 10, 0.0); y1 = _get(tags, 20, 0.0); z1 = _get(tags, 30, 0.0)
    x2 = _get(tags, 11, 0.0); y2 = _get(tags, 21, 0.0); z2 = _get(tags, 31, 0.0)
    # LINE определён в WCS (не в OCS) — преобразование не требуется.
    return {'type': 'segment_mouse',
            'params': {'p1': (x1, y1), 'p2': (x2, y2)}}


def _convert_circle(tags):
    cx = _get(tags, 10, 0.0); cy = _get(tags, 20, 0.0); cz = _get(tags, 30, 0.0)
    r = _get(tags, 40, 1.0)
    ext = _entity_extrusion(tags)
    wx, wy, _ = _ocs_to_wcs((cx, cy, cz), ext)
    return {'type': 'circle', 'params': {'cx': wx, 'cy': wy, 'r': r}}


def _convert_arc(tags):
    cx = _get(tags, 10, 0.0); cy = _get(tags, 20, 0.0); cz = _get(tags, 30, 0.0)
    r = _get(tags, 40, 1.0)
    sa = _get(tags, 50, 0.0)
    ea = _get(tags, 51, 360.0)
    ext = _entity_extrusion(tags)
    wx, wy, _ = _ocs_to_wcs((cx, cy, cz), ext)
    return {'type': 'arc',
            'params': {'cx': wx, 'cy': wy, 'r': r,
                       'start_angle': sa, 'end_angle': ea}}


def _convert_ellipse(tags):
    cx = _get(tags, 10, 0.0); cy = _get(tags, 20, 0.0); cz = _get(tags, 30, 0.0)
    # Конец главной полуоси (относительно центра).
    ax = _get(tags, 11, 1.0); ay = _get(tags, 21, 0.0); az = _get(tags, 31, 0.0)
    ratio = _get(tags, 40, 1.0)
    rx = math.hypot(ax, ay)  # длина главной полуоси
    ry = rx * (ratio or 1.0)
    angle = math.degrees(math.atan2(ay, ax))
    return {'type': 'ellipse',
            'params': {'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry, 'angle': angle}}


def _convert_lwpolyline(tags):
    """LWPOLYLINE — компактная 2D-полилиния. Координаты в OCS."""
    pts = []
    cur = [None, None]
    for c, v in tags:
        cv = _coerce(c, v)
        if c == 10:
            if cur[0] is not None:
                pts.append((cur[0], cur[1] if cur[1] is not None else 0.0))
            cur = [cv, None]
        elif c == 20 and cur[0] is not None:
            cur[1] = cv
    if cur[0] is not None:
        pts.append((cur[0], cur[1] if cur[1] is not None else 0.0))
    closed = bool((_get(tags, 70, 0) or 0) & 1)
    ext = _entity_extrusion(tags)
    elev = _get(tags, 38, 0.0) or 0.0
    pts_w = []
    for x, y in pts:
        wx, wy, _ = _ocs_to_wcs((x, y, elev), ext)
        pts_w.append((wx, wy))
    return _polyline_to_primitive(pts_w, closed)


def _convert_polyline(tags, vertices):
    """Старая POLYLINE: основная сущность + список VERTEX-ей."""
    closed = bool((_get(tags, 70, 0) or 0) & 1)
    ext = _entity_extrusion(tags)
    pts = []
    for vt in vertices:
        x = _get(vt, 10, 0.0); y = _get(vt, 20, 0.0); z = _get(vt, 30, 0.0)
        wx, wy, _ = _ocs_to_wcs((x, y, z), ext)
        pts.append((wx, wy))
    return _polyline_to_primitive(pts, closed)


def _polyline_to_primitive(pts, closed):
    """Решить, чем стала прочитанная полилиния: rect / polygon / polyline."""
    # Уберём дубликат завершающей точки, если он совпадает с первой.
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
        closed = True
    if len(pts) < 2:
        return None
    if closed:
        if len(pts) == 4 and _is_rectangle(pts):
            return {'type': 'rect', 'params': {'points': list(pts)}}
        if len(pts) >= 3:
            return _build_polygon_primitive(pts)
        # 2 точки и closed — выродим в отрезок.
        return {'type': 'segment_mouse',
                'params': {'p1': pts[0], 'p2': pts[1]}}
    if len(pts) == 2:
        return {'type': 'segment_mouse',
                'params': {'p1': pts[0], 'p2': pts[1]}}
    return {'type': 'polyline', 'params': {'points': list(pts)}}


def _is_rectangle(pts, tol=1e-6):
    """4 точки образуют прямоугольник, если противоположные стороны равны
    по длине и смежные стороны взаимно перпендикулярны."""
    if len(pts) != 4:
        return False
    def sub(a, b): return (a[0] - b[0], a[1] - b[1])
    def dot(a, b): return a[0] * b[0] + a[1] * b[1]
    def length2(a):  return a[0] * a[0] + a[1] * a[1]
    s = [sub(pts[(i + 1) % 4], pts[i]) for i in range(4)]
    if abs(length2(s[0]) - length2(s[2])) > tol: return False
    if abs(length2(s[1]) - length2(s[3])) > tol: return False
    if abs(dot(s[0], s[1])) > tol: return False
    return True


def _build_polygon_primitive(pts):
    """Построить полную запись 'polygon' с центром, радиусом и пр."""
    n = len(pts)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    radii = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
    r = max(radii) if radii else 1.0
    base_angle = math.degrees(math.atan2(pts[0][1] - cy, pts[0][0] - cx))
    return {'type': 'polygon',
            'params': {'cx': cx, 'cy': cy, 'r': r, 'n': n,
                       'inscribed': True,
                       'rotation_angle': 0.0,
                       'base_angle': base_angle,
                       'vertices': list(pts)}}


def _convert_spline(tags):
    """SPLINE: используем fit points (11/21), при их отсутствии —
    control points (10/20). Внутренний 'spline' — Catmull-Rom через
    набор точек."""
    fit_x = []
    fit_y = []
    ctrl_x = []
    ctrl_y = []
    cur_fit = [None, None]
    cur_ctrl = [None, None]
    for c, v in tags:
        cv = _coerce(c, v)
        if c == 11:
            if cur_fit[0] is not None:
                fit_x.append(cur_fit[0]); fit_y.append(cur_fit[1] or 0.0)
            cur_fit = [cv, None]
        elif c == 21 and cur_fit[0] is not None:
            cur_fit[1] = cv
        elif c == 10:
            if cur_ctrl[0] is not None:
                ctrl_x.append(cur_ctrl[0]); ctrl_y.append(cur_ctrl[1] or 0.0)
            cur_ctrl = [cv, None]
        elif c == 20 and cur_ctrl[0] is not None:
            cur_ctrl[1] = cv
    if cur_fit[0] is not None:
        fit_x.append(cur_fit[0]); fit_y.append(cur_fit[1] or 0.0)
    if cur_ctrl[0] is not None:
        ctrl_x.append(cur_ctrl[0]); ctrl_y.append(cur_ctrl[1] or 0.0)
    pts = list(zip(fit_x, fit_y)) if fit_x else list(zip(ctrl_x, ctrl_y))
    if len(pts) < 2:
        return None
    return {'type': 'spline', 'params': {'points': pts}}


# ---------------------------------------------------------------------------
# Главный цикл: преобразование всех сущностей.
# ---------------------------------------------------------------------------

def _walk_entities(raw_entities):
    """Разделить сырые сущности, склеив POLYLINE с её VERTEX-ами/SEQEND.
    Возвращает список (tags, etype, sub_tags) — для POLYLINE sub_tags —
    список тегов вершин; для остальных — пустой список."""
    out = []
    i = 0
    n = len(raw_entities)
    while i < n:
        ent = raw_entities[i]
        etype = ent[0][1] if ent and ent[0][0] == 0 else None
        if etype == 'POLYLINE':
            verts = []
            i += 1
            while i < n:
                sub = raw_entities[i]
                stype = sub[0][1] if sub and sub[0][0] == 0 else None
                if stype == 'VERTEX':
                    verts.append(sub)
                    i += 1
                elif stype == 'SEQEND':
                    i += 1
                    break
                else:
                    break
            out.append((ent, 'POLYLINE', verts))
        else:
            out.append((ent, etype, []))
            i += 1
    return out


def _convert_one(ent, etype, sub):
    if etype == 'LINE':
        return _convert_line(ent)
    if etype == 'CIRCLE':
        return _convert_circle(ent)
    if etype == 'ARC':
        return _convert_arc(ent)
    if etype == 'ELLIPSE':
        return _convert_ellipse(ent)
    if etype == 'LWPOLYLINE':
        return _convert_lwpolyline(ent)
    if etype == 'POLYLINE':
        return _convert_polyline(ent, sub)
    if etype == 'SPLINE':
        return _convert_spline(ent)
    return None  # POINT, TEXT, INSERT и пр. — обработаны отдельно/проигнорированы


def _resolve_color(tags, layer_aci):
    """Вернуть HEX-цвет для сущности."""
    tc = _get(tags, 420, None)
    if tc is not None:
        h = truecolor_to_hex(tc)
        if h is not None:
            return h
    aci = _get(tags, 62, None)
    # 256 = BYLAYER, 0 = BYBLOCK — подставляем цвет слоя.
    if aci is None or aci == 256 or aci == 0:
        aci = layer_aci if layer_aci is not None else 7
    try:
        aci = abs(int(aci))
    except (TypeError, ValueError):
        aci = 7
    if aci < 1 or aci > 255:
        aci = 7
    return rgb_to_hex(aci_to_rgb(aci))


# ---------------------------------------------------------------------------
# Применение преобразования INSERT (вставка блока).
# ---------------------------------------------------------------------------

def _apply_insert(insert_tags, blocks):
    """Развернуть INSERT в список синтетических сущностей (tags, etype, sub).
    Поддерживается смещение, масштаб (X, Y) и поворот вокруг точки вставки.
    Это упрощённая реализация — DXF позволяет также строки/столбцы и
    наклонную трансформацию, но для большинства файлов 2D-черчения хватает."""
    name = _get(insert_tags, 2, '')
    if name not in blocks:
        return []
    blk = blocks[name]
    bx, by, _ = blk['base']
    ix = _get(insert_tags, 10, 0.0); iy = _get(insert_tags, 20, 0.0)
    sx = _get(insert_tags, 41, 1.0) or 1.0
    sy = _get(insert_tags, 42, 1.0) or 1.0
    rot = math.radians(_get(insert_tags, 50, 0.0) or 0.0)
    cosA, sinA = math.cos(rot), math.sin(rot)

    def transform(x, y):
        # 1) Сдвиг относительно base_point блока
        x -= bx; y -= by
        # 2) Масштаб
        x *= sx; y *= sy
        # 3) Поворот
        xr = x * cosA - y * sinA
        yr = x * sinA + y * cosA
        # 4) Сдвиг в точку вставки
        return xr + ix, yr + iy

    def transform_tags(tags):
        out = []
        for c, v in tags:
            if c in (10, 11, 12, 13):
                # Парная Y — следующий тег с (c+10)
                pass
            out.append((c, v))
        # Применим преобразование «пост-фактум» через подмену значений
        # координатных пар.
        result = []
        i = 0
        while i < len(out):
            c, v = out[i]
            if c in (10, 11) and i + 1 < len(out) and out[i + 1][0] == c + 10:
                x = float(_coerce(c, v))
                y = float(_coerce(c + 10, out[i + 1][1]))
                nx, ny = transform(x, y)
                result.append((c, str(nx)))
                result.append((c + 10, str(ny)))
                i += 2
                continue
            result.append((c, v))
            i += 1
        return result

    expanded = []
    walked = _walk_entities(blk['entities'])
    for ent, etype, sub in walked:
        if etype == 'INSERT':
            # Рекурсивно разворачиваем вложенные INSERT-ы.
            for sub_ent in _apply_insert(ent, blocks):
                expanded.append(sub_ent)
            continue
        new_ent = transform_tags(ent)
        new_sub = [transform_tags(s) for s in sub]
        # Слой/цвет наследуем от исходной сущности блока, но если в самом
        # блоке слой '0' — заменим его на слой INSERT-а (стандартное
        # поведение DXF).
        ins_layer = _get(insert_tags, 8, None)
        if ins_layer:
            new_ent = [(c, ins_layer if c == 8 and v == '0' else v)
                       for c, v in new_ent]
        expanded.append((new_ent, etype, new_sub))
    return expanded


# ---------------------------------------------------------------------------
# Сборка внутренних стилей по таблицам слоёв и LTYPE.
# ---------------------------------------------------------------------------

def _build_style_for_layer(layer_name, layer_info, ltypes):
    """Имя внутреннего стиля + словарь {'type', 'width'}."""
    ltname = layer_info.get('ltype', 'CONTINUOUS')
    stype = ltype_to_style_type(ltname)
    # Базовое имя — стандартный стиль из ГОСТ-набора, если совпадает по типу.
    base_name = _STYLE_BY_TYPE.get(stype, 'Сплошная основная')
    # Если LTYPE — нестандартный (не CONTINUOUS и не один из узнаваемых
    # имён), создадим уникальный стиль с именем "слой::ltype".
    well_known = ltname.upper() in ('CONTINUOUS', 'DASHED', 'DASHDOT',
                                    'DIVIDE', 'HIDDEN', 'CENTER',
                                    'BYLAYER', 'BYBLOCK', '')
    if well_known:
        return base_name, {'type': stype, 'width': 1.0}
    style_name = f'{layer_name}::{ltname}'[:60]
    return style_name, {'type': stype, 'width': 1.0}


# ---------------------------------------------------------------------------
# Публичная функция импорта.
# ---------------------------------------------------------------------------

def import_from_dxf(filepath):
    """Загрузить DXF-файл и вернуть словарь:

        {
            'primitives':   list[dict],     # как в SegmentApp.primitives
            'line_styles':  dict[name->style],
            'layers':       dict[name->{'aci','ltype','rgb','hex'}],
            'header':       {'acadver','insunits','extmin','extmax'},
            'stats':        {'entities': N, 'skipped': K},
        }

    Не модифицирует файл; единицы измерения сохраняются как у источника."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f'Файл не найден: {filepath}')

    text = _read_text(filepath)
    tags = _tokenize(text)
    sections = _split_sections(tags)

    # --- HEADER
    header_body = sections.get('HEADER', [])
    header = _parse_header(header_body)

    # --- TABLES
    layers, ltypes = _parse_tables(sections.get('TABLES', []))

    # --- BLOCKS
    blocks = _parse_blocks(sections.get('BLOCKS', []))

    # --- ENTITIES
    raw = _split_entities(sections.get('ENTITIES', []))
    walked = _walk_entities(raw)

    # Развернём INSERT-ы.
    flattened = []
    for ent, etype, sub in walked:
        if etype == 'INSERT':
            flattened.extend(_apply_insert(ent, blocks))
        else:
            flattened.append((ent, etype, sub))

    # Соберём набор используемых стилей.
    line_styles = {}
    layer_to_style = {}
    for lname, linfo in layers.items():
        sname, sdef = _build_style_for_layer(lname, linfo, ltypes)
        layer_to_style[lname] = sname
        # Не перетираем уже существующие стили (например, базовые ГОСТ-имена).
        if sname not in line_styles:
            line_styles[sname] = sdef

    # Конвертируем сущности.
    primitives = []
    skipped = 0
    name_counters = {}  # type -> int

    type_label = {
        'segment_mouse': 'Отрезок',
        'polyline':      'Ломаная',
        'circle':        'Окружность',
        'arc':           'Дуга',
        'rect':          'Прямоугольник',
        'polygon':       'Многоугольник',
        'ellipse':       'Эллипс',
        'spline':        'Сплайн',
    }

    # --- Сайдкар с описаниями размеров (если есть)
    sidecar_dims = _read_dim_sidecar(filepath)
    skip_dim_layer = bool(sidecar_dims)

    for ent, etype, sub in flattened:
        layer_name = _get(ent, 8, '0') or '0'
        # Если есть сайдкар — геометрию слоя «Размеры» пропускаем (она
        # будет восстановлена из сайдкара как редактируемые размеры).
        if skip_dim_layer and layer_name == DIMENSIONS_LAYER:
            skipped += 1
            continue
        prim = _convert_one(ent, etype, sub)
        if prim is None:
            skipped += 1
            continue
        layer_info = layers.get(layer_name, {'aci': 7, 'ltype': 'CONTINUOUS'})
        color_hex = _resolve_color(ent, layer_info.get('aci', 7))
        style_name = layer_to_style.get(layer_name, 'Сплошная основная')
        # Если стиля нет в финальном словаре — добавим.
        if style_name not in line_styles:
            stype = ltype_to_style_type(layer_info.get('ltype', 'CONTINUOUS'))
            line_styles[style_name] = {'type': stype, 'width': 1.0}
        prim['color'] = color_hex
        prim['style_name'] = style_name
        kind = prim['type']
        name_counters[kind] = name_counters.get(kind, 0) + 1
        prim['name'] = f"{type_label.get(kind, kind)} {name_counters[kind]}"
        primitives.append(prim)

    # --- Восстановление размеров из сайдкара
    for d in sidecar_dims:
        primitives.append({
            'type':       d['type'],
            'name':       d.get('name', d['type']),
            'color':      d.get('color', '#FFFFFF'),
            'style_name': d.get('style_name', 'Сплошная тонкая'),
            'params':     d['params'],
        })

    # Дополним layers HEX-цветом.
    for lname, info in layers.items():
        info['rgb'] = aci_to_rgb(info.get('aci', 7))
        info['hex'] = rgb_to_hex(info['rgb'])

    return {
        'primitives':  primitives,
        'line_styles': line_styles,
        'layers':      layers,
        'header':      header,
        'stats':       {'entities': len(primitives), 'skipped': skipped},
    }


# ---------------------------------------------------------------------------
# Сайдкар-файл с описаниями размеров.
# ---------------------------------------------------------------------------

def _read_dim_sidecar(dxf_path):
    """Читает <dxf>.dim.json (если существует) и возвращает список размеров.
    Файл создаётся dxf_export'ом и хранит исходные параметры размеров для
    восстановления редактируемых объектов внутри нашего приложения.
    Другие CAD-программы файл игнорируют."""
    base, _ = os.path.splitext(dxf_path)
    sidecar = base + '.dim.json'
    if not os.path.isfile(sidecar):
        return []
    try:
        with open(sidecar, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    if payload.get('format') != 'geomod-dimensions':
        return []
    dims = payload.get('dimensions') or []
    out = []
    for d in dims:
        if not isinstance(d, dict) or 'type' not in d or 'params' not in d:
            continue
        # Кортежи в JSON сериализуются как списки — конвертируем обратно
        params = _restore_param_tuples(d['params'])
        out.append({
            'type':       d['type'],
            'name':       d.get('name', d['type']),
            'color':      d.get('color', '#FFFFFF'),
            'style_name': d.get('style_name', 'Сплошная тонкая'),
            'params':     params,
        })
    return out


def _restore_param_tuples(params):
    """Превращает 2-элементные списки координат обратно в кортежи."""
    result = {}
    for k, v in params.items():
        if isinstance(v, list) and len(v) == 2 and \
                all(isinstance(c, (int, float)) for c in v):
            result[k] = (float(v[0]), float(v[1]))
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# HEADER.
# ---------------------------------------------------------------------------

def _parse_header(body):
    """HEADER хранит переменные как пары: (9, $NAME) затем значение."""
    out = {'acadver': None, 'insunits': None,
           'extmin': None, 'extmax': None}
    i = 0
    n = len(body)
    while i < n:
        c, v = body[i]
        if c == 9:
            name = v
            # Считываем все теги до следующего c==9.
            vals = []
            i += 1
            while i < n and body[i][0] != 9:
                vals.append(body[i])
                i += 1
            if name == '$ACADVER' and vals:
                out['acadver'] = vals[0][1]
            elif name == '$INSUNITS' and vals:
                try:
                    out['insunits'] = int(vals[0][1])
                except ValueError:
                    pass
            elif name == '$EXTMIN':
                x = next((float(_coerce(c2, v2)) for c2, v2 in vals if c2 == 10), 0.0)
                y = next((float(_coerce(c2, v2)) for c2, v2 in vals if c2 == 20), 0.0)
                out['extmin'] = (x, y)
            elif name == '$EXTMAX':
                x = next((float(_coerce(c2, v2)) for c2, v2 in vals if c2 == 10), 0.0)
                y = next((float(_coerce(c2, v2)) for c2, v2 in vals if c2 == 20), 0.0)
                out['extmax'] = (x, y)
        else:
            i += 1
    return out
