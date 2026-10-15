import importlib.util
from datetime import date
from pathlib import Path


def core():
    path = Path(__file__).resolve().parents[1] / 'core.py'
    assert path.exists(), 'Token 面板核心尚未实现'
    spec = importlib.util.spec_from_file_location('pet_token_core', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_counts_cached_input_once_and_seven_calendar_days():
    report = {'daily': [
        {'date': '2026-10-08', 'inputTokens': 1, 'cacheReadTokens': 2, 'outputTokens': 3, 'totalTokens': 6},
        {'date': '2026-10-09', 'inputTokens': 10, 'cacheReadTokens': 20, 'outputTokens': 30, 'totalTokens': 60},
        {'date': '2026-10-15', 'inputTokens': 100, 'cacheReadTokens': 200, 'outputTokens': 300, 'reasoningOutputTokens': 50, 'totalTokens': 600},
    ]}
    result = core().summarize(report, date(2026, 10, 15))
    assert result['today'] == 600
    assert result['week'] == 660
    assert result['total'] == 666
    assert result['input'] == 111
    assert result['cached'] == 222
    assert result['output'] == 333


def test_empty_report_has_zeroes():
    assert core().summarize({'daily': []}, date(2026, 10, 15))['total'] == 0


def test_panel_stays_inside_work_area_and_avoids_pet():
    c = core()
    assert c.place_panel((900, 500, 990, 620), (340, 350), (0, 0, 1000, 700)) == (548, 338)
    assert c.place_panel((0, 0, 100, 120), (340, 350), (0, 0, 1000, 700)) == (112, 12)
    assert c.place_panel((-900, 300, -800, 420), (340, 350), (-1000, 0, 0, 700)) == (-788, 300)


def test_only_pet_sized_codex_window_near_anchor_is_selected():
    c = core()
    windows = [
        (1, 'ChatGPT', (0, 0, 2560, 1600), False),
        (2, 'Unrelated', (2200, 730, 2400, 950), True),
        (3, 'ChatGPT', (2200, 730, 2450, 1000), True),
    ]
    assert c.choose_pet(windows, (2234, 734)) == windows[2]
    assert c.choose_pet(windows, (1000, 1000)) is None


def test_full_height_transparent_pet_host_is_supported():
    window = (4, 'ChatGPT', (2150, 0, 2560, 1600), True)
    assert core().choose_pet([window], (2234, 734), 1.5) == window


def test_current_codex_full_height_host_does_not_depend_on_guessed_size():
    window = (3870032, 'ChatGPT', (1220, 0, 2656, 1602), True)
    assert core().choose_pet([window], (2167, 717), 1.5) == window


def test_ui_date_and_refresh_timestamp_use_beijing_time():
    import app
    from datetime import timedelta
    assert hasattr(app, 'beijing_now'), '界面日期尚未固定北京时间'
    assert app.beijing_now().utcoffset() == timedelta(hours=8)


def test_seven_day_chart_preserves_missing_dates_and_counts_recorded_zero():
    c = core()
    assert hasattr(c, 'daily_series'), '七天趋势数据尚未实现'
    report = {'daily': [
        {'date': '2026-10-08', 'totalTokens': 99},
        {'date': '2026-10-13', 'totalTokens': 10},
        {'date': '2026-10-13', 'totalTokens': 20},
        {'date': '2026-10-14', 'totalTokens': 0},
        {'date': '2026-10-15', 'totalTokens': 40},
        {'date': '2026-10-16', 'totalTokens': 99},
    ]}
    series = c.daily_series(report, date(2026, 10, 15))
    assert len(series) == 7
    assert series[0] == (date(2026, 10, 9), None)
    assert series[-3:] == [(date(2026, 10, 13), 30), (date(2026, 10, 14), 0), (date(2026, 10, 15), 40)]


def test_live_limits_show_remaining_and_available_reset_count():
    c = core()
    assert hasattr(c, 'quota_summary'), '账户额度读取尚未实现'
    result = c.quota_summary({'rate_limit': {
        'primary_window': {'used_percent': 70, 'reset_at': 123},
        'secondary_window': {'used_percent': 58, 'reset_at': 456}},
        'rate_limit_reset_credits': {'available_count': 0}})
    assert result == {'five_hour': 30, 'weekly': 42, 'five_reset': 123, 'week_reset': 456, 'reset_cards': 0}


def test_missing_quota_is_unknown_instead_of_zero_and_cards_are_not_balance():
    c = core()
    assert hasattr(c, 'quota_summary'), '账户额度读取尚未实现'
    result = c.quota_summary({'credits': {'balance': '99'}})
    assert all(value is None for value in result.values())
    assert c.quota_summary({'rate_limit_reset_credits': {'available_count': 3}})['reset_cards'] == 3


def test_quota_request_ignores_curl_config_and_keeps_credentials_off_command_line(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import quotas
    (tmp_path / 'auth.json').write_text(json.dumps({'tokens': {'access_token': 'test-secret', 'account_id': 'test-account'}}))
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"rate_limit_reset_credits":{"available_count":0}}')
    monkeypatch.setattr(quotas.subprocess, 'run', run)
    monkeypatch.setattr(quotas.urllib.request, 'getproxies', lambda: {})
    assert quotas.fetch_quota(tmp_path)['reset_cards'] == 0
    command, options = calls[0]
    assert command[1] == '-q'
    assert 'test-secret' not in ' '.join(command)
    assert 'test-secret' in options['input']


def test_views_are_separate_and_last_selection_is_remembered(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, 'PREFS', tmp_path / 'ui-prefs.json')
    p = app.Overlay()
    try:
        p.expanded = True
        p.view = 'quota'
        p.build()
        assert p.trend is None and not p.labels and 'reset_cards' in p.quota_labels
        p.switch_view('numbers')
        assert p.trend is None and 'today' in p.labels and not p.quota_labels
        p.switch_view('charts')
        assert p.trend is not None and 'today' not in p.labels and not p.quota_labels
    finally:
        p.root.destroy()
    restored = app.Overlay()
    try:
        assert restored.view == 'charts'
    finally:
        restored.root.destroy()
