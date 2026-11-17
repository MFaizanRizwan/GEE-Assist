# GEE-Assist

Desktop app (PyQt6) for querying and analysing Google Earth Engine data.

## Running the app

1. Start the authentication server ([GEE-Assist-Backend](https://github.com/Abdullah2265Habib/GEE-Assist-Backend)),
   by default on `http://localhost:8000`:

   ```bash
   cd GEE-Assist-Backend
   .venv\Scripts\activate
   uvicorn app.main:app
   ```

2. Install and run the desktop app:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env      # optional: AUTH_API_URL if the server is not on localhost:8000
   python main.py
   ```

Run the tests with `python -m pytest`.

## Start-up and sign-in

### Your own Earth Engine project and Gemini key

Every user enters their own **Earth Engine project ID** and **Gemini API key**. A new copy of the
app asks for both at the first sign-in (the **Set up GEE-Assist** window cannot be skipped, only
signed out of) and shows the steps to get them:

- **Earth Engine project ID**: create a project in the
  [Google Cloud console](https://console.cloud.google.com/projectcreate) and note its *Project ID*;
  register it at <https://code.earthengine.google.com/register> (unpaid usage); enable the
  [Earth Engine API](https://console.cloud.google.com/apis/library/earthengine.googleapis.com);
  enter the ID, then sign this computer in once with **Terminal → Sign in to Earth Engine…**.
- **Gemini API key**: in [Google AI Studio](https://aistudio.google.com/apikey) press **Create API
  key** and paste it.

Change them, and how long **Keep me signed in** lasts, any time in **Options → Settings…**
(Ctrl+,); changes are used at once, without restarting. The key is kept in Windows Credential
Manager (never in a file); the project ID and session length in `workspace/app_settings.json`.
While developing, `GEE_PROJECT`, `GEMINI_API_KEY` and `SESSION_DURATION` in `.env` are used for
whatever was never entered in the app.


- On the very first start-up the app asks for a theme: **Light** (the default), **Dark – blue-green**
  or **Dark – grey**. Change it later in **View → Theme**; the app restarts to apply it. The choice
  is kept in `workspace/appearance.json`. Each theme has its own project icon (window, taskbar and
  side bar logo) in `assets/project_icon/`.
- The intro video (`assets/starting_video/start.mp4`) plays centred on a white screen, then fades out.
  Click or press Esc / Space / Enter to skip it.
- The sign-in screen offers username/password sign-in, sign-up and Google sign-in.
- New accounts must verify their email. The app waits on a "Check your email" screen (resend,
  change email) and signs the user in as soon as the link is opened.
- **Keep me signed in** (ticked by default) stores the refresh token in the Windows Credential
  Manager (via `keyring`), so the next launch goes straight to the dashboard. The saved session
  lasts as long as chosen in **Options → Settings…** (7 days unless changed), counted from signing in; after that
  the app asks to sign in again.
- After signing in the app opens on the **dashboard**. Its **Query Input** card opens the parameter
  form (with the "Chat with Gemini" assistant); the back arrow (**←**) at the top of the side bar
  returns to it. On the dashboard itself there is no back arrow and the logo is at the top.
- A menu bar runs along the top of every page, as in Word or Excel:
  - **File**: New project… (Ctrl+Shift+N), Open project… (Ctrl+Shift+O), Recent projects, Rename
    project…, Move project…, Close project, New request (Ctrl+N), Open GeoTIFF… (Ctrl+O), Sign out,
    Exit (Ctrl+Q)
  - **Edit**: Undo, Redo, Cut, Copy, Paste, Select all, acting on the text field with the cursor
  - **View**: Dashboard, Query Input, Downloads, Account, Analysis (Ctrl+1 to Ctrl+5), Reports (Ctrl+7),
    Show analysis table (Ctrl+6), Side bar (Ctrl+B), Terminal (Ctrl+`), Full screen (F11), Theme
  - **Terminal** (gkonsol's, as in VS Code): Show terminal (Ctrl+`), Maximise terminal, Clear terminal,
    Stop running command; Check everything, Verify Earth Engine sign-in, Sign in to Earth Engine…,
    Verify my session, Watch download progress, Download speed chart, List downloads and gkonsol help,
    which run that command in the terminal; Command reference (opens docs/GKONSOL.md)
  - **Options**: Download chunk size…, Manage users… (administrators)
  - **Help**: Rate, feedback or suggestion…, About GEE-Assist
- Navigation is in a side bar on the left: **Query Input**, **Downloads**, **Analysis** and
  **Terminal**, each with an icon that animates while the pointer is over it (a pencil writing on a
  sheet; an arrow sliding down into a tray; chart bars rising in a wave under a sweeping magnifying
  lens; a prompt typing). It starts collapsed (icons only); clicking the logo slides it
  open (icons and names) or closed again. **Terminal** opens gkonsol (see below) and stays
  highlighted while it is open.
- Clicking your name or avatar in the side bar opens the account menu: **Manage account**
  (the account page), **Sign-up details** and **Sign out**.
- The **account page** shows your details on the left and your photo on the right. Click your
  name (or username, phone) to change it; once something really changed, **Discard** and **Save
  changes** appear at the bottom right (Esc gives up a change). Click the photo to **change** or
  **remove** it. Accounts that sign in with a password also get a **Change password** section:
  the current password, then the new one twice; it is changed when you save. Only an
  administrator can change your email address, role or status.
- **Profile photos stay on this computer**: they are saved in `workspace/profile_photos/` (one file
  per user id) and never sent to the server, so they do not follow you to another computer.
- Administrators get a **Manage users** window: list users page by page, find anyone by email (type
  it in the search box and press Enter), **add a user**, edit a user's details including their email
  (a new address must be verified again), change roles, reset passwords, enable / disable and
  **delete** accounts. Your own account is changed from the account page instead.

## Projects

As in other desktop apps, you work inside a project. A project is a folder:

```
<location>/<project name>/
    project.json                 the project's id, name and creation time
    downloads/                   every dataset downloaded while the project is open
    analysis/                    analysis results you save
        analysis_results.json    every analysis run in the project: settings, numbers, saved file
    explanation/                 AI explanations of analysis results (Markdown)
    reports/                     PDF reports made from the AI explanations
```

- **Create** one from the dashboard (**New project**) or **File → New project…**: give it a name and
  the folder to create it in (by default next to your last project, else
  `Documents/GEE-Assist Projects`). The dialog shows the folder that will be made. Leave the name
  empty to get **Project 1**, then **Project 2**, **Project 3**, ... (the first number not already a
  folder in that location).
- **Open** one with **Open project…** (choose its folder), a card under **Recent projects** on the
  dashboard, or **File → Recent projects**.
- **Rename** or **Move** the open project from the dashboard card or the File menu: its folder is
  renamed or moved, with everything in it. Saved downloads, even paused ones, follow it; this is
  refused while one of its downloads is running (pause it first).
- **Close** the open project from the dashboard card or the File menu; signing out closes it too.
- A **download needs an open project**: the form's "Save to folder" always shows the project's
  `downloads` folder (use **Save to…** on the Downloads page to copy a dataset elsewhere). The
  parameter form only says what to download; analyses are chosen and run on the Analysis page. Starting a download without a project asks you to create or open one first.
- **Analyses run inside the open project**: each run is recorded in `analysis_results.json` (what
  ran, when, its numbers, and the GeoTIFF if you saved it; paths inside the project are stored
  relative to it, so moving the project keeps them valid). **Save result** puts the GeoTIFF in the
  project's `analysis` folder.
- The **dashboard** shows the open project, the **last 3 projects** (name and the folder they are
  in; click one to open it) and the **latest analysis results of those 3 projects**.
- Where your projects are is remembered on this computer in `workspace/projects.json` (per user).
  Forgetting a project there never deletes its folder.

## Analysis

- **Analysis** (side bar, the dashboard's Analysis card, or View → Analysis): choose a dataset (a
  finished download, or any GeoTIFF with **Open GeoTIFF…**), one of the four analyses, its processes
  and their parameters, then **Run analysis**.
- The four analyses (SRS FR-06 to FR-09) and their sub-types:
  - **Water**: water indices, water quality, water bodies & area, snow & ice
  - **Vegetation**: vegetation indices, moisture & drought, burn & fire
  - **Land Surface Temperature**: surface temperature, temperature change, heat stress
  - **Land Use / Land Cover**: land cover change, built-up & urban, soil & salinity,
    transformations (Tasseled Cap, PCA), radar (SAR)
- Processes are cards, grouped by sub-type (chips narrow them to one sub-type). Click a card (or press
  Space) to select it. Processes the dataset **can run** come first; those it **can't run** are in a
  separate section below, folded away, each showing why (e.g. "Needs the red-edge 1 band"). An
  analysis the dataset cannot run at all is greyed out.
- Before / after processes (dNBR, RdNBR, RBR, land-cover change, LST change) need a dataset of the
  same place from another date, ticked under **Compare with**.
- Results are **not saved** unless you ask: they are shown (each layer with its legend, and the
  numbers) from a temporary file. **Save result** saves the GeoTIFF (one band per layer) in the open
  project's `analysis` folder, without asking, and writes its numbers and settings next to it as
  `.json`; an earlier result with the same name is kept (the new one gets `_2`, `_3`, ...).
  The file is named `<dataset>_<analysis>_<processes>_<date-time>.tif`, e.g.
  `Sentinel-2_73.0708_31.4357_2026-08-14_2026-11-14_Vegetation_NDVI_EVI_2026-11-14_23-02-58.tif`. With
  many processes the name keeps the first few and says how many more (`..._GCI_and_26_more_...`);
  the `.json` lists them all. An unsaved result is deleted when the next
  one replaces it or the app closes. A result can also be opened in the viewer or laid over the map.
- Raw download values are scaled to reflectance / kelvin per satellite before any index is computed.
- **GPU**: the app lists the computer's graphics cards. With a dedicated NVIDIA GPU and CuPy installed
  (`pip install cupy-cuda12x`), analyses run on the GPU; otherwise, or if the GPU runs out of memory,
  on the CPU. The line above **Run analysis** says which, and why. Files are processed in blocks of
  rows, so large downloads do not need to fit in memory.
- **View → Show analysis table** (only there) opens the cheat sheet: every index with its formula,
  bands, value range, how to read it and its use cases, grouped the same way (e.g. "Vegetation ›
  Burn & fire"), with chips for the four analyses and a search box. Rows marked "Reference" (SPI,
  PDSI, NDBaI, coherence) are described but not computed.

## AI explanation

- **Explain with AI** under an analysis result opens the **AI explanation** page. A project must be
  open: if the result is not saved yet, its GeoTIFF is saved in the project's `analysis` folder
  first (as **Save result** does), so the file sent to Gemini is always the one kept in the project.
- On the left the page shows what Gemini is sent:
  - **Analysis**: which analysis and processes ran (with their formulas), the parameters, where it
    ran and how long it took;
  - **Before the analysis**: the metadata of the dataset analysed, and of any earlier dataset it was
    compared with: satellite, dates, bands, size in pixels, pixel size, coordinate system, bounds,
    centre, area, data type, no-data value, file size;
  - **After the analysis**: the same metadata of the result GeoTIFF, its layers (with how each
    preview is coloured) and its numbers.
- Gemini is sent the result **GeoTIFF** (through the Gemini Files API, deleted again afterwards), a
  **PNG preview** of each layer and a prompt with all of the above. Gemini does not read every file
  type: if it refuses the GeoTIFF, the request is sent again with the previews and metadata only, and
  the page says so.
- The explanation (Markdown) appears on the right, with **Explain again**, **Copy** and **Open
  folder**. It is kept in the project as `explanation/<result>_explanation.md` (explaining the same
  result again keeps the earlier file: `_2`, `_3`, ...), together with the metadata it was made from.

### Feedback

After every AI explanation, whenever you go from the AI explanation page to the dashboard, and
whenever you come back to the dashboard after running an analysis, a window asks you to **Rate the app**, **Send feedback** or **Suggest a feature** (or **Not now**).
Your choice opens that tab of the website's community page in the browser:
`http://localhost:5173/community?tab=rate`, `?tab=feedback` or `?tab=suggest`. **Help → Rate,
feedback or suggestion…** opens the same window at any time. The website's address is
`WEB_APP_URL` in `.env` (default `http://localhost:5173`, where
[GEE-Assist-Web](https://github.com/Abdullah2265Habib/GEE-Assist-Web) runs with `npm run dev`).

## PDF reports

- The **Reports** page (the dashboard's **Reports** card, **View → Reports** or Ctrl+7) lists the AI
  explanations saved in the open project, newest first, and whether each already has a PDF.
- **Create PDF report** makes the chosen explanation's report: first a picture of each layer of the
  analysis result it explains (the `.tif` in the project's `analysis` folder, coloured as on the
  Analysis page, each with its colour bar and range, or its classes), then the explanation exactly
  as saved, with its headings, lists and tables. It is an A4 PDF kept in the project as
  `reports/<explanation>.pdf`; creating it again replaces it. If the result `.tif` is no longer
  there, the report says so and has the explanation only.
- **PDF report** on the AI explanation page goes to the Reports page and creates that explanation's
  report at once.
- **Export PDF…** saves a copy anywhere on the computer (Documents, a USB drive, ...); the project keeps
  its own copy. **Open PDF** opens it in the computer's PDF viewer, **Open reports folder** shows the
  folder.

## gkonsol, the command line

gkonsol is a terminal inside GEE-Assist, below the pages as in VS Code. Open it with the side
bar's **Terminal** button, the **Terminal** menu, **View → Terminal** or **Ctrl+`**; drag the line
above it to make it taller or shorter, or maximise it from its header. Everything the window does
can be done with a command, for example:

```
gee verify                                   check the Earth Engine sign-in step by step
gee login                                    sign in to Earth Engine in the browser
whoami / user info / session verify          your account and session
form set dataset landsat-8                   fill the parameter form (or: form wizard, ask ...)
form aoi bbox 74.20 31.40 74.45 31.60
form submit
download start                               download with a live progress bar, speed and ETA
download speed                               the live download speed as a chart
doctor                                       check everything at once
```

Type `help` for every command and `help <command>` for one. Its commands work only inside
GEE-Assist: they are not Windows, PowerShell or cmd commands. Every command is described in
[docs/GKONSOL.md](docs/GKONSOL.md).

## Downloading datasets (Google Earth Engine)

One-time setup:

1. Register a Google Cloud project for Earth Engine at <https://code.earthengine.google.com/register>.
2. Enter its Project ID in **Options → Settings…** (asked for at the first sign-in).
3. Sign in once on this computer: type `gee login` in gkonsol, or run `earthengine authenticate`
   in a command prompt (with the venv active). `gee verify` checks the whole set-up.

Then create or open a project, fill the parameter form (or let Gemini fill it), press **Submit
Parameters**, and press **Start Download** under Kept Requests. The dataset is saved in the project's
`downloads` folder. The **Downloads** page (dashboard card or side bar)
shows progress, speed and ETA, with Start / Pause / Cancel for every download.

How it works:

- The request is split into **chunks of 500 MB** (`workspace/download_settings.json`, or
  **Change…** on the Downloads page; applies to new downloads). A 2 GB dataset is 4 chunks.
- Each chunk is fetched from GEE as small requests (about 4 MB, 8 at a time), far under GEE's
  48 MB limit: GEE computes small requests sooner, so data arrives early and steadily. Responses
  are read as they stream in and each piece is written to disk as soon as it arrives, so the
  speed graph, progress bar, DOWNLOADED, REMAINING and DISK USAGE update live. No data arrives
  while GEE is still computing, so the speed is 0 then, as in Task Manager.
- If GEE runs out of memory on a request (e.g. a median over many years), that request is
  fetched as four smaller ones, split again if needed, and the rest of the download starts at
  that size. If even small requests fail, the download stops with a message: shorten the date
  range or use the mosaic composite, then press **Retry**.
- Chunks are merged as soon as two exist: 1 + 2 -> 1 GB, + 3 -> 1.5 GB, + 4 -> the full file.
- The result is `<project>/downloads/<name>/<name>.tif`, where `<name>` is
  `<satellite>_<lon>_<lat>_<start date>_<end date>`: the centre of the AOI and the request's dates, e.g.
  `Sentinel-2_73.8231_33.2334_2023-01-01_2023-12-31/Sentinel-2_73.8231_33.2334_2023-01-01_2023-12-31.tif`.
  The same request downloaded again gets `_2`, `_3`, ... at the end.
- **Save to…** on a finished download copies its GeoTIFF into any folder you choose (a USB drive, a
  shared folder, ...). The project keeps its own copy, so the Analysis page still finds it; an
  existing file there is never overwritten (the copy gets `_2`, `_3`, ...).
- Pause keeps finished parts; Start continues where it stopped, even after closing the app.
  Cancel deletes the files. Failed chunks are retried 3 times, then **Retry** re-runs only them.

## Viewing a downloaded GeoTIFF

Press **View** on a finished download (or **File → Open GeoTIFF…** for any `.tif`) to open the
viewer:

- **Views**, depending on the file's bands: true colour, false colour (vegetation shows red), NDVI
  (vegetation), NDWI (water), Dynamic World land-cover classes in their official colours, and each
  band on its own on a colour scale. Composites and single bands are stretched between their 2nd and
  98th percentiles; NDVI (-0.2 to 0.8) and NDWI (-0.5 to 0.5) use fixed ranges, so a colour means
  the same in every file. No-data pixels are transparent.
- **Legend** for the view: a colour bar with its range, the classes present, or which band is shown
  as red, green and blue.
- **Under the pointer**: latitude/longitude, every band's value (read from the full-resolution file)
  and the index or land-cover class there.
- **Details**: size, bands, coordinate system, area, file size and path.
- Mouse wheel zooms, dragging pans, double-click fits the picture again. Large files are drawn at
  most 1600 px across (the banner says by how much).
- **Show on map** lays the current view over the Query Input map, with an opacity slider and a
  "Remove from map" button on the map.
- **Analysis results** (a saved result's `.tif`) get an **Analysis colours** switch under the view.
  On (the default): each layer in exactly the colours and range of the Analysis page (e.g. NDVI from
  red to green over -0.2 to 0.8), read from the `.json` saved next to the result. Off: each band on
  the general colour scale, stretched to its own values (useful to see small differences).

### Where the code is

| Layer | Files |
|---|---|
| HTTP client for the auth server | `backend/data/clients/auth_api_client.py` |
| Saved session (credential store) | `backend/data/session_store.py` |
| Sign-in tokens shared by the service and DAO | `backend/data/auth_session.py` |
| Accounts (server) and profile photos (local) | `backend/data/dao/user_dao.py`, reached through `backend/data/data_facade.py` |
| Business logic (tokens, refresh, flows, managing accounts) | `backend/business/user/user_service.py` |
| Account page and its dialogs | `frontend/views/account_view.py`, `frontend/views/account_dialogs.py` |
| Projects: folders, history and analysis results (JSON) | `backend/data/dao/project_dao.py`, `backend/dto/project_dto.py` |
| Projects: create, open, rename, move | `backend/business/request/request_service.py`, `backend/business/request/project_rules.py` |
| Project dialogs and dashboard | `frontend/views/project_dialogs.py`, `frontend/views/dashboard_view.py` |
| Sign-up rules checked in the app | `backend/business/user/signup_validation.py` |
| UI entry point (`IBusinessFacade`) | `backend/business/facade/` |
| Intro video | `frontend/views/splash_view.py`, `frontend/views/startup_window.py` |
| Sign-in / sign-up screens | `frontend/views/auth/` |
| Theme (colours, fonts, styles) | `frontend/theme.py` |
| Admin user management | `frontend/views/user_admin_view.py` |
| Dashboard and signed-in window | `frontend/views/dashboard_view.py`, `frontend/views/home_window.py` |
| Side bar | `frontend/widgets/side_bar.py`, `frontend/widgets/side_icons.py` |
| Menu bar | `frontend/widgets/menu_bar.py` |
| Themes (colours, saved choice, first-run dialog) | `frontend/palette.py`, `frontend/appearance.py`, `frontend/views/theme_choice_dialog.py` |
| Query input (parameter form, Gemini assistant) | `frontend/views/main_window.py`, `frontend/views/parameter_form_view.py` |
| Download (chunking, merging, queue) | `backend/business/download/` |
| Earth Engine client | `backend/data/clients/gee_client.py`, `gee_tiles.py` |
| Downloads page | `frontend/views/download_view.py`, `frontend/widgets/download_rows.py`, `speed_chart.py` |
| GeoTIFF viewer (views, colours, legend, values) | `backend/business/map/`, `frontend/views/raster_viewer_view.py`, `frontend/widgets/raster_canvas.py`, `raster_legend.py` |
| AI explanation (metadata, previews, Gemini, saving) | `backend/business/explanation/`, `backend/data/clients/gemini_client.py`, `prompts.py`, `frontend/views/explanation_view.py` |
| Feedback window (website community tabs) | `frontend/views/feedback_dialog.py` |
| PDF reports (content, saving, export; drawing; page) | `backend/business/report/`, `frontend/report_pdf.py`, `frontend/views/reports_view.py` |
| gkonsol terminal (shell, commands, panel) | `frontend/gkonsol/` (see [docs/GKONSOL.md](docs/GKONSOL.md#9-for-developers)) |
| Earth Engine set-up checks and browser sign-in | `backend/data/clients/gee_client.py`, `gee_sign_in.py` |
