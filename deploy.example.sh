#!/usr/bin/env bash
# 示例部署脚本：复制本文件并按你的环境修改后再使用。
#
# 安全提醒：
#   - 不要把真实密码、私钥、内网 IP 写进脚本并提交到仓库；
#   - 建议使用 SSH 免密登录 + sudoers 精确授权，或直接手动执行 docker compose 命令。
#
# 用法：
#   cp deploy.example.sh deploy.sh
#   chmod +x deploy.sh
#   ./deploy.sh

set -euo pipefail

# 项目在部署机上的绝对路径（请替换）
PROJECT_DIR="/path/to/douyin-spark"

cd "$PROJECT_DIR"

echo "==> 构建镜像"
docker compose build

echo "==> 重启容器"
docker compose up -d

echo "==> 当前状态"
docker compose ps

echo "==> 访问地址：http://<部署机IP>:8787"
