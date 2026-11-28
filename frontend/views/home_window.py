"""Window shown after signing in.

A menu bar along the top (File, Edit, View, Terminal, Options, Help) over a side bar on the
left (logo, navigation and the signed-in user) next to the pages: the dashboard (start
page), the query-input workspace, downloads, analysis, the AI explanation of an analysis
result, the PDF reports made from explanations, the account card, the GeoTIFF viewer (opened
from a finished download) and the analysis table (View → Show analysis table only). Clicking
the GEE-Assist logo shows the dashboard (there is no back button); clicking the user opens
the account menu (account options and "Sign out"). The side bar opens while the pointer is
over it, sliding over the page rather than pushing it aside; View → Side bar (Ctrl+B) keeps it
open, and then it takes its own room beside the page.

Below the pages is the terminal, gkonsol, as in VS Code: hidden until opened from the
side bar's Terminal button, the Terminal menu or View → Terminal (Ctrl+`), and as tall
as the user drags it. The Terminal menu also runs common commands in it.

After every AI explanation, whenever the user goes from the AI explanation page to the
dashboard, and whenever they come back to the dashboard after running an analysis, a modal asks them to rate the app, send feedback or suggest a feature; the choice
opens that tab of the website's community page in the browser.
"""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QPoint, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QKeySequence, QMouseEvent, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.dto.project_dto import ProjectDTO
from backend.dto.user_dto import UserDTO
from backend.dto.version_dto import AppVersionDTO
from backend.exceptions import GeeAssistError
from frontend import appearance, assets, fieldbook, layout_mode, palette, theme, theming
from frontend.project_paths import current_project, downloads_folder
from frontend.views.account_view import AccountView, Avatar, SignupDetailsDialog
from frontend.views.project_dialogs import ProjectActions
from frontend.views.settings_dialog import SettingsDialog, settings_needed
from frontend.views.analysis_table_view import AnalysisTableView
from frontend.views.analysis_view import AnalysisView
from frontend.views.explanation_view import ExplanationView
from frontend.views.feedback_dialog import ask_for_feedback
from frontend.views.reports_view import ReportsView
from frontend.restart import restart_app
from frontend.workers.task_worker import run_task
from frontend.views.auth.hero_panel import round_logo
from frontend.views.dashboard_view import DashboardView
from frontend.views.download_view import DownloadView
from frontend.views.main_window import MainWindow
from frontend.views.raster_viewer_view import RasterViewerView
from frontend.views.vector_map_view import VectorMapView
from frontend.views.dem_view import DemView
from frontend.views.idw_view import IdwView
from frontend.views.prediction_view import PredictionView
from frontend.views.data_catalog_view import DataCatalogView
from frontend.gkonsol.form_port import WidgetForm
from frontend.gkonsol.help import REFERENCE_FILE
from frontend.gkonsol.history import GkonsolStore, History
from frontend.gkonsol.panel import GkonsolPanel, TerminalArea
from frontend.gkonsol.ports import MemoryForm
from frontend.views.user_admin_view import UserAdminDialog
from frontend.widgets.menu_bar import AppMenuBar
from frontend.widgets.side_bar import COLLAPSED_WIDTH, EXPANDED_WIDTH, LOGO_SIZE, SideBar
from frontend.widgets.side_icons import (
    AnalysisIcon,
    CatalogIcon,
    DownloadIcon,
    ExplainIcon,
    InterpolateIcon,
    PredictIcon,
    TerminalIcon,
    TerrainIcon,
    VectorIcon,
    WritingIcon,
)
from frontend.views.result_picker_dialog import choose_result

def _pages_background_css() -> str:
    """The pages' ground: Layout 3 rules it like a field book on an 8px module."""
    if fieldbook.active():
        return (f"#HomePages, #DashboardPage {{ background-color: {palette.ACTIVE['PAGE_BG']}; "
                f"background-image: url({fieldbook.grid_tile()}); background-repeat: repeat-xy; }}")
    return f"#HomePages, #DashboardPage {{ background: {_page_background()}; }}"


def _page_background() -> str:
    return (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {theme.PAGE_GRADIENT_TOP}, stop:0.6 {theme.PAGE_GRADIENT_MIDDLE}, stop:1 {theme.PAGE_GRADIENT_BOTTOM})"
    )

# Why the feedback modal is shown (its first line).
AFTER_EXPLANATION = "Your AI explanation is ready. Was it useful?"
BACK_FROM_EXPLANATION = "Thanks for trying the AI explanation."
AFTER_ANALYSIS = "Your analysis is done. How did it go?"
FEEDBACK_DELAY_MS = 800  # the explanation is drawn (and seen) before the modal opens

# Why a project is needed (the first lines of the "A project is needed" message).
DOWNLOAD_NEEDS_PROJECT = "Datasets are downloaded into a project's downloads folder."
EXPLANATION_NEEDS_PROJECT = "AI explanations are made from the analysis results saved in a project."
QUERY_NEEDS_PROJECT = "A request is filled for the open project: its data is downloaded into the project's folder."


