<template>
  <!-- 初始化加载中，完全屏蔽登录/主页面闪烁 -->
  <div v-if="initLoading" class="init-loading-mask">
    <div class="loading-text">正在加载...</div>
  </div>

  <!-- 登录弹窗 -->
  <div v-else-if="!isLogin" class="login-mask">
    <div class="login-box">
      <h2>NAS媒体瀑布流 - 登录</h2>
      <div class="form-item">
        <label>用户名</label>
        <input v-model="loginForm.username" type="text" @keyup.enter="doLogin" />
      </div>
      <div class="form-item">
        <label>密码</label>
        <input v-model="loginForm.password" type="password" @keyup.enter="doLogin" />
      </div>
      <div class="login-error" v-if="loginErr">{{loginErr}}</div>
      <div class="login-btn-group">
        <button @click="doLogin" class="btn primary">登录</button>
      </div>
    </div>
  </div>
  <div v-else class="app-container">
    <header class="header">
      <div class="header-left">
        <h1>NAS 媒体瀑布流</h1>
        <div class="user-dropdown-wrap">
          <div class="avatar-btn" @click="toggleUserDrop">
            <span class="avatar-circle">{{ avatarInitial }}</span>
            <span class="avatar-name">{{userInfo.username}}</span>
          </div>
          <transition name="drop">
            <div v-if="showUserDrop" class="user-dropdown">
              <div class="drop-section">
                <div v-if="cacheRunning" class="drop-item cache-status-item">缓存处理中 {{cachePercent}}%</div>
                <div v-else class="drop-item cache-run-item" @click="runCacheTask">
                  <span>预生成缓存</span>
                  <span class="cache-sub">未缓存 {{ cacheStats.uncached }}/{{ cacheStats.total }}</span>
                </div>
                <div v-if="cacheStats.last_finish_time" class="drop-item cache-meta">上次完成 {{ formatDateTime(cacheStats.last_finish_time) }}<template v-if="cacheStats.failed > 0"> · 失败 {{ cacheStats.failed }} 个</template></div>
                <div v-if="cacheRunning" class="drop-item" @click="stopCacheTask">取消缓存任务</div>
              </div>
              <div class="drop-section">
                <div class="drop-item drop-with-icon" @click="openChangePwdModal">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  <span>修改密码</span>
                </div>
                <div v-if="userInfo.is_admin" class="drop-item drop-with-icon" @click="openUserManageModal">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
                  <span>用户管理</span>
                </div>
              </div>
              <div class="drop-section">
                <div class="drop-item drop-with-icon drop-logout" @click="doLogout">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                  <span>退出登录</span>
                </div>
              </div>
            </div>
          </transition>
        </div>
      </div>
      <div class="header-actions">
        <div class="search-box">
          <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></svg>
          <input v-model="searchQuery" type="text" placeholder="搜索文件名" />
          <span v-if="searchQuery" class="search-clear" @click="searchQuery=''">×</span>
        </div>
        <div class="sort-select-wrap">
          <select v-model="sortBy" class="sort-select">
            <option value="name">按名称</option>
            <option value="time">按时间</option>
            <option value="size">按大小</option>
          </select>
          <svg class="sort-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
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

    <!-- JS横向优先瀑布流容器 MacBook优选270px -->
    <div ref="waterfallBoxRef" class="waterfall-wrap">
      <div v-if="isLoading" class="empty-state">加载中...</div>
      <div v-else-if="!displayList.length" class="empty-state">
        <template v-if="searchQuery">没有匹配「{{ searchQuery }}」的文件</template>
        <template v-else>当前目录为空</template>
      </div>
      <div
        v-for="item in displayList"
        :key="item.id"
        class="media-card"
        :style="{left: item._left + 'px', top: item._top + 'px'}"
        @click="handleCardClick(item)"
      >
        <div class="card-thumb">
          <template v-if="item.type === 'folder'">
            <img
              v-if="item.cover_path"
              :src="getThumbUrl(item.cover_path)"
              alt=""
              loading="lazy"
              decoding="async"
              :class="{loaded: item._loaded}"
              @load="onImageLoaded(item)"
            />
            <div v-else class="folder-placeholder">
              <svg width="80" height="80" viewBox="0 0 24 24" fill="#f0c040">
                <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z" />
              </svg>
            </div>
          </template>
          <img
            v-else-if="item.type === 'image'"
            :src="getThumbUrl(item.path)"
            alt=""
            loading="lazy"
            decoding="async"
            :class="{loaded: item._loaded}"
            @load="onImageLoaded(item)"
          />
          <div v-else-if="item.type === 'video'" class="video-wrap">
            <img
              :src="getThumbUrl(item.path)"
              alt=""
              loading="lazy"
              decoding="async"
              :class="{loaded: item._loaded}"
              @load="onImageLoaded(item)"
            />
            <div class="play-icon">▶</div>
          </div>
          <!-- 角标 -->
          <div v-if="item.type === 'folder'" class="card-badge badge-count">{{ item.count }}</div>
          <div v-else-if="item.type === 'video' && item.duration" class="card-badge badge-duration">{{ formatDuration(item.duration) }}</div>
          <!-- hover 元信息 -->
          <div class="card-overlay">
            <div class="card-overlay-name">{{ item.name }}</div>
            <div class="card-overlay-meta">
              <template v-if="item.size">{{ formatSize(item.size) }} · </template>{{ formatDate(item.mtime) }}
            </div>
          </div>
        </div>
        <div class="card-name">{{ item.name }}</div>
      </div>
    </div>

    <!-- 预览弹窗 -->
    <div v-if="previewShow" class="preview-mask" @click.self="closePreview">
      <div class="preview-box">
        <button class="close-btn" @click="closePreview">×</button>
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
    <!-- 修改本人密码弹窗 -->
    <div v-if="changePwdModal" class="preview-mask" @click.self="changePwdModal=false">
      <div class="setting-box">
        <h3>修改登录密码</h3>
        <div class="form-row">
          <label>原密码</label>
          <input v-model="pwdForm.old" type="password" />
        </div>
        <div class="form-row">
          <label>新密码</label>
          <input v-model="pwdForm.new" type="password" />
        </div>
        <div class="form-row">
          <label>确认新密码</label>
          <input v-model="pwdForm.confirm" type="password" />
        </div>
        <div class="msg-tip">{{pwdMsg}}</div>
        <div class="btn-group">
          <button @click="submitChangePwd" class="btn primary">保存</button>
          <button @click="changePwdModal=false" class="btn">取消</button>
        </div>
      </div>
    </div>
    <!-- ========== 用户管理弹窗【新版：列表 + 表单分离】 ========== -->
    <div v-if="userManageModal" class="preview-mask" @click.self="closeUserManageModal">
      <div class="user-manage-box">
        <div class="um-header">
          <h3>用户管理（管理员）</h3>
          <button class="um-close-btn" @click="closeUserManageModal">×</button>
        </div>
        <!-- 列表视图 -->
        <div v-if="umView === 'list'" class="um-content-wrap">
          <div class="um-top-bar">
            <button class="btn primary" @click="switchToAddForm">+ 新增用户</button>
          </div>
          <div class="um-table">
            <div class="um-table-head">
              <div class="col-uname">用户名</div>
              <div class="col-role">角色</div>
              <div class="col-dir">允许目录</div>
              <div class="col-op">操作</div>
            </div>
            <div class="um-table-row" v-for="u in adminUserList" :key="u.username">
              <div class="col-uname">{{u.username}}</div>
              <div class="col-role">
                <span v-if="u.is_admin" class="tag-admin">管理员</span>
                <span v-else class="tag-user">普通用户</span>
              </div>
              <div class="col-dir">{{u.allow_dirs.join("; ")}}</div>
              <div class="col-op">
                <button class="btn btn-sm" @click="switchToEditForm(u)">编辑</button>
                <button class="btn btn-sm btn-danger" @click="openDelConfirm(u)">删除</button>
              </div>
            </div>
          </div>
        </div>
        <!-- 新增/编辑表单视图 -->
        <div v-if="umView === 'form'" class="um-content-wrap">
          <div class="um-form-title">{{editUser ? "编辑用户":"新增用户"}}</div>
          <div class="um-form-item">
            <label>用户名</label>
            <div style="display:flex;gap:8px;">
              <input v-model="umForm.username" :disabled="!!editUser" />
              <button v-if="editUser" class="btn btn-sm" @click="triggerRename">修改用户名</button>
            </div>
          </div>
          <div class="um-form-item">
            <label>密码（编辑留空不修改）</label>
            <input v-model="umForm.password" type="password" placeholder="新增用户必填" />
          </div>
          <div class="um-form-item">
            <label>是否管理员</label>
            <input type="checkbox" v-model="umForm.is_admin" />
          </div>
          <div class="um-form-item">
            <label>允许访问目录（多选）</label>
            <div class="multi-select-wrap">
              <div v-for="opt in dirOptions" class="check-item">
                <input type="checkbox" :value="opt" v-model="umForm.allow_dirs" :id="'umdir_'+opt" />
                <label :for="'umdir_'+opt">{{opt}}</label>
              </div>
            </div>
          </div>
          <div class="msg-tip">{{adminMsg}}</div>
          <div class="um-form-buttons">
            <button class="btn" @click="switchToList">返回列表</button>
            <button class="btn primary" @click="submitUmForm">保存</button>
          </div>
        </div>
      </div>
      <!-- 删除确认弹窗 -->
      <div v-if="umDelConfirm.show" class="inner-confirm-mask">
        <div class="confirm-box">
          <p>确认删除用户【{{umDelConfirm.user.username}}】？</p>
          <div class="confirm-btn-row">
            <button class="btn" @click="umDelConfirm.show=false">取消</button>
            <button class="btn btn-danger" @click="doInnerDelete">确认删除</button>
          </div>
        </div>
      </div>
    </div>
    <!-- 幻灯片全屏渲染层 -->
    <div v-if="slideShow" class="slide-root">
      <div class="slide-content">
        <img v-if="currentSlide.type==='image'" :src="getSrcUrl(currentSlide.path)" alt="" />
        <video v-else controls :src="getSrcUrl(currentSlide.path)"></video>
        <div class="slide-name">{{ currentSlide.name }}</div>
        <button class="slide-exit-btn" @click="exitSlide">退出全屏</button>
        <button class="slide-prev-btn" @click="slidePrev">‹</button>
        <button class="slide-next-btn" @click="slideNext">›</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'

