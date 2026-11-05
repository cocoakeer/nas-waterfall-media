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
        <div class="app-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.6"/><path d="M21 15l-5-5L5 21"/></svg>
        </div>
        <h1 class="app-title">NAS 媒体瀑布流</h1>
        <div class="user-dropdown-wrap">
          <div class="avatar-btn" @click="toggleUserDrop">
            <span class="avatar-circle">{{ avatarInitial }}</span>
            <span class="avatar-name">{{userInfo.username}}</span>
            <svg class="avatar-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
          </div>
          <transition name="drop">
            <div v-if="showUserDrop" class="user-dropdown">
              <div class="drop-section">
                <div v-if="cacheRunning" class="drop-item cache-status-item">缓存处理中 {{cachePercent}}%</div>
                <div v-else class="drop-item cache-run-item" @click="runCacheTask">
                  <span>预生成缓存</span>
                  <span class="cache-sub">未缓存 {{ cacheStats.uncached }}/{{ cacheStats.total }}</span>
                </div>
                <div v-if="cacheStats.last_finish_time" class="drop-item cache-meta">上次完成 {{ formatDateTime(cacheStats.last_finish_time) }}<template v-if="cacheStats.failed > 0"> · <span class="cache-failed-link" @click="openFailedFilesModal">失败 {{ cacheStats.failed }} 个</span></template></div>
                <div v-if="cacheRunning" class="drop-item" @click="stopCacheTask">取消缓存任务</div>
              </div>
              <div class="drop-section">
                <div class="drop-item drop-with-icon" @click="openChangePwdModal">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  <span>修改密码</span>
                </div>
                <div v-if="userInfo.is_admin" class="drop-item drop-with-icon" @click="openLogModal">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                  <span>执行日志</span>
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
        <button @click="startRandomSlide" class="btn primary" :disabled="randomSlideLoading">{{ randomSlideLoading ? '加载中…' : '随机幻灯片' }}</button>
      </div>
    </header>
    <div class="breadcrumb">
      <span @click="changeDir('')" class="breadcrumb-item" :class="{current: !breadcrumbList.length}">根目录</span>
      <span v-for="(item, idx) in breadcrumbList" :key="idx">
        <span class="separator">/</span>
        <span @click="changeDir(item.path)" class="breadcrumb-item" :class="{current: idx === breadcrumbList.length - 1}">{{ item.name }}</span>
      </span>
    </div>

    <!-- JS横向优先瀑布流容器 MacBook优选270px -->
    <div ref="waterfallBoxRef" class="waterfall-wrap">
      <div v-if="isLoading" class="empty-state">
        <div class="empty-illustration">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.6"/><path d="M21 15l-5-5L5 21"/></svg>
        </div>
        <div class="empty-title">正在加载...</div>
        <div class="empty-desc">正在读取目录内容，请稍候</div>
      </div>
      <div v-else-if="!displayList.length" class="empty-state">
        <div class="empty-illustration">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.6"/><path d="M21 15l-5-5L5 21"/></svg>
        </div>
        <div v-if="searchQuery" class="empty-title">没有匹配「{{ searchQuery }}」的文件</div>
        <div v-else class="empty-title">当前目录为空</div>
        <div class="empty-desc">{{ searchQuery ? '试试更换关键词，或清空搜索条件' : '这里有图片或视频时，会自动排成瀑布流展示' }}</div>
      </div>
      <div
        v-for="item in displayList"
        :key="item.id"
        class="media-card"
        :style="{left: item._left + 'px', top: item._top + 'px'}"
        @click="handleCardClick(item)"
      >
        <div class="card-thumb" :class="{'thumb-loaded': item._loaded || (item.type === 'folder' && !item.cover_path)}">
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
            <div class="play-icon">
              <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>
            </div>
          </div>
          <!-- 文件夹名称标签 -->
          <div v-if="item.type === 'folder'" class="folder-label">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
            <span>{{ item.name }}</span>
          </div>
          <!-- 角标 -->
          <div v-if="item.type === 'folder'" class="card-badge badge-count">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>{{ item.count }}
          </div>
          <div v-else-if="item.type === 'video' && item.duration" class="card-badge badge-duration">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>{{ formatDuration(item.duration) }}
          </div>
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
        <div class="preview-image-area"
             @touchstart="onTouchStart"
             @touchend="onTouchEnd">
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
          <input v-model.number="slideDelay" type="number" min="1" max="3600" step="1" />
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
    <!-- 执行日志弹窗 -->
    <div v-if="logModal" class="preview-mask" @click.self="logModal=false">
      <div class="log-box">
        <div class="um-header">
          <h3>执行日志</h3>
          <div class="log-header-actions">
            <button class="log-clear-btn" @click="clearLogs">清除</button>
            <button class="um-close-btn" @click="logModal=false">×</button>
          </div>
        </div>
        <div class="log-list">
          <div v-for="log in logList" :key="log.id" class="log-item">
            <div class="log-time">{{ formatDateTime(log.time) }}</div>
            <div class="log-main">
              <div class="log-line">
                <span class="log-operator">{{ log.operator }}</span>
                <span v-if="log.action" class="event-tag" :class="{warn: isWarnLog(log)}">{{ logActionLabel(log.action) }}</span>
              </div>
              <div v-if="log.detail" class="log-detail">{{ log.detail }}</div>
            </div>
          </div>
          <div v-if="!logList.length" class="empty-state">暂无日志</div>
        </div>
      </div>
    </div>
    <!-- 缓存失败文件弹窗 -->
    <div v-if="failedFilesModal" class="preview-mask" @click.self="failedFilesModal=false">
      <div class="log-box">
        <div class="um-header">
          <h3>缓存失败文件（{{ cacheStats.failed_files.length }}）</h3>
          <button class="um-close-btn" @click="failedFilesModal=false">×</button>
        </div>
        <div class="log-list">
          <div v-for="(f, idx) in cacheStats.failed_files" :key="idx" class="log-item">
            <div class="failed-item">
              <div class="log-detail">{{ typeof f === 'string' ? f : f.path }}</div>
              <div v-if="typeof f === 'object' && f.error" class="log-error">{{ f.error }}</div>
            </div>
          </div>
          <div v-if="!cacheStats.failed_files.length" class="empty-state">无失败文件</div>
        </div>
      </div>
    </div>
    <!-- 幻灯片全屏渲染层 -->
    <div v-if="slideShow" class="slide-root">
      <div class="slide-content"
           @touchstart="onTouchStart"
           @touchend="onTouchEnd">
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

