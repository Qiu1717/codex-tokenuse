"""Capture the real UI with synthetic data, never a user's pet or usage."""
import os
from pathlib import Path
import sys
import time
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['CODEX_TOKENUSE_DATA_DIR'] = str(ROOT / '.work' / 'preview-data')
os.environ['CODEX_HOME'] = str(ROOT / '.work' / 'empty-codex')

from PIL import ImageGrab
import app


overlay = app.Overlay()
now = app.beijing_now()
overlay.report = {'daily': []}
for offset, total in enumerate([600000, 920000, 430000, 1250000, 780000, 1040000, 860000]):
    overlay.report['daily'].append({'date': (now.date() - timedelta(days=6 - offset)).isoformat(),
        'inputTokens': total * 15 // 100, 'cacheReadTokens': total * 80 // 100,
        'outputTokens': total * 5 // 100, 'totalTokens': total})
overlay.updated = now.replace(hour=9, minute=30, second=0, microsecond=0).isoformat()
overlay.quota_updated = overlay.updated
overlay.quota = {'five_hour': 72, 'weekly': 48, 'reset_cards': 2,
                 'five_reset': int((now + timedelta(hours=3)).timestamp()),
                 'week_reset': int((now + timedelta(days=4)).timestamp())}
underlay = app.tk.Toplevel(overlay.root)
underlay.overrideredirect(True)
underlay.attributes('-topmost', True)
underlay.configure(bg='#efebe3')
try:
    for view in ('entry', 'quota', 'numbers', 'charts'):
        overlay.expanded = view != 'entry'
        overlay.view = view if overlay.expanded else 'quota'
        overlay.build()
        def mark(widget):
            if isinstance(widget, app.tk.Label) and widget.cget('text') == 'CODEX  /  TOKENUSE':
                widget.configure(text='DEMO  /  演示数据')
            for child in widget.winfo_children():
                mark(child)
        mark(overlay.body)
        overlay.root.update_idletasks()
        width = max(round(278 * overlay.scale), overlay.panel.winfo_reqwidth()) if overlay.expanded else 153
        height = overlay.panel.winfo_reqheight() if overlay.expanded else 45
        underlay.geometry(f'{width + 20}x{height + 20}+40+40')
        overlay.panel.geometry(f'{width}x{height}+50+50')
        overlay.panel.deiconify()
        overlay.root.update()
        overlay.panel.lift()
        overlay.render()
        hwnd = app.u.GetAncestor(overlay.panel.winfo_id(), 2)
        radius = 18 if overlay.expanded else height
        region = app.gdi.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
        if not app.u.SetWindowRgn(hwnd, region, True):
            app.gdi.DeleteObject(region)
        overlay.root.update()
        time.sleep(.15)
        ImageGrab.grab(bbox=(40, 40, 60 + width, 60 + height)).save(ROOT / 'docs' / f'{view}.png')
finally:
    overlay.root.destroy()
