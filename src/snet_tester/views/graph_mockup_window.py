"""Preview-only window for the quasi-square graph layout proposal."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets


def _chip(text: str, bg: str, fg: str = "#18212B") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setAlignment(QtCore.Qt.AlignCenter)
    label.setMinimumHeight(24)
    label.setStyleSheet(
        f"""
        QLabel {{
            background: {bg};
            color: {fg};
            border: 1px solid #8EA0B2;
            border-radius: 3px;
            font-weight: 600;
            padding: 2px 8px;
        }}
        """
    )
    return label


class GraphMockupWindow(QtWidgets.QMainWindow):
    """Graph-focused mockup for operator-friendly industrial layout."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SNET Graph Aspect Ratio Mockup")
        self.resize(1440, 920)
        self.setMinimumSize(1320, 860)
        self._apply_palette()
        self._build_ui()

    def _apply_palette(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #E7EBF0;
                color: #23313D;
                font-size: 9pt;
            }
            QGroupBox {
                background: #F4F7FA;
                border: 1px solid #B5C0CA;
                border-radius: 4px;
                margin-top: 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QFrame#shellPanel, QFrame#statusCard, QFrame#controlStrip, QFrame#infoPanel {
                background: #F4F7FA;
                border: 1px solid #B5C0CA;
                border-radius: 4px;
            }
            QFrame#graphPanel {
                background: #000000;
                border: 1px solid #596573;
                border-radius: 2px;
            }
            QFrame#valvePanel {
                background: #06080B;
                border: 1px solid #596573;
                border-radius: 2px;
            }
            QFrame#graphToolbar {
                background: #DDE4EA;
                border: 1px solid #A8B3BE;
                border-radius: 3px;
            }
            QLabel[role="caption"] {
                color: #5A6875;
                font-size: 8pt;
                font-weight: 600;
            }
            QLabel[role="hero"] {
                color: #19252F;
                font-size: 16pt;
                font-weight: 700;
            }
            QLabel[role="muted"] {
                color: #6C7986;
            }
            QLabel[role="graphTitle"] {
                color: #DCE3EA;
                font-size: 10pt;
                font-weight: 700;
            }
            QLabel[role="graphMeta"] {
                color: #9FB0C0;
                font-size: 8pt;
            }
            QPushButton {
                background: #E1E8EE;
                border: 1px solid #96A3AF;
                border-radius: 3px;
                min-height: 28px;
                padding: 0 10px;
                font-weight: 600;
            }
            QPushButton#primaryButton {
                background: #4F73A6;
                color: white;
                border-color: #3E5E8A;
            }
            QPushButton#runButton {
                background: #2DA56A;
                color: white;
                border-color: #248858;
            }
            QPushButton#stopButton {
                background: #D86859;
                color: white;
                border-color: #BC5548;
            }
            QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {
                background: #FCFDFE;
                border: 1px solid #B5C0CA;
                border-radius: 3px;
            }
            QHeaderView::section {
                background: #DCE4EB;
                color: #23313D;
                border: 1px solid #B5C0CA;
                padding: 4px;
                font-weight: 600;
            }
            """
        )

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        shell_status = self._build_shell_status()
        root.addWidget(shell_status)

        body = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        body.addWidget(self._build_left_graph_area())
        body.addWidget(self._build_right_work_area())
        body.setSizes([1040, 400])
        root.addWidget(body, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Preview only: quasi-square graph with bottom control strip")

    def _build_shell_status(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("shellPanel")
        layout = QtWidgets.QGridLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        items = [
            ("RUN", _chip("IDLE", "#E5E9EE")),
            ("LINK", _chip("CONNECTED", "#CFEAD8")),
            ("MODE", _chip("RUN", "#D8E4F2")),
            ("ALARM", _chip("NORMAL", "#CFEAD8")),
            ("SELECTED CH", _chip("CH1", "#E5E9EE")),
            ("RESP", _chip("48 ms", "#E5E9EE")),
            ("WINDOW", _chip("10.0 s", "#E5E9EE")),
        ]

        for column, (caption, widget) in enumerate(items):
            label = QtWidgets.QLabel(caption)
            label.setProperty("role", "caption")
            layout.addWidget(label, 0, column)
            layout.addWidget(widget, 1, column)
        return frame

    def _build_left_graph_area(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_graph_status_card(), 0)
        layout.addWidget(self._build_main_graph_card(), 6)
        layout.addWidget(self._build_control_strip(), 1)
        layout.addWidget(self._build_valve_graph_card(), 2)
        return widget

    def _build_graph_status_card(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("statusCard")
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        cards = [
            ("Selected CH", "CH1", "Recipe A / Main lane"),
            ("Set vs Act", "45.0 / 42.8 %", "Tracking stable"),
            ("Valve", "2.10 V", "Normal response"),
            ("Graph Mode", "TIME", "Quasi-square trend view"),
        ]
        for caption, hero, body in cards:
            card = QtWidgets.QFrame()
            card.setObjectName("infoPanel")
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            c = QtWidgets.QLabel(caption)
            c.setProperty("role", "caption")
            h = QtWidgets.QLabel(hero)
            h.setProperty("role", "hero")
            b = QtWidgets.QLabel(body)
            b.setProperty("role", "muted")
            card_layout.addWidget(c)
            card_layout.addWidget(h)
            card_layout.addWidget(b)
            layout.addWidget(card, 1)
        return frame

    def _build_main_graph_card(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("graphPanel")
        outer = QtWidgets.QVBoxLayout(frame)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("MAIN RATIO GRAPH")
        title.setProperty("role", "graphTitle")
        meta = QtWidgets.QLabel("Target range, selected channel emphasis, quasi-square aspect")
        meta.setProperty("role", "graphMeta")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(meta)
        outer.addLayout(top)

        canvas = QtWidgets.QTableWidget(12, 16)
        canvas.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        canvas.setFocusPolicy(QtCore.Qt.NoFocus)
        canvas.horizontalHeader().hide()
        canvas.verticalHeader().hide()
        canvas.setShowGrid(True)
        canvas.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        canvas.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        for row in range(canvas.rowCount()):
            canvas.setRowHeight(row, 36)
        for column in range(canvas.columnCount()):
            canvas.setColumnWidth(column, 58)
        for row in range(canvas.rowCount()):
            for column in range(canvas.columnCount()):
                item = QtWidgets.QTableWidgetItem("")
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                base = "#040608" if (row + column) % 2 == 0 else "#0A0E12"
                item.setBackground(QtGui.QColor(base))
                item.setForeground(QtGui.QColor("#1A2026"))
                canvas.setItem(row, column, item)
        outer.addWidget(canvas, 1)

        legend = QtWidgets.QHBoxLayout()
        for text, color in (
            ("SET", "#FFD400"),
            ("ACT", "#00E5FF"),
            ("Selected CH", "#39FF14"),
            ("Alarm Limit", "#FF5A4F"),
        ):
            swatch = QtWidgets.QLabel(f"  {text}  ")
            swatch.setStyleSheet(
                f"QLabel {{ color: {color}; border: 1px solid #4E5965; padding: 2px 8px; border-radius: 3px; }}"
            )
            legend.addWidget(swatch)
        legend.addStretch(1)
        outer.addLayout(legend)
        return frame

    def _build_control_strip(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("controlStrip")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        title_row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("GRAPH CONTROL STRIP")
        label.setProperty("role", "caption")
        sub = QtWidgets.QLabel("Graph-local controls stay below the graph, not inside the right work panel")
        sub.setProperty("role", "muted")
        title_row.addWidget(label)
        title_row.addStretch(1)
        title_row.addWidget(sub)
        layout.addLayout(title_row)

        toolbar = QtWidgets.QFrame()
        toolbar.setObjectName("graphToolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(8)

        controls = [
            ("WINDOW", "10 s"),
            ("X AXIS", "TIME"),
            ("Y AXIS", "RATIO"),
            ("FOCUS", "CH1"),
        ]
        for caption, value in controls:
            box = QtWidgets.QVBoxLayout()
            cap = QtWidgets.QLabel(caption)
            cap.setProperty("role", "caption")
            val = QtWidgets.QLineEdit(value)
            val.setMinimumWidth(92)
            box.addWidget(cap)
            box.addWidget(val)
            toolbar_layout.addLayout(box)

        toggle_group = QtWidgets.QVBoxLayout()
        toggle_caption = QtWidgets.QLabel("TRACE")
        toggle_caption.setProperty("role", "caption")
        toggle_row = QtWidgets.QHBoxLayout()
        for label in ("SET", "ACT", "VALVE"):
            btn = QtWidgets.QPushButton(label)
            toggle_row.addWidget(btn)
        toggle_group.addWidget(toggle_caption)
        toggle_group.addLayout(toggle_row)
        toolbar_layout.addLayout(toggle_group)

        toolbar_layout.addStretch(1)

        freeze = QtWidgets.QPushButton("FREEZE")
        freeze.setObjectName("primaryButton")
        capture = QtWidgets.QPushButton("CAPTURE")
        capture.setObjectName("primaryButton")
        reset = QtWidgets.QPushButton("RESET VIEW")
        toolbar_layout.addWidget(freeze)
        toolbar_layout.addWidget(capture)
        toolbar_layout.addWidget(reset)

        layout.addWidget(toolbar)
        return frame

    def _build_valve_graph_card(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("valvePanel")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("VALVE GRAPH")
        title.setProperty("role", "graphTitle")
        meta = QtWidgets.QLabel("Separated support graph, linked by time axis")
        meta.setProperty("role", "graphMeta")
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(meta)
        layout.addLayout(row)

        canvas = QtWidgets.QTableWidget(4, 16)
        canvas.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        canvas.setFocusPolicy(QtCore.Qt.NoFocus)
        canvas.horizontalHeader().hide()
        canvas.verticalHeader().hide()
        canvas.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        canvas.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        for row_index in range(canvas.rowCount()):
            canvas.setRowHeight(row_index, 30)
        for column in range(canvas.columnCount()):
            canvas.setColumnWidth(column, 58)
        for row_index in range(canvas.rowCount()):
            for column in range(canvas.columnCount()):
                item = QtWidgets.QTableWidgetItem("")
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                base = "#05080A" if (row_index + column) % 2 == 0 else "#0C1015"
                item.setBackground(QtGui.QColor(base))
                canvas.setItem(row_index, column, item)
        layout.addWidget(canvas, 1)
        return frame

    def _build_right_work_area(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_operation_panel())
        layout.addWidget(self._build_channel_panel())
        layout.addWidget(self._build_engineering_panel(), 1)
        return widget

    def _build_operation_panel(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Operation")
        layout = QtWidgets.QGridLayout(group)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        fields = [("Port", "COM6"), ("Mode", "RUN"), ("Preset", "SET-01"), ("Channel", "CH1")]
        for row, (caption, value) in enumerate(fields):
            layout.addWidget(QtWidgets.QLabel(caption), row, 0)
            layout.addWidget(QtWidgets.QLineEdit(value), row, 1)

        button_row = QtWidgets.QHBoxLayout()
        run = QtWidgets.QPushButton("RUN")
        run.setObjectName("runButton")
        stop = QtWidgets.QPushButton("STOP")
        stop.setObjectName("stopButton")
        apply_btn = QtWidgets.QPushButton("APPLY")
        apply_btn.setObjectName("primaryButton")
        button_row.addWidget(run)
        button_row.addWidget(stop)
        button_row.addWidget(apply_btn)
        layout.addLayout(button_row, 4, 0, 1, 2)
        return group

    def _build_channel_panel(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Selected Channel Detail")
        layout = QtWidgets.QVBoxLayout(group)

        form = QtWidgets.QGridLayout()
        values = [
            ("Set", "45.0 %"),
            ("Actual", "42.8 %"),
            ("Valve", "2.10 V"),
            ("Pressure", "0.9 bar"),
            ("Temp", "28.3 C"),
        ]
        for row, (caption, value) in enumerate(values):
            form.addWidget(QtWidgets.QLabel(caption), row, 0)
            form.addWidget(QtWidgets.QLineEdit(value), row, 1)
        layout.addLayout(form)

        table = QtWidgets.QTableWidget(4, 3)
        table.setHorizontalHeaderLabels(["Preset", "Value", "Apply"])
        table.verticalHeader().hide()
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        rows = [("SET-01", "45", "Preview"), ("SET-02", "30", "Preview"), ("SET-03", "10", "Preview"), ("SET-04", "0", "Preview")]
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                table.setItem(row_index, column_index, QtWidgets.QTableWidgetItem(value))
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        return group

    def _build_engineering_panel(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Engineering / Notes")
        layout = QtWidgets.QVBoxLayout(group)
        text = QtWidgets.QPlainTextEdit()
        text.setPlainText(
            "Mockup notes\n"
            "- Left graph area ratio target: 1.5:1 ~ 1.8:1\n"
            "- Bottom strip stays visible\n"
            "- Valve graph remains separated\n"
            "- Operators keep legacy familiarity"
        )
        layout.addWidget(text)
        return group
