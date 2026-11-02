(h) => {
  // Given a form control that is hidden (type=hidden or not displayed), find the custom widget the user
  // actually operates: a date picker on a read-only input, a rich text editor, a listbox of options or a
  // combobox. Many UI libraries keep the real value in such a hidden control and sync it from the widget.
  const vis = e => !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)
    && getComputedStyle(e).visibility !== 'hidden';
  const txt = el => (el ? (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ') : '');
  const labelRaw = el => {
    if (!el) return '';
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return txt(l); }
    const wrap = el.closest('label'); if (wrap) return txt(wrap);
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const by = el.getAttribute('aria-labelledby');
    if (by) return by.split(' ').map(i => txt(document.getElementById(i))).join(' ').trim();
    return '';
  };
  const labelFor = el => labelRaw(el).replace(/\s*[(\[](optional|required|mandatory)[)\]]\s*$/i, '').replace(/\s*\*\s*$/, '').trim();
  if (!h || (vis(h) && (h.type || '').toLowerCase() !== 'hidden')) return null;
  const SEL = '[contenteditable=""],[contenteditable="true"],[role=textbox],[role=listbox],[role=combobox],'
    + 'input:not([type=hidden]):not([name]),input[readonly]:not([type=hidden])';
  let c = h.parentElement, ui = null;
  for (let i = 0; i < 4 && c && c.tagName !== 'FORM' && c !== document.body; i++, c = c.parentElement) {
    const cands = [...c.querySelectorAll(SEL)].filter(vis);
    if (cands.length === 1) { ui = cands[0]; break; }
    if (cands.length > 1) break;
  }
  if (!ui) return null;
  const role = ui.getAttribute('role');
  let kind = (ui.isContentEditable || role === 'textbox') ? 'richtext'
    : role === 'listbox' ? 'listbox' : role === 'combobox' ? 'combobox' : 'text';
  const ph = ui.getAttribute('placeholder') || '';
  const label = labelFor(ui) || labelFor(h) || '';
  const hint = `${ui.className || ''} ${ui.id || ''} ${label}`;
  if (kind === 'text' && (/\b(dd|mm|yyyy|yy)\b/i.test(ph) || /date|picker|calendar|dob/i.test(hint)
      || ui.getAttribute('aria-haspopup') === 'dialog')) kind = 'datepicker';
  if (!ui.dataset.aqUi) ui.dataset.aqUi = 'w' + Math.random().toString(36).slice(2, 9);
  const opts = role === 'listbox' ? [...ui.querySelectorAll('[role=option]')]
    .map(o => ({value: o.dataset.value || o.getAttribute('value') || txt(o), text: txt(o)})) : null;
  return {
    kind, ui: ui.dataset.aqUi, label, placeholder: ph,
    required: !!ui.required || ui.getAttribute('aria-required') === 'true',
    options: opts, multiple: ui.getAttribute('aria-multiselectable') === 'true' || !!h.multiple,
    maxlength: ui.getAttribute('maxlength') || ui.getAttribute('data-maxlength') || null,
  };
}
