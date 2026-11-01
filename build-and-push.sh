#!/bin/zsh
set -e

echo "===== 前端dist已经打包完成，准备提交git ====="
git add .
git status
echo
read "msg?输入本次提交备注: "
git commit -m "$msg"
git push origin main

echo "✅ 推送完成！GitHub Action 已经开始构建镜像了"


