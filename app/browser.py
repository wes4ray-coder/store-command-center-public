"""Store-native browser automation via the Chrome DevTools Protocol.

Drives a real, persistent-profile Chrome (headed by default so you can log into
marketplaces once and see what's happening). Replaces the OpenClaw browser dependency
for resale posting. Requires `websocket-client` + a Chrome/Chromium binary.
"""
import json
import time
import base64
import shutil
import threading
import subprocess
from pathlib import Path

import httpx
import websocket  # websocket-client

try:
    from config import CHROME_BIN, DATA_DIR
except Exception:
    CHROME_BIN = "google-chrome"
    DATA_DIR = Path(__file__).resolve().parent.parent

PROFILE_DIR = DATA_DIR / "browser-profile"
DEBUG_PORT = 9222
_BASE = f"http://127.0.0.1:{DEBUG_PORT}"


def _chrome_bin():
    for b in (CHROME_BIN, "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(b)
        if p:
            return p
    return None


class Tab:
    """A CDP session bound to one page target."""
    def __init__(self, ws_url: str):
        self._ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
        self._id = 0
        self._lock = threading.Lock()
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("DOM.enable")

    def cmd(self, method: str, params: dict = None, timeout: float = 60):
        with self._lock:
            self._id += 1
            mid = self._id
            self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            self._ws.settimeout(timeout)
            while True:
                msg = json.loads(self._ws.recv())
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(msg["error"].get("message", str(msg["error"])))
                    return msg.get("result", {})
                # ignore events

    def navigate(self, url: str):
        self.cmd("Page.navigate", {"url": url})
        # give the page a moment to start loading
        time.sleep(2)

    def eval_js(self, expression: str, timeout: float = 30):
        r = self.cmd("Runtime.evaluate",
                     {"expression": expression, "returnByValue": True, "awaitPromise": True},
                     timeout=timeout)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("text", "JS error"))
        return r.get("result", {}).get("value")

    def type_into(self, css: str, text: str) -> bool:
        """Set a field's value in a React-safe way (native setter + input/change events)."""
        js = ("(function(sel,val){var el=document.querySelector(sel);if(!el)return false;"
              "try{el.focus();}catch(e){}"
              "if(el.getAttribute&&el.getAttribute('contenteditable')==='true'){el.innerText=val;}"
              "else{var p=Object.getPrototypeOf(el);var d=Object.getOwnPropertyDescriptor(p,'value');"
              "if(d&&d.set){d.set.call(el,val);}else{el.value=val;}}"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "el.dispatchEvent(new Event('blur',{bubbles:true}));return true;})(%s,%s)"
              % (json.dumps(css), json.dumps(text)))
        return bool(self.eval_js(js))

    def type_by_label(self, label: str, text: str) -> bool:
        """Fill an editable field found by its nearest visible label (for sites like
        Facebook where inputs have no stable id/name/aria)."""
        js = ("(function(label,val){var els=document.querySelectorAll("
              "'input[type=text],input[type=number],textarea,[contenteditable=\"true\"],[role=\"textbox\"]');"
              "for(var i=0;i<els.length;i++){var el=els[i],n=el,lbl='';"
              "for(var d=0;d<6&&n;d++){n=n.parentElement;if(!n)break;"
              "var t=(n.innerText||'').trim().split('\\n')[0];if(t&&t.length<40){lbl=t;break;}}"
              "if(lbl.toLowerCase()===label.toLowerCase()){try{el.focus();}catch(e){}"
              "if(el.getAttribute&&el.getAttribute('contenteditable')==='true'){el.innerText=val;}"
              "else{var p=Object.getPrototypeOf(el);var dd=Object.getOwnPropertyDescriptor(p,'value');"
              "if(dd&&dd.set){dd.set.call(el,val);}else{el.value=val;}}"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "el.dispatchEvent(new Event('blur',{bubbles:true}));return true;}}return false;})(%s,%s)"
              % (json.dumps(label), json.dumps(text)))
        return bool(self.eval_js(js))

    def fill_composer(self, text: str) -> bool:
        """Put a message into a chat composer on the current page (contenteditable /
        role=textbox / message textarea). Leaves sending (Enter) to the user."""
        js = ("(function(val){var sels=['div[contenteditable=\"true\"]','[role=\"textbox\"]',"
              "'textarea[aria-label*=\"essage\" i]','textarea[placeholder*=\"essage\" i]',"
              "'[aria-label=\"Message\"]','textarea'];var el=null;"
              "for(var i=0;i<sels.length&&!el;i++){var c=document.querySelector(sels[i]);"
              "if(c&&c.offsetParent!==null)el=c;}if(!el)return false;try{el.focus();}catch(e){}"
              "if(el.getAttribute&&el.getAttribute('contenteditable')==='true'){el.innerText=val;"
              "el.dispatchEvent(new InputEvent('input',{bubbles:true,data:val,inputType:'insertText'}));}"
              "else{var p=Object.getPrototypeOf(el);var d=Object.getOwnPropertyDescriptor(p,'value');"
              "if(d&&d.set){d.set.call(el,val);}else{el.value=val;}"
              "el.dispatchEvent(new Event('input',{bubbles:true}));}return true;})(%s)"
              % json.dumps(text))
        return bool(self.eval_js(js))

    def click(self, css: str) -> bool:
        js = ("(function(sel){var el=document.querySelector(sel);if(!el)return false;"
              "el.click();return true;})(%s)" % json.dumps(css))
        return bool(self.eval_js(js))

    def exists(self, css: str) -> bool:
        return bool(self.eval_js("!!document.querySelector(%s)" % json.dumps(css)))

    def dump_fields(self) -> list:
        """Inspect the page's form controls — used to discover selectors on a real page."""
        js = ("JSON.stringify([].slice.call(document.querySelectorAll("
              "'input,textarea,select,[contenteditable=\"true\"],[role=textbox],[role=combobox],[role=button],button'))"
              ".slice(0,120).map(function(e){return {tag:e.tagName,type:e.type||'',name:e.name||'',"
              "id:e.id||'',ph:e.placeholder||'',aria:(e.getAttribute&&e.getAttribute('aria-label'))||'',"
              "text:(e.innerText||'').slice(0,40)};}))")
        raw = self.eval_js(js)
        try:
            return json.loads(raw)
        except Exception:
            return []

    def upload_files(self, css_selector: str, file_paths: list) -> bool:
        """Set files on a matching <input type=file> via CDP."""
        doc = self.cmd("DOM.getDocument", {"depth": -1})
        root = doc["root"]["nodeId"]
        res = self.cmd("DOM.querySelector", {"nodeId": root, "selector": css_selector})
        node = res.get("nodeId")
        if not node:
            return False
        self.cmd("DOM.setFileInputFiles", {"files": file_paths, "nodeId": node})
        return True

    def screenshot(self) -> str:
        r = self.cmd("Page.captureScreenshot", {"format": "png"})
        return r.get("data", "")   # base64

    def url(self) -> str:
        try:
            return self.eval_js("location.href") or ""
        except Exception:
            return ""

    def page_signal(self) -> dict:
        """Best-effort read of what page we're actually on, so callers never operate
        blind. Detects login walls (redirect to /login, a visible password field, or
        obvious 'log in' text) and whether the page even has fillable fields."""
        js = ("(function(){var o={url:location.href,title:document.title||''};"
              "var u=location.href.toLowerCase();"
              "var pw=document.querySelector('input[type=password]');"
              "o.has_password=!!(pw&&pw.offsetParent!==null);"
              "o.login_url=/(login|checkpoint|signin|\\/auth|account\\/login|two_step)/.test(u);"
              "var bt=(document.body?document.body.innerText:'')||'';"
              "o.login_text=/(log in to|sign in to|enter your password|log into facebook)/i.test(bt.slice(0,4000));"
              "o.fields=document.querySelectorAll('input[type=text],input[type=number],textarea,"
              "[contenteditable=\"true\"],[role=\"textbox\"]').length;"
              "o.body_len=bt.length;return o;})()")
        try:
            sig = self.eval_js(js) or {}
        except Exception:
            sig = {}
        sig["needs_login"] = bool(sig.get("has_password") or sig.get("login_url") or sig.get("login_text"))
        return sig

    def close(self):
        try:
            self._ws.close()
        except Exception:
            pass