// 幻灯片间隔限制在 1~3600 秒，避免 0/负值导致 setTimeout 空转打满 CPU
function clampSlideDelay(v) {
  const n = Math.round(Number(v))
  if (!Number.isFinite(n)) return 3
  return Math.min(3600, Math.max(1, n))
}

// 执行日志：事件中文标签与告警态（仅用于展示，不改变日志数据）
const LOG_ACTION_LABELS = {
  login: '登录',
  logout: '退出登录',
  change_password: '修改密码',
  user_rename: '重命名用户',
  user_save: '用户管理',
  user_delete: '删除用户',
  logs_clear: '清除日志',
  cache_run: '手动缓存',
  cache_stop: '取消缓存',
  cache_daily: '定时任务',
  cache_result: '缓存结果'
}
function logActionLabel(action) {
  return LOG_ACTION_LABELS[action] || action || '操作'
}
function isWarnLog(log) {
  const action = log.action || ''
  if (['user_delete', 'logs_clear', 'cache_stop'].includes(action)) return true
  if (action === 'cache_result' && /失败|错误|异常/.test(log.detail || '')) return true
  return false
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
// 首页随机幻灯片：全库随机抽取；预览里的「从此处开始幻灯片」仍是顺序播放
const randomSlideLoading = ref(false)
const randomSlideMode = ref(false)
const randomBatchLoading = ref(false)
const RANDOM_BATCH_SIZE = 1000

const cacheRunning = ref(false)
const cachePercent = ref(0)
let statusPollTimer = null
// 缓存统计：total 全部 / cached 已缓存 / uncached 未缓存 / failed 失败 / failed_files 失败文件 / last_finish_time 上次完成时间
const cacheStats = ref({ total: 0, cached: 0, uncached: 0, failed: 0, failed_files: [], last_finish_time: null })
// 执行日志
const logModal = ref(false)
const logList = ref([])
// 缓存失败文件弹窗
const failedFilesModal = ref(false)

const STORAGE_KEY = "waterfall_last_dir"

// ========= JS瀑布流【响应式：手机2列 / 平板3-4列 / 桌面270px】 =========
let resizeTimer = null
// 卡片高度缓存：图片逐张加载时不再全量读 offsetHeight，避免 O(n^2) 的强制重排
const cardHeightCache = new Map()
// 上一次的列宽：卡片高度依赖宽度，列宽一变缓存就整体失效
let lastCardWidth = null

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

  // 首次布局或列宽变化时，缓存是在旧宽度下测出来的，必须整体作废
  if (lastCardWidth === null || Math.abs(cardWidth - lastCardWidth) > 0.5) {
    cardHeightCache.clear()
  }
  lastCardWidth = cardWidth

  // 先设列宽再测高度：否则读到的 offsetHeight 属于旧的 270px 回退宽度
  waterfallBoxRef.value.style.setProperty('--card-width', cardWidth + 'px')
  waterfallBoxRef.value.style.setProperty('--card-gap', gap + 'px')

  // 每列高度记录
  const colHeights = new Array(colCount).fill(0)

  list.forEach((item, idx)=>{
    // 行优先逻辑：索引 % 列数，实现一行一行横向排布
    const colIndex = idx % colCount
    const left = colIndex * (cardWidth + gap)

    let cardH = cardHeightCache.get(item.id)
    if (cardH == null) {
      const dom = waterfallBoxRef.value.children[idx]
      cardH = dom ? (dom.offsetHeight || 280) : 280
      cardHeightCache.set(item.id, cardH)
    }

    const top = colHeights[colIndex]
    colHeights[colIndex] = top + cardH + gap

    item._left = left
    item._top = top
  })

  // 设置容器总高度
  const maxH = Math.max(...colHeights)
  waterfallBoxRef.value.style.height = maxH + 'px'
}

