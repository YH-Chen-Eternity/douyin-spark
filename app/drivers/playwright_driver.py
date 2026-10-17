"""基于 Playwright 持久上下文的抖音驱动。

要点：
1. 每个账号一个独立浏览器 profile 目录，Cookie/登录态天然隔离；
2. 每个账号一个独立工作线程 —— Playwright 的同步 API 不是线程安全的，
   所有浏览器操作都必须在同一个线程里执行，这里用命令队列保证；
3. 长时间空闲自动关闭浏览器，NAS 内存很宝贵。
"""
import queue
import re
import shutil
import threading
import time
from pathlib import Path

from app.config import (
    BROWSER_ARGS,
    HEADLESS,
    LOGIN_TIMEOUT,
    OP_TIMEOUT,
    TMP_DIR,
    TZ,
    USER_AGENT,
)
from app.drivers.base import BaseDriver, DriverError, LoginResult
from app.drivers.selectors import as_list, load_selectors

_IDLE_SECONDS = 600

# 新版私信页 /chat 的加载预算（秒）。
# NAS 上打开 /chat 到会话列表渲染出来要十几秒，冷启动更慢。
CHAT_POLL_TIMEOUT = 45

# 新版私信页地址：2026-10 抖音网页版改版后，私信从首页弹窗迁移到独立页面。
CHAT_URL = "https://www.douyin.com/chat"

# 在会话列表里等目标好友渲染出来的预算（秒）。
# 会话列表是异步 + 虚拟滚动，列表出现 ≠ 目标好友已经渲染出来。
FIND_TIMEOUT = 25

# 等登录二维码真正渲染出来的上限（秒）。
# NAS 上抖音首页 + 登录弹窗实测要 40~60 秒才出二维码，给足预算。
QR_WAIT_TIMEOUT = 90


def _normalize(text):
    """抖音昵称里混着不间断空格(\\u00a0)，统一空白后再做匹配。"""
    return re.sub(r"[\s\u00a0]+", " ", str(text or "")).strip()


# 容器/Linux 环境下抖音前端不下发 im 入口与组件，需伪装 Windows 指纹
# （页面加载前注入，见 AccountWorker._ensure_browser 的 add_init_script）。
PLATFORM_SPOOF_JS = """
Object.defineProperty(navigator, 'platform', { get: () => 'Win32', configurable: true });
try {
  const uad = navigator.userAgentData;
  if (uad) {
    Object.defineProperty(uad, 'platform', { get: () => 'Windows', configurable: true });
    Object.defineProperty(uad, 'mobile', { get: () => false, configurable: true });
  }
} catch (e) {}
try {
  Object.defineProperty(NavigatorUAData.prototype, 'platform', { get: () => 'Windows', configurable: true });
} catch (e) {}
"""

# 登录二维码「到底渲染出来没有」的探测脚本。
# 抖音登录弹窗是异步渲染的：容器先出现、二维码图片（base64）几秒后才填进去，
# 而且弹窗 DOM 会被反复重建。所以既不能只判断容器可见，也不能用 locator.screenshot
# （弹窗重建时 locator 会一直等元素直到超时）。
# 返回 {loaded, x, y, width, height, sel}；loaded=False 表示还在加载。
QR_BOX_JS = r"""
() => {
  const cands = [
    '#animate_qrcode_container img',
    '#douyin_login_comp_scan_code img',
    '#douyin-login-new-id img',
    'img[src^="data:image"]',
  ];
  for (const sel of cands) {
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      if (r.width < 80 || r.height < 80) continue;
      const src = el.currentSrc || el.src || '';
      if (el.complete && el.naturalWidth >= 80 && src.indexOf('data:image') === 0) {
        return {loaded: true, x: r.x, y: r.y, width: r.width, height: r.height, sel: sel};
      }
    }
  }
  for (const sel of ['#animate_qrcode_container', '#douyin_login_comp_scan_code']) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.width >= 80 && r.height >= 80) {
      return {loaded: false, x: r.x, y: r.y, width: r.width, height: r.height, sel: sel};
    }
  }
  return null;
}
"""


