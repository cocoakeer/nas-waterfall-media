<template>
  <div class="app-container">
    <header class="header">
      <h1>NAS 媒体瀑布流</h1>
      <div class="header-actions">
        <button @click="runCacheTask" class="btn" :disabled="cacheRunning">
          {{ cacheRunning ? `处理中 ${cachePercent}%` : "预生成缓存" }}
        </button>
        <button v-if="cacheRunning" @click="stopCacheTask" class="btn btn-danger">
          取消任务
        </button>
        <button @click="openSlideSetting" class="btn">幻灯片设置</button>
        <button @click="startSlideFromDir" class="btn primary">开始幻灯片</button>
      </div>
    </header>

    <div class="breadcrumb">
      <span @click="changeDir('')" class="breadcrumb-item">根目录</span>
      <span v-for="(item, idx) in breadcrumbList" :key="idx">
        <span class="separator">/</span>
        <span @click="changeDir(item.path)" class="breadcrumb-item">{{ item.name }}</span>
      </span>
    </div>

    <div ref="waterfallRef" class="waterfall-wrap">
      <div
        v-for="item in mediaList"
        :key="item.id"
        class="media-card"
        @click="handleCardClick(item)"
      >
        <div class="card-thumb">
          <template v-if="item.type === 'folder'">
            <img
              v-if="item.cover_path"
              :src="getThumbUrl(item.cover_path)"
              alt=""
              loading="lazy"
              @load="onMediaImgFinish"
              @error="onMediaImgFinish"
            />
            <svg v-else width="80" height="80" viewBox="0 0 24 24" fill="#f0c040">
              <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
            </svg>
          </template>
          <img
            v-else-if="item.type === 'image'"
            :src="getThumbUrl(item.path)"
            alt=""
            loading="lazy"
            @load="onMediaImgFinish"
            @error="onMediaImgFinish"
          />
          <div v-else-if="item.type === 'video'" class="video-wrap">
            <img
              :src="getThumbUrl(item.path)"
              alt=""
              loading="lazy"
              @load="onMediaImgFinish"
              @error="onMediaImgFinish"
            />
            <div class="play-icon">▶</div>
          </div>
        </div>
        <div class="card-name">{{ item.name }}</div>
      </div>
    </div>

    <!-- 预览弹窗 -->
    <div v-if="previewShow" class="preview-mask" @click.self="closePreview">
      <div class="preview-box">
        <button class="close-btn" @click="closePreview">×</button>

        <!-- 左右翻页箭头 -->
        <button class="arrow-btn arrow-left" @click.stop="prevMedia" :disabled="previewCurrentIndex <= 0">‹</button>
        <button class="arrow-btn arrow-right" @click.stop="nextMedia" :disabled="previewCurrentIndex >= previewMediaList.length - 1">›</button>

        <div class="preview-image-area">
          <img
            v-if="previewItem.type === 'image'"
            :src="getSrcUrl(previewItem.path)"
            alt=""
            :style="imgRotateStyle"
          />
          <video
            v-else
            controls
            :src="getSrcUrl(previewItem.path)"
          ></video>
        </div>

        <div class="preview-footer">
          <div class="preview-name">{{ previewItem.name }} ({{ previewCurrentIndex + 1 }} / {{ previewMediaList.length }})</div>
          <div v-if="previewItem.type === 'image'" class="img-action-bar">
            <button @click="openOriginal">查看原图</button>
            <button @click="rotateLeft">↺ 左旋90°</button>
            <button @click="rotateRight">↻ 右旋90°</button>
            <button @click="resetRotate">重置旋转</button>
            <!-- 新增：从当前图片开始幻灯片 -->
            <button @click="startSlideFromCurrent">从此处开始幻灯片</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 幻灯片设置弹窗 -->
    <div v-if="settingShow" class="preview-mask" @click.self="settingShow=false">
      <div class="setting-box">
        <h3>幻灯片设置</h3>
        <div class="form-row">
          <label>切换间隔（秒）</label>
          <input v-model.number="slideDelay" type="number" min="1" />
        </div>
        <div class="form-row">
          <label>循环播放</label>
          <input v-model="slideLoop" type="checkbox" />
        </div>
        <div class="btn-group">
          <button @click="saveSetting" class="btn primary">保存</button>
          <button @click="settingShow=false" class="btn">取消</button>
        </div>
      </div>
    </div>

    <!-- 幻灯片全屏预览 -->
    <div v-if="slideShow" ref="slideRootRef" class="slide-mask">
      <div class="slide-content">
        <img v-if="currentSlide.type==='image'" :src="getSrcUrl(currentSlide.path)" alt="" />
        <video v-else controls :src="getSrcUrl(currentSlide.path)"></video>
        <div class="slide-name">{{ currentSlide.name }}</div>
        <button class="slide-exit-btn" @click="exitSlide">退出全屏</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'

const baseUrl = ''
const mediaList = ref([])
const breadcrumbList = ref([])
const waterfallRef = ref(null)
const slideRootRef = ref(null)

const previewShow = ref(false)
const previewItem = ref(null)
let previewMediaList = []
let previewCurrentIndex = 0
const imgRotateDeg = ref(0)

const settingShow = ref(false)
const slideDelay = ref(3)
const slideLoop = ref(true)
const slideShow = ref(false)
const slideIndex = ref(0)
const slideTimer = ref(null)
const slideList = ref([])
const currentSlide = ref({})

let resizeObserver = null
let layoutDebounceTimer = null

const cacheRunning = ref(false)
const cachePercent = ref(0)
let statusPollTimer = null

const STORAGE_KEY = "waterfall_last_dir"

const getThumbUrl = (path) => {
  return `${baseUrl}/api/thumb?path=${encodeURIComponent(path)}`
}
const getSrcUrl = (path) => {
  return `${baseUrl}/api/src?path=${encodeURIComponent(path)}`
}

const imgRotateStyle = ref({
  transform: 'rotate(0deg)',
  transition: 'transform 0.25s ease'
})

function rotateLeft() {
  imgRotateDeg.value -= 90
  imgRotateStyle.value.transform = `rotate(${imgRotateDeg.value}deg)`
}
function rotateRight() {
  imgRotateDeg.value += 90
  imgRotateStyle.value.transform = `rotate(${imgRotateDeg.value}deg)`
}
function resetRotate() {
  imgRotateDeg.value = 0
  imgRotateStyle.value.transform = 'rotate(0deg)'
}
function openOriginal() {
  window.open(getSrcUrl(previewItem.value.path), '_blank')
}

function getColumnCount() {
  const w = window.innerWidth
  if (w <= 480) return 1
  if (w <= 768) return 2
  if (w <= 1200) return 3
  return 4
}

function layoutWaterfall() {
  if (!waterfallRef.value) return
  const container = waterfallRef.value
  const cards = Array.from(container.querySelectorAll('.media-card'))
  const colCount = getColumnCount()
  const gap = 14

  container.style.position = 'relative'
  cards.forEach(card => {
    card.style.position = 'absolute'
  })

  const colHeights = new Array(colCount).fill(0)
  const cardWidth = (container.clientWidth - gap * (colCount - 1)) / colCount

  for (const card of cards) {
    let minCol = 0
    for (let i = 0; i < colCount; i++) {
      if (colHeights[i] < colHeights[minCol]) minCol = i
    }
    card.style.width = cardWidth + 'px'
    card.style.left = minCol * (cardWidth + gap) + 'px'
    card.style.top = colHeights[minCol] + 'px'
    colHeights[minCol] += card.offsetHeight + gap
  }
  container.style.height = Math.max(...colHeights) + 'px'
}

function debounceLayout() {
  clearTimeout(layoutDebounceTimer)
  layoutDebounceTimer = setTimeout(() => {
    layoutWaterfall()
  }, 120)
}

function onMediaImgFinish() {
  debounceLayout()
}

async function pollCacheStatus() {
  try {
    const res = await fetch(`${baseUrl}/api/cache-status`)
    const st = await res.json()
    cachePercent.value = st.percent
    if (!st.running) {
      clearInterval(statusPollTimer)
      statusPollTimer = null
      cacheRunning.value = false
      alert(`✅缓存任务结束！\n${st.message}\n处理文件:${st.processed}/${st.total}`)
    }
  } catch (err) {
    console.error("查询任务状态失败", err)
  }
}

async function initCheckCacheTask() {
  try {
    const res = await fetch(`${baseUrl}/api/cache-status`)
    const st = await res.json()
    if (st.running) {
      cacheRunning.value = true
      cachePercent.value = st.percent
      statusPollTimer = setInterval(pollCacheStatus, 800)
    }
  } catch (err) {
    console.error("初始化检查缓存任务失败", err)
  }
}

async function runCacheTask() {
  if (cacheRunning.value) return
  cacheRunning.value = true
  cachePercent.value = 0
  try {
    const res = await fetch(`${baseUrl}/api/cache-run`)
    const ret = await res.json()
    if (ret.code !== 0) {
      alert("❌" + ret.msg)
      cacheRunning.value = false
      return
    }
    statusPollTimer = setInterval(pollCacheStatus, 800)
  } catch (err) {
    console.error(err)
    alert("❌请求失败，提交任务出错！")
    cacheRunning.value = false
  }
}

