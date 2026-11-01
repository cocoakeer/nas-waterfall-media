<template>
  <div class="app-container">
    <header class="app-header">
      <h1 class="title">NAS 媒体瀑布流</h1>
      <div class="control-bar">
        <div class="input-group">
          <label>幻灯片间隔(秒)</label>
          <input v-model.number="slideDelay" type="number" min="1" @change="saveConfig" />
        </div>
        <label class="checkbox-item">
          <input v-model="loopSlide" type="checkbox" @change="saveConfig" />
          循环播放
        </label>
        <button class="btn-primary" @click="toggleSlide">
          {{ slideRunning ? '停止播放' : '幻灯片播放' }}
        </button>
      </div>
    </header>

    <div class="breadcrumb">
      <span class="breadcrumb-item" @click="changeDir('')">根目录</span>
      <span v-for="(item, idx) in breadPathList" :key="idx" class="breadcrumb-item" @click="changeDir(item)">
        / {{ item }}
      </span>
    </div>

    <div class="waterfall">
      <div
        v-for="media in mediaList"
        :key="media.path"
        class="waterfall-card"
        @click="handleCardClick(media)"
      >
        <div class="card-media">
          <img v-if="media.type === 'image'" :src="media.thumb" alt="" class="card-img" />
          <div v-else-if="media.type === 'video'" class="video-wrap">
            <img :src="media.thumb" alt="" class="card-img" />
            <div class="play-icon">▶</div>
          </div>
          <div v-else class="folder-wrap">
            <div class="folder-icon">📁</div>
            <div class="folder-name">{{ media.name }}</div>
          </div>
        </div>
        <div class="card-name">{{ media.name }}</div>
      </div>
    </div>

    <!-- 预览弹窗 -->
    <div
      v-show="previewShow"
      class="lightbox"
      @click="closePreview"
      @mouseenter="onLightboxEnter"
      @mouseleave="onLightboxLeave"
      @mousemove="onLightboxMouseMove"
      @wheel.prevent="handlePreviewWheel"
    >
      <div v-if="showArrows" class="lightbox-nav prev" @click.stop="prevMedia">❮</div>
      <div v-if="showArrows" class="lightbox-nav next" @click.stop="nextMedia">❯</div>

      <div class="lightbox-content" @click.stop>
        <div v-if="currentItem.type === 'image'" class="img-box" :style="imgStyle">
          <img :src="currentItem.src" alt="" :style="imgStyle" />
        </div>
        <video
          v-else-if="currentItem.type === 'video'"
          ref="videoRef"
          class="video-player"
          controls
          :src="currentItem.src"
        ></video>
      </div>

      <div v-if="showArrows" class="lightbox-footer">
        <span>{{ currentIndex + 1 }} / {{ slideList.length }}</span>
        <div class="footer-actions">
          <button @click="rotateLeft">↺ 左旋</button>
          <button @click="rotateRight">↻ 右旋</button>
          <button @click="resetScale">重置缩放</button>
          <button @click="toggleFullscreen">全屏</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const currentDir = ref('')
const page = ref(1)
const pageSize = ref(30)
const hasMore = ref(true)
const loading = ref(false)
const mediaList = ref([])
const slideDelay = ref(5)
const loopSlide = ref(true)
const previewShow = ref(false)
const currentItem = ref({})
const slideRunning = ref(false)
let slideTimer = null
let scrollDebounceTimer = null

const isFullscreen = ref(false)
const showArrows = ref(false)
const previewLoading = ref(false)
const rotateDeg = ref(0)
const videoRef = ref(null)

// 缩放、拖拽变量
const scale = ref(1)
const panX = ref(0)
const panY = ref(0)
let isDragging = false
let dragStartX = 0
let dragStartY = 0
let dragStartPanX = 0
let dragStartPanY = 0
const MIN_SCALE = 0.3
const MAX_SCALE = 5
const SCALE_STEP = 0.12

// 鼠标闲置自动隐藏
let idleTimer = null
const IDLE_HIDE_DELAY = 3000

