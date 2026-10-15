"""只读 Codex 桌宠旁的 Token 统计面板。"""
import ctypes
from ctypes import wintypes as w
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import webbrowser

from core import choose_pet, daily_series, place_panel, summarize
from quotas import fetch_quota
from paths import codex_home, data_directory, usage_command

BASE = data_directory()
BASE.mkdir(parents=True, exist_ok=True)
CODEX = codex_home()
STATE = CODEX / '.codex-global-state.json'
CACHE = BASE / 'usage-cache.json'
QUOTA_CACHE = BASE / 'quota-cache.json'
PREFS = BASE / 'ui-prefs.json'
BG, INK, MUTED, LINE = '#faf8f3', '#292722', '#827c72', '#e3ded5'
ACCENT, TRACK = '#b57743', '#eee8de'
logging.basicConfig(filename=BASE / 'app.log', level=logging.WARNING)
u = ctypes.windll.user32
k = ctypes.windll.kernel32
u.SetProcessDPIAware()

u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.IsWindowVisible.argtypes = [w.HWND]
u.IsIconic.argtypes = [w.HWND]
u.GetDpiForWindow.argtypes = [w.HWND]
u.GetAncestor.argtypes = [w.HWND, w.UINT]
u.GetAncestor.restype = w.HWND
u.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
u.SetWindowLongW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_long]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
u.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
u.MonitorFromWindow.restype = w.HANDLE
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
k.CloseHandle.argtypes = [w.HANDLE]
k.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
k.CreateMutexW.restype = w.HANDLE


class MonitorInfo(ctypes.Structure):
    _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT), ('flags', w.DWORD)]


u.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(MonitorInfo)]
ENUM = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [ENUM, w.LPARAM]
gdi = ctypes.windll.gdi32
gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi.CreateRoundRectRgn.restype = w.HANDLE
gdi.DeleteObject.argtypes = [w.HANDLE]
u.SetWindowRgn.argtypes = [w.HWND, w.HANDLE, w.BOOL]


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


def rect(hwnd):
    result = w.RECT()
    if u.GetWindowRect(hwnd, ctypes.byref(result)):
        return result.left, result.top, result.right, result.bottom


def inside(point, bounds, padding=0):
    x, y = point
    l, t, r, b = bounds
    return l - padding <= x <= r + padding and t - padding <= y <= b + padding


def codex_windows():
    windows = []

    @ENUM
    def visit(hwnd, _):
        if not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd):
            return True
        pid = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = k.OpenProcess(0x1000, False, pid.value)
        if process:
            try:
                path = ctypes.create_unicode_buffer(1024)
                size = w.DWORD(len(path))
                if k.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                    name = Path(path.value).stem
                    bounds = rect(hwnd)
                    if name in ('ChatGPT', 'Codex') and bounds:
                        style = u.GetWindowLongW(hwnd, -20)
                        windows.append((hwnd, name, bounds, bool(style & 0x00080000 and style & 0x00000080)))
            finally:
                k.CloseHandle(process)
        return True

    u.EnumWindows(visit, 0)
    return windows


