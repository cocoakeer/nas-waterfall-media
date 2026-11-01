<template>
  <div class="app-container">
    <header class="header">
      <h1>NAS 媒体瀑布流</h1>
      <div class="header-actions">
        <button @click="openSlideSetting" class="btn">幻灯片设置</button>
        <button @click="startSlide" class="btn primary">开始幻灯片</button>
      </div>
    </header>

    <div class="breadcrumb">
      <span @click="changeDir('')" class="breadcrumb-item">根目录</span>
      <span v-for="(item, idx) in breadcrumbList" :key="idx">
        <span class="separator">/</span>
        <span @click="changeDir(item.path)" class="breadcrumb-item">{{ item.name }}</span>
      </span>
    </div>

    <div class="waterfall">
      <div
        v-for="item in mediaList"
        :key="item.id"
        class="media-card"
        @click="handleCardClick(item)"
      >
        <div class="card-thumb">
          <template v-if="item.type === 'folder'">
            <!-- 文件夹：优先cover_path封面图，无封面显示黄色文件夹svg -->
            <img v-if="item.cover_path" :src="getThumbUrl(item.cover_path)" alt="" />
            <svg v-else width="80" height="80" viewBox="0 0 24 24" fill="#f0c040">
              <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
            </svg>
          </template>
          <img v-else-if="item.type === 'image'" :src="getThumbUrl(item.path)" alt="" />
          <div v-else-if="item.type === 'video'" class="video-wrap">
            <img :src="getThumbUrl(item.path)" alt="" />
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
        <div v-if="previewItem.type === 'image'" class="preview-media">
          <img :src="getSrcUrl(previewItem.path)" alt="" />
        </div>
        <div v-else class="preview-media">
          <video controls :src="getSrcUrl(previewItem.path)"></video>
        </div>
        <div class="preview-name">{{ previewItem.name }}</div>
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
    <div v-if="slideShow" class="slide-mask" @click="slideShow=false">
      <div class="slide-content">
        <img v-if="currentSlide.type==='image'" :src="getSrcUrl(currentSlide.path)" alt="" />
        <video v-else controls :src="getSrcUrl(currentSlide.path)"></video>
        <div class="slide-name">{{ currentSlide.name }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const baseUrl = ''
const mediaList = ref([])
const breadcrumbList = ref([])

const previewShow = ref(false)
const previewItem = ref(null)
let previewMediaList = []
let previewCurrentIndex = 0

const settingShow = ref(false)
const slideDelay = ref(3)
const slideLoop = ref(true)
const slideShow = ref(false)
const slideIndex = ref(0)
const slideTimer = ref(null)
const slideList = ref([])
const currentSlide = ref({})

const getThumbUrl = (path) => {
  return `${baseUrl}/api/thumb?path=${encodeURIComponent(path)}`
}
const getSrcUrl = (path) => {
  return `${baseUrl}/api/src?path=${encodeURIComponent(path)}`
}

async function loadMedia(dir = '') {
  try {
    const res = await fetch(`${baseUrl}/api/list?dir=${encodeURIComponent(dir)}`)
    if (!res.ok) throw new Error()
    const data = await res.json()
    mediaList.value = data.list || []
    breadcrumbList.value = data.breadcrumb || []
  } catch (err) {
    console.error(err)
    mediaList.value = []
  }
}

function changeDir(path) {
  loadMedia(path)
}

function handleCardClick(item) {
  if (item.type === 'folder') {
    changeDir(item.path)
  } else {
    previewMediaList = mediaList.value.filter(x => x.type !== 'folder')
    previewCurrentIndex = previewMediaList.findIndex(x => x.id === item.id)
    previewItem.value = item
    previewShow.value = true
  }
}

function prevMedia() {
  if (previewCurrentIndex > 0) {
    previewCurrentIndex -= 1
    previewItem.value = previewMediaList[previewCurrentIndex]
  }
}
function nextMedia() {
  if (previewCurrentIndex < previewMediaList.length - 1) {
    previewCurrentIndex += 1
    previewItem.value = previewMediaList[previewCurrentIndex]
  }
}

function handleKeydown(e) {
  if (!previewShow.value) return
  switch(e.key) {
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
function startSlide() {
  slideList.value = mediaList.value.filter(i => i.type === 'image')
  if (slideList.value.length === 0) return alert('当前目录没有图片，无法幻灯片')
  slideIndex.value = 0
  slideShow.value = true
  runSlide()
}
function runSlide() {
  clearTimeout(slideTimer.value)
  currentSlide.value = slideList.value[slideIndex.value]
  slideTimer.value = setTimeout(() => {
    slideIndex.value++
    if (slideIndex.value >= slideList.value.length) {
      if (slideLoop.value) slideIndex.value = 0
      else { slideShow.value = false; return }
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

onMounted(()=>{
  document.addEventListener('keydown', handleKeydown)
})
onUnmounted(()=>{
  document.removeEventListener('keydown', handleKeydown)
})

loadMedia()
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
.btn.primary {
  background: #2563eb;
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

.waterfall {
  display: flex;
  flex-wrap: wrap;
  gap:14px;
}
.media-card {
  width: calc(25% - 11px);
  background: #1e1e1e;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.media-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(0,0,0,0.32);
}
.card-thumb {
  width:100%;
  height:180px;
  overflow: hidden;
  background:#222;
  position:relative;
  display:flex;
  align-items:center;
  justify-content:center;
}
.card-thumb img {
  width:100%;
  height:100%;
  object-fit:cover;
  display:block;
}
.play-icon {
  position:absolute;
  top:50%;
  left:50%;
  transform:translate(-50%,-50%);
  width:44px;
  height:44px;
  background:rgba(0,0,0,0.6);
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:18px;
  color:#fff;
}
.card-name {
  padding:10px 12px;
  font-size:13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width:1200px) {
  .media-card {
    width: calc(33.333% - 10px);
  }
}
@media (max-width:768px) {
  .media-card {
    width: calc(50% - 7px);
  }
}
@media (max-width:480px) {
  .media-card {
    width:100%;
  }
}

.preview-mask {
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.85);
  z-index:99;
  display:flex;
  align-items:center;
  justify-content:center;
}
.preview-box {
  background:#181818;
  border-radius:12px;
  padding:12px;
  max-width:90vw;
  max-height:90vh;
  position:relative;
}
.close-btn {
  position:absolute;
  top: 4px;
  right: 4px;
  width:28px;
  height:28px;
  border-radius:50%;
  background:#333;
  color:#fff;
  border:none;
  font-size:20px;
  cursor:pointer;
  z-index:2;
}
.preview-media {
  max-width:85vw;
  max-height:80vh;
}
.preview-media img, .preview-media video {
  max-width:100%;
  max-height:80vh;
  display:block;
}
.preview-name {
  text-align:center;
  margin-top:8px;
  font-size:14px;
}

.setting-box {
  background:#181818;
  border-radius:12px;
  padding:24px;
  width:360px;
}
.form-row {
  margin:14px 0;
  display:flex;
  justify-content:space-between;
  align-items:center;
}
.btn-group {
  display:flex;
  gap:10px;
  justify-content:flex-end;
  margin-top:20px;
}

.slide-mask {
  position:fixed;
  inset:0;
  background:#000;
  z-index:100;
  display:flex;
  align-items:center;
  justify-content:center;
}
.slide-content img, .slide-content video {
  max-width:98vw;
  max-height:98vh;
}
.slide-name {
  position:absolute;
  bottom:16px;
  color:#fff;
  font-size:14px;
}
</style>
