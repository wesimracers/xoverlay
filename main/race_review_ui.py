"""Post-race participant table and manual iRacing ID management."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class DriverReviewDialog(QDialog):
    def __init__(self, blacklist_store, event=None, on_saved=None, parent=None):
        super().__init__(parent)
        self.store = blacklist_store
        self.event = event
        self.on_saved = on_saved
        self.saved = False
        self._checkboxes = []
        saved_ids = blacklist_store.read_ids()
        participants = list(event.get("participants", [])) if event else [
            {"id": user_id, "number": "—", "name": f"iRacing ID {user_id}"}
            for user_id in sorted(saved_ids)
        ]

        self.setWindowTitle("Race drivers" if event else "Manage marked drivers")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(570, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Select drivers, then click Save. Marks apply to future sessions."
            if event else "IDs marked in Relative. Clear a checkbox to remove an ID, or add one below."
        ))

        table = QTableWidget(len(participants), 3, self)
        table.setHorizontalHeaderLabels(["Car number", "Driver name", "Mark"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setColumnWidth(0, 130)
        table.setColumnWidth(2, 75)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        for row_index, person in enumerate(participants):
            number = QTableWidgetItem(str(person.get("number") or "—"))
            display_name = str(person.get("name") or "Unnamed driver")
            if display_name == "Piloto sem nome":  # fallback saved by older builds
                display_name = "Unnamed driver"
            name = QTableWidgetItem(display_name)
            user_id = person.get("id")
            if user_id is not None:
                name.setToolTip(f"iRacing ID: {user_id}")
            table.setItem(row_index, 0, number)
            table.setItem(row_index, 1, name)
            checkbox = QCheckBox()
            checkbox.setChecked(user_id in saved_ids)
            checkbox.setEnabled(user_id is not None)
            if user_id is None:
                checkbox.setToolTip("UserID unavailable; a name or car number cannot identify a driver safely.")
            holder = QWidget()
            centered = QHBoxLayout(holder)
            centered.setContentsMargins(0, 0, 0, 0)
            centered.addStretch()
            centered.addWidget(checkbox)
            centered.addStretch()
            table.setCellWidget(row_index, 2, holder)
            self._checkboxes.append((user_id, checkbox))
        self.table = table
        layout.addWidget(table)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Add iRacing ID:"))
        self.manual_id = QLineEdit()
        self.manual_id.setPlaceholderText("Positive number only")
        manual_row.addWidget(self.manual_id)
        layout.addLayout(manual_row)
        layout.addWidget(QLabel('You can also edit blacklist.json: {"ids": [12345, 67890]}'))

        buttons = QHBoxLayout()
        buttons.addStretch()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)
        close_button = QPushButton("Close without saving")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _save(self):
        visible_ids = {user_id for user_id, _box in self._checkboxes if user_id is not None}
        selected_ids = {user_id for user_id, box in self._checkboxes
                        if user_id is not None and box.isChecked()}
        try:
            self.store.save_selection(visible_ids, selected_ids, self.manual_id.text())
        except (OSError, ValueError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Could not write blacklist.json. Check file access and try again."
            warning = QMessageBox(self)
            warning.setIcon(QMessageBox.Icon.Warning)
            warning.setWindowTitle("Could not save")
            warning.setText(message)
            warning.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            warning.exec()
            return
        self.saved = True
        if self.on_saved is not None:
            self.on_saved(self.event)
        self.accept()