class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.panel = tk.Toplevel(self.root)
        self.panel.withdraw()
        self.panel.title('Codex TokenUse')
        self.panel.overrideredirect(True)
        self.panel.attributes('-topmost', True)
        self.panel.configure(bg=LINE)
        self.body = tk.Frame(self.panel, bg=BG, padx=14, pady=12)
        self.body.pack(fill='both', expand=True, padx=1, pady=1)
        self.expanded = False
        self.anchor = None
        self.pet_hwnd = None
        self.host_origin = None
        self.last_hover = 0.0
        self.last_refresh = 0.0
        self.last_state_read = 0.0
        self.state = {}
        self.report = None
        self.updated = None
        self.refreshing = False
        self.error = None
        self.results = queue.Queue()
        self.scale = 1.5
        self.labels = {}
        self.status = None
        self.trend = None
        self.composition = None
        self.current_bounds = None
        self.rounded_size = None
        self.view = 'quota'
        self.quota = None
        self.quota_updated = None
        self.quota_refreshing = False
        self.quota_error = None
        self.last_quota_refresh = 0
        self.quota_results = queue.Queue()
        self.quota_labels = {}
        self.quota_bars = {}
        try:
            view = json.loads(PREFS.read_text(encoding='utf-8')).get('view')
            if view in ('quota', 'numbers', 'charts'):
                self.view = view
        except (OSError, ValueError):
            pass
        try:
            cached = json.loads(QUOTA_CACHE.read_text(encoding='utf-8'))
            self.quota, self.quota_updated = cached['quota'], cached['updated']
        except (OSError, ValueError, KeyError):
            pass
        try:
            cached = json.loads(CACHE.read_text(encoding='utf-8'))
            summarize(cached['report'])
            self.report, self.updated = cached['report'], cached['updated']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.build()
        self.root.update_idletasks()
        hwnd = u.GetAncestor(self.panel.winfo_id(), 2)
        style = u.GetWindowLongW(hwnd, -20)
        u.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)
        self.panel.bind('<Escape>', lambda _: self.collapse())

    def label(self, parent, text, size=9, color=MUTED, bold=False):
        return tk.Label(parent, text=text, font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'),
                        fg=color, bg=BG, anchor='w')

    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, relief='flat', bd=0,
                         font=('Microsoft YaHei UI', 8), padx=9, pady=4, cursor='hand2',
                         bg=INK if primary else BG, fg=BG if primary else MUTED,
                         activebackground=TRACK, activeforeground=INK, takefocus=False)

    def switch_view(self, view):
        self.view = view
        PREFS.write_text(json.dumps({'view': view}), encoding='utf-8')
        self.last_hover = time.monotonic()
        self.build()
        if view == 'quota':
            self.refresh_quota()

    def build(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.labels, self.quota_labels, self.quota_bars = {}, {}, {}
        self.status = self.trend = self.composition = None
        if not self.expanded:
            self.body.configure(padx=0, pady=0)
            width, height = round(102 * self.scale) - 2, round(30 * self.scale) - 2
            pill = tk.Canvas(self.body, width=width, height=height, bg=BG, highlightthickness=0, cursor='hand2')
            pill.pack(fill='both', expand=True)
            for index, bar in enumerate((7, 15, 11)):
                x = 16 + index * 6
                pill.create_line(x, height / 2 + 7, x, height / 2 + 7 - bar, fill=ACCENT, width=3)
            pill.create_text(47, height / 2, text='用量', anchor='w', fill=INK, font=('Microsoft YaHei UI', 9, 'bold'))
            pill.create_line(width - 22, height / 2 - 4, width - 18, height / 2, width - 22, height / 2 + 4, fill=MUTED, width=1.5)
            pill.bind('<Button-1>', lambda _: self.expand())
            pill.bind('<Enter>', lambda _: pill.configure(bg=TRACK))
            pill.bind('<Leave>', lambda _: pill.configure(bg=BG))
            return
        self.body.configure(padx=14, pady=12)
        header = tk.Frame(self.body, bg=BG)
        header.pack(fill='x')
        brand = tk.Frame(header, bg=BG)
        brand.pack(side='left')
        self.label(brand, 'CODEX  /  TOKENUSE', 7).pack(fill='x')
        self.label(brand, '用量概览', 12, INK, True).pack(fill='x')
        self.button(header, '收起', self.collapse).pack(side='right')
        tabs = tk.Frame(self.body, bg=TRACK, padx=3, pady=3)
        tabs.pack(fill='x', pady=(10, 12))
        for view, text in [('quota', '额度'), ('numbers', '数字'), ('charts', '图表')]:
            tab = self.button(tabs, text, lambda view=view: self.switch_view(view))
            tab.configure(bg=BG if view == self.view else TRACK, fg=INK if view == self.view else MUTED,
                          font=('Microsoft YaHei UI', 8, 'bold' if view == self.view else 'normal'))
            tab.pack(side='left', fill='x', expand=True)
        content = tk.Frame(self.body, bg=BG, height=round(185 * self.scale), width=round(250 * self.scale))
        content.pack(fill='x')
        content.pack_propagate(False)
        if self.view == 'quota':
            for key, reset_key, title in [('five_hour', 'five_reset', '5 小时限额'), ('weekly', 'week_reset', '周限额')]:
                row = tk.Frame(content, bg=BG)
                row.pack(fill='x')
                self.label(row, title, 9, INK, True).pack(side='left')
                self.quota_labels[key] = self.label(row, '—', 19, INK, True)
                self.quota_labels[key].pack(side='right')
                self.quota_labels[reset_key] = self.label(content, '正在读取账户额度', 7)
                self.quota_labels[reset_key].pack(fill='x')
                bar = tk.Canvas(content, height=5, bg=TRACK, highlightthickness=0)
                bar.pack(fill='x', pady=(5, 12))
                bar.bind('<Configure>', lambda _: self.render_quota())
                self.quota_bars[key] = bar
            card = tk.Frame(content, bg=BG)
            card.pack(fill='x', pady=(6, 0))
            self.label(card, '可用重置卡', 9, INK, True).pack(side='left')
            self.quota_labels['reset_cards'] = self.label(card, '—', 17, ACCENT, True)
            self.quota_labels['reset_cards'].pack(side='right')
        elif self.view == 'numbers':
            self.label(content, '今日 TOKEN', 8).pack(fill='x')
            self.labels['today'] = self.label(content, '读取中…', 21, INK, True)
            self.labels['today'].pack(fill='x', pady=(0, 7))
            metrics = tk.Frame(content, bg=BG)
            metrics.pack(fill='x')
            for key, title in [('week', '近七天'), ('total', '累计')]:
                column = tk.Frame(metrics, bg=BG)
                column.pack(side='left', fill='x', expand=True)
                self.label(column, title, 7).pack(fill='x')
                self.labels[key] = self.label(column, '—', 10, INK, True)
                self.labels[key].pack(fill='x')
            tk.Frame(content, bg=LINE, height=1).pack(fill='x', pady=10)
            for key, title in [('input', '未缓存输入'), ('cached', '缓存输入'), ('output', '输出（含推理）')]:
                row = tk.Frame(content, bg=BG)
                row.pack(fill='x', pady=1)
                self.label(row, title, 8).pack(side='left')
                self.labels[key] = self.label(row, '—', 8, INK, True)
                self.labels[key].pack(side='right')
        else:
            row = tk.Frame(content, bg=BG)
            row.pack(fill='x')
            self.label(row, '近七天趋势', 9, INK, True).pack(side='left')
            self.chart_hint = self.label(row, '悬停查看数字', 7)
            self.chart_hint.pack(side='right')
            self.trend = tk.Canvas(content, width=round(250 * self.scale), height=round(100 * self.scale), bg=BG, highlightthickness=0)
            self.trend.pack(fill='x', pady=(7, 10))
            self.trend.bind('<Configure>', lambda _: self.draw_charts())
            self.trend.bind('<Motion>', self.chart_hover)
            self.trend.bind('<Leave>', lambda _: self.chart_hint.configure(text='悬停查看数字'))
            self.label(content, '累计构成', 8, INK, True).pack(fill='x')
            self.composition = tk.Canvas(content, width=round(250 * self.scale), height=7, bg=BG, highlightthickness=0)
            self.composition.pack(fill='x', pady=(5, 5))
            self.composition.bind('<Configure>', lambda _: self.draw_charts())
            legend = tk.Frame(content, bg=BG)
            legend.pack(fill='x')
            for key, title, color in [('input', '输入', '#484640'), ('cached', '缓存', '#b57743'), ('output', '输出', '#a99c86')]:
                self.labels[key] = self.label(legend, '● ' + title, 7, color)
                self.labels[key].pack(side='left', fill='x', expand=True)
        tk.Frame(self.body, bg=LINE, height=1).pack(fill='x', pady=(8, 7))
        footer = tk.Frame(self.body, bg=BG)
        footer.pack(fill='x')
        self.status = self.label(footer, '', 7)
        self.status.pack(side='left')
        self.button(footer, '刷新', self.refresh_current).pack(side='right')
        links = tk.Frame(self.body, bg=BG)
        links.pack(fill='x', pady=(3, 0))
        self.button(links, '使用说明 ↗', self.open_help).pack(side='left')
        self.button(links, '退出', self.root.destroy).pack(side='right')
        self.render()

    def render_quota(self):
        if not self.expanded or self.view != 'quota':
            return
        data = self.quota or {}
        for key, reset_key in [('five_hour', 'five_reset'), ('weekly', 'week_reset')]:
            value = data.get(key)
            self.quota_labels[key].configure(text=f'{value:g}% 剩余' if value is not None else '—')
            reset = data.get(reset_key)
            text = datetime.fromtimestamp(reset, timezone(timedelta(hours=8))).strftime('%m/%d %H:%M 重置') if reset else '重置时间未知'
            self.quota_labels[reset_key].configure(text=text)
            bar = self.quota_bars[key]
            bar.delete('all')
            if value is not None:
                bar.create_rectangle(0, 0, bar.winfo_width() * value / 100, 5, fill=ACCENT if value > 20 else '#aa4f35', outline='')
        count = data.get('reset_cards')
        self.quota_labels['reset_cards'].configure(text=f'{count} 张' if count is not None else '未知')

    def render(self):
        if not self.expanded:
            return
        if self.view == 'quota':
            self.render_quota()
            refreshing, error, updated = self.quota_refreshing, self.quota_error, self.quota_updated
            source = '账户'
        else:
            if self.report:
                summary = summarize(self.report, beijing_now().date())
                for key, label in self.labels.items():
                    if self.view == 'numbers':
                        label.configure(text=f'{summary[key]:,}')
                    else:
                        title = {'input': '输入', 'cached': '缓存', 'output': '输出'}[key]
                        share = summary[key] / summary['total'] * 100 if summary['total'] else 0
                        label.configure(text=f'● {title} {share:.1f}%')
                self.draw_charts()
            refreshing, error, updated = self.refreshing, self.error, self.updated
            source = '本机'
        if refreshing:
            status = '正在刷新…'
        elif error:
            status = '读取失败 · 上次 ' + datetime.fromisoformat(updated).strftime('%H:%M') if updated else '暂未读取到数据'
        elif updated:
            status = source + ' · ' + datetime.fromisoformat(updated).strftime('%H:%M:%S')
        else:
            status = '等待读取…'
        self.status.configure(text=status)

    def draw_charts(self):
        if not self.expanded or self.view != 'charts' or not self.trend or not self.composition:
            return
        report = self.report or {'daily': []}
        series = daily_series(report, beijing_now().date())
        canvas = self.trend
        canvas.delete('all')
        width = max(canvas.winfo_width(), int(canvas['width']))
        height = int(canvas['height'])
        baseline, top = height - 22, 8
        maximum = max((count or 0 for _, count in series), default=0)
        for fraction in (0, 0.5, 1):
            y = baseline - (baseline - top) * fraction
            canvas.create_line(0, y, width, y, fill=LINE, dash=(2, 4))
        cell = width / 7
        for index, (day, count) in enumerate(series):
            center = (index + 0.5) * cell
            bar_width = cell * 0.42
            if count is None:
                canvas.create_text(center, baseline - 6, text='–', fill='#b9b0a1', font=('Microsoft YaHei UI', 8))
            elif count == 0:
                canvas.create_line(center - bar_width / 2, baseline, center + bar_width / 2, baseline, fill=ACCENT, width=2)
            else:
                bar_height = (baseline - top) * count / maximum
                canvas.create_rectangle(center - bar_width / 2, baseline - bar_height, center + bar_width / 2, baseline,
                                        fill=ACCENT if index == 6 else '#d5bd9f', outline='')
            canvas.create_text(center, height - 8, text=day.strftime('%m/%d'), fill=INK if index == 6 else MUTED,
                               font=('Microsoft YaHei UI', 7))
        summary = summarize(report, beijing_now().date())
        canvas = self.composition
        canvas.delete('all')
        width = max(canvas.winfo_width(), int(canvas['width']))
        height = int(canvas['height'])
        canvas.create_rectangle(0, 0, width, height, fill=TRACK, outline='')
        x = 0
        for key, color in [('input', '#484640'), ('cached', '#b57743'), ('output', '#a99c86')]:
            end = x + width * summary[key] / summary['total'] if summary['total'] else x
            canvas.create_rectangle(x, 0, end, height, fill=color, outline='')
            x = end

    def chart_hover(self, event):
        series = daily_series(self.report or {'daily': []}, beijing_now().date())
        index = min(6, max(0, int(event.x / max(1, self.trend.winfo_width()) * 7)))
        day, count = series[index]
        value = f'{count:,}' if count is not None else '无本机记录'
        self.chart_hint.configure(text=day.strftime('%m/%d') + ' · ' + value)

    def refresh_current(self):
        if self.view == 'quota':
            self.refresh_quota(force=True)
        else:
            self.refresh(force=True)

    def refresh_quota(self, force=False):
        if self.quota_refreshing or (not force and time.monotonic() - self.last_quota_refresh < 60):
            return
        self.quota_refreshing = True
        self.last_quota_refresh = time.monotonic()
        self.render()

        def worker():
            try:
                quota = fetch_quota(CODEX)
                updated = beijing_now().isoformat()
                QUOTA_CACHE.write_text(json.dumps({'quota': quota, 'updated': updated}), encoding='utf-8')
                self.quota_results.put((quota, updated, None))
            except Exception:
                self.quota_results.put((None, None, '账户额度读取失败'))

        threading.Thread(target=worker, daemon=True).start()


    def expand(self):
        self.expanded = True
        self.last_hover = time.monotonic()
        self.build()
        self.refresh_current()

    def collapse(self):
        self.expanded = False
        self.last_hover = time.monotonic()
        self.build()

    def open_help(self):
        webbrowser.open('https://github.com/Qiu1717/codex-tokenuse#使用方法')

    def refresh(self, force=False):
        if self.refreshing or (not force and time.monotonic() - self.last_refresh < 30):
            return
        self.refreshing = True
        self.last_refresh = time.monotonic()
        self.render()

        def worker():
            try:
                process = subprocess.run([*usage_command(), 'codex', 'daily', '--json', '--offline',
                                          '--no-cost', '--timezone', 'Asia/Shanghai'],
                                         capture_output=True, text=True, encoding='utf-8',
                                         creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
                if process.returncode:
                    raise RuntimeError('Local statistics command failed')
                report = json.loads(process.stdout)
                summarize(report)
                updated = beijing_now().isoformat()
                CACHE.write_text(json.dumps({'report': report, 'updated': updated}, ensure_ascii=False), encoding='utf-8')
                self.results.put((report, updated, None))
            except Exception as exc:
                logging.exception('Token refresh failed')
                self.results.put((None, None, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def pet_bounds(self):
        now = time.monotonic()
        if now - self.last_state_read > 0.4:
            self.last_state_read = now
            try:
                self.state = json.loads(STATE.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return None
        if not self.state.get('electron-avatar-overlay-open'):
            self.pet_hwnd = None
            return None
        stored = self.state.get('electron-avatar-overlay-bounds') or {}
        if not self.pet_hwnd or not u.IsWindowVisible(self.pet_hwnd) or u.IsIconic(self.pet_hwnd):
            self.pet_hwnd = None
            windows = codex_windows()
            for window in windows:
                scale = (u.GetDpiForWindow(window[0]) or 96) / 96
                monitor = MonitorInfo()
                monitor.size = ctypes.sizeof(monitor)
                u.GetMonitorInfoW(u.MonitorFromWindow(window[0], 2), ctypes.byref(monitor))
                display = stored.get('displayBounds', {})
                ax = monitor.monitor.left + (stored.get('x', 0) - display.get('x', 0)) * scale
                ay = monitor.monitor.top + (stored.get('y', 0) - display.get('y', 0)) * scale
                candidate = choose_pet([window], (ax, ay), scale)
                if candidate and (not self.pet_hwnd or (window[2][2] - window[2][0]) * (window[2][3] - window[2][1]) < best_area):
                    self.pet_hwnd = window[0]
                    best_area = (window[2][2] - window[2][0]) * (window[2][3] - window[2][1])
                    self.scale = scale
                    self.host_origin = (window[2][0], window[2][1])
                    self.anchor_position = (ax, ay)
                    self.saved_position = (stored.get('x'), stored.get('y'), stored.get('displayId'))
            if not self.pet_hwnd:
                return None
        current = rect(self.pet_hwnd)
        if not current:
            self.pet_hwnd = None
            return None
        self.scale = (u.GetDpiForWindow(self.pet_hwnd) or 96) / 96
        monitor = MonitorInfo()
        monitor.size = ctypes.sizeof(monitor)
        u.GetMonitorInfoW(u.MonitorFromWindow(self.pet_hwnd, 2), ctypes.byref(monitor))
        self.work = (monitor.work.left, monitor.work.top, monitor.work.right, monitor.work.bottom)
        display = stored.get('displayBounds', {})
        saved_position = (stored.get('x'), stored.get('y'), stored.get('displayId'))
        if saved_position != self.saved_position:
            x = monitor.monitor.left + (stored.get('x', 0) - display.get('x', 0)) * self.scale
            y = monitor.monitor.top + (stored.get('y', 0) - display.get('y', 0)) * self.scale
        else:
            x = self.anchor_position[0] + current[0] - self.host_origin[0]
            y = self.anchor_position[1] + current[1] - self.host_origin[1]
        self.host_origin, self.anchor_position, self.saved_position = current[:2], (x, y), saved_position
        mascot = stored.get('mascot') or stored.get('anchor') or {}
        # 当前版本不公开龙娘的轮廓，覆盖已实测的形象范围；出现精确尺寸时优先使用。
        width = float(mascot.get('width', 200)) * self.scale
        height = float(mascot.get('height', 220)) * self.scale
        return tuple(map(round, (x, y, x + width, y + height)))

    def tick(self):
        try:
            while not self.quota_results.empty():
                quota, updated, error = self.quota_results.get_nowait()
                self.quota_refreshing, self.quota_error = False, error
                if quota is not None:
                    self.quota, self.quota_updated = quota, updated
                self.render()
            while not self.results.empty():
                report, updated, error = self.results.get_nowait()
                self.refreshing, self.error = False, error
                if report is not None:
                    self.report, self.updated = report, updated
                self.render()
            self.anchor = self.pet_bounds()
            if self.anchor is None:
                self.panel.withdraw()
                self.expanded = False
                self.current_bounds = None
            else:
                cursor = w.POINT()
                u.GetCursorPos(ctypes.byref(cursor))
                point = (cursor.x, cursor.y)
                over = inside(point, self.anchor, 12 * self.scale) or (
                    self.current_bounds is not None and inside(point, self.current_bounds, 16 * self.scale))
                if over:
                    self.last_hover = time.monotonic()
                visible = time.monotonic() - self.last_hover < 1.2
                if visible:
                    if not self.expanded and self.status is not None:
                        self.build()
                    self.root.update_idletasks()
                    size = (max(round(278 * self.scale), self.panel.winfo_reqwidth()), self.panel.winfo_reqheight()) if self.expanded else (round(102 * self.scale), round(30 * self.scale))
                    x, y = place_panel(self.anchor, size, self.work)
                    self.panel.geometry(f'{size[0]}x{size[1]}{x:+}{y:+}')
                    self.current_bounds = (x, y, x + size[0], y + size[1])
                    self.panel.deiconify()
                    hwnd = u.GetAncestor(self.panel.winfo_id(), 2)
                    u.SetWindowPos(hwnd, w.HWND(-1), x, y, size[0], size[1], 0x0010)
                    rounded_size = (*size, self.expanded)
                    if rounded_size != self.rounded_size:
                        radius = round(12 * self.scale) if self.expanded else size[1]
                        region = gdi.CreateRoundRectRgn(0, 0, size[0] + 1, size[1] + 1, radius, radius)
                        if region and not u.SetWindowRgn(hwnd, region, True):
                            gdi.DeleteObject(region)
                        self.rounded_size = rounded_size
                    if self.view == 'quota':
                        self.refresh_quota()
                    else:
                        self.refresh()
                else:
                    self.panel.withdraw()
                    self.expanded = False
                    self.current_bounds = None
        except Exception:
            logging.exception('Pet follow failed')
            self.panel.withdraw()
        self.root.after(120, self.tick)

    def run(self):
        self.tick()
        self.root.mainloop()


def self_test():
    """Validate the packaged runtime without touching Codex, auth or the desktop pet."""
    result = subprocess.run([*usage_command(), '--version'], capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    if result.returncode:
        raise RuntimeError('Bundled ccusage self-test failed')
    overlay = Overlay()
    sizes = {}
    try:
        overlay.expanded = True
        for view in ('quota', 'numbers', 'charts'):
            overlay.view = view
            overlay.build()
            overlay.root.update_idletasks()
            sizes[view] = [overlay.panel.winfo_reqwidth(), overlay.panel.winfo_reqheight()]
    finally:
        overlay.root.destroy()
    (BASE / 'self-test.json').write_text(json.dumps({'ok': True, 'ccusage': result.stdout.strip(), 'views': sizes}), encoding='utf-8')


if __name__ == '__main__' and '--self-test' in sys.argv:
    self_test()
elif __name__ == '__main__':
    mutex = k.CreateMutexW(None, False, 'Local\\CodexTokenUse')
    if k.GetLastError() != 183:
        try:
            overlay = Overlay()
            try:
                shown = json.loads(STATE.read_text(encoding='utf-8')).get('electron-avatar-overlay-open')
            except (OSError, ValueError):
                shown = False
            if not shown:
                messagebox.showinfo('Codex TokenUse', '程序已启动。\n\n请在 Codex 中显示桌宠（例如输入 /pet），然后悬停桌宠并点击「用量」。\n\n需要先安装并登录 Codex；退出可从用量面板操作。', parent=overlay.root)
            overlay.run()
        except Exception:
            logging.exception('Token overlay stopped')
            messagebox.showerror('Codex TokenUse', '启动失败，请查看本机配置目录中的 app.log。')
    else:
        messagebox.showinfo('Codex TokenUse', '程序已在运行。请显示 Codex 桌宠，悬停后点击「用量」。')
    if mutex:
        k.CloseHandle(mutex)
