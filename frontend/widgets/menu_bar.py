"""Menu bar along the top of the signed-in window, like the classic one in Word or Excel.

File, Edit, View, Terminal, Options and Help, each with keyboard shortcuts shown next
to its items. The Terminal menu is gkonsol's, as VS Code has one for its terminal.
The Edit commands act on the text field that has the cursor, as in Word;
items that cannot apply are greyed out while the menu is open. The other actions
are given their meaning by the window the menu bar belongs to (see ``HomeWindow``).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QMenu,
    QMenuBar,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from backend.dto.version_dto import AppVersionDTO
from frontend import appearance, layout_mode, palette, theme, theming

def _stylesheet():
    return f"""
QMenuBar {{
    background: {theme.WHITE}; border: none; border-bottom: 1px solid {theme.BORDER};
    padding: 2px 6px; color: {theme.INK};
}}
QMenuBar::item {{ background: transparent; padding: 5px 12px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {theme.FOAM}; }}
QMenuBar::item:pressed {{ background: {theme.MINT}; }}
QPushButton#UpdateBadge {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E05638, stop:1 #D35400);
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 600;
    border: none;
    border-radius: 11px;
    padding: 3px 12px;
    margin-top: 2px;
    margin-bottom: 2px;
    margin-right: 8px;
}}
QPushButton#UpdateBadge:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #D35400, stop:1 #BA4A00);
}}
QPushButton#UpdateBadge:pressed {{
    background: #A04000;
}}
""" + theme.MENU_STYLE


# Terminal menu items that run a gkonsol command, in groups: (label, the command typed in the terminal).
TERMINAL_COMMANDS: tuple[tuple[tuple[str, str], ...], ...] = (
    (
        ("Check &everything", "doctor"),
        ("&Verify Earth Engine sign-in", "gee verify"),
        ("Sign &in to Earth Engine…", "gee login"),
        ("Verify my sessi&on", "session verify"),
    ),
    (
        ("&Watch download progress", "download watch"),
        ("Download s&peed chart", "download speed"),
        ("&List downloads", "download list"),
    ),
    (
        ("gkonsol &help", "help"),
    ),
)


class AppMenuBar(QMenuBar):
    theme_chosen = pyqtSignal(str)  # a theme other than the current one, e.g. "dark-green"
    update_requested = pyqtSignal(object)   # AppVersionDTO: the user clicked the update badge
    layout_chosen = pyqtSignal(str)  # a layout other than the current one, e.g. "modern"
    terminal_command = pyqtSignal(str)  # a gkonsol command to run in the terminal, e.g. "gee verify"
    recent_project_chosen = pyqtSignal(str)  # the folder of a project in File > Recent projects

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        theming.styled(self, _stylesheet)

        self.file_menu = self._menu("&File")
        self.new_project = self._action(self.file_menu, "New &project…", "Ctrl+Shift+N")
        self.open_project = self._action(self.file_menu, "Open pro&ject…", "Ctrl+Shift+O")
        self.recent_projects_menu = self.file_menu.addMenu("Recen&t projects")
        theming.styled(self.recent_projects_menu, lambda: theme.MENU_STYLE)
        self.rename_project = self._action(self.file_menu, "Rena&me project…")
        self.move_project = self._action(self.file_menu, "Mo&ve project…")
        self.close_project = self._action(self.file_menu, "C&lose project")
        self.file_menu.addSeparator()
        self.new_request = self._action(self.file_menu, "&New request", "Ctrl+N")
        self.open_geotiff = self._action(self.file_menu, "&Open GeoTIFF…", "Ctrl+O")
        self.file_menu.addSeparator()
        self.sign_out = self._action(self.file_menu, "Sign &out")
        self.exit = self._action(self.file_menu, "E&xit", "Ctrl+Q")

        self.edit_menu = self._menu("&Edit")
        self.undo = self._action(self.edit_menu, "&Undo", QKeySequence.StandardKey.Undo)
        self.redo = self._action(self.edit_menu, "&Redo", "Ctrl+Y")
        self.edit_menu.addSeparator()
        self.cut = self._action(self.edit_menu, "Cu&t", QKeySequence.StandardKey.Cut)
        self.copy = self._action(self.edit_menu, "&Copy", QKeySequence.StandardKey.Copy)
        self.paste = self._action(self.edit_menu, "&Paste", QKeySequence.StandardKey.Paste)
        self.edit_menu.addSeparator()
        self.select_all = self._action(self.edit_menu, "Select &all", QKeySequence.StandardKey.SelectAll)
        self._edit_commands = {
            self.undo: "undo", self.redo: "redo", self.cut: "cut",
            self.copy: "copy", self.paste: "paste", self.select_all: "selectAll",
        }
        for action, command in self._edit_commands.items():
            action.triggered.connect(lambda _=False, command=command: self._run_edit(command))
        self.edit_menu.aboutToShow.connect(self._update_edit_items)
        self.edit_menu.aboutToHide.connect(self._enable_edit_items)  # shortcuts keep working afterwards

        self.view_menu = self._menu("&View")
        self.view_dashboard = self._action(self.view_menu, "&Dashboard", "Ctrl+1")
        self.view_query_input = self._action(self.view_menu, "&Query Input", "Ctrl+2")
        self.view_downloads = self._action(self.view_menu, "Do&wnloads", "Ctrl+3")
        self.view_account = self._action(self.view_menu, "&Account", "Ctrl+4")
        self.view_analysis = self._action(self.view_menu, "A&nalysis", "Ctrl+5")
        self.view_reports = self._action(self.view_menu, "&Reports", "Ctrl+7")
        self.view_vector_maps = self._action(self.view_menu, "&Vector maps", "Ctrl+8")
        self.view_dem = self._action(self.view_menu, "&Digital Elevation Model", "Ctrl+9")
        self.view_idw = self._action(self.view_menu, "&IDW interpolation", "Ctrl+0")
        self.view_prediction = self._action(self.view_menu, "&Prediction (ML)", "Ctrl+Shift+P")
        self.view_data_catalog = self._action(self.view_menu, "Data &catalog", "Ctrl+Shift+D")
        self.view_menu.addSeparator()
        # The analysis table (formulas and use cases of every index) is opened only from here.
        self.view_analysis_table = self._action(self.view_menu, "Show analysis ta&ble", "Ctrl+6")
        self.view_menu.addSeparator()
        self.toggle_side_bar = self._action(self.view_menu, "&Side bar", "Ctrl+B", checkable=True)
        self.toggle_terminal = self._action(self.view_menu, "&Terminal", "Ctrl+`", checkable=True)
        self.full_screen = self._action(self.view_menu, "&Full screen", "F11", checkable=True)
        self.view_menu.addSeparator()
        # Layout: the original "classical" workspace, or the "modern" map-first panel.
        self.layout_menu = self.view_menu.addMenu("&Layout")
        theming.styled(self.layout_menu, lambda: theme.MENU_STYLE)
        self.layout_actions: dict[str, QAction] = {}
        layout_group = QActionGroup(self)  # one layout at a time
        current_layout = layout_mode.current_layout()
        for name, label in layout_mode.LAYOUTS.items():
            action = self._action(self.layout_menu, label, checkable=True)
            action.setChecked(name == current_layout)
            action.triggered.connect(lambda _=False, name=name: self._choose_layout(name))
            layout_group.addAction(action)
            self.layout_actions[name] = action
        self.theme_menu = self.view_menu.addMenu("&Theme")
        theming.styled(self.theme_menu, lambda: theme.MENU_STYLE)
        self.theme_actions: dict[str, QAction] = {}
        group = QActionGroup(self)  # one theme at a time
        for name, label in appearance.THEMES.items():
            action = self._action(self.theme_menu, label, checkable=True)
            action.setChecked(name == palette.THEME)
            action.triggered.connect(lambda _=False, name=name: self._choose_theme(name))
            group.addAction(action)
            self.theme_actions[name] = action

        self.terminal_menu = self._menu("&Terminal")
        self.terminal_menu.setToolTipsVisible(True)
        # Ctrl+` belongs to View → Terminal; after the tab, the menu only shows it.
        self.show_terminal = self._action(self.terminal_menu, "&Show terminal\tCtrl+`", checkable=True)
        self.show_terminal.setToolTip("Show or hide gkonsol, the command line (Ctrl+`)")
        self.maximize_terminal = self._action(self.terminal_menu, "&Maximise terminal", checkable=True)
        self.maximize_terminal.setToolTip("Let the terminal fill the window")
        self.clear_terminal = self._action(self.terminal_menu, "&Clear terminal")
        self.stop_command = self._action(self.terminal_menu, "S&top running command")
        self.stop_command.setToolTip("Stop the command that is running, as Ctrl+C does in the terminal")
        self.terminal_commands: dict[str, QAction] = {}  # gkonsol command -> its menu item
        for items in TERMINAL_COMMANDS:
            self.terminal_menu.addSeparator()
            for label, command in items:
                action = self._action(self.terminal_menu, label)
                action.setToolTip(f"Runs '{command}' in the terminal")
                action.triggered.connect(lambda _=False, command=command: self.terminal_command.emit(command))
                self.terminal_commands[command] = action
        self.command_reference = self._action(self.terminal_menu, "Command &reference")
        self.command_reference.setToolTip("Every gkonsol command, with examples (docs/GKONSOL.md)")

        self.options_menu = self._menu("&Options")
        self.app_settings = self._action(self.options_menu, "&Settings…", "Ctrl+,")
        self.app_settings.setToolTip("Earth Engine project, Gemini API key, how long you stay signed in")
        self.chunk_size = self._action(self.options_menu, "Download &chunk size…")
        self.manage_users = self._action(self.options_menu, "&Manage users…")

        self.help_menu = self._menu("&Help")
        self.give_feedback = self._action(self.help_menu, "&Rate, feedback or suggestion…")
        self.give_feedback.setToolTip("Rate GEE-Assist, send feedback or suggest a feature on the website")
        self.help_menu.addSeparator()
        self.about = self._action(self.help_menu, "&About GEE-Assist")

        # ---- update available badge (shown on the right side of the navbar if an update is available)
        self._update_info: AppVersionDTO | None = None
        self.update_button = QPushButton("Update Available", self)
        self.update_button.setObjectName("UpdateBadge")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.clicked.connect(self._show_update_dialog)
        self.update_button.hide()
        self.setCornerWidget(self.update_button, Qt.Corner.TopRightCorner)

    # ------------------------------------------------------------- Update Available
    def set_update_info(self, info: AppVersionDTO) -> None:
        self._update_info = info
        self.update_button.setText(f"● Update Available (v{info.latest_version})")
        self.update_button.setToolTip(
            f"A newer version (v{info.latest_version}) of GEE-Assist is available!\nClick to view release details."
        )
        self.update_button.show()

    def clear_update_info(self) -> None:
        self._update_info = None
        self.update_button.hide()

    def _show_update_dialog(self) -> None:
        if self._update_info is not None:
            self.update_requested.emit(self._update_info)   # the window opens the dialog (it has the facade)

    # ------------------------------------------------------------- Theme
    def _choose_theme(self, name: str) -> None:
        if name != palette.THEME:
            self.theme_chosen.emit(name)

    def show_current_theme(self) -> None:
        """Tick the theme in use again (e.g. when switching was cancelled)."""
        self.theme_actions[palette.THEME].setChecked(True)

    # ------------------------------------------------------------- Layout
    def _choose_layout(self, name: str) -> None:
        if name != layout_mode.current_layout():
            self.layout_chosen.emit(name)

    def show_current_layout(self) -> None:
        """Tick the layout in use again (e.g. when switching was cancelled)."""
        self.layout_actions[layout_mode.current_layout()].setChecked(True)

    # ------------------------------------------------------------- Edit
    @staticmethod
    def edit_target() -> QWidget | None:
        """The text field the Edit commands apply to: the one with the cursor, if any."""
        widget = QApplication.focusWidget()
        if isinstance(widget, QComboBox) and widget.isEditable():
            widget = widget.lineEdit()
        return widget if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)) else None

    def _run_edit(self, command: str) -> None:
        target = self.edit_target()
        if target is not None:
            getattr(target, command)()

    def _update_edit_items(self) -> None:
        target = self.edit_target()
        if target is None:
            for action in self._edit_commands:
                action.setEnabled(False)
            return
        writable = not target.isReadOnly()
        if isinstance(target, QLineEdit):
            selected = target.hasSelectedText()
            can_undo, can_redo = target.isUndoAvailable(), target.isRedoAvailable()
            can_paste = bool(QApplication.clipboard().text())
        else:
            selected = target.textCursor().hasSelection()
            document = target.document()
            can_undo, can_redo = document.isUndoAvailable(), document.isRedoAvailable()
            can_paste = target.canPaste()
        self.undo.setEnabled(writable and can_undo)
        self.redo.setEnabled(writable and can_redo)
        self.cut.setEnabled(writable and selected)
        self.copy.setEnabled(selected)
        self.paste.setEnabled(writable and can_paste)
        self.select_all.setEnabled(True)

    def _enable_edit_items(self) -> None:
        for action in self._edit_commands:
            action.setEnabled(True)

    def set_projects(self, current, recent: list) -> None:
        """The open project (a ProjectDTO or None) and the recent ones (File > Recent projects)."""
        for action in (self.rename_project, self.move_project, self.close_project):
            action.setEnabled(current is not None)
        self.recent_projects_menu.clear()
        for project in recent:
            action = self.recent_projects_menu.addAction(f"{project.name}  —  {project.location}")
            action.setToolTip(project.folder)
            action.triggered.connect(lambda _=False, folder=project.folder: self.recent_project_chosen.emit(folder))
        if not recent:
            self.recent_projects_menu.addAction("No recent projects").setEnabled(False)

    def _menu(self, title: str) -> QMenu:
        menu = self.addMenu(title)
        theming.styled(menu, lambda: theme.MENU_STYLE)
        return menu

    def _action(self, menu: QMenu, text: str, shortcut=None, checkable: bool = False) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        menu.addAction(action)
        return action
