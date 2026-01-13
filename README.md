# Solo Public Lobby V - Online (SPL_GTAVO)

A single-file-ready Windows GUI to manage a Windows Firewall rule for GTA Online and provide global hotkeys.  
Designed to be packaged with PyInstaller as a single EXE. Includes embedded helper scripts (PowerShell / BAT) to perform suspend/resume and rule toggling tasks.

Key goals
- Simple GUI to create / toggle / delete a named firewall rule that blocks GTA Online UDP ports.
- Global hotkeys (RegisterHotKey) handled in a dedicated native-thread so the GUI remains responsive.
- Hotkey recorder dialog with one-shot recording and soft-blocking while recording.
- Single-file packaging support (PyInstaller --onefile) with embedded helper scripts and icons.
- Robust logging and thread exception tracing for easier troubleshooting.

Contents
- `create_rule_admin_gui_simple.py` — main application script (single-file ready).
- `GTAO.ico`, `GTAO_active.ico` — inactive/active icons used by the window and taskbar (include next to the script before building).
- `build_onefile.bat` — helper script to build the onefile EXE with PyInstaller (optional).
- Embedded helper scripts (written to %TEMP%/SPL_GTAVO at runtime if needed):
  - suspend_resume_generic.ps1, suspend_resume_GTA5.ps1, suspend_resume_GTA5_Enhanced.ps1
  - suspend_resume_GTA5.bat, suspend_resume_GTA5_Enhanced.bat
  - toggle_rule.ps1, toggle_rule.bat

Features
- Create / Enable / Disable / Delete a Windows Firewall rule named "GTA Online Rule".
- Global hotkeys for common actions (configurable via GUI); hotkeys run in a separate native thread.
- Hotkey recorder dialog that records combos (one-shot), validates entries, and persists them to `hotkeys.json`.
- Set and swap window/taskbar icons (inactive/active) using Win32 calls; sets AppUserModelID for proper taskbar grouping.
- Diagnostic logs: `debug_log.txt`, `crash_log.txt` (written to exe_dir()).

Requirements
- Windows 10/11 (32-bit or 64-bit)
- Python 3.8+ for development (if running the script directly)
- PyInstaller (for building the single-file EXE)

Quick start (development)
1. Clone the repo and open a cmd/PowerShell in the project root.
2. Create a virtual environment (recommended):
   - python -m venv venv
   - venv\Scripts\activate.bat
3. Install dependencies:
   - pip install pyinstaller
4. Run the script (requires administrator privileges for firewall commands):
   - python create_rule_admin_gui_simple.py

Building the single-file EXE (recommended)
The build script bundles the EXE icon and also includes the active icon as runtime data so the onefile can locate it.

From project root:

- Using the included build script:
  - Double-click `build_onefile.bat` or run it from a terminal.
- Or call PyInstaller manually:
  - py -3 -m PyInstaller --onefile --name "Solo_Public_Lobby_V-Online" --uac-admin --windowed --icon=GTAO.ico --add-data "GTAO_active.ico;." create_rule_admin_gui_simple.py

Notes:
- `--icon=GTAO.ico` sets the EXE file icon (Explorer / shortcuts).
- `--add-data "GTAO_active.ico;."` bundles `GTAO_active.ico` into the onefile so the runtime can extract and use it via `sys._MEIPASS`.
- After building, the EXE will be in `dist\Solo_Public_Lobby_V-Online.exe`.

Icon behavior & troubleshooting
- The app uses both:
  - the EXE's embedded icon (via PyInstaller `--icon`) for Explorer/shortcuts, and
  - runtime calls (LoadImage + WM_SETICON) to set the window titlebar / taskbar thumbnail icon from `GTAO.ico` / `GTAO_active.ico`.
- For onefile builds, the code looks for resources in `sys._MEIPASS` so `--add-data` is required to bundle runtime icons.
- If Explorer or the taskbar shows an old icon after you replace the EXE:
  - Restart Explorer (Task Manager → Windows Explorer → Restart) or log off / reboot.
  - Optionally clear the icon cache:
    - Stop Explorer, remove `%LocalAppData%\Microsoft\Windows\Explorer\iconcache*`, restart Explorer.

Where the app stores files & logs
- The helper function exe_dir() chooses a sensible directory:
  - When running normally: directory next to the script.
  - When running a onefile EXE and PyInstaller extracted: uses `%TEMP%` extraction (sys._MEIPASS); embedded helpers are handled too.
  - If needed, falls back to `%APPDATA%\SPL_GTAVO` for onefile runtime extracted instances.
- Logs:
  - debug_log.txt — trace messages and unhandled exceptions
  - crash_log.txt — tracebacks recorded when explicit exceptions occur while handling hotkeys
  - These files are created in `exe_dir()`.

Hotkeys
- Default hotkeys (configurable from GUI):
  - Create: Ctrl+Alt+C
  - Toggle: Ctrl+Alt+T
  - Delete: Ctrl+Alt+D
  - Suspend Enhanced: Ctrl+Alt+E
- Hotkeys are registered in a dedicated native thread to make PostThreadMessage / RegisterHotKey reliable on Windows.
- Use the Hotkeys dialog to rebind; the dialog supports a one-shot recorder and saves to `hotkeys.json`.

Troubleshooting & diagnostics (quick)
- If hotkeys don't work:
  - Ensure the app runs elevated (Administrator).
  - Check `debug_log.txt` for hotkey-thread messages.
- If icons are missing in the running EXE:
  - Verify `GTAO.ico` and `GTAO_active.ico` were included at build time (`--icon` and `--add-data`).
  - Verify resource_path includes `sys._MEIPASS` (onefile).
- If firewall commands fail:
  - Confirm the app is elevated and Windows power policies allow modification.
  - Check the output of `netsh` in error dialogs and in `debug_log.txt`.

Automatic updates (notes)
- The project currently uses manual releases (GitHub Releases recommended).
- If you want auto-update in future: consider `pyupdater`, `Squirrel.Windows`, or a small updater helper that runs with elevation to replace the EXE.

Contributing
- Use Issues for bugs and feature requests (include OS details, whether onefile EXE or onedir run, logs and screenshots).
- Suggested workflow:
  - Fork → feature/fix branch → Pull Request into main
  - Keep changes small and include a changelog entry.
- If you'd like, add a GitHub Actions workflow to build releases automatically — a template can be provided.

CI / Releases
- Recommended: GitHub Actions workflow that builds the onefile EXE on `windows-latest` and uploads the artifact for manual release or automatically publishes on tags.
- The provided `build_onefile.bat` is useful locally; CI should run PyInstaller similarly.

Security / signing
- For distribution to end-users, sign the EXE to avoid SmartScreen warnings (purchase a code-signing certificate and sign with Microsoft signtool).

License
- Include a LICENSE file in the repo. (Recommend MIT if you want permissive use. Replace with your preferred license.)

Useful files
- create_rule_admin_gui_simple.py — main app
- build_onefile.bat — build helper
- GTAO.ico, GTAO_active.ico — icons (place next to the script before building)

Contact / Support
- For bug reports / feature requests: open an Issue with the following:
  - App version (add a VERSION constant if helpful)
  - Windows version (10/11 + build)
  - 32/64-bit
  - Onefile EXE or folder build
  - Steps to reproduce, expected vs actual
  - Attach `debug_log.txt` and `crash_log.txt` if present

Changelog
- Keep a `CHANGELOG.md` and follow semantic versioning (MAJOR.MINOR.PATCH).

---
