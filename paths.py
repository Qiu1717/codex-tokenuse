"""Current-user data paths and bundled resource lookup."""
import os
from pathlib import Path
import sys


RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def codex_home(environ=None, home=None):
    environ = os.environ if environ is None else environ
    custom = environ.get('CODEX_HOME', '').strip()
    return Path(os.path.expandvars(custom)).expanduser() if custom else (home or Path.home()) / '.codex'


def data_directory(environ=None):
    environ = os.environ if environ is None else environ
    custom = environ.get('CODEX_TOKENUSE_DATA_DIR')
    if custom:
        return Path(custom).expanduser()
    return Path(environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'codex-tokenuse'


def usage_command(resource_root=None):
    root = resource_root or RESOURCE_ROOT
    for binary in (root / 'runtime' / 'ccusage.exe', root / 'node_modules' / '@ccusage' / 'ccusage-win32-x64' / 'bin' / 'ccusage.exe'):
        if binary.is_file():
            return [str(binary)]
    raise RuntimeError('缺少 ccusage.exe；请完整解压下载包，源码运行请先执行 npm ci --ignore-scripts。')