// 图片加载完成：只让该卡片高度失效，由 layoutWaterfall 在列宽确定后统一测量
function onImageLoaded(item){
  item._loaded = true
  cardHeightCache.delete(item.id)
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(()=>{
    layoutWaterfall()
  },120)
}

watch(displayList, async ()=>{
  cardHeightCache.clear()
  await nextTick()
  layoutWaterfall()
})

function onWindowResize(){
  // 列宽变化会让所有卡片高度失效，必须重新测量
  cardHeightCache.clear()
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

// ========= 移动端滑动切换图片 =========
let touchStartX = 0
let touchStartY = 0

function onTouchStart(e) {
  if (e.touches.length === 1) {
    touchStartX = e.touches[0].clientX
    touchStartY = e.touches[0].clientY
  }
}
function onTouchEnd(e) {
  if (e.changedTouches.length !== 1) return
  const dx = e.changedTouches[0].clientX - touchStartX
  const dy = e.changedTouches[0].clientY - touchStartY
  // 水平滑动为主，且位移超过阈值
  if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
    if (slideShow.value) {
      // 幻灯片：仅图片滑动，视频保留进度条拖动
      if (currentSlide.value.type === 'image') {
        dx < 0 ? slideNext() : slidePrev()
      }
    } else if (previewItem.value && previewItem.value.type === 'image') {
      // 预览弹窗：仅图片滑动
      dx < 0 ? nextMedia() : prevMedia()
    }
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
      slideDelay.value = clampSlideDelay(j.settings.slide_delay ?? 3)
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
  slideDelay.value = clampSlideDelay(slideDelay.value)
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

// 从整个媒体库随机取一批图片
async function fetchRandomImages() {
  const res = await fetch(`${baseUrl}/api/random-images?limit=${RANDOM_BATCH_SIZE}`)
  if (!res.ok) { checkAuthResp(res); return null }
  const j = await res.json()
  if (j.code !== 0) return null
  return j.list || []
}

// 首页随机幻灯片：点击后播放第一批（不影响预览里的顺序播放）
async function startRandomSlide() {
  if (randomSlideLoading.value) return
  randomSlideLoading.value = true
  try {
    const list = await fetchRandomImages()
    if (list === null) return alert('❌ 随机幻灯片加载失败')
    if (!list.length) return alert('媒体库里没有可用于幻灯片的图片')
    slideList.value = list
    randomSlideMode.value = true
    slideIndex.value = 0
    openRootFullscreen()
    slideShow.value = true
    runSlide()
  } catch (e) {
    console.error('加载随机图片失败', e)
    alert('❌ 加载图片失败，请稍后重试')
  } finally {
    randomSlideLoading.value = false
  }
}

// 每轮播完重新从全库抽一批，避免一直循环同一批图片
async function reloadRandomBatch() {
  if (randomBatchLoading.value) return false
  randomBatchLoading.value = true
  try {
    const list = await fetchRandomImages()
    if (list && list.length) {
      slideList.value = list
      return true
    }
  } catch (e) {
    console.error('重新抽取随机图片失败', e)
  } finally {
    randomBatchLoading.value = false
  }
  return false
}

// 换批失败时的兜底：洗牌当前批次，保证播放不中断
function shuffleSlideList() {
  const arr = slideList.value.slice()
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    const tmp = arr[i]
    arr[i] = arr[j]
    arr[j] = tmp
  }
  slideList.value = arr
}

function startSlideFromCurrent() {
  slideList.value = previewMediaList.filter(i => i.type === 'image')
  randomSlideMode.value = false
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
  randomSlideMode.value = false
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
  }, clampSlideDelay(slideDelay.value) * 1000)
}