async function stopCacheTask() {
  if (!confirm("确认要终止缓存任务吗？")) return
  try {
    const res = await fetch(`${baseUrl}/api/cache-stop`)
    const ret = await res.json()
    if (ret.code !== 0) {
      alert("❌" + ret.msg)
    }
  } catch (err) {
    console.error(err)
    alert("❌发送停止指令失败")
  }
}

function getDirFromUrl() {
  const params = new URLSearchParams(window.location.search)
  return params.get('dir') ?? ''
}

function syncDirToUrl(dir) {
  const url = new URL(window.location.href)
  if (dir) {
    url.searchParams.set('dir', dir)
  } else {
    url.searchParams.delete('dir')
  }
  window.history.pushState({ dir }, '', url.toString())
}

async function loadMedia(dir = '', pushHistory = false) {
  try {
    const res = await fetch(`${baseUrl}/api/list?dir=${encodeURIComponent(dir)}`)
    if (!res.ok) throw new Error()
    const data = await res.json()
    mediaList.value = data.list || []
    breadcrumbList.value = data.breadcrumb || []
    localStorage.setItem(STORAGE_KEY, dir)

    if (pushHistory) {
      syncDirToUrl(dir)
    }

    await nextTick()
    debounceLayout()
  } catch (err) {
    console.error(err)
    mediaList.value = []
  }
}

function changeDir(path) {
  loadMedia(path, true)
}

function handleCardClick(item) {
  if (item.type === 'folder') {
    changeDir(item.path)
  } else {
    previewMediaList = mediaList.value.filter(x => x.type !== 'folder')
    previewCurrentIndex = previewMediaList.findIndex(x => x.id === item.id)
    previewItem.value = item
    imgRotateDeg.value = 0
    imgRotateStyle.value.transform = 'rotate(0deg)'
    previewShow.value = true
  }
}

function prevMedia() {
  if (previewCurrentIndex > 0) {
    previewCurrentIndex -= 1
    previewItem.value = previewMediaList[previewCurrentIndex]
    imgRotateDeg.value = 0
    imgRotateStyle.value.transform = 'rotate(0deg)'
  }
}

function nextMedia() {
  if (previewCurrentIndex < previewMediaList.length - 1) {
    previewCurrentIndex += 1
    previewItem.value = previewMediaList[previewCurrentIndex]
    imgRotateDeg.value = 0
    imgRotateStyle.value.transform = 'rotate(0deg)'
  }
}

function handleKeydown(e) {
  if (!previewShow.value) return
  switch (e.key) {
    case 'ArrowLeft':
      e.preventDefault()
      prevMedia()
      break
    case 'ArrowRight':
      e.preventDefault()
      nextMedia()
      break
    case 'Escape':
      e.preventDefault()
      closePreview()
      break
  }
}

function openSlideSetting() {
  settingShow.value = true
}

function saveSetting() {
  settingShow.value = false
}

// 从当前目录第一张开始
function startSlideFromDir() {
  slideList.value = mediaList.value.filter(i => i.type === 'image')
  if (slideList.value.length === 0) return alert('当前目录没有图片，无法幻灯片')
  slideIndex.value = 0
  openFullscreen()
  slideShow.value = true
  runSlide()
}

// 【新增】从当前预览图片开始播放
function startSlideFromCurrent() {
  slideList.value = previewMediaList.filter(i => i.type === 'image')
  if (slideList.value.length === 0) return alert('没有图片可以幻灯片')
  // 找到当前图片在图片列表里的下标
  const idx = slideList.value.findIndex(x => x.path === previewItem.value.path)
  slideIndex.value = Math.max(idx, 0)
  closePreview()
  openFullscreen()
  slideShow.value = true
  runSlide()
}

// 开启浏览器全屏
async function openFullscreen() {
  const el = slideRootRef.value
  if (!el) return
  try {
    if (el.requestFullscreen) {
      await el.requestFullscreen()
    } else if (el.webkitRequestFullscreen) {
      await el.webkitRequestFullscreen()
    } else if (el.msRequestFullscreen) {
      await el.msRequestFullscreen()
    }
  } catch (e) {
    console.warn("无法进入全屏，浏览器权限限制", e)
  }
}

// 退出全屏 + 关闭幻灯片
function exitSlide() {
  clearTimeout(slideTimer.value)
  slideShow.value = false
  if (document.exitFullscreen) {
    document.exitFullscreen()
  } else if (document.webkitExitFullscreen) {
    document.webkitExitFullscreen()
  } else if (document.msExitFullscreen) {
    document.msExitFullscreen()
  }
}