class SideBarHost(QWidget):
    """The window's central widget: the side bar floats over the pages' left edge, as tall as
    the window, while the layout keeps ``room`` for it: its collapsed width, or all of it when
    it is kept open. Opening on hover then slides over the page instead of reflowing it."""

    def __init__(self, side_bar: SideBar, pages: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.side_bar = side_bar
        self.room = QWidget()
        self.room.setFixedWidth(EXPANDED_WIDTH if side_bar.is_pinned() else COLLAPSED_WIDTH)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.room)
        layout.addWidget(pages, 1)
        side_bar.setParent(self)
        side_bar.raise_()  # above the pages
        side_bar.pinned_changed.connect(self._pinned)

    def _pinned(self, pinned: bool) -> None:
        self.room.setFixedWidth(EXPANDED_WIDTH if pinned else COLLAPSED_WIDTH)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self.side_bar.setGeometry(0, 0, self.side_bar.width(), self.height())
        self.side_bar.raise_()


class ProfileButton(QFrame):
    """The signed-in user at the bottom of the side bar: avatar, plus name and role when expanded."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ProfileButton")
        theming.styled(self, lambda: (
            f"#ProfileButton {{ border-radius: 8px; }} #ProfileButton:hover {{ background: "
            f"{fieldbook.cover_raised() if fieldbook.active() else theme.FOAM}; }}"
        ))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Your account")
        self.avatar = Avatar(38)
        self.name = QLabel()
        theming.styled(self.name, lambda: (
            f"color: {fieldbook.cover_text() if fieldbook.active() else theme.INK}; font-weight: 600;"))
        self.role = QLabel(objectName="Muted")
        for label in (self.name, self.role):  # clipped, not holding the bar open, while it slides
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # Name and role in one widget: hidden, it takes no room, so the avatar can centre.
        self.details = QWidget()
        self.details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        who = QVBoxLayout(self.details)
        who.setContentsMargins(0, 0, 0, 0)
        who.setSpacing(0)
        who.addWidget(self.name)
        who.addWidget(self.role)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(6, 6, 6, 6)
        self._row.setSpacing(10)
        self._row.addWidget(self.avatar)
        self._row.addWidget(self.details, 1)

    def set_user(self, user: UserDTO, photo: bytes | None = None) -> None:
        self.avatar.set_user(user, photo)
        self.name.setText(user.full_name)
        self.role.setText("Administrator" if user.is_admin else "User")

    def set_compact(self, compact: bool) -> None:
        self.details.setVisible(not compact)
        self._row.setAlignment(self.avatar, Qt.AlignmentFlag.AlignHCenter if compact else Qt.AlignmentFlag.AlignLeft)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class TerminalApp:
    """What gkonsol's commands can do in the signed-in window (its ``AppPort``)."""

    def __init__(self, window: "HomeWindow"):
        self._window = window

    def current_page(self) -> str:
        window = self._window
        pages = {window.dashboard: "dashboard", window.query_input: "query", window.downloads: "downloads",
                 window._account_page: "account"}
        return pages.get(window.current_page(), "dashboard")

    def show_page(self, page: str) -> None:
        window = self._window
        {"dashboard": window.show_dashboard, "query": window.show_query_input, "downloads": window.show_downloads,
         "account": window.show_account}[page]()

    def sign_out(self) -> None:
        self._window.sign_out()

    def is_side_bar_expanded(self) -> bool:
        return self._window.side_bar.is_pinned()  # "on": kept open, as View → Side bar

    def set_side_bar_expanded(self, expanded: bool) -> None:
        self._window.side_bar.set_pinned(expanded)

    def is_full_screen(self) -> bool:
        return self._window.isFullScreen()

    def set_full_screen(self, on: bool) -> None:
        self._window.set_full_screen(on)

    def switch_theme(self, theme_name: str) -> None:
        self._window.change_theme(theme_name)  # live, like View → Theme

    def open_path(self, path: str) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_url(self, url: str) -> bool:
        return QDesktopServices.openUrl(QUrl(url))

    def open_user_admin(self) -> None:
        self._window.open_user_admin()

    def quit(self) -> None:
        self._window.exit_app()


