"""The web UI's embedded JavaScript is plain text inside a Python string --
no build step, no linter -- so a Python string-escaping mistake can
silently corrupt it. Confirmed live 2026-07-29: `\\'` inside the JS source
is a *recognized* Python escape sequence, so Python quietly consumes the
backslash before the JS ever sees it, leaving a bare `'` that terminated a
JS string literal early mid-array and took out every function declared
after it in the same <script> tag -- the wizard's Back/Next buttons
silently stopped working with no server-side signal at all.

This extracts the actual served script and executes it in a real JS engine
(quickjs) against a minimal DOM stub, to catch exactly that class of bug
automatically -- something none of the HTTP-level tests in test_web_ui.py
can see, since they only assert on response text, never execute it.
"""
from __future__ import annotations

import re

import quickjs

from cedar_goto.web.ui import _PAGE

_DOM_STUB = """
function makeEl() {
  return {
    style: {},
    children: [],
    appendChild: function(c) { this.children.push(c); },
    addEventListener: function() {},
    setAttribute: function() {},
    set innerHTML(v) { this.children = []; },
    get innerHTML() { return ''; },
  };
}
function makeClassList() {
  var set = {};
  return {
    add: function(c) { set[c] = true; },
    remove: function(c) { delete set[c]; },
    contains: function(c) { return !!set[c]; },
    toggle: function(c) {
      if (set[c]) { delete set[c]; return false; }
      set[c] = true; return true;
    },
  };
}
var document = {
  documentElement: { classList: makeClassList() },
  getElementById: function(id) { return makeEl(); },
  createElement: function(tag) { return makeEl(); },
  addEventListener: function() {},
  visibilityState: 'visible',
};
var EventSource = function(url) { this.url = url; this.onmessage = null; };
EventSource.prototype.close = function() {};
var fetch = function() { return Promise.resolve({ json: function() { return Promise.resolve({}); } }); };
var localStorage = {
  _data: {},
  getItem: function(k) { return Object.prototype.hasOwnProperty.call(this._data, k) ? this._data[k] : null; },
  setItem: function(k, v) { this._data[k] = String(v); },
};
"""


def _extract_script(page: str) -> str:
    # Two <script> blocks now: the head's early night-mode-class script (runs
    # before <body> parses, to avoid a flash of full brightness before
    # switching to red) and the main body script. Concatenating both keeps
    # this test's escaping-bug coverage (see module docstring) on the new one
    # too, rather than silently only checking the first match.
    blocks = re.findall(r"<script>\n(.*?)\n</script>", page, re.S)
    assert blocks, "no <script> block found in the rendered page"
    return "\n\n".join(blocks)


def test_page_script_is_valid_javascript_and_defines_the_wizard_handlers():
    # __CEDAR_UI_LINK__/__CEDAR_SAME_HOST__ are normally substituted by
    # ui.index() at request time (web/ui.py) -- stand in for that here, same
    # as a "mock" backend (no real cedar-server, so no UI link and no local
    # systemd unit to control).
    js = _extract_script(
        _PAGE.replace("__CEDAR_UI_LINK__", "null").replace("__CEDAR_SAME_HOST__", "false")
    )
    ctx = quickjs.Context()
    ctx.eval(_DOM_STUB + js)
    assert ctx.eval("typeof wizardNext") == "function"
    assert ctx.eval("typeof wizardBack") == "function"
    assert ctx.eval("typeof post") == "function"
    assert ctx.eval("typeof formatAge") == "function"
    assert ctx.eval("typeof refreshLog") == "function"
    assert ctx.eval("typeof renderStatus") == "function"
    assert ctx.eval("typeof connectEvents") == "function"
