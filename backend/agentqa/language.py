"""English first: every agent switches a portal to English before it reads or tests it.

Many government portals open in the state language (Malayalam, Hindi, Tamil...). The SRS, the test cases and the
expected results are in English, so a page in another language would make every comparison fail. Before working on
a page, the agents check it (the share of Latin letters in the visible text, then the page's lang attribute). When it
is not English they look for the switch the way a person would: a link or button called English / ENG / EN (or the
English word written in an Indian script), a link whose address carries lang=en, or an English option in a language
drop-down. What worked is remembered per application (.agentqa/language.json) and handed to the generated tests, so
they switch the same way. When nothing fits, AgentQA asks the person once per application.

Crawlers never follow a switch to another language (is_switch).

project.yaml:  language: {target: en, switch: true}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agentqa import live
from agentqa.util import warn

ENGLISH_WORDS = ("english", "eng", "en", "in english", "english version", "switch to english", "view in english",
                 "ഇംഗ്ലീഷ്", "अंग्रेज़ी", "अंग्रेजी", "इंग्लिश", "ఇంగ్లీష్", "ஆங்கிலம்", "ಇಂಗ್ಲಿಷ್", "ইংরেজি", "ଇଂରାଜୀ",
                 "અંગ્રેજી", "ਅੰਗਰੇਜ਼ੀ", "انگریزی")
LANG_NAMES = re.compile(r"^\s*(english|eng|en|hindi|हिन्दी|हिंदी|malayalam|മലയാളം|ml|tamil|தமிழ்|telugu|తెలుగు|kannada|"
                        r"ಕನ್ನಡ|bengali|বাংলা|odia|ଓଡ଼ିଆ|marathi|मराठी|gujarati|ગુજરાતી|punjabi|ਪੰਜਾਬੀ|urdu|اردو|"
                        r"assamese|অসমীয়া|ഇംഗ്ലീഷ്|अंग्रेज़ी|अंग्रेजी)\s*$", re.I)
LANG_HREF = re.compile(r"([?&](lang|language|locale|hl|lng)=[a-z]{2}\b|/(lang|language|locale)/[a-z]{2}\b|/set-?lang)", re.I)

DETECT_JS = r"""() => {
  const text = (document.body ? document.body.innerText : '').slice(0, 5000);
  const letters = (text.match(/\p{L}/gu) || []).length;
  const latin = (text.match(/[A-Za-z]/g) || []).length;
  return {lang: (document.documentElement.getAttribute('lang') || '').toLowerCase(), letters, ratio: letters ? latin / letters : 1};
}"""

FIND_JS = r"""(words) => {
  const want = new Set(words.map(w => w.toLowerCase()));
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const clicks = [], selects = [];
  let n = 0;
  for (const e of document.querySelectorAll('a, button, [role=button], [role=menuitem], [role=option], [role=link], input[type=button], input[type=submit], [onclick], li, span')) {
    if (!vis(e)) continue;
    const t = (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
    const lang = (e.getAttribute('lang') || e.getAttribute('hreflang') || e.dataset.lang || '').toLowerCase();
    const href = e.getAttribute('href') || '';
    let score = 0;
    if (want.has(t.toLowerCase())) score = 3;
    else if (/^en(-|_|$)/.test(lang) && t.length < 25) score = 2;
    else if (/[?&](lang|language|locale|hl|lng)=en\b|\/(lang|language|locale)\/en\b|\/en\/?$/i.test(href)) score = 2;
    if (!score) continue;
    if (/^(SPAN|LI)$/.test(e.tagName) && e.querySelector('a, button')) continue;
    const id = 'L' + (n++); e.setAttribute('data-aq-lang', id);
    clicks.push({id, text: t, score, tag: e.tagName.toLowerCase()});
  }
  for (const s of document.querySelectorAll('select')) {
    if (!vis(s)) continue;
    const o = [...s.options].find(o => want.has(o.text.trim().toLowerCase()) || /^en(-|_|$)/i.test(o.value));
    if (!o || s.selectedIndex === o.index) continue;
    const id = 'L' + (n++); s.setAttribute('data-aq-lang', id);
    selects.push({id, value: o.value, text: o.text.trim()});
  }
  clicks.sort((a, b) => b.score - a.score);
  return {clicks, selects};
}"""

_ASKED: set[str] = set()


def is_english(info: dict, target: str = "en") -> bool:
    lang = info.get("lang") or ""
    ratio = info.get("ratio", 1)
    if lang and not lang.startswith(target) and ratio < 0.97:
        return False                 # the page says it is in another language and shows some of it
    if info.get("letters", 0) >= 40:
        return ratio >= 0.75
    return not lang or lang.startswith(target)


def is_switch(text: str = "", href: str = "") -> bool:
    """A link or button that changes the portal's language: crawlers must not follow it."""
    return bool(LANG_NAMES.match(text or "")) or bool(LANG_HREF.search(href or ""))


def _cfg(project) -> dict:
    c = (project.cfg.get("language") or {}) if project is not None else {}
    return {"target": c.get("target", "en"), "switch": c.get("switch", True)}


def _store(project) -> Path:
    return Path(project.state) / "language.json"


def learned(project) -> dict:
    try:
        return json.loads(_store(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _learn(project, app: str, how: dict) -> None:
    data = learned(project)
    if data.get(app) != how:
        data[app] = how
        _store(project).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def detect(page) -> dict:
    try:
        return page.evaluate(DETECT_JS)
    except Exception:  # noqa: BLE001
        return {"lang": "", "letters": 0, "ratio": 1}


def _settle(page) -> None:
    try:
        page.wait_for_load_state("load", timeout=10000)
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass


def _try(page, how: dict) -> bool:
    found = page.evaluate(FIND_JS, list(ENGLISH_WORDS))
    if how.get("select"):
        s = next((x for x in found["selects"]), None)
        if s:
            page.locator(f'[data-aq-lang="{s["id"]}"]').select_option(value=s["value"])
            _settle(page)
            return True
        return False
    want = (how.get("click") or "").lower()
    c = next((x for x in found["clicks"] if x["text"].lower() == want), None) if want else None
    if c is None and not want:
        c = found["clicks"][0] if found["clicks"] else None
    if c is None:
        return False
    page.locator(f'[data-aq-lang="{c["id"]}"]').first.click(timeout=8000)
    _settle(page)
    return True


def ensure_english(page, project, *, agent: str = "explorer", role: str | None = None, ask: bool = True) -> bool:
    """Switch the page to English if it is not. True when the page is (now) in English."""
    cfg = _cfg(project)
    if not cfg["switch"]:
        return True
    info = detect(page)
    if is_english(info, cfg["target"]):
        return True
    before = page.url
    try:
        app = project.split_path(project.rel(before))[0]
    except Exception:  # noqa: BLE001
        app = "main"
    tries = [learned(project).get(app)] if learned(project).get(app) else []
    tries += [{"click": ""}, {"select": True}]
    for how in tries:
        try:
            if not _try(page, how):
                continue
        except Exception as exc:  # noqa: BLE001
            warn(f"[language] could not use the language switch on {before}: {exc.__class__.__name__}")
            continue
        if is_english(detect(page), cfg["target"]):
            done = how
            if how.get("click") == "":
                # remember the words of the control that worked
                found = page.evaluate(FIND_JS, list(ENGLISH_WORDS))
                done = {"click": found["clicks"][0]["text"]} if found["clicks"] else {"click": "English"}
            _learn(project, app, done)
            _back(page, before)
            live.emit(agent, "action", f"The page was not in English ({info.get('lang') or 'another script'}); switched "
                      f"it to English" + (f" with '{done.get('click')}'" if done.get("click") else " in the language list"),
                      role=role)
            return True
    if ask and app not in _ASKED:
        _ASKED.add(app)
        from agentqa import assist
        ans = assist.ask(project, "navigate", "This page is not in English. Click the switch that shows it in English.",
                         role=role, agent=agent, page=page,
                         hint="AgentQA tests in English, the language of the SRS. Click the language switch (it may be "
                              "an icon or a drop-down), or skip to test in the portal's language.")
        if ans and ("x" in ans or ans.get("text")):
            try:
                if "x" in ans:
                    text = page.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); const t = e && (e.closest('a,button,[role=button],[role=menuitem],[onclick],li,span') || e);"
                                         " return t ? (t.innerText || t.value || t.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 40) : ''; }",
                                         [float(ans["x"]), float(ans["y"])])
                    page.mouse.click(float(ans["x"]), float(ans["y"]))
                else:
                    text = ans["text"].strip()
                    page.get_by_text(text, exact=True).first.click(timeout=8000)
                _settle(page)
                if is_english(detect(page), cfg["target"]):
                    if text:
                        _learn(project, app, {"click": text})
                    _back(page, before)
                    return True
            except Exception as exc:  # noqa: BLE001
                warn(f"[language] the switch you showed did not work: {exc.__class__.__name__}")
    live.emit(agent, "observe", "The page is not in English and no language switch was found: testing it as it is",
              role=role, level="warn")
    return False


def _back(page, before: str) -> None:
    """A switch may land on another page (a home page): go back to where the agent was."""
    try:
        if page.url.split("#")[0].split("?")[0] != before.split("#")[0].split("?")[0]:
            page.goto(before, wait_until="load")
    except Exception:  # noqa: BLE001
        pass


def settings(project) -> dict:
    """What the generated tests need: the target language and the switch that worked per application."""
    c = _cfg(project)
    return {"target": c["target"], "switch": bool(c["switch"]), "learned": learned(project), "words": list(ENGLISH_WORDS)}