class HomeWindow(QMainWindow):
    signed_out = pyqtSignal(str)  # message for the sign-in screen

    def __init__(self, facade: IBusinessFacade, user: UserDTO, parent: QWidget | None = None):
        super().__init__(parent)
        self._facade = facade
        self._user = user
        self.setWindowTitle("GEE-Assist")
        self.setMinimumSize(1000, 680)

        # ---- side bar
        # ---- menu bar (File, Edit, View, ...) above every page
        self.menu_bar = AppMenuBar(self)
        self.setMenuBar(self.menu_bar)

        # Layout 3 is a power workspace: its index stays open.
        self.side_bar = SideBar(round_logo(LOGO_SIZE, self.devicePixelRatioF()), expanded=fieldbook.active())
        self.query_input_button = self.side_bar.add_button("Query Input", "Q", icon=WritingIcon())
        self.downloads_button = self.side_bar.add_button("Downloads", "D", icon=DownloadIcon())
        self.analysis_button = self.side_bar.add_button("Analysis", "A", icon=AnalysisIcon())
        self.analysis_button.setToolTip("Analysis: run vegetation, water, burn, ... analyses on a dataset (Ctrl+5)")
        self.vector_button = self.side_bar.add_button("Vector Maps", "V", icon=VectorIcon())
        self.vector_button.setToolTip("Vector Maps: open a shapefile (.shp) and explore its features (Ctrl+8)")
        self.dem_button = self.side_bar.add_button("Elevation (DEM)", "E", icon=TerrainIcon())
        self.dem_button.setToolTip("Digital Elevation Model: hillshade, slope, aspect and contours from a DEM (Ctrl+9)")
        self.idw_button = self.side_bar.add_button("IDW Interpolation", "I", icon=InterpolateIcon())
        self.idw_button.setToolTip("IDW: interpolate a point shapefile's values into a surface (Ctrl+0)")
        self.prediction_button = self.side_bar.add_button("Prediction (ML)", "P", icon=PredictIcon())
        self.prediction_button.setToolTip("Prediction (ML): forecast values, future land cover, classify or find "
                                          "anomalies from past and present images (Ctrl+Shift+P)")
        self.catalog_button = self.side_bar.add_button("Data Catalog", "C", icon=CatalogIcon())
        self.catalog_button.setToolTip("Data Catalog: download boundaries, basemaps and OSM data (Ctrl+Shift+D)")
        self.explain_button = self.side_bar.add_button("AI Explanation", "AI", icon=ExplainIcon())
        self.explain_button.setToolTip("AI Explanation: choose an analysis result of the open project and "
                                       "let Gemini explain it")
        self.terminal_button = self.side_bar.add_button("Terminal", "T", icon=TerminalIcon())
        self.terminal_button.setCheckable(True)  # lit while the terminal is open
        self.terminal_button.setToolTip("Terminal: gkonsol, the GEE-Assist command line (Ctrl+`)")
        self.manage_users = self.side_bar.add_button("Manage users", "M")
        self.manage_users.setToolTip("Administrators: view accounts, change roles, enable or disable users")
        self.profile = ProfileButton()
        self.side_bar.add_widget(self.profile, footer=True)

        # ---- account menu
        self.account_menu = QMenu(self)
        theming.styled(self.account_menu, lambda: theme.MENU_STYLE)
        self.manage_account_action = QAction("Manage account", self)
        self.manage_account_action.setToolTip("Edit your details, change your password or profile photo")
        self.signup_details_action = QAction("Sign-up details", self)
        self.sign_out_action = QAction("Sign out", self)
        for action in (self.manage_account_action, self.signup_details_action):
            self.account_menu.addAction(action)
        self.account_menu.addSeparator()
        self.account_menu.addAction(self.sign_out_action)

        # ---- pages
        self.dashboard = DashboardView(facade)

        # The query-input workspace (parameter form + kept requests) is a QMainWindow
        # of its own; shown as a page it is embedded as a plain widget.
        self.query_input = MainWindow(facade)
        self.query_input.setWindowFlags(Qt.WindowType.Widget)
        self.downloads = DownloadView(facade)
        self.viewer = RasterViewerView(facade)
        self.analysis = AnalysisView(facade)
        self.vector_maps = VectorMapView(facade)
        self.dem = DemView(facade)
        self.idw = IdwView(facade)
        self.prediction = PredictionView(facade)
        self.data_catalog = DataCatalogView(facade)
        self.explanation = ExplanationView(facade)
        self.reports = ReportsView(facade)
        self.analysis_table = AnalysisTableView(facade)

        self.account = AccountView(facade)
        # The account card uses the page's width (up to its maximum) and scrolls in a short window.
        account_content = QFrame(objectName="HomeContent")
        theming.styled(account_content, lambda: f"#HomeContent {{ background: {_page_background()}; }}")
        page_layout = QVBoxLayout(account_content)
        page_layout.setContentsMargins(36, 32, 36, 32)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.account, 100)
        row.addStretch(1)
        page_layout.addLayout(row)
        page_layout.addStretch(1)
        account_page = QScrollArea(objectName="AccountPage")
        account_page.setWidgetResizable(True)
        account_page.setFrameShape(QFrame.Shape.NoFrame)
        account_page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        account_page.setWidget(account_content)

        self.pages = QStackedWidget(objectName="HomePages")
        theming.styled(self.pages, _pages_background_css)
        self.dashboard.setObjectName("DashboardPage")
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.query_input)
        self.pages.addWidget(self.downloads)
        self.pages.addWidget(account_page)
        self.pages.addWidget(self.viewer)
        self.pages.addWidget(self.analysis)
        self.pages.addWidget(self.vector_maps)
        self.pages.addWidget(self.dem)
        self.pages.addWidget(self.idw)
        self.pages.addWidget(self.prediction)
        self.pages.addWidget(self.data_catalog)
        self.pages.addWidget(self.explanation)
        self.pages.addWidget(self.reports)
        self.pages.addWidget(self.analysis_table)
        self._account_page = account_page
        # The side bar button of each page that has one: highlighted while its page is shown.
        self.page_buttons = {
            self.query_input: self.query_input_button,
            self.downloads: self.downloads_button,
            self.analysis: self.analysis_button,
            self.vector_maps: self.vector_button,
            self.dem: self.dem_button,
            self.idw: self.idw_button,
            self.prediction: self.prediction_button,
            self.data_catalog: self.catalog_button,
            self.explanation: self.explain_button,
        }

        # ---- terminal (gkonsol) under the pages
        store = GkonsolStore()
        self.terminal = GkonsolPanel()
        pages_host = self._fieldbook_pages_host() if fieldbook.active() else self.pages
        self.terminal_area = TerminalArea(pages_host, self.terminal, store)
        form_view = getattr(self.query_input, "form_view", None)
        form = WidgetForm(form_view) if form_view is not None else MemoryForm(facade)
        self.terminal.start(facade, TerminalApp(self), form, self.terminal_area, History(store))

        self.setCentralWidget(SideBarHost(self.side_bar, self.terminal_area))

        self.sign_out_action.triggered.connect(self.sign_out)
        self.account.session_expired.connect(
            lambda: self.signed_out.emit("Your session has expired. Please sign in again.")
        )
        self.manage_users.clicked.connect(self.open_user_admin)
        self.side_bar.home_requested.connect(self.show_dashboard)  # the GEE-Assist logo leads home
        self.profile.clicked.connect(self.show_account_menu)
        self.manage_account_action.triggered.connect(self.manage_account)
        self.account.user_changed.connect(self.set_user)  # e.g. a new name or photo shows in the side bar
        self.signup_details_action.triggered.connect(self.show_signup_details)
        self.projects = ProjectActions(facade, self)
        self.projects.project_changed.connect(lambda _project: self.refresh_projects())
        dashboard = self.dashboard
        dashboard.open_recent.connect(self.projects.open_folder)
        dashboard.open_result.connect(self.show_viewer)  # a result map on the dashboard
        dashboard.new_project_requested.connect(self.projects.new_project)  # dashboard "Create project"
        dashboard.open_project_requested.connect(self.projects.open_project)  # dashboard "Open project"
        self.query_input_button.clicked.connect(self.show_query_input)
        self.downloads_button.clicked.connect(self.show_downloads)
        self.analysis_button.clicked.connect(self.show_analysis)
        self.vector_button.clicked.connect(self.show_vector_maps)
        self.dem_button.clicked.connect(self.show_dem)
        self.idw_button.clicked.connect(self.show_idw)
        self.prediction_button.clicked.connect(self.show_prediction)
        self.prediction.show_on_map_requested.connect(self.show_on_map)
        self.catalog_button.clicked.connect(self.show_data_catalog)
        self.data_catalog.open_requested.connect(self.open_downloaded_dataset)
        self.explain_button.clicked.connect(self.explain_saved_result)
        self.result_chooser = choose_result  # (results, project name, parent) -> result or None; tests replace it
        self.terminal_button.clicked.connect(self.toggle_terminal)
        self.terminal_area.visibility_changed.connect(self._terminal_shown)
        app = QApplication.instance()
        if app is not None:  # a command still running when the app quits is stopped first
            app.aboutToQuit.connect(self.terminal.shutdown)
        self.query_input.download_requested.connect(self.start_download)
        self.downloads.view_requested.connect(self.show_viewer)
        self.viewer.show_on_map_requested.connect(self.show_on_map)
        self.analysis.show_on_map_requested.connect(self.show_on_map)
        self.analysis.open_in_viewer_requested.connect(self.show_viewer)
        self.analysis.explain_requested.connect(self.show_explanation)
        self.explanation.back_requested.connect(self.show_analysis)
        self.explanation.result_saved.connect(self.analysis.set_saved_result)
        self.explanation.report_requested.connect(self.show_reports)
        self.explanation.explanation_ready.connect(
            lambda _explanation: self.later(FEEDBACK_DELAY_MS, lambda: self.ask_for_feedback(AFTER_EXPLANATION)))
        self.feedback_prompt = ask_for_feedback  # (parent, reason) -> tab opened or None; tests replace it
        self._asking_feedback = False
        self._analysis_since_dashboard = False  # an analysis ran since the dashboard was last shown
        self.analysis.analysis_finished.connect(self._on_analysis_finished)
        self._connect_menu_bar()
        self._admin_dialog: UserAdminDialog | None = None
        self._was_maximized = False  # before going full screen
        self.full_map = None         # the full-screen "Show on map" window, while open
        self.set_user(user)
        self._project_shown: str | None = "none yet"
        self.refresh_projects()
        if fieldbook.active():
            self._assemble_fieldbook_shell()
        self.show_dashboard()
        # A new copy of the app: ask for the Earth Engine project and Gemini key once the window is up.
        self.later(0, self.check_first_run)
        # Check if a new version of the app is available (runs in background off UI thread)
        self.later(500, self.check_for_updates)

    def _assemble_fieldbook_shell(self) -> None:
        """Layout 3: the side bar becomes the field book's index. Pages are grouped by division and
        each shows its real keyboard shortcut in the icon's place; the run log starts open."""
        bar = self.side_bar
        self.dashboard_button = bar.add_button("Dashboard", "H")
        self.dashboard_button.setToolTip("Dashboard: the open project, its results and recent projects (Ctrl+1)")
        self.reports_button = bar.add_button("Reports", "R")
        self.reports_button.setToolTip("Reports: the PDF reports of this project (Ctrl+7)")
        self.dashboard_button.clicked.connect(self.show_dashboard)
        self.reports_button.clicked.connect(lambda: self.show_reports())
        self.page_buttons[self.dashboard] = self.dashboard_button
        self.page_buttons[self.reports] = self.reports_button
        QShortcut(QKeySequence("Ctrl+Shift+E"), self, activated=self.explain_saved_result)
        self.explain_button.setToolTip(self.explain_button.toolTip() + " (Ctrl+Shift+E)")
        # The index runs in the order of the pages: Alt+1 ... Alt+0 (the Ctrl shortcuts keep working).
        indexed = (self.dashboard_button, self.query_input_button, self.downloads_button, self.catalog_button,
                   self.analysis_button, self.vector_button, self.dem_button, self.idw_button,
                   self.explain_button, self.reports_button)
        for position, button in enumerate(indexed, start=1):
            key = str(position % 10)
            button.set_index(key)
            QShortcut(QKeySequence(f"Alt+{key}"), self, activated=button.click)
            button.setToolTip(f"{button.toolTip()}  (Alt+{key})")
        for button in (self.terminal_button, self.manage_users):
            button.set_index("")  # tools, not pages: aligned with the pages, with no index
        self.prediction_button.set_index("P")   # Alt+1..0 are taken: its own key, Ctrl+Shift+P
        bar.arrange([
            ("division", "work", "Work"), self.dashboard_button, self.query_input_button,
            self.downloads_button, self.catalog_button,
            ("division", "analyse", "Analyse"), self.analysis_button, self.vector_button,
            self.dem_button, self.idw_button, self.prediction_button,
            ("division", "explain", "Explain"), self.explain_button,
            ("division", "report", "Report"), self.reports_button,
            ("division", "tools", "Tools"), self.terminal_button, self.manage_users,
        ])
        self.set_terminal_visible(True)  # the run log is part of the power workspace

    def _fieldbook_pages_host(self) -> QWidget:
        """Layout 3: the pages under a strip of division tabs (Work, Analyse, Explain, Report), the
        current division filled in its hue. A tab opens its division's first page."""
        host = QWidget(objectName="FieldPagesHost")
        strip = QFrame(objectName="DivisionStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(24, 10, 24, 8)
        row.setSpacing(6)
        targets = {"work": self.show_dashboard, "analyse": self.show_analysis,
                   "explain": self.explain_saved_result, "report": lambda: self.show_reports()}
        self.division_tabs: dict[str, QPushButton] = {}
        for key, label in (("work", "Work"), ("analyse", "Analyse"), ("explain", "Explain"), ("report", "Report")):
            tab = QPushButton(label, objectName="DivisionTab")
            tab.setCheckable(True)
            tab.setProperty("division", key)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.clicked.connect(lambda _=False, go=targets[key]: (go(), self._mark_division()))
            row.addWidget(tab)
            self.division_tabs[key] = tab
        row.addStretch(1)
        theming.styled(strip, fieldbook.division_strip_css)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(strip)
        layout.addWidget(self.pages, 1)
        self.pages.currentChanged.connect(self._mark_division)
        self._mark_division()  # the page already shown (no change signal for it)
        return host

    def _mark_division(self, *_args) -> None:
        divisions = {self.dashboard: "work", self.query_input: "work", self.downloads: "work",
                     self.data_catalog: "work", self.analysis: "analyse", self.viewer: "analyse",
                     self.vector_maps: "analyse", self.dem: "analyse", self.idw: "analyse",
                     self.prediction: "analyse",
                     self.analysis_table: "analyse", self.explanation: "explain", self.reports: "report"}
        current = divisions.get(self.pages.currentWidget())
        for key, tab in self.division_tabs.items():
            tab.setChecked(key == current)

    def later(self, msec: int, action) -> None:
        """Run ``action`` after ``msec`` ms, unless the window has been deleted by then (e.g. the user
        signed out): calling into a deleted window from a timer would end the app."""
        QTimer.singleShot(msec, lambda: None if sip.isdeleted(self) else action())

    def check_for_updates(self) -> None:
        run_task(self, self._facade.check_app_version, on_success=self._on_version_checked)

    def _on_version_checked(self, info: AppVersionDTO | None) -> None:
        if info is not None and info.update_available:
            self.menu_bar.set_update_info(info)
        else:
            self.menu_bar.clear_update_info()

    # ------------------------------------------------------------- app settings
    def check_first_run(self) -> None:
        """The Earth Engine project and Gemini key must be entered before the app is used."""
        if settings_needed(self._facade):
            self.exec_settings(first_run=True)

    def open_settings(self) -> None:
        """Options > Settings…: change the Earth Engine project, Gemini key or session length."""
        self.exec_settings(first_run=False)

    def exec_settings(self, first_run: bool) -> bool:
        dialog = SettingsDialog(self._facade, first_run=first_run, parent=self)
        dialog.sign_out_requested.connect(self.sign_out)
        return dialog.exec() == SettingsDialog.DialogCode.Accepted

    # ------------------------------------------------------------- projects
    def refresh_projects(self) -> None:
        """Show the open project, its latest analysis results and the recent projects everywhere they appear."""
        project = current_project(self._facade)
        try:
            recent = [p for p in self._facade.list_projects() if isinstance(p, ProjectDTO)]
            results = list(self._facade.get_analysis_results(project)) if project is not None else []
        except GeeAssistError:
            recent, results = [], []
        self.dashboard.set_projects(project, recent, results)
        self.menu_bar.set_projects(project, recent)
        self.setWindowTitle(f"GEE-Assist — {project.name}" if project is not None else "GEE-Assist")
        form_view = getattr(self.query_input, "form_view", None)
        if form_view is not None and hasattr(form_view, "set_project"):
            form_view.set_project(project)
        if self._project_shown != (project.id if project is not None else None):
            self._project_shown = project.id if project is not None else None
            self.analysis.project_changed()  # only that project's datasets

    def ensure_project(self, why: str = DOWNLOAD_NEEDS_PROJECT) -> bool:
        """True once a project is open; asks the user to create or open one when none is."""
        if current_project(self._facade) is not None:
            return True
        choice = self.ask_for_project(why)
        if choice == "new":
            return self.projects.new_project() is not None
        if choice == "open":
            return self.projects.open_project() is not None
        return False

    def ask_for_project(self, why: str = DOWNLOAD_NEEDS_PROJECT) -> str | None:
        """"new", "open" or None (cancelled): what to do when something needs a project and none is open."""
        box = QMessageBox(QMessageBox.Icon.Information, "A project is needed",
                          f"{why} Create a project, or open an existing one, first.", parent=self)
        create = box.addButton("New project…", QMessageBox.ButtonRole.AcceptRole)
        existing = box.addButton("Open project…", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return {create: "new", existing: "open"}.get(box.clickedButton())

    # ------------------------------------------------------------- navigation
    def show_dashboard(self) -> None:
        reason = self._feedback_reason_for_dashboard()
        self.refresh_projects()  # e.g. results of analyses run since
        self._show_page(self.dashboard)
        if reason:  # once the dashboard is drawn
            self.later(0, lambda: self.ask_for_feedback(reason))

    def _feedback_reason_for_dashboard(self) -> str:
        """Why to ask for feedback on reaching the dashboard ("" = don't): coming from the AI
        explanation page, or an analysis ran since the last visit. One modal per visit."""
        if self.current_page() is self.dashboard:
            return ""
        analysed, self._analysis_since_dashboard = self._analysis_since_dashboard, False
        if self.current_page() is self.explanation:
            return BACK_FROM_EXPLANATION
        return AFTER_ANALYSIS if analysed else ""

    def _on_analysis_finished(self, _result) -> None:
        self._analysis_since_dashboard = True

    def show_query_input(self) -> None:
        # The parameter form is always for the open project, so ask for one first; stay
        # where we are if the user does not create or open a project.
        if not self.ensure_project(QUERY_NEEDS_PROJECT):
            return
        self._show_page(self.query_input)

    def show_downloads(self) -> None:
        self._show_page(self.downloads)

    def show_analysis(self) -> None:
        if self.analysis.isVisibleTo(self.pages) or self.analysis._loaded:
            self.analysis.refresh_datasets()  # a download may have finished since (the first visit loads anyway)
        self._show_page(self.analysis)

    def show_vector_maps(self) -> None:
        """The Vector Maps page: open and explore shapefiles. No project needed (works on any file)."""
        self._show_page(self.vector_maps)

    def show_dem(self) -> None:
        """The Digital Elevation Model page: derive terrain surfaces from a DEM. No project needed."""
        self._show_page(self.dem)

    def show_prediction(self) -> None:
        """The Prediction (ML) page: learn from past and present images and predict. No project needed."""
        self._show_page(self.prediction)

    def show_idw(self) -> None:
        """The IDW Interpolation page: interpolate point data into a surface. No project needed."""
        self._show_page(self.idw)

    def show_data_catalog(self) -> None:
        """The Data Catalog page: download geodata from providers. No project needed."""
        self._show_page(self.data_catalog)

    def open_downloaded_dataset(self, path: str, open_in: str) -> None:
        """Open a dataset downloaded from the Data Catalog in the page it belongs to."""
        if open_in == "dem":
            self.dem.load(path)
            self.show_dem()
        elif open_in == "idw":
            self.idw.load(path)
            self.show_idw()
        else:
            self.vector_maps.load(path)
            self.show_vector_maps()

    def show_reports(self, explanation_path: str = "") -> None:
        """The Reports page; given a saved explanation, its PDF report is created there at once."""
        self._show_page(self.reports)
        if explanation_path:
            self.reports.create_report(explanation_path)

    def explain_saved_result(self) -> None:
        """The side bar's AI Explanation: choose one of the open project's saved results and explain it."""
        if not self.ensure_project(EXPLANATION_NEEDS_PROJECT):
            return
        project = current_project(self._facade)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            results = list(self._facade.list_saved_results())
        except GeeAssistError as exc:
            QMessageBox.warning(self, "AI explanation", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not results:
            if self.offer_analysis(project.name if project else ""):
                self.show_analysis()
            return
        chosen = self.result_chooser(results, project.name if project else "", self)
        if chosen is not None:
            self.show_explanation(chosen)

    def offer_analysis(self, project_name: str) -> bool:
        """No result to explain yet: True if the user wants to go and run an analysis."""
        box = QMessageBox(QMessageBox.Icon.Information, "AI explanation",
                          f"No analysis results are saved in {project_name or 'this project'} yet. Run an "
                          "analysis and press Save result (or Explain with AI) first.", parent=self)
        analyse = box.addButton("Open Analysis", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        return box.clickedButton() is analyse

    def show_explanation(self, result) -> None:
        """The AI explanation page for an analysis result (saved in the project, then sent to Gemini)."""
        self.explanation.explain(result)
        self._show_page(self.explanation)

    def ask_for_feedback(self, reason: str = "") -> str | None:
        """The modal asking to rate the app, send feedback or suggest a feature (one at a time);
        the choice opens that tab of the website's community page."""
        if self._asking_feedback or not self.isVisible():
            return None
        self._asking_feedback = True
        try:
            return self.feedback_prompt(self, reason)
        finally:
            self._asking_feedback = False

    def show_analysis_table(self) -> None:
        """The cheat sheet of indices: only opened from View → Show analysis table."""
        self._show_page(self.analysis_table)

    def start_download(self, form) -> None:
        """Send a kept request to GEE (into the open project) and show its progress on the Downloads page."""
        if not self.ensure_project():
            return
        self.downloads.start(form)
        self.show_downloads()

    def show_account(self) -> None:
        self._show_page(self._account_page)

    def open_geotiff(self) -> None:
        """Choose any GeoTIFF on the computer (starting in the downloads folder) and show it."""
        path, _ = QFileDialog.getOpenFileName(self, "Open GeoTIFF", downloads_folder(self._facade),
                                              "GeoTIFF (*.tif *.tiff);;All files (*)")
        if path:
            self.show_viewer(path)

    def show_on_map(self, png: bytes, bounds: tuple, title: str, extras=None) -> None:
        """Lay a picture (an analysis result, or a GeoTIFF's view) over the world map, full
        screen, with its legend, opacity and the value under the pointer. The page it came
        from stays as it was underneath (it used to switch to the Query Input form's map)."""
        from frontend.views.full_map_window import FullMapWindow  # late: loads the web map

        if self.full_map is not None:
            self.full_map.close()
        window = FullMapWindow(png, bounds, title, extras)
        window.destroyed.connect(self._full_map_closed)
        self.full_map = window
        window.showFullScreen()

    def _full_map_closed(self, *_args) -> None:
        self.full_map = None

    def show_viewer(self, path: str) -> None:
        """Show the GeoTIFF at ``path`` on the Viewer page."""
        self.viewer.open(path)
        self._show_page(self.viewer)

    def sign_out(self) -> None:
        self.signed_out.emit("You have been signed out.")

    def exit_app(self) -> None:
        QApplication.quit()  # the active download is paused first (see app.py)

    def set_full_screen(self, on: bool) -> None:
        if on:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        elif self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.menu_bar.full_screen.setChecked(on)

    def change_theme(self, name: str) -> None:
        """Switch the theme live — no restart. Every styled widget re-themes itself."""
        theming.set_theme(name)   # swaps the palette, rebuilds the stylesheets, re-applies app-wide, saves
        self._refresh_theme_icons()
        self.menu_bar.show_current_theme()

    def _refresh_theme_icons(self) -> None:
        """Swap the per-theme app / taskbar / side-bar logo after a live theme change."""
        icon = QIcon(str(assets.app_icon(palette.THEME)))
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        if hasattr(self.side_bar, "refresh_logo"):
            self.side_bar.refresh_logo()

    def change_layout(self, name: str) -> None:
        """Save the chosen layout and restart, as it is applied while the window is built."""
        answer = QMessageBox.question(
            self, "Change layout",
            f"GEE-Assist restarts to switch to {layout_mode.LAYOUTS[name]}. A running download "
            "is paused and can be resumed afterwards.\n\nRestart now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.menu_bar.show_current_layout()
            return
        layout_mode.save_layout(name)
        restart_app()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About GEE-Assist",
            "<h3>GEE-Assist</h3>"
            "<p>Describe a request in plain language or fill the parameter form, then download "
            "the imagery from Google Earth Engine in chunks, merged into one GeoTIFF.</p>",
        )

    def current_page(self) -> QWidget:
        return self.pages.currentWidget()

    def _show_page(self, page: QWidget) -> None:
        self.pages.setCurrentWidget(page)  # every page's button stays in the side bar ...
        for shown, button in self.page_buttons.items():
            button.set_current(shown is page)  # ... and the one of the page shown is highlighted
        self.terminal.refresh_prompt()  # the prompt shows the page: ~/downloads

    # ------------------------------------------------------------- terminal
    def toggle_terminal(self) -> None:
        self.terminal_area.toggle_terminal()

    def set_terminal_visible(self, shown: bool) -> None:
        if shown:
            self.terminal_area.show_terminal()
        else:
            self.terminal_area.hide_terminal()

    def _terminal_shown(self, shown: bool) -> None:
        self.terminal_button.setChecked(shown)
        self.menu_bar.toggle_terminal.setChecked(shown)
        self.menu_bar.show_terminal.setChecked(shown)

    def run_in_terminal(self, line: str) -> None:
        """Open the terminal and run ``line`` in it, as if it were typed (the Terminal menu's commands)."""
        self.terminal_area.show_terminal()
        self.terminal.run_command(line)

    def open_command_reference(self) -> None:
        """docs/GKONSOL.md in the app that opens .md files; the terminal's own help if that fails."""
        opened = REFERENCE_FILE.is_file() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(REFERENCE_FILE)))
        if not opened:
            self.run_in_terminal("help")

    def _update_terminal_menu(self) -> None:
        """Before the Terminal menu opens: tick Maximise if it is, and offer Stop only while a command runs."""
        self.menu_bar.maximize_terminal.setChecked(self.terminal_area.is_terminal_maximized())
        self.menu_bar.stop_command.setEnabled(self.terminal.shell.running is not None)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        self.terminal.shutdown()  # e.g. an Earth Engine sign-in stops waiting for the browser
        self.analysis.discard_unsaved()  # results are kept only when the user saves them
        super().closeEvent(event)

    # ------------------------------------------------------------- account
    def show_account_menu(self) -> None:
        """The account menu, opening to the right of the user in the side bar."""
        self.account_menu.popup(self.profile.mapToGlobal(QPoint(self.profile.width() + 6, 0)))

    def show_signup_details(self) -> None:
        SignupDetailsDialog(self._user, self).exec()

    def _connect_menu_bar(self) -> None:
        bar = self.menu_bar
        bar.new_project.triggered.connect(self.projects.new_project)
        bar.open_project.triggered.connect(self.projects.open_project)
        bar.recent_project_chosen.connect(self.projects.open_folder)
        bar.rename_project.triggered.connect(self.projects.rename_project)
        bar.move_project.triggered.connect(self.projects.move_project)
        bar.close_project.triggered.connect(self.projects.close_project)
        bar.new_request.triggered.connect(self.show_query_input)
        bar.open_geotiff.triggered.connect(self.open_geotiff)
        bar.sign_out.triggered.connect(self.sign_out)
        bar.exit.triggered.connect(self.exit_app)
        bar.view_dashboard.triggered.connect(self.show_dashboard)
        bar.view_query_input.triggered.connect(self.show_query_input)
        bar.view_downloads.triggered.connect(self.show_downloads)
        bar.view_account.triggered.connect(self.show_account)
        bar.view_analysis.triggered.connect(self.show_analysis)
        bar.view_vector_maps.triggered.connect(self.show_vector_maps)
        bar.view_dem.triggered.connect(self.show_dem)
        bar.view_idw.triggered.connect(self.show_idw)
        bar.view_prediction.triggered.connect(self.show_prediction)
        bar.view_data_catalog.triggered.connect(self.show_data_catalog)
        bar.view_reports.triggered.connect(lambda: self.show_reports())
        bar.view_analysis_table.triggered.connect(self.show_analysis_table)
        bar.toggle_side_bar.setChecked(self.side_bar.is_pinned())  # "Side bar": keep it open
        bar.toggle_side_bar.triggered.connect(self.side_bar.set_pinned)
        bar.toggle_terminal.triggered.connect(self.set_terminal_visible)
        self.side_bar.pinned_changed.connect(bar.toggle_side_bar.setChecked)  # also from gkonsol
        bar.terminal_menu.aboutToShow.connect(self._update_terminal_menu)
        bar.show_terminal.triggered.connect(self.set_terminal_visible)
        bar.maximize_terminal.triggered.connect(self.terminal_area.set_terminal_maximized)
        bar.clear_terminal.triggered.connect(self.terminal.shell.clear)
        bar.stop_command.triggered.connect(self.terminal.stop_command)
        bar.terminal_command.connect(self.run_in_terminal)
        bar.command_reference.triggered.connect(self.open_command_reference)
        bar.full_screen.triggered.connect(self.set_full_screen)
        bar.chunk_size.triggered.connect(self.downloads.change_chunk_size)
        bar.app_settings.triggered.connect(self.open_settings)
        bar.manage_users.triggered.connect(self.open_user_admin)
        bar.about.triggered.connect(self.show_about)
        bar.give_feedback.triggered.connect(lambda: self.ask_for_feedback())
        bar.theme_chosen.connect(self.change_theme)
        bar.layout_chosen.connect(self.change_layout)

    def open_user_admin(self) -> None:
        if self._admin_dialog is None:
            self._admin_dialog = UserAdminDialog(self._facade, self)
            self._admin_dialog.session_expired.connect(
                lambda: self.signed_out.emit("Your session has expired. Please sign in again.")
            )
        else:
            self._admin_dialog.reload()
        self._admin_dialog.show()
        self._admin_dialog.raise_()
        self._admin_dialog.activateWindow()

    def manage_account(self) -> None:
        """The account page: click a detail to change it, the photo to change or remove it."""
        self.show_account()

    def set_user(self, user: UserDTO) -> None:
        self._user = user
        self.profile.set_user(user, self._facade.get_profile_photo(user.id))
        self.manage_users.setVisible(user.is_admin)
        self.menu_bar.manage_users.setVisible(user.is_admin)
        self.account.set_user(user)
        self.dashboard.set_user(user)