const baseUrl = ''
// 初始化加载标记：修复刷新闪现登录页
const initLoading = ref(true)
const isLogin = ref(false)
const userInfo = ref({})
// 头像首字母（用户名首字符大写）
const avatarInitial = computed(() => {
  const n = userInfo.value.username || '?'
  return n.charAt(0).toUpperCase()
})
const loginForm = ref({username:'', password:''})
const loginErr = ref('')

// 用户下拉菜单
const showUserDrop = ref(false)
// 修改密码弹窗
const changePwdModal = ref(false)
const pwdForm = ref({old:"",new:"",confirm:""})
const pwdMsg = ref("")

// ========= 用户管理【新版状态】 =========
const userManageModal = ref(false)
const umView = ref('list') // list / form
const editUser = ref(null) // null=新增；对象=编辑
const adminUserList = ref([])
const dirOptions = ref([])
const adminMsg = ref("")
const umForm = ref({
  username:"",
  password:"",
  is_admin:false,
  allow_dirs:[]
})
// 删除确认内部弹窗
const umDelConfirm = ref({
  show:false,
  user:null
})

const mediaList = ref([])
const breadcrumbList = ref([])
const waterfallBoxRef = ref(null)

// 搜索与排序
const searchQuery = ref('')
const sortBy = ref('name') // name | time | size

