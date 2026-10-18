#!/bin/bash
set -e

# 有头模式需要虚拟显示。启动 Xvfb 并导出 DISPLAY。
# 抖音对无头浏览器有风控，必须用有头模式 + Xvfb 才能拿到扫码二维码。
if [ -z "$DISPLAY" ]; then
  # 清理上次运行残留的锁/socket，避免容器重启后 Xvfb 启动失败
  rm -f /tmp/.X99-lock
  rm -f /tmp/.X11-unix/X99
  # 容器以非 root 运行，/tmp 可写，确保 socket 目录存在
  mkdir -p /tmp/.X11-unix
  Xvfb :99 -screen 0 1440x900x24 -nolisten tcp >/dev/null 2>&1 &
  export DISPLAY=:99
  # 等待 Xvfb 的 socket 就绪（最多 10 秒）
  for _ in $(seq 1 20); do
    [ -S /tmp/.X11-unix/X99 ] && break
    sleep 0.5
  done
fi

exec "$@"
