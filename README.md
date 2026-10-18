# 抖音火花助手

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

一个跑在自己设备上的抖音「续火花」小工具。用 Playwright 打开抖音网页版，按设定时间给好友发送消息，省掉每天手动点一遍的麻烦。配了一个 Web 界面，登录、选好友、定时、看日志都在浏览器里完成。

抖音没有开放私信相关的官方接口，所以只能自动化操作网页。这意味着页面一改版就可能失效，项目把页面选择器做成了可覆盖的配置，遇到改版通常不用改代码。

仅供学习交流和技术研究。使用前请自行评估风险，后果自负。

## 背景

最早是给自己用的：几个好友的火花快断了，每天手动发一句挺烦，就写了个脚本，后来越加越多，有了登录、多账号、定时和 Web 界面，最后整理开源出来。代码不复杂，胜在能跑。

## 功能

- 两个账号分别托管，数据、Cookie、浏览器 Profile 互不影响
- 登录方式：扫码、短信验证码、导入 Cookie
- 好友列表从会话列表拉取，可搜索、勾选、单独设置消息
- 每个账号可配多个每日时间点，随时启停
- 消息池支持多条，随机或顺序轮换，支持 `{nickname}`、`{date}`、`{time}`、`{index}` 变量
- 发送间隔随机抖动，支持试运行模式
- 可选 TOTP 二次验证（RFC 6238），保护管理界面
- 运行日志按账号记录，同时输出到 `docker logs`
- 页面选择器可通过 `data/selectors.json` 覆盖

## 目录结构

```text
.
├── app/
│   ├── __init__.py               Flask 应用工厂
│   ├── config.py                 配置（全部可用环境变量覆盖）
│   ├── extensions.py             SQLAlchemy 实例
│   ├── models.py                 Account / Friend / RunLog
│   ├── logstore.py               运行日志
│   ├── otp.py                    TOTP 校验（纯标准库）
│   ├── web.py                    HTTP API 与页面路由
│   ├── drivers/
│   │   ├── base.py               驱动接口
│   │   ├── selectors.py          页面选择器
│   │   ├── playwright_driver.py  真实浏览器实现
│   │   └── mock_driver.py        演示实现，不访问抖音
│   ├── services/scheduler.py     APScheduler 定时任务
│   ├── static/                   前端资源
│   └── templates/                页面模板
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh                 容器入口，启动 Xvfb 后运行应用
├── requirements.txt
├── run.py
├── .env.example
├── deploy.example.sh
├── LICENSE
├── NOTICE
├── README.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
└── CHANGELOG.md
```

运行时数据都在 `data/` 下，不进仓库：`spark.db` 是 SQLite 数据库，`profiles/` 存浏览器 Profile 和 Cookie，`tmp/` 存二维码截图。

## 环境要求

- Python 3.11+
- 能访问 `www.douyin.com`
- Docker 部署需要 Docker 24+ 和 docker compose v2
- 建议 2GB 以上内存。浏览器常驻大概 300–600MB，空闲 10 分钟会自动关闭

## 部署

### Docker

```bash
git clone https://github.com/YH-Chen-Eternity/douyin-spark.git
cd douyin-spark

cp .env.example .env

# 必须生成 SECRET_KEY 填进 .env，否则 compose 会拒绝启动（会话密钥不能是公开固定值）
python -c "import secrets;print(secrets.token_hex(32))"

docker compose build
docker compose up -d
docker compose logs -f --tail 100
```

启动后访问 `http://<部署机IP>:8787`。

容器里的 `entrypoint.sh` 会启动 Xvfb 虚拟显示，浏览器以有头模式运行。抖音对无头浏览器风控很严，`HEADLESS` 请保持 `false`。

默认 `docker compose` 会把端口发布到所有网卡。如果只在本机用，建议把 `ports` 改成 `"127.0.0.1:8787:8787"`，或绑定到具体内网地址。

### 本地运行

```bash
python -m venv .venv
source .venv/bin/activate        # Windows 用 .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# 演示模式：不访问抖音，用来验证界面、勾选、定时和日志
export DATA_DIR=./data
export SPARK_DRIVER=mock
export HEADLESS=true
python run.py
```

打开 `http://127.0.0.1:8787`。

真实模式把 `SPARK_DRIVER` 换成 `playwright`、`HEADLESS` 设为 `false`，并且需要一个可用的图形界面（或者自己配 Xvfb / VNC）。

## 配置

配置都走环境变量，Docker 部署写在 `.env` 里，参考 `.env.example`。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATA_DIR` | `/data` | 数据库、Profile、二维码截图的存放目录 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8787` | 监听端口 |
| `SPARK_DRIVER` | `playwright` | `playwright` 或 `mock` |
| `HEADLESS` | `false` | 是否无头运行 |
| `TZ` | `Asia/Shanghai` | 时区，影响定时任务 |
| `SECRET_KEY` | 占位值 | Flask 会话密钥，生产环境务必换掉 |
| `SPARK_OTP_SECRET` | 空 | TOTP 密钥（Base32），留空则关闭 OTP |
| `SPARK_OTP_SESSION_HOURS` | `12` | OTP 登录有效期（小时） |
| `LOGIN_TIMEOUT` | `300` | 扫码等待上限（秒） |
| `OP_TIMEOUT` | `90` | 单次浏览器操作超时（秒） |

生成 TOTP 密钥：

```bash
python -c "import base64,os;print(base64.b32encode(os.urandom(20)).decode())"
```

把结果填进 `.env` 的 `SPARK_OTP_SECRET`，再用支持 TOTP 的验证器添加同一个密钥，访问界面时输入 6 位动态口令即可。`.env` 已在 `.gitignore` 里，不要提交。