// 工具：格式化文件大小 / 日期 / 视频时长
function formatSize(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}
function formatDate(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
function formatDateTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function formatDuration(sec) {
  if (sec == null) return ''
  const s = Math.round(sec)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const p = (n) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`
}

// 过滤 + 排序后的展示列表
const displayList = computed(() => {
  let list = mediaList.value
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter((x) => x.name.toLowerCase().includes(q))
  }
  const sorted = [...list]
  if (sortBy.value === 'name') {
    sorted.sort((a, b) => a.name.localeCompare(b.name, 'zh'))
  } else if (sortBy.value === 'time') {
    sorted.sort((a, b) => (b.mtime || 0) - (a.mtime || 0))
  } else if (sortBy.value === 'size') {
    sorted.sort((a, b) => (b.size || 0) - (a.size || 0))
  }
  return sorted
})

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

const cacheRunning = ref(false)
const cachePercent = ref(0)
let statusPollTimer = null
// 缓存统计：total 全部 / cached 已缓存 / uncached 未缓存 / failed 失败 / last_finish_time 上次完成时间
const cacheStats = ref({ total: 0, cached: 0, uncached: 0, failed: 0, last_finish_time: null })

const STORAGE_KEY = "waterfall_last_dir"

// ========= JS瀑布流【响应式：手机2列 / 平板3-4列 / 桌面270px】 =========
let resizeTimer = null

// 根据容器宽度决定列数与卡片宽度（均分填满整行，无留白、无边界跳变）
function getCardLayout(boxWidth) {
  const gap = 12
  let colCount
  if (boxWidth < 480) {
    colCount = 2
  } else if (boxWidth < 768) {
    colCount = 3
  } else if (boxWidth < 1100) {
    colCount = 4
  } else {
    // 桌面：以约 270px 为目标列宽，取整列数，均分填满
    colCount = Math.max(4, Math.round((boxWidth + gap) / (270 + gap)))
  }
  const cardWidth = (boxWidth - gap * (colCount - 1)) / colCount
  return { cardWidth, gap, colCount }
}

/**
 * 横向优先（行优先）瀑布流计算
 * 逻辑：一行排满列数，再下一行
 */
function layoutWaterfall(){
  const list = displayList.value
  if(!waterfallBoxRef.value || !list.length) return
  const boxWidth = waterfallBoxRef.value.clientWidth
  const { cardWidth, gap, colCount } = getCardLayout(boxWidth)

  // 通过 CSS 变量联动卡片宽度与间距
  waterfallBoxRef.value.style.setProperty('--card-width', cardWidth + 'px')
  waterfallBoxRef.value.style.setProperty('--card-gap', gap + 'px')

  // 每列高度记录
  const colHeights = new Array(colCount).fill(0)

  list.forEach((item, idx)=>{
    // 行优先逻辑：索引 % 列数，实现一行一行横向排布
    const colIndex = idx % colCount
    const left = colIndex * (cardWidth + gap)

    const dom = waterfallBoxRef.value.children[idx]
    let cardH = 280
    if(dom) cardH = dom.offsetHeight || 280

    const top = colHeights[colIndex]
    colHeights[colIndex] = top + cardH + gap

    item._left = left
    item._top = top
  })

  // 设置容器总高度
  const maxH = Math.max(...colHeights)
  waterfallBoxRef.value.style.height = maxH + 'px'
}

// 图片加载完成：标记已加载（触发渐显）+ 防抖重布局
function onImageLoaded(item){
  item._loaded = true
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(()=>{
    layoutWaterfall()
  },120)
}

watch(displayList, async ()=>{
  await nextTick()
  layoutWaterfall()
})

function onWindowResize(){
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(()=>{
    layoutWaterfall()
  },150)
}

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

async function pollCacheStatus() {
  try {
    const res = await fetch(`${baseUrl}/api/cache-status`)
    if (!res.ok) { checkAuthResp(res); return }
    const st = await res.json()
    cachePercent.value = st.percent
    if (!st.running) {
      clearInterval(statusPollTimer)
      statusPollTimer = null
      cacheRunning.value = false
      loadCacheStats()
      alert(`✅缓存任务结束！\n${st.message}`)
    }
  } catch (err) {
    console.error("查询任务状态失败", err)
  }
}

async function initCheckCacheTask() {
  try {
    const res = await fetch(`${baseUrl}/api/cache-status`)
    if (!res.ok) { checkAuthResp(res); return }
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
    if (!res.ok) { checkAuthResp(res); return }
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
    if (!res.ok) { checkAuthResp(res); return }
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

function checkAuthResp(r) {
  if (r.status === 401) {
    isLogin.value = false
    userInfo.value = {}
  }
}

const isLoading = ref(false)
async function loadMedia(dir = '', pushHistory = false) {
  if(isLoading.value) return
  isLoading.value = true
  mediaList.value = []
  breadcrumbList.value = []
  try {
    const res = await fetch(`${baseUrl}/api/list?dir=${encodeURIComponent(dir)}`)
    if (!res.ok) { checkAuthResp(res); return }
    const data = await res.json()
    mediaList.value = data.list || []
    breadcrumbList.value = data.breadcrumb || []
    localStorage.setItem(STORAGE_KEY, dir)
    if (pushHistory) {
      syncDirToUrl(dir)
    }
  } catch (err) {
    console.error(err)
    mediaList.value = []
  }finally{
    isLoading.value = false
  }
}

function changeDir(path) {
  loadMedia(path, true)
}

function handleCardClick(item) {
  if(isLoading.value) return
  if (item.type === 'folder') {
    changeDir(item.path)
  } else {
    previewMediaList = displayList.value.filter(x => x.type !== 'folder')
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
  if (slideShow.value) {
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      slidePrev()
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      slideNext()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      exitSlide()
    }
    return
  }
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

async function loadSlideSettings() {
  try {
    const res = await fetch(`${baseUrl}/api/settings`)
    if (!res.ok) return
    const j = await res.json()
    if (j.code === 0 && j.settings) {
      slideDelay.value = j.settings.slide_delay ?? 3
      slideLoop.value = j.settings.slide_loop ?? true
    }
  } catch (e) {
    console.error("加载幻灯片设置失败", e)
  }
}

async function openSlideSetting() {
  await loadSlideSettings()
  settingShow.value = true
}

async function saveSetting() {
  try {
    await fetch(`${baseUrl}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slide_delay: slideDelay.value, slide_loop: slideLoop.value })
    })
  } catch (e) {
    console.error("保存幻灯片设置失败", e)
  }
  settingShow.value = false
}

