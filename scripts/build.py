"""Build a Windows x64 portable folder, test it without Node, then zip it."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'


def run(command, **kwargs):
    subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def main():
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise SystemExit('Build on Windows x64 with an x64 Python runtime.')
    run([sys.executable, '-m', 'pytest', '-q'])
    npm = shutil.which('npm.cmd')
    if not npm:
        raise SystemExit('npm is required on the build machine; end users do not need it.')
    run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'])
    binary = ROOT / 'node_modules/@ccusage/ccusage-win32-x64/bin/ccusage.exe'
    if not binary.is_file():
        raise SystemExit('Missing pinned ccusage Windows x64 runtime.')
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
         '--noupx', '--icon', 'NONE', '--name', 'CodexTokenUse', '--distpath', 'dist',
         '--workpath', 'build/pyinstaller', '--specpath', 'build',
         '--add-binary', str(binary) + os.pathsep + 'runtime', 'app.py'])
    bundle = ROOT / 'dist/CodexTokenUse'
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md'):
        shutil.copy2(ROOT / name, bundle / name)
    licenses = bundle / 'licenses'
    licenses.mkdir(exist_ok=True)
    for source in (ROOT / 'licenses').glob('*.txt'):
        shutil.copy2(source, licenses / source.name)
    shutil.copy2(ROOT / 'node_modules/ccusage/LICENSE', licenses / 'ccusage-LICENSE.txt')
    python_root = Path(sys.base_prefix)
    shutil.copy2(python_root / 'LICENSE.txt', licenses / 'Python-LICENSE.txt')
    for component in ('tcl8.6', 'tk8.6'):
        source = python_root / 'tcl' / component / 'license.terms'
        if source.exists():
            shutil.copy2(source, licenses / (component + '-LICENSE.txt'))
    distribution = importlib.metadata.distribution('pyinstaller')
    for item in distribution.files or []:
        if item.name in ('COPYING.txt', 'COPYING', 'COPYRIGHT.txt'):
            source = Path(distribution.locate_file(item))
            if source.is_file():
                shutil.copy2(source, licenses / ('PyInstaller-' + item.name))
    previews = bundle / 'docs'
    previews.mkdir(exist_ok=True)
    for image in (ROOT / 'docs').glob('*.png'):
        shutil.copy2(image, previews / image.name)
    with tempfile.TemporaryDirectory(prefix='codex-tokenuse-smoke-') as temporary:
        env = os.environ.copy()
        env['CODEX_TOKENUSE_DATA_DIR'] = temporary
        env['CODEX_HOME'] = str(Path(temporary) / 'empty-codex-home')
        env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
        result = subprocess.run([str(bundle / 'CodexTokenUse.exe'), '--self-test'], env=env,
                                cwd=temporary, timeout=30)
        if result.returncode:
            raise SystemExit('Packaged self-test failed.')
        report = json.loads((Path(temporary) / 'self-test.json').read_text())
        if not report.get('ok'):
            raise SystemExit('Packaged self-test did not produce a passing report.')
        print('Packaged self-test (no Python/Node on PATH):', report)
    archive = ROOT / 'dist' / f'codex-tokenuse-v{VERSION}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for file in sorted(bundle.rglob('*')):
            if file.is_file():
                relative = file.relative_to(bundle)
                if file.name in ('auth.json', 'app.log', 'ui-prefs.json') or file.name.endswith('-cache.json'):
                    raise SystemExit(f'Private runtime data in bundle: {relative}')
                output.write(file, Path('CodexTokenUse') / relative)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.parent / 'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Ready: {archive.name} ({archive.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
