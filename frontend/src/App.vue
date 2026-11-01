<template>
  <div class="app-wrap">
    <header class="header-bar">
      <div class="breadcrumb">
        <span @click="goRoot">根目录</span>
        <span v-for="(item, idx) in breadList" :key="idx" class="sep">/</span>
        <span v-for="(item, idx) in breadList" :key="idx" @click="navBread(idx)">{{ item }}</span>
      </div>
      <div class="ctrl-group">
        <span>幻灯片间隔(秒)</span>
        <input v-model.number="slideDelay" type="number" min="1" class="inp">
        <label class="check">
          <input v-model="loopPlay" type="checkbox">循环播放
        </label>
        <button @click="startSlide" class="btn">幻灯片播放</button>
      </div>
    </header>

    <div class="waterfall">
      <div v-for="item in mediaList" :key="item.path" class="card">
        <div v-if="item.type === 'folder'" class="folder-card" @click="openFolder(item.path)">
          <div class="folder-preview">
            <img v-if="item.cover" :src="item.cover" class="cover-img" alt="">
            <div v-else class="folder-icon">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="#999">
                <path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
              </svg>
            </div>
          </div>
          <div class="folder-name">{{ item.name }}</div>
        </div>

        <div v-else class="media-card" @click="openMedia(item)">
          <div class="media-preview">
            <img :src="item.thumb" class="cover-img" alt="">
            <div v-if="item.type==='video'" class="play-mark">▶</div>
          </div>
          <div class="media-name">{{ item.name }}</div>
        </div>
      </div>
    </div>

    <!-- 幻灯片弹窗 -->
    <div v-if="slideOpen" class="slide-modal" @click.self="closeSlide">
      <div class="slide-inner">
        <img v-if="curItem.type==='image'" :src="`/api/src?path=${curItem.path}`" class="slide-media">
        <video v-else-if="curItem.type==='video'" :src="`/api/src?path=${curItem.path}`" controls autoplay class="slide-media"></video>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from "vue"
const curDir = ref("")
const breadList = ref([])
const mediaList = ref([])
const slideDelay = ref(3)
const loopPlay = ref(false)
const slideOpen = ref(false)
const curIdx = ref(0)
const curItem = ref(null)
const slideTimer = ref(null)
const imgOnlyList = ref([])

async function loadSetting() {
  const res = await fetch("/api/get-setting")
  const d = await res.json()
  slideDelay.value = d.slide_delay ?? 3
  loopPlay.value = !!d.loop
}
async function saveSetting() {
  await fetch("/api/save-setting", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({slide_delay: slideDelay.value, loop: loopPlay.value})
  })
}

async function loadList() {
  const q = new URLSearchParams({dir:curDir.value, page:1, size:999})
  const res = await fetch(`/api/list?${q}`)
  const dat = await res.json()
  mediaList.value = dat.list
  imgOnlyList.value = dat.list.filter(x=>x.type==="image")
  breadList.value = curDir.value.split("/").filter(Boolean)
}
function goRoot() {
  curDir.value = ""
}
function openFolder(p) {
  curDir.value = p
}
function navBread(idx) {
  curDir.value = breadList.value.slice(0, idx+1).join("/")
}
function openMedia(it) {
  curItem.value = it
  slideOpen.value = true
  stopTimer()
}
function startSlide() {
  if(!imgOnlyList.value.length) return alert("当前目录无图片")
  curIdx.value = 0
  curItem.value = imgOnlyList.value[0]
  slideOpen.value = true
  runSlide()
}
function runSlide() {
  stopTimer()
  slideTimer.value = setInterval(()=>{
    curIdx.value++
    if(curIdx.value >= imgOnlyList.value.length) {
      if(loopPlay.value) curIdx.value = 0
      else {closeSlide();return}
    }
    curItem.value = imgOnlyList.value[curIdx.value]
  }, slideDelay.value * 1000)
}
function stopTimer() {
  if(slideTimer.value) clearInterval(slideTimer.value)
}
function closeSlide() {
  slideOpen.value = false
  stopTimer()
}
watch([slideDelay, loopPlay], ()=>saveSetting())
watch(curDir, loadList, {immediate:true})
onMounted(loadSetting)
</script>

<style scoped>
.app-wrap {
  min-height:100vh;
  background:#121212;
  color:#eee;
  padding:16px;
  box-sizing:border-box;
}
.header-bar {
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:16px;
  flex-wrap:wrap;
  gap:12px;
}
.breadcrumb {
  font-size:15px;
}
.breadcrumb span {
  cursor:pointer;
  color:#8cf;
}
.sep {
  margin:0 6px;
  color:#666;
  cursor:default !important;
}
.ctrl-group {
  display:flex;
  align-items:center;
  gap:8px;
}
.inp {
  width:60px;
  background:#222;
  border:1px solid #444;
  color:#fff;
  padding:4px;
  border-radius:4px;
}
.check {
  display:flex;
  align-items:center;
  gap:4px;
}
.btn {
  background:#2563eb;
  color:white;
  border:none;
  padding:6px 12px;
  border-radius:6px;
  cursor:pointer;
}
.waterfall {
  display:grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap:14px;
}
.card {
  background:#1e1e1e;
  border-radius:10px;
  overflow:hidden;
  cursor:pointer;
  transition:0.2s;
}
.card:hover {
  transform:translateY(-3px);
  box-shadow:0 6px 14px #0006;
}
.folder-preview, .media-preview {
  width:100%;
  aspect-ratio:16/12;
  background:#292929;
  display:flex;
  align-items:center;
  justify-content:center;
  overflow:hidden;
  position:relative;
}
.cover-img {
  width:100%;
  height:100%;
  object-fit:cover;
}
.folder-icon svg {
  opacity:0.6;
}
.play-mark {
  position:absolute;
  width:40px;height:40px;
  background:#0008;
  border-radius:50%;
  color:white;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:18px;
}
.folder-name, .media-name {
  padding:8px 10px;
  font-size:14px;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.slide-modal {
  position:fixed;
  inset:0;
  background:#000c;
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:999;
}
.slide-media {
  max-width:90vw;
  max-height:90vh;
}
</style>
 