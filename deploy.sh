#!/bin/zsh
set -e

# 需要的忽略规则
IGNORE_RULES=(
"frontend/node_modules/"
"frontend/package-lock.json"
".DS_Store"
"*.log"
)

echo "===== 检查 .gitignore ====="
if [ ! -f ".gitignore" ];then
  echo ".gitignore 不存在，自动创建"
  touch .gitignore
fi

for rule in "${IGNORE_RULES[@]}";do
  if ! grep -qxF "$rule" .gitignore;then
    echo "$rule" >> .gitignore
    echo "追加忽略规则：$rule"
  fi
done

echo "===== 检查Git缓存中是否还有node_modules ====="
if git ls-files | grep -q "frontend/node_modules";then
  echo "⚠️  发现git正在追踪 frontend/node_modules，自动清理缓存"
  git rm --cached -r frontend/node_modules
fi

echo "===== 开始打包前端 ====="
cd frontend
npm run build
cd ..

echo "===== 打包完成，准备提交git ====="
git add .
echo "请输入提交备注（直接回车使用默认：update）："
read msg
# 为空就赋值默认
if [ -z "$msg" ];then
  msg="update"
fi
git commit -m "$msg"

echo "===== 推送到GitHub ====="
git push origin main

echo "✅ 打包+上传全部完成！前往Github Actions查看镜像构建"
