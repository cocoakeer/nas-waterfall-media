#!/usr/bin/env bash
# 瀑布相册 APK 构建脚本
#
# 刻意不用 Gradle / AndroidX / Maven 依赖：只需要 JDK 17 + Android SDK 的
# platform 与 build-tools，CI 里下载量小、没有版本兼容问题。
#
# 用法（装好 JDK 和 Android SDK 后）：
#   export ANDROID_HOME=/path/to/Android/sdk
#   sdkmanager "platforms;android-34" "build-tools;34.0.0"
#   bash android/build.sh
# 产物：android/out/waterfall-album.apk
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -z "$SDK" ] || [ ! -d "$SDK" ]; then
  echo "❌ 未找到 Android SDK，请设置 ANDROID_HOME" >&2
  exit 1
fi

ANDROID_JAR="$SDK/platforms/android-34/android.jar"
if [ ! -f "$ANDROID_JAR" ]; then
  # || true 不能省：pipefail 下目录缺失会让整条命令替换返回非 0，
  # set -e 会在赋值处直接退出，绕过下面那句友好报错
  ANDROID_JAR="$(find "$SDK/platforms" -name android.jar 2>/dev/null | sort | tail -1 || true)"
fi
if [ -z "$ANDROID_JAR" ] || [ ! -f "$ANDROID_JAR" ]; then
  echo "❌ 缺少 platforms;android-34，请先运行 sdkmanager" >&2
  exit 1
fi

BT="$(ls -d "$SDK"/build-tools/*/ 2>/dev/null | sort | tail -1 || true)"
if [ -z "$BT" ]; then
  echo "❌ 缺少 build-tools，请先运行 sdkmanager" >&2
  exit 1
fi
for tool in aapt2 d8 zipalign apksigner; do
  if [ ! -x "$BT/$tool" ]; then
    echo "❌ build-tools 里缺少 $tool（$BT）" >&2
    exit 1
  fi
done

# 固定签名密钥：保证以后更新 APK 时能直接覆盖安装，不用先卸载。
# 这是专为本应用新生成的自签名密钥，不含任何个人凭证。
KS="$ROOT/keystore/release.p12"
KS_PASS="waterfall-album-2026"
if [ ! -f "$KS" ]; then
  echo "❌ 缺少签名密钥 $KS" >&2
  exit 1
fi

rm -rf "$ROOT/build" "$ROOT/out"
mkdir -p "$ROOT/build/gen" "$ROOT/build/classes" "$ROOT/build/dex" "$ROOT/out"

echo "==> [1/6] 编译资源"
"$BT/aapt2" compile --dir "$ROOT/app/src/main/res" -o "$ROOT/build/res.zip"

echo "==> [2/6] 链接资源与 Manifest"
"$BT/aapt2" link \
  -o "$ROOT/build/base.apk" \
  -I "$ANDROID_JAR" \
  --manifest "$ROOT/app/src/main/AndroidManifest.xml" \
  --min-sdk-version 24 \
  --target-sdk-version 34 \
  --auto-add-overlay \
  "$ROOT/build/res.zip"

echo "==> [3/6] 编译 Java"
# 不用 mapfile：macOS 自带 Bash 3.2 没有它，数组 + while 两边都兼容
SOURCES=()
while IFS= read -r f; do SOURCES+=("$f"); done < <(find "$ROOT/app/src/main/java" -name '*.java' | sort)
# 只用 -classpath 不用 -bootclasspath：JDK 17 下后者容易报兼容错误，
# java.lang 由 JDK 自身提供，android.* 从 android.jar 解析，结果等价。
javac -encoding UTF-8 -source 8 -target 8 -Xlint:-options -nowarn \
  -classpath "$ANDROID_JAR" \
  -d "$ROOT/build/classes" "${SOURCES[@]}"

echo "==> [4/6] 转 DEX"
CLASSES=()
while IFS= read -r f; do CLASSES+=("$f"); done < <(find "$ROOT/build/classes" -name '*.class' | sort)
"$BT/d8" --lib "$ANDROID_JAR" --min-api 24 \
  --output "$ROOT/build/dex" "${CLASSES[@]}"

echo "==> [5/6] 打包并对齐"
(cd "$ROOT/build/dex" && zip -q "$ROOT/build/base.apk" classes.dex)
"$BT/zipalign" -f -p 4 "$ROOT/build/base.apk" "$ROOT/build/aligned.apk"

echo "==> [6/6] 签名"
"$BT/apksigner" sign \
  --ks "$KS" --ks-type PKCS12 \
  --ks-pass "pass:$KS_PASS" \
  --key-pass "pass:$KS_PASS" \
  --ks-key-alias waterfall \
  --v1-signing-enabled true --v2-signing-enabled true \
  --out "$ROOT/out/waterfall-album.apk" \
  "$ROOT/build/aligned.apk"
"$BT/apksigner" verify "$ROOT/out/waterfall-album.apk"
echo "   签名校验通过"

echo "✅ 产物：$ROOT/out/waterfall-album.apk"
ls -lh "$ROOT/out/waterfall-album.apk"