function startSlideFromDir() {
  slideList.value = displayList.value.filter(i => i.type === 'image')
  if (slideList.value.length === 0) return alert('当前目录没有图片，无法幻灯片')
  slideIndex.value = 0
  openRootFullscreen()
  slideShow.value = true
  runSlide()
}

function startSlideFromCurrent() {
  slideList.value = previewMediaList.filter(i => i.type === 'image')
  if (slideList.value.length === 0) return alert('没有图片可以幻灯片')
  const idx = slideList.value.findIndex(x => x.path === previewItem.value.path)
  slideIndex.value = Math.max(idx, 0)
  closePreview()
  openRootFullscreen()
  slideShow.value = true
  runSlide()
}

async function openRootFullscreen() {
  const docEl = document.documentElement
  try {
    if (docEl.requestFullscreen) {
      await docEl.requestFullscreen()
    } else if (docEl.webkitRequestFullscreen) {
      await docEl.webkitRequestFullscreen()
    } else if (docEl.msRequestFullscreen) {
      await docEl.msRequestFullscreen()
    }
  } catch (e) {
    console.warn("无法进入全屏，浏览器策略限制", e)
  }
}

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
    slideNext()
  }, slideDelay.value * 1000)
}

function slideNext() {
  slideIndex.value++
  if (slideIndex.value >= slideList.value.length) {
    if (slideLoop.value) slideIndex.value = 0
    else {
      exitSlide()
      return
    }
  }
  runSlide()
}
function slidePrev() {
  slideIndex.value--
  if (slideIndex.value < 0) {
    if (slideLoop.value) slideIndex.value = slideList.value.length - 1
    else slideIndex.value = 0
  }
  runSlide()
}

