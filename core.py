from datetime import date, timedelta
import math


def quota_summary(data):
    limits = data.get('rate_limit') or {}
    result = {}
    for name, window_name, reset_name in [('five_hour', 'primary_window', 'five_reset'), ('weekly', 'secondary_window', 'week_reset')]:
        window = limits.get(window_name) or {}
        used = window.get('used_percent')
        result[name] = max(0, min(100, 100 - used)) if type(used) in (int, float) and math.isfinite(used) else None
        reset = window.get('reset_at')
        result[reset_name] = reset if type(reset) is int and reset > 0 else None
    count = (data.get('rate_limit_reset_credits') or {}).get('available_count')
    result['reset_cards'] = count if type(count) is int and count >= 0 else None
    return result


def daily_series(report, today):
    days = {today - timedelta(days=offset): None for offset in range(6, -1, -1)}
    for row in report['daily']:
        day = date.fromisoformat(row['date'])
        if day in days:
            days[day] = (days[day] or 0) + int(row['totalTokens'])
    return list(days.items())


def summarize(report, today=None):
    today = today or date.today()
    start = today - timedelta(days=6)
    result = dict.fromkeys(('today', 'week', 'total', 'input', 'cached', 'output'), 0)
    for row in report['daily']:
        day = date.fromisoformat(row['date'])
        count = int(row['totalTokens'])
        result['total'] += count
        result['input'] += int(row['inputTokens'])
        result['cached'] += int(row['cacheReadTokens'])
        result['output'] += int(row['outputTokens'])
        if day == today:
            result['today'] += count
        if start <= day <= today:
            result['week'] += count
    return result


def place_panel(pet, size, work):
    left, top, right, bottom = pet
    width, height = size
    wl, wt, wr, wb = work
    x = right + 12 if right + 12 + width <= wr - 12 else left - width - 12
    return max(wl + 12, min(x, wr - width - 12)), max(wt + 12, min(top, wb - height - 12))


def choose_pet(windows, anchor, scale=1.0):
    candidates = []
    ax, ay = anchor
    for window in windows:
        _, process, (left, top, right, bottom), pet_overlay = window
        width, height = right - left, bottom - top
        if not pet_overlay or process not in ('ChatGPT', 'Codex') or width <= 0 or height <= 0:
            continue
        distance = max(left - ax, ax - right, 0) + max(top - ay, ay - bottom, 0)
        if distance <= 48 * scale:
            candidates.append((distance, width * height, window))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[:2])[2]
