import tkinter as tk
from tkinter import ttk, colorchooser, Menu, messagebox, simpledialog, filedialog
import math
import os

from dxf_export import export_to_dxf
from dxf_import import import_from_dxf
from dimensions import (LinearDimension, RadialDimension, AngularDimension,
                        make_dimension, is_dimension_type, arrow_polygon)

class SegmentApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Построение отрезков в координатных системах")
        self.root.geometry("1400x900")
        
        # Параметры
        self.coord_system = "cartesian"
        self.angle_unit = "degrees"
        self.grid_step = 50
        self.segment_color = "#00D4FF"
        self.prim_default_color = "#00D4FF"  # default color for new primitives
        self.bg_color = "#0D1117"
        self.grid_color = "#1E2A38"

        # === DARK THEME PALETTE ===
        self.T = {
            'bg':        '#0D1117',   # main background
            'panel':     '#111820',   # side panel bg
            'panel2':    '#162030',   # card/section bg
            'border':    '#1E3050',   # borders / dividers
            'accent':    '#00D4FF',   # primary cyan accent
            'accent2':   '#FF8C00',   # secondary amber accent
            'accent3':   '#00FF88',   # tertiary green
            'text':      '#C8D8E8',   # primary text
            'text_dim':  '#5A7A98',   # dimmed text
            'btn_hover': '#1E3A55',   # button hover
            'danger':    '#FF3B30',   # danger/delete
            'warn':      '#FF8C00',   # warning
            'success':   '#00FF88',   # success
            'entry_bg':  '#0A1520',   # entry field bg
            'select':    '#003D5C',   # listbox selection
        }
        
        # Стили линий по ГОСТ 2.303-68
        self.line_styles = {
            'Сплошная основная': {'type': 'solid', 'width': 2.0},
            'Сплошная тонкая': {'type': 'solid', 'width': 1.0},
            'Сплошная волнистая': {'type': 'wavy', 'width': 1.0, 'amplitude': 2, 'period': 10},
            'Штриховая': {'type': 'dashed', 'width': 1.0, 'dash': (10, 5)},
            'Штрихпунктирная утолщенная': {'type': 'dashdot', 'width': 2.0, 'dash': (10, 5, 2, 5)},
            'Штрихпунктирная тонкая': {'type': 'dashdot', 'width': 1.0, 'dash': (10, 5, 2, 5)},
            'Штрихпунктирная с двумя точками': {'type': 'dashdotdot', 'width': 1.0, 'dash': (10, 5, 2, 5, 2, 5)},
            'Сплошная тонкая с изломами': {'type': 'zigzag', 'width': 1.0, 'amplitude': 2, 'period': 10},
        }
        self.base_styles = list(self.line_styles.keys())
        self.current_style = 'Сплошная основная'
        
        # Список отрезков
        self.segments = []
        self.point1 = None
        self.point2 = None
        
        # Список примитивов САПР
        self.primitives = []  # список {type, params, color, style_name, name, id}
        self._next_prim_id = 1

        # Параметры размеров по умолчанию (ЕСКД ГОСТ 2.307-2011)
        self.dim_defaults = dict(
            arrow_size    = 0.30,
            text_height   = 0.35,
            ext_overshoot = 0.15,
            ext_offset    = 0.05,
            dim_extension = 0.00,
            precision     = 2,
            arrow_filled  = True,
            text_color    = '#FFFFFF',
            line_color    = '#FFFFFF',
            ext_style     = 'Сплошная тонкая',
            dim_style     = 'Сплошная тонкая',
        )
        
        # Привязки
        self.snap_enabled = True
        self.snap_modes = {"end": True, "mid": True, "center": True,
                           "intersect": False, "perp": False, "tangent": False}
        self.snap_radius = 12  # px
        self.snap_point = None   # текущая точка привязки (world coords)
        self.snap_label = ""
        self.snap_ref = None     # ассоц. ссылка на исходный примитив: {'prim_id', 'src_key'}
        
        # Состояние создания примитива
        self.current_prim_tool = None   # 'circle', 'arc', 'rect', 'ellipse', 'polygon', 'spline'
        self.prim_creation_step = 0
        self.prim_points = []           # накопленные мировые точки
        self.prim_preview = []          # id объектов превью на холсте
        self.creation_mode = {}         # доп. режимы: {'circle_method': 'center_radius', ...}
        
        # Выбранный примитив для редактирования
        self.selected_prim_idx = None
        self.drag_ctrl_pt = None        # {idx, pt_key} для перетаскивания
        self.prim_prop_vars = {}        # переменные полей свойств примитива
        
        # Параметры навигации (аффинные преобразования)
        self.pan_x = 0  # Сдвиг по X
        self.pan_y = 0  # Сдвиг по Y
        self.scale = 1.0  # Масштаб
        self.rotation = 0.0  # Угол поворота в радианах
        
        # Параметры взаимодействия
        self.active_tool = "select"  # select, pan, zoom_in, zoom_out
        self.pan_active = False  # Флаг для режима панорамирования с ЛКМ
        self.pan_start = None
        self.mouse_world_coords = (0, 0)
        
        self.create_menu()
        self.create_ui()
        self.bind_shortcuts()
        
    def create_menu(self):
        """Создание главного меню"""
        T = self.T
        menubar = Menu(self.root, bg=T['panel'], fg=T['text'],
                       activebackground=T['select'], activeforeground=T['accent'],
                       relief='flat', borderwidth=0)
        self.root.config(menu=menubar)

        def dark_menu():
            return Menu(menubar, tearoff=0, bg=T['panel2'], fg=T['text'],
                        activebackground=T['select'], activeforeground=T['accent'],
                        relief='flat', borderwidth=1)

        file_menu = dark_menu()
        menubar.add_cascade(label="  ФАЙЛ  ", menu=file_menu)
        file_menu.add_command(label="Импорт из DXF…", command=self.import_dxf,
                              accelerator="Ctrl+I")
        file_menu.add_command(label="Экспорт в DXF…", command=self.export_dxf,
                              accelerator="Ctrl+E")

        view_menu = dark_menu()
        menubar.add_cascade(label="  ВИД  ", menu=view_menu)
        view_menu.add_command(label="Увеличить (+)", command=self.zoom_in, accelerator="Ctrl++")
        view_menu.add_command(label="Уменьшить (-)", command=self.zoom_out, accelerator="Ctrl+-")
        view_menu.add_command(label="Показать весь чертёж", command=self.fit_all, accelerator="Ctrl+0")
        view_menu.add_separator()
        view_menu.add_command(label="Повернуть влево", command=self.rotate_left, accelerator="Ctrl+L")
        view_menu.add_command(label="Повернуть вправо", command=self.rotate_right, accelerator="Ctrl+R")
        view_menu.add_separator()
        view_menu.add_command(label="Сбросить вид", command=self.reset_view, accelerator="Ctrl+H")
        
    def create_ui(self):
        T = self.T
        FONT_MONO  = ("Consolas", 9)
        FONT_LABEL = ("Consolas", 8)
        FONT_HEAD  = ("Consolas", 9, "bold")
        FONT_TITLE = ("Consolas", 10, "bold")

        # --- configure ttk style for dark comboboxes ---
        style = ttk.Style()
        style.theme_use('default')
        style.configure('Dark.TCombobox',
            fieldbackground=T['entry_bg'],
            background=T['panel2'],
            foreground=T['accent'],
            selectbackground=T['select'],
            selectforeground=T['accent'],
            arrowcolor=T['accent'],
            bordercolor=T['border'],
            lightcolor=T['border'],
            darkcolor=T['border'])
        style.map('Dark.TCombobox',
            fieldbackground=[('readonly', T['entry_bg'])],
            foreground=[('readonly', T['accent'])],
            selectbackground=[('readonly', T['select'])])

        # ---------- helpers ----------
        def mk_btn(parent, text, cmd, color=None, text_color=None, **kw):
            bg = color or T['panel2']
            fg = text_color or T['accent']
            b = tk.Button(parent, text=text, command=cmd,
                          bg=bg, fg=fg, activebackground=T['btn_hover'],
                          activeforeground=T['accent'],
                          font=FONT_MONO, relief='flat', bd=0,
                          cursor='hand2', padx=6, pady=4, **kw)
            b.bind('<Enter>', lambda e: b.config(bg=T['btn_hover']))
            b.bind('<Leave>', lambda e: b.config(bg=bg))
            return b

        def mk_section(parent, title):
            # top border stripe
            tk.Frame(parent, bg=T['accent'], height=1).pack(fill=tk.X, padx=6, pady=(10, 0))
            header = tk.Frame(parent, bg=T['panel2'])
            header.pack(fill=tk.X, padx=6)
            tk.Label(header, text=f" {title} ", bg=T['panel2'], fg=T['accent'],
                     font=FONT_TITLE, anchor='w').pack(side=tk.LEFT)
            body = tk.Frame(parent, bg=T['panel2'])
            body.pack(fill=tk.X, padx=6, pady=(0, 4))
            return body

        def mk_label(parent, text, **kw):
            return tk.Label(parent, text=text, bg=T['panel2'], fg=T['text_dim'],
                            font=FONT_LABEL, **kw)

        def mk_entry(parent, width=10):
            e = tk.Entry(parent, width=width,
                         bg=T['entry_bg'], fg=T['accent'],
                         insertbackground=T['accent'],
                         relief='flat', font=FONT_MONO,
                         highlightthickness=1,
                         highlightbackground=T['border'],
                         highlightcolor=T['accent'])
            return e

        def mk_radio(parent, text, variable, value, command=None):
            r = tk.Radiobutton(parent, text=text, variable=variable, value=value,
                               bg=T['panel2'], fg=T['text'], selectcolor=T['select'],
                               activebackground=T['btn_hover'], activeforeground=T['accent'],
                               font=FONT_MONO, relief='flat', bd=0,
                               indicatoron=1, command=command)
            return r

        def mk_check(parent, text, variable, command=None):
            c = tk.Checkbutton(parent, text=text, variable=variable,
                               bg=T['panel2'], fg=T['text'],
                               selectcolor=T['select'],
                               activebackground=T['btn_hover'], activeforeground=T['accent'],
                               font=FONT_LABEL, relief='flat', bd=0,
                               command=command)
            return c

        def mk_listbox(parent, height=5):
            lb = tk.Listbox(parent, height=height,
                            bg=T['entry_bg'], fg=T['text'],
                            selectbackground=T['select'], selectforeground=T['accent'],
                            font=FONT_MONO, relief='flat', bd=0,
                            highlightthickness=1,
                            highlightbackground=T['border'],
                            activestyle='none')
            return lb

        def mk_combobox(parent, **kw):
            cb = ttk.Combobox(parent, style='Dark.TCombobox', font=FONT_MONO, **kw)
            return cb

        # ===== ROOT STYLING =====
        self.root.config(bg=T['bg'])

        # ===== STATUS BAR (bottom) =====
        status_frame = tk.Frame(self.root, bg=T['panel'], height=24,
                                highlightthickness=1, highlightbackground=T['border'])
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        status_frame.pack_propagate(False)

        sep_kw = dict(bg=T['border'], width=1)
        dot = lambda p: tk.Frame(p, **sep_kw).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=3)

        self.status_coords = tk.Label(status_frame, text="XY  0.00, 0.00",
                                      bg=T['panel'], fg=T['accent'], font=FONT_MONO,
                                      anchor=tk.W, width=22)
        self.status_coords.pack(side=tk.LEFT, padx=(8,0))
        dot(status_frame)
        self.status_scale = tk.Label(status_frame, text="ZOOM 100%",
                                     bg=T['panel'], fg=T['text_dim'], font=FONT_MONO, width=14)
        self.status_scale.pack(side=tk.LEFT)
        dot(status_frame)
        self.status_rotation = tk.Label(status_frame, text="ROT  0.0°",
                                        bg=T['panel'], fg=T['text_dim'], font=FONT_MONO, width=12)
        self.status_rotation.pack(side=tk.LEFT)
        dot(status_frame)
        self.status_tool = tk.Label(status_frame, text="TOOL  Выбор",
                                    bg=T['panel'], fg=T['text_dim'], font=FONT_MONO, width=22)
        self.status_tool.pack(side=tk.LEFT)

        # ===== MAIN LAYOUT =====
        main_container = tk.Frame(self.root, bg=T['bg'])
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # ===== LEFT PANEL =====
        left_panel_container = tk.Frame(main_container, width=300, bg=T['panel'],
                                        highlightthickness=1, highlightbackground=T['border'])
        left_panel_container.pack(side=tk.LEFT, fill=tk.Y, padx=(6,0), pady=6)
        left_panel_container.pack_propagate(False)

        # App title strip at top of panel
        title_strip = tk.Frame(left_panel_container, bg=T['bg'], height=38)
        title_strip.pack(fill=tk.X)
        title_strip.pack_propagate(False)
        tk.Label(title_strip, text="⬡  CAD WORKBENCH", bg=T['bg'], fg=T['accent'],
                 font=("Consolas", 11, "bold"), anchor='w').pack(side=tk.LEFT, padx=10, pady=6)

        # Scrollable inner canvas
        left_canvas = tk.Canvas(left_panel_container, bg=T['panel'], highlightthickness=0)
        scrollbar = tk.Scrollbar(left_panel_container, orient="vertical",
                                 command=left_canvas.yview,
                                 bg=T['panel2'], troughcolor=T['bg'],
                                 activebackground=T['accent'], relief='flat')
        left_panel = tk.Frame(left_canvas, bg=T['panel'])
        canvas_window = left_canvas.create_window((0, 0), window=left_panel, anchor="nw")

        def configure_scroll_region(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            canvas_width = left_panel_container.winfo_width() - scrollbar.winfo_width()
            left_canvas.itemconfig(canvas_window, width=max(canvas_width, 1))

        left_panel.bind("<Configure>", configure_scroll_region)
        left_panel_container.bind("<Configure>", configure_scroll_region)
        left_canvas.configure(yscrollcommand=scrollbar.set)

        def on_left_panel_mousewheel(event):
            left_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            return "break"

        for widget in [left_canvas, left_panel]:
            widget.bind("<MouseWheel>", on_left_panel_mousewheel)
            widget.bind("<Button-4>", lambda e: left_canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda e: left_canvas.yview_scroll(1, "units"))

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # ===== RIGHT PANEL =====
        right_panel = tk.Frame(main_container, bg=T['bg'])
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ===== SECTION: TOOLS =====
        body = mk_section(left_panel, "ИНСТРУМЕНТЫ")

        # Build segment button — primary action
        mk_btn(body, "  ✏  ПОСТРОИТЬ ОТРЕЗОК",
               self.build_segment, color=T['accent'], text_color=T['bg']).pack(fill=tk.X, padx=4, pady=(6,2))

        row = tk.Frame(body, bg=T['panel2'])
        row.pack(fill=tk.X, padx=4, pady=2)
        mk_btn(row, "↩ Удалить посл.", self.delete_last_primitive,
               color=T['panel'], text_color=T['warn']).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        mk_btn(row, "✕ Удалить все", self.delete_all_primitives,
               color=T['panel'], text_color=T['danger']).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Navigation sub-section
        tk.Frame(body, bg=T['border'], height=1).pack(fill=tk.X, padx=4, pady=(8, 4))
        tk.Label(body, text="НАВИГАЦИЯ", bg=T['panel2'], fg=T['text_dim'],
                 font=("Consolas", 7, "bold")).pack(anchor='w', padx=4)

        self.tool_var = tk.StringVar(value="select")
        nav_frame = tk.Frame(body, bg=T['panel2'])
        nav_frame.pack(fill=tk.X, padx=4, pady=2)

        nav_btn_cfg = dict(variable=self.tool_var, bg=T['panel'],
                           fg=T['text'], selectcolor=T['select'],
                           activebackground=T['btn_hover'], activeforeground=T['accent'],
                           font=FONT_MONO, relief='flat', bd=0, indicatoron=0)
        self.pan_button = tk.Radiobutton(nav_frame, text="✋", value="pan",
                                          command=self.toggle_pan_mode, **nav_btn_cfg)
        self.pan_button.pack(side=tk.LEFT, padx=1, ipadx=8, ipady=3)
        tk.Radiobutton(nav_frame, text="🔍+", value="zoom_in",
                       command=self.change_tool, **nav_btn_cfg).pack(side=tk.LEFT, padx=1, ipadx=8, ipady=3)
        tk.Radiobutton(nav_frame, text="🔍-", value="zoom_out",
                       command=self.change_tool, **nav_btn_cfg).pack(side=tk.LEFT, padx=1, ipadx=8, ipady=3)

        zoom_row = tk.Frame(body, bg=T['panel2'])
        zoom_row.pack(fill=tk.X, padx=4, pady=2)
        mk_btn(zoom_row, "+ Увеличить", self.zoom_in).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        mk_btn(zoom_row, "− Уменьшить", self.zoom_out).pack(side=tk.LEFT, fill=tk.X, expand=True)

        mk_btn(body, "⊞ Показать всё", self.fit_all, color=T['panel'],
               text_color=T['accent3']).pack(fill=tk.X, padx=4, pady=2)

        rot_row = tk.Frame(body, bg=T['panel2'])
        rot_row.pack(fill=tk.X, padx=4, pady=2)
        mk_btn(rot_row, "↶ Влево", self.rotate_left, color=T['panel'],
               text_color=T['accent2']).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        mk_btn(rot_row, "↷ Вправо", self.rotate_right, color=T['panel'],
               text_color=T['accent2']).pack(side=tk.LEFT, fill=tk.X, expand=True)

        mk_btn(body, "⟲ Сбросить вид", self.reset_view, color=T['panel'],
               text_color=T['text_dim']).pack(fill=tk.X, padx=4, pady=(2,6))
        
        # ===== SECTION: SETTINGS =====
        body = mk_section(left_panel, "НАСТРОЙКИ")

        mk_label(body, "Система координат:").pack(anchor='w', padx=4, pady=(4,0))
        coord_frame = tk.Frame(body, bg=T['panel2'])
        coord_frame.pack(fill=tk.X, padx=4, pady=2)
        self.coord_var = tk.StringVar(value="cartesian")
        mk_radio(coord_frame, "Декартова", self.coord_var, "cartesian",
                 self.update_coord_system).pack(side=tk.LEFT, padx=(0,8))
        mk_radio(coord_frame, "Полярная", self.coord_var, "polar",
                 self.update_coord_system).pack(side=tk.LEFT)

        mk_label(body, "Единицы углов:").pack(anchor='w', padx=4, pady=(4,0))
        angle_frame = tk.Frame(body, bg=T['panel2'])
        angle_frame.pack(fill=tk.X, padx=4, pady=2)
        self.angle_var = tk.StringVar(value="degrees")
        mk_radio(angle_frame, "Градусы", self.angle_var, "degrees").pack(side=tk.LEFT, padx=(0,8))
        mk_radio(angle_frame, "Радианы", self.angle_var, "radians").pack(side=tk.LEFT)

        mk_label(body, "Шаг сетки:").pack(anchor='w', padx=4, pady=(4,0))
        grid_row = tk.Frame(body, bg=T['panel2'])
        grid_row.pack(fill=tk.X, padx=4, pady=2)
        self.grid_entry = mk_entry(grid_row, width=8)
        self.grid_entry.insert(0, str(self.grid_step))
        self.grid_entry.pack(side=tk.LEFT, padx=(0,4))
        mk_btn(grid_row, "Применить", self.update_grid_step).pack(side=tk.LEFT)

        mk_label(body, "Цвета:").pack(anchor='w', padx=4, pady=(6,0))
        color_row1 = tk.Frame(body, bg=T['panel2'])
        color_row1.pack(fill=tk.X, padx=4, pady=2)
        mk_btn(color_row1, "Цвет отрезка",
               lambda: self.choose_color("segment")).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        mk_btn(color_row1, "Цвет фона",
               lambda: self.choose_color("bg")).pack(side=tk.LEFT, fill=tk.X, expand=True)
        mk_btn(body, "Цвет сетки",
               lambda: self.choose_color("grid")).pack(fill=tk.X, padx=4, pady=(0,2))

        mk_label(body, "Стиль линии:").pack(anchor='w', padx=4, pady=(4,0))
        self.current_style_var = tk.StringVar(value=self.current_style)
        self.current_style_combo = mk_combobox(body, textvariable=self.current_style_var,
                                               values=sorted(self.line_styles.keys()), state="readonly")
        self.current_style_combo.pack(fill=tk.X, padx=4, pady=(2,6))
        self.current_style_combo.bind("<<ComboboxSelected>>", lambda e: self.set_current_style())
        
        # ===== SECTION: COORDINATES =====
        body = mk_section(left_panel, "КООРДИНАТЫ ТОЧЕК")

        coords_grid = tk.Frame(body, bg=T['panel2'])
        coords_grid.pack(fill=tk.X, padx=4, pady=6)

        mk_label(coords_grid, "x₁").grid(row=0, column=0, sticky='w', padx=(0,4), pady=2)
        self.x1_entry = mk_entry(coords_grid, width=10)
        self.x1_entry.grid(row=0, column=1, padx=(0,10), pady=2, sticky='w')
        mk_label(coords_grid, "y₁").grid(row=1, column=0, sticky='w', padx=(0,4), pady=2)
        self.y1_entry = mk_entry(coords_grid, width=10)
        self.y1_entry.grid(row=1, column=1, padx=(0,10), pady=2, sticky='w')

        tk.Frame(coords_grid, bg=T['border'], width=1).grid(row=0, column=2, rowspan=4, padx=4, sticky='ns')

        self.x2_label = mk_label(coords_grid, "x₂")
        self.x2_label.grid(row=0, column=3, sticky='w', padx=(4,4), pady=2)
        self.x2_entry = mk_entry(coords_grid, width=10)
        self.x2_entry.grid(row=0, column=4, pady=2, sticky='w')
        self.y2_label = mk_label(coords_grid, "y₂")
        self.y2_label.grid(row=1, column=3, sticky='w', padx=(4,4), pady=2)
        self.y2_entry = mk_entry(coords_grid, width=10)
        self.y2_entry.grid(row=1, column=4, pady=2, sticky='w')
        
        # hidden compat widgets (not displayed)
        hidden = tk.Frame(left_panel)
        self.segments_listbox = tk.Listbox(hidden)
        self.selected_style_button = tk.Button(hidden, text="Сплошная основная")
        self.selected_name_entry = tk.Entry(hidden)
        
        # ===== SECTION: STYLES =====
        body = mk_section(left_panel, "УПРАВЛЕНИЕ СТИЛЯМИ")

        self.styles_listbox = mk_listbox(body, height=4)
        self.styles_listbox.pack(fill=tk.X, padx=4, pady=(4,2))
        self.styles_listbox.bind("<<ListboxSelect>>", self.on_style_select)

        style_btns = tk.Frame(body, bg=T['panel2'])
        style_btns.pack(fill=tk.X, padx=4, pady=2)
        mk_btn(style_btns, "Новый", self.new_style).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        mk_btn(style_btns, "Редакт.", self.edit_style).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        mk_btn(style_btns, "Удалить", self.delete_style, color=T['panel'],
               text_color=T['danger']).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.style_preview = tk.Canvas(body, height=28, bg=T['entry_bg'],
                                        highlightthickness=1, highlightbackground=T['border'])
        self.style_preview.pack(fill=tk.X, padx=4, pady=4)

        edit_style_frame = tk.Frame(body, bg=T['panel2'])
        edit_style_frame.pack(fill=tk.X, padx=4, pady=2)
        edit_style_frame.columnconfigure(1, weight=1)

        for i, (lbl, attr) in enumerate([("Имя:", None), ("Тип:", None),
                                           ("Толщина:", None), ("Паттерн:", None)]):
            mk_label(edit_style_frame, lbl).grid(row=i, column=0, sticky='w', pady=1)

        self.style_name_entry = mk_entry(edit_style_frame)
        self.style_name_entry.grid(row=0, column=1, sticky='ew', padx=(4,0), pady=1)

        self.style_type_var = tk.StringVar()
        self.style_type_combo = mk_combobox(edit_style_frame, textvariable=self.style_type_var,
                                             values=['solid','dashed','dashdot','dashdotdot','wavy','zigzag'],
                                             state="readonly")
        self.style_type_combo.grid(row=1, column=1, sticky='ew', padx=(4,0), pady=1)
        self.style_type_combo.bind("<<ComboboxSelected>>", self.update_pattern_label)

        self.style_width_entry = mk_entry(edit_style_frame)
        self.style_width_entry.grid(row=2, column=1, sticky='ew', padx=(4,0), pady=1)

        self.style_pattern_label = mk_label(edit_style_frame, "Паттерн:")
        self.style_pattern_label.grid(row=3, column=0, sticky='w', pady=1)
        self.style_pattern_entry = mk_entry(edit_style_frame)
        self.style_pattern_entry.grid(row=3, column=1, sticky='ew', padx=(4,0), pady=1)

        mk_btn(edit_style_frame, "✔ Применить стиль", self.apply_style_changes,
               color=T['accent'], text_color=T['bg']).grid(row=4, column=0, columnspan=2,
                                                             sticky='ew', pady=(4,4))
        
        # ===== SECTION: CAD PRIMITIVES =====
        body = mk_section(left_panel, "ПРИМИТИВЫ САПР")

        self.prim_tool_var = tk.StringVar(value="")
        prim_buttons_data = [
            ("📏  Отрезок (мышь)",   "segment_mouse"),
            ("〰  Ломаная линия",    "polyline"),
            ("⭕  Окружность",       "circle"),
            ("🌙  Дуга",             "arc"),
            ("▭  Прямоугольник",    "rect"),
            ("⬭  Эллипс",           "ellipse"),
            ("⬡  Многоугольник",    "polygon"),
            ("〜  Сплайн",           "spline"),
        ]
        # 2-column grid of radio-buttons styled as toggles
        prim_grid = tk.Frame(body, bg=T['panel2'])
        prim_grid.pack(fill=tk.X, padx=4, pady=(4,2))
        for idx, (txt, val) in enumerate(prim_buttons_data):
            r = idx // 2
            c = idx % 2
            rb = tk.Radiobutton(prim_grid, text=txt, variable=self.prim_tool_var,
                                value=val, bg=T['panel'], fg=T['text'],
                                selectcolor=T['select'],
                                activebackground=T['btn_hover'],
                                activeforeground=T['accent'],
                                font=FONT_MONO, relief='flat', bd=0,
                                indicatoron=0, anchor='w',
                                command=lambda v=val: self.activate_prim_tool(v))
            rb.grid(row=r, column=c, padx=2, pady=1, sticky='ew', ipadx=4, ipady=3)
        prim_grid.columnconfigure(0, weight=1)
        prim_grid.columnconfigure(1, weight=1)

        mk_btn(body, "✕  Отменить создание", self.cancel_prim_creation,
               color=T['panel'], text_color=T['warn']).pack(fill=tk.X, padx=4, pady=(2,4))

        # ---- Размеры по ЕСКД ГОСТ 2.307-2011 ----
        tk.Frame(body, bg=T['border'], height=1).pack(fill=tk.X, padx=4, pady=(2,4))
        tk.Label(body, text="РАЗМЕРЫ (ЕСКД 2.307)", bg=T['panel2'], fg=T['text_dim'],
                 font=("Consolas", 7, "bold")).pack(anchor='w', padx=4)
        dim_buttons_data = [
            ("📏  Линейный",  "dim_linear"),
            ("⌖  Радиус",     "dim_radial_r"),
            ("⌀  Диаметр",   "dim_radial_d"),
            ("∠  Угловой",   "dim_angular"),
        ]
        dim_grid = tk.Frame(body, bg=T['panel2'])
        dim_grid.pack(fill=tk.X, padx=4, pady=(2,4))
        for idx, (txt, val) in enumerate(dim_buttons_data):
            r = idx // 2
            c = idx % 2
            rb = tk.Radiobutton(dim_grid, text=txt, variable=self.prim_tool_var,
                                value=val, bg=T['panel'], fg=T['accent2'],
                                selectcolor=T['select'],
                                activebackground=T['btn_hover'],
                                activeforeground=T['accent'],
                                font=FONT_MONO, relief='flat', bd=0,
                                indicatoron=0, anchor='w',
                                command=lambda v=val: self.activate_prim_tool(v))
            rb.grid(row=r, column=c, padx=2, pady=1, sticky='ew', ipadx=4, ipady=3)
        dim_grid.columnconfigure(0, weight=1)
        dim_grid.columnconfigure(1, weight=1)

        mk_label(body, "Метод:").pack(anchor='w', padx=4)
        self.prim_method_label = mk_label(body, "Метод:")
        # (already packed above, hide duplicate – reuse label from below)
        self.prim_method_var = tk.StringVar(value="")
        self.prim_method_combo = mk_combobox(body, textvariable=self.prim_method_var, state="readonly")
        self.prim_method_combo.pack(fill=tk.X, padx=4, pady=(0,4))
        self.prim_method_combo.bind("<<ComboboxSelected>>", self.on_prim_method_change)

        # Snap section
        tk.Frame(body, bg=T['border'], height=1).pack(fill=tk.X, padx=4, pady=4)
        tk.Label(body, text="ПРИВЯЗКИ", bg=T['panel2'], fg=T['text_dim'],
                 font=("Consolas", 7, "bold")).pack(anchor='w', padx=4)

        self.snap_enabled_var = tk.BooleanVar(value=True)
        mk_check(body, "Привязки включены", self.snap_enabled_var,
                 self.toggle_snap).pack(anchor='w', padx=4, pady=2)

        snap_modes_data = [
            ("Конец",       "end"),   ("Середина",    "mid"),
            ("Центр",       "center"),("Пересечение", "intersect"),
            ("Перпендикуляр","perp"), ("Касательная", "tangent"),
        ]
        snap_grid = tk.Frame(body, bg=T['panel2'])
        snap_grid.pack(fill=tk.X, padx=4, pady=2)
        self.snap_mode_vars = {}
        for idx, (label, key) in enumerate(snap_modes_data):
            var = tk.BooleanVar(value=self.snap_modes[key])
            self.snap_mode_vars[key] = var
            r, c = idx // 2, idx % 2
            mk_check(snap_grid, label, var,
                     lambda k=key, v=var: self.set_snap_mode(k, v)
                     ).grid(row=r, column=c, sticky='w', padx=(4,0))
        snap_grid.columnconfigure(0, weight=1)
        snap_grid.columnconfigure(1, weight=1)

        self.prim_hint_label = tk.Label(body, text="Выберите инструмент",
                                         bg=T['panel2'], fg=T['text_dim'],
                                         font=("Consolas", 7, "italic"),
                                         wraplength=260, justify='left')
        self.prim_hint_label.pack(fill=tk.X, padx=4, pady=(2,6))
        
        # ===== SECTION: PRIMITIVES LIST =====
        body = mk_section(left_panel, "СПИСОК ПРИМИТИВОВ")

        self.prims_listbox = mk_listbox(body, height=5)
        self.prims_listbox.pack(fill=tk.X, padx=4, pady=(4,2))
        self.prims_listbox.bind("<<ListboxSelect>>", self.on_prim_select)

        plist_btns = tk.Frame(body, bg=T['panel2'])
        plist_btns.pack(fill=tk.X, padx=4, pady=(2,6))
        mk_btn(plist_btns, "Удалить", self.delete_selected_prim,
               color=T['panel'], text_color=T['danger']).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,2))
        mk_btn(plist_btns, "Дублировать", self.duplicate_prim).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # ===== SECTION: PRIMITIVE PROPERTIES =====
        body = mk_section(left_panel, "СВОЙСТВА ПРИМИТИВА")

        self.prim_props_inner = tk.Frame(body, bg=T['panel2'])
        self.prim_props_inner.pack(fill=tk.X, padx=4, pady=4)

        mk_label(body, "Стиль линии:").pack(anchor='w', padx=4)
        self.prim_style_var = tk.StringVar(value=self.current_style)
        self.prim_style_combo = mk_combobox(body, textvariable=self.prim_style_var,
                                              values=sorted(self.line_styles.keys()), state="readonly")
        self.prim_style_combo.pack(fill=tk.X, padx=4, pady=2)

        mk_label(body, "Цвет:").pack(anchor='w', padx=4)
        self.prim_color_btn = mk_btn(body, "■  Выбрать цвет", self.change_prim_color)
        self.prim_color_btn.pack(fill=tk.X, padx=4, pady=2)

        mk_btn(body, "✔  Применить изменения", self.apply_prim_props,
               color=T['accent'], text_color=T['bg']).pack(fill=tk.X, padx=4, pady=(2,6))

        # need to expose this as attribute since original code references it
        self.prim_props_frame = body

        # ===== CANVAS AREA =====
        canvas_wrapper = tk.Frame(right_panel, bg=T['border'], bd=1)
        canvas_wrapper.pack(fill=tk.BOTH, expand=True, pady=(0,4))

        self.canvas = tk.Canvas(canvas_wrapper, bg=self.bg_color,
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # Canvas event bindings
        self.canvas.bind("<Button-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self.on_pan_end)
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)
        self.root.bind("<Escape>", lambda e: self.cancel_prim_creation())

        def canvas_mousewheel(event):
            factor = 1.1 if event.delta > 0 else 0.9091
            self.zoom_at_point(event.x, event.y, factor)
            return "break"

        self.canvas.bind("<MouseWheel>", canvas_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self.zoom_at_point(e.x, e.y, 1.1))
        self.canvas.bind("<Button-5>", lambda e: self.zoom_at_point(e.x, e.y, 0.9091))

        self.context_menu = Menu(self.canvas, tearoff=0,
                                  bg=T['panel2'], fg=T['text'],
                                  activebackground=T['select'], activeforeground=T['accent'],
                                  relief='flat', font=FONT_MONO)
        self.context_menu.add_command(label="  + Увеличить", command=self.zoom_in)
        self.context_menu.add_command(label="  − Уменьшить", command=self.zoom_out)
        self.context_menu.add_command(label="  ⊞ Показать всё", command=self.fit_all)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="  ⟲ Сбросить вид", command=self.reset_view)
        
        # ===== INFO PANEL (below canvas) =====
        info_outer = tk.Frame(right_panel, bg=T['border'], height=1)
        info_outer.pack(fill=tk.X, pady=(2,0))

        info_frame = tk.Frame(right_panel, bg=T['panel'], height=90)
        info_frame.pack(fill=tk.X)
        info_frame.pack_propagate(False)

        tk.Label(info_frame, text="LOG", bg=T['panel'], fg=T['text_dim'],
                 font=("Consolas", 7, "bold")).pack(anchor='w', padx=8, pady=(4,0))

        self.info_text = tk.Text(info_frame, height=4, wrap=tk.WORD,
                                  bg=T['entry_bg'], fg=T['accent3'],
                                  insertbackground=T['accent'],
                                  font=("Consolas", 8), relief='flat',
                                  highlightthickness=0, padx=6, pady=4,
                                  state='normal')
        self.info_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0,4))
        
        # Инициализация
        self.update_styles_list()
        self.root.after(100, self.redraw_all)
        
    def bind_shortcuts(self):
        self.root.bind("<Control-plus>", lambda e: self.zoom_in())
        self.root.bind("<Control-equal>", lambda e: self.zoom_in())
        self.root.bind("<Control-minus>", lambda e: self.zoom_out())
        self.root.bind("<Control-0>", lambda e: self.fit_all())
        self.root.bind("<Control-l>", lambda e: self.rotate_left(shift_pressed=bool(e.state & 0x0001)))
        self.root.bind("<Control-L>", lambda e: self.rotate_left(shift_pressed=bool(e.state & 0x0001)))
        self.root.bind("<Control-r>", lambda e: self.rotate_right(shift_pressed=bool(e.state & 0x0001)))
        self.root.bind("<Control-R>", lambda e: self.rotate_right(shift_pressed=bool(e.state & 0x0001)))
        self.root.bind("<Control-h>", lambda e: self.reset_view())
        self.root.bind("<Control-H>", lambda e: self.reset_view())
        self.root.bind("<Control-e>", lambda e: self.export_dxf())
        self.root.bind("<Control-E>", lambda e: self.export_dxf())
        self.root.bind("<Control-i>", lambda e: self.import_dxf())
        self.root.bind("<Control-I>", lambda e: self.import_dxf())
        # Enter — завершить многоточечный примитив
        self.root.bind("<Return>", self.on_enter_key)
        self.root.bind("<KP_Enter>", self.on_enter_key)
        # Delete — удалить активный примитив
        self.root.bind("<Delete>", self.on_delete_key)
        self.root.bind("<KP_Delete>", self.on_delete_key)

    def on_delete_key(self, event=None):
        """Удаляет активный (выделенный) примитив. Не срабатывает в полях ввода."""
        # Не удалять, если фокус в поле ввода (Entry/Text)
        focus = self.root.focus_get()
        if isinstance(focus, (tk.Entry, tk.Text)):
            return
        if self.selected_prim_idx is not None and \
                0 <= self.selected_prim_idx < len(self.primitives):
            self.delete_selected_prim()
        
    def toggle_pan_mode(self):
        if self.active_tool == "pan":
            self.pan_active = not self.pan_active
            if self.pan_active:
                self.pan_button.config(relief=tk.SUNKEN)
                self.canvas.config(cursor="fleur")
            else:
                self.pan_button.config(relief=tk.RAISED)
                self.canvas.config(cursor="")
                self.active_tool = "select"
                self.tool_var.set("select")
                self.change_tool()
        else:
            self.pan_active = True
            self.active_tool = "pan"
            self.tool_var.set("pan")
            self.pan_button.config(relief=tk.SUNKEN)
            self.canvas.config(cursor="fleur")
            self.change_tool()
    
    def change_tool(self):
        self.active_tool = self.tool_var.get()
        tool_names = {
            "select": "Выбор",
            "pan": "Панорамирование (Рука)",
            "zoom_in": "Увеличение (Лупа+)",
            "zoom_out": "Уменьшение (Лупа-)"
        }
        self.status_tool.config(text=f"TOOL  {tool_names.get(self.active_tool, 'Выбор')}")
        
        cursors = {
            "select": "",
            "pan": "fleur",
            "zoom_in": "plus",
            "zoom_out": "sizing"
        }
        self.canvas.config(cursor=cursors.get(self.active_tool, ""))
    
    def screen_to_world(self, x, y):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        center_x = width / 2
        center_y = height / 2
        
        x -= center_x
        y -= center_y
        
        cos_r = math.cos(-self.rotation)
        sin_r = math.sin(-self.rotation)
        x_rot = x * cos_r - y * sin_r
        y_rot = x * sin_r + y * cos_r
        
        world_x = (x_rot / self.scale - self.pan_x) / self.grid_step
        world_y = - (y_rot / self.scale - self.pan_y) / self.grid_step
        
        return world_x, world_y
    
    def world_to_screen(self, x, y):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        center_x = width / 2
        center_y = height / 2
        
        x = (x * self.grid_step + self.pan_x) * self.scale
        y = (-y * self.grid_step + self.pan_y) * self.scale
        
        cos_r = math.cos(self.rotation)
        sin_r = math.sin(self.rotation)
        x_rot = x * cos_r - y * sin_r
        y_rot = x * sin_r + y * cos_r
        
        return center_x + x_rot, center_y + y_rot
    
    def on_mouse_move(self, event):
        world_x, world_y = self.screen_to_world(event.x, event.y)
        self.mouse_world_coords = (world_x, world_y)
        
        # Привязки — работают всегда когда активен инструмент рисования
        if self.snap_enabled and self.current_prim_tool:
            sp = self.find_snap_point(event.x, event.y, world_x, world_y)
            self.snap_point = sp
        else:
            self.snap_point = None
        
        wx, wy = self.snap_point if self.snap_point else (world_x, world_y)
        self.status_coords.config(text=f"XY  {wx:.2f}, {wy:.2f}")
        
        if self.current_prim_tool and self.prim_points:
            self.update_prim_preview(event.x, event.y)
        
        # Показать маркер привязки
        self.canvas.delete("snap_marker")
        if self.snap_point:
            sx, sy = self.world_to_screen(*self.snap_point)
            r = 9
            self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, outline="#FF6600", width=2, tags="snap_marker")
            self.canvas.create_rectangle(sx-3, sy-3, sx+3, sy+3, fill="#FF6600", tags="snap_marker")
            self.canvas.create_text(sx+14, sy-12, text=self.snap_label, fill="#FF4400",
                                    font=("Arial", 8, "bold"), tags="snap_marker")
    
    def on_pan_start(self, event):
        self.pan_start = (event.x, event.y)
        self.canvas.config(cursor="fleur")
    
    def on_pan_move(self, event):
        if self.pan_start:
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            
            cos_r = math.cos(-self.rotation)
            sin_r = math.sin(-self.rotation)
            dx_rot = dx * cos_r - dy * sin_r
            dy_rot = dx * sin_r + dy * cos_r
            
            self.pan_x += dx_rot / self.scale
            self.pan_y += dy_rot / self.scale
            
            self.pan_start = (event.x, event.y)
            self.redraw_all()
    
    def on_pan_end(self, event):
        self.pan_start = None
        self.change_tool()
    
    def on_left_click(self, event):
        if self.active_tool == "zoom_in":
            self.zoom_at_point(event.x, event.y, 1.2)
        elif self.active_tool == "zoom_out":
            self.zoom_at_point(event.x, event.y, 0.8333)
        elif self.pan_active:
            self.on_pan_start(event)
        elif self.current_prim_tool:
            self.prim_canvas_click(event)
        else:
            # Сначала проверяем, не попали ли в гриппер активного примитива
            grip = self._hit_grip(event.x, event.y)
            if grip is not None:
                self.drag_ctrl_pt = grip
                self.canvas.config(cursor="hand2")
                return
            self.try_select_prim(event)

    def on_left_drag(self, event):
        if self.pan_active and self.pan_start:
            self.on_pan_move(event)
            return
        if self.drag_ctrl_pt is not None:
            wx, wy = self.screen_to_world(event.x, event.y)
            # учитываем привязки при перетаскивании
            if self.snap_enabled:
                sp = self.find_snap_point(event.x, event.y, wx, wy)
                if sp:
                    wx, wy = sp
            idx = self.drag_ctrl_pt['idx']
            if 0 <= idx < len(self.primitives):
                prim = self.primitives[idx]
                self._move_gripper(prim, self.drag_ctrl_pt['key'], (wx, wy))
                self._sync_segments_from_primitives()
                self.redraw_all()
                # Подсветим маркер привязки
                if self.snap_point:
                    sx, sy = self.world_to_screen(*self.snap_point)
                    r = 9
                    self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r,
                                             outline="#FF6600", width=2,
                                             tags="snap_marker")

    def on_left_release(self, event):
        if self.pan_active:
            self.on_pan_end(event)
            return
        if self.drag_ctrl_pt is not None:
            idx = self.drag_ctrl_pt['idx']
            self.drag_ctrl_pt = None
            self.canvas.config(cursor="crosshair")
            # Обновим панель свойств после завершения перетаскивания
            if 0 <= idx < len(self.primitives) and self.selected_prim_idx == idx:
                self.build_prim_props_panel(self.primitives[idx])
                self.update_prims_list()
    
    def show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
    
    def zoom_at_point(self, x, y, factor):
        world_x, world_y = self.screen_to_world(x, y)
        
        self.scale *= factor
        self.scale = max(0.1, min(10.0, self.scale))
        
        world_x_new, world_y_new = self.screen_to_world(x, y)
        
        self.pan_x += (world_x_new - world_x) * self.grid_step
        self.pan_y += (world_y - world_y_new) * self.grid_step
        
        self.update_status()
        self.redraw_all()
    
    def zoom_in(self):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        self.zoom_at_point(width/2, height/2, 1.2)
    
    def zoom_out(self):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        self.zoom_at_point(width/2, height/2, 0.8333)
    

    
    def rotate_left(self, shift_pressed=False):
        angle = 90 if shift_pressed else 15
        self.rotate_view(-angle)
    
    def rotate_right(self, shift_pressed=False):
        angle = 90 if shift_pressed else 15
        self.rotate_view(angle)
    
    def rotate_view(self, angle_deg):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        center_x = width / 2
        center_y = height / 2
        
        world_x, world_y = self.screen_to_world(center_x, center_y)
        
        self.rotation += math.radians(angle_deg)
        
        world_x_new, world_y_new = self.screen_to_world(center_x, center_y)
        
        self.pan_x += (world_x_new - world_x) * self.grid_step
        self.pan_y += (world_y - world_y_new) * self.grid_step
        
        self.update_status()
        self.redraw_all()
    
    def reset_view(self):
        self.pan_x = 0
        self.pan_y = 0
        self.scale = 1.0
        self.rotation = 0
        self.update_status()
        self.redraw_all()

    def import_dxf(self):
        """Импорт DXF-файла во внутреннюю модель приложения."""
        path = filedialog.askopenfilename(
            title="Открыть DXF",
            filetypes=[("AutoCAD DXF", "*.dxf"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            data = import_from_dxf(path)
        except Exception as e:
            messagebox.showerror("Ошибка импорта DXF", str(e))
            return

        replace = True
        if self.primitives:
            ans = messagebox.askyesnocancel(
                "Импорт DXF",
                "Заменить текущий чертёж?\n"
                "Да — очистить и загрузить.\n"
                "Нет — добавить к существующему."
            )
            if ans is None:
                return
            replace = ans

        if replace:
            self.primitives.clear()
            self.segments.clear()
            self.selected_prim_idx = None

        # Объединяем стили: новые стили из DXF добавляем, существующие не трогаем.
        for sname, sdef in data['line_styles'].items():
            if sname not in self.line_styles:
                self.line_styles[sname] = sdef

        # Перенумеровываем имена импортированных примитивов с учётом уже
        # имеющихся в чертеже.
        offset = len(self.primitives)
        for i, prim in enumerate(data['primitives'], start=1):
            prim_copy = dict(prim)
            prim_copy['name'] = f"{prim['name'].split(' ')[0]} {offset + i}"
            prim_copy['id'] = self._next_prim_id
            self._next_prim_id += 1
            self.primitives.append(prim_copy)

        self._sync_segments_from_primitives()
        self.update_prims_list()
        self.update_segments_list()

        # Авто-вписывание импортированного чертежа.
        try:
            self.fit_all()
        except Exception:
            self.redraw_all()

        hdr = data.get('header') or {}
        ver = hdr.get('acadver') or '—'
        st = data['stats']
        messagebox.showinfo(
            "Импорт DXF",
            f"Файл загружен:\n{path}\n\n"
            f"Версия DXF: {ver}\n"
            f"Объектов импортировано: {st['entities']}\n"
            f"Слоёв: {len(data['layers'])}\n"
            f"Пропущено сущностей: {st['skipped']}"
        )

    def export_dxf(self):
        if not self.primitives:
            messagebox.showwarning("Экспорт DXF", "Чертёж пуст — экспортировать нечего.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить как DXF",
            defaultextension=".dxf",
            filetypes=[("AutoCAD DXF", "*.dxf"), ("Все файлы", "*.*")],
            initialfile="drawing.dxf",
        )
        if not path:
            return
        try:
            stats = export_to_dxf(
                filepath=path,
                primitives=self.primitives,
                line_styles=self.line_styles,
                units='mm',
                default_color=self.prim_default_color,
            )
        except Exception as e:
            messagebox.showerror("Ошибка экспорта DXF", str(e))
            return
        messagebox.showinfo(
            "Экспорт DXF",
            f"Файл сохранён:\n{stats['path']}\n\n"
            f"Объектов: {stats['entities']}\nСлоёв: {stats['layers']}"
        )

    def update_status(self):
        scale_percent = int(self.scale * 100)
        self.status_scale.config(text=f"ZOOM {scale_percent}%")
        
        rotation_deg = math.degrees(self.rotation) % 360
        self.status_rotation.config(text=f"ROT  {rotation_deg:.1f}°")
    
    def update_coord_system(self):
        self.coord_system = self.coord_var.get()
        
        if self.coord_system == "polar":
            self.x2_label.config(text="r₂:")
            self.y2_label.config(text="θ₂:")
        else:
            self.x2_label.config(text="x₂:")
            self.y2_label.config(text="y₂:")
        
        self.auto_convert_coordinates()
    
    def update_grid_step(self):
        try:
            self.grid_step = int(self.grid_entry.get())
            self.redraw_all()
        except ValueError:
            pass
    
    def auto_convert_coordinates(self):
        try:
            x1 = float(self.x1_entry.get())
            y1 = float(self.y1_entry.get())
            
            if self.x2_entry.get() and self.y2_entry.get():
                if self.coord_system == "polar":
                    x2 = float(self.x2_entry.get())
                    y2 = float(self.y2_entry.get())
                    r, theta = self.cartesian_to_polar(x1, y1, x2, y2)
                    
                    self.x2_entry.delete(0, tk.END)
                    self.x2_entry.insert(0, f"{r:.4f}")
                    self.y2_entry.delete(0, tk.END)
                    self.y2_entry.insert(0, f"{theta:.4f}")
                else:
                    r = float(self.x2_entry.get())
                    theta = float(self.y2_entry.get())
                    x2, y2 = self.polar_to_cartesian(x1, y1, r, theta)
                    
                    self.x2_entry.delete(0, tk.END)
                    self.x2_entry.insert(0, f"{x2:.4f}")
                    self.y2_entry.delete(0, tk.END)
                    self.y2_entry.insert(0, f"{y2:.4f}")
        except ValueError:
            pass
    
    def choose_color(self, color_type):
        color = colorchooser.askcolor()[1]
        if color:
            if color_type == "segment":
                self.segment_color = color
            elif color_type == "bg":
                self.bg_color = color
                self.canvas.config(bg=color)
            elif color_type == "grid":
                self.grid_color = color
            self.redraw_all()
    
    def polar_to_cartesian(self, x1, y1, r, theta):
        if self.angle_var.get() == "degrees":
            theta_rad = math.radians(theta)
        else:
            theta_rad = theta
        
        x2 = x1 + r * math.cos(theta_rad)
        y2 = y1 + r * math.sin(theta_rad)
        
        return x2, y2
    
    def cartesian_to_polar(self, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        
        r = math.sqrt(dx**2 + dy**2)
        theta_rad = math.atan2(dy, dx)
        
        if self.angle_var.get() == "degrees":
            theta = math.degrees(theta_rad)
        else:
            theta = theta_rad
        
        return r, theta
    
    def set_current_style(self):
        self.current_style = self.current_style_var.get()
    
    def build_segment(self):
        """Строит отрезок из полей ввода координат и добавляет в единый список примитивов."""
        try:
            x1 = float(self.x1_entry.get())
            y1 = float(self.y1_entry.get())
            
            if self.coord_system == "cartesian":
                x2 = float(self.x2_entry.get())
                y2 = float(self.y2_entry.get())
            else:
                r = float(self.x2_entry.get())
                theta = float(self.y2_entry.get())
                x2, y2 = self.polar_to_cartesian(x1, y1, r, theta)
            
            # Создаём как примитив segment_mouse для единого списка
            prim = {
                'type': 'segment_mouse',
                'params': {'p1': (x1, y1), 'p2': (x2, y2)},
                'style_name': self.current_style,
                'color': self.segment_color,
                'name': f"Отрезок {len(self.primitives) + 1}",
                'id': self._next_prim_id
            }
            self._next_prim_id += 1
            self.primitives.append(prim)
            
            # Совместимость — также в self.segments для update_info
            self.point1 = (x1, y1)
            self.point2 = (x2, y2)
            seg_compat = {'point1': (x1,y1), 'point2': (x2,y2),
                          'style_name': self.current_style, 'color': self.segment_color,
                          'name': prim['name']}
            self.segments.append(seg_compat)
            
            self.update_prims_list()
            self.update_segments_list()
            self.redraw_all()
            self.update_info()
            
        except ValueError:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, "Ошибка: введите корректные числовые значения!")

    def delete_last_primitive(self):
        """Удаляет последний добавленный примитив."""
        if self.primitives:
            self.primitives.pop()
            # Синхронизируем self.segments (удаляем последний segment_mouse если есть)
            if self.segments:
                self.segments.pop()
            self.selected_prim_idx = None
            self.update_prims_list()
            self.update_segments_list()
            self.redraw_all()
            self.update_info()
        else:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, "Нет объектов для удаления.")

    def delete_all_primitives(self):
        """Удаляет все примитивы."""
        self.primitives.clear()
        self.segments.clear()
        self.point1 = None
        self.point2 = None
        self.selected_prim_idx = None
        self.update_prims_list()
        self.update_segments_list()
        self.redraw_all()
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, "Все объекты удалены.")
    
    def delete_last_segment(self):
        self.delete_last_primitive()
    
    def delete_all_segments(self):
        self.delete_all_primitives()
    
    def delete_selected_segment(self):
        self.delete_selected_prim()
    
    def edit_segment(self):
        """Загружает выбранный segment_mouse в поля ввода для редактирования."""
        selected = self.segments_listbox.curselection()
        if not selected:
            return
        index = selected[0]
        # Найти соответствующий примитив segment_mouse
        seg_prims = [i for i,p in enumerate(self.primitives) if p['type'] == 'segment_mouse']
        if index < len(seg_prims):
            prim_idx = seg_prims[index]
            prim = self.primitives[prim_idx]
            p1 = prim['params']['p1']
            p2 = prim['params']['p2']
            self.x1_entry.delete(0, tk.END); self.x1_entry.insert(0, p1[0])
            self.y1_entry.delete(0, tk.END); self.y1_entry.insert(0, p1[1])
            if self.coord_system == "cartesian":
                self.x2_entry.delete(0, tk.END); self.x2_entry.insert(0, p2[0])
                self.y2_entry.delete(0, tk.END); self.y2_entry.insert(0, p2[1])
            else:
                r, theta = self.cartesian_to_polar(*p1, *p2)
                self.x2_entry.delete(0, tk.END); self.x2_entry.insert(0, r)
                self.y2_entry.delete(0, tk.END); self.y2_entry.insert(0, theta)
            del self.primitives[prim_idx]
            self._sync_segments_from_primitives()
            self.update_prims_list()
            self.update_segments_list()
            self.redraw_all()
            self.update_info()
    
    def update_segments_list(self):
        self.segments_listbox.delete(0, tk.END)
        for i, seg in enumerate(self.segments):
            p1 = seg['point1']
            p2 = seg['point2']
            name = seg.get('name', f"Отрезок {i+1}")
            self.segments_listbox.insert(tk.END, f"{name}: ({p1[0]:.1f}, {p1[1]:.1f}) -> ({p2[0]:.1f}, {p2[1]:.1f})")
    
    def on_segment_select(self, event):
        selected = self.segments_listbox.curselection()
        if selected:
            names = [self.segments[i].get('name', f"Отрезок {i+1}") for i in selected]
            styles = set(self.segments[i]['style_name'] for i in selected)
            if len(names) == 1:
                self.selected_name_entry.config(state='normal')
                self.selected_name_entry.delete(0, tk.END)
                self.selected_name_entry.insert(0, names[0])
            else:
                self.selected_name_entry.config(state='disabled')
                self.selected_name_entry.delete(0, tk.END)
                self.selected_name_entry.insert(0, "Разные")
            if len(styles) == 1:
                self.selected_style_button.config(text=next(iter(styles)))
            else:
                self.selected_style_button.config(text="Разные")
    
    def show_style_menu(self):
        menu = Menu(self.root, tearoff=0)
        for name in sorted(self.line_styles.keys()):
            menu.add_command(label=name, command=lambda n=name: self.set_selected_style(n))
        menu.tk_popup(self.selected_style_button.winfo_rootx(), self.selected_style_button.winfo_rooty() + self.selected_style_button.winfo_height())
    
    def set_selected_style(self, new_style):
        self.selected_style_button.config(text=new_style)
    
    def change_selected_color(self):
        selected = self.segments_listbox.curselection()
        if selected:
            color = colorchooser.askcolor()[1]
            if color:
                for i in selected:
                    self.segments[i]['color'] = color
                self.redraw_all()
    
    def apply_selected_changes(self):
        selected = self.segments_listbox.curselection()
        if selected:
            new_style = self.selected_style_button['text']
            if new_style in self.line_styles:
                for i in selected:
                    self.segments[i]['style_name'] = new_style
            new_name = self.selected_name_entry.get().strip()
            if new_name and len(selected) == 1:
                self.segments[selected[0]]['name'] = new_name
            self.update_segments_list()
            self.redraw_all()
            self.update_info()
    
    def update_styles_list(self):
        self.styles_listbox.delete(0, tk.END)
        for name in sorted(self.line_styles.keys()):
            self.styles_listbox.insert(tk.END, name)
        vals = sorted(self.line_styles.keys())
        self.current_style_combo['values'] = vals
        self.prim_style_combo['values'] = vals
    
    def on_style_select(self, event):
        selected = self.styles_listbox.curselection()
        if selected:
            name = self.styles_listbox.get(selected[0])
            style = self.line_styles[name]
            self.style_name_entry.delete(0, tk.END)
            self.style_name_entry.insert(0, name)
            if name in self.base_styles:
                self.style_name_entry.config(state='disabled')
            else:
                self.style_name_entry.config(state='normal')
            self.style_type_var.set(style['type'])
            self.style_width_entry.delete(0, tk.END)
            self.style_width_entry.insert(0, style['width'])
            if style['type'] in ['dashed', 'dashdot', 'dashdotdot']:
                pattern_str = ' '.join(map(str, style['dash']))
            elif style['type'] in ['wavy', 'zigzag']:
                pattern_str = f"{style['amplitude']} {style['period']}"
            else:
                pattern_str = ''
            self.style_pattern_entry.delete(0, tk.END)
            self.style_pattern_entry.insert(0, pattern_str)
            self.draw_style_preview()
    
    def update_pattern_label(self, event):
        type_ = self.style_type_var.get()
        if type_ == 'solid':
            self.style_pattern_label.config(text="Паттерн: (не требуется)")
        elif type_ == 'dashed':
            self.style_pattern_label.config(text="Паттерн: (штрих пробел)")
        elif type_ == 'dashdot':
            self.style_pattern_label.config(text="Паттерн: (штрих пробел точка пробел)")
        elif type_ == 'dashdotdot':
            self.style_pattern_label.config(text="Паттерн: (штрих пробел точка пробел точка пробел)")
        elif type_ in ['wavy', 'zigzag']:
            self.style_pattern_label.config(text="Паттерн: (амплитуда период)")
    
    def draw_style_preview(self):
        self.style_preview.delete("all")
        try:
            type_ = self.style_type_var.get()
            width = float(self.style_width_entry.get() or 1.0)
            pattern = self.style_pattern_entry.get().strip()
            style = {'type': type_, 'width': width}
            if pattern:
                nums = list(map(int, pattern.split()))
                if type_ in ['dashed', 'dashdot', 'dashdotdot']:
                    style['dash'] = tuple(nums)
                elif type_ in ['wavy', 'zigzag']:
                    style['amplitude'] = nums[0]
                    style['period'] = nums[1]
            self.draw_styled_line(self.style_preview, 10, 15, 190, 15, style, 'black')
        except:
            pass
    
    def apply_style_changes(self):
        selected = self.styles_listbox.curselection()
        if not selected:
            return
        old_name = self.styles_listbox.get(selected[0])
        new_name = self.style_name_entry.get().strip()
        type_ = self.style_type_var.get()
        try:
            width = float(self.style_width_entry.get())
        except:
            messagebox.showerror("Ошибка", "Некорректная толщина")
            return
        pattern = self.style_pattern_entry.get().strip()
        style = {'type': type_, 'width': width}
        if pattern:
            try:
                nums = list(map(int, pattern.split()))
                if type_ == 'dashed' and len(nums) == 2:
                    style['dash'] = tuple(nums)
                elif type_ == 'dashdot' and len(nums) == 4:
                    style['dash'] = tuple(nums)
                elif type_ == 'dashdotdot' and len(nums) == 6:
                    style['dash'] = tuple(nums)
                elif type_ in ['wavy', 'zigzag'] and len(nums) == 2:
                    style['amplitude'] = nums[0]
                    style['period'] = nums[1]
                else:
                    raise ValueError
            except:
                messagebox.showerror("Ошибка", "Некорректный паттерн")
                return
        if old_name in self.base_styles:
            new_name = old_name
        if new_name == "":
            messagebox.showerror("Ошибка", "Имя не может быть пустым")
            return
        if new_name != old_name and new_name in self.line_styles:
            messagebox.showerror("Ошибка", "Имя уже существует")
            return
        if new_name != old_name:
            for seg in self.segments:
                if seg['style_name'] == old_name:
                    seg['style_name'] = new_name
        del self.line_styles[old_name]
        self.line_styles[new_name] = style
        self.update_styles_list()
        self.styles_listbox.selection_set(sorted(self.line_styles.keys()).index(new_name))
        self.redraw_all()
    
    def new_style(self):
        name = simpledialog.askstring("Новый стиль", "Введите имя стиля:")
        if name and name not in self.line_styles:
            self.line_styles[name] = {'type': 'solid', 'width': 1.0}
            self.update_styles_list()
            idx = sorted(self.line_styles.keys()).index(name)
            self.styles_listbox.selection_set(idx)
            self.on_style_select(None)
        elif name in self.line_styles:
            messagebox.showerror("Ошибка", "Имя уже существует")
    
    def edit_style(self):
        selected = self.styles_listbox.curselection()
        if selected:
            self.on_style_select(None)
    
    def delete_style(self):
        selected = self.styles_listbox.curselection()
        if selected:
            name = self.styles_listbox.get(selected[0])
            if name in self.base_styles:
                messagebox.showerror("Ошибка", "Нельзя удалить базовый стиль")
                return
            del self.line_styles[name]
            for seg in self.segments:
                if seg['style_name'] == name:
                    seg['style_name'] = 'Сплошная основная'
            self.update_styles_list()
            self.redraw_all()
    
    def redraw_all(self):
        self.draw_grid()
        # Рисуем все примитивы (включая отрезки из ввода координат)
        for i, prim in enumerate(self.primitives):
            selected = (i == self.selected_prim_idx)
            self.draw_primitive(prim, selected=selected)
    
    def draw_styled_line(self, canvas, x1, y1, x2, y2, style, color, tags=""):
        type_ = style['type']
        width = style['width']
        if type_ in ['solid', 'dashed', 'dashdot', 'dashdotdot']:
            dash = style.get('dash', None) if type_ != 'solid' else None
            canvas.create_line(x1, y1, x2, y2, fill=color, width=width, dash=dash, tags=tags)
        elif type_ == 'wavy':
            amp = style['amplitude']
            period = style['period']
            self.draw_wavy_line(canvas, x1, y1, x2, y2, amp, period, width, color, tags)
        elif type_ == 'zigzag':
            amp = style['amplitude']
            period = style['period']
            self.draw_zigzag_line(canvas, x1, y1, x2, y2, amp, period, width, color, tags)
    
    def draw_wavy_line(self, canvas, x1, y1, x2, y2, amp, period, width, color, tags):
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx**2 + dy**2)
        if length == 0:
            return
        vx = dx / length
        vy = dy / length
        px = -vy
        py = vx
        num_points = int(length) + 1
        points = []
        for i in range(num_points):
            t = i / (num_points - 1) * length
            base_x = x1 + vx * t
            base_y = y1 + vy * t
            offset = amp * math.sin(2 * math.pi * t / period)
            points.append(base_x + px * offset)
            points.append(base_y + py * offset)
        canvas.create_line(*points, fill=color, width=width, smooth=True, tags=tags)
    
    def draw_zigzag_line(self, canvas, x1, y1, x2, y2, amp, period, width, color, tags):
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx**2 + dy**2)
        if length == 0:
            return
        vx = dx / length
        vy = dy / length
        px = -vy
        py = vx
        num_zigs = int(length / period) + 1
        points = [x1, y1]
        for i in range(1, num_zigs * 2):
            t = i / (num_zigs * 2) * length
            base_x = x1 + vx * t
            base_y = y1 + vy * t
            sign = 1 if i % 2 == 1 else -1
            offset = amp * sign
            points.append(base_x + px * offset)
            points.append(base_y + py * offset)
        points.append(x2)
        points.append(y2)
        canvas.create_line(*points, fill=color, width=width, tags=tags)
    
    def draw_grid(self):
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        if width <= 1 or height <= 1:
            return
        
        corners = [
            self.screen_to_world(0, 0),
            self.screen_to_world(width, 0),
            self.screen_to_world(0, height),
            self.screen_to_world(width, height)
        ]
        
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        grid_x_start = math.floor(min_x)
        grid_x_end = math.ceil(max_x)
        grid_y_start = math.floor(min_y)
        grid_y_end = math.ceil(max_y)
        
        for i in range(grid_x_start, grid_x_end + 1):
            x1_s, y1_s = self.world_to_screen(i, min_y - 1)
            x2_s, y2_s = self.world_to_screen(i, max_y + 1)
            fill = "#00D4FF" if i == 0 else self.grid_color
            w = 2 if i == 0 else 1
            self.canvas.create_line(x1_s, y1_s, x2_s, y2_s, fill=fill, width=w, tags="grid" if i != 0 else "axis")
        
        for i in range(grid_y_start, grid_y_end + 1):
            x1_s, y1_s = self.world_to_screen(min_x - 1, i)
            x2_s, y2_s = self.world_to_screen(max_x + 1, i)
            fill = "#00D4FF" if i == 0 else self.grid_color
            w = 2 if i == 0 else 1
            self.canvas.create_line(x1_s, y1_s, x2_s, y2_s, fill=fill, width=w, tags="grid" if i != 0 else "axis")
        
        origin_screen = self.world_to_screen(0, 0)
        
        canvas_width = width
        canvas_height = height
        
        x_point_world = max(1, (max_x - min_x) * 0.85 + min_x)
        x_label_world = self.world_to_screen(x_point_world, 0)
        x_label_x = max(30, min(canvas_width - 30, x_label_world[0]))
        x_label_y = max(30, min(canvas_height - 30, x_label_world[1]))
        if origin_screen[1] < 0:
            x_label_y = 20
        elif origin_screen[1] > canvas_height:
            x_label_y = canvas_height - 20
        x_label_y += 15
        self.canvas.create_rectangle(x_label_x - 12, x_label_y - 12, x_label_x + 12, x_label_y + 12, fill="#0A1520", outline="#00D4FF", width=1, tags="axis_label_bg")
        self.canvas.create_text(x_label_x, x_label_y, text="X", font=("Consolas", 14, "bold"), fill="#00D4FF", tags="axis_label")
        
        y_point_world = max(1, (max_y - min_y) * 0.85 + min_y)
        y_label_world = self.world_to_screen(0, y_point_world)
        y_label_x = max(30, min(canvas_width - 30, y_label_world[0]))
        y_label_y = max(30, min(canvas_height - 30, y_label_world[1]))
        if origin_screen[0] < 0:
            y_label_x = 20
        elif origin_screen[0] > canvas_width:
            y_label_x = canvas_width - 20
        y_label_x += 15
        self.canvas.create_rectangle(y_label_x - 12, y_label_y - 12, y_label_x + 12, y_label_y + 12, fill="#0A1520", outline="#00D4FF", width=1, tags="axis_label_bg")
        self.canvas.create_text(y_label_x, y_label_y, text="Y", font=("Consolas", 14, "bold"), fill="#00D4FF", tags="axis_label")
    
    def update_info(self):
        self.info_text.delete(1.0, tk.END)
        if self.segments:
            self.info_text.insert(tk.END, f"Всего отрезков: {len(self.segments)}\n\n")
            if self.point1 and self.point2:
                length = math.sqrt((self.point2[0] - self.point1[0])**2 + (self.point2[1] - self.point1[1])**2)
                dx = self.point2[0] - self.point1[0]
                dy = self.point2[1] - self.point1[1]
                angle_rad = math.atan2(dy, dx)
                angle_deg = math.degrees(angle_rad)
                r, theta = self.cartesian_to_polar(self.point1[0], self.point1[1], self.point2[0], self.point2[1])
                info = f"Декартовы координаты:\n"
                info += f"  Точка 1: ({self.point1[0]:.2f}, {self.point1[1]:.2f})\n"
                info += f"  Точка 2: ({self.point2[0]:.2f}, {self.point2[1]:.2f})\n\n"
                info += f"Полярные (относительно точки 1):\n"
                info += f"  r = {r:.2f}, θ = {theta:.2f} {self.angle_var.get()}\n\n"
                info += f"Длина: {length:.2f}\n"
                info += f"Угол: {angle_deg:.2f}° ({angle_rad:.4f} рад)\n"
                self.info_text.insert(tk.END, info)
        else:
            self.info_text.insert(tk.END, "Нет отрезков.")

    # =========================================================
    # ПРИМИТИВЫ САПР — вспомогательные методы
    # =========================================================

    def activate_prim_tool(self, tool):
        self.current_prim_tool = tool
        self.prim_points = []
        self.prim_creation_step = 0
        self.clear_prim_preview()
        
        methods_map = {
            'segment_mouse': ["Две точки"],
            'polyline': ["По точкам (Enter/двойной клик — завершить)"],
            'circle':  ["Центр и радиус", "Центр и диаметр", "По двум точкам", "По трём точкам"],
            'arc':     ["Три точки", "Центр, нач. угол, кон. угол"],
            'rect':    ["Две противоположные точки", "Точка + ширина + высота", "Центр + ширина + высота"],
            'ellipse': ["Центр и две оси"],
            'polygon': ["Центр и радиус"],
            'spline':  ["По контрольным точкам (Enter/двойной клик — завершить)"],
            'dim_linear':   ["Выровненный", "Горизонтальный", "Вертикальный"],
            'dim_radial_r': ["Радиус (выбрать окружность/дугу)"],
            'dim_radial_d': ["Диаметр (выбрать окружность/дугу)"],
            'dim_angular':  ["Вершина → точка1 → точка2 → положение дуги"],
        }
        vals = methods_map.get(tool, ["Стандартный"])
        self.prim_method_combo['values'] = vals
        self.prim_method_var.set(vals[0])
        self.creation_mode['method'] = vals[0]
        self.update_prim_hint()

    def on_prim_method_change(self, event=None):
        self.creation_mode['method'] = self.prim_method_var.get()
        self.prim_points = []
        self.prim_creation_step = 0
        self.clear_prim_preview()
        self.update_prim_hint()

    def update_prim_hint(self):
        tool = self.current_prim_tool
        method = self.creation_mode.get('method', '')
        step = self.prim_creation_step
        hints = {
            'segment_mouse': {
                "Две точки": ["Укажите начальную точку отрезка", "Укажите конечную точку отрезка"],
            },
            'polyline': {
                "По точкам (Enter/двойной клик — завершить)": [
                    "Укажите первую точку ломаной",
                    "Укажите следующую точку (Enter или двойной клик — завершить)",
                ],
            },
            'circle': {
                "Центр и радиус": ["Укажите центр окружности", "Укажите точку на окружности (радиус)"],
                "Центр и диаметр": ["Укажите центр окружности", "Укажите точку диаметра"],
                "По двум точкам": ["Укажите первую точку диаметра", "Укажите вторую точку диаметра"],
                "По трём точкам": ["Укажите точку 1", "Укажите точку 2", "Укажите точку 3"],
            },
            'arc': {
                "Три точки": ["Укажите начальную точку", "Укажите промежуточную точку", "Укажите конечную точку"],
                "Центр, нач. угол, кон. угол": ["Укажите центр дуги", "Укажите начало дуги (угол)", "Укажите конец дуги (угол)"],
            },
            'rect': {
                "Две противоположные точки": ["Укажите первый угол", "Укажите противоположный угол"],
                "Точка + ширина + высота": ["Укажите первый угол", "Укажите противоположный угол (или введите W/H)"],
                "Центр + ширина + высота": ["Укажите центр", "Укажите угол прямоугольника"],
            },
            'ellipse': {
                "Центр и две оси": ["Укажите центр эллипса", "Укажите конец большой оси", "Укажите конец малой оси"],
            },
            'polygon': {
                "Центр и радиус": ["Укажите центр многоугольника", "Укажите вершину (радиус)"],
            },
            'spline': {
                "По контрольным точкам (Enter/двойной клик — завершить)": [
                    "Укажите первую точку сплайна",
                    "Укажите следующую точку (Enter или двойной клик — завершить)",
                ],
            },
            'dim_linear': {
                "Выровненный":   ["Укажите 1-ю точку измерения", "Укажите 2-ю точку измерения", "Укажите положение размерной линии"],
                "Горизонтальный":["Укажите 1-ю точку измерения", "Укажите 2-ю точку измерения", "Укажите положение размерной линии"],
                "Вертикальный":  ["Укажите 1-ю точку измерения", "Укажите 2-ю точку измерения", "Укажите положение размерной линии"],
            },
            'dim_radial_r': {
                "Радиус (выбрать окружность/дугу)": ["Кликните по окружности/дуге", "Укажите положение надписи"],
            },
            'dim_radial_d': {
                "Диаметр (выбрать окружность/дугу)": ["Кликните по окружности/дуге", "Укажите положение надписи"],
            },
            'dim_angular': {
                "Вершина → точка1 → точка2 → положение дуги": [
                    "Укажите вершину угла",
                    "Укажите точку на 1-м луче",
                    "Укажите точку на 2-м луче",
                    "Укажите положение размерной дуги",
                ],
            },
        }
        step_hints = hints.get(tool, {}).get(method, [])
        if step < len(step_hints):
            self.prim_hint_label.config(text=step_hints[step])
        else:
            self.prim_hint_label.config(text="Завершение...")

    def cancel_prim_creation(self):
        """Отмена/завершение создания примитива. Для многоточечных — сохраняет уже набранные точки."""
        tool = self.current_prim_tool
        # Для сплайна и ломаной — если точек >= 2, сохраняем то, что набрали
        if tool in ('spline', 'polyline') and len(self.prim_points) >= 2:
            self.finalize_primitive()
            return
        self._reset_prim_tool()

    def _reset_prim_tool(self):
        """Полный сброс инструмента без сохранения."""
        self.current_prim_tool = None
        self.prim_points = []
        self.prim_creation_step = 0
        self.creation_mode = {}
        self.clear_prim_preview()
        self.prim_tool_var.set("")
        self.prim_hint_label.config(text="Выберите инструмент")
        self.canvas.delete("snap_marker")

    def clear_prim_preview(self):
        self.canvas.delete("prim_preview")

    def toggle_snap(self):
        self.snap_enabled = self.snap_enabled_var.get()

    def set_snap_mode(self, key, var):
        self.snap_modes[key] = var.get()

    # ---- Нахождение точки привязки ----
    def find_snap_point(self, sx, sy, world_x, world_y):
        """Ищем ближайшую точку привязки. Радиус в пикселях, но кандидаты в мировых координатах."""
        # Радиус захвата в мировых координатах (20px → мировые)
        snap_r_world = 20.0 / (self.scale * self.grid_step)

        best_d = snap_r_world
        best_pt = None
        best_label = ""
        best_ref = None

        # Базовые кандидаты (конец, середина, центр)
        for cand in self._collect_snap_candidates():
            pt, label = cand[0], cand[1]
            ref = cand[2] if len(cand) > 2 else None
            d = math.hypot(world_x - pt[0], world_y - pt[1])
            if d < best_d:
                best_d = d
                best_pt = pt
                best_label = label
                best_ref = ref
        
        # Касательная / Перпендикуляр — нужна «отправная» точка (откуда вести линию).
        # Активируем для любого многоточечного инструмента с накопленной точкой.
        TANGENT_TOOLS = ('segment_mouse', 'polyline', 'spline',
                         'dim_linear', 'dim_angular')
        from_pt = self.prim_points[-1] if self.prim_points else None

        if self.snap_modes.get('tangent') and from_pt and \
                self.current_prim_tool in TANGENT_TOOLS:
            for pt, label in self._collect_tangent_candidates(from_pt, world_x, world_y, snap_r_world):
                d = math.hypot(world_x - pt[0], world_y - pt[1])
                if d < best_d:
                    best_d = d
                    best_pt = pt
                    best_label = label
                    best_ref = None

        # Перпендикуляр — нужна «отправная» точка (откуда опускать перпендикуляр)
        if self.snap_modes.get('perp') and from_pt and \
                self.current_prim_tool in TANGENT_TOOLS:
            for pt, label in self._collect_perp_candidates(from_pt, world_x, world_y, snap_r_world):
                d = math.hypot(world_x - pt[0], world_y - pt[1])
                if d < best_d:
                    best_d = d
                    best_pt = pt
                    best_label = label
                    best_ref = None

        # Пересечение — между любыми двумя примитивами (отрезки, ломаные, дуги, окружности и т.д.)
        if self.snap_modes.get('intersect'):
            for pt, label in self._collect_intersection_candidates(world_x, world_y, snap_r_world):
                d = math.hypot(world_x - pt[0], world_y - pt[1])
                if d < best_d:
                    best_d = d
                    best_pt = pt
                    best_label = label
                    best_ref = None

        self.snap_label = best_label
        self.snap_ref = best_ref
        return best_pt

    # ====================================================================
    #                        Привязка «Пересечение»
    # ====================================================================
    def _collect_intersection_candidates(self, wx, wy, snap_r):
        """Возвращает точки пересечения примитивов (отрезок-отрезок,
        отрезок-окружность, окружность-окружность и т.п.) в окрестности (wx,wy)."""
        # Извлекаем все «линейные» отрезки и окружности/дуги из примитивов.
        segs = []   # [((ax,ay),(bx,by)), ...]
        circs = []  # [(cx, cy, r, arc_range_or_None), ...]
        for prim in self.primitives:
            t = prim['type']; p = prim['params']
            if is_dimension_type(t):
                continue
            if t == 'segment_mouse':
                segs.append((p['p1'], p['p2']))
            elif t == 'polyline':
                pts = p['points']
                for i in range(len(pts) - 1):
                    segs.append((pts[i], pts[i+1]))
            elif t == 'rect':
                pts = p['points']
                for i in range(len(pts)):
                    segs.append((pts[i], pts[(i+1) % len(pts)]))
            elif t == 'polygon':
                verts = p['vertices']
                for i in range(len(verts)):
                    segs.append((verts[i], verts[(i+1) % len(verts)]))
            elif t == 'circle':
                circs.append((p['cx'], p['cy'], p['r'], None))
            elif t == 'arc':
                circs.append((p['cx'], p['cy'], p['r'],
                              (p['start_angle'], p['end_angle'])))

        cands = []

        # отрезок-отрезок
        n = len(segs)
        for i in range(n):
            for j in range(i + 1, n):
                pt = self._seg_seg_intersect(segs[i], segs[j])
                if pt and math.hypot(pt[0]-wx, pt[1]-wy) < snap_r:
                    cands.append((pt, "Пересечение"))

        # отрезок-окружность(дуга)
        for seg in segs:
            for circ in circs:
                for pt in self._seg_circle_intersect(seg, circ):
                    if math.hypot(pt[0]-wx, pt[1]-wy) < snap_r:
                        cands.append((pt, "Пересечение"))

        # окружность(дуга)-окружность(дуга)
        m = len(circs)
        for i in range(m):
            for j in range(i + 1, m):
                for pt in self._circle_circle_intersect(circs[i], circs[j]):
                    if math.hypot(pt[0]-wx, pt[1]-wy) < snap_r:
                        cands.append((pt, "Пересечение"))

        return cands

    @staticmethod
    def _seg_seg_intersect(s1, s2):
        """Точка пересечения двух отрезков либо None."""
        (x1, y1), (x2, y2) = s1
        (x3, y3), (x4, y4) = s2
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / denom
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        return None

    @staticmethod
    def _angle_in_arc(angle_deg, arc_range):
        """True если angle_deg попадает в дугу [a1..a2] CCW."""
        a1, a2 = arc_range
        while a2 < a1:
            a2 += 360.0
        ang = angle_deg
        while ang < a1:
            ang += 360.0
        return ang <= a2

    @classmethod
    def _seg_circle_intersect(cls, seg, circ):
        """Точки пересечения отрезка с окружностью или дугой."""
        (x1, y1), (x2, y2) = seg
        cx, cy, r, arc_range = circ
        dx, dy = x2 - x1, y2 - y1
        if dx*dx + dy*dy < 1e-20:
            return []
        fx, fy = x1 - cx, y1 - cy
        a = dx*dx + dy*dy
        b = 2*(fx*dx + fy*dy)
        c = fx*fx + fy*fy - r*r
        disc = b*b - 4*a*c
        if disc < 0:
            return []
        sq = math.sqrt(disc)
        out = []
        for t in ((-b - sq) / (2*a), (-b + sq) / (2*a)):
            if 0.0 <= t <= 1.0:
                px = x1 + t*dx
                py = y1 + t*dy
                if arc_range is not None:
                    ang = math.degrees(math.atan2(py-cy, px-cx))
                    if not cls._angle_in_arc(ang, arc_range):
                        continue
                out.append((px, py))
        return out

    @classmethod
    def _circle_circle_intersect(cls, c1, c2):
        """Точки пересечения двух окружностей (и/или дуг)."""
        cx1, cy1, r1, ar1 = c1
        cx2, cy2, r2, ar2 = c2
        dx, dy = cx2 - cx1, cy2 - cy1
        d = math.hypot(dx, dy)
        if d < 1e-12:
            return []
        if d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
            return []
        a = (r1*r1 - r2*r2 + d*d) / (2.0*d)
        h_sq = r1*r1 - a*a
        if h_sq < 0:
            return []
        h = math.sqrt(h_sq)
        px = cx1 + a*dx/d
        py = cy1 + a*dy/d
        rx = -dy * (h/d)
        ry =  dx * (h/d)
        candidates = [(px + rx, py + ry), (px - rx, py - ry)]
        out = []
        for ix, iy in candidates:
            ok = True
            for cx, cy, _r, ar in ((cx1, cy1, r1, ar1), (cx2, cy2, r2, ar2)):
                if ar is not None:
                    ang = math.degrees(math.atan2(iy-cy, ix-cx))
                    if not cls._angle_in_arc(ang, ar):
                        ok = False
                        break
            if ok:
                out.append((ix, iy))
        return out

    def _collect_tangent_candidates(self, from_pt, wx, wy, snap_r):
        """Касательная к окружности/дуге.

        Поведение: пока курсор находится вблизи касательной прямой
        (проведённой из from_pt через точку касания), снап «скользит»
        вдоль этой прямой — кандидат = проекция курсора на прямую.
        Это позволяет вытягивать отрезок дальше точки касания, как в
        AutoCAD/КОМПАС.
        """
        cands = []
        fx, fy = from_pt

        for prim in self.primitives:
            t = prim['type']
            p = prim['params']

            if t not in ('circle', 'arc'):
                continue

            cx, cy, r = p['cx'], p['cy'], p['r']
            dist = math.hypot(fx - cx, fy - cy)
            if dist <= r * (1.0 + 1e-9):
                continue  # точка внутри/на окружности — касательной нет

            # Угол центр→from_pt и поправка на радиус-к-точке-касания.
            base_angle = math.atan2(fy - cy, fx - cx)
            half = math.acos(r / dist)

            for sign in (+1, -1):
                touch_angle = base_angle + sign * half
                tx = cx + r * math.cos(touch_angle)
                ty = cy + r * math.sin(touch_angle)

                # Для дуги — точка касания должна лежать в её угловом диапазоне.
                if t == 'arc':
                    ang_deg = math.degrees(touch_angle)
                    if not self._angle_in_arc(ang_deg,
                                              (p['start_angle'], p['end_angle'])):
                        continue

                # Направляющий вектор касательной = единичный from_pt → touch.
                ux = tx - fx
                uy = ty - fy
                ulen = math.hypot(ux, uy)
                if ulen < 1e-12:
                    continue
                ux /= ulen
                uy /= ulen

                # Проекция курсора на прямую (from_pt + t·u).
                vx = wx - fx
                vy = wy - fy
                tparam = vx * ux + vy * uy
                proj_x = fx + tparam * ux
                proj_y = fy + tparam * uy

                # Снап активен, если курсор близко к самой прямой
                # (перпендикулярное расстояние < snap_r).
                dist_to_line = math.hypot(wx - proj_x, wy - proj_y)
                if dist_to_line < snap_r:
                    cands.append(((proj_x, proj_y), "Касательная"))

        return cands

    def _collect_perp_candidates(self, from_pt, wx, wy, snap_r):
        """Перпендикуляр: ножка перпендикуляра от первой точки отрезка (from_pt) на отрезок.
        Так новый отрезок (from_pt → ножка) образует угол 90° с существующим отрезком."""
        cands = []
        fx, fy = from_pt

        def foot_on_segment(ax, ay, bx, by, px, py):
            """Точка на отрезке A-B, в которую опущен перпендикуляр из P. t in [0,1] — на отрезке."""
            abx, aby = bx - ax, by - ay
            apx, apy = px - ax, py - ay
            ab2 = abx*abx + aby*aby
            if ab2 < 1e-20:
                return (ax, ay), 0.0
            t = (apx*abx + apy*aby) / ab2
            t = max(0.0, min(1.0, t))
            foot_x = ax + t * abx
            foot_y = ay + t * aby
            return (foot_x, foot_y), t

        for prim in self.primitives:
            t = prim['type']
            p = prim['params']

            if t == 'segment_mouse':
                foot, _ = foot_on_segment(p['p1'][0], p['p1'][1], p['p2'][0], p['p2'][1], fx, fy)
                if math.hypot(wx - foot[0], wy - foot[1]) < snap_r:
                    cands.append((foot, "Перпендикуляр"))

            elif t == 'polyline':
                pts = p['points']
                for i in range(len(pts) - 1):
                    foot, _ = foot_on_segment(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1], fx, fy)
                    if math.hypot(wx - foot[0], wy - foot[1]) < snap_r:
                        cands.append((foot, "Перпендикуляр"))

            elif t == 'rect':
                pts = p['points']
                for i in range(len(pts)):
                    i2 = (i + 1) % len(pts)
                    foot, _ = foot_on_segment(pts[i][0], pts[i][1], pts[i2][0], pts[i2][1], fx, fy)
                    if math.hypot(wx - foot[0], wy - foot[1]) < snap_r:
                        cands.append((foot, "Перпендикуляр"))

            elif t == 'polygon':
                verts = p['vertices']
                for i in range(len(verts)):
                    i2 = (i + 1) % len(verts)
                    foot, _ = foot_on_segment(verts[i][0], verts[i][1], verts[i2][0], verts[i2][1], fx, fy)
                    if math.hypot(wx - foot[0], wy - foot[1]) < snap_r:
                        cands.append((foot, "Перпендикуляр"))

        return cands

    def _collect_snap_candidates(self):
        """Собираем базовые точки привязки (конец, середина, центр, начало координат).
        Каждый кандидат — кортеж (point, label, ref). ref = {'prim_id', 'src_key'} либо None."""
        cands = []

        # 🔥 Начало мировой системы координат
        if self.snap_modes.get('center'):
            cands.append(((0.0, 0.0), "Начало координат", None))

        # Привязки примитивов (исключая сами размеры)
        for prim in self.primitives:
            t = prim['type']
            p = prim['params']
            pid = prim.get('id')

            # Размеры не служат источниками привязок (чтобы не цеплялись за себя)
            if is_dimension_type(t):
                continue

            if t == 'segment_mouse':
                if self.snap_modes['end']:
                    cands.append((p['p1'], "Конец", {'prim_id': pid, 'src_key': 'p1'}))
                    cands.append((p['p2'], "Конец", {'prim_id': pid, 'src_key': 'p2'}))
                if self.snap_modes['mid']:
                    mid = ((p['p1'][0]+p['p2'][0])/2,
                        (p['p1'][1]+p['p2'][1])/2)
                    cands.append((mid, "Середина", {'prim_id': pid, 'src_key': 'mid'}))

            elif t == 'polyline':
                pts = p['points']
                if self.snap_modes['end'] and pts:
                    cands.append((pts[0], "Конец", {'prim_id': pid, 'src_key': 'pt0'}))
                    cands.append((pts[-1], "Конец", {'prim_id': pid, 'src_key': f'pt{len(pts)-1}'}))
                if self.snap_modes['mid']:
                    for i in range(len(pts)-1):
                        mid = ((pts[i][0]+pts[i+1][0])/2,
                            (pts[i][1]+pts[i+1][1])/2)
                        cands.append((mid, "Середина", None))

            elif t == 'circle':
                cx, cy, r = p['cx'], p['cy'], p['r']
                if self.snap_modes['center']:
                    cands.append(((cx, cy), "Центр", {'prim_id': pid, 'src_key': 'center'}))
                if self.snap_modes['end']:
                    for a in [0, 90, 180, 270]:
                        ar = math.radians(a)
                        cands.append(((cx + r*math.cos(ar),
                                    cy + r*math.sin(ar)), "Квадрант", None))

            elif t == 'arc':
                cx, cy = p['cx'], p['cy']
                r, a1, a2 = p['r'], p['start_angle'], p['end_angle']
                if self.snap_modes['center']:
                    cands.append(((cx, cy), "Центр", {'prim_id': pid, 'src_key': 'center'}))
                if self.snap_modes['end']:
                    cands.append(((cx + r*math.cos(math.radians(a1)),
                                cy + r*math.sin(math.radians(a1))), "Конец",
                                {'prim_id': pid, 'src_key': 'arc_start'}))
                    cands.append(((cx + r*math.cos(math.radians(a2)),
                                cy + r*math.sin(math.radians(a2))), "Конец",
                                {'prim_id': pid, 'src_key': 'arc_end'}))
                if self.snap_modes['mid']:
                    am = (a1 + a2) / 2
                    cands.append(((cx + r*math.cos(math.radians(am)),
                                cy + r*math.sin(math.radians(am))), "Середина", None))

            elif t == 'rect':
                pts = p['points']
                if self.snap_modes['end']:
                    for i, pt in enumerate(pts):
                        cands.append((pt, "Конец", {'prim_id': pid, 'src_key': f'corner{i}'}))

            elif t == 'polygon':
                verts = p['vertices']
                if self.snap_modes['end']:
                    for i, v in enumerate(verts):
                        cands.append((v, "Конец", {'prim_id': pid, 'src_key': f'vert{i}'}))

        return cands

    # ---- Клик на холсте при создании примитива ----
    def prim_canvas_click(self, event):
        wx, wy = self.screen_to_world(event.x, event.y)
        if self.snap_point:
            wx, wy = self.snap_point

        tool = self.current_prim_tool
        method = self.creation_mode.get('method', '')

        # ---- Размеры: специальная обработка первого клика для радиальных ----
        if tool in ('dim_radial_r', 'dim_radial_d') and len(self.prim_points) == 0:
            # Первый клик: выбираем окружность/дугу примитив, ближайшую к точке клика
            target = self._pick_circle_or_arc(wx, wy)
            if target is None:
                self.prim_hint_label.config(
                    text="Не найдено окружность/дугу рядом — кликните на окружность/дугу")
                return
            self.creation_mode['target_prim_id'] = target['id']
            self.creation_mode['target_cx'] = target['params']['cx']
            self.creation_mode['target_cy'] = target['params']['cy']
            self.creation_mode['target_r']  = target['params']['r']
            # Запоминаем точку клика как "псевдоточку" для определения угла
            self.prim_points.append((wx, wy))
            self.prim_creation_step += 1
            self.update_prim_hint()
            return

        # Захватываем ассоциативную привязку (если кликнули на снап-точку с ref'ом)
        if self.snap_point and self.snap_ref:
            if 'snap_refs' not in self.creation_mode:
                self.creation_mode['snap_refs'] = []
            self.creation_mode['snap_refs'].append(dict(self.snap_ref))
        else:
            if 'snap_refs' not in self.creation_mode:
                self.creation_mode['snap_refs'] = []
            self.creation_mode['snap_refs'].append(None)

        self.prim_points.append((wx, wy))
        self.prim_creation_step += 1

        # Проверяем, нужно ли завершить примитив
        done = False

        if tool == 'segment_mouse':
            if len(self.prim_points) == 2:
                done = True

        elif tool == 'polyline':
            # Продолжаем добавлять точки, завершение по Enter/двойному клику
            done = False

        elif tool == 'circle':
            if method in ("Центр и радиус", "Центр и диаметр", "По двум точкам") and len(self.prim_points) == 2:
                done = True
            elif method == "По трём точкам" and len(self.prim_points) == 3:
                done = True

        elif tool == 'arc':
            if len(self.prim_points) == 3:
                done = True

        elif tool == 'rect':
            if len(self.prim_points) == 2:
                done = True

        elif tool == 'ellipse':
            if len(self.prim_points) == 3:
                done = True

        elif tool == 'polygon':
            if len(self.prim_points) == 2:
                done = True

        elif tool == 'spline':
            # Добавляем точки, завершение по двойному клику
            done = False

        elif tool == 'dim_linear':
            if len(self.prim_points) == 3:
                done = True

        elif tool in ('dim_radial_r', 'dim_radial_d'):
            if len(self.prim_points) == 2:
                done = True

        elif tool == 'dim_angular':
            if len(self.prim_points) == 4:
                done = True

        if done:
            self.finalize_primitive()
        else:
            self.update_prim_hint()

    def _pick_circle_or_arc(self, wx, wy):
        """Находит ближайшую окружность или дугу к точке (wx, wy)."""
        best = None
        best_d = float('inf')
        for prim in self.primitives:
            if prim['type'] in ('circle', 'arc'):
                p = prim['params']
                d = abs(math.hypot(wx - p['cx'], wy - p['cy']) - p['r'])
                # Принимаем, если расстояние < 25% радиуса или < 0.7 ед.
                tol = max(0.7, 0.25 * p['r'])
                if d < tol and d < best_d:
                    best_d = d
                    best = prim
        return best

    def on_canvas_double_click(self, event):
        """Двойной клик — завершение многоточечных примитивов."""
        tool = self.current_prim_tool
        if tool in ('spline', 'polyline') and len(self.prim_points) >= 2:
            # Убираем последнюю точку (она дублируется двойным кликом)
            self.prim_points.pop()
            self.finalize_primitive()
        elif tool == 'segment_mouse' and len(self.prim_points) >= 1:
            pass  # для отрезка двойной клик не нужен

    def on_enter_key(self, event=None):
        """Enter — завершить многоточечный примитив (сплайн, ломаная)."""
        tool = self.current_prim_tool
        if tool in ('spline', 'polyline') and len(self.prim_points) >= 2:
            self.finalize_primitive()

    def finalize_primitive(self):
        """Создаём примитив из накопленных точек."""
        tool = self.current_prim_tool
        method = self.creation_mode.get('method', '')
        pts = self.prim_points
        color = self.prim_default_color
        style_name = self.current_style
        
        prim = None
        
        try:
            if tool == 'segment_mouse':
                if len(pts) >= 2:
                    prim = {'type': 'segment_mouse', 'params': {'p1': pts[0], 'p2': pts[1]},
                            'color': color, 'style_name': style_name,
                            'name': f"Отрезок {len(self.primitives)+1}"}

            elif tool == 'polyline':
                if len(pts) >= 2:
                    prim = {'type': 'polyline', 'params': {'points': list(pts)},
                            'color': color, 'style_name': style_name,
                            'name': f"Ломаная {len(self.primitives)+1}"}

            elif tool == 'circle':
                params = self._build_circle_params(method, pts)
                if params:
                    prim = {'type': 'circle', 'params': params, 'color': color,
                            'style_name': style_name, 'name': f"Окружность {len(self.primitives)+1}"}
            
            elif tool == 'arc':
                params = self._build_arc_params(method, pts)
                if params:
                    prim = {'type': 'arc', 'params': params, 'color': color,
                            'style_name': style_name, 'name': f"Дуга {len(self.primitives)+1}"}
            
            elif tool == 'rect':
                params = self._build_rect_params(method, pts)
                if params:
                    prim = {'type': 'rect', 'params': params, 'color': color,
                            'style_name': style_name, 'name': f"Прямоугольник {len(self.primitives)+1}"}
            
            elif tool == 'ellipse':
                params = self._build_ellipse_params(method, pts)
                if params:
                    prim = {'type': 'ellipse', 'params': params, 'color': color,
                            'style_name': style_name, 'name': f"Эллипс {len(self.primitives)+1}"}
            
            elif tool == 'polygon':
                n = self._ask_polygon_sides()
                inscribed = self._ask_polygon_inscribed()
                params = self._build_polygon_params(pts, n, inscribed)
                if params:
                    prim = {'type': 'polygon', 'params': params, 'color': color,
                            'style_name': style_name, 'name': f"Многоугольник {len(self.primitives)+1}"}
            
            elif tool == 'spline':
                if len(pts) >= 2:
                    prim = {'type': 'spline', 'params': {'points': list(pts)}, 'color': color,
                            'style_name': style_name, 'name': f"Сплайн {len(self.primitives)+1}"}

            elif tool == 'dim_linear':
                prim = self._build_dim_linear(pts, method)

            elif tool == 'dim_radial_r':
                prim = self._build_dim_radial(pts, kind='radius')

            elif tool == 'dim_radial_d':
                prim = self._build_dim_radial(pts, kind='diameter')

            elif tool == 'dim_angular':
                prim = self._build_dim_angular(pts)

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать примитив: {e}")

        if prim:
            # Назначаем уникальный id (для ассоциативности)
            prim['id'] = self._next_prim_id
            self._next_prim_id += 1
            self.primitives.append(prim)
            self._sync_segments_from_primitives()
            self.update_prims_list()
            self.update_segments_list()

        self._reset_prim_tool()
        self.redraw_all()

    # ---- Построители размеров ----
    def _build_dim_linear(self, pts, method):
        if len(pts) < 3:
            return None
        orient_map = {
            "Выровненный":    LinearDimension.ORIENT_ALIGNED,
            "Горизонтальный": LinearDimension.ORIENT_HORIZONTAL,
            "Вертикальный":   LinearDimension.ORIENT_VERTICAL,
        }
        orientation = orient_map.get(method, LinearDimension.ORIENT_ALIGNED)
        # Ассоциативные ссылки для p1 и p2 (если были захвачены snap'ом)
        refs = self.creation_mode.get('snap_refs', [])
        assoc = []
        if len(refs) >= 1 and refs[0]:
            assoc.append({'point_key': 'p1', **refs[0]})
        if len(refs) >= 2 and refs[1]:
            assoc.append({'point_key': 'p2', **refs[1]})
        dim = LinearDimension(pts[0], pts[1], pts[2],
                              orientation=orientation,
                              assoc=assoc, **self.dim_defaults)
        return {'type': dim.KIND, 'params': dim.to_params(),
                'color': self.dim_defaults['line_color'],
                'style_name': self.dim_defaults['dim_style'],
                'name': f"Размер лин. {len(self.primitives)+1}"}

    def _build_dim_radial(self, pts, kind='radius'):
        if len(pts) < 2:
            return None
        cx = self.creation_mode.get('target_cx')
        cy = self.creation_mode.get('target_cy')
        r  = self.creation_mode.get('target_r')
        target_id = self.creation_mode.get('target_prim_id')
        if cx is None or r is None:
            return None
        # Угол радиальной линии — от центра к точке текста
        text_pt = pts[1]
        angle = math.degrees(math.atan2(text_pt[1] - cy, text_pt[0] - cx))
        assoc = [{'point_key': 'circle', 'prim_id': target_id, 'src_key': 'circle'}] if target_id else []
        # У диаметра по ЕСКД по умолчанию надпись на полке-выноске
        defaults = dict(self.dim_defaults)
        if kind == 'diameter':
            defaults['with_shelf'] = True
        dim = RadialDimension(cx, cy, r, angle, kind=kind,
                              text_pos=text_pt, assoc=assoc,
                              **defaults)
        type_label = 'диаметр' if kind == 'diameter' else 'радиус'
        return {'type': dim.KIND, 'params': dim.to_params(),
                'color': self.dim_defaults['line_color'],
                'style_name': self.dim_defaults['dim_style'],
                'name': f"Размер {type_label} {len(self.primitives)+1}"}

    def _build_dim_angular(self, pts):
        if len(pts) < 4:
            return None
        vertex, p1, p2, dim_pos = pts[0], pts[1], pts[2], pts[3]
        # Радиус дуги = расстояние от вершины до точки положения
        arc_r = math.hypot(dim_pos[0]-vertex[0], dim_pos[1]-vertex[1])
        if arc_r < 1e-6:
            arc_r = max(math.hypot(p1[0]-vertex[0], p1[1]-vertex[1]),
                        math.hypot(p2[0]-vertex[0], p2[1]-vertex[1])) * 0.6
        refs = self.creation_mode.get('snap_refs', [])
        assoc = []
        for i, key in enumerate(('vertex', 'p1', 'p2')):
            if i < len(refs) and refs[i]:
                assoc.append({'point_key': key, **refs[i]})
        dim = AngularDimension(vertex, p1, p2, arc_r,
                               assoc=assoc, **self.dim_defaults)
        return {'type': dim.KIND, 'params': dim.to_params(),
                'color': self.dim_defaults['line_color'],
                'style_name': self.dim_defaults['dim_style'],
                'name': f"Размер угл. {len(self.primitives)+1}"}

    # ---- Построители параметров примитивов ----
    def _build_circle_params(self, method, pts):
        if method == "Центр и радиус":
            cx, cy = pts[0]
            r = math.hypot(pts[1][0]-cx, pts[1][1]-cy)
            return {'cx': cx, 'cy': cy, 'r': r}
        
        elif method == "Центр и диаметр":
            cx, cy = pts[0]
            d = math.hypot(pts[1][0]-cx, pts[1][1]-cy)
            return {'cx': cx, 'cy': cy, 'r': d/2}
        
        elif method == "По двум точкам":
            # Диаметр задан двумя точками
            cx = (pts[0][0] + pts[1][0]) / 2
            cy = (pts[0][1] + pts[1][1]) / 2
            r = math.hypot(pts[1][0]-pts[0][0], pts[1][1]-pts[0][1]) / 2
            return {'cx': cx, 'cy': cy, 'r': r}
        
        elif method == "По трём точкам":
            # Описанная окружность через три точки
            ax, ay = pts[0]; bx, by = pts[1]; cx_, cy_ = pts[2]
            d = 2*(ax*(by-cy_) + bx*(cy_-ay) + cx_*(ay-by))
            if abs(d) < 1e-10:
                return None
            ux = ((ax**2+ay**2)*(by-cy_) + (bx**2+by**2)*(cy_-ay) + (cx_**2+cy_**2)*(ay-by)) / d
            uy = ((ax**2+ay**2)*(cx_-bx) + (bx**2+by**2)*(ax-cx_) + (cx_**2+cy_**2)*(bx-ax)) / d
            r = math.hypot(ax-ux, ay-uy)
            return {'cx': ux, 'cy': uy, 'r': r}
        return None

    def _build_arc_params(self, method, pts):
        if method == "Три точки":
            # Дуга через три точки: находим центр, потом углы
            ax, ay = pts[0]; bx, by = pts[1]; cx_, cy_ = pts[2]
            d = 2*(ax*(by-cy_) + bx*(cy_-ay) + cx_*(ay-by))
            if abs(d) < 1e-10:
                return None
            ux = ((ax**2+ay**2)*(by-cy_) + (bx**2+by**2)*(cy_-ay) + (cx_**2+cy_**2)*(ay-by)) / d
            uy = ((ax**2+ay**2)*(cx_-bx) + (bx**2+by**2)*(ax-cx_) + (cx_**2+cy_**2)*(bx-ax)) / d
            r = math.hypot(ax-ux, ay-uy)
            a1 = math.degrees(math.atan2(ay-uy, ax-ux))
            a2 = math.degrees(math.atan2(cy_-uy, cx_-ux))
            return {'cx': ux, 'cy': uy, 'r': r, 'start_angle': a1, 'end_angle': a2}
        
        elif method == "Центр, нач. угол, кон. угол":
            cx, cy = pts[0]
            r = math.hypot(pts[1][0]-cx, pts[1][1]-cy)
            a1 = math.degrees(math.atan2(pts[1][1]-cy, pts[1][0]-cx))
            a2 = math.degrees(math.atan2(pts[2][1]-cy, pts[2][0]-cx))
            return {'cx': cx, 'cy': cy, 'r': r, 'start_angle': a1, 'end_angle': a2}
        return None

    def _build_rect_params(self, method, pts):
        if method in ("Две противоположные точки", "Точка + ширина + высота"):
            x1, y1 = pts[0]; x2, y2 = pts[1]
            corners = [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]
            return {'points': corners, 'chamfer': 0, 'fillet': 0}
        
        elif method == "Центр + ширина + высота":
            cx, cy = pts[0]
            x2, y2 = pts[1]
            hw = abs(x2-cx); hh = abs(y2-cy)
            corners = [(cx-hw,cy-hh),(cx+hw,cy-hh),(cx+hw,cy+hh),(cx-hw,cy+hh)]
            return {'points': corners, 'chamfer': 0, 'fillet': 0}
        return None

    def _build_ellipse_params(self, method, pts):
        cx, cy = pts[0]
        rx = math.hypot(pts[1][0]-cx, pts[1][1]-cy)
        ry = math.hypot(pts[2][0]-cx, pts[2][1]-cy)
        angle = math.degrees(math.atan2(pts[1][1]-cy, pts[1][0]-cx))
        return {'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry, 'angle': angle}

    def _build_polygon_params(self, pts, n, inscribed):
        cx, cy = pts[0]
        r = math.hypot(pts[1][0]-cx, pts[1][1]-cy)
        # Match preview: first vertex at 0° (world +X). Preview uses a = i*360/n with no base_angle.
        base_angle = 0.0
        if not inscribed:
            r = r / math.cos(math.pi/n)
        verts = []
        for i in range(n):
            a = math.radians(base_angle + i * 360/n)
            verts.append((cx + r*math.cos(a), cy + r*math.sin(a)))
        return {'cx': cx, 'cy': cy, 'r': r, 'n': n, 'inscribed': inscribed,
                'vertices': verts, 'base_angle': base_angle, 'rotation_angle': 0.0}

    def _ask_polygon_sides(self):
        val = simpledialog.askinteger("Многоугольник", "Количество сторон:", initialvalue=6, minvalue=3, maxvalue=100)
        return val if val else 6

    def _ask_polygon_inscribed(self):
        return messagebox.askyesno("Многоугольник", "Вписанный? (Нет = описанный)")

    # ---- Превью при создании ----
    def update_prim_preview(self, sx, sy):
        self.clear_prim_preview()
        wx, wy = self.screen_to_world(sx, sy)
        if self.snap_point:
            wx, wy = self.snap_point
        
        tool = self.current_prim_tool
        method = self.creation_mode.get('method', '')
        pts = self.prim_points + [(wx, wy)]
        
        try:
            if tool == 'segment_mouse' and len(pts) >= 2:
                p1s = self.world_to_screen(*pts[0])
                p2s = self.world_to_screen(*pts[1])
                self.canvas.create_line(*p1s, *p2s, fill="#888888", width=1, dash=(4,4), tags="prim_preview")
            
            elif tool == 'polyline' and len(pts) >= 2:
                screen_pts = [c for p in pts for c in self.world_to_screen(*p)]
                self.canvas.create_line(*screen_pts, fill="#888888", width=1, dash=(4,4), tags="prim_preview")
            
            elif tool == 'circle' and len(pts) >= 2:
                params = self._build_circle_params(method, pts[:2] if method != "По трём точкам" else pts[:3])
                if params:
                    self._preview_circle(params)
            
            elif tool == 'arc' and len(pts) >= 3:
                params = self._build_arc_params(method, pts[:3])
                if params:
                    self._preview_arc(params)
            
            elif tool == 'rect' and len(pts) >= 2:
                params = self._build_rect_params(method, pts[:2])
                if params:
                    self._preview_rect(params)
            
            elif tool == 'ellipse' and len(pts) >= 3:
                params = self._build_ellipse_params(method, pts[:3])
                if params:
                    self._preview_ellipse(params)
            
            elif tool == 'polygon' and len(pts) >= 2:
                self._preview_polygon_approx(pts[0], (wx, wy))
            
            elif tool == 'spline' and len(pts) >= 2:
                self._preview_spline(pts)

            elif tool == 'dim_linear' and len(pts) >= 2:
                # Превью: показываем линию между p1 и p2 пунктиром,
                # и (если есть 3-я точка) — размерную линию
                p1s = self.world_to_screen(*pts[0])
                p2s = self.world_to_screen(*pts[1])
                self.canvas.create_line(*p1s, *p2s, fill="#FFA500", width=1, dash=(2,3),
                                         tags="prim_preview")
                if len(pts) >= 3:
                    method = self.creation_mode.get('method', '')
                    orient_map = {
                        "Выровненный":    LinearDimension.ORIENT_ALIGNED,
                        "Горизонтальный": LinearDimension.ORIENT_HORIZONTAL,
                        "Вертикальный":   LinearDimension.ORIENT_VERTICAL,
                    }
                    orient = orient_map.get(method, LinearDimension.ORIENT_ALIGNED)
                    dim = LinearDimension(pts[0], pts[1], pts[2], orientation=orient,
                                          **self.dim_defaults)
                    g = dim.geometry()
                    e1s = self.world_to_screen(*g['e1'])
                    e2s = self.world_to_screen(*g['e2'])
                    self.canvas.create_line(*e1s, *e2s, fill="#888888", width=1,
                                             dash=(4,4), tags="prim_preview")

            elif tool in ('dim_radial_r', 'dim_radial_d') and len(pts) >= 1:
                cx = self.creation_mode.get('target_cx')
                cy = self.creation_mode.get('target_cy')
                r  = self.creation_mode.get('target_r')
                if cx is not None and r is not None:
                    text_pt = pts[-1]
                    a = math.atan2(text_pt[1] - cy, text_pt[0] - cx)
                    on_circle = (cx + r*math.cos(a), cy + r*math.sin(a))
                    sc = self.world_to_screen(cx, cy)
                    so = self.world_to_screen(*on_circle)
                    st = self.world_to_screen(*text_pt)
                    self.canvas.create_line(*sc, *so, fill="#888888", width=1,
                                             dash=(4,4), tags="prim_preview")
                    self.canvas.create_line(*so, *st, fill="#888888", width=1,
                                             dash=(4,4), tags="prim_preview")

            elif tool == 'dim_angular' and len(pts) >= 3:
                v = pts[0]
                pp1, pp2 = pts[1], pts[2]
                # дуги ещё нет — покажем лучи
                for q in (pp1, pp2):
                    sv = self.world_to_screen(*v)
                    sq = self.world_to_screen(*q)
                    self.canvas.create_line(*sv, *sq, fill="#FFA500", width=1,
                                             dash=(2,3), tags="prim_preview")
                if len(pts) >= 4:
                    arc_r = math.hypot(pts[3][0]-v[0], pts[3][1]-v[1])
                    a1 = math.atan2(pp1[1]-v[1], pp1[0]-v[0])
                    a2 = math.atan2(pp2[1]-v[1], pp2[0]-v[0])
                    d = a2 - a1
                    while d >  math.pi: d -= 2*math.pi
                    while d < -math.pi: d += 2*math.pi
                    steps = 32
                    pts_s = []
                    for i in range(steps+1):
                        a = a1 + d * (i/steps)
                        wp = (v[0] + arc_r*math.cos(a), v[1] + arc_r*math.sin(a))
                        sxx, syy = self.world_to_screen(*wp)
                        pts_s.extend([sxx, syy])
                    if len(pts_s) >= 4:
                        self.canvas.create_line(*pts_s, fill="#888888", width=1,
                                                 dash=(4,4), tags="prim_preview")
        except:
            pass
        
        # Рисуем уже введённые точки
        for pt in self.prim_points:
            px, py = self.world_to_screen(*pt)
            self.canvas.create_oval(px-4, py-4, px+4, py+4, fill="#FF6600", outline="#CC4400", tags="prim_preview")

    def _preview_circle(self, params):
        world_pts = self._circle_world_points(params['cx'], params['cy'], params['r'])
        screen_pts = [c for wp in world_pts for c in self.world_to_screen(*wp)]
        self.canvas.create_line(*screen_pts, fill="#888888", width=1, dash=(4,4), tags="prim_preview")

    def _preview_arc(self, params):
        world_pts = self._arc_world_points(params['cx'], params['cy'], params['r'],
                                            params['start_angle'], params['end_angle'])
        screen_pts = [c for wp in world_pts for c in self.world_to_screen(*wp)]
        if len(screen_pts) >= 4:
            self.canvas.create_line(*screen_pts, fill="#888888", width=1, dash=(4,4), tags="prim_preview")

    def _preview_rect(self, params):
        pts_loop = params['points'] + [params['points'][0]]
        for i in range(len(pts_loop)-1):
            ax, ay = self.world_to_screen(*pts_loop[i])
            bx, by = self.world_to_screen(*pts_loop[i+1])
            self.canvas.create_line(ax, ay, bx, by, fill="#888888", width=1, dash=(4,4), tags="prim_preview")

    def _preview_ellipse(self, params):
        world_pts = self._ellipse_world_points(params['cx'], params['cy'],
                                                params['rx'], params['ry'], params['angle'])
        screen_pts = [c for wp in world_pts for c in self.world_to_screen(*wp)]
        if len(screen_pts) >= 4:
            self.canvas.create_line(*screen_pts, fill="#888888", width=1, dash=(4,4), tags="prim_preview")

    def _preview_polygon_approx(self, center, pt2):
        cx, cy = center
        r = math.hypot(pt2[0]-cx, pt2[1]-cy)
        n = 6
        pts = []
        for i in range(n+1):
            a = math.radians(i*360/n)
            sx, sy = self.world_to_screen(cx+r*math.cos(a), cy+r*math.sin(a))
            pts += [sx, sy]
        self.canvas.create_line(*pts, fill="#888888", width=1, dash=(4,4), tags="prim_preview")

    def _preview_spline(self, pts):
        world_pts = self._spline_world_points(pts)
        screen_pts = [c for wp in world_pts for c in self.world_to_screen(*wp)]
        if len(screen_pts) >= 4:
            self.canvas.create_line(*screen_pts, fill="#888888", width=1, dash=(4,4), tags="prim_preview")

    # ---- Рисование готовых примитивов ----
    def draw_primitive(self, prim, selected=False):
        t = prim['type']
        p = prim['params']
        color = prim['color']
        style = self.line_styles.get(prim['style_name'], {'type': 'solid', 'width': 1.5})
        width = style['width']
        sel_color = "#00AAFF" if selected else color
        
        if t == 'segment_mouse':
            p1s = self.world_to_screen(*p['p1'])
            p2s = self.world_to_screen(*p['p2'])
            self.draw_styled_line(self.canvas, p1s[0], p1s[1], p2s[0], p2s[1],
                                  style, sel_color, tags="primitive")
            # Точки и метки координат
            r = 5
            self.canvas.create_oval(p1s[0]-r, p1s[1]-r, p1s[0]+r, p1s[1]+r,
                                    fill=sel_color, tags="primitive")
            self.canvas.create_oval(p2s[0]-r, p2s[1]-r, p2s[0]+r, p2s[1]+r,
                                    fill=sel_color, tags="primitive")
            self.canvas.create_text(p1s[0], p1s[1]-15,
                                    text=f"P({p['p1'][0]:.1f}, {p['p1'][1]:.1f})",
                                    font=("Arial", 8), fill=sel_color, tags="primitive")
            self.canvas.create_text(p2s[0], p2s[1]-15,
                                    text=f"P({p['p2'][0]:.1f}, {p['p2'][1]:.1f})",
                                    font=("Arial", 8), fill=sel_color, tags="primitive")
            if selected:
                self._draw_ctrl_point(*p1s)
                self._draw_ctrl_point(*p2s)
        
        elif t == 'polyline':
            pts_w = p['points']
            for i in range(len(pts_w) - 1):
                a = self.world_to_screen(*pts_w[i])
                b = self.world_to_screen(*pts_w[i+1])
                self.draw_styled_line(self.canvas, a[0], a[1], b[0], b[1],
                                      style, sel_color, tags="primitive")
            if selected:
                for pt in pts_w:
                    px, py = self.world_to_screen(*pt)
                    self._draw_ctrl_point(px, py)
        
        elif t == 'circle':
            # Генерируем точки и рисуем со стилем
            world_pts = self._circle_world_points(p['cx'], p['cy'], p['r'])
            self._draw_styled_curve(world_pts, style, sel_color, closed=True)
            if selected:
                cx, cy = self.world_to_screen(p['cx'], p['cy'])
                self._draw_ctrl_point(cx, cy)
                cxr, cyr = self.world_to_screen(p['cx'] + p['r'], p['cy'])
                self._draw_ctrl_point(cxr, cyr)
        
        elif t == 'arc':
            world_pts = self._arc_world_points(p['cx'], p['cy'], p['r'], p['start_angle'], p['end_angle'])
            self._draw_styled_curve(world_pts, style, sel_color, closed=False)
            if selected:
                cx, cy = self.world_to_screen(p['cx'], p['cy'])
                self._draw_ctrl_point(cx, cy)
        
        elif t == 'rect':
            corners_s = [self.world_to_screen(*pt) for pt in p['points']]
            pts_loop = p['points'] + [p['points'][0]]
            for i in range(len(pts_loop)-1):
                a, b = pts_loop[i], pts_loop[i+1]
                ax, ay = self.world_to_screen(*a)
                bx, by = self.world_to_screen(*b)
                self.draw_styled_line(self.canvas, ax, ay, bx, by, style, sel_color, tags="primitive")
            if selected:
                for cs in corners_s:
                    self._draw_ctrl_point(*cs)
        
        elif t == 'ellipse':
            world_pts = self._ellipse_world_points(p['cx'], p['cy'], p['rx'], p['ry'], p['angle'])
            self._draw_styled_curve(world_pts, style, sel_color, closed=True)
            if selected:
                cx, cy = self.world_to_screen(p['cx'], p['cy'])
                self._draw_ctrl_point(cx, cy)
        
        elif t == 'polygon':
            verts = p['vertices'] + [p['vertices'][0]]
            for i in range(len(verts)-1):
                ax, ay = self.world_to_screen(*verts[i])
                bx, by = self.world_to_screen(*verts[i+1])
                self.draw_styled_line(self.canvas, ax, ay, bx, by, style, sel_color, tags="primitive")
            if selected:
                for v in p['vertices']:
                    self._draw_ctrl_point(*self.world_to_screen(*v))
        
        elif t == 'spline':
            world_pts = self._spline_world_points(p['points'])
            self._draw_styled_curve(world_pts, style, sel_color, closed=False)
            if selected:
                for pt in p['points']:
                    px, py = self.world_to_screen(*pt)
                    self._draw_ctrl_point(px, py)

        elif is_dimension_type(t):
            self._draw_dimension(prim, selected=selected)

    # ====================================================================
    #                    Отрисовка размеров по ЕСКД
    # ====================================================================
    def _find_prim_by_id(self, pid):
        if pid is None:
            return None
        for pr in self.primitives:
            if pr.get('id') == pid:
                return pr
        return None

    def _resolve_assoc_point(self, ref):
        """Возвращает актуальные координаты точки по ассоциативной ссылке либо None."""
        if not ref:
            return None
        src = self._find_prim_by_id(ref.get('prim_id'))
        if src is None:
            return None
        key = ref.get('src_key')
        sp = src['params']
        st = src['type']
        try:
            if st == 'segment_mouse':
                if key == 'p1': return sp['p1']
                if key == 'p2': return sp['p2']
                if key == 'mid':
                    return ((sp['p1'][0]+sp['p2'][0])/2, (sp['p1'][1]+sp['p2'][1])/2)
            elif st == 'polyline':
                if key and key.startswith('pt'):
                    idx = int(key[2:])
                    pts = sp['points']
                    if 0 <= idx < len(pts):
                        return pts[idx]
            elif st in ('circle', 'arc'):
                if key == 'center':
                    return (sp['cx'], sp['cy'])
                if key == 'circle':
                    return (sp['cx'], sp['cy'])
            elif st == 'rect':
                if key and key.startswith('corner'):
                    idx = int(key[6:])
                    pts = sp['points']
                    if 0 <= idx < len(pts):
                        return pts[idx]
            elif st == 'polygon':
                if key and key.startswith('vert'):
                    idx = int(key[4:])
                    verts = sp['vertices']
                    if 0 <= idx < len(verts):
                        return verts[idx]
        except Exception:
            return None
        return None

    def _refresh_dim_assoc(self, prim):
        """Пересчитывает p1/p2/cx/cy и т.п. размера из ассоциативных ссылок."""
        params = prim['params']
        for ref in params.get('assoc', []):
            pt = self._resolve_assoc_point(ref)
            if pt is None:
                continue
            key = ref.get('point_key')
            if key in ('p1', 'p2', 'vertex'):
                params[key] = pt
            elif key == 'circle':
                # точка-центр окружности
                params['cx'] = pt[0]
                params['cy'] = pt[1]
                # также обновить r из исходной окружности, если возможно
                src = self._find_prim_by_id(ref.get('prim_id'))
                if src and src['type'] in ('circle', 'arc'):
                    params['r'] = src['params']['r']

    def _draw_dimension(self, prim, selected=False):
        """Рисует размер по ЕСКД ГОСТ 2.307-2011."""
        # Обновляем поля по ассоциативным ссылкам (если есть)
        self._refresh_dim_assoc(prim)

        try:
            dim = make_dimension(prim['type'], prim['params'])
        except Exception:
            return

        sel_color = "#00AAFF" if selected else (prim.get('color') or dim.line_color)
        text_color = sel_color if selected else dim.text_color
        ext_style = self.line_styles.get(dim.ext_style, {'type': 'solid', 'width': 1.0})
        dim_style = self.line_styles.get(dim.dim_style, {'type': 'solid', 'width': 1.0})

        if isinstance(dim, LinearDimension):
            self._draw_dim_linear(dim, sel_color, text_color, ext_style, dim_style, selected)
        elif isinstance(dim, RadialDimension):
            self._draw_dim_radial(dim, sel_color, text_color, dim_style, selected)
        elif isinstance(dim, AngularDimension):
            self._draw_dim_angular(dim, sel_color, text_color, dim_style, selected)

    def _scr(self, pt):
        return self.world_to_screen(pt[0], pt[1])

    def _draw_dim_arrow(self, tip_world, dir_world, size_world, color, filled=True):
        """Рисует одну стрелку в мировых координатах."""
        tri = arrow_polygon(tip_world, dir_world, size_world)
        sx = []
        for pt in tri:
            x, y = self._scr(pt)
            sx.extend([x, y])
        if filled:
            self.canvas.create_polygon(*sx, fill=color, outline=color, tags="primitive")
        else:
            self.canvas.create_polygon(*sx, fill='', outline=color, width=1.2, tags="primitive")

    def _draw_dim_linear(self, dim, color, text_color, ext_style, dim_style, selected):
        g = dim.geometry()
        e1, e2 = g['e1'], g['e2']
        p1, p2 = g['p1'], g['p2']
        nrm = g['normal']

        # Длина по размерной линии
        L = math.hypot(e2[0]-e1[0], e2[1]-e1[1])
        if L < 1e-9:
            return
        dir_ = ((e2[0]-e1[0])/L, (e2[1]-e1[1])/L)

        # --- 1. Выносные линии ---
        # От точки измерения, со зазором ext_offset до проекции, с выходом ext_overshoot за неё
        for src, foot in ((p1, e1), (p2, e2)):
            vx = foot[0] - src[0]
            vy = foot[1] - src[1]
            vl = math.hypot(vx, vy)
            if vl < 1e-9:
                # точка измерения совпадает с проекцией — рисуем перпендикуляр
                vx, vy = nrm
                vl = 1.0
            ux, uy = vx/vl, vy/vl
            # начало с зазором от точки измерения
            start = (src[0] + ux * dim.ext_offset, src[1] + uy * dim.ext_offset)
            end   = (foot[0] + ux * dim.ext_overshoot, foot[1] + uy * dim.ext_overshoot)
            sx1, sy1 = self._scr(start)
            sx2, sy2 = self._scr(end)
            self.draw_styled_line(self.canvas, sx1, sy1, sx2, sy2,
                                   ext_style, color, tags="primitive")

        # --- 2. Размерная линия (с расширением dim_extension за выносные) ---
        ext = dim.dim_extension
        L_world = (dir_[0] * ext, dir_[1] * ext)
        d1 = (e1[0] - L_world[0], e1[1] - L_world[1])
        d2 = (e2[0] + L_world[0], e2[1] + L_world[1])
        sx1, sy1 = self._scr(d1)
        sx2, sy2 = self._scr(d2)
        self.draw_styled_line(self.canvas, sx1, sy1, sx2, sy2,
                               dim_style, color, tags="primitive")

        # --- 3. Стрелки на концах размерной линии (направлены наружу к выносным) ---
        self._draw_dim_arrow(e1, (-dir_[0], -dir_[1]), dim.arrow_size, color, dim.arrow_filled)
        self._draw_dim_arrow(e2,  dir_,                dim.arrow_size, color, dim.arrow_filled)

        # --- 4. Текст ---
        mid = ((e1[0]+e2[0])/2, (e1[1]+e2[1])/2)
        # Смещаем текст от размерной линии на text_height/2 в сторону, противоположную геометрии
        # ЕСКД: текст над размерной линией со стороны, противоположной геометрии
        avg_geom = ((p1[0]+p2[0])/2, (p1[1]+p2[1])/2)
        vec_to_geom = (avg_geom[0] - mid[0], avg_geom[1] - mid[1])
        side = vec_to_geom[0]*nrm[0] + vec_to_geom[1]*nrm[1]
        text_nrm = nrm if side < 0 else (-nrm[0], -nrm[1])
        offset = dim.text_height * 0.7
        tx = mid[0] + text_nrm[0] * offset
        ty = mid[1] + text_nrm[1] * offset
        sxt, syt = self._scr((tx, ty))

        # Размер шрифта в пикселях по экрану
        font_size = max(8, int(dim.text_height * self.scale * self.grid_step * 0.9))
        # Угол поворота текста по направлению размерной линии
        # tkinter angle: 0 — горизонтально, поворот против часовой
        # Текст ориентируется ПАРАЛЛЕЛЬНО размерной линии (ЕСКД ГОСТ 2.307-2011 п.4.6).
        # Tk angle: положительный = против часовой; world Y направлена вверх,
        # screen Y — вниз, поэтому учитываем поворот вьюпорта вычитанием.
        text_angle_deg = math.degrees(math.atan2(dir_[1], dir_[0]))
        text_angle_deg -= math.degrees(self.rotation)
        # Нормализуем в диапазон (-90, 90], чтобы текст не был перевёрнут.
        while text_angle_deg > 90:
            text_angle_deg -= 180
        while text_angle_deg <= -90:
            text_angle_deg += 180

        self.canvas.create_text(sxt, syt, text=dim.label(),
                                 fill=text_color,
                                 font=("Arial", font_size),
                                 angle=text_angle_deg,
                                 tags="primitive")
        if selected:
            for pt in (p1, p2, e1, e2, dim.dim_pos):
                self._draw_ctrl_point(*self._scr(pt))

    def _draw_dim_radial(self, dim, color, text_color, dim_style, selected):
        g = dim.geometry()
        cx, cy = g['center']
        on_circle = g['on_circle']
        opp = g['opposite']
        text_pos = g['text_pos'] or on_circle
        kind = g['kind']

        # Размерная линия
        if kind == RadialDimension.KIND_DIAMETER:
            # Диаметр: линия через центр от opp к on_circle
            sx1, sy1 = self._scr(opp)
            sx2, sy2 = self._scr(on_circle)
            self.draw_styled_line(self.canvas, sx1, sy1, sx2, sy2,
                                   dim_style, color, tags="primitive")
            # Стрелки на обоих концах, направлены наружу
            d1 = (on_circle[0]-cx, on_circle[1]-cy)
            l1 = math.hypot(*d1) or 1
            self._draw_dim_arrow(on_circle, (d1[0]/l1, d1[1]/l1),
                                  dim.arrow_size, color, dim.arrow_filled)
            d2 = (opp[0]-cx, opp[1]-cy)
            l2 = math.hypot(*d2) or 1
            self._draw_dim_arrow(opp, (d2[0]/l2, d2[1]/l2),
                                  dim.arrow_size, color, dim.arrow_filled)
        else:
            # Радиус: от центра к точке на окружности
            sx1, sy1 = self._scr((cx, cy))
            sx2, sy2 = self._scr(on_circle)
            self.draw_styled_line(self.canvas, sx1, sy1, sx2, sy2,
                                   dim_style, color, tags="primitive")
            d1 = (on_circle[0]-cx, on_circle[1]-cy)
            l1 = math.hypot(*d1) or 1
            self._draw_dim_arrow(on_circle, (d1[0]/l1, d1[1]/l1),
                                  dim.arrow_size, color, dim.arrow_filled)

        # Линия-выноска от on_circle до text_pos (если text_pos снаружи)
        d_text_to_center = math.hypot(text_pos[0]-cx, text_pos[1]-cy)
        text_outside = d_text_to_center > dim.r * 1.05
        if text_outside:
            sx1, sy1 = self._scr(on_circle)
            sx2, sy2 = self._scr(text_pos)
            self.draw_styled_line(self.canvas, sx1, sy1, sx2, sy2,
                                   dim_style, color, tags="primitive")

        font_size = max(8, int(dim.text_height * self.scale * self.grid_step * 0.9))
        label = dim.label()
        with_shelf = bool(getattr(dim, 'with_shelf', False)) and text_outside

        if with_shelf:
            # Полка: горизонтальный отрезок в направлении от центра к text_pos.
            # Длина полки ≈ ширина надписи в мировых единицах.
            shelf_len = max(len(label) * dim.text_height * 0.7,
                            dim.text_height * 2.0)
            sign = 1.0 if text_pos[0] >= cx else -1.0
            shelf_end = (text_pos[0] + sign * shelf_len, text_pos[1])
            sx1, sy1 = self._scr(text_pos)
            sx2, sy2 = self._scr(shelf_end)
            self.draw_styled_line(self.canvas, sx1, sy1, sx2, sy2,
                                   dim_style, color, tags="primitive")
            # Текст по центру полки, над ней
            tx = (text_pos[0] + shelf_end[0]) / 2.0
            sxt, syt = self._scr((tx, text_pos[1]))
            self.canvas.create_text(sxt, syt - font_size * 0.7,
                                     text=label, fill=text_color,
                                     font=("Arial", font_size),
                                     tags="primitive")
        else:
            sxt, syt = self._scr(text_pos)
            self.canvas.create_text(sxt, syt - font_size - 2, text=label,
                                     fill=text_color,
                                     font=("Arial", font_size),
                                     tags="primitive")
        if selected:
            self._draw_ctrl_point(*self._scr((cx, cy)))
            self._draw_ctrl_point(*self._scr(on_circle))
            self._draw_ctrl_point(*self._scr(text_pos))

    def _draw_dim_angular(self, dim, color, text_color, dim_style, selected):
        g = dim.geometry()
        v = g['vertex']
        a1, a2 = g['a1'], g['a2']
        mid = g['mid']
        R = g['arc_radius']
        p1, p2 = g['p1'], g['p2']

        # Выносные линии — продолжаем лучи vertex→p1 и vertex→p2 до радиуса R
        for ray_pt in (p1, p2):
            dx = ray_pt[0] - v[0]
            dy = ray_pt[1] - v[1]
            l = math.hypot(dx, dy) or 1
            ux, uy = dx/l, dy/l
            arc_end  = (v[0] + ux * (R + dim.ext_overshoot),
                         v[1] + uy * (R + dim.ext_overshoot))
            # выносная начинается чуть дальше геометрической точки
            ext_start = (v[0] + ux * (l + dim.ext_offset),
                          v[1] + uy * (l + dim.ext_offset))
            sx1, sy1 = self._scr(ext_start)
            sx2, sy2 = self._scr(arc_end)
            self.draw_styled_line(self.canvas, sx1, sy1, sx2, sy2,
                                   dim_style, color, tags="primitive")

        # Размерная дуга: интерполируем по углам от a1 до a2 в направлении sign
        steps = 48
        d = a2 - a1
        while d > math.pi: d -= 2*math.pi
        while d < -math.pi: d += 2*math.pi
        screen_pts = []
        for i in range(steps + 1):
            t = i / steps
            a = a1 + d * t
            wp = (v[0] + R * math.cos(a), v[1] + R * math.sin(a))
            sxx, syy = self._scr(wp)
            screen_pts.extend([sxx, syy])
        if len(screen_pts) >= 4:
            self.canvas.create_line(*screen_pts, fill=color,
                                     width=dim_style.get('width', 1.0),
                                     tags="primitive")

        # Стрелки на концах дуги — касательно к дуге
        end1 = (v[0] + R * math.cos(a1), v[1] + R * math.sin(a1))
        end2 = (v[0] + R * math.cos(a2), v[1] + R * math.sin(a2))
        # Касательная: перпендикуляр к радиусу, в направлении дуги
        s = 1.0 if d >= 0 else -1.0
        tan1 = (-math.sin(a1) * s, math.cos(a1) * s)
        tan2 = ( math.sin(a2) * s, -math.cos(a2) * s)
        # Стрелки направлены вдоль дуги наружу из угловой меры
        self._draw_dim_arrow(end1, (-tan1[0], -tan1[1]),
                              dim.arrow_size, color, dim.arrow_filled)
        self._draw_dim_arrow(end2, (-tan2[0], -tan2[1]),
                              dim.arrow_size, color, dim.arrow_filled)

        # Текст в середине дуги, параллельно касательной к дуге (ЕСКД).
        text_offset = dim.text_height * 0.7
        mid_pt = (v[0] + (R + text_offset) * math.cos(mid),
                   v[1] + (R + text_offset) * math.sin(mid))
        sxt, syt = self._scr(mid_pt)
        font_size = max(8, int(dim.text_height * self.scale * self.grid_step * 0.9))
        # Касательная к дуге в точке mid: перпендикуляр к радиусу
        tan_angle = math.degrees(mid) + 90.0
        tan_angle -= math.degrees(self.rotation)
        while tan_angle > 90:
            tan_angle -= 180
        while tan_angle <= -90:
            tan_angle += 180
        self.canvas.create_text(sxt, syt, text=dim.label(),
                                 fill=text_color,
                                 font=("Arial", font_size),
                                 angle=tan_angle,
                                 tags="primitive")
        if selected:
            # Грипперы: ВЕРШИНА, концы лучей P1/P2, плюс точка управления радиусом дуги
            self._draw_ctrl_point(*self._scr(v))
            self._draw_ctrl_point(*self._scr(p1))
            self._draw_ctrl_point(*self._scr(p2))
            arc_mid_pt = (v[0] + R * math.cos(mid), v[1] + R * math.sin(mid))
            self._draw_ctrl_point(*self._scr(arc_mid_pt))

    def _draw_ctrl_point(self, x, y, r=5):
        self.canvas.create_rectangle(x-r, y-r, x+r, y+r, fill="#00AAFF", outline="#0044AA", width=1, tags="primitive")

    def _circle_world_points(self, cx, cy, r, steps=72):
        pts = []
        for i in range(steps + 1):
            a = 2 * math.pi * i / steps
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    def _arc_world_points(self, cx, cy, r, a1_deg, a2_deg, steps=60):
        a1, a2 = a1_deg, a2_deg
        while a2 < a1:
            a2 += 360
        span = a2 - a1 or 360
        pts = []
        for i in range(steps + 1):
            a = math.radians(a1 + i * span / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    def _ellipse_world_points(self, cx, cy, rx, ry, angle_deg=0, steps=72):
        ar = math.radians(angle_deg)
        pts = []
        for i in range(steps + 1):
            t = 2 * math.pi * i / steps
            lx = rx * math.cos(t)
            ly = ry * math.sin(t)
            pts.append((cx + lx*math.cos(ar) - ly*math.sin(ar),
                        cy + lx*math.sin(ar) + ly*math.cos(ar)))
        return pts

    def _spline_world_points(self, ctrl_pts, steps=8):
        """Catmull-Rom интерполяция через контрольные точки."""
        if len(ctrl_pts) < 2:
            return list(ctrl_pts)
        if len(ctrl_pts) == 2:
            return list(ctrl_pts)
        # Расширяем для Catmull-Rom (дублируем края)
        pts = [ctrl_pts[0]] + list(ctrl_pts) + [ctrl_pts[-1]]
        result = []
        for i in range(1, len(pts) - 2):
            p0, p1, p2, p3 = pts[i-1], pts[i], pts[i+1], pts[i+2]
            for j in range(steps + (1 if i == len(pts)-3 else 0)):
                t = j / steps
                t2, t3 = t*t, t*t*t
                x = 0.5*((2*p1[0]) + (-p0[0]+p2[0])*t +
                         (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2 +
                         (-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
                y = 0.5*((2*p1[1]) + (-p0[1]+p2[1])*t +
                         (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2 +
                         (-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
                result.append((x, y))
        return result

    def _draw_styled_curve(self, world_pts, style, color, closed=False):
        """Рисует кривую (список мировых точек) с заданным стилем."""
        if len(world_pts) < 2:
            return
        if closed and world_pts[0] != world_pts[-1]:
            world_pts = list(world_pts) + [world_pts[0]]
        
        type_ = style.get('type', 'solid')
        width = style.get('width', 1.0)
        
        if type_ == 'solid':
            # Рисуем одной линией через экранные точки
            screen_pts = [c for wp in world_pts for c in self.world_to_screen(*wp)]
            self.canvas.create_line(*screen_pts, fill=color, width=width, tags="primitive")
        
        elif type_ in ('dashed', 'dashdot', 'dashdotdot'):
            dash = style.get('dash', (10, 5))
            screen_pts = [c for wp in world_pts for c in self.world_to_screen(*wp)]
            self.canvas.create_line(*screen_pts, fill=color, width=width, dash=dash, tags="primitive")
        
        elif type_ in ('wavy', 'zigzag'):
            # Для волнистых/зигзаг рисуем каждый сегмент отдельно
            amp = style.get('amplitude', 2)
            period = style.get('period', 10)
            for i in range(len(world_pts) - 1):
                ax, ay = self.world_to_screen(*world_pts[i])
                bx, by = self.world_to_screen(*world_pts[i+1])
                if type_ == 'wavy':
                    self.draw_wavy_line(self.canvas, ax, ay, bx, by, amp, period, width, color, "primitive")
                else:
                    self.draw_zigzag_line(self.canvas, ax, ay, bx, by, amp, period, width, color, "primitive")

    # ---- Список примитивов и выбор ----
    def update_prims_list(self):
        """Обновляет список примитивов, сохраняя текущее выделение."""
        prev_sel = self.selected_prim_idx
        self.prims_listbox.delete(0, tk.END)
        icons = {
            'segment_mouse': '📏', 'polyline': '〰', 'circle': '⭕',
            'arc': '🌙', 'rect': '▭', 'ellipse': '⬭',
            'polygon': '⬡', 'spline': '〜',
            'dim_linear': '↔', 'dim_radial': '⌀', 'dim_angular': '∠',
        }
        for prim in self.primitives:
            icon = icons.get(prim['type'], '•')
            style = prim.get('style_name', '')
            self.prims_listbox.insert(tk.END, f"{icon} {prim['name']}  [{style}]")
        # Восстанавливаем выделение
        if prev_sel is not None and prev_sel < len(self.primitives):
            self.prims_listbox.selection_set(prev_sel)
            self.prims_listbox.see(prev_sel)

    def on_prim_select(self, event):
        sel = self.prims_listbox.curselection()
        if sel:
            self.selected_prim_idx = sel[0]
            prim = self.primitives[self.selected_prim_idx]
            self.build_prim_props_panel(prim)
            # Обновляем info если это отрезок
            if prim['type'] == 'segment_mouse':
                self.point1 = prim['params']['p1']
                self.point2 = prim['params']['p2']
                self.update_info()
            self.redraw_all()
        # Не сбрасываем selected_prim_idx при потере фокуса списка

    def try_select_prim(self, event):
        """Попытка выбрать примитив кликом."""
        wx, wy = self.screen_to_world(event.x, event.y)
        best_i = None
        best_d = 15 / (self.scale * self.grid_step) + 0.2
        
        for i, prim in enumerate(self.primitives):
            d = self._dist_to_primitive(wx, wy, prim)
            if d < best_d:
                best_d = d
                best_i = i
        
        if best_i is not None:
            self.selected_prim_idx = best_i
            self.prims_listbox.selection_clear(0, tk.END)
            self.prims_listbox.selection_set(best_i)
            self.prims_listbox.see(best_i)
            self.build_prim_props_panel(self.primitives[best_i])
        else:
            # Клик в пустое место — снимаем выделение
            self.selected_prim_idx = None
            self.prims_listbox.selection_clear(0, tk.END)
        self.redraw_all()

    def _dist_to_primitive(self, wx, wy, prim):
        t = prim['type']
        p = prim['params']
        
        if t == 'segment_mouse':
            return self._point_segment_dist(wx, wy, p['p1'][0], p['p1'][1], p['p2'][0], p['p2'][1])
        
        elif t == 'polyline':
            pts = p['points']
            min_d = float('inf')
            for i in range(len(pts)-1):
                d = self._point_segment_dist(wx, wy, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
                min_d = min(min_d, d)
            return min_d
        
        elif t == 'circle':
            d = abs(math.hypot(wx-p['cx'], wy-p['cy']) - p['r'])
            return d
        
        elif t == 'arc':
            d_center = math.hypot(wx-p['cx'], wy-p['cy'])
            d_r = abs(d_center - p['r'])
            # Проверяем угол
            angle = math.degrees(math.atan2(wy-p['cy'], wx-p['cx']))
            a1, a2 = p['start_angle'], p['end_angle']
            while a2 < a1: a2 += 360
            norm_a = angle
            while norm_a < a1: norm_a += 360
            if norm_a <= a2:
                return d_r
            return d_r + 1000
        
        elif t == 'rect':
            pts = p['points']
            min_d = float('inf')
            for i in range(4):
                a, b = pts[i], pts[(i+1)%4]
                d = self._point_segment_dist(wx, wy, a[0], a[1], b[0], b[1])
                min_d = min(min_d, d)
            return min_d
        
        elif t == 'ellipse':
            dx = (wx - p['cx']) / (p['rx'] + 0.0001)
            dy = (wy - p['cy']) / (p['ry'] + 0.0001)
            return abs(dx**2 + dy**2 - 1) * min(p['rx'], p['ry'])
        
        elif t == 'polygon':
            verts = p['vertices']
            min_d = float('inf')
            for i in range(len(verts)):
                a, b = verts[i], verts[(i+1)%len(verts)]
                d = self._point_segment_dist(wx, wy, a[0], a[1], b[0], b[1])
                min_d = min(min_d, d)
            return min_d
        
        elif t == 'dim_linear':
            try:
                dim = make_dimension(t, p)
                e1 = dim.project(dim.p1)
                e2 = dim.project(dim.p2)
                return self._point_segment_dist(wx, wy, e1[0], e1[1], e2[0], e2[1])
            except Exception:
                return float('inf')

        elif t == 'dim_radial':
            cx, cy = p['cx'], p['cy']
            text_pos = p.get('text_pos') or (cx + p['r'], cy)
            return self._point_segment_dist(wx, wy, cx, cy, text_pos[0], text_pos[1])

        elif t == 'dim_angular':
            v = p['vertex']
            R = p['arc_radius']
            d = abs(math.hypot(wx - v[0], wy - v[1]) - R)
            return d

        elif t == 'spline':
            pts = p['points']
            min_d = float('inf')
            for i in range(len(pts)-1):
                d = self._point_segment_dist(wx, wy, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
                min_d = min(min_d, d)
            return min_d
        
        return float('inf')

    # ====================================================================
    #          Грипперы (контрольные точки) для редактирования
    # ====================================================================
    def _get_grippers(self, prim):
        """Список контрольных точек примитива: [{'key': str, 'pt': (wx, wy)}, ...]"""
        t = prim['type']; p = prim['params']
        if t == 'segment_mouse':
            return [{'key': 'p1', 'pt': p['p1']}, {'key': 'p2', 'pt': p['p2']}]
        if t == 'polyline':
            return [{'key': f'pt{i}', 'pt': pt} for i, pt in enumerate(p['points'])]
        if t == 'circle':
            return [{'key': 'center', 'pt': (p['cx'], p['cy'])},
                    {'key': 'edge',   'pt': (p['cx'] + p['r'], p['cy'])}]
        if t == 'arc':
            a1 = math.radians(p['start_angle'])
            a2 = math.radians(p['end_angle'])
            return [{'key': 'center', 'pt': (p['cx'], p['cy'])},
                    {'key': 'start',  'pt': (p['cx'] + p['r']*math.cos(a1),
                                              p['cy'] + p['r']*math.sin(a1))},
                    {'key': 'end',    'pt': (p['cx'] + p['r']*math.cos(a2),
                                              p['cy'] + p['r']*math.sin(a2))}]
        if t == 'rect':
            return [{'key': f'corner{i}', 'pt': pt} for i, pt in enumerate(p['points'])]
        if t == 'ellipse':
            ar = math.radians(p.get('angle', 0))
            return [{'key': 'center', 'pt': (p['cx'], p['cy'])},
                    {'key': 'rx',     'pt': (p['cx'] + p['rx']*math.cos(ar),
                                              p['cy'] + p['rx']*math.sin(ar))},
                    {'key': 'ry',     'pt': (p['cx'] - p['ry']*math.sin(ar),
                                              p['cy'] + p['ry']*math.cos(ar))}]
        if t == 'polygon':
            return [{'key': 'center', 'pt': (p['cx'], p['cy'])},
                    {'key': 'vertex', 'pt': p['vertices'][0]}]
        if t == 'spline':
            return [{'key': f'pt{i}', 'pt': pt} for i, pt in enumerate(p['points'])]
        if t == 'dim_linear':
            return [{'key': 'p1',      'pt': p['p1']},
                    {'key': 'p2',      'pt': p['p2']},
                    {'key': 'dim_pos', 'pt': p['dim_pos']}]
        if t == 'dim_radial':
            a = math.radians(p['angle_deg'])
            on_circle = (p['cx'] + p['r']*math.cos(a),
                         p['cy'] + p['r']*math.sin(a))
            text_pos = p.get('text_pos') or on_circle
            return [{'key': 'center',    'pt': (p['cx'], p['cy'])},
                    {'key': 'on_circle', 'pt': on_circle},
                    {'key': 'text_pos',  'pt': text_pos}]
        if t == 'dim_angular':
            v = p['vertex']
            R = p.get('arc_radius', 1.0)
            a1 = math.atan2(p['p1'][1]-v[1], p['p1'][0]-v[0])
            a2 = math.atan2(p['p2'][1]-v[1], p['p2'][0]-v[0])
            d = a2 - a1
            while d >  math.pi: d -= 2*math.pi
            while d < -math.pi: d += 2*math.pi
            mid = a1 + d/2
            arc_mid_pt = (v[0] + R*math.cos(mid), v[1] + R*math.sin(mid))
            return [{'key': 'vertex',   'pt': v},
                    {'key': 'p1',       'pt': p['p1']},
                    {'key': 'p2',       'pt': p['p2']},
                    {'key': 'arc_mid',  'pt': arc_mid_pt}]
        return []

    def _hit_grip(self, sx, sy, hit_radius=8):
        """Проверяет, попадает ли клик (sx,sy) в гриппер активного примитива."""
        if self.selected_prim_idx is None:
            return None
        if self.selected_prim_idx >= len(self.primitives):
            return None
        prim = self.primitives[self.selected_prim_idx]
        for g in self._get_grippers(prim):
            gx, gy = self.world_to_screen(*g['pt'])
            if math.hypot(gx - sx, gy - sy) <= hit_radius:
                return {'idx': self.selected_prim_idx, 'key': g['key']}
        return None

    def _move_gripper(self, prim, key, new_pt):
        """Перемещение гриппера → обновление параметров примитива."""
        t = prim['type']; p = prim['params']

        if t == 'segment_mouse':
            if key in ('p1', 'p2'):
                p[key] = tuple(new_pt)

        elif t == 'polyline':
            if key.startswith('pt'):
                idx = int(key[2:])
                if 0 <= idx < len(p['points']):
                    p['points'][idx] = tuple(new_pt)

        elif t == 'circle':
            if key == 'center':
                p['cx'], p['cy'] = new_pt
            elif key == 'edge':
                p['r'] = math.hypot(new_pt[0]-p['cx'], new_pt[1]-p['cy'])

        elif t == 'arc':
            if key == 'center':
                p['cx'], p['cy'] = new_pt
            elif key == 'start':
                p['start_angle'] = math.degrees(math.atan2(new_pt[1]-p['cy'],
                                                            new_pt[0]-p['cx']))
                p['r'] = math.hypot(new_pt[0]-p['cx'], new_pt[1]-p['cy'])
            elif key == 'end':
                p['end_angle'] = math.degrees(math.atan2(new_pt[1]-p['cy'],
                                                          new_pt[0]-p['cx']))

        elif t == 'rect':
            if key.startswith('corner'):
                idx = int(key[6:])
                opp_idx = (idx + 2) % 4
                opp = p['points'][opp_idx]
                xs = [new_pt[0], opp[0]]
                ys = [new_pt[1], opp[1]]
                # axis-aligned восстановление: сохраняем порядок углов
                p['points'] = [(xs[0], ys[0]), (xs[1], ys[0]),
                               (xs[1], ys[1]), (xs[0], ys[1])]

        elif t == 'ellipse':
            if key == 'center':
                p['cx'], p['cy'] = new_pt
            elif key == 'rx':
                dx = new_pt[0]-p['cx']; dy = new_pt[1]-p['cy']
                p['rx'] = math.hypot(dx, dy)
                p['angle'] = math.degrees(math.atan2(dy, dx))
            elif key == 'ry':
                dx = new_pt[0]-p['cx']; dy = new_pt[1]-p['cy']
                p['ry'] = math.hypot(dx, dy)

        elif t == 'polygon':
            if key == 'center':
                dx = new_pt[0] - p['cx']
                dy = new_pt[1] - p['cy']
                p['cx'], p['cy'] = new_pt
                p['vertices'] = [(v[0]+dx, v[1]+dy) for v in p['vertices']]
            elif key == 'vertex':
                dx = new_pt[0]-p['cx']; dy = new_pt[1]-p['cy']
                r = math.hypot(dx, dy)
                p['r'] = r
                n = p['n']
                base = math.degrees(math.atan2(dy, dx))
                p['rotation_angle'] = base - p.get('base_angle', 0)
                verts = []
                for i in range(n):
                    a = math.radians(base + i*360/n)
                    verts.append((p['cx']+r*math.cos(a), p['cy']+r*math.sin(a)))
                p['vertices'] = verts

        elif t == 'spline':
            if key.startswith('pt'):
                idx = int(key[2:])
                if 0 <= idx < len(p['points']):
                    p['points'][idx] = tuple(new_pt)

        elif t == 'dim_linear':
            if key in ('p1', 'p2', 'dim_pos'):
                p[key] = tuple(new_pt)
                # Ручное перемещение → разорвать ассоциативную ссылку для этой точки
                p['assoc'] = [a for a in p.get('assoc', [])
                              if a.get('point_key') != key]

        elif t == 'dim_radial':
            if key == 'center':
                p['cx'], p['cy'] = new_pt
                p['assoc'] = []
            elif key == 'on_circle':
                dx = new_pt[0]-p['cx']; dy = new_pt[1]-p['cy']
                p['angle_deg'] = math.degrees(math.atan2(dy, dx))
                # если нет ассоциативной ссылки на окружность — обновляем r
                has_circle_ref = any(a.get('point_key') == 'circle'
                                     for a in p.get('assoc', []))
                if not has_circle_ref:
                    p['r'] = math.hypot(dx, dy)
            elif key == 'text_pos':
                p['text_pos'] = tuple(new_pt)
                # Также обновляем угол: радиальная линия идёт от центра к тексту
                dx = new_pt[0]-p['cx']; dy = new_pt[1]-p['cy']
                p['angle_deg'] = math.degrees(math.atan2(dy, dx))

        elif t == 'dim_angular':
            if key in ('vertex', 'p1', 'p2'):
                p[key] = tuple(new_pt)
                p['assoc'] = [a for a in p.get('assoc', [])
                              if a.get('point_key') != key]
            elif key == 'arc_mid':
                v = p['vertex']
                p['arc_radius'] = max(1e-6,
                                       math.hypot(new_pt[0]-v[0], new_pt[1]-v[1]))

    def _point_segment_dist(self, px, py, ax, ay, bx, by):
        dx, dy = bx-ax, by-ay
        if dx == 0 and dy == 0:
            return math.hypot(px-ax, py-ay)
        t = max(0, min(1, ((px-ax)*dx + (py-ay)*dy) / (dx*dx+dy*dy)))
        return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

    def delete_selected_prim(self):
        if self.selected_prim_idx is not None:
            del self.primitives[self.selected_prim_idx]
            self.selected_prim_idx = None
            # Пересинхронизируем self.segments из primitives
            self._sync_segments_from_primitives()
            self.update_prims_list()
            self.update_segments_list()
            self.redraw_all()

    def _sync_segments_from_primitives(self):
        """Синхронизирует self.segments из primitives (для update_info и совместимости)."""
        self.segments = [
            {'point1': p['params']['p1'], 'point2': p['params']['p2'],
             'style_name': p.get('style_name','Сплошная основная'),
             'color': p.get('color', self.prim_default_color), 'name': p['name']}
            for p in self.primitives if p['type'] == 'segment_mouse'
        ]

    def duplicate_prim(self):
        if self.selected_prim_idx is not None:
            import copy
            p = copy.deepcopy(self.primitives[self.selected_prim_idx])
            p['name'] = p['name'] + " (копия)"
            t = p['type']
            if t == 'segment_mouse':
                p['params']['p1'] = (p['params']['p1'][0]+0.5, p['params']['p1'][1]+0.5)
                p['params']['p2'] = (p['params']['p2'][0]+0.5, p['params']['p2'][1]+0.5)
            elif t in ('polyline', 'spline'):
                p['params']['points'] = [(x+0.5, y+0.5) for x,y in p['params']['points']]
            elif t in ('circle', 'arc', 'ellipse'):
                p['params']['cx'] += 0.5; p['params']['cy'] += 0.5
            elif t == 'rect':
                p['params']['points'] = [(x+0.5, y+0.5) for x,y in p['params']['points']]
            elif t == 'polygon':
                p['params']['cx'] += 0.5; p['params']['cy'] += 0.5
                p['params']['vertices'] = [(x+0.5, y+0.5) for x,y in p['params']['vertices']]
            p['id'] = self._next_prim_id
            self._next_prim_id += 1
            self.primitives.append(p)
            self.update_prims_list()
            self.redraw_all()

    # ---- Панель свойств примитива ----
    def build_prim_props_panel(self, prim):
        for w in self.prim_props_inner.winfo_children():
            w.destroy()
        self.prim_prop_vars = {}
        t = prim['type']
        p = prim['params']
        
        # Заполняем стиль и цвет
        style_name = prim.get('style_name', self.current_style)
        if style_name not in self.line_styles:
            style_name = 'Сплошная основная'
        self.prim_style_var.set(style_name)
        color = prim.get('color', self.prim_default_color)
        self.prim_color_btn.config(bg=color, fg=self._contrast_fg(color))
        
        # Имя
        tk.Label(self.prim_props_inner, text="Имя:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=0, column=0, sticky=tk.W)
        name_var = tk.StringVar(value=prim['name'])
        tk.Entry(self.prim_props_inner, textvariable=name_var, width=18, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=0, column=1, columnspan=2, sticky=tk.EW)
        self.prim_prop_vars['name'] = name_var
        
        row = 1
        if t == 'segment_mouse':
            for lbl, key, coord in [("x1","p1",0),("y1","p1",1),("x2","p2",0),("y2","p2",1)]:
                tk.Label(self.prim_props_inner, text=lbl+":", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var = tk.StringVar(value=f"{p[key][coord]:.4f}")
                tk.Entry(self.prim_props_inner, textvariable=var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
                self.prim_prop_vars[f'{key}_{coord}'] = var
                row += 1
        
        elif t == 'polyline':
            pts = p['points']
            for i, (x, y) in enumerate(pts):
                tk.Label(self.prim_props_inner, text=f"P{i+1}:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var_x = tk.StringVar(value=f"{x:.4f}")
                var_y = tk.StringVar(value=f"{y:.4f}")
                tk.Entry(self.prim_props_inner, textvariable=var_x, width=8, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1)
                tk.Entry(self.prim_props_inner, textvariable=var_y, width=8, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=2)
                self.prim_prop_vars[f'plx{i}'] = var_x
                self.prim_prop_vars[f'ply{i}'] = var_y
                row += 1
            tk.Button(self.prim_props_inner, text="+Точка", command=self.polyline_add_point).grid(row=row, column=0, sticky=tk.EW)
            tk.Button(self.prim_props_inner, text="-Точка", command=self.polyline_remove_point).grid(row=row, column=1, sticky=tk.EW)
            row += 1

        elif t == 'circle':
            for lbl, key in [("cx", "cx"), ("cy", "cy"), ("r", "r")]:
                tk.Label(self.prim_props_inner, text=lbl+":", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var = tk.StringVar(value=f"{p[key]:.4f}")
                tk.Entry(self.prim_props_inner, textvariable=var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
                self.prim_prop_vars[key] = var
                row += 1
        
        elif t == 'arc':
            for lbl, key in [("cx","cx"),("cy","cy"),("r","r"),("Нач. угол°","start_angle"),("Кон. угол°","end_angle")]:
                tk.Label(self.prim_props_inner, text=lbl+":", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var = tk.StringVar(value=f"{p[key]:.2f}")
                tk.Entry(self.prim_props_inner, textvariable=var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
                self.prim_prop_vars[key] = var
                row += 1
        
        elif t == 'rect':
            pts = p['points']
            for i, (x, y) in enumerate(pts):
                tk.Label(self.prim_props_inner, text=f"P{i+1}:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var_x = tk.StringVar(value=f"{x:.4f}")
                var_y = tk.StringVar(value=f"{y:.4f}")
                tk.Entry(self.prim_props_inner, textvariable=var_x, width=8, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1)
                tk.Entry(self.prim_props_inner, textvariable=var_y, width=8, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=2)
                self.prim_prop_vars[f'rx{i}'] = var_x
                self.prim_prop_vars[f'ry{i}'] = var_y
                row += 1
            # Фаска/скругление
            tk.Label(self.prim_props_inner, text="Фаска:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
            ch_var = tk.StringVar(value=f"{p.get('chamfer',0):.4f}")
            tk.Entry(self.prim_props_inner, textvariable=ch_var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
            self.prim_prop_vars['chamfer'] = ch_var
            row += 1
            tk.Label(self.prim_props_inner, text="Скругление:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
            fi_var = tk.StringVar(value=f"{p.get('fillet',0):.4f}")
            tk.Entry(self.prim_props_inner, textvariable=fi_var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
            self.prim_prop_vars['fillet'] = fi_var
            row += 1
        
        elif t == 'ellipse':
            for lbl, key in [("cx","cx"),("cy","cy"),("rx","rx"),("ry","ry"),("Угол°","angle")]:
                tk.Label(self.prim_props_inner, text=lbl+":", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var = tk.StringVar(value=f"{p[key]:.4f}")
                tk.Entry(self.prim_props_inner, textvariable=var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
                self.prim_prop_vars[key] = var
                row += 1
        
        elif t == 'polygon':
            for lbl, key in [("cx","cx"),("cy","cy"),("r","r"),("N сторон","n")]:
                tk.Label(self.prim_props_inner, text=lbl+":", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var = tk.StringVar(value=f"{p[key]}")
                tk.Entry(self.prim_props_inner, textvariable=var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
                self.prim_prop_vars[key] = var
                row += 1
            tk.Label(self.prim_props_inner, text="Поворот\xb0:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
            rot_var = tk.StringVar(value=f"{p.get('rotation_angle', 0.0):.4f}")
            tk.Entry(self.prim_props_inner, textvariable=rot_var, width=12, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, sticky=tk.EW)
            self.prim_prop_vars['rotation_angle'] = rot_var
            row += 1
            inscr_var = tk.BooleanVar(value=p.get('inscribed', True))
            tk.Checkbutton(self.prim_props_inner, text="Вписанный", variable=inscr_var, bg="#162030", fg="#C8D8E8", selectcolor="#003D5C", activebackground="#1E3A55", font=("Consolas", 8)).grid(row=row, columnspan=2, sticky=tk.W)
            self.prim_prop_vars['inscribed'] = inscr_var
            row += 1
        
        elif t == 'spline':
            pts = p['points']
            for i, (x, y) in enumerate(pts):
                tk.Label(self.prim_props_inner, text=f"P{i+1}:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var_x = tk.StringVar(value=f"{x:.4f}")
                var_y = tk.StringVar(value=f"{y:.4f}")
                tk.Entry(self.prim_props_inner, textvariable=var_x, width=8, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1)
                tk.Entry(self.prim_props_inner, textvariable=var_y, width=8, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=2)
                self.prim_prop_vars[f'sx{i}'] = var_x
                self.prim_prop_vars[f'sy{i}'] = var_y
                row += 1
            # Кнопки добавить/удалить точку
            tk.Button(self.prim_props_inner, text="+Точка", command=self.spline_add_point).grid(row=row, column=0, sticky=tk.EW)
            tk.Button(self.prim_props_inner, text="-Точка", command=self.spline_remove_point).grid(row=row, column=1, sticky=tk.EW)
            row += 1

        elif is_dimension_type(t):
            # --- Общие свойства размеров ---
            try:
                dim = make_dimension(t, p)
                value_text = f"{dim.measure():.{p.get('precision', 2)}f}"
            except Exception:
                value_text = "?"
            tk.Label(self.prim_props_inner, text="Значение:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
            tk.Label(self.prim_props_inner, text=value_text, bg="#162030", fg="#00FF88", font=("Consolas", 9, "bold")).grid(row=row, column=1, sticky=tk.W)
            row += 1

            def add_entry(label, key, val, width=12):
                nonlocal row
                tk.Label(self.prim_props_inner, text=label, bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                var = tk.StringVar(value=str(val) if val is not None else "")
                tk.Entry(self.prim_props_inner, textvariable=var, width=width, bg="#0A1520", fg="#00D4FF", insertbackground="#00D4FF", relief="flat", font=("Consolas", 8), highlightthickness=1, highlightbackground="#1E3050", highlightcolor="#00D4FF").grid(row=row, column=1, columnspan=2, sticky=tk.EW)
                self.prim_prop_vars[key] = var
                row += 1

            add_entry("Текст (override):", 'text_override', p.get('text_override') or "")
            add_entry("Высота шрифта:",     'text_height',   f"{p.get('text_height', 0.35):.3f}")
            add_entry("Размер стрелки:",    'arrow_size',    f"{p.get('arrow_size', 0.30):.3f}")
            add_entry("Выход выносной:",    'ext_overshoot', f"{p.get('ext_overshoot', 0.15):.3f}")
            add_entry("Зазор выносной:",    'ext_offset',    f"{p.get('ext_offset', 0.05):.3f}")
            add_entry("Точность (знаки):",  'precision',     f"{int(p.get('precision', 2))}")

            if t == 'dim_linear':
                tk.Label(self.prim_props_inner, text="Ориентация:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                ori_var = tk.StringVar(value=p.get('orientation', 'aligned'))
                ttk.Combobox(self.prim_props_inner, textvariable=ori_var,
                             values=['aligned', 'horizontal', 'vertical'],
                             state='readonly', width=12).grid(row=row, column=1, sticky=tk.EW)
                self.prim_prop_vars['orientation'] = ori_var
                row += 1
            elif t == 'dim_radial':
                tk.Label(self.prim_props_inner, text="Тип:", bg="#162030", fg="#5A7A98", font=("Consolas", 8)).grid(row=row, column=0, sticky=tk.W)
                kind_var = tk.StringVar(value=p.get('kind', 'radius'))
                ttk.Combobox(self.prim_props_inner, textvariable=kind_var,
                             values=['radius', 'diameter'],
                             state='readonly', width=12).grid(row=row, column=1, sticky=tk.EW)
                self.prim_prop_vars['kind'] = kind_var
                row += 1
                add_entry("Угол радиуса (°):", 'angle_deg', f"{p.get('angle_deg', 0.0):.2f}")
                shelf_var = tk.BooleanVar(value=bool(p.get('with_shelf', False)))
                tk.Checkbutton(self.prim_props_inner, text="Полка-выноска",
                               variable=shelf_var, bg="#162030", fg="#C8D8E8",
                               selectcolor="#003D5C", activebackground="#1E3A55",
                               font=("Consolas", 8)).grid(row=row, columnspan=2, sticky=tk.W)
                self.prim_prop_vars['with_shelf'] = shelf_var
                row += 1
            elif t == 'dim_angular':
                add_entry("Радиус дуги:", 'arc_radius', f"{p.get('arc_radius', 1.0):.3f}")

    def apply_prim_props(self):
        if self.selected_prim_idx is None:
            messagebox.showwarning("Нет выбора", "Сначала выберите примитив из списка.")
            return
        if self.selected_prim_idx >= len(self.primitives):
            self.selected_prim_idx = None
            return
        if not self.prim_prop_vars:
            return
        prim = self.primitives[self.selected_prim_idx]
        t = prim['type']
        p = prim['params']
        v = self.prim_prop_vars
        
        try:
            prim['name'] = v['name'].get()
            # Применяем стиль линии
            chosen_style = self.prim_style_var.get()
            if chosen_style in self.line_styles:
                prim['style_name'] = chosen_style
            
            if t == 'segment_mouse':
                x1 = float(v['p1_0'].get()); y1 = float(v['p1_1'].get())
                x2 = float(v['p2_0'].get()); y2 = float(v['p2_1'].get())
                p['p1'] = (x1, y1); p['p2'] = (x2, y2)
            
            elif t == 'polyline':
                n = len(p['points'])
                new_pts = []
                for i in range(n):
                    x = float(v[f'plx{i}'].get())
                    y = float(v[f'ply{i}'].get())
                    new_pts.append((x, y))
                p['points'] = new_pts
            
            elif t == 'circle':
                p['cx'] = float(v['cx'].get())
                p['cy'] = float(v['cy'].get())
                p['r'] = float(v['r'].get())
            
            elif t == 'arc':
                p['cx'] = float(v['cx'].get())
                p['cy'] = float(v['cy'].get())
                p['r'] = float(v['r'].get())
                p['start_angle'] = float(v['start_angle'].get())
                p['end_angle'] = float(v['end_angle'].get())
            
            elif t == 'rect':
                new_pts = []
                for i in range(4):
                    x = float(v[f'rx{i}'].get())
                    y = float(v[f'ry{i}'].get())
                    new_pts.append((x, y))
                p['points'] = new_pts
                p['chamfer'] = float(v['chamfer'].get())
                p['fillet'] = float(v['fillet'].get())
            
            elif t == 'ellipse':
                p['cx'] = float(v['cx'].get())
                p['cy'] = float(v['cy'].get())
                p['rx'] = float(v['rx'].get())
                p['ry'] = float(v['ry'].get())
                p['angle'] = float(v['angle'].get())
            
            elif t == 'polygon':
                p['cx'] = float(v['cx'].get())
                p['cy'] = float(v['cy'].get())
                p['r'] = float(v['r'].get())
                p['n'] = int(float(v['n'].get()))
                p['inscribed'] = v['inscribed'].get()
                p['rotation_angle'] = float(v['rotation_angle'].get())
                # Пересчитываем вершины
                base_angle = p.get('base_angle', 0)
                rotation_angle = p.get('rotation_angle', 0.0)
                n = p['n']
                r = p['r']
                cx, cy = p['cx'], p['cy']
                if not p['inscribed']:
                    r = r / math.cos(math.pi/n)
                verts = []
                for i in range(n):
                    a = math.radians(base_angle + rotation_angle + i*360/n)
                    verts.append((cx + r*math.cos(a), cy + r*math.sin(a)))
                p['vertices'] = verts
            
            elif t == 'spline':
                n = len(p['points'])
                new_pts = []
                for i in range(n):
                    x = float(v[f'sx{i}'].get())
                    y = float(v[f'sy{i}'].get())
                    new_pts.append((x, y))
                p['points'] = new_pts

            elif is_dimension_type(t):
                # Общие параметры
                ov = v.get('text_override').get().strip()
                p['text_override']  = ov if ov else None
                p['text_height']    = float(v['text_height'].get())
                p['arrow_size']     = float(v['arrow_size'].get())
                p['ext_overshoot']  = float(v['ext_overshoot'].get())
                p['ext_offset']     = float(v['ext_offset'].get())
                p['precision']      = int(float(v['precision'].get()))
                if t == 'dim_linear' and 'orientation' in v:
                    p['orientation'] = v['orientation'].get()
                elif t == 'dim_radial':
                    if 'kind' in v:
                        p['kind'] = v['kind'].get()
                    if 'angle_deg' in v:
                        p['angle_deg'] = float(v['angle_deg'].get())
                    if 'with_shelf' in v:
                        p['with_shelf'] = bool(v['with_shelf'].get())
                elif t == 'dim_angular' and 'arc_radius' in v:
                    p['arc_radius'] = float(v['arc_radius'].get())

            self._sync_segments_from_primitives()
            self.update_prims_list()
            self.update_segments_list()
            self.redraw_all()
        
        except ValueError as e:
            messagebox.showerror("Ошибка", f"Некорректное значение: {e}")

    def change_prim_color(self):
        if self.selected_prim_idx is not None:
            color = colorchooser.askcolor()[1]
            if color:
                self.primitives[self.selected_prim_idx]['color'] = color
                self.prim_color_btn.config(bg=color, fg=self._contrast_fg(color))
                self.redraw_all()
                self.update_prims_list()

    def _contrast_fg(self, hex_color):
        """Возвращает чёрный или белый цвет в зависимости от яркости фона."""
        try:
            hex_color = hex_color.lstrip('#')
            r, g, b = int(hex_color[0:2],16), int(hex_color[2:4],16), int(hex_color[4:6],16)
            return 'black' if (r*299+g*587+b*114)/1000 > 128 else 'white'
        except:
            return 'black'

    def polyline_add_point(self):
        if self.selected_prim_idx is not None:
            prim = self.primitives[self.selected_prim_idx]
            if prim['type'] == 'polyline':
                pts = prim['params']['points']
                last = pts[-1] if pts else (0.0, 0.0)
                pts.append((last[0]+0.5, last[1]+0.5))
                self.build_prim_props_panel(prim)
                self.redraw_all()

    def polyline_remove_point(self):
        if self.selected_prim_idx is not None:
            prim = self.primitives[self.selected_prim_idx]
            if prim['type'] == 'polyline' and len(prim['params']['points']) > 2:
                prim['params']['points'].pop()
                self.build_prim_props_panel(prim)
                self.redraw_all()

    def spline_add_point(self):
        if self.selected_prim_idx is not None:
            prim = self.primitives[self.selected_prim_idx]
            if prim['type'] == 'spline':
                pts = prim['params']['points']
                if pts:
                    last = pts[-1]
                    pts.append((last[0]+0.5, last[1]+0.5))
                else:
                    pts.append((0.0, 0.0))
                self.build_prim_props_panel(prim)
                self.redraw_all()

    def spline_remove_point(self):
        if self.selected_prim_idx is not None:
            prim = self.primitives[self.selected_prim_idx]
            if prim['type'] == 'spline' and len(prim['params']['points']) > 2:
                prim['params']['points'].pop()
                self.build_prim_props_panel(prim)
                self.redraw_all()

    # ---- fit_all обновление для примитивов ----
    def fit_all(self):
        all_points = []
        for seg in self.segments:
            all_points.append(seg['point1'])
            all_points.append(seg['point2'])
        
        for prim in self.primitives:
            t = prim['type']
            p = prim['params']
            if t == 'segment_mouse':
                all_points += [p['p1'], p['p2']]
            elif t == 'polyline':
                all_points += p['points']
            elif t == 'circle':
                all_points += [(p['cx']-p['r'], p['cy']-p['r']), (p['cx']+p['r'], p['cy']+p['r'])]
            elif t == 'arc':
                all_points += [(p['cx']-p['r'], p['cy']-p['r']), (p['cx']+p['r'], p['cy']+p['r'])]
            elif t == 'rect':
                all_points += p['points']
            elif t == 'ellipse':
                all_points += [(p['cx']-p['rx'], p['cy']-p['ry']), (p['cx']+p['rx'], p['cy']+p['ry'])]
            elif t == 'polygon':
                all_points += p['vertices']
            elif t == 'spline':
                all_points += p['points']
            elif t == 'dim_linear':
                all_points += [p.get('p1', (0,0)), p.get('p2', (0,0)), p.get('dim_pos', (0,0))]
            elif t == 'dim_radial':
                cx, cy, r = p['cx'], p['cy'], p['r']
                all_points += [(cx-r, cy-r), (cx+r, cy+r)]
                if p.get('text_pos'):
                    all_points.append(p['text_pos'])
            elif t == 'dim_angular':
                v = p['vertex']
                R = p['arc_radius']
                all_points += [(v[0]-R, v[1]-R), (v[0]+R, v[1]+R)]

        if not all_points:
            self.reset_view()
            return
        
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        width_world = max_x - min_x
        height_world = max_y - min_y
        
        if width_world == 0 and height_world == 0:
            self.reset_view()
            return
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if width_world > 0 and height_world > 0:
            scale_x = (canvas_width * 0.8) / (width_world * self.grid_step)
            scale_y = (canvas_height * 0.8) / (height_world * self.grid_step)
            self.scale = min(scale_x, scale_y)
        else:
            self.scale = 1.0
        
        self.pan_x = -center_x * self.grid_step
        self.pan_y = center_y * self.grid_step
        self.rotation = 0
        self.update_status()
        self.redraw_all()


if __name__ == "__main__":
    root = tk.Tk()
    app = SegmentApp(root)
    root.mainloop()