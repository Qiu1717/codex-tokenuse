# Third-party notices

Codex TokenUse is an independent MIT-licensed application. It does not bundle OpenAI Codex, desktop pet artwork, account credentials or session logs.

The Windows distribution includes:

- **ccusage 20.0.32** — MIT License. Copyright and full license are in `licenses/ccusage-LICENSE.txt`. Source: https://github.com/ccusage/ccusage . The native Windows x64 program is obtained from the integrity-pinned npm package `@ccusage/ccusage-win32-x64` through `package-lock.json`.
- **CPython and its standard library** — Python Software Foundation license and included notices, copied from the build runtime into `licenses/Python-LICENSE.txt`. Source: https://www.python.org/ .
- **Tcl/Tk** — respective Tcl/Tk license terms, copied from the Python runtime to `licenses`.
- **PyInstaller bootloader** — GPL with the PyInstaller bootloader exception permitting distribution of bundled applications under their own license. The build copies the installed PyInstaller copyright, exception and license files to `licenses`. Source: https://pyinstaller.org/ .

Windows' system curl is used for authenticated HTTPS requests and is not bundled. Node.js and npm are build-time tools only and are not distributed. GitHub Actions and pytest are development/test tools and are not included in the executable.