class Browser:
    def __init__(self):
        self._proc = None
        self._tab = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        try:
            httpx.get(f"{_BASE}/json/version", timeout=2)
            return True
        except Exception:
            return False

    def _clear_session(self):
        """Wipe Chrome's saved tab/session state so a fresh launch never RESTORES stale
        pages. Without this the automation profile would reopen whatever was left from a
        previous run — e.g. a half-finished Facebook Marketplace login/post that stalled
        at FB's 2FA wall — making it look like a tab keeps popping up "on a schedule".
        This browser is controlled per-request via CDP, so it should always start clean."""
        import shutil, json
        d = PROFILE_DIR / "Default"
        try:
            shutil.rmtree(d / "Sessions", ignore_errors=True)
            for name in ("Current Session", "Last Session", "Current Tabs", "Last Tabs"):
                (d / name).unlink(missing_ok=True)
            prefs = d / "Preferences"
            if prefs.exists():
                p = json.loads(prefs.read_text())
                prof = p.setdefault("profile", {})
                prof["exit_type"] = "Normal"          # no crash-restore prompt
                prof["exited_cleanly"] = True
                p.setdefault("session", {})["restore_on_startup"] = 5   # 5 = new tab page, never restore
                prefs.write_text(json.dumps(p))
        except Exception:
            pass

    def launch(self, headless: bool = False):
        with self._lock:
            if self.is_running():
                return
            binp = _chrome_bin()
            if not binp:
                raise RuntimeError("Chrome/Chromium not found (set STORE_CHROME_BIN)")
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._clear_session()   # never restore stale tabs (see _clear_session)
            args = [binp, f"--remote-debugging-port={DEBUG_PORT}",
                    f"--user-data-dir={PROFILE_DIR}", "--remote-allow-origins=*",
                    "--no-first-run", "--no-default-browser-check", "--disable-gpu",
                    "--hide-crash-restore-bubble", "--no-sandbox", "--disable-features=Translate"]
            if headless:
                args.append("--headless=new")
            self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(40):
                if self.is_running():
                    return
                time.sleep(0.5)
            raise RuntimeError("Chrome did not start (no display? try headless)")

    def _new_ws_tab(self, url: str) -> Tab:
        r = httpx.put(f"{_BASE}/json/new?{url}", timeout=10)
        data = r.json()
        return Tab(data["webSocketDebuggerUrl"])

    def open(self, url: str, headless: bool = False) -> Tab:
        """Ensure Chrome is up and open `url` in a (reused) working tab."""
        self.launch(headless=headless)
        with self._lock:
            if self._tab is None:
                self._tab = self._new_ws_tab(url)
            else:
                try:
                    self._tab.navigate(url)
                except Exception:
                    self._tab = self._new_ws_tab(url)
            return self._tab

    def status(self) -> dict:
        running = self.is_running()
        out = {"running": running, "chrome": bool(_chrome_bin()), "profile": str(PROFILE_DIR)}
        if running:
            try:
                out["current_url"] = self._tab.url() if self._tab else None
            except Exception:
                out["current_url"] = None
        return out

    def screenshot_b64(self) -> str:
        if not self._tab:
            raise RuntimeError("No open tab")
        return self._tab.screenshot()

    def quit(self):
        with self._lock:
            if self._tab:
                self._tab.close()
                self._tab = None
            if self._proc:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                self._proc = None

    def reset(self) -> dict:
        """Recover from a Chrome that didn't exit cleanly: kill any process still using
        our profile, then delete the stale Singleton* lock files that block relaunch."""
        self.quit()
        # Kill orphaned Chrome bound to OUR profile only (never the user's other Chrome).
        try:
            subprocess.run(["pkill", "-f", f"--user-data-dir={PROFILE_DIR}"], timeout=10)
        except Exception:
            pass
        time.sleep(1)
        removed = []
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            p = PROFILE_DIR / name
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
                    removed.append(name)
            except Exception:
                pass
        return {"ok": True, "killed_profile_chrome": True, "removed_locks": removed,
                "running": self.is_running()}


browser = Browser()
