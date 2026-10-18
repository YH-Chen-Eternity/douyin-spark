FROM python:3.11-slim-bookworm

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    PORT=8787 \
    SPARK_DRIVER=playwright \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/appuser

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Chromium 及其系统依赖（扫码登录需要真实浏览器环境）。
# 指定 PLAYWRIGHT_BROWSERS_PATH 后浏览器装在 /ms-playwright，非 root 用户也能使用。
RUN playwright install --with-deps chromium

# xauth 供 xvfb-run 使用（有头模式 + 虚拟显示）
RUN apt-get update \
    && apt-get install -y --no-install-recommends xauth \
    && rm -rf /var/lib/apt/lists/*

# 完整版 Google Chrome：抖音网页版私信入口依赖真实 Chrome 环境指纹
# （Chromium 下前端不下发 im 模块，见 app/drivers/playwright_driver.py 的 _open_im_panel）
RUN curl -sL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# 非 root 运行用户。uid/gid 固定，宿主机数据目录需要 chown 10001:10001。
RUN useradd --uid 10001 --user-group --create-home --shell /usr/sbin/nologin appuser

COPY . .

# 构建上下文可能来自有特殊权限位的文件系统（例如 NAS），COPY 会原样保留权限。
# 这里统一补齐读/执行权限，否则非 root 用户无法读取代码或执行入口脚本。
RUN chmod -R a+rX /app \
    && chmod 755 /app/entrypoint.sh
RUN mkdir -p /data/profiles /data/tmp \
    && chown -R appuser:appuser /data

VOLUME ["/data"]
EXPOSE 8787

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "run.py"]
