"""Paint a native loading surface before WebView2 has its first document.

The normal HTML startup/error screen takes over only after a browser paint.
No storage, model calls, navigation retries or workbench state is changed here.
"""
from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger(__name__)


def attach_startup_surface(window, observer=None):
    if sys.platform != 'win32':
        return None
    state = {'panel': None, 'disposed': False, 'handed_off': False, 'timer': None, 'form': None}
    started = time.perf_counter()

    def mark(event, **extra):
        if observer:
            observer({'event': event, 'elapsed': round(time.perf_counter() - started, 4), **extra})

    def do_handoff(surface='workbench'):
        if state['disposed'] or state['handed_off']:
            return
        state['handed_off'] = True
        timer = state.get('timer')
        if timer is not None:
            try:
                timer.Stop()
                timer.Dispose()
            except Exception:
                pass
        panel = state.get('panel')
        if panel is not None and panel.Parent is not None:
            try:
                panel.Parent.Controls.Remove(panel)
                panel.Dispose()
            except Exception:
                pass
        mark('browser_handoff', document=surface)

    def before_show():
        # before_show is a synchronous GUI-thread event. Adding controls here
        # avoids both the blank first frame and cross-thread WinForms calls.
        try:
            from System import Action
            from System.Drawing import Color, Font, FontStyle, Point, Size
            from System.Windows.Forms import AnchorStyles, Button, DockStyle, Label, Panel, Timer
            form = window.native
            if form is None or not hasattr(form, 'Controls'):
                return
            panel = Panel()
            panel.Dock = DockStyle.Fill
            panel.BackColor = Color.FromArgb(246, 247, 249)
            panel.Name = 'CDTVNativeStartup'
            card = Panel()
            card.Size = Size(440, 180)
            card.BackColor = panel.BackColor
            brand = Label()
            brand.Text = 'CDTV'
            brand.Font = Font('Microsoft YaHei UI', 26, FontStyle.Bold)
            brand.ForeColor = Color.FromArgb(37, 48, 71)
            brand.AutoSize = True
            brand.Location = Point(0, 0)
            heading = Label()
            heading.Text = '正在打开创作工作台'
            heading.Font = Font('Microsoft YaHei UI', 14)
            heading.ForeColor = brand.ForeColor
            heading.AutoSize = True
            heading.Location = Point(0, 65)
            status = Label()
            status.Text = '正在准备界面，请稍候…'
            status.Font = Font('Microsoft YaHei UI', 10)
            status.ForeColor = Color.FromArgb(95, 107, 125)
            status.AutoSize = True
            status.Location = Point(0, 110)
            for control in (brand, heading, status):
                card.Controls.Add(control)
            close = Button()
            close.Text = '×'
            close.AccessibleName = '关闭启动窗口'
            close.Font = Font('Microsoft YaHei UI', 15)
            close.Size = Size(40, 36)
            close.Anchor = AnchorStyles.Top | AnchorStyles.Right
            close.Click += lambda *_: form.Close()
            panel.Controls.Add(card)
            panel.Controls.Add(close)

            def layout(*_):
                card.Location = Point(max(24, (panel.ClientSize.Width - card.Width) // 2), max(50, (panel.ClientSize.Height - card.Height) // 2))
                close.Location = Point(max(0, panel.ClientSize.Width - 52), 10)

            panel.Resize += layout
            painted = [False]

            def paint(*_):
                if not painted[0]:
                    painted[0] = True
                    mark('native_painted', width=panel.ClientSize.Width, height=panel.ClientSize.Height)

            panel.Paint += paint
            form.Controls.Add(panel)
            panel.BringToFront()
            state['panel'] = panel
            state['form'] = form
            layout()
            mark('native_attached', visible=bool(panel.Visible))
            timer = Timer()
            timer.Interval = 10000

            def slow(*_):
                timer.Stop()
                if not state['disposed'] and not state['handed_off']:
                    status.Text = '启动耗时较长，正在进入工作台…'
                    mark('native_timeout_handoff')
                    form = state.get('form')
                    if form is not None and not form.IsDisposed:
                        form.BeginInvoke(Action(lambda: do_handoff('timeout_fallback')))
                    else:
                        do_handoff('timeout_fallback')

            timer.Tick += slow
            state['timer'] = timer
            timer.Start()
        except Exception:
            # An unsupported backend must still follow its normal startup path.
            log.exception('Could not create the optional native startup surface')

    def loaded():
        if state['disposed'] or state['handed_off'] or state['panel'] is None:
            return
        mark('document_loaded')

        def painted(result):
            # A loaded/error document without actual UI must not reveal blank.
            if not isinstance(result, dict) or result.get('painted') is not True:
                return
            from System import Action
            surface = result.get('surface', 'workbench')
            form = state.get('form')
            if form is not None and not form.IsDisposed:
                form.BeginInvoke(Action(lambda: do_handoff(surface)))
            else:
                do_handoff(surface)

        # In WebView2, when a native Control is docked over the webview,
        # requestAnimationFrame can be paused or delayed by the compositor.
        # We use setTimeout-based polling with an immediate check and a maximum
        # bounded wait (1.5s) to guarantee handoff never blocks.
        js_check = """new Promise(resolve => {
            // requestAnimationFrame
            const start = Date.now();
            const check = () => {
                try {
                    const startup = document.getElementById('startup-screen');
                    const app = document.getElementById('app');
                    const visible = el => !!el && (el.offsetHeight > 0 || el.getBoundingClientRect().height > 0)
                        && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
                    if (visible(startup) || visible(app) || (Date.now() - start > 1500)) {
                        resolve({painted: true, surface: visible(startup) ? 'startup' : 'workbench'});
                        return;
                    }
                } catch(e) {}
                setTimeout(check, 30);
            };
            check();
        })"""

        try:
            window.evaluate_js(js_check, painted)
        except Exception:
            log.exception('Native startup is waiting for a painted document')
            from System import Action
            form = state.get('form')
            if form is not None and not form.IsDisposed:
                form.BeginInvoke(Action(lambda: do_handoff('exception_fallback')))
            else:
                do_handoff('exception_fallback')

    def closing():
        state['disposed'] = True
        timer = state['timer']
        if timer is not None:
            timer.Stop()
            timer.Dispose()
        mark('closed')

    window.events.before_show += before_show
    window.events.loaded += loaded
    window.events.closing += closing
    return state
