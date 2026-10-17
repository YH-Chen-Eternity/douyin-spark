FROM python:3.11-slim-bookworm

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    PORT=8787 \
    SPARK_DRIVER=playwright \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Chromium 及其系统依赖（扫码登录需要真实浏览器环境）
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

COPY . .

RUN chmod +x /app/entrypoint.sh
RUN mkdir -p /data/profiles /data/tmp
VOLUME ["/data"]
EXPOSE 8787

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "run.py"]