const breadSegments = computed(() => {
  return currentDir.value.split('/').filter(s => s)
})
const breadPathList = computed(() => {
  const arr = []
  let tmp = ''
  for (const s of breadSegments.value) {
    tmp = tmp ? `${tmp}/${s}` : s
    arr.push(tmp)
  }
  return arr
})
const slideList = computed(() => {
  return mediaList.value.filter(i => i.type !== 'folder')
})
const currentIndex = computed(() => {
  return slideList.value.findIndex(i => i.path === currentItem.value.path)
})
const imgStyle = computed(() => {
  return {
    transform: `rotate(${rotateDeg.value}deg) scale(${scale.value}) translate(${panX.value}px, ${panY.value}px)`
  }
})

async function changeDir(path) {
  currentDir.value = path
  page.value = 1
  mediaList.value = []
  hasMore.value = true
  await fetchMedia()
}

async function fetchMedia() {
  if (!hasMore.value || loading.value) return
  loading.value = true
  try {
    const params = new URLSearchParams({
      dir: currentDir.value,
      page: page.value,
      size: pageSize.value
    })
    const res = await fetch(`/api/list?${params}`)
    const json = await res.json()
    const mapped = json.list.map(item => {
      if (item.type === 'folder') return { ...item }
      const src = `/api/media?path=${encodeURIComponent(item.path)}`
      const thumb = item.type === 'image' ? src : `/api/thumb?path=${encodeURIComponent(item.path)}`
      return { ...item, src, thumb }
    })
    mediaList.value.push(...mapped)
    hasMore.value = json.page * json.size < json.total
    page.value += 1
  } catch (e) {
    console.warn('加载媒体失败：', e)
  } finally {
    loading.value = false
  }
}

function handleCardClick(item) {
  if (item.type === 'folder') {
    changeDir(item.path)
  } else {
    openPreview(item)
  }
}

async function loadConfig() {
  try {
    const res = await fetch('/api/get-setting')
    const cfg = await res.json()
    slideDelay.value = cfg.slide_delay || 5
    loopSlide.value = cfg.loop_slide ?? true
  } catch (e) {
    console.warn('读取配置失败', e)
  }
}

async function saveConfig() {
  try {
    await fetch('/api/save-setting', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        slide_delay: slideDelay.value,
        loop_slide: loopSlide.value
      })
    })
  } catch (e) {
    console.warn('保存配置失败', e)
  }
}

function preloadAdjacent(index) {
  const len = slideList.value.length
  if (len <= 1) return
  const prevIdx = (index - 1 + len) % len
  const nextIdx = (index + 1) % len
  new Image().src = slideList.value[prevIdx].src
  new Image().src = slideList.value[nextIdx].src
}

function resetScale() {
  scale.value = 1
  panX.value = 0
  panY.value = 0
  resetIdleTimer()
}

async function openPreview(item) {
  previewLoading.value = true
  const idx = slideList.value.findIndex(i => i.path === item.path)
  currentItem.value = slideList.value[idx]
  rotateDeg.value = 0
  resetScale()
  previewShow.value = true
  showArrows.value = true
  preloadAdjacent(idx)
  resetIdleTimer()
  setTimeout(() => { previewLoading.value = false }, 200)
}

async function closePreview() {
  previewShow.value = false
  stopSlide()
  clearIdleTimer()
  rotateDeg.value = 0
  resetScale()
  if (document.fullscreenElement) {
    await document.exitFullscreen().catch(() => {})
  }
  isFullscreen.value = false
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.src = ''
  }
}

async function toggleFullscreen() {
  if (!document.fullscreenElement) {
    await document.documentElement.requestFullscreen().catch(err => console.log('全屏失败', err))
    isFullscreen.value = true
  } else {
    await document.exitFullscreen().catch(() => {})
    isFullscreen.value = false
  }
}

function prevMedia() {
  if (slideList.value.length === 0) return
  previewLoading.value = true
  let idx = currentIndex.value
  idx = idx <= 0 ? slideList.value.length - 1 : idx - 1
  currentItem.value = slideList.value[idx]
  rotateDeg.value = 0
  resetScale()
  preloadAdjacent(idx)
  resetIdleTimer()
  setTimeout(() => { previewLoading.value = false }, 150)
}

function nextMedia() {
  if (slideList.value.length === 0) return
  previewLoading.value = true
  let idx = currentIndex.value
  if (loopSlide.value) {
    idx = idx >= slideList.value.length - 1 ? 0 : idx + 1
    currentItem.value = slideList.value[idx]
    rotateDeg.value = 0
    resetScale()
    preloadAdjacent(idx)
    resetIdleTimer()
  } else {
    if (idx >= slideList.value.length - 1) {
      closePreview()
      return
    }
    idx = idx + 1
    currentItem.value = slideList.value[idx]
    rotateDeg.value = 0
    resetScale()
    preloadAdjacent(idx)
    resetIdleTimer()
  }
  setTimeout(() => { previewLoading.value = false }, 150)
}

function rotateLeft() {
  rotateDeg.value -= 90
  resetScale()
  resetIdleTimer()
}
function rotateRight() {
  rotateDeg.value += 90
  resetScale()
  resetIdleTimer()
}

function toggleSlide() {
  slideRunning.value ? stopSlide() : startSlide()
}

function startSlide() {
  if (slideList.value.length === 0) return
  slideRunning.value = true
  if (!previewShow.value) {
    openPreview(slideList.value[0])
  }
  clearInterval(slideTimer)
  slideTimer = setInterval(() => {
    nextMedia()
  }, slideDelay.value * 1000)
}

function stopSlide() {
  clearInterval(slideTimer)
  slideTimer = null
  slideRunning.value = false
  clearIdleTimer()
  showArrows.value = true
}

function clearIdleTimer() {
  if (idleTimer) {
    clearTimeout(idleTimer)
    idleTimer = null
  }
}
function resetIdleTimer() {
  clearIdleTimer()
  if (slideRunning.value) {
    showArrows.value = true
    idleTimer = setTimeout(() => {
      showArrows.value = false
    }, IDLE_HIDE_DELAY)
  }
}

function onLightboxEnter() {
  if (!slideRunning.value) {
    showArrows.value = true
  } else {
    resetIdleTimer()
  }
}
function onLightboxLeave() {
  if (!slideRunning.value) {
    showArrows.value = false
  } else {
    clearIdleTimer()
  }
}
function onLightboxMouseMove() {
  if (slideRunning.value) {
    resetIdleTimer()
  }
}

function handlePreviewWheel(e) {
  if (currentItem.value.type !== 'image') return
  const delta = e.deltaY > 0 ? -SCALE_STEP : SCALE_STEP
  let newScale = scale.value + delta
  newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, newScale))
  scale.value = newScale
  resetIdleTimer()
}

function onPanStart(e) {
  if (currentItem.value.type !== 'image') return
  isDragging = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  dragStartPanX = panX.value
  dragStartPanY = panY.value
  resetIdleTimer()
}
function onPanMove(e) {
  if (!isDragging) return
  const dx = e.clientX - dragStartX
  const dy = e.clientY - dragStartY
  panX.value = dragStartPanX + dx
  panY.value = dragStartPanY + dy
  resetIdleTimer()
}
function onPanEnd() {
  isDragging = false
}

function onKeydown(e) {
  if (!previewShow.value) return
  resetIdleTimer()
  if (e.key === 'ArrowLeft') {
    e.preventDefault()
    prevMedia()
  }
  if (e.key === 'ArrowRight') {
    e.preventDefault()
    nextMedia()
  }
  if (e.key === 'Escape') closePreview()
  if (currentItem.value?.type === 'image') {
    if (e.key.toLowerCase() === 'r') {
      if (e.shiftKey) rotateLeft()
      else rotateRight()
    }
    if (e.key === '0') resetScale()
  }
}

function onScroll() {
  clearTimeout(scrollDebounceTimer)
  scrollDebounceTimer = setTimeout(() => {
    const bottom = document.documentElement.scrollHeight - window.innerHeight - window.scrollY
    if (bottom < 250) fetchMedia()
  }, 120)
}

