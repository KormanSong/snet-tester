"""Preview-only wireframe window for the proposed industrial UI relayout."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets


def _status_chip(text: str, bg: str, fg: str = "#1F2933") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setAlignment(QtCore.Qt.AlignCenter)
    label.setMinimumHeight(26)
    label.setStyleSheet(
        f"""
        QLabel {{
            background: {bg};
            color: {fg};
            border: 1px solid #AAB3BC;
            border-radius: 4px;
            font-weight: 600;
            padding: 2px 8px;
        }}
        """
    )
    return label


class LayoutPreviewWindow(QtWidgets.QMainWindow):
    """Static wireframe that demonstrates the proposed screen hierarchy."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SNET Protocol Tester - UI Relayout Preview")
        self.resize(1440, 920)
        self.setMinimumSize(1320, 860)
        self._apply_palette()
        self._build_ui()

    def _apply_palette(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #E9EDF1;
                color: #24313D;
                font-size: 9pt;
            }
            QGroupBox {
                background: #F5F7F9;
                border: 1px solid #B6C0C9;
                border-radius: 4px;
                margin-top: 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px 0 4px;
            }
            QFrame#statusStrip, QFrame#trendPlaceholder, QFrame#noteFrame {
                background: #F5F7F9;
                border: 1px solid #B6C0C9;
                border-radius: 4px;
            }
            QTableWidget, QTabWidget::pane, QPlainTextEdit {
                background: #FCFDFE;
                border: 1px solid #B6C0C9;
                gridline-color: #D4DAE0;
            }
            QHeaderView::section {
                background: #DCE3E9;
                color: #24313D;
                border: 1px solid #B6C0C9;
                padding: 4px;
                font-weight: 600;
            }
            QPushButton {
                background: #E2E8EE;
                border: 1px solid #98A3AD;
                border-radius: 4px;
                min-height: 30px;
                padding: 0 12px;
                font-weight: 600;
            }
            QPushButton#startButton {
                background: #2FA36B;
                color: white;
                border-color: #248555;
            }
            QPushButton#stopButton {
                background: #D96A5C;
                color: white;
                border-color: #B95448;
            }
            QPushButton#applyButton {
                background: #4A6FA5;
                color: white;
                border-color: #3A5C8C;
            }
            QLabel[role="sectionCaption"] {
                color: #5A6875;
                font-size: 8pt;
                font-weight: 600;
            }
            QLabel[role="heroValue"] {
                font-size: 16pt;
                font-weight: 700;
                color: #1F2933;
            }
            QLabel[role="placeholderTitle"] {
                font-size: 12pt;
                font-weight: 700;
                color: #52606D;
            }
            QLabel[role="placeholderBody"] {
                color: #6B7785;
            }
            """
        )

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_status_strip())
        body_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        body_splitter.addWidget(self._build_monitor_panel())
        body_splitter.addWidget(self._build_work_panel())
        body_splitter.setSizes([860, 520])
        root.addWidget(body_splitter, 1)
        root.addWidget(self._build_alarm_panel(), 0)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Preview only: proposed relayout for operator-safe industrial UI")

    def _build_status_strip(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("statusStrip")
        layout = QtWidgets.QGridLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        statuses = [
            ("CONNECTION", _status_chip("CONNECTED", "#CDEBD9")),
            ("RUN STATE", _status_chip("IDLE", "#E4E7EB")),
            ("MODE", _status_chip("RUN", "#D8E4F2")),
            ("ALARM", _status_chip("NORMAL", "#CDEBD9")),
            ("SELECTED CH", _status_chip("CH1", "#E9EEF3")),
            ("LAST RESPONSE", _status_chip("48 ms", "#E9EEF3")),
            ("ACTIVE PRESET", _status_chip("SET-01", "#E9EEF3")),
        ]

        for column, (caption, value_widget) in enumerate(statuses):
            caption_label = QtWidgets.QLabel(caption)
            caption_label.setProperty("role", "sectionCaption")
            caption_label.setObjectName(f"caption{column}")
            layout.addWidget(caption_label, 0, column)
            layout.addWidget(value_widget, 1, column)

        return frame

    def _build_monitor_panel(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_overview_group())
        layout.addWidget(self._build_trend_group(), 1)
        layout.addWidget(self._build_channel_summary_group())
        return widget

    def _build_overview_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Monitor Dashboard")
        layout = QtWidgets.QGridLayout(group)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        cards = [
            ("Selected Channel", "CH1", "Flow control / Recipe A"),
            ("Set vs Actual", "45.0% / 42.8%", "Tracking within tolerance"),
            ("Valve", "2.1 V", "Normal response"),
            ("Device Health", "Stable", "No active interlock"),
        ]
        for index, (caption, value, body) in enumerate(cards):
            frame = QtWidgets.QFrame()
            frame.setObjectName("noteFrame")
            frame_layout = QtWidgets.QVBoxLayout(frame)
            frame_layout.setContentsMargins(10, 8, 10, 8)
            caption_label = QtWidgets.QLabel(caption)
            caption_label.setProperty("role", "sectionCaption")
            value_label = QtWidgets.QLabel(value)
            value_label.setProperty("role", "heroValue")
            body_label = QtWidgets.QLabel(body)
            body_label.setWordWrap(True)
            body_label.setProperty("role", "placeholderBody")
            frame_layout.addWidget(caption_label)
            frame_layout.addWidget(value_label)
            frame_layout.addWidget(body_label)
            layout.addWidget(frame, 0, index)

        return group

    def _build_trend_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Trend Monitor")
        layout = QtWidgets.QVBoxLayout(group)
        info = QtWidgets.QLabel(
            "좌측 추세 영역은 목표선, 허용범위, 현재 채널, 최근 응답시간을 함께 보여주는 구조를 가정합니다."
        )
        info.setWordWrap(True)
        info.setProperty("role", "placeholderBody")
        layout.addWidget(info)

        placeholder = QtWidgets.QFrame()
        placeholder.setObjectName("trendPlaceholder")
        placeholder_layout = QtWidgets.QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(12, 12, 12, 12)

        title = QtWidgets.QLabel("Trend Area Placeholder")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setProperty("role", "placeholderTitle")
        body = QtWidgets.QLabel(
            "Ratio trend, valve trend, target line, alarm threshold, selected channel marker"
        )
        body.setAlignment(QtCore.Qt.AlignCenter)
        body.setWordWrap(True)
        body.setProperty("role", "placeholderBody")

        canvas = QtWidgets.QTableWidget(8, 12)
        canvas.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        canvas.setFocusPolicy(QtCore.Qt.NoFocus)
        canvas.horizontalHeader().hide()
        canvas.verticalHeader().hide()
        canvas.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        canvas.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        for row in range(canvas.rowCount()):
            canvas.setRowHeight(row, 30)
        for column in range(canvas.columnCount()):
            canvas.setColumnWidth(column, 56)
        for row in range(canvas.rowCount()):
            for column in range(canvas.columnCount()):
                item = QtWidgets.QTableWidgetItem("")
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                item.setBackground(QtGui.QColor("#F6F8FA" if (row + column) % 2 == 0 else "#EDF1F4"))
                canvas.setItem(row, column, item)

        placeholder_layout.addWidget(title)
        placeholder_layout.addWidget(body)
        placeholder_layout.addWidget(canvas, 1)
        layout.addWidget(placeholder, 1)
        return group

    def _build_channel_summary_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Channel Summary")
        layout = QtWidgets.QVBoxLayout(group)

        table = QtWidgets.QTableWidget(6, 6)
        table.setHorizontalHeaderLabels(["CH", "Role", "Set", "Actual", "Valve", "State"])
        table.verticalHeader().hide()
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        rows = [
            ("CH1", "Main", "45.0%", "42.8%", "2.1 V", "Ready"),
            ("CH2", "Aux", "20.0%", "19.9%", "1.1 V", "Ready"),
            ("CH3", "Aux", "0.0%", "0.0%", "0.0 V", "Idle"),
            ("CH4", "Reserve", "0.0%", "N/A", "Disabled", "Disabled"),
            ("CH5", "Reserve", "0.0%", "N/A", "Disabled", "Disabled"),
            ("CH6", "Reserve", "0.0%", "N/A", "Disabled", "Disabled"),
        ]
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QtWidgets.QTableWidgetItem(value)
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                table.setItem(row_index, column_index, item)
        table.selectRow(0)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        return group

    def _build_work_panel(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_operation_group())
        layout.addWidget(self._build_channel_detail_group())
        layout.addWidget(self._build_engineering_group(), 1)
        return widget

    def _build_operation_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Operation Control")
        layout = QtWidgets.QGridLayout(group)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        labels = [
            ("Port", "COM6"),
            ("Mode", "RUN"),
            ("Preset", "SET-01"),
        ]
        for row, (caption, value) in enumerate(labels):
            layout.addWidget(QtWidgets.QLabel(caption), row, 0)
            line = QtWidgets.QLineEdit(value)
            layout.addWidget(line, row, 1)

        button_row = QtWidgets.QHBoxLayout()
        start = QtWidgets.QPushButton("START")
        start.setObjectName("startButton")
        stop = QtWidgets.QPushButton("STOP")
        stop.setObjectName("stopButton")
        apply_btn = QtWidgets.QPushButton("APPLY SETPOINT")
        apply_btn.setObjectName("applyButton")
        hold = QtWidgets.QPushButton("HOLD")
        button_row.addWidget(start)
        button_row.addWidget(stop)
        button_row.addWidget(apply_btn)
        button_row.addWidget(hold)
        layout.addLayout(button_row, 3, 0, 1, 2)

        help_text = QtWidgets.QLabel(
            "위험 동작은 확인 대화상자와 인터락 상태 확인 후에만 활성화되는 구조를 가정합니다."
        )
        help_text.setWordWrap(True)
        help_text.setProperty("role", "placeholderBody")
        layout.addWidget(help_text, 4, 0, 1, 2)
        return group

    def _build_channel_detail_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Selected Channel")
        layout = QtWidgets.QVBoxLayout(group)

        form = QtWidgets.QGridLayout()
        fields = [
            ("Selected CH", "CH1"),
            ("Current Ratio", "42.8 %"),
            ("Target Ratio", "45.0 %"),
            ("Pressure", "0.9 bar"),
            ("Temperature", "28.3 C"),
            ("Response", "OK"),
        ]
        for row, (caption, value) in enumerate(fields):
            form.addWidget(QtWidgets.QLabel(caption), row, 0)
            line = QtWidgets.QLineEdit(value)
            if caption in {"Current Ratio", "Pressure", "Temperature", "Response"}:
                line.setReadOnly(True)
                line.setStyleSheet("QLineEdit { background: #EEF2F5; }")
            form.addWidget(line, row, 1)
        layout.addLayout(form)

        preset_table = QtWidgets.QTableWidget(4, 4)
        preset_table.setHorizontalHeaderLabels(["Preset", "CH1", "CH2", "Apply"])
        preset_table.verticalHeader().hide()
        preset_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        preset_rows = [
            ("SET-01", "45", "20", "Preview"),
            ("SET-02", "30", "15", "Preview"),
            ("SET-03", "10", "10", "Preview"),
            ("SET-04", "0", "0", "Preview"),
        ]
        for row_index, row in enumerate(preset_rows):
            for column_index, value in enumerate(row):
                preset_table.setItem(row_index, column_index, QtWidgets.QTableWidgetItem(value))
        preset_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(preset_table)
        return group

    def _build_engineering_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Engineering")
        layout = QtWidgets.QVBoxLayout(group)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_engineering_tab("Calibration", ["Valve Zero", "Valve Span", "Sensor Offset"]), "Calibration")
        tabs.addTab(self._build_engineering_tab("PID", ["KP", "KI", "KD", "Anti Windup"]), "PID")
        tabs.addTab(self._build_engineering_tab("TX / RX Frame", ["Last TX", "Last RX", "Protocol State"]), "Frame")
        layout.addWidget(tabs)
        return group

    def _build_engineering_tab(self, title: str, field_names: list[str]) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        info = QtWidgets.QLabel(f"{title} 영역은 운영 기본 흐름보다 낮은 우선순위의 보조 패널입니다.")
        info.setWordWrap(True)
        info.setProperty("role", "placeholderBody")
        layout.addWidget(info)

        form = QtWidgets.QFormLayout()
        for name in field_names:
            line = QtWidgets.QLineEdit("Preview")
            form.addRow(name, line)
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(QtWidgets.QPushButton("LOAD"))
        buttons.addWidget(QtWidgets.QPushButton("SAVE"))
        buttons.addStretch(1)
        layout.addLayout(buttons)

        dump = QtWidgets.QPlainTextEdit()
        dump.setPlainText("Preview area\n- details\n- diagnostics\n- engineer notes")
        layout.addWidget(dump, 1)
        return widget

    def _build_alarm_panel(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Alarm / Event Log")
        group.setMinimumHeight(180)
        layout = QtWidgets.QVBoxLayout(group)

        table = QtWidgets.QTableWidget(5, 6)
        table.setHorizontalHeaderLabels(["Time", "Severity", "Source", "Message", "Action Guide", "Ack"])
        table.verticalHeader().hide()
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        rows = [
            ("21:52:13", "INFO", "System", "Preview loaded", "No action", "Y"),
            ("21:52:15", "INFO", "CH1", "Setpoint applied", "Observe trend", "Y"),
            ("21:52:20", "WARN", "Sensor", "Response delay increased", "Check cable or load", "N"),
            ("21:52:25", "INFO", "Mode", "Engineering panel locked", "Run mode active", "Y"),
            ("21:52:30", "ALARM", "Interlock", "Placeholder only", "Review logic before release", "N"),
        ]
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QtWidgets.QTableWidgetItem(value)
                if column_index == 1:
                    if value == "WARN":
                        item.setBackground(QtGui.QColor("#F7E3B5"))
                    elif value == "ALARM":
                        item.setBackground(QtGui.QColor("#F2C4BF"))
                    else:
                        item.setBackground(QtGui.QColor("#D8E4F2"))
                table.setItem(row_index, column_index, item)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        return group