function closePreview() {
  previewShow.value = false
  previewItem.value = null
  previewMediaList = []
  previewCurrentIndex = 0
}

function onPopState(e) {
  const dir = e.state?.dir ?? getDirFromUrl()
  loadMedia(dir, false)
}

// ========== 登录登出 ==========
async function doLogin() {
  loginErr.value = ''
  try {
    const res = await fetch(`${baseUrl}/api/login`, {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(loginForm.value)
    })
    const ret = await res.json()
    if (!res.ok || ret.code !==0) {
      loginErr.value = "账号或密码错误"
      return
    }
    await checkLoginStatus()
  } catch(err) {
    loginErr.value = "网络异常"
  }
}

async function doLogout() {
  await fetch(`${baseUrl}/api/logout`, {method:"POST"})
  isLogin.value = false
  userInfo.value = {}
  showUserDrop.value = false
}

async function checkLoginStatus() {
  try {
    const res = await fetch(`${baseUrl}/api/whoami`)
    if (res.ok) {
      const ret = await res.json()
      isLogin.value = true
      userInfo.value = ret
      const urlDir = getDirFromUrl()
      const initDir = urlDir ?? ''
      await loadMedia(initDir, !!urlDir)
      await loadSlideSettings()
      initCheckCacheTask()
    } else {
      isLogin.value = false
    }
  } catch(e) {
    isLogin.value = false
  } finally {
    initLoading.value = false
  }
}

// ========= 用户头像下拉 =========
async function loadCacheStats() {
  try {
    const res = await fetch(`${baseUrl}/api/cache-stats`)
    if (!res.ok) return
    const j = await res.json()
    if (j.code === 0) {
      cacheStats.value = {
        total: j.total,
        cached: j.cached,
        uncached: j.uncached,
        failed: j.failed || 0,
        last_finish_time: j.last_finish_time
      }
    }
  } catch (e) {
    console.error("加载缓存统计失败", e)
  }
}
function toggleUserDrop(){
  showUserDrop.value = !showUserDrop.value
  if (showUserDrop.value) {
    loadCacheStats()
  }
}
function openChangePwdModal(){
  showUserDrop.value = false
  changePwdModal.value = true
  pwdForm.value = {old:"",new:"",confirm:""}
  pwdMsg.value = ""
}
async function submitChangePwd(){
  pwdMsg.value = ""
  const f = pwdForm.value
  if(!f.old || !f.new || !f.confirm){
    pwdMsg.value = "全部字段不能为空"
    return
  }
  if(f.new !== f.confirm){
    pwdMsg.value = "两次新密码不一致"
    return
  }
  try{
    const res = await fetch("/api/user/change-password",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({old_password:f.old, new_password:f.new})
    })
    const json = await res.json()
    if(res.ok && json.code ===0){
      pwdMsg.value = "密码修改成功！"
      setTimeout(()=>{changePwdModal.value=false},1200)
    }else{
      pwdMsg.value = json.detail || "修改失败"
    }
  }catch(e){
    pwdMsg.value = "网络错误"
  }
}