function runSlide() {
  clearTimeout(slideTimer.value)
  currentSlide.value = slideList.value[slideIndex.value]
  slideTimer.value = setTimeout(() => {
    slideIndex.value++
    if (slideIndex.value >= slideList.value.length) {
      if (slideLoop.value) slideIndex.value = 0
      else {
        exitSlide()
        return
      }
    }
    runSlide()
  }, slideDelay.value * 1000)
}

function closePreview() {
  previewShow.value = false
  previewItem.value = null
  previewMediaList = []
  previewCurrentIndex = 0
}

function onWindowResize() {
  debounceLayout()
}

function onPopState(e) {
  const dir = e.state?.dir ?? getDirFromUrl()
  loadMedia(dir, false)
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('popstate', onPopState)

  // 监听ESC退出全屏
  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && slideShow.value) {
      exitSlide()
    }
  })

  resizeObserver = new ResizeObserver(() => {
    debounceLayout()
  })
  if (waterfallRef.value) resizeObserver.observe(waterfallRef.value)

  const urlDir = getDirFromUrl()
  const lastDir = localStorage.getItem(STORAGE_KEY) ?? ''
  const initDir = urlDir || lastDir || ''

  loadMedia(initDir, !!urlDir)
  initCheckCacheTask()
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('popstate', onPopState)
  if (resizeObserver) resizeObserver.disconnect()
  clearTimeout(layoutDebounceTimer)
  if (statusPollTimer) clearInterval(statusPollTimer)
  clearTimeout(slideTimer.value)
})
</script>

<style scoped>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

.app-container {
  min-height: 100vh;
  background: #121212;
  color: #eee;
  padding: 16px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.header h1 {
  font-size: 22px;
  color: #fff;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.btn {
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: #2a2a2a;
  color: #fff;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.btn.primary {
  background: #2563eb;
}

.btn-danger {
  background: #dc2626;
}

.breadcrumb {
  margin-bottom: 16px;
  color: #aaa;
}

.breadcrumb-item {
  color: #60a5fa;
  cursor: pointer;
}

.separator {
  margin: 0 6px;
}

.waterfall-wrap {
  width: 100%;
  min-height: 200px;
  position: relative;
}

.media-card {
  background: #1e1e1e;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.media-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.32);
}

.card-thumb {
  width: 100%;
  overflow: hidden;
  background: #222;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-thumb img {
  width: 100%;
  height: auto;
  display: block;
}

.play-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 44px;
  height: 44px;
  background: rgba(0, 0, 0, 0.6);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: #fff;
}

.card-name {
  padding: 10px 12px;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.preview-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.88);
  z-index: 99;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
}

.preview-box {
  background: transparent;
  border-radius: 0;
  width: min(97vw, 1280px);
  height: min(94vh, 960px);
  max-width: 97vw;
  max-height: 94vh;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.close-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: rgba(40,40,40,0.75);
  color: #fff;
  border: none;
  font-size: 20px;
  cursor: pointer;
  z-index: 4;
}

.arrow-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: rgba(40,40,40,0.75);
  color: #fff;
  border: none;
  font-size: 26px;
  cursor: pointer;
  z-index: 3;
  transition: background 0.2s;
}
.arrow-btn:hover:not(:disabled) {
  background: rgba(80,80,80,0.9);
}
.arrow-btn:disabled {
  opacity:0.25;
  cursor: default;
}
.arrow-left {
  left: 12px;
}
.arrow-right {
  right: 12px;
}

.preview-image-area {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: 18px 18px 10px;
}

.preview-image-area img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.preview-image-area video {
  max-width: 100%;
  max-height: 100%;
}

.preview-footer {
  flex-shrink: 0;
  background: transparent;
  padding: 10px 16px 14px;
  border-top: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.preview-name {
  font-size: 14px;
  color: #eee;
  text-align: center;
}

.img-action-bar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: center;
}

.img-action-bar button {
  padding: 6px 12px;
  background: rgba(42,42,42,0.75);
  color: #fff;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.img-action-bar button:hover {
  background: rgba(58,58,58,0.9);
}

.setting-box {
  background: #181818;
  border-radius: 12px;
  padding: 24px;
  width: 360px;
}

.form-row {
  margin: 14px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.btn-group {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
}

.slide-mask {
  position: fixed;
  inset: 0;
  background: #000;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.slide-content {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.slide-content img,
.slide-content video {
  max-width: 98vw;
  max-height: 98vh;
}

.slide-name {
  position: absolute;
  bottom: 60px;
  left: 0;
  right: 0;
  text-align: center;
  color: #fff;
  font-size: 14px;
}

.slide-exit-btn {
  position: absolute;
  top: 16px;
  right: 16px;
  padding: 8px 14px;
  background: rgba(40,40,40,0.75);
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.slide-exit-btn:hover {
  background: rgba(80,80,80,0.9);
}
</style>
