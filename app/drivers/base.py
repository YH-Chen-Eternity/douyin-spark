"""驱动接口定义。

所有抖音侧的操作都必须通过这里的方法，上层（调度器 / Web）不直接碰浏览器。
想接入别的实现（比如某天抖音出官方接口），实现这些方法即可。
"""


class DriverError(Exception):
    pass


class LoginResult:
    def __init__(self, status, qr_url=None, message="", nickname=""):
        # pending | success | expired | error
        self.status = status
        self.qr_url = qr_url
        self.message = message
        self.nickname = nickname

    def to_dict(self):
        return {
            "status": self.status,
            "qr_url": self.qr_url,
            "message": self.message,
            "nickname": self.nickname,
        }


class BaseDriver:
    name = "base"

    def start_login(self, account, **kwargs):
        """打开登录页并给出二维码。返回 LoginResult(pending, qr_url=...)"""
        raise NotImplementedError

    def query_login(self, account):
        """轮询扫码结果。返回 LoginResult。"""
        raise NotImplementedError

    def cancel_login(self, account):
        raise NotImplementedError

    def verify(self, account):
        """用已有本地会话校验是否仍然在线。返回 LoginResult。"""
        raise NotImplementedError

    def fetch_friends(self, account):
        """返回 [{'ref','nickname','avatar'}]"""
        raise NotImplementedError

    def warmup(self, account):
        """任务开始前预热浏览器/页面（可选）。默认不做事。"""
        return {"status": "skipped"}

    def send_message(self, account, friend, text, **kwargs):
        """返回 (ok: bool, message: str)"""
        raise NotImplementedError

    def logout(self, account):
        raise NotImplementedError

    def shutdown(self, account):
        """释放该账号占用的资源（浏览器等）。"""
        raise NotImplementedError