// ========= 用户管理新版逻辑 =========
async function openUserManageModal(){
  showUserDrop.value = false
  userManageModal.value = true
  umView.value = 'list'
  editUser.value = null
  adminMsg.value = ""
  umDelConfirm.value.show = false
  await reloadDirOptions()
  await reloadAdminUserList()
}
function closeUserManageModal(){
  userManageModal.value = false
}
async function reloadDirOptions(){
  try{
    const res = await fetch("/api/admin/dirs")
    const json = await res.json()
    if(json.code===0){
      dirOptions.value = json.options
    }
  }catch(e){}
}
async function reloadAdminUserList(){
  try{
    const res = await fetch("/api/admin/users")
    const json = await res.json()
    if(json.code===0){
      adminUserList.value = json.list
    }
  }catch(e){
    adminMsg.value = "获取用户列表失败"
  }
}
function switchToList(){
  umView.value = 'list'
  editUser.value = null
  adminMsg.value = ""
}
function switchToAddForm(){
  editUser.value = null
  umForm.value = {username:"",password:"",is_admin:false,allow_dirs:[]}
  adminMsg.value = ""
  umView.value = 'form'
}
function switchToEditForm(u){
  editUser.value = u
  umForm.value = {
    username: u.username,
    password:"",
    is_admin: u.is_admin,
    allow_dirs:[...u.allow_dirs]
  }
  adminMsg.value = ""
  umView.value = 'form'
}
// 修改用户名（弹窗prompt）
async function triggerRename(){
  if(!editUser.value) return
  const oldU = editUser.value.username
  const newName = prompt("输入新用户名", oldU)
  if(!newName || !newName.trim()) return
  const newTrim = newName.trim()
  if(newTrim === oldU){
    adminMsg.value = "用户名未变化"
    return
  }
  try{
    const res = await fetch("/api/admin/user-rename",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({old_username:oldU, new_username:newTrim})
    })
    const json = await res.json()
    if(json.code===0){
      adminMsg.value = "用户名修改成功"
      umForm.value.username = newTrim
      await reloadAdminUserList()
    }else{
      adminMsg.value = json.detail || "修改失败"
    }
  }catch(e){
    adminMsg.value = "网络异常"
  }
}
// 提交保存新增/编辑
async function submitUmForm(){
  adminMsg.value = ""
  const username = umForm.value.username.trim()
  if(!username){
    adminMsg.value = "用户名不能为空"
    return
  }
  if(umForm.value.allow_dirs.length===0){
    adminMsg.value = "至少勾选一个允许访问目录"
    return
  }
  const body = {
    username: username,
    password: umForm.value.password.trim() || null,
    allow_dirs: umForm.value.allow_dirs,
    is_admin: umForm.value.is_admin
  }
  try{
    const res = await fetch("/api/admin/user-save",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)
    })
    const json = await res.json()
    if(json.code===0){
      adminMsg.value = json.msg || "保存成功"
      await reloadAdminUserList()
      switchToList()
    }else{
      adminMsg.value = json.detail || "保存失败"
    }
  }catch(e){
    adminMsg.value = "网络异常"
  }
}
// 删除确认
function openDelConfirm(u){
  umDelConfirm.value.user = u
  umDelConfirm.value.show = true
}
async function doInnerDelete(){
  const uname = umDelConfirm.value.user.username
  try{
    const res = await fetch(`/api/admin/user/${encodeURIComponent(uname)}`,{method:"DELETE"})
    const json = await res.json()
    if(json.code===0){
      await reloadAdminUserList()
    }
  }catch(e){}
  umDelConfirm.value.show = false
}

// 点击外部关闭下拉
function onClickOutsideDrop(e){
  const el = document.querySelector(".user-dropdown-wrap")
  if(el && !el.contains(e.target)){
    showUserDrop.value = false
  }
}

onMounted(() => {
  checkLoginStatus()
  document.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('popstate', onPopState)
  document.addEventListener("click", onClickOutsideDrop)

  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && slideShow.value) {
      exitSlide()
    }
  })
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('popstate', onPopState)
  document.removeEventListener("click", onClickOutsideDrop)
  if (statusPollTimer) clearInterval(statusPollTimer)
  clearTimeout(slideTimer.value)
  clearTimeout(resizeTimer)
})
</script>

<style scoped>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
/* 初始化加载遮罩，修复刷新闪现登录页 */
.init-loading-mask{
  position:fixed;
  inset:0;
  background:#000;
  z-index:999999;
  display:flex;
  align-items:center;
  justify-content:center;
}
.loading-text{
  color:#fff;
  font-size:16px;
}

.login-mask {
  position: fixed;
  inset:0;
  background:#000;
  z-index:99999;
  display:flex;
  align-items:center;
  justify-content:center;
}
.login-box {
  background:#1e1e1e;
  padding:32px;
  border-radius:12px;
  width:min(340px, 90vw);
  box-sizing:border-box;
}
.login-box h2 {
  color:#fff;
  margin-bottom:24px;
  text-align:center;
}
.form-item {
  margin-bottom:14px;
}
.form-item label {
  display:block;
  color:#ccc;
  margin-bottom:6px;
  font-size:14px;
}
.form-item input {
  width:100%;
  padding:10px;
  border-radius:6px;
  border:none;
  background:#2d2d2d;
  color:#fff;
}
.login-error {
  color:#ff5555;
  font-size:13px;
  margin:8px 0;
  text-align:center;
}
.login-btn-group {
  margin-top:20px;
}

