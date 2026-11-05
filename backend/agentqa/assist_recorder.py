"""What a person does in a browser handed to them (clicks, typed values, Enter), recorded so AgentQA can repeat
it (moved out of `assist.py` in M1.4 Phase C, unchanged). login_flow turns the recording into login steps."""
from __future__ import annotations


RECORDER_JS = r"""(() => {
  if (window.__aqRecOn) return; window.__aqRecOn = true;
  const send = ev => { try { if (window.__aqRec) window.__aqRec(ev); } catch (e) {} };
  const clean = t => (t || '').trim().replace(/\s+/g, ' ');
  const labelOf = e => {
    let l = '';
    if (e.labels && e.labels.length) l = e.labels[0].innerText;
    if (!l && e.getAttribute && e.getAttribute('aria-label')) l = e.getAttribute('aria-label');
    if (!l) { let p = e.previousElementSibling; while (p && !l) { if (/^(LABEL|SPAN|DIV|P|B|STRONG)$/.test(p.tagName)) l = p.innerText; p = p.previousElementSibling; } }
    return clean(l).slice(0, 80);
  };
  const desc = e => {
    if (!e || !e.tagName) return {};
    const d = {tag: e.tagName.toLowerCase(), type: (e.getAttribute('type') || (e.tagName === 'SELECT' ? 'select' : e.tagName === 'TEXTAREA' ? 'textarea' : '')).toLowerCase(),
               name: e.name || e.getAttribute('name') || '', elid: e.id || '', label: /^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) ? labelOf(e) : '',
               placeholder: e.placeholder || '', aria: e.getAttribute('aria-label') || '', title: e.title || '',
               text: /^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) ? clean(e.type === 'submit' || e.type === 'button' ? e.value : '') : clean(e.innerText).slice(0, 80),
               href: e.getAttribute('href') || '', autocomplete: e.autocomplete || '', maxlength: e.maxLength > 0 ? e.maxLength : null,
               role: e.getAttribute('role') || ''};
    return d;
  };
  const target = e => (e && e.closest) ? (e.closest('a,button,[role=button],[role=tab],[role=menuitem],[role=link],input,select,textarea,summary,label,[onclick]') || e) : e;
  const last = new WeakMap();
  const flush = e => {
    if (!e || !/^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) || ['submit', 'button', 'checkbox', 'radio', 'file', 'hidden'].includes(e.type)) return;
    const v = e.tagName === 'SELECT' ? clean((e.options[e.selectedIndex] || {}).text || e.value) : e.value;
    if (last.get(e) === v) return; last.set(e, v);
    send({kind: e.tagName === 'SELECT' ? 'select' : 'input', el: desc(e), value: v, url: location.href, t: Date.now()});
  };
  document.addEventListener('click', ev => { const t = target(ev.target);
    if (t && /^(INPUT|TEXTAREA)$/.test(t.tagName) && !['submit', 'button', 'checkbox', 'radio'].includes(t.type)) return;
    send({kind: 'click', el: Object.assign(desc(t), {x: ev.clientX, y: ev.clientY}), url: location.href, t: Date.now()}); }, true);
  document.addEventListener('change', ev => flush(ev.target), true);
  document.addEventListener('blur', ev => flush(ev.target), true);
  document.addEventListener('keydown', ev => { if (ev.key === 'Enter') { flush(ev.target); send({kind: 'key', key: 'Enter', el: desc(ev.target), url: location.href, t: Date.now()}); } }, true);
  document.addEventListener('submit', ev => { for (const e of ev.target.querySelectorAll('input,select,textarea')) flush(e); }, true);
  window.addEventListener('pagehide', () => flush(document.activeElement), true);
})();"""


def recorder_start(page) -> list[dict]:
    """Record what is done in this browser (clicks, typed values, Enter). Returns the live list of events."""
    ctx = page.context
    events = getattr(ctx, "_aq_rec_events", None)
    if events is None:
        events = []
        ctx._aq_rec_events = events

        def on_event(_source, ev):
            ctx._aq_rec_events.append(ev)
        ctx.expose_binding("__aqRec", on_event)
        ctx.add_init_script(RECORDER_JS)
    try:
        page.evaluate(RECORDER_JS)
    except Exception:  # noqa: BLE001
        pass
    return events


def recorder_flush(page) -> None:
    try:
        page.evaluate("() => { const a = document.activeElement; if (a && a.blur) a.blur(); }")
        page.wait_for_timeout(150)
    except Exception:  # noqa: BLE001
        pass