async function slideNext() {
  slideIndex.value++
  if (slideIndex.value >= slideList.value.length) {
    if (!slideLoop.value) {
      exitSlide()
      return
    }
    if (randomSlideMode.value) {
      const ok = await reloadRandomBatch()
      if (!slideShow.value) return
      if (!ok) shuffleSlideList()
    }
    slideIndex.value = 0
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
    // 首次挂载时 app-container 到此刻才渲染，先前所有布局都因容器不存在被跳过。
    // DOM 就绪后补一次，确保 --card-width 与卡片位置立即生效（不依赖图片 load）。
    await nextTick()
    layoutWaterfall()
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
        failed_files: j.failed_files || [],
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
// ========= 执行日志 =========
async function openLogModal(){
  showUserDrop.value = false
  logModal.value = true
  await loadLogs()
}
function openFailedFilesModal(){
  showUserDrop.value = false
  failedFilesModal.value = true
}
async function loadLogs(){
  try {
    const res = await fetch(`${baseUrl}/api/logs?limit=200`)
    if (!res.ok) return
    const j = await res.json()
    if (j.code === 0) {
      logList.value = j.logs || []
    }
  } catch (e) {
    console.error("加载日志失败", e)
  }
}
async function clearLogs(){
  if (!confirm("确认清除全部执行日志？此操作不可恢复。")) return
  try {
    const res = await fetch(`${baseUrl}/api/logs`, { method: 'DELETE' })
    if (!res.ok) { checkAuthResp(res); return }
    const ret = await res.json()
    if (ret.code === 0) {
      await loadLogs()
    } else {
      alert("❌" + (ret.msg || "清除失败"))
    }
  } catch (e) {
    console.error("清除日志失败", e)
    alert("❌清除失败")
  }
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

function onFullscreenChange(){
  if (!document.fullscreenElement && slideShow.value) {
    exitSlide()
  }
}

onMounted(() => {
  checkLoginStatus()
  document.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('popstate', onPopState)
  document.addEventListener("click", onClickOutsideDrop)

  document.addEventListener('fullscreenchange', onFullscreenChange)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('popstate', onPopState)
  document.removeEventListener("click", onClickOutsideDrop)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  if (statusPollTimer) clearInterval(statusPollTimer)
  clearTimeout(slideTimer.value)
  clearTimeout(resizeTimer)
})
</script>

<style scoped>
/* ==========================================================
   UI 主题：A 克制精致
   仅调整视觉层，不改变任何交互逻辑与瀑布流布局计算
   设计变量统一定义在 src/style.css 的 :root
   ========================================================== */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
  -webkit-tap-highlight-color: transparent;
}

/* ---------- 初始化 / 登录 ---------- */
.init-loading-mask {
  position: fixed;
  inset: 0;
  background: var(--bg);
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
}
.loading-text {
  color: var(--text-2);
  font-size: 14px;
  letter-spacing: .5px;
}
.loading-text::after {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse { 50% { opacity: .25 } }

.login-mask {
  position: fixed;
  inset: 0;
  background: radial-gradient(circle at 50% 8%, rgba(91, 130, 247, .10), transparent 55%), var(--bg);
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.login-box {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 30px 28px;
  width: min(360px, 92vw);
  animation: boxIn .28s cubic-bezier(.2, .9, .3, 1);
}
.login-box h2 {
  color: var(--text);
  font-size: 16px;
  font-weight: 500;
  letter-spacing: .3px;
  margin-bottom: 24px;
  text-align: center;
}
.login-box h2::before {
  content: "";
  display: block;
  width: 34px;
  height: 34px;
  margin: 0 auto 16px;
  border-radius: 10px;
  background: var(--accent);
  box-shadow: 0 4px 14px rgba(91, 130, 247, .28);
}
.form-item { margin-bottom: 16px }
.form-item label {
  display: block;
  color: var(--text-2);
  margin-bottom: 7px;
  font-size: 13px;
}
.form-item input,
.form-row input:not([type="checkbox"]),
.um-form-item input:not([type="checkbox"]) {
  width: 100%;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
  font-size: 13px;
  outline: none;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.form-item input:focus,
.form-row input:not([type="checkbox"]):focus,
.um-form-item input:not([type="checkbox"]):focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.form-item input::placeholder,
.um-form-item input::placeholder { color: var(--muted) }
input[type="checkbox"] {
  accent-color: var(--accent);
  width: 16px;
  height: 16px;
  margin: 0;
  cursor: pointer;
}
.login-error {
  color: var(--danger);
  font-size: 12px;
  margin: 8px 0;
  text-align: center;
}
.login-btn-group { margin-top: 22px }
.login-btn-group .btn { width: 100%; padding: 10px }

/* ---------- 顶栏 ---------- */
.app-container {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
}
.header {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  flex-wrap: wrap;
  gap: 12px;
  background: var(--header-bg);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.app-logo {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  flex-shrink: 0;
  background: var(--accent);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(91, 130, 247, .28);
}
.app-logo svg { width: 18px; height: 18px }
.header h1.app-title {
  font-size: 17px;
  font-weight: 500;
  letter-spacing: .2px;
  color: var(--text);
  white-space: nowrap;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

/* 头像与下拉 */
.user-dropdown-wrap { position: relative }
.avatar-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 11px 4px 4px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 20px;
  cursor: pointer;
  color: var(--text);
  font-size: 13px;
  transition: background .15s ease;
}
.avatar-btn:hover { background: var(--surface-3) }
.avatar-circle {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.avatar-name { white-space: nowrap }
.avatar-caret {
  width: 13px;
  height: 13px;
  color: var(--muted);
}
.user-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 230px;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  z-index: 200;
  overflow: hidden;
}
.drop-section { padding: 6px 0 }
.drop-section + .drop-section { border-top: 1px solid var(--border) }
.drop-item {
  padding: 9px 14px;
  color: var(--text-2);
  cursor: pointer;
  font-size: 13px;
  transition: background .15s ease, color .15s ease;
}
.drop-item:hover { background: var(--surface-2); color: var(--text) }
.drop-with-icon { display: flex; align-items: center; gap: 10px }
.drop-with-icon svg {
  width: 15px;
  height: 15px;
  color: var(--muted);
  flex-shrink: 0;
}
.drop-logout { color: var(--danger) }
.drop-logout svg { color: var(--danger) }
.drop-logout:hover { background: var(--danger-soft); color: var(--danger) }
.drop-enter-active, .drop-leave-active {
  transition: opacity .15s ease, transform .15s ease;
}
.drop-enter-from, .drop-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
.cache-status-item { color: #ffd044; cursor: default }
.cache-status-item:hover { background: transparent }
.cache-run-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.cache-sub { font-size: 12px; color: var(--muted) }
.cache-meta { font-size: 12px; color: var(--muted); cursor: default }
.cache-meta:hover { background: transparent }
.cache-failed-link {
  color: var(--danger);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

/* 搜索与排序 */
.search-box { position: relative; display: flex; align-items: center }
.search-icon {
  position: absolute;
  left: 10px;
  width: 15px;
  height: 15px;
  color: var(--muted);
  pointer-events: none;
}
.search-box input {
  width: 190px;
  padding: 8px 28px 8px 32px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 13px;
  outline: none;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.search-box input::placeholder { color: var(--muted) }
.search-box input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.search-clear {
  position: absolute;
  right: 9px;
  color: var(--muted);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.search-clear:hover { color: var(--text) }
.sort-select-wrap { position: relative; display: flex; align-items: center }
.sort-select {
  appearance: none;
  -webkit-appearance: none;
  padding: 8px 28px 8px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 13px;
  outline: none;
  cursor: pointer;
  transition: border-color .15s ease;
}
.sort-select:hover { border-color: var(--border-strong) }
.sort-select option { background: var(--surface); color: var(--text) }
.sort-arrow {
  position: absolute;
  right: 9px;
  width: 13px;
  height: 13px;
  color: var(--muted);
  pointer-events: none;
}

/* 按钮 */
.btn {
  padding: 8px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: background .15s ease, border-color .15s ease, transform .1s ease;
}
.btn:hover { background: var(--surface-3); border-color: var(--accent) }
.btn:active { transform: translateY(1px) }
.btn:focus-visible,
.avatar-btn:focus-visible,
.close-btn:focus-visible,
.arrow-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.btn-sm { padding: 5px 10px; font-size: 12px }
.btn:disabled { opacity: .55; cursor: not-allowed; transform: none }
.btn.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  font-weight: 500;
  box-shadow: 0 4px 14px rgba(91, 130, 247, .22);
}
.btn.primary:hover { background: var(--accent-2); border-color: var(--accent-2) }
.btn.primary:active { background: #4a70e0 }
.btn-danger { background: transparent; border-color: var(--danger); color: var(--danger) }
.btn-danger:hover { background: var(--danger-soft); border-color: var(--danger) }

/* 面包屑 */
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  padding: 14px 20px 4px;
  font-size: 13px;
  color: var(--muted);
}
.breadcrumb-item {
  padding: 4px 9px;
  border-radius: 7px;
  color: var(--text-2);
  cursor: pointer;
  transition: background .15s ease, color .15s ease;
}
.breadcrumb-item:hover { background: var(--surface-2); color: var(--accent-2) }
.breadcrumb-item.current {
  background: var(--accent-soft);
  color: var(--accent-2);
  font-weight: 500;
}
.separator { color: var(--muted); opacity: .6; margin: 0 2px }

/* ---------- 瀑布流卡片 ---------- */
.waterfall-wrap {
  width: calc(100% - 40px);
  margin: 14px 20px 28px;
  position: relative;
}
.media-card {
  width: var(--card-width, 270px);
  position: absolute;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.media-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow);
  border-color: var(--border-strong);
}
.card-thumb {
  width: 100%;
  overflow: hidden;
  display: block;
  position: relative;
  background: var(--surface-2);
}
.card-thumb:not(.thumb-loaded) {
  background-image: linear-gradient(100deg, var(--surface-2) 20%, var(--surface-3) 45%, var(--surface-2) 70%);
  background-size: 220% 100%;
  animation: shimmer 1.6s linear infinite;
}
@keyframes shimmer {
  from { background-position: 120% 0 }
  to   { background-position: -120% 0 }
}
.card-thumb img {
  width: 100%;
  height: auto;
  display: block;
  opacity: 0;
  transition: opacity .3s ease;
}
.card-thumb img.loaded { opacity: 1 }
.folder-placeholder {
  width: 100%;
  min-height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-2);
}
.folder-placeholder svg { opacity: .8 }
.folder-label {
  position: absolute;
  left: 10px;
  top: 10px;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: calc(100% - 20px);
  padding: 5px 9px;
  border-radius: 8px;
  background: rgba(10, 12, 18, .55);
  border: 1px solid rgba(255, 255, 255, .14);
  backdrop-filter: blur(8px);
  color: #fff;
  font-size: 11px;
}
.folder-label span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.folder-label svg { width: 13px; height: 13px; flex-shrink: 0 }
.card-badge {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 20px;
  background: rgba(10, 12, 18, .62);
  border: 1px solid rgba(255, 255, 255, .14);
  backdrop-filter: blur(8px);
  color: #fff;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.card-badge svg { width: 11px; height: 11px }
.card-overlay {
  position: absolute;
  inset: 0;
  z-index: 2;
  background: linear-gradient(180deg, transparent 42%, rgba(6, 8, 12, .88) 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 12px;
  opacity: 0;
  transition: opacity .22s ease;
}
.media-card:hover .card-overlay { opacity: 1 }
.card-overlay-name { font-size: 12px; color: #fff; word-break: break-all; line-height: 1.45 }
.card-overlay-meta { font-size: 11px; color: rgba(255, 255, 255, .72); margin-top: 4px }
.play-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 3;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: rgba(10, 12, 18, .55);
  border: 1px solid rgba(255, 255, 255, .24);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  transition: transform .2s ease, background .2s ease;
}
.media-card:hover .play-icon {
  transform: translate(-50%, -50%) scale(1.08);
  background: rgba(91, 130, 247, .75);
}
.play-icon svg { width: 17px; height: 17px; margin-left: 2px }
.card-name {
  padding: 10px 12px;
  font-size: 12.5px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 空状态 */
.empty-state {
  width: 100%;
  padding: 70px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.empty-illustration {
  width: 96px;
  height: 96px;
  border-radius: 26px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}
.empty-illustration svg { width: 44px; height: 44px; color: var(--muted) }
.empty-title { font-size: 15px; color: var(--text); margin-bottom: 7px }
.empty-desc { font-size: 13px; color: var(--muted) }

/* ---------- 弹窗 ---------- */
@keyframes maskIn { from { opacity: 0 } to { opacity: 1 } }
@keyframes boxIn {
  from { opacity: 0; transform: translateY(10px) scale(.975) }
  to   { opacity: 1; transform: none }
}
@keyframes mediaIn { from { opacity: 0 } to { opacity: 1 } }

.preview-mask {
  position: fixed;
  inset: 0;
  background: rgba(4, 5, 8, .82);
  backdrop-filter: blur(6px);
  z-index: 99;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  animation: maskIn .2s ease;
}
.preview-box {
  background: transparent;
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
  background: rgba(20, 24, 32, .7);
  border: 1px solid rgba(255, 255, 255, .2);
  color: #fff;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  z-index: 4;
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background .15s ease;
}
.close-btn:hover { background: rgba(91, 130, 247, .8) }
.arrow-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(20, 24, 32, .7);
  border: 1px solid rgba(255, 255, 255, .2);
  color: #fff;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  z-index: 3;
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background .2s;
}
.arrow-btn:hover:not(:disabled) { background: rgba(91, 130, 247, .8) }
.arrow-btn:disabled { opacity: .25; cursor: default }
.arrow-left { left: 10px }
.arrow-right { right: 10px }
.preview-image-area {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: 18px 18px 10px;
}
.preview-image-area img,
.preview-image-area video {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  animation: mediaIn .24s ease;
}
.preview-footer {
  flex-shrink: 0;
  padding: 10px 16px 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.preview-name { font-size: 13px; color: var(--text-2); text-align: center; word-break: break-all }
.img-action-bar { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center }
.img-action-bar button {
  padding: 7px 13px;
  background: rgba(255, 255, 255, .10);
  border: 1px solid rgba(255, 255, 255, .16);
  border-radius: 8px;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  backdrop-filter: blur(8px);
  transition: background .15s ease;
}
.img-action-bar button:hover { background: rgba(255, 255, 255, .2) }

/* 设置 / 表单弹窗 */
.setting-box {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 22px 24px;
  width: min(400px, 92vw);
  animation: boxIn .24s cubic-bezier(.2, .9, .3, 1);
}
.setting-box h3,
.um-header h3 { font-size: 14px; font-weight: 500; color: var(--text) }
.setting-box h3 { margin-bottom: 20px }
.form-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--text-2);
}
.form-row label { white-space: nowrap }
.form-row input:not([type="checkbox"]) { width: 120px; flex-shrink: 0 }
.btn-group { display: flex; gap: 10px; justify-content: flex-end; margin-top: 22px }

/* 用户管理 / 日志弹窗 */
.user-manage-box,
.log-box {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: boxIn .24s cubic-bezier(.2, .9, .3, 1);
}
.user-manage-box { width: min(720px, 95vw) }
.log-box { width: min(560px, 95vw); max-height: 80vh }
.log-header-actions { display: flex; align-items: center; gap: 10px }
.log-clear-btn {
  background: transparent;
  border: 1px solid var(--danger);
  color: var(--danger);
  border-radius: 8px;
  padding: 5px 11px;
  font-size: 12px;
  cursor: pointer;
  transition: background .15s ease;
}
.log-clear-btn:hover { background: var(--danger-soft) }
.log-list { flex: 1; overflow-y: auto; padding: 6px 0; scrollbar-width: thin }
.log-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  transition: background .15s ease;
}
.log-item:last-child { border-bottom: none }
.log-item:hover { background: var(--surface-2) }
.log-time {
  flex-shrink: 0;
  min-width: 118px;
  color: var(--muted);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.log-main { display: flex; flex-direction: column; gap: 5px; min-width: 0; flex: 1 }
.log-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap }
.log-operator { flex-shrink: 0; color: var(--accent-2); font-size: 12px; font-weight: 500 }
.event-tag {
  font-size: 10.5px;
  padding: 2px 7px;
  border-radius: 20px;
  background: var(--accent-soft);
  color: var(--accent-2);
}
.event-tag.warn { background: var(--danger-soft); color: var(--danger) }
.log-detail { color: var(--text-2); font-size: 12.5px; word-break: break-all; line-height: 1.5 }
.failed-item { display: flex; flex-direction: column; gap: 6px; min-width: 0; width: 100% }
.log-error {
  color: var(--danger);
  font-size: 11.5px;
  background: var(--danger-soft);
  padding: 6px 9px;
  border-radius: 7px;
  word-break: break-all;
}
.log-list .empty-state { padding: 36px 20px; font-size: 13px; color: var(--muted) }

.um-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.um-close-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.um-close-btn:hover { background: var(--surface-3); color: var(--text) }
.um-content-wrap { flex: 1; overflow-y: auto; padding: 16px 18px }
.um-top-bar { margin-bottom: 14px }
.um-table { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden }
.um-table-head,
.um-table-row {
  display: grid;
  grid-template-columns: 140px 100px 1fr 160px;
  padding: 10px 12px;
  align-items: center;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.um-table-head { background: var(--surface-2); font-weight: 500; color: var(--text-2) }
.um-table-row:last-child { border-bottom: none }
.um-table-row:hover { background: var(--surface-2) }
.tag-admin { color: #ffd044; font-size: 12px }
.tag-user { color: var(--text-2); font-size: 12px }
.um-form-title { font-size: 15px; font-weight: 500; margin-bottom: 16px }
.um-form-item { margin-bottom: 14px; display: flex; flex-direction: column; gap: 6px }
.um-form-item label { font-size: 13px; color: var(--text-2) }
.um-form-item > div input:not([type="checkbox"]) { width: auto; flex: 1; min-width: 0 }
.multi-select-wrap {
  width: 100%;
  max-height: 220px;
  overflow-y: auto;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px;
}
.check-item { display: flex; align-items: center; gap: 8px; padding: 4px 0 }
.check-item label { color: var(--text); font-size: 13px; cursor: pointer }
.um-form-buttons {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 22px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.msg-tip { color: #ffd77a; font-size: 12px; min-height: 20px }

.inner-confirm-mask {
  position: absolute;
  inset: 0;
  background: rgba(4, 5, 8, .7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.confirm-box {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px 24px;
  color: var(--text-2);
  font-size: 13px;
}
.confirm-btn-row { display: flex; gap: 10px; justify-content: flex-end; margin-top: 18px }

/* ---------- 幻灯片全屏层 ---------- */
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
.slide-content video { max-width: 98vw; max-height: 98vh; object-fit: contain }
.slide-name {
  position: absolute;
  bottom: 64px;
  left: 0;
  right: 0;
  padding: 0 24px;
  text-align: center;
  color: rgba(255, 255, 255, .86);
  font-size: 13px;
  text-shadow: 0 2px 8px rgba(0, 0, 0, .8);
}
.slide-exit-btn {
  position: absolute;
  top: 16px;
  right: 16px;
  padding: 8px 14px;
  background: rgba(20, 24, 32, .7);
  border: 1px solid rgba(255, 255, 255, .2);
  color: #fff;
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
  backdrop-filter: blur(8px);
}
.slide-exit-btn:hover { background: rgba(91, 130, 247, .8) }
.slide-prev-btn,
.slide-next-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: rgba(20, 24, 32, .7);
  border: 1px solid rgba(255, 255, 255, .2);
  color: #fff;
  font-size: 26px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(8px);
}
.slide-prev-btn:hover,
.slide-next-btn:hover { background: rgba(91, 130, 247, .8) }
.slide-prev-btn { left: 20px }
.slide-next-btn { right: 20px }

/* ---------- 响应式 ---------- */
@media (max-width: 900px) {
  .header-actions { gap: 8px }
  .search-box input { width: 150px }
}
@media (max-width: 768px) {
  .header { padding: 12px 14px }
  .breadcrumb { padding: 12px 14px 2px }
  .waterfall-wrap { width: calc(100% - 28px); margin: 12px 14px 24px }
  .header-actions { width: 100% }
  .search-box { flex: 1; min-width: 140px }
  .search-box input { width: 100%; box-sizing: border-box }
  .media-card:hover { transform: none; box-shadow: var(--shadow-sm) }
  .card-overlay {
    opacity: 1;
    padding: 8px;
    background: linear-gradient(180deg, transparent 55%, rgba(6, 8, 12, .86) 100%);
  }
  .card-overlay-meta { display: none }
  .card-overlay-name { font-size: 11px }
  .card-name { display: none }
  .um-table-head,
  .um-table-row { grid-template-columns: 90px 70px 1fr 110px; font-size: 12px; padding: 8px }
  .preview-image-area { padding: 12px 12px 8px }
  .arrow-btn { width: 38px; height: 38px; font-size: 20px }
  .arrow-left { left: 6px }
  .arrow-right { right: 6px }
  .preview-name { font-size: 12px }
}
@media (max-width: 480px) {
  .header h1.app-title { font-size: 16px }
  .sort-select { flex: 1 }
  .img-action-bar button { padding: 8px 10px; font-size: 12px }
  .slide-prev-btn { left: 8px; width: 44px; height: 44px }
  .slide-next-btn { right: 8px; width: 44px; height: 44px }
  .preview-mask { padding: 0 }
  .preview-box { width: 100vw; height: 100vh; max-width: 100vw; max-height: 100vh }
  .close-btn { top: 8px; right: 8px; width: 30px; height: 30px; font-size: 18px }
  .log-time { min-width: 0 }
  .log-item { gap: 8px; padding: 9px 12px }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important }
}
</style>
