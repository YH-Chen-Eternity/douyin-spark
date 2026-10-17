"""抖音页面选择器。

抖音网页版结构会不定期改版，这里的选择器只是「当前可用的猜测值」。
如果发现扫码/发消息失效，不要改代码 —— 在 /data/selectors.json 里覆盖对应字段即可，
容器重启后生效，无需重新构建镜像。

覆盖文件格式示例（/data/selectors.json）：
{
  "qr_container": ["div.qrcode-img", "canvas"],
  "chat_editor": ["div[contenteditable='true']"]
}
"""
import json

from app.config import DATA_DIR

DEFAULTS = {
    # ---- 登录 ----
    "login_url": "https://www.douyin.com/",
    # 二维码所在的容器，截图这个元素给用户扫
    "qr_container": [
        "#animate_qrcode_container img",
        "#animate_qrcode_container",
        "#douyin_login_comp_scan_code",
        "#douyin-login-new-id img[src^='data:image/png']",
        "div.qrcode",
        "div.qrcode-img",
        "div.login-pannel img",
        "div.web-login img.qrcode-img",
        "canvas.qrcode",
        "div[data-e2e='login-qrcode']",
        "img.qrcode-img",
    ],
    # 页面上出现「扫码登录」等文案时，说明还没登录
    "login_pending_marker": [
        "text=扫码登录",
        "text=扫码",
        "div.login-pannel",
    ],
    # 登录后才会出现的元素（头像 / 侧边栏入口）
    "logged_in_marker": [
        "div[data-e2e='live-avatar']",
        "div.avatar",
        "a[href*='/user/']",
        "div[data-e2e='feed-active-video']",
        "div.sidebar",
        "img.avatar",
    ],
    "nickname": [
        "div[data-e2e='login-user-name']",
        "span.nickname",
        "div.user-name",
    ],
    # ---- 验证码登录 ----
    "sms_tab": ["text=验证码登录", "span:has-text('验证码登录')"],
    "sms_phone_input": ["#normal-input", "input[name='normal-input']"],
    "sms_code_input": ["#button-input", "input[name='button-input']"],
    "sms_send_button": ["text=获取验证码", "span:has-text('获取验证码')"],
    "sms_login_button": ["button:has-text('登录')", "button[class*='login']"],
    "sms_agreement": ["span[class*='agreement']", "input[type='checkbox']"],
    # ---- 消息 ----
    # 2026-10 抖音网页版改版：私信从首页弹窗迁移到独立的 /chat 页面
    "messages_url": "https://www.douyin.com/chat",
    "friend_item": [
        "[data-e2e='conversation-item']",
    ],
    "friend_name": [
        "[class*='ConversationItemtitle']",
        "span[class*='name']",
        "div[class*='name']",
    ],
    "chat_editor": [
        "div[data-e2e='msg-input'] div[contenteditable='true']",
        "div[contenteditable='true'][data-placeholder='发送消息']",
        "div[contenteditable='true']",
    ],
    "send_button": [
        "[class*='e2e-send-msg-btn']",
        "button[data-e2e='message-send']",
        "span:has-text('发送')",
    ],
}

_OVERRIDE_FILE = DATA_DIR / "selectors.json"


def load_selectors():
    result = dict(DEFAULTS)
    try:
        if _OVERRIDE_FILE.exists():
            with open(_OVERRIDE_FILE, "r", encoding="utf-8") as fp:
                override = json.load(fp)
            if isinstance(override, dict):
                for key, value in override.items():
                    result[key] = value
    except Exception:
        pass
    return result


def as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    return []
