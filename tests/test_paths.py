import importlib.util
from pathlib import Path


def paths():
    path = Path(__file__).resolve().parents[1] / 'paths.py'
    assert path.exists(), 'Portable runtime paths are not implemented'
    spec = importlib.util.spec_from_file_location('portable_paths', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_custom_codex_home_is_respected(tmp_path):
    p = paths()
    assert p.codex_home({'CODEX_HOME': str(tmp_path)}, Path('unused')) == tmp_path


def test_default_codex_home_follows_current_user(tmp_path):
    assert paths().codex_home({}, tmp_path) == tmp_path / '.codex'


def test_runtime_files_are_separate_from_program_files(tmp_path):
    assert paths().data_directory({'LOCALAPPDATA': str(tmp_path)}) == tmp_path / 'codex-tokenuse'


def test_bundled_usage_tool_needs_no_node_or_path_lookup(tmp_path):
    binary = tmp_path / 'runtime' / 'ccusage.exe'
    binary.parent.mkdir()
    binary.write_bytes(b'test-placeholder')
    command = paths().usage_command(tmp_path)
    assert command == [str(binary)]


def test_missing_usage_binary_has_an_actionable_error(tmp_path):
    import pytest
    with pytest.raises(RuntimeError, match='ccusage'):
        paths().usage_command(tmp_path)