/* 用户头像下拉 */
.user-dropdown-wrap {
  position:relative;
}
.avatar-btn {
  display:flex;
  align-items:center;
  gap:8px;
  padding:4px 10px 4px 4px;
  background:#2a2a2a;
  border:1px solid #3a3a3a;
  border-radius:18px;
  cursor:pointer;
  color:#fff;
  transition: background 0.15s ease;
}
.avatar-btn:hover {
  background:#3a3a3a;
}
.avatar-circle {
  width:26px;
  height:26px;
  border-radius:50%;
  background:#2563eb;
  color:#fff;
  font-size:13px;
  font-weight:500;
  display:flex;
  align-items:center;
  justify-content:center;
  flex-shrink:0;
}
.user-dropdown {
  position:absolute;
  top:calc(100% + 6px);
  right:0;
  min-width:220px;
  background:#1e1e1e;
  border:1px solid #333;
  border-radius:10px;
  z-index:200;
  overflow:hidden;
}
.drop-section {
  padding:6px 0;
}
.drop-section + .drop-section {
  border-top:1px solid #2a2a2a;
}
.drop-item {
  padding:8px 14px;
  color:#eee;
  cursor:pointer;
  font-size:13px;
}
.drop-item:hover {
  background:#2a2a2a;
}
.drop-with-icon {
  display:flex;
  align-items:center;
  gap:10px;
}
.drop-with-icon svg {
  width:15px;
  height:15px;
  color:#999;
  flex-shrink:0;
}
.drop-logout {
  color:#f09595;
}
.drop-logout svg {
  color:#e24b4a;
}
.drop-enter-active,
.drop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.drop-enter-from,
.drop-leave-to {
  opacity:0;
  transform: translateY(-6px);
}
.cache-status-item {
  color: #ffd044;
  cursor: default;
}
.cache-status-item:hover {
  background: transparent;
}
.cache-run-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.cache-sub {
  font-size: 12px;
  color: #888;
}
.cache-meta {
  font-size: 12px;
  color: #777;
  cursor: default;
}
.cache-meta:hover {
  background: transparent;
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

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.header h1 {
  font-size: 22px;
  color: #fff;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items:center;
}
.search-box {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 9px;
  width: 14px;
  height: 14px;
  color: #888;
  pointer-events: none;
}
.search-box input {
  width: 180px;
  padding: 7px 26px 7px 30px;
  background: #2a2a2a;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  outline: none;
}
.search-box input:focus {
  border-color: #2563eb;
}
.search-clear {
  position: absolute;
  right: 8px;
  color: #999;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.sort-select-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.sort-select {
  appearance: none;
  -webkit-appearance: none;
  padding: 7px 28px 7px 10px;
  background: #2a2a2a;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  outline: none;
  cursor: pointer;
}
.sort-select:hover {
  background: #333;
}
.sort-arrow {
  position: absolute;
  right: 8px;
  width: 14px;
  height: 14px;
  color: #888;
  pointer-events: none;
}

.btn {
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: #2a2a2a;
  color: #fff;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.1s ease;
}
.btn:hover {
  background: #3a3a3a;
}
.btn:active {
  background: #222;
  transform: translateY(1px);
}
.btn-sm{
  padding:4px 8px;
  font-size:13px;
}
.btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.btn.primary {
  background: #2563eb;
}
.btn.primary:hover {
  background: #3b82f6;
}
.btn.primary:active {
  background: #1d4ed8;
}
.btn-danger {
  background: #dc2626;
}
.btn-danger:hover {
  background: #ef4444;
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

/* ========= JS横向优先瀑布流容器｜Mac优选270px ========= */
.waterfall-wrap {
  width: 100%;
  position: relative;
}

.media-card {
  width: var(--card-width, 270px);
  position: absolute;
  background: #1e1e1e;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.media-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
}

.card-thumb {
  width: 100%;
  overflow: hidden;
  background: #222;
  display: block;
  position:relative;
}
.card-thumb img {
  width: 100%;
  height: auto;
  display: block;
  opacity: 0;
  transition: opacity 0.3s ease;
}
.card-thumb img.loaded {
  opacity: 1;
}
.folder-placeholder {
  width: 100%;
  min-height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #222;
}
.card-badge {
  position: absolute;
  right: 6px;
  bottom: 6px;
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  z-index: 2;
}
.card-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 10px;
  opacity: 0;
  transition: opacity 0.2s ease;
  z-index: 3;
}
.media-card:hover .card-overlay {
  opacity: 1;
}
.card-overlay-name {
  font-size: 13px;
  word-break: break-all;
  line-height: 1.4;
}
.card-overlay-meta {
  font-size: 12px;
  color: #ccc;
  margin-top: 4px;
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
.empty-state {
  width: 100%;
  padding: 60px 0;
  text-align: center;
  color: #777;
  font-size: 14px;
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
  padding:24px;
  width:min(380px, 92vw);
  box-sizing:border-box;
}

/* =========新版用户管理弹窗样式 ========= */
.user-manage-box{
  background:#181818;
  border-radius:12px;
  width:min(720px, 95vw);
  max-height:85vh;
  display:flex;
  flex-direction:column;
  overflow:hidden;
}
.um-header{
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:14px 18px;
  border-bottom:1px solid #333;
}
.um-close-btn{
  background:transparent;
  border:none;
  color:#aaa;
  font-size:22px;
  cursor:pointer;
}
.um-content-wrap{
  flex:1;
  overflow-y:auto;
  padding:16px 18px;
}
.um-top-bar{
  margin-bottom:14px;
}
.um-table{
  border:1px solid #333;
  border-radius:8px;
}
.um-table-head,.um-table-row{
  display:grid;
  grid-template-columns:140px 100px 1fr 160px;
  padding:10px 12px;
  align-items:center;
  border-bottom:1px solid #333;
}
.um-table-head{
  background:#242424;
  font-weight:bold;
}
.um-table-row:last-child{
  border-bottom:none;
}
.tag-admin{
  color:#ffd044;
  font-size:12px;
}
.tag-user{
  color:#aaa;
  font-size:12px;
}
.um-form-title{
  font-size:16px;
  font-weight:bold;
  margin-bottom:16px;
}
.um-form-item{
  margin-bottom:14px;
  display:flex;
  flex-direction:column;
  gap:6px;
}
.um-form-item label{
  font-size:14px;
  color:#ccc;
}
.um-form-item input{
  padding:9px;
  background:#2a2a2a;
  border:1px solid #444;
  border-radius:6px;
  color:#fff;
}
.multi-select-wrap {
  width:100%;
  max-height:220px;
  overflow-y:auto;
  background:#2a2a2a;
  border-radius:6px;
  padding:10px;
}
.check-item {
  display:flex;
  align-items:center;
  gap:8px;
  padding:4px 0;
}
.check-item label {
  color:#eee;
  font-size:14px;
}
.um-form-buttons{
  display:flex;
  gap:10px;
  justify-content:flex-end;
  margin-top:22px;
  padding-top:12px;
  border-top:1px solid #333;
  flex-shrink:0;
}
.msg-tip {
  color:#ffdd77;
  font-size:13px;
  min-height:20px;
}

.inner-confirm-mask{
  position:absolute;
  inset:0;
  background:rgba(0,0,0,0.65);
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:100;
}
.confirm-box{
  background:#1c1c1c;
  padding:20px 24px;
  border-radius:10px;
}
.confirm-btn-row{
  display:flex;
  gap:10px;
  justify-content:flex-end;
  margin-top:18px;
}
.btn-group {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
}

.slide-root {
  position: fixed;
  inset: 0;
  background: #000;
  z-index: 9999;
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
  object-fit: contain;
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
.slide-prev-btn,
.slide-next-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: rgba(40,40,40,0.7);
  color: #fff;
  border: none;
  font-size: 28px;
  cursor: pointer;
}
.slide-prev-btn { left: 20px; }
.slide-next-btn { right: 20px; }

/* ========= 手机 / 平板响应式 ========= */
@media (max-width: 768px) {
  .app-container {
    padding: 10px;
  }
  .header {
    flex-direction: column;
    align-items: stretch;
  }
  .header-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  .search-box {
    flex: 1;
    min-width: 140px;
  }
  .search-box input {
    width: 100%;
    box-sizing: border-box;
  }
  .media-card:hover {
    transform: none;
    box-shadow: none;
  }
  .um-table-head,
  .um-table-row {
    grid-template-columns: 90px 70px 1fr 110px;
    font-size: 12px;
    padding: 8px;
  }
  .preview-image-area {
    padding: 12px 12px 8px;
  }
}

@media (max-width: 480px) {
  .header h1 {
    font-size: 18px;
  }
  .sort-select {
    flex: 1;
  }
  .img-action-bar button {
    padding: 8px 10px;
    font-size: 13px;
  }
  .slide-prev-btn { left: 8px; width: 44px; height: 44px; }
  .slide-next-btn { right: 8px; width: 44px; height: 44px; }
}
</style>
