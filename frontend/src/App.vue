<template>
  <div class="app-container">
    <!-- 顶部导航栏 -->
    <header class="header-bar">
      <div class="breadcrumb">
        <span @click="goRoot" class="crumb-item">根目录</span>
        <span v-for="(item, idx) in breadcrumbs" :key="idx" class="crumb-sep">/</span>
        <span v-for="(item, idx) in breadcrumbs" :key="idx" @click="clickCrumb(idx)" class="crumb-item">{{ item.name }}</span>
      </div>
      <div class="header-actions">
        <button @click="viewMode = 'waterfall'" :class="{active: viewMode === 'waterfall'}">瀑布流</button>
        <button @click="viewMode = 'list'" :class="{active: viewMode === 'list'}">平铺目录</button>
        <button @click="openSetting">设置</button>
      </div>
    </header>

    <!-- 内容区域 -->
    <main class="main-content">
      <!-- 平铺列表模式 -->
      <div v-if="viewMode === 'list'" class="folder-list">
        <div v-for="item in folderData" :key="item.path" class="folder-row" @click="enterFolder(item)">
          <span class="folder-icon">📁</span>
          <span class="folder-name">{{ item.name }}</span>
        </div>
      </div>

      <!-- 瀑布流模式（重点优化，大图卡片） -->
      <div v-if="viewMode === 'waterfall'" class="waterfall-wrap">
        <div v-for="item in mediaData" :key="item.path" class="media-card" @click="openMedia(item)">
          <div class="card-thumb">
            <img v-if="item.type === 'image'" :src="`/api/media?path=${encodeURIComponent(item.path)}`" alt="">
            <img v-if="item.type === 'video'" :src="`/api/thumb?path=${encodeURIComponent(item.path)}`" alt="">
            <div v-if="item.type === 'video'" class="play-icon">▶</div>
          </div>
          <div class="card-name">{{ item.name }}</div>
        </div>
      </div>
    </main>

    <!-- 图片/视频弹窗查看器 -->
    <div v-if="viewerShow" class="viewer-mask" @click.self="closeViewer">
      <div class="viewer-wrap">
        <button class="close-btn" @click="closeViewer">×</button>
        <div v-if="currentMedia.type === 'image'" class="image-viewer">
          <img :src="`/api/media?path=${encodeURIComponent(currentMedia.path)}`" alt="">
        </div>
        <div v-if="currentMedia.type === 'video'" class="video-viewer">
          <video controls autoplay :src="`/api/media?path=${encodeURIComponent(currentMedia.path)}`"></video>
        </div>
        <div class="slide-control">
          <button @click="prevMedia">上一张</button>
          <button @click="nextMedia">下一张</button>
          <button @click="toggleSlidePlay">{{ slidePlaying ? '停止轮播' : '幻灯片播放' }}</button>
        </div>
      </div>
    </div>

    <!-- 设置弹窗 -->
    <div v-if="settingShow" class="setting-mask" @click.self="settingShow=false">
      <div class="setting-panel">
        <h3>设置</h3>
        <div class="setting-row">
          <label>幻灯片间隔（秒）：</label>
          <input v-model.number="slideDelay" type="number" min="1">
        </div>
        <button @click="saveSetting">保存</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'

const viewMode = ref('waterfall')
const breadcrumbs = ref([])
const folderData = ref([])
const mediaData = ref([])

const viewerShow = ref(false)
const currentMedia = ref(null)
const mediaIndex = ref(0)
const slidePlaying = ref(false)
const slideDelay = ref(3)
let slideTimer = null

const settingShow = ref(false)

// 加载目录
async function loadDir(path = '/') {
  const res = await fetch(`/api/list?path=${encodeURIComponent(path)}`)
  const json = await res.json()
  folderData.value = json.folders
  mediaData.value = json.files
}

// 面包屑
function goRoot() {
  breadcrumbs.value = []
  loadDir('/')
}
function clickCrumb(idx) {
  breadcrumbs.value = breadcrumbs.value.slice(0, idx + 1)
  const fullPath = breadcrumbs.value.map(i => i.name).join('/')
  loadDir('/' + fullPath)
}
function enterFolder(item) {
  breadcrumbs.value.push(item)
  loadDir(item.path)
}

// 媒体弹窗
function openMedia(item) {
  currentMedia.value = item
  mediaIndex.value = mediaData.value.findIndex(m => m.path === item.path)
  viewerShow.value = true
}
function closeViewer() {
  viewerShow.value = false
  slidePlaying.value = false
  clearInterval(slideTimer)
}
function prevMedia() {
  mediaIndex.value = mediaIndex.value <= 0 ? mediaData.value.length -1 : mediaIndex.value -1
  currentMedia.value = mediaData.value[mediaIndex.value]
}
function nextMedia() {
  mediaIndex.value = mediaIndex.value >= mediaData.value.length -1 ? 0 : mediaIndex.value +1
  currentMedia.value = mediaData.value[mediaIndex.value]
}
function toggleSlidePlay() {
  slidePlaying.value = !slidePlaying.value
  if (slidePlaying.value) {
    slideTimer = setInterval(()=> nextMedia(), slideDelay.value * 1000)
  } else {
    clearInterval(slideTimer)
  }
}

// 设置
function openSetting() {
  settingShow.value = true
}
async function saveSetting() {
  await fetch('/api/config', {
    method:'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({slideDelay: slideDelay.value})
  })
  settingShow.value = false
}
async function loadConfig() {
  const res = await fetch('/api/config')
  const cfg = await res.json()
  slideDelay.value = cfg.slideDelay ?? 3
}

onMounted(()=>{
  loadDir('/')
  loadConfig()
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
  background-color: #121212;
  color: #eee;
}
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: #1e1e1e;
  border-bottom: 1px solid #2d2d2d;
  position: sticky;
  top:0;
  z-index: 10;
}
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
}
.crumb-item {
  color: #8ab4f8;
  cursor: pointer;
}
.crumb-sep {
  color:#666;
}
.header-actions button {
  padding: 6px 12px;
  margin-left: 6px;
  background:#2b2b2b;
  color:#fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.header-actions button.active {
  background:#3b78d9;
}
.main-content {
  padding: 16px;
}

/* ========== 重点：优化后的瀑布流样式，匹配你效果图 ========== */
.waterfall-wrap {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  grid-template-rows: masonry;
}
.media-card {
  background: #1e1e1e;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.media-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 22px rgba(0,0,0,0.45);
}
.card-thumb {
  width:100%;
  overflow:hidden;
  background:#222;
}
.card-thumb img {
  width:100%;
  height:auto;
  display:block;
}
.play-icon {
  position:absolute;
  top: 50%;
  left:50%;
  transform: translate(-50%, -50%);
  font-size:32px;
  color:#fff;
  background:rgba(0,0,0,0.45);
  width: 48px;
  height:48px;
  border-radius: 50%;
  display:flex;
  align-items:center;
  justify-content:center;
}
.card-thumb {
  position: relative;
}
.card-name {
  padding: 8px 10px;
  font-size: 13px;
  color:#ccc;
  white-space: nowrap;
  overflow:hidden;
  text-overflow: ellipsis;
}

/* 平铺目录 */
.folder-list {
  display:flex;
  flex-direction: column;
  gap: 8px;
}
.folder-row {
  padding:10px 14px;
  background:#1e1e1e;
  border-radius:8px;
  cursor:pointer;
}
.folder-icon {
  margin-right:8px;
}

/* 查看弹窗 */
.viewer-mask {
  position: fixed;
  inset:0;
  background:rgba(0,0,0,0.88);
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:99;
}
.viewer-wrap {
  max-width: 90vw;
  max-height:90vh;
  position:relative;
}
.close-btn {
  position:absolute;
  top:-32px;
  right:0;
  font-size:28px;
  color:#fff;
  background:none;
  border:none;
  cursor:pointer;
}
.image-viewer img {
  max-width:90vw;
  max-height:85vh;
  display:block;
}
.video-viewer video {
  max-width:90vw;
  max-height:85vh;
}
.slide-control {
  margin-top:12px;
  display:flex;
  gap:10px;
  justify-content:center;
}
.slide-control button {
  padding:6px 12px;
}

/* 设置弹窗 */
.setting-mask {
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.75);
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:99;
}
.setting-panel {
  background:#1e1e1e;
  padding:24px;
  border-radius:10px;
}
.setting-row {
  margin:14px 0;
}
.setting-row input {
  width: 80px;
  padding:4px;
}
</style>