## 使用

1. 打开 `http://<部署机IP>:8787`，输入 OTP 口令（如果开了）
2. 点「扫码登录」，用抖音 App 扫码并在手机上确认。扫码不行可以换短信验证码或导入 Cookie
3. 点「刷新」拉取会话列表（要求账号在抖音里已经有聊天记录）
4. 勾选要续火花的好友，需要的话给单个好友填专属消息
5. 在「定时任务」里添加时间点，设置消息和间隔抖动
6. 先勾上「试运行」点一次「立即执行一次」，看日志没问题再关掉
7. 打开任务开关

## 关于页面改版

抖音网页版在 2026 年 10 月把私信从首页弹窗（`im-entry` / `im-dialog`）搬到了独立的 `/chat` 页面，旧的选择器全部失效。现在的驱动直接打开 `https://www.douyin.com/chat`，用到的选择器：

| 元素 | 默认选择器 |
| --- | --- |
| 会话列表项 | `[data-e2e='conversation-item']` |
| 会话昵称 | `[class*='ConversationItemtitle']` |
| 消息输入框 | `div[data-e2e='msg-input'] div[contenteditable='true']` |
| 发送按钮 | `[class*='e2e-send-msg-btn']` |
| 消息气泡 | `[data-e2e='msg-item-content']` |

如果以后扫码或发送又失效了，先在 `data/selectors.json` 里覆盖对应字段，重启容器生效，不用重新构建镜像：

```json
{
  "qr_container": ["div.new-qrcode-class"],
  "friend_item": ["[data-e2e='conversation-item']"],
  "friend_name": ["[class*='ConversationItemtitle']"],
  "chat_editor": ["div[data-e2e='msg-input'] div[contenteditable='true']"],
  "send_button": ["[class*='e2e-send-msg-btn']"]
}
```

找新选择器的方法：电脑浏览器打开抖音网页版，F12 用元素选择器点目标元素，右键 Copy → Copy selector。

另外几个执行上的处理：

- 任务开始前先校验登录态，失效就直接中止并提示重新扫码，不会白跑很久
- 执行前预热浏览器和私信页，减少第一个好友的冷启动失败
- 失败的好友在任务最后补发一次
- 每个账号一个工作线程和一份浏览器 Profile，互不干扰

## 常见问题

**二维码一直不出来，或者提示「二维码截图失败」**

先看 `docker compose logs -f`。常见原因：机器慢，首页到二维码渲染要 40–60 秒；或者页面改版导致 `qr_container` 失效，按上面的方法覆盖；也可能是浏览器被风控，试试重启容器或换网络。

**提示需要滑块验证**

抖音的风控。建议改用导入 Cookie：在电脑浏览器登录抖音网页版，从开发者工具复制 Cookie 粘到界面里。Cookie 是敏感信息，别外传。

**登录后第二天就失效了**

抖音会定期让网页会话失效，重新扫码就行。任务开始前会先校验登录态，失效时会明确提示。

**抓不到好友列表**

确认账号已登录、抖音里确实有会话、页面没有改版。不行就覆盖 `friend_item` / `friend_name`，或者手动添加好友。

**报「私信页面加载超时」「未找到会话」**

多半是页面改版或账号风控。先确认登录态，再检查 `/chat` 页面的选择器。

**Docker 报 permission denied**

当前用户没有 Docker 权限。用 `sudo docker compose ...`，或者把用户加进 docker 组后重新登录：

```bash
sudo usermod -aG docker "$USER"
```

**内存占用高**

浏览器常驻 300–600MB，空闲 10 分钟会自动关掉。内存小的设备建议只登一个账号。

## 安全

`data/` 里有数据库、浏览器 Profile、Cookie 和二维码截图，属于登录态数据，不要提交、不要分享。`.env` 里有 `SECRET_KEY` 和 `SPARK_OTP_SECRET`，同样不要提交。部署脚本里的密码、私钥、内网地址也别写进仓库，`deploy.example.sh` 是个占位符版本。

`SECRET_KEY` 必须设置为随机值，不能用默认/固定值：会话 Cookie 里带有「OTP 已通过」的标记，密钥泄露就等于 OTP 可以被伪造绕过。启用 OTP 时如果没有设置 `SECRET_KEY`，程序会直接拒绝启动。

贴日志或截图到 Issue 之前，先把 Cookie、`sessionid`、手机号、内网 IP 之类的删掉。

建议只在内网跑，端口只绑定内网地址。非要公网访问的话，前面加一层 HTTPS 反向代理，再配合 OTP 和访问控制。怀疑密钥泄露就重新扫码登录，换掉 `SPARK_OTP_SECRET` 和 `SECRET_KEY`。

更多见 [SECURITY.md](SECURITY.md)。

## 贡献

欢迎提 Issue 和 PR。动手之前先看：

- [CONTRIBUTING.md](CONTRIBUTING.md)：分支和提交信息规范、PR 要求
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)：行为准则
- [SECURITY.md](SECURITY.md)：安全问题怎么报

## 许可证

本项目采用 [Apache License 2.0](LICENSE)，版权信息见 [NOTICE](NOTICE)。

```
Copyright 2026 YH-Chen-Eternity

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

## 免责声明

这个项目只是学习交流用的，不保证能用、也不保证稳定。它不是抖音官方接口，抖音随时可能改版让功能失效。用这个工具可能违反平台的服务条款，账号有被风控、限制功能甚至封禁的风险。请遵守平台规则和当地法律法规，别高频发送，别用来骚扰别人，别拿去做商业用途。因为使用或无法使用这个项目造成的任何损失，作者和贡献者都不负责，用之前请想清楚。