class AccountWorker(threading.Thread):
    def __init__(self, account_id, profile_dir):
        super().__init__(daemon=True, name=f"acct-worker-{account_id}")
        self.account_id = account_id
        self.profile_dir = str(profile_dir)
        self.selectors = load_selectors()

        self._q = queue.Queue()
        self._stop = threading.Event()
        self._last_active = time.time()
        self._lock = threading.Lock()

        self.pw = None
        self.context = None
        self.page = None

    # ---------------- 外部接口 ----------------
    def submit(self, op, timeout=OP_TIMEOUT, **kwargs):
        box = {}
        done = threading.Event()
        self._q.put((op, kwargs, box, done))
        if not done.wait(timeout):
            raise DriverError(f"操作超时（{timeout}s）：{op}")
        if box.get("error"):
            raise DriverError(box["error"])
        return box.get("result")

    def stop(self):
        self._stop.set()
        self.join(timeout=15)

    # ---------------- 线程主循环 ----------------
    def run(self):
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                if time.time() - self._last_active > _IDLE_SECONDS:
                    self._close_browser()
                continue
            op, kwargs, box, done = item
            try:
                handler = getattr(self, f"_op_{op}")
                box["result"] = handler(**kwargs)
            except Exception as exc:  # noqa: BLE001
                box["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                self._last_active = time.time()
                done.set()
        self._close_browser()

    # ---------------- 浏览器生命周期 ----------------
    def _ensure_browser(self):
        if self.page is not None:
            try:
                _ = self.page.url
                return
            except Exception:
                self._close_browser()

        # 清理上次异常退出可能残留的 Chromium profile 锁。
        # 否则新 Chromium 会认为 profile 被"另一进程/另一台机器"占用而拒绝启动。
        profile_dir = Path(self.profile_dir)
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_path = profile_dir / lock_name
            try:
                if lock_path.exists() or lock_path.is_symlink():
                    lock_path.unlink()
            except Exception:
                pass

        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()
        self.context = self.pw.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=HEADLESS,
            args=BROWSER_ARGS,
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id=TZ,
            ignore_https_errors=True,
        )
        try:
            self.context.add_init_script(PLATFORM_SPOOF_JS)
        except Exception:
            pass
        self.context.set_default_timeout(15000)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def _close_browser(self):
        for closer in (
            lambda: self.context.close(),
            lambda: self.pw.stop(),
        ):
            try:
                closer()
            except Exception:
                pass
        self.context = None
        self.page = None
        self.pw = None

    # ---------------- 通用工具 ----------------
    def _first_visible(self, page, candidates, timeout=3000):
        for selector in as_list(candidates):
            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=timeout)
                return locator
            except Exception:
                continue
        return None

    def _qr_box(self):
        """返回二维码区域坐标；loaded=False 表示登录弹窗在、二维码还没生成。"""
        try:
            return self.page.evaluate(QR_BOX_JS)
        except Exception:
            return None

    def _goto(self, url, wait=1.5):
        try:
            self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
        except Exception:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass
        time.sleep(wait)

    # ---------------- 私信页（新版 /chat） ----------------
    # 2026-10 抖音网页版改版：私信从首页弹窗（im-entry / im-dialog）搬到了独立的
    # /chat 页面（网址 https://www.douyin.com/chat），旧的选择器和“注入 im 模块再
    # 调用 openImConversation”的方案全部失效。这里改为直接操作 /chat：
    #   左侧 = 会话列表（[data-e2e='conversation-item']）
    #   右侧 = 聊天窗（输入框 [data-e2e='msg-input']，发送按钮 class 含 e2e-send-msg-btn）

    def _chat_ready(self):
        try:
            return bool(
                self.page.evaluate(
                    "() => !!document.querySelector(\"[data-e2e='conversation-item']\")"
                    " || !!document.querySelector(\"[data-e2e='msg-input']\")"
                )
            )
        except Exception:
            return False

    def _open_chat(self, attempts=2):
        """打开 /chat 私信页并等会话列表渲染出来，失败就整页重载再试。"""
        if self._chat_ready():
            return
        for attempt in range(attempts):
            self._goto(CHAT_URL, wait=2.0)
            deadline = time.time() + CHAT_POLL_TIMEOUT
            while time.time() < deadline:
                if self._chat_ready():
                    return
                time.sleep(1)
            status, _ = self._detect_login_state()
            if status != "success":
                raise DriverError("登录态已失效，请在界面上重新扫码登录")
            if attempt < attempts - 1:
                print("[chat] 会话列表未加载，重载重试", flush=True)
                time.sleep(1.5)
        raise DriverError("私信页面加载超时")

    def _conversation_locator(self):
        try:
            locator = self.page.locator("[data-e2e='conversation-item']")
            if locator.count() > 0:
                return locator
        except Exception:
            pass
        return None

    def _conversation_title_text(self, node):
        """取会话项里的昵称。会话项文本是多行的（昵称 / 时间 / 最后一条消息），
        必须只取标题元素的第一行，否则拉下来的名字会带时间或未读数。"""
        try:
            text = node.evaluate(
                "(el) => {"
                "  const t = el.querySelector(\"[class*='ConversationItemtitle']\");"
                "  const s = t ? (t.innerText || '') : (el.innerText || '');"
                "  return (s.split('\\n')[0] || '').trim();"
                "}"
            )
            if text:
                return text
        except Exception:
            pass
        for selector in as_list(self.selectors.get("friend_name")):
            try:
                text = node.locator(selector).first.inner_text(timeout=600)
                if text and text.strip():
                    return text.strip().split("\n")[0].strip()
            except Exception:
                continue
        try:
            lines = (node.inner_text() or "").split("\n")
            return lines[0].strip() if lines else ""
        except Exception:
            return ""

    def _find_conversation_index(self, locator, ref, nickname):
        """在会话项里按昵称找目标好友下标；找不到返回 None。"""
        nick_n = _normalize(nickname)
        ref_n = _normalize(ref)
        try:
            count = locator.count()
        except Exception:
            return None
        for index in range(count):
            try:
                name_n = _normalize(
                    self._conversation_title_text(locator.nth(index))
                )
            except Exception:
                continue
            if not name_n:
                continue
            if name_n == nick_n or name_n == ref_n:
                return index
            # 列表里长昵称可能被省略号截断，用前缀兜底
            for wanted in (nick_n, ref_n):
                if wanted and (name_n.startswith(wanted) or wanted.startswith(name_n)):
                    return index
        return None

    def _chat_pane_title(self):
        try:
            text = self.page.locator(
                "[class*='RightPanelHeadertitle']"
            ).first.inner_text(timeout=1500)
            return _normalize(text)
        except Exception:
            return ""

    def _chat_editor_exists(self):
        try:
            return bool(
                self.page.evaluate(
                    "() => !!document.querySelector("
                    "\"[data-e2e='msg-input'] div[contenteditable='true']\")"
                )
            )
        except Exception:
            return False

    def _scroll_conversation_list(self, step=900):
        """左侧会话列表是虚拟滚动，目标不在可视区时滚一下。"""
        try:
            box = self.page.locator(
                "[class*='conversationConversationListwrapper']"
            ).first.bounding_box()
            if not box:
                return
            self.page.mouse.move(
                box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            )
            self.page.mouse.wheel(0, step)
            time.sleep(0.8)
        except Exception:
            pass

    def _find_and_open_conversation(self, ref, nickname, timeout=FIND_TIMEOUT):
        """在左侧列表点开目标会话，并等右侧标题切到目标好友。"""
        target = _normalize(nickname) or _normalize(ref)
        deadline = time.time() + timeout
        scrolls = 0
        while time.time() < deadline:
            locator = self._conversation_locator()
            if locator is not None:
                index = self._find_conversation_index(locator, ref, nickname)
                if index is not None:
                    try:
                        locator.nth(index).click(timeout=3000)
                    except Exception:
                        pass
                    else:
                        wait_until = time.time() + 10
                        while time.time() < wait_until:
                            title = self._chat_pane_title()
                            if title and (
                                title == target
                                or target in title
                                or title in target
                            ):
                                return True
                            if not title and self._chat_editor_exists():
                                return True
                            time.sleep(0.5)
                elif scrolls < 6 and time.time() > deadline - timeout / 2:
                    self._scroll_conversation_list()
                    scrolls += 1
            time.sleep(0.8)
        return False

    def _cookies_hint_logged_in(self):
        try:
            names = {c.get("name") for c in self.context.cookies()}
        except Exception:
            return False
        for key in ("sessionid", "sessionid_ss", "sid_tt", "passport_auth_status"):
            if key in names:
                return True
        return False

    def _detect_login_state(self):
        """返回 (status, nickname)。status: success | pending"""
        if self._cookies_hint_logged_in():
            nickname = self._read_nickname()
            if nickname:
                return "success", nickname
            # Cookie 到位但 DOM 没渲染出来，去首页兜一次
            self._goto(self.selectors.get("login_url"), wait=2.0)
            nickname = self._read_nickname()
            if nickname:
                return "success", nickname

        # 未登录：先看是否还在登录面板（快），避免逐个遍历 logged_in_marker 浪费时间
        pending = self._first_visible(
            self.page, self.selectors.get("login_pending_marker"), timeout=1500
        )
        if pending is not None:
            return "pending", ""

        # 关键修复：cookie 里已有登录态且页面无登录弹窗 = 已登录。
        # 抖音会话以 cookie 为准，昵称选择器会随页面改版失效，不能作为唯一判据。
        if self._cookies_hint_logged_in():
            return "success", self._read_nickname() or ""

        # 兜底：再看是否已登录
        marker = self._first_visible(
            self.page, self.selectors.get("logged_in_marker"), timeout=1000
        )
        if marker is not None and self._cookies_hint_logged_in():
            return "success", self._read_nickname()

        return "pending", ""

    def _read_nickname(self):
        locator = self._first_visible(
            self.page, self.selectors.get("nickname"), timeout=1500
        )
        if locator is None:
            return ""
        try:
            return (locator.inner_text() or "").strip()[:64]
        except Exception:
            return ""

    # ---------------- 具体操作 ----------------
    def _op_start_login(self):
        self._ensure_browser()
        self._goto(self.selectors.get("login_url"), wait=1.5)

        # 抖音登录弹窗是自动弹出的，无需点击登录按钮。
        qr_path = TMP_DIR / f"qr_{self.account_id}.png"
        # 等二维码图片真正填充进来（弹窗先出、base64 图片后到，NAS 上整个过程 40~60s）
        box = self._wait_qr_box(timeout=QR_WAIT_TIMEOUT)

        if box is None or not box.get("loaded"):
            # 可能已经登录，或者弹窗没出。检查登录态。
            status, nickname = self._detect_login_state()
            if status == "success":
                return LoginResult("success", nickname=nickname).to_dict()

        try:
            self._screenshot_qr(box, qr_path)
        except Exception as exc:
            raise DriverError(f"二维码截图失败：{exc}")

        return LoginResult(
            "pending",
            qr_url=f"/files/qr_{self.account_id}.png?v={int(time.time())}",
        ).to_dict()

    def _wait_qr_box(self, timeout=QR_WAIT_TIMEOUT):
        """轮询等待二维码渲染完成，返回坐标；超时返回最后一次看到的区域。"""
        deadline = time.time() + timeout
        fallback = None
        while time.time() < deadline:
            box = self._qr_box()
            if box:
                if box.get("loaded"):
                    print(f"[qr] 二维码已渲染（{box.get('sel')}）", flush=True)
                    return box
                fallback = fallback or box
            time.sleep(0.5)
        print("[qr] 等二维码渲染超时", flush=True)
        return fallback

    def _screenshot_qr(self, box, qr_path):
        """把二维码区域截下来给用户扫。

        不要用 locator.screenshot()：抖音登录弹窗会反复重建 DOM，locator 在
        检测到可见之后随时可能 detach，screenshot 就一直等元素直到 15 秒超时
        —— 2026-10 扫码登录失败就是这么来的。这里用 page.screenshot(clip=坐标)，
        坐标来自一次 evaluate；失败就重新取坐标重试，最后退回整页截图。
        """
        errors = []
        for _ in range(3):
            try:
                if box and box.get("width") and box.get("height"):
                    self.page.screenshot(path=str(qr_path), clip=box, timeout=15000)
                else:
                    self.page.screenshot(path=str(qr_path), timeout=15000)
                if qr_path.exists() and qr_path.stat().st_size > 1024:
                    return
                errors.append("截图内容为空")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc)[:200])
            time.sleep(0.5)
            box = self._qr_box() or box
        raise DriverError("；".join(errors) or "截图失败")


    def _op_query_login(self, timeout=LOGIN_TIMEOUT):
        if self.page is None:
            return LoginResult("expired", message="登录会话已失效，请重新扫码").to_dict()
        deadline = time.time() + min(timeout, 30)
        while time.time() < deadline:
            status, nickname = self._detect_login_state()
            if status == "success":
                return LoginResult("success", nickname=nickname).to_dict()
            time.sleep(2)
        return LoginResult("pending", message="等待扫码中").to_dict()

    def _op_cancel_login(self):
        try:
            if self.page is not None:
                self.page.goto("about:blank", timeout=5000)
        except Exception:
            pass
        return {"status": "cancelled"}

    def _op_verify(self):
        self._ensure_browser()
        self._goto(self.selectors.get("login_url"), wait=3.0)
        status, nickname = self._detect_login_state()
        if status == "success":
            return LoginResult("success", nickname=nickname).to_dict()
        return LoginResult("expired", message="登录态已失效，请重新扫码").to_dict()

    def _op_import_cookies(self, cookie_text=""):
        self._ensure_browser()
        cookies = []
        for chunk in cookie_text.split(";"):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            name, _, value = chunk.partition("=")
            name, value = name.strip(), value.strip()
            if not name:
                continue
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".douyin.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": False,
                }
            )
        if not cookies:
            raise DriverError("Cookie 内容为空或格式不正确")
        try:
            self.context.clear_cookies()
            self.context.add_cookies(cookies)
        except Exception as exc:
            raise DriverError(f"写入 Cookie 失败：{exc}")

        self._goto(self.selectors.get("login_url"), wait=3.0)
        status, nickname = self._detect_login_state()
        if status == "success":
            return LoginResult("success", nickname=nickname).to_dict()
        return LoginResult("expired", message="Cookie 无效或已过期").to_dict()

    def _op_sms_send_code(self, phone=""):
        """验证码登录：填手机号并发送验证码。"""
        phone = str(phone or "").strip()
        if not phone:
            raise DriverError("手机号不能为空")

        self._ensure_browser()
        self._goto(self.selectors.get("login_url"), wait=1.5)

        # 切到验证码登录 tab
        self._switch_sms_tab()

        # 填手机号
        phone_input = None
        for selector in as_list(self.selectors.get("sms_phone_input")):
            try:
                loc = self.page.locator(selector).first
                loc.wait_for(state="visible", timeout=3000)
                phone_input = loc
                break
            except Exception:
                continue
        if phone_input is None:
            raise DriverError("没有找到手机号输入框，页面可能已改版")
        phone_input.click()
        phone_input.fill(phone)

        # 点「获取验证码」
        clicked = False
        for selector in as_list(self.selectors.get("sms_send_button")):
            try:
                self.page.get_by_text("获取验证码", exact=False).first.click(timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise DriverError("没有找到「获取验证码」按钮")

        return {"status": "code_sent", "message": "验证码已发送，请查收短信"}

    def _switch_sms_tab(self):
        deadline = time.time() + 45
        while time.time() < deadline:
            for selector in as_list(self.selectors.get("sms_tab")):
                try:
                    loc = self.page.locator(selector).first
                    if loc.count() > 0 and loc.is_visible():
                        loc.click(timeout=2000)
                        time.sleep(1.0)
                        return True
                except Exception:
                    continue
            time.sleep(0.5)
        return False

    def _op_sms_verify(self, code=""):
        """验证码登录：填入验证码并提交，成功后 Cookie 自动落盘。"""
        code = str(code or "").strip()
        if not code:
            raise DriverError("验证码不能为空")

        self._ensure_browser()

        # 填验证码
        code_input = None
        for selector in as_list(self.selectors.get("sms_code_input")):
            try:
                loc = self.page.locator(selector).first
                loc.wait_for(state="visible", timeout=3000)
                code_input = loc
                break
            except Exception:
                continue
        if code_input is None:
            raise DriverError("没有找到验证码输入框")

        # 勾选协议（如果有未勾选的协议）
        try:
            for selector in as_list(self.selectors.get("sms_agreement")):
                try:
                    el = self.page.locator(selector).first
                    if el.count() > 0:
                        checked = el.get_attribute("aria-checked") or el.is_checked()
                        if not checked:
                            el.click(timeout=1000)
                            break
                except Exception:
                    continue
        except Exception:
            pass

        code_input.click()
        code_input.fill(code)

        # 点「登录」
        clicked = False
        for selector in as_list(self.selectors.get("sms_login_button")):
            try:
                self.page.locator(selector).first.click(timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            self.page.get_by_text("登录", exact=True).first.click(timeout=3000)

        # 等待登录结果（登录成功后 Cookie 自动保存到 profile，即"自动抓 Cookie"）
        deadline = time.time() + 25
        while time.time() < deadline:
            status, nickname = self._detect_login_state()
            if status == "success":
                return LoginResult("success", nickname=nickname).to_dict()
            time.sleep(1.5)
        return LoginResult("pending", message="登录状态未确认，请稍后点「校验登录态」")

    def _op_fetch_friends(self):
        self._ensure_browser()
        self._open_chat()

        locator = self._conversation_locator()
        if locator is None:
            for _ in range(3):
                self._scroll_conversation_list()
                locator = self._conversation_locator()
                if locator is not None:
                    break
        if locator is None:
            raise DriverError(
                "没有抓到好友列表。可能未登录、页面结构已改版。"
                "可在 /data/selectors.json 覆盖 friend_item / friend_name 后重试。"
            )

        result = []
        total = min(locator.count(), 200)
        for index in range(total):
            try:
                node = locator.nth(index)
                name = self._conversation_title_text(node)
                if not name:
                    continue
                avatar = ""
                try:
                    avatar = node.locator("img").first.get_attribute("src") or ""
                except Exception:
                    pass
                result.append(
                    {
                        "ref": name[:64],
                        "nickname": name[:64],
                        "avatar": avatar[:512],
                    }
                )
            except Exception:
                continue

        if not result:
            raise DriverError("好友列表为空，请确认已登录且存在会话记录")
        return result

    def _op_warmup(self):
        """任务开始前预热：把 Chromium 和 /chat 私信页先拉起来。"""
        self._ensure_browser()
        if self._chat_ready():
            return {"status": "ready", "cold": False}
        self._open_chat()
        return {"status": "ready", "cold": True}

    def _editor_locator(self):
        for selector in as_list(self.selectors.get("chat_editor")):
            try:
                locator = self.page.locator(selector).first
                if locator.count() > 0:
                    locator.wait_for(state="visible", timeout=3000)
                    return locator
            except Exception:
                continue
        return None

    def _editor_text(self, editor):
        """读输入框里的文字；读不到返回 None（用于区分「空」和「读不出来」）。"""
        try:
            return (editor.inner_text(timeout=1000) or "").strip()
        except Exception:
            return None

    def _message_count(self):
        try:
            return int(
                self.page.evaluate(
                    "() => document.querySelectorAll("
                    "\"[data-e2e='msg-item-content']\").length"
                )
            )
        except Exception:
            return -1

    def _op_send_message(self, ref="", nickname="", text="", dry_run=False):
        self._ensure_browser()
        self._open_chat()

        if not self._find_and_open_conversation(ref, nickname, timeout=FIND_TIMEOUT):
            return False, f"未找到会话：{nickname or ref}"

        # 防发错人：右侧聊天标题必须就是目标好友
        target = _normalize(nickname) or _normalize(ref)
        title = self._chat_pane_title()
        if (
            title
            and target
            and title != target
            and target not in title
            and title not in target
        ):
            return False, f"打开的会话与目标不符（{title}）：{nickname or ref}"

        editor = self._editor_locator()
        if editor is None:
            return False, "没有找到消息输入框（页面结构可能已改版）"

        baseline = self._editor_text(editor)
        if dry_run:
            return True, "试运行：未真正发送"

        before_count = self._message_count()
        try:
            editor.click(timeout=3000)
            # 先清空可能残留的草稿（上一次发送失败时留在输入框里的内容），
            # 否则重试会把旧内容和新消息拼在一起发出去。
            try:
                self.page.keyboard.press("Control+a")
                self.page.keyboard.press("Backspace")
                time.sleep(0.2)
            except Exception:
                pass
            self.page.keyboard.type(text, delay=30)
            time.sleep(0.4)

            sent = False
            button = self._first_visible(
                self.page, self.selectors.get("send_button"), timeout=2000
            )
            if button is not None:
                try:
                    button.click(timeout=3000)
                    sent = True
                except Exception:
                    sent = False
            if not sent:
                self.page.keyboard.press("Enter")

            # 发送成功判定：输入框被清空，或聊天区消息条数增加
            deadline = time.time() + 6
            while time.time() < deadline:
                current = self._editor_text(editor)
                if current is None or current == "" or current == baseline:
                    return True, "已发送"
                if before_count >= 0 and self._message_count() > before_count:
                    return True, "已发送"
                time.sleep(0.4)
            return False, "发送后输入框没有清空，消息可能没发出去"
        except Exception as exc:
            return False, f"发送失败：{exc}"

    def _op_logout(self):
        try:
            if self.context is not None:
                self.context.clear_cookies()
        except Exception:
            pass
        self._close_browser()
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        try:
            shutil.rmtree(self.profile_dir, ignore_errors=True)
        except Exception:
            pass
        return {"status": "offline"}


class PlaywrightDriver(BaseDriver):
    name = "playwright"

    def __init__(self):
        self._workers = {}
        self._lock = threading.Lock()

    def _worker(self, account):
        with self._lock:
            worker = self._workers.get(account.id)
            if worker is None or not worker.is_alive():
                worker = AccountWorker(account.id, account.profile_dir)
                worker.start()
                self._workers[account.id] = worker
            return worker

    def start_login(self, account, **kwargs):
        # 等二维码渲染在 NAS 上要 40~60s，加上兜底检测，给足 180s
        return self._worker(account).submit("start_login", timeout=180)

    def query_login(self, account, **kwargs):
        return self._worker(account).submit("query_login", timeout=60)

    def cancel_login(self, account):
        return self._worker(account).submit("cancel_login", timeout=30)

    def verify(self, account):
        return self._worker(account).submit("verify", timeout=90)

    def import_cookies(self, account, cookie_text):
        return self._worker(account).submit(
            "import_cookies", timeout=90, cookie_text=cookie_text
        )

    def sms_send_code(self, account, phone):
        return self._worker(account).submit(
            "sms_send_code", timeout=90, phone=phone
        )

    def sms_verify(self, account, code):
        return self._worker(account).submit(
            "sms_verify", timeout=90, code=code
        )

    def fetch_friends(self, account):
        return self._worker(account).submit("fetch_friends", timeout=200)

    def warmup(self, account):
        # 冷启动预热：Chromium 拉起 + 抖音首页 + im 模块，给足预算
        return self._worker(account).submit("warmup", timeout=300)

    def send_message(self, account, friend, text, dry_run=False):
        return self._worker(account).submit(
            "send_message",
            timeout=240,
            ref=friend.ref,
            nickname=friend.nickname or friend.ref,
            text=text,
            dry_run=dry_run,
        )

    def logout(self, account):
        return self._worker(account).submit("logout", timeout=60)

    def shutdown(self, account):
        worker = self._workers.pop(account.id, None)
        if worker:
            worker.stop()