onMounted(async () => {
  await loadConfig()
  await fetchMedia()
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('keydown', onKeydown)
  document.addEventListener('pointerdown', onPanStart)
  document.addEventListener('pointermove', onPanMove)
  document.addEventListener('pointerup', onPanEnd)
  document.addEventListener('pointercancel', onPanEnd)
  document.addEventListener('fullscreenchange', () => {
    isFullscreen.value = !!document.fullscreenElement
  })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('keydown', onKeydown)
  clearInterval(slideTimer)
  clearTimeout(scrollDebounceTimer)
  clearIdleTimer()
})
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  background: #121212;
  color: #eee;
  padding: 16px;
  box-sizing: border-box;
  font-family: system-ui, sans-serif;
}
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap:12px;
  margin-bottom:16px;
}
.title {
  margin:0;
  font-size:22px;
}
.control-bar {
  display:flex;
  gap:12px;
  align-items:center;
  flex-wrap:wrap;
}
.input-group {
  display:flex;
  align-items:center;
  gap:6px;
}
.input-group input {
  width:70px;
  padding:4px 6px;
  border-radius:4px;
  border:0;
  outline:none;
}
.checkbox-item {
  display:flex;
  align-items:center;
  gap:4px;
  cursor:pointer;
}
.btn-primary {
  padding:6px 14px;
  background:#2563eb;
  color:white;
  border:none;
  border-radius:6px;
  cursor:pointer;
}
.breadcrumb {
  display:flex;
  gap:6px;
  margin-bottom:16px;
  color:#aaa;
  flex-wrap:wrap;
}
.breadcrumb-item {
  cursor:pointer;
}
.breadcrumb-item:hover {
  color:#fff;
  text-decoration:underline;
}
.waterfall {
  column-count: 4;
  column-gap: 14px;
}
.waterfall-card {
  break-inside: avoid;
  margin-bottom:14px;
  background:#1e1e1e;
  border-radius:10px;
  overflow:hidden;
  cursor:pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.waterfall-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 20px #0006;
}
.card-media {
  width:100%;
  background:#2a2a2a;
}
.card-img {
  width:100%;
  display:block;
}
.video-wrap {
  position:relative;
}
.play-icon {
  position:absolute;
  top:50%;
  left:50%;
  transform:translate(-50%,-50%);
  font-size:32px;
  color:white;
  background:#0007;
  width:50px;
  height:50px;
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
}
.folder-wrap {
  padding:30px 10px;
  text-align:center;
}
.folder-icon {
  font-size:48px;
  margin-bottom:8px;
}
.folder-name {
  font-size:14px;
}
.card-name {
  padding:8px 10px;
  font-size:14px;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.lightbox {
  position:fixed;
  inset:0;
  background:#000d;
  z-index:999;
  display:flex;
  align-items:center;
  justify-content:center;
}
.lightbox-content {
  max-width:90vw;
  max-height:90vh;
  overflow:hidden;
}
.img-box {
  display:flex;
  align-items:center;
  justify-content:center;
  cursor:grab;
}
.img-box:active {
  cursor:grabbing;
}
.img-box img {
  max-width:90vw;
  max-height:90vh;
  object-fit:contain;
  transition: transform 0.1s;
}
.video-player {
  max-width:90vw;
  max-height:90vh;
}
.lightbox-nav {
  position:absolute;
  top:50%;
  transform:translateY(-50%);
  width:44px;
  height:44px;
  display:flex;
  align-items:center;
  justify-content:center;
  background:#0007;
  color:white;
  border-radius:50%;
  cursor:pointer;
  font-size:20px;
  user-select:none;
  transition:opacity 0.2s;
}
.prev { left:20px; }
.next { right:20px; }
.lightbox-footer {
  position:absolute;
  bottom:20px;
  left:50%;
  transform:translateX(-50%);
  background:#0008;
  padding:10px 16px;
  border-radius:8px;
  display:flex;
  gap:16px;
  align-items:center;
}
.footer-actions {
  display:flex;
  gap:8px;
}
.footer-actions button {
  padding:4px 8px;
  border:none;
  border-radius:4px;
  cursor:pointer;
}
</style>
 