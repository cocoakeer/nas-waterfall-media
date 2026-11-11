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
        <button @click="doLogin" class="btn primary" :disabled="loginLockRemaining > 0">
          {{ loginLockRemaining > 0 ? '已锁定 ' + formatLockClock(loginLockRemaining) : '登录' }}
        </button>
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
              <div v-if="userInfo.is_admin" class="drop-section">
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
        <button @click="startRandomSlide" class="btn primary">{{ randomSlideLoading ? (randomSlideHint || '加载中…') + ' · 点此取消' : '随机幻灯片' }}</button>
        <button v-if="isTvMode" class="btn tv-setup-btn" @click="openTvSetup">服务器地址</button>
      </div>
    </header>
    <div class="breadcrumb">
      <span @click="changeDir('')" class="breadcrumb-item" :class="{current: !breadcrumbList.length}">根目录</span>
      <span v-for="(item, idx) in breadcrumbList" :key="idx">
        <span class="separator">/</span>
        <span @click="changeDir(item.path)" class="breadcrumb-item" :tabindex="isTvMode ? 0 : undefined" :class="{current: idx === breadcrumbList.length - 1}">{{ item.name }}</span>
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
        :tabindex="isTvMode ? 0 : undefined"
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
          <div v-else-if="item.type === 'video'">
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
          <!-- 角标 -->
          <div v-if="item.type === 'folder'" class="card-badge">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>{{ item.count }}
          </div>
          <div v-else-if="item.type === 'video' && item.duration" class="card-badge">
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

    <!-- 预览弹窗。手势挂在整个预览层上：视频、画面留白、底部按钮栏，
         任意位置左右滑快进、上下滑调音量都要生效（以前只在视频区域里才响应） -->
    <!-- 全屏元素是 .preview-box（top layer 只渲染它和它的子树），
         所以手势必须挂在它身上全屏时才收得到；遮罩那套加 .self 只补最外圈黑边，
         两者互斥，不会一次触摸触发两遍 -->
    <div v-if="previewShow" class="preview-mask" @click.self="onPreviewMaskClick" @wheel="stopOverlayWheel"
         @touchstart.self="onTouchStart" @touchmove.self="onTouchMove"
         @touchend.self="onTouchEnd" @touchcancel.self="onTouchCancel">
      <div class="preview-box" ref="previewBoxRef" @click="onPreviewBoxClick"
           @pointerdown="onSurfacePointerDown"
           @touchstart="onTouchStart" @touchmove="onTouchMove"
           @touchend="onTouchEnd" @touchcancel="onTouchCancel">
        <button class="close-btn" ref="closeBtnRef" :style="closeBtnStyle" @click="closePreview">×</button>
        <!-- 视频预览不显示左右切换箭头：方向键已改为快进/后退（浏览器、手机、
             电视都一样，TV 切下一个视频改用上下键），箭头只留给图片 -->
        <button v-if="previewItem.type === 'image'" class="arrow-btn arrow-left" @click.stop="prevMedia" :disabled="previewCurrentIndex <= 0">‹</button>
        <button v-if="previewItem.type === 'image'" class="arrow-btn arrow-right" @click.stop="nextMedia" :disabled="previewCurrentIndex >= previewMediaList.length - 1">›</button>
        <div class="preview-image-area">
          <img
            v-if="previewItem.type === 'image'"
            ref="previewMediaRef"
            :src="getSrcUrl(previewItem.path)"
            alt=""
            :style="imgRotateStyle"
            @load="updateCloseBtnPos"
          />
          <video
            v-else
            ref="previewMediaRef"
            controls
            autoplay
            playsinline
            :src="getSrcUrl(previewItem.path)"
            @loadedmetadata="onPreviewMediaReady"
            @play="onVideoPlayback(false, $event)"
            @pause="onVideoPlayback(true, $event)"
          ></video>
        </div>
        <div class="preview-footer" :class="{'footer-compact': previewItem.type !== 'image' && !isTvMode}">
          <div class="preview-name">{{ previewItem.name }} ({{ previewCurrentIndex + 1 }} / {{ previewMediaList.length }})</div>
          <div v-if="previewItem.type === 'image'" class="img-action-bar">
            <button @click="openOriginal">查看原图</button>
            <button @click="rotateLeft">↺ 左旋90°</button>
            <button @click="rotateRight">↻ 右旋90°</button>
            <button @click="resetRotate">重置旋转</button>
            <button @click="startSlideFromCurrent">从此处开始幻灯片</button>
          </div>
          <!-- 电视只有遥控器，没有可点的按钮：把键位直接写在画面上，
               否则「左右快进、上下切换、OK 暂停」全靠猜 -->
          <p v-if="isTvMode" class="tv-key-hint">
            <template v-if="previewItem.type === 'image'">
              方向键 切换上一个 / 下一个　·　返回键 退出
            </template>
            <template v-else>
              {{ previewPaused ? '已暂停' : '播放中' }}　·　OK {{ previewPaused ? '继续播放' : '暂停' }}　·　◀ ▶ 快进 / 后退 10 秒　·　▲ ▼ 切换
            </template>
          </p>
        </div>
        <!-- 全屏元素换成 .preview-box 后，只有它子树里的 DOM 才会被渲染。
             提示层必须放一份在这里，全屏时的快进/音量/播放提示才看得见 -->
        <div v-if="seekHud.show" class="seek-hud">{{ seekHud.deltaText }}</div>
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
          <button v-if="userInfo.is_admin" @click="saveSetting" class="btn primary">保存</button>
          <button @click="settingShow=false" class="btn">{{ userInfo.is_admin ? '取消' : '关闭' }}</button>
        </div>
        <p v-if="!userInfo.is_admin" class="setting-hint">这组设置对所有人生效，只有管理员可以修改。</p>
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
              <div>用户名</div>
              <div>角色</div>
              <div>允许目录</div>
              <div>操作</div>
            </div>
            <div class="um-table-row" v-for="u in adminUserList" :key="u.username">
              <div>{{u.username}}</div>
              <div>
                <span v-if="u.is_admin" class="tag-admin">管理员</span>
                <span v-else class="tag-user">普通用户</span>
              </div>
              <div>{{u.allow_dirs.join("; ")}}</div>
              <div>
                <button class="btn btn-sm" @click="switchToEditForm(u)">编辑</button>
                <button class="btn btn-sm btn-danger" @click="openDelConfirm(u)">删除</button>
              </div>
            </div>
          </div>

          <!-- 登录锁定：按「账号 + 来源 IP」两个维度查看与一键解锁 -->
          <div class="guard-section">
            <div class="guard-head">
              <div class="guard-title">登录锁定 <span class="guard-count">{{ guardList.length }}</span></div>
              <div class="guard-actions">
                <button class="btn btn-sm" @click="loadLoginGuard()">刷新</button>
                <button class="btn btn-sm" @click="unlockAllGuard" :disabled="!guardList.length">全部解锁</button>
              </div>
            </div>
            <div class="guard-hint">按「账号 + 来源 IP」分别锁定：别人从自己设备输错，不会锁住你的设备。IP 维度限制该来源对所有账号的尝试。</div>
            <div class="msg-tip">{{ guardMsg }}</div>
            <div v-if="!guardList.length" class="guard-empty">当前没有失败或锁定记录</div>
            <div v-else class="guard-table">
              <div class="guard-row guard-row-head">
                <div>账号 / 范围</div><div>来源 IP</div><div>失败</div><div>剩余锁定</div><div>操作</div>
              </div>
              <div v-for="(g, gi) in guardList" :key="gi" class="guard-row">
                <div>{{ g.kind === 'ip' ? '全部账号（IP 维度）' : g.username }}</div>
                <div class="guard-ip">{{ g.ip }}</div>
                <div>{{ g.fails }}</div>
                <div :class="{'guard-locked': g.locked}">{{ g.locked ? formatGuardLeft(g.left) : '—' }}</div>
                <div><button class="btn btn-sm" @click="unlockGuard(g)">解锁</button></div>
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
          <h3>缓存失败文件（{{ cacheStats.failed_files.length }}<template v-if="cacheStats.failed_files_truncated">，共 {{ cacheStats.failed }} 条，仅显示前 500</template>）</h3>
          <button class="um-close-btn" @click="failedFilesModal=false">×</button>
        </div>
        <div v-if="cacheStats.failed_files_truncated" class="failed-truncate-tip">
          失败太多，明细只保留前 500 条；完整清单请用「执行日志」或直接在 NAS 上排查。
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
    <div v-if="slideShow" class="slide-root" @wheel="stopOverlayWheel">
      <div class="slide-content"
           @touchstart="onTouchStart"
           @touchmove="onTouchMove"
           @touchend="onTouchEnd"
           @touchcancel="onTouchCancel">
        <img v-if="currentSlide.type==='image'" :src="getSrcUrl(currentSlide.path)" alt="" />
        <video v-else ref="slideVideoRef" controls autoplay muted playsinline :src="getSrcUrl(currentSlide.path)"
               @play="onVideoPlayback(false, $event)" @pause="onVideoPlayback(true, $event)"></video>
        <div class="slide-name">{{ currentSlide.name }}</div>
        <button class="slide-exit-btn" @click="exitSlide">退出全屏</button>
        <button class="slide-prev-btn" @click="slidePrev">‹</button>
        <button class="slide-next-btn" @click="slideNext">›</button>
      </div>
    </div>

    <!-- 幻灯片 / 列表页那份提示。预览打开时由 .preview-box 内那份负责，
         两者互斥，不会同时出现两个（fixed + 极高 z-index 保证盖得住） -->
    <div v-if="seekHud.show && !previewShow" class="seek-hud">{{ seekHud.deltaText }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'

const baseUrl = ''
// TV 客户端的 WebView 在 UA 里加了 WaterfallAlbumTV 标记；
// 浏览器与手机 App 检测不到，所有 TV 逻辑都不会生效
const isTvMode = typeof navigator !== 'undefined' && /WaterfallAlbumTV/.test(navigator.userAgent)
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

// 登录失败阶梯锁定：后端 429 带 retry_after，前端倒计时并禁用登录按钮。
// 倒计时只在本机显示，真正的锁定判定在后端（刷新页面后点一次即可恢复倒计时）
const loginLockRemaining = ref(0)
let loginLockDeadline = 0
let loginLockTimer = null

function formatLockClock(sec) {
  const s = Math.max(0, Math.ceil(sec))
  const m = Math.floor(s / 60)
  return m > 0 ? `${m}:${String(s % 60).padStart(2, '0')}` : `${s} 秒`
}
function stopLoginLock() {
  if (loginLockTimer) clearInterval(loginLockTimer)
  loginLockTimer = null
  loginLockDeadline = 0
  loginLockRemaining.value = 0
}
function startLoginLock(seconds) {
  if (loginLockTimer) clearInterval(loginLockTimer)
  const secs = Math.max(1, Math.ceil(Number(seconds) || 0))
  loginLockDeadline = Date.now() + secs * 1000
  loginLockRemaining.value = secs
  loginLockTimer = setInterval(() => {
    const left = Math.ceil((loginLockDeadline - Date.now()) / 1000)
    if (left <= 0) {
      stopLoginLock()
      loginErr.value = '锁定已解除，可以重新登录'
      return
    }
    loginLockRemaining.value = left
  }, 1000)
}

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
// 登录锁定：管理员查看与一键解锁
const guardList = ref([])
const guardMsg = ref('')

const mediaList = ref([])
const breadcrumbList = ref([])
const currentDir = ref('')
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
  login_locked: '登录锁定',
  login_unlock: '解除锁定',
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
  if (['user_delete', 'logs_clear', 'cache_stop', 'login_locked', 'login_unlock'].includes(action)) return true
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
// 必须用 ref：这两个值直接参与模板（箭头 disabled、第 n / 共 m 张）。
// 用普通变量时只能靠 previewItem 变化顺带触发重渲染，一旦哪天只改下标
// 就会「数据变了、界面不动」，属于埋雷
const previewMediaList = ref([])
const previewCurrentIndex = ref(0)
const imgRotateDeg = ref(0)
/** 预览里的视频是否暂停着：画面中间那个大按钮与电视端的键位提示都靠它 */
const previewPaused = ref(false)
const settingShow = ref(false)
const slideDelay = ref(3)
const slideLoop = ref(true)
const slideShow = ref(false)
const slideIndex = ref(0)
const slideTimer = ref(null)
const slideList = ref([])
const currentSlide = ref({})
// 随机幻灯片换批是异步的：await 期间 slideIndex 暂时越界且没有计时器，
// 方向变化触发的 runSlide 不能在这时插进来重设 currentSlide 或另起计时器
let slideBatchReloading = false
// 每次启动/退出幻灯片递增：在途的换批请求回来后凭它判断自己是否已作废
let slideSessionId = 0
// 首次建索引等待期间的显式取消（手机没有 ESC 键，靠再点一次按钮）
let randomSlideCancelled = false
// 首页随机幻灯片：全库随机抽取；预览里的「从此处开始幻灯片」仍是顺序播放
const randomSlideLoading = ref(false)
const randomSlideMode = ref(false)
const randomBatchLoading = ref(false)
// 首次启动后台要在后台建图片索引，大库可能要几十秒，这里把它显示出来
const randomSlideHint = ref('')
const RANDOM_BATCH_SIZE = 1000
// 后端索引未就绪时返回 code=2：首点最多等 90 秒（NAS 冷扫 100 万图约 22~45 秒），
// 换批只等 8 秒——换批失败有洗牌兜底，不能让播放干等
const RANDOM_INDEX_WAIT_MS = 90000
const RANDOM_BATCH_WAIT_MS = 8000
const RANDOM_INDEX_RETRY_MS = 2000
// 单次取数最长等待：连接挂起时不能让 slideBatchReloading / randomBatchLoading
// 永久卡在 true，否则幻灯片再也不计时、按钮永远 disabled
const RANDOM_FETCH_TIMEOUT_MS = 12000

// ========= 全屏幻灯片方向策略 =========
// 不锁设备方向、不弹方向提示：横屏竖屏都由 CSS 自适应布局，
// 轮播在任何方向下都继续播放。旋转只改变视口尺寸，不重载页面也不中断计时，
// 具体适配见 .slide-root / .slide-content 的媒体查询与安全区设置。

const cacheRunning = ref(false)
const cachePercent = ref(0)
let statusPollTimer = null
// 本次会话是否亲自点过「预生成缓存」。接管别人任务的进度时不该弹「任务结束」
let cacheTaskOwnedByMe = false
// 组件卸载后，在途请求返回时不要再把轮询链重新挂起来
let disposed = false
// 缓存统计：total 全部 / cached 已缓存 / uncached 未缓存 / failed 失败 / failed_files 失败文件 / last_finish_time 上次完成时间
const cacheStats = ref({ total: 0, cached: 0, uncached: 0, failed: 0, failed_files: [], failed_files_truncated: false, last_finish_time: null })
// 执行日志
const logModal = ref(false)
const logList = ref([])
// 缓存失败文件弹窗
const failedFilesModal = ref(false)

// ========= JS瀑布流【响应式：手机2列 / 平板3-4列 / 桌面270px】 =========
let resizeTimer = null
let imageLoadTimer = null
// 卡片高度缓存：图片逐张加载时不再全量读 offsetHeight，避免 O(n^2) 的强制重排
const cardHeightCache = new Map()
// 上一次的列宽：卡片高度依赖宽度，列宽一变缓存就整体失效
let lastCardWidth = null

// 根据容器宽度决定列数与卡片宽度（均分填满整行，无留白、无边界跳变）
function getCardLayout(boxWidth) {
  const gap = 12
  let colCount
  if (isTvMode) {
    // 10-foot 界面：卡片更大、列数更少，1920 宽的电视约 5 列
    colCount = Math.max(3, Math.min(6, Math.round((boxWidth + gap) / (360 + gap))))
  } else if (boxWidth < 480) {
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
  if(!waterfallBoxRef.value) return
  // 目录被清空 / 搜索无结果时要撤掉上一次写死的高度，
  // 否则空状态下面会挂着一条跟刚才列表一样高的空白滚动区
  if(!list.length){
    waterfallBoxRef.value.style.height = ''
    return
  }
  const boxWidth = waterfallBoxRef.value.clientWidth
  const { cardWidth, gap, colCount } = getCardLayout(boxWidth)

  // 首次布局或列宽变化时，缓存是在旧宽度下测出来的，必须整体作废
  if (lastCardWidth === null || Math.abs(cardWidth - lastCardWidth) > 0.5) {
    cardHeightCache.clear()
  }
  lastCardWidth = cardWidth

  // 先设列宽再测高度：否则读到的 offsetHeight 属于旧的 270px 回退宽度
  waterfallBoxRef.value.style.setProperty('--card-width', cardWidth + 'px')
  // 间距由下面的 JS 常量 gap 直接参与定位，不需要再写一个没人读的 CSS 变量

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
  // 与窗口 resize 各用一条定时器：原来共用 resizeTimer，
  // 图片 load 会把刚排队的 resize 布局（含叉号重定位）直接取消掉
  clearTimeout(imageLoadTimer)
  imageLoadTimer = setTimeout(()=>{
    layoutWaterfall()
  },120)
}

watch(displayList, async ()=>{
  cardHeightCache.clear()
  await nextTick()
  layoutWaterfall()
  // 电视上没有鼠标，列表出来后必须主动给一张卡片焦点，否则遥控器无从下手。
  // 焦点已在顶栏输入/按钮或某张卡片上时不动它，避免抢焦点
  if (isTvMode && !previewShow.value && !slideShow.value && !settingShow.value &&
      !userManageModal.value && !logModal.value && !changePwdModal.value &&
      !failedFilesModal.value) {
    const el = document.activeElement
    const onCard = el && el.classList && el.classList.contains('media-card')
    // 弹窗、搜索框、按钮正拿着焦点时不抢；只有焦点落在页面上才给首卡
    const busy = el && (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(el.tagName)
      || el.isContentEditable)
    if (!onCard && !busy) {
      const first = document.querySelector('.media-card')
      if (first) first.focus({ preventScroll: true })
    }
  }
})

function onWindowResize(){
  // 列宽变化会让所有卡片高度失效，必须重新测量
  cardHeightCache.clear()
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(()=>{
    layoutWaterfall()
    updateCloseBtnPos()
  },150)
}

const getThumbUrl = (path) => {
  return `${baseUrl}/api/thumb?path=${encodeURIComponent(path)}`
}
const getSrcUrl = (path) => {
  return `${baseUrl}/api/src?path=${encodeURIComponent(path)}`
}

// 旋转只保留一个角度源，样式由它派生，避免两份状态不同步
const imgRotateStyle = computed(() => ({
  transform: `rotate(${imgRotateDeg.value}deg)`,
  transition: 'transform 0.25s ease'
}))

// 预览关闭按钮跟随图片实际显示区域的右上角；未测量到时回退到容器右上角（CSS 默认）
const previewBoxRef = ref(null)
const previewMediaRef = ref(null)
const slideVideoRef = ref(null)
const closeBtnRef = ref(null)
const closeBtnStyle = ref({})

async function updateCloseBtnPos() {
  await nextTick()
  const box = previewBoxRef.value
  const media = previewMediaRef.value
  const btn = closeBtnRef.value
  if (!box || !media || !btn) return
  const br = box.getBoundingClientRect()
  const mr = media.getBoundingClientRect()
  if (!mr.width || !mr.height) return
  const gap = 8
  const bw = btn.offsetWidth || 34
  const bh = btn.offsetHeight || 34
  // 视频：贴预览框最外侧右上角，别贴画面右上角——原生媒体控件的音量/倍速
  // 按钮在那一片，会与 × 叠在一起。图片仍按视觉区域右上角计算（含旋转）
  let left, top
  if (media.tagName === 'VIDEO') {
    left = br.width - bw - gap
    top = gap
  } else {
    left = mr.right - br.left - bw - gap
    top = mr.top - br.top + gap
  }
  left = Math.max(gap, Math.min(left, br.width - bw - gap))
  top = Math.max(gap, Math.min(top, br.height - bh - gap))
  closeBtnStyle.value = { left: left + 'px', top: top + 'px', right: 'auto' }
}

// 视频预览：元数据就绪即自动播放；被浏览器策略拦截时静音重试，保证点开就播
let videoMutedFallback = false
let closeBtnPosTimer = null

function scheduleCloseBtnPos() {
  clearTimeout(closeBtnPosTimer)
  closeBtnPosTimer = setTimeout(updateCloseBtnPos, 260)
}

function onPreviewMediaReady() {
  updateCloseBtnPos()
  const v = previewMediaRef.value
  if (!v || v.tagName !== 'VIDEO') return
  // 上一个视频因策略降级为静音时，新视频先恢复有声再尝试
  if (videoMutedFallback) {
    v.muted = false
    videoMutedFallback = false
  }
  previewPaused.value = false
  const p = v.play()
  if (p && typeof p.catch === 'function') {
    p.catch(() => {
      v.muted = true
      videoMutedFallback = true
      // 部分 WebView 的 play() 返回 undefined，直接 .catch 会抛 TypeError
      const p2 = v.play()
      if (p2 && typeof p2.catch === 'function') p2.catch(() => {})
    })
  }
}

watch(previewShow, async (show) => {
  closeBtnStyle.value = {}
  if (!show) return
  await nextTick()
  updateCloseBtnPos()
})

function rotateLeft() {
  imgRotateDeg.value -= 90
  scheduleCloseBtnPos()
}
function rotateRight() {
  imgRotateDeg.value += 90
  scheduleCloseBtnPos()
}
function resetRotate() {
  imgRotateDeg.value = 0
  scheduleCloseBtnPos()
}
function openOriginal() {
  // noopener：新标签页不该拿得到本页的 window.opener（反向 tabnabbing），
  // 这里打开的虽然是同源图片，顺手关上这个口子没有代价
  window.open(getSrcUrl(previewItem.value.path), '_blank', 'noopener')
}

// 用「一次请求完成后再排下一次」代替 setInterval：NAS 响应慢于 800ms 时
// 不会把请求一层层堆起来；重复启动也只会有一条链。
function stopStatusPoll() {
  if (statusPollTimer) clearTimeout(statusPollTimer)
  statusPollTimer = null
}
function startStatusPoll() {
  stopStatusPoll()
  statusPollTimer = setTimeout(pollCacheStatus, 800)
}
async function pollCacheStatus() {
  statusPollTimer = null
  try {
    const res = await fetch(`${baseUrl}/api/cache-status`)
    if (disposed) return
    if (!res.ok) {
      checkAuthResp(res)
      stopStatusPoll()
      cacheRunning.value = false
      return
    }
    const st = await res.json()
    if (disposed) return
    cachePercent.value = st.percent
    if (!st.running) {
      stopStatusPoll()
      cacheRunning.value = false
      loadCacheStats()
      // 只是接管了别人（或定时任务）的进度时，不给当前用户弹完成提示
      if (cacheTaskOwnedByMe) alert(`✅缓存任务结束！\n${st.message}`)
      cacheTaskOwnedByMe = false
      return
    }
    startStatusPoll()
  } catch (err) {
    console.error("查询任务状态失败", err)
    if (disposed) return
    startStatusPoll()  // 网络抖动继续重试，不中断进度显示
  }
}

async function initCheckCacheTask() {
  // 非管理员看不到缓存入口，也不该接管上一位管理员留下的轮询链
  if (!userInfo.value.is_admin) {
    stopStatusPoll()
    cacheRunning.value = false
    cachePercent.value = 0
    cacheTaskOwnedByMe = false
    return
  }
  try {
    const res = await fetch(`${baseUrl}/api/cache-status`)
    if (!res.ok) { checkAuthResp(res); return }
    const st = await res.json()
    if (st.running) {
      cacheRunning.value = true
      cachePercent.value = st.percent
      startStatusPoll()
    } else {
      // 重新登录时任务可能已经结束，必须复位，否则永远显示「缓存处理中」
      cacheRunning.value = false
      cachePercent.value = 0
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
    if (!res.ok) {
      // 先复位再交给鉴权处理，否则界面会永远停在「缓存处理中 0%」
      cacheRunning.value = false
      checkAuthResp(res)
      return
    }
    const ret = await res.json()
    if (ret.code !== 0) {
      if (ret.code === 1) {
        // code=1 = 后端已有任务在跑：接管进度显示，这不是失败，别弹错误框
        startStatusPoll()
      } else {
        alert("❌" + ret.msg)
        cacheRunning.value = false
      }
      return
    }
    cacheTaskOwnedByMe = true
    startStatusPoll()
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
  // 深链首次加载时 URL 已经指向这个目录，再压一条会让第一次后退「看不出反应」
  if ((new URL(window.location.href).searchParams.get('dir') ?? '') === dir) {
    window.history.replaceState({ dir }, '', url.toString())
    return
  }
  window.history.pushState({ dir }, '', url.toString())
}

// 预览弹窗占用一条浏览器历史：按后退只关预览，不把目录一起退回去
let previewHistoryPushed = false

function pushPreviewHistory() {
  if (previewHistoryPushed) return
  try {
    window.history.pushState(
      { ...(window.history.state || {}), preview: true },
      '',
      window.location.href
    )
    previewHistoryPushed = true
  } catch (e) {
    // 历史 API 不可用时退化为原行为，不影响预览本身
  }
}

let lastForbiddenAlert = 0
function checkAuthResp(r) {
  if (r.status === 401) {
    // 会话过期：把弹窗、列表、幻灯片全部复位，不能只切登录页
    resetUiState()
    stopStatusPoll()
    cacheRunning.value = false
    cachePercent.value = 0
    cacheTaskOwnedByMe = false
    isLogin.value = false
    userInfo.value = {}
  } else if (r.status === 403) {
    // 静默刷新 / 进度轮询也走这里，降权后每 800ms 一次会把 alert 打爆，
    // 所以同类提示 30 秒内只弹一次
    const now = Date.now()
    if (now - lastForbiddenAlert > 30000) {
      lastForbiddenAlert = now
      alert('没有权限执行此操作，请确认账号权限')
    }
  }
}

const isLoading = ref(false)
// 加载中又来了新的目录请求：只保留最后一次，等当前请求结束再执行
let pendingLoad = null
const LIST_REFRESH_MS = 15000  // 静默刷新间隔，与后端目录校验周期配套
let listRefreshTimer = null

// 只比较业务字段：瀑布流会把 _left/_top/_loaded 挂到 item 上，
// 直接 JSON.stringify 会永远不相等，导致每次轮询都重排闪烁
function listSignature(list) {
  return JSON.stringify(list.map(x => [x.id, x.name, x.type, x.count,
    x.size, x.mtime, x.cover_path, x.duration]))
}

// 静默刷新互斥：定时器和 visibilitychange 都会触发，NAS 上单次请求可能
// 超过刷新间隔，不拦住就会叠请求、先发后到的旧响应还会盖掉新数据
let silentRefreshing = false

async function silentRefreshList() {
  if (silentRefreshing) return
  if (!isLogin.value || document.visibilityState !== 'visible') return
  if (isLoading.value || previewShow.value || slideShow.value ||
      userManageModal.value || logModal.value || changePwdModal.value ||
      settingShow.value || failedFilesModal.value) return
  silentRefreshing = true
  const dirAtStart = currentDir.value
  // 请求挂住时不能让互斥标记一直占着，否则静默刷新永久停摆
  const abortCtrl = new AbortController()
  const abortTimer = setTimeout(() => abortCtrl.abort(), 8000)
  try {
    const res = await fetch(`${baseUrl}/api/list?dir=${encodeURIComponent(dirAtStart)}`,
      { signal: abortCtrl.signal })
    if (!res.ok) { checkAuthResp(res); return }
    const data = await res.json()
    // 请求期间用户可能已切换目录（或新的加载正在进行）。
    // NAS 上旧请求可能更慢，不能让它把旧目录的数据盖回当前页面。
    if (!isLogin.value || currentDir.value !== dirAtStart || isLoading.value) return
    const next = data.list || []
    if (listSignature(next) !== listSignature(mediaList.value)) {
      // 必须保留瀑布流挂在 item 上的 UI 字段：img 按 :key 复用、src 没变就不会
      // 再触发 load，丢掉 _loaded 会让整页缩略图永久停在 opacity:0 的骨架态
      const prev = new Map(mediaList.value.map(x => [x.id, x]))
      mediaList.value = next.map(item => {
        const old = prev.get(item.id)
        if (!old) return item
        item._loaded = old._loaded
        item._left = old._left
        item._top = old._top
        return item
      })
      breadcrumbList.value = data.breadcrumb || []
    }
  } catch (e) {
    // 静默失败（含 8 秒超时中断），不打扰正在浏览的用户
  } finally {
    clearTimeout(abortTimer)
    silentRefreshing = false
  }
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible') silentRefreshList()
}

async function loadMedia(dir = '', pushHistory = false) {
  // 正在加载时不并发打 NAS：记下最后一次目标，当前请求结束后接着加载它，
  // 这样加载中按后退不会被静默丢弃（否则 URL 变了、列表还停在旧目录）
  if (isLoading.value) {
    pendingLoad = { dir, pushHistory }
    return
  }
  isLoading.value = true
  currentDir.value = dir
  // 导航意图要立刻反映到地址栏：如果等响应回来再压栈，加载中途按后退时
  // 排队请求会让列表退到旧目录、URL 却还留在新目录
  if (pushHistory) syncDirToUrl(dir)
  mediaList.value = []
  breadcrumbList.value = []
  try {
    const res = await fetch(`${baseUrl}/api/list?dir=${encodeURIComponent(dir)}`)
    if (!res.ok) { checkAuthResp(res); return }
    const data = await res.json()
    // 请求在途时用户可能已经登出，别把上一位用户的目录内容写回来
    if (!isLogin.value) return
    mediaList.value = data.list || []
    breadcrumbList.value = data.breadcrumb || []
  } catch (err) {
    console.error(err)
    mediaList.value = []
  }finally{
    isLoading.value = false
    if (pendingLoad && isLogin.value) {
      const next = pendingLoad
      pendingLoad = null
      loadMedia(next.dir, next.pushHistory)
    }
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
    previewMediaList.value = displayList.value.filter(x => x.type !== 'folder')
    previewCurrentIndex.value = previewMediaList.value.findIndex(x => x.id === item.id)
    muteVideoPlaybackHint()   // 打开预览时的自动播放不弹「播放」
    resetSurfaceTap()
    previewItem.value = item
    resetRotate()
    previewShow.value = true
    pushPreviewHistory()
  }
}

function prevMedia() {
  if (previewCurrentIndex.value > 0) {
    muteVideoPlaybackHint()   // 换片会连带触发 pause/play，别弹「已暂停」
    resetSurfaceTap()         // 点按状态从头算，防护别跨片残留
    previewCurrentIndex.value -= 1
    previewItem.value = previewMediaList.value[previewCurrentIndex.value]
    resetRotate()
  }
}

function nextMedia() {
  if (previewCurrentIndex.value < previewMediaList.value.length - 1) {
    muteVideoPlaybackHint()   // 同上：换片时的 pause/play 不提示
    resetSurfaceTap()
    previewCurrentIndex.value += 1
    previewItem.value = previewMediaList.value[previewCurrentIndex.value]
    resetRotate()
  }
}

// ========= 移动端滑动：图片切张 / 视频快进后退 / 视频音量 =========
// 图片沿用「左滑下一张」。视频第一次移动超过 6px 即锁定方向：横向按秒预览
// 目标进度、松手才 seek（避免拖动中反复解码卡顿）；纵向逐像素实时调音量。
// 预览区域内的 touchmove 一律拦默认行为，纵向滑动不会再带到底层页面。
// 原生视频全屏时 WebView 收不到触摸，由客户端回传两轴比例给
// __albumVideoGestureStart / __albumVideoGestureUpdate，公式共用这一份。
// 一屏最多 2 分钟：手机 400px 宽约 0.3 秒/像素，能卡到具体某一秒；
// 长片要跳远就多滑几次，每次松手后从新位置继续
const SEEK_MAX_SPAN = 120
const GESTURE_MIN_DIST = 6     // 6px 即触发，小幅滑动也能立刻看到反馈
const NATIVE_BAR_HEIGHT = 36   // 只放行进度条最底下的一条，不占整条控制栏
const VOL_FULL_SPAN = 0.9      // 纵向滑一屏高度约改 90% 音量，逐像素连续调节
const KEY_SEEK_STEP = 10       // 键盘左右键每次快进/后退 10 秒
const KEY_VOLUME_STEP = 0.02   // 键盘上下键每次调 2% 音量
// 全屏时 top layer 只画 <video>，那行 HUD 不在全屏子树里、看不见，
// 2% 的差别听不出来，按一下像没反应。全屏用 10%，靠听感就能确认
const KEY_VOLUME_STEP_FULLSCREEN = 0.1
let touchStartX = 0
let touchStartY = 0
/** 本次手势是否从有效的单指触摸开始：多指/触摸取消都不该再触发切图或 seek */
let touchTracking = false
/** 兜底：touchend 的 preventDefault 万一没拦住合成 click，短时间内忽略点空白退出 */
let suppressPreviewClickUntil = 0
let seekVideoEl = null
let seekBaseTime = 0
let seekBaseVolume = 0
let seekDuration = 0
let seekActive = false
/** 起点落在原生控制条上：这一次完全不拦默认行为，让浏览器自己拖进度条 */
let touchNativeBar = false
/** 一次手势只锁定一个轴：'h' 快进后退 / 'v' 音量，避免斜滑时两种操作互相打架 */
let gestureAxis = null
let seekHudTimer = null
/** 一行提示：快进/后退报秒数、音量报百分比、播放/暂停报状态。
 *  与手机客户端原生全屏那行提示保持同一套文案与视觉，方便一眼对上 */
const seekHud = ref({ show: false, deltaText: '' })

/** 点是否落在视频画面上（画面外的黑边、底部名字栏都不算） */
function onVideoSurface(x, y, v) {
  if (!v) return false
  const r = v.getBoundingClientRect()
  if (!r.width || !r.height) return false
  return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom
}

/** 触摸起点是否落在视频底部让给原生进度条的那一条（手势放行区，36px）。
 *  上下都要限死：只判「比底边靠下」会把底部文件名栏、画面外的黑边一起算成
 *  控制条，那些位置的手势被整段放行掉，等于滑动无效区 */
function inNativeBar(clientY, v) {
  if (!v) return false
  const r = v.getBoundingClientRect()
  if (!r.height) return false
  const top = r.bottom - Math.min(NATIVE_BAR_HEIGHT, r.height * 0.25)
  return clientY > top && clientY <= r.bottom
}

/** 点按是否落在原生控制条的按钮区。比手势放行区略宽，
 *  保证播放/暂停按钮不会被「点画面不切播放」的防护误撤销；
 *  手势仍只用 36px，不会重新出现大块滑动无效区。
 *  同样限定在视频矩形内：画面下方的名字栏不算控制条 */
function inControlsClickArea(clientY, v) {
  if (!v) return false
  const r = v.getBoundingClientRect()
  if (!r.height) return false
  const top = r.bottom - Math.min(48, r.height * 0.25)
  return clientY > top && clientY <= r.bottom
}

function getActiveVideo() {
  const v = slideShow.value ? slideVideoRef.value : previewMediaRef.value
  return v && v.tagName === 'VIDEO' ? v : null
}

function videoDuration(v) {
  const d = v ? v.duration : NaN
  return Number.isFinite(d) && d > 0 ? d : 0
}

/** 位移比例 → 秒。公式只在这里定义，前端手势与原生全屏共用，避免手感漂移 */
function ratioToSeconds(ratio, dur) {
  return ratio * Math.min(dur, SEEK_MAX_SPAN)
}

function clampSeekTime(base, delta, dur) {
  return Math.min(Math.max(0, base + delta), Math.max(0, dur - 0.1))
}

/** 真正执行 seek，返回实际落点相对起点的秒数差；视频不可 seek 时返回 null */
function seekVideoBy(delta, v = getActiveVideo(), base = null) {
  const dur = videoDuration(v)
  if (!v || !dur) return null
  // 内联手势传按下时的时间：拖动期间视频还在播放，若用当前 currentTime，
  // 松手落点会比 HUD 预览的目标时间多出这几秒。原生全屏不传 base，用当前值
  const from = base === null ? (v.currentTime || 0) : base
  const target = clampSeekTime(from, delta, dur)
  try { v.currentTime = target } catch (e) { return null }
  return target - from
}

/** 统一的 HUD 出口：所有提示都走这里，保证只有一份倒计时 */
function showHud(text) {
  seekHud.value = { show: true, deltaText: String(text || '') }
  clearTimeout(seekHudTimer)
  seekHudTimer = setTimeout(hideSeekHud, 1500)
}

/** 加减秒数的文本，前端大字与原生全屏 HUD 共用。符号取自原始位移，
 *  这样拖回起点附近时仍显示「−0 秒」而不是忽然变成正向 */
function formatDelta(delta) {
  const raw = Number(delta) || 0
  return (raw < 0 ? '−' : '+') + Math.round(Math.abs(raw)) + ' 秒'
}

/** 快进/后退：只显示加减秒数，落点交给视频自己的进度条 */
function showSeekHud(delta) {
  showHud(formatDelta(delta))
}

function hideSeekHud() {
  clearTimeout(seekHudTimer)
  seekHudTimer = null
  seekHud.value.show = false
}

function resetSeekGesture() {
  seekVideoEl = null
  seekActive = false
  touchNativeBar = false
  gestureAxis = null
  seekDuration = 0
  seekBaseTime = 0
  seekBaseVolume = 0
}

/** 键盘左右键：固定 10 秒快进/后退，复用横滑那套 seek 与 HUD */
function keySeekVideo(delta) {
  const applied = seekVideoBy(delta)
  if (applied !== null) showSeekHud(applied)
}

/** 写音量：精确到 1%（键盘 2% 步进、纵向手势逐像素都用它），并读回确认是否生效 */
function applyVolume(v, wanted) {
  const next = Math.min(1, Math.max(0, Math.round(wanted * 100) / 100))
  if (next > 0 && v.muted) {
    // 自动播放被浏览器策略拦截时会降级为静音；目标音量不为 0 就说明用户想听声，
    // 顺带解除静音（减小音量时同样生效）
    try { v.muted = false } catch (e) { /* 忽略 */ }
  }
  let applied = false
  try {
    v.volume = next
    applied = Math.abs((typeof v.volume === 'number' ? v.volume : next) - next) < 0.005
  } catch (e) { applied = false }
  return { applied, value: next }
}

function showVolumeHud(value, applied) {
  showHud(applied ? '音量 ' + Math.round(value * 100) + '%' : '音量不可调')
}

/** 键盘上下键：每次 2% 音量 */
function adjustVideoVolume(delta) {
  const v = getActiveVideo()
  if (!v) return
  let base = 1
  try { if (typeof v.volume === 'number') base = v.volume } catch (e) { /* 用默认值 */ }
  const r = applyVolume(v, base + delta)
  showVolumeHud(r.value, r.applied)
}

/** 点视频画面 = 只让原生控制条出现，绝不切换播放状态。
 *  暂停/播放只有三个入口：控制条上的播放/暂停按钮、空格键、TV 的 OK 键。
 *  麻烦在于 Chrome 点 <video> 本体会自己顺手切一次播放，所以每次点画面都要
 *  架一层防护：拦下紧接着的那个 play/pause 并还原；个别 WebView 不派发事件时
 *  用 150ms 定时兜底再比一次状态。 */
let surfaceTapLastAt = 0        // touch 与 click 两路只算一次点按
let surfaceRestoreUntil = 0
let surfaceRestoreVideo = null
let surfaceRestorePaused = false   // 点按前的 v.paused，要还原成这个状态
let surfaceRestoreTimer = null
// pointerdown 时记下的「点击前是否暂停」。Chrome 点 <video> 本体会在 click 的
// target 阶段就把播放切掉（原生控件是 shadow DOM，它的处理先于冒泡到 .preview-box
// 的 click），等我们架防护时 v.paused 已经是被切过的值；拿它当「点击前状态」，
// 就会把「暂停」当成要还原的目标，于是点了永远是暂停。pointerdown 一定早于那次
// 切换，只能从这里记
let surfacePausedBeforeTap = null
let surfacePausedBeforeTapAt = 0

/** 把浏览器自己切走的播放状态还原，并压住还原引发的提示 */
function restoreVideoPlayback(v, wantPaused) {
  if (wantPaused) {
    try { v.pause() } catch (e) { /* 忽略 */ }
  } else {
    const p = v.play()
    if (p && typeof p.catch === 'function') p.catch(() => {})
  }
  muteVideoPlaybackHint()
}

/** 点画面之后架好防护 */
function armPlaybackGuard(v, now, pausedBefore = null) {
  surfaceRestoreUntil = now + 800
  surfaceRestoreVideo = v
  // 优先用 pointerdown 记下的点击前状态；没有（或已经过期）才退回读 v.paused
  const fresh = surfacePausedBeforeTap !== null && now - surfacePausedBeforeTapAt < 1000
  surfaceRestorePaused = pausedBefore !== null
    ? pausedBefore
    : (fresh ? surfacePausedBeforeTap : v.paused)
  muteVideoPlaybackHint()
  clearTimeout(surfaceRestoreTimer)
  surfaceRestoreTimer = setTimeout(() => {
    surfaceRestoreTimer = null
    // 用户明确切了播放 / 换了片会 disarm 并把 surfaceRestoreVideo 置空，
    // 那时不该再还原；抑制器命中过不算，兜底必须继续确认 play() 真的成功了
    if (surfaceRestoreVideo !== v) return
    if (!previewShow.value || getActiveVideo() !== v) return
    if (v.paused !== surfaceRestorePaused) restoreVideoPlayback(v, surfaceRestorePaused)
  }, 150)
}

/** 用户明确要切播放（点控制条按钮 / 按空格 / 遥控器 OK / 换片 / 片尾）：
 *  撤掉防护，让浏览器或按键真正生效。clearHints 用于需要立刻看到状态提示的路径 */
function disarmPlaybackGuard(clearHints = false) {
  surfaceRestoreUntil = 0
  surfaceRestoreVideo = null
  clearTimeout(surfaceRestoreTimer)
  surfaceRestoreTimer = null
  if (clearHints) {
    videoHintMutedUntil = 0
    videoStateMutedUntil = 0
  }
}

function handleSurfaceTap(v) {
  if (!v) return
  const now = Date.now()
  if (now - surfaceTapLastAt < 350) return
  surfaceTapLastAt = now
  armPlaybackGuard(v, now)
}

/** pointerdown 比浏览器切换播放更早：在这里记下「点击前是否暂停」并先把防护架好。
 *  只靠 click 不够——Chrome 在 click 的 target 阶段就切了播放，那时读到的状态
 *  已经是切过之后的 */
function onSurfacePointerDown(e) {
  if (!isVideoPreview()) return
  const v = getActiveVideo()
  if (!v) return
  // <video> 本体全屏时整块画面归原生控制条管，点一下就是切播放，不插手
  if (currentFullscreenElement() === v) return
  const t = e.target
  // 起点在自绘按钮上（× / 图片箭头）：交给按钮自己
  if (t && typeof t.closest === 'function' && t.closest('button')) return
  // 原生控制条那一条：上面按钮（播放、音量、全屏）的点击要真正生效
  if (inControlsClickArea(e.clientY, v)) return
  const now = Date.now()
  surfacePausedBeforeTap = v.paused
  surfacePausedBeforeTapAt = now
  armPlaybackGuard(v, now, v.paused)
}

/** 打开/关闭预览、换片、退出幻灯片时把点按状态整个归零 */
function resetSurfaceTap() {
  surfaceTapLastAt = 0
  surfacePausedBeforeTap = null
  surfacePausedBeforeTapAt = 0
  disarmPlaybackGuard()
}

/** 播放 / 暂停当前视频（空格 / TV OK）。这里直接给一次提示：
 *  事件是异步派发的，按下去要立刻有反馈；点控制条按钮那条路径由事件兜住 */
function toggleVideoPlay() {
  disarmPlaybackGuard()
  const v = getActiveVideo()
  if (!v) return
  if (v.paused) {
    const p = v.play()
    if (p && typeof p.catch === 'function') p.catch(() => {})
    previewPaused.value = false
    showHud('播放')
  } else {
    try { v.pause() } catch (e) { /* 忽略 */ }
    previewPaused.value = true
    showHud('已暂停')
  }
}

/** 记住「刚刚是不是我们提示过暂停」，避免自动播放一打开就弹一个「播放」 */
let videoPausedHintShown = false
/** 换片 / 打开预览时浏览器会顺带发 pause+play，这段时间内不弹提示，免得刷屏 */
let videoHintMutedUntil = 0
/** 状态更新只挡 seek 引发的那一对 pause→play 连击。窗口必须比提示窗口短：
 *  否则用户在这半秒里点原生控制条暂停，中间按钮与 TV 键位提示会一直不更新 */
let videoStateMutedUntil = 0

function muteVideoPlaybackHint() {
  const now = Date.now()
  videoHintMutedUntil = now + 500
  videoStateMutedUntil = now + 160
  videoPausedHintShown = false
}

function isPlaybackGuardActive(now, ev) {
  return now < surfaceRestoreUntil && !!ev && ev.target === surfaceRestoreVideo
}

/** <video> 的 play / pause 事件：暂停给提示，恢复播放只在「从暂停里点起来」时提示。
 *  自动播放、切片换源那种 pause→play 连击不该刷屏 */
function onVideoPlayback(paused, ev) {
  const now = Date.now()
  // 播到结尾同样会派发 pause，这不是浏览器顺手切的那次。解除防护与静音窗口，
  // 否则片尾会被强行重新播一遍，且「播放结束」提示与状态都被吞掉
  if (ev && ev.target && ev.target.ended) disarmPlaybackGuard(true)
  // 点画面：浏览器顺手切的那次播放状态一律撤销（只撤销一次）。
  // 播放中点会变成 pause，暂停中点会变成 play，两种都要还原
  if (isPlaybackGuardActive(now, ev)) {
    // 只关掉事件拦截（第二个事件不该再被拦），别 disarm：
    // 否则 150ms 兜底被取消，万一这次 play() 被自动播放策略拒绝就没人补救
    surfaceRestoreUntil = 0
    restoreVideoPlayback(ev.target, surfaceRestorePaused)
    return
  }
  // 两个窗口分开：状态只挡 160ms 的 seek 连击（不跳变），提示挡 500ms（不刷屏）。
  // 以前共用一个 500ms 窗口，用户在这半秒里点控制条暂停会完全丢状态
  if (now >= videoStateMutedUntil) previewPaused.value = paused
  if (now < videoHintMutedUntil) return
  // 播到结尾也会派发 pause：这时候说「已暂停」不对，而且紧接着的「播放」也不该弹
  const ended = !!(paused && ev && ev.target && ev.target.ended)
  if (paused) {
    videoPausedHintShown = !ended
    showHud(ended ? '播放结束' : '已暂停')
    return
  }
  if (videoPausedHintShown) {
    videoPausedHintShown = false
    showHud('播放')
  }
}

/** 纵向手势：按屏幕高度连续改音量（上滑增大），实时生效不需要等松手 */
function gestureVolume(dy) {
  if (!seekVideoEl) return
  const h = window.innerHeight || 1
  const r = applyVolume(seekVideoEl, seekBaseVolume - (dy / h) * VOL_FULL_SPAN)
  showVolumeHud(r.value, r.applied)
}

// ========= 原生视频全屏：WebView 收不到触摸，由客户端回传两个轴的比例 =========
// 位移→秒、位移→音量两套公式都只在下面定义一次，内联手势与全屏手势共用
let nativeGesture = null

function nativeGestureStart() {
  let v = getActiveVideo()
  // 部分 WebView 在 onShowCustomView 时会把 <video> 从原父节点摘走，
  // Vue 的 ref 可能已经失效，这时直接从 DOM 找回来
  if (!v && typeof document !== 'undefined' && typeof document.querySelector === 'function') {
    v = document.querySelector('.preview-box video') ||
        document.querySelector('.slide-root video') ||
        document.querySelector('video')
  }
  const dur = videoDuration(v)
  if (!v || !dur) { nativeGesture = null; return '' }
  let vol = 1
  try { if (typeof v.volume === 'number') vol = v.volume } catch (e) { /* 用默认值 */ }
  nativeGesture = { v, dur, baseTime: v.currentTime || 0, baseVolume: vol }
  return ''
}

/** commit=false 只预览秒级进度（横向）/实时改音量（纵向）；commit=true 才真正 seek */
function nativeGestureUpdate(dxRatio, dyRatio, commit) {
  // DOWN 的 start 是异步投递的，万一 MOVE 先到，这里自动补一次基准
  if (!nativeGesture) nativeGestureStart()
  const g = nativeGesture
  if (!g || !Number.isFinite(dxRatio) || !Number.isFinite(dyRatio)) return ''
  if (Math.abs(dxRatio) >= Math.abs(dyRatio)) {
    let delta = clampSeekTime(g.baseTime, ratioToSeconds(dxRatio, g.dur), g.dur) - g.baseTime
    if (commit) {
      const applied = seekVideoBy(delta, g.v, g.baseTime)
      if (applied === null) return ''
      delta = applied
    }
    showSeekHud(delta)
    return formatDelta(delta)
  }
  const r = applyVolume(g.v, g.baseVolume - dyRatio * VOL_FULL_SPAN)
  showVolumeHud(r.value, r.applied)
  return '音量 ' + Math.round(r.value * 100) + '%'
}

/** 兼容旧版 APK：只传横向比例时按「开始 → 立即提交」处理 */
function seekByRatioFromNative(ratio) {
  if (!Number.isFinite(ratio)) return ''
  nativeGestureStart()
  return nativeGestureUpdate(ratio, 0, true)
}

function onTouchStart(e) {
  resetSeekGesture()
  touchTracking = !isTvMode && e.touches.length === 1
  if (!touchTracking) { hideSeekHud(); return }
  touchStartX = e.touches[0].clientX
  touchStartY = e.touches[0].clientY
  // 起点在自绘按钮上（×、图片箭头、图片操作栏）：这次触摸交给按钮自己，
  // 不挂手势。否则手指抖几像素就锁成快进/音量手势，按钮反而点不动
  if (e.target && typeof e.target.closest === 'function' && e.target.closest('button')) return
  const v = getActiveVideo()
  const dur = videoDuration(v)
  // 视频元数据还没就绪、或是图片预览时，也要拦住纵向滑动，别把滚动传到底层页面
  if (!v || !dur) return
  // 只有视频底部那 36px 留给原生控制条：那一条里点能跳、拖也能拖，其余位置
  // （画面、画面外的黑边、底部文件名栏）全部接管手势
  if (inNativeBar(touchStartY, v)) {
    touchNativeBar = true
    return
  }
  seekVideoEl = v
  seekDuration = dur
  seekBaseTime = v.currentTime || 0
  try { seekBaseVolume = typeof v.volume === 'number' ? v.volume : 1 } catch (err) { seekBaseVolume = 1 }
}

function onTouchMove(e) {
  if (!touchTracking) return
  // 中途按下第二根手指（缩放等）直接作废本次手势，否则抬手时会误切图/误快进
  if (e.touches.length !== 1) { onTouchCancel(); return }
  // 手势进行中：屏蔽 seek 触发的 pause/play 连击，免得中间按钮闪现
  if (seekVideoEl) muteVideoPlaybackHint()
  // 预览层里拦掉默认行为（纵向滑动绝不能把滚动传到底层页面）；
  // 起点在控制条上的那次手势除外，否则进度条拖不动
  if (!touchNativeBar && e.cancelable) e.preventDefault()
  if (!seekVideoEl) return
  const dx = e.touches[0].clientX - touchStartX
  const dy = e.touches[0].clientY - touchStartY
  const ax = Math.abs(dx)
  const ay = Math.abs(dy)
  // 6px 即锁定方向，之后整次手势只走一个轴，斜滑不会在快进和音量之间来回跳
  if (!gestureAxis) {
    if (Math.max(ax, ay) < GESTURE_MIN_DIST) return
    gestureAxis = ax > ay * 1.1 ? 'h' : 'v'
  }
  seekActive = true
  if (gestureAxis === 'v') {
    gestureVolume(dy)
    return
  }
  const ratio = dx / (window.innerWidth || 1)
  showSeekHud(clampSeekTime(seekBaseTime, ratioToSeconds(ratio, seekDuration), seekDuration) - seekBaseTime)
}

function onTouchCancel() {
  touchTracking = false
  resetSeekGesture()
  hideSeekHud()
}

function onTouchEnd(e) {
  if (!touchTracking || e.changedTouches.length !== 1) { onTouchCancel(); return }
  touchTracking = false
  const dx = e.changedTouches[0].clientX - touchStartX
  const dy = e.changedTouches[0].clientY - touchStartY
  // resetSeekGesture 会清掉这两个，先留一份
  const startedInBar = touchNativeBar
  const startY = touchStartY
  if (startedInBar) disarmPlaybackGuard(true)
  if (seekActive) {
    // 阻止合成 click，否则 .preview-box 会把它当成「点空白退出预览」
    if (e.cancelable) e.preventDefault()
    suppressPreviewClickUntil = Date.now() + 400
    muteVideoPlaybackHint()   // 松手后再压 500ms，覆盖 seek 落点时补发的 pause/play
    if (gestureAxis === 'h' && Math.abs(dx) >= GESTURE_MIN_DIST) {
      const ratio = dx / (window.innerWidth || 1)
      const applied = seekVideoBy(ratioToSeconds(ratio, seekDuration), seekVideoEl, seekBaseTime)
      if (applied !== null) showSeekHud(applied)
      else hideSeekHud()
    } else if (gestureAxis === 'v') {
      // 音量在 move 中已实时生效，用抬手位置再确认一次即可
      gestureVolume(dy)
    } else {
      hideSeekHud()
    }
    resetSeekGesture()
    return
  }
  resetSeekGesture()
  // 点一下画面（没滑动、也不在原生控制条上）＝ 只显示控制条，不切播放。
  // 安卓 WebView 里点视频不一定派发 click，这里也走一遍，两路由
  // handleSurfaceTap 的 350ms 窗口去重
  if (!startedInBar && Math.abs(dx) <= GESTURE_MIN_DIST && Math.abs(dy) <= GESTURE_MIN_DIST) {
    const onButton = e.target && typeof e.target.closest === 'function' && e.target.closest('button')
    const tapVideo = previewShow.value && !slideShow.value ? getActiveVideo() : null
    if (tapVideo && onVideoSurface(touchStartX, startY, tapVideo)
        && inControlsClickArea(startY, tapVideo)) {
      // 点的是控制条按钮区（含播放/暂停键）：撤掉防护，交给浏览器
      disarmPlaybackGuard(true)
    } else if (!onButton && tapVideo && onVideoSurface(touchStartX, startY, tapVideo)
        && !inNativeBar(startY, tapVideo)
        && currentFullscreenElement() !== tapVideo) {
      handleSurfaceTap(tapVideo)
    }
  }
  // 图片：水平滑动切上一张/下一张。只在真的切了张时才拦合成 click
  // （原来没拦，切完可能顺带把预览关掉）。视频若时长未知、或手指落在
  // 底部控制条上，这里必须放行，否则拖不动原生进度条、点不亮控制条
  if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
    const isImage = slideShow.value
      ? currentSlide.value && currentSlide.value.type === 'image'
      : previewItem.value && previewItem.value.type === 'image'
    if (isImage) {
      if (e.cancelable) e.preventDefault()
      suppressPreviewClickUntil = Date.now() + 400
      if (slideShow.value) dx < 0 ? slideNext() : slidePrev()
      else dx < 0 ? nextMedia() : prevMedia()
    }
  }
}

function handleKeydown(e) {
  // 等索引时按 ESC 也能取消（手机端点按钮取消）
  if (randomSlideLoading.value && e.key === 'Escape') {
    e.preventDefault()
    randomSlideCancelled = true
    return
  }
  // 搜索框/下拉框里方向键要留给移动光标、切换选项
  const ae = typeof document !== 'undefined' ? document.activeElement : null
  if (ae && (['INPUT', 'SELECT', 'TEXTAREA'].includes(ae.tagName) || ae.isContentEditable)) return
  if (!slideShow.value && !previewShow.value) return

  const video = getActiveVideo()
  // 浏览器/手机端：只要当前渲染的是 <video>，方向键就归视频管（左右快进/后退、
  // 上下调音量）。这里不能再用时长判定，否则视频刚打开、元数据还没就绪时
  // 左右键会退回切图逻辑——箭头已隐藏、点空白也不退出，却能莫名切到下个媒体。
  // 时长无效时 seekVideoBy 会静默返回，不会误操作。TV 是遥控器，仍保持左右切媒体
  if (video && !isTvMode) {
    // 方向键只归视频管：焦点若落在原生控制条的按钮（尤其是全屏）上，
    // 浏览器默认会把方向键用来在控件之间挪焦点/高亮窗口，先把它清掉
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)
        && ae && ae !== document.body && typeof ae.blur === 'function') {
      try { ae.blur() } catch (err) { /* 忽略 */ }
    }
    // <video> 本体全屏时那行 HUD 画不出来（top layer 只渲染 video），只能靠听，
    // 用 10% 的步进；内联有百分比提示，保持 2% 的细腻手感
    const volStep = currentFullscreenElement() === video
      ? KEY_VOLUME_STEP_FULLSCREEN
      : KEY_VOLUME_STEP
    switch (e.key) {
      case 'ArrowLeft':  e.preventDefault(); keySeekVideo(-KEY_SEEK_STEP); break
      case 'ArrowRight': e.preventDefault(); keySeekVideo(KEY_SEEK_STEP); break
      case 'ArrowUp':    e.preventDefault(); adjustVideoVolume(volStep); break
      case 'ArrowDown':  e.preventDefault(); adjustVideoVolume(-volStep); break
      case ' ': case 'Spacebar':
        // 空格播放/暂停（网页里最顺手的那个键）。焦点在按钮上时让按钮自己响应，
        // 否则用户想按空格点「关闭」反而把视频切了
        if (ae && ae.tagName === 'BUTTON') break
        e.preventDefault()
        toggleVideoPlay()
        break
      case 'Escape': {
        e.preventDefault()
        // 幻灯片的全屏是幻灯片自己的一部分，Esc 依旧一次退出幻灯片（保持原样）
        if (slideShow.value) { exitSlide(); break }
        // 视频预览全屏时 Esc 只退全屏，预览留着；再按一次才关预览
        if (currentFullscreenElement()) {
          const exit = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen
          if (exit) {
            // 这次退全屏是我们按 Esc 主动做的，先清掉「上一次全屏元素」，
            // 免得随后的 fullscreenchange 又记一次退出时刻，把下一次 Esc 白吞掉
            lastFullscreenEl = null
            try { Promise.resolve(exit.call(document)).catch(() => {}) } catch (err) { /* 忽略 */ }
          }
          break
        }
        // 浏览器可能已经先替我们退了全屏（原生 <video> 全屏时 Esc 由浏览器自己处理），
        // 此时 fullscreenElement 已是 null。刚退过全屏的那一次 Esc 不再叠加关预览，
        // 否则一次 Esc 会同时退全屏 + 关预览，看着像按一下就全没了
        if (Date.now() - fullscreenExitAt < 600) { fullscreenExitAt = 0; break }
        closePreview()
        break
      }
    }
    return
  }

  if (slideShow.value) {
    if (e.key === 'Escape') {
      e.preventDefault()
      exitSlide()
      return
    }
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      slidePrev()
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      slideNext()
    }
    return
  }

  // TV 预览：遥控器只有方向 + OK，重新分工。
  // 视频：左右快进/后退 10 秒（复用手机那套步进与秒数 HUD）、上下切上一个/下一个、
  //       OK 播放/暂停。图片：方向键一律切张，保持原来的习惯。
  // 电视音量由电视遥控器 / HDMI-CEC 管，这里不抢音量键；
  // 幻灯片（slideShow）仍用左右翻页，不受这段影响。
  if (isTvMode && previewShow.value) {
    if (video) {
      switch (e.key) {
        case 'ArrowLeft':   e.preventDefault(); keySeekVideo(-KEY_SEEK_STEP); return
        case 'ArrowRight':  e.preventDefault(); keySeekVideo(KEY_SEEK_STEP); return
        case 'ArrowUp':     e.preventDefault(); prevMedia(); return
        case 'ArrowDown':   e.preventDefault(); nextMedia(); return
        case 'Enter': case ' ':
          e.preventDefault(); toggleVideoPlay(); return
        case 'Escape':      e.preventDefault(); closePreview(); return
      }
      return
    }
    switch (e.key) {
      case 'ArrowLeft': case 'ArrowUp':    e.preventDefault(); prevMedia(); return
      case 'ArrowRight': case 'ArrowDown': e.preventDefault(); nextMedia(); return
      case 'Escape':                       e.preventDefault(); closePreview(); return
    }
    return
  }

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

// ========= 遮罩层打开时锁住底层页面滚动 =========
// 预览、幻灯片和各种弹窗都是 position:fixed 覆盖层，鼠标滚轮默认仍会带动
// 底层 body 滚动。锁 body + html 的 overflow，弹窗内部自己的滚动容器不受影响。
const overlayOpen = computed(() =>
  previewShow.value || slideShow.value || settingShow.value ||
  changePwdModal.value || userManageModal.value || logModal.value || failedFilesModal.value
)

function lockPageScroll(locked) {
  // watch 带 immediate，初始化时就会跑一次；非浏览器环境直接跳过
  if (typeof document === 'undefined' || !document.body) return
  const val = locked ? 'hidden' : ''
  document.body.style.overflow = val
  document.documentElement.style.overflow = val
}

/** 预览/幻灯片层：内容没超高时滚轮一律拦下，避免某些 WebView 忽略 body 的
 *  overflow 时把滚动传到底层。遮罩自身内容超高（小屏长弹窗）则放行让它自己滚，
 *  此时 overscroll-behavior: contain 仍会切断滚动链。
 *  其他弹窗（日志列表等）刻意不加这个，保留它们自己的滚动。 */
function stopOverlayWheel(e) {
  const box = e.currentTarget
  if (box && box.scrollHeight > box.clientHeight) return
  if (e.cancelable) e.preventDefault()
}

watch(overlayOpen, lockPageScroll, { immediate: true })

// ========= TV 遥控器导航 =========
// 瀑布流卡片是绝对定位、行优先排布，浏览器默认的焦点顺序不可靠。
// 用 getBoundingClientRect 按「方向 + 距离」挑最近的一张卡片，
// 只有 TV 模式才注册，手机/浏览器的方向键行为完全不变
let tvNavHandler = null

function installTvNavigation() {
  if (!isTvMode) return
  // TV 客户端在页面加载完也会注入一套兜底导航；谁先执行谁装，避免重复监听
  if (window.__tvNavReady) return
  window.__tvNavReady = true
  document.documentElement.classList.add('tv-mode')
  tvNavHandler = (e) => {
    // 卡片和面包屑是 div/span + tabindex，浏览器默认 Enter 激活只对 button/a 生效，
    // 电视遥控器的 OK 键落上去不会触发 click，这里显式补上。
    // 但预览/幻灯片/弹窗打开时 OK 另有用途（视频播放/暂停），而且焦点还留在
    // 背后的卡片上——此时再点一次等于把预览重开一遍、还多压一条历史
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
      if (overlayOpen.value) return
      const hit = document.activeElement
      if (hit && hit.classList && (hit.classList.contains('media-card') ||
          hit.classList.contains('breadcrumb-item'))) {
        e.preventDefault()
        hit.click()
      }
      return
    }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return
    // 预览 / 幻灯片 / 弹窗里方向键另有用途（切图等），不接管
    if (previewShow.value || slideShow.value || settingShow.value ||
        userManageModal.value || logModal.value || changePwdModal.value ||
        failedFilesModal.value) return
    const cur = document.activeElement
    // 搜索框要用左右键移光标、下拉框要用方向键换选项，此时不能把焦点抢到卡片
    if (cur && (['INPUT', 'SELECT', 'TEXTAREA'].includes(cur.tagName) || cur.isContentEditable)) return
    const cards = Array.from(document.querySelectorAll('.media-card'))
    if (!cards.length) return
    // 顶栏按钮与面包屑：左右在这些控件之间切，下键进卡片区。
    // 没有这段，遥控器进了瀑布流就再也够不到「随机幻灯片」等顶栏功能
    const bars = Array.from(document.querySelectorAll('.header-actions button, .breadcrumb-item'))
    const bi = bars.indexOf(cur)
    if (bi >= 0) {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const nb = bars[bi + (e.key === 'ArrowRight' ? 1 : -1)]
        if (nb) { nb.focus({ preventScroll: true }); e.preventDefault() }
      } else if (e.key === 'ArrowDown') {
        cards[0].focus({ preventScroll: true })
        cards[0].scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        e.preventDefault()
      }
      return
    }
    const idx = cards.indexOf(cur)
    if (idx < 0) {
      cards[0].focus({ preventScroll: true })
      cards[0].scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      e.preventDefault()
      return
    }
    const r = cards[idx].getBoundingClientRect()
    const cx = r.left + r.width / 2
    const cy = r.top + r.height / 2
    let best = -1
    let bestScore = Infinity
    cards.forEach((c, i) => {
      if (i === idx) return
      const t = c.getBoundingClientRect()
      const dx = (t.left + t.width / 2) - cx
      const dy = (t.top + t.height / 2) - cy
      const horizontal = e.key === 'ArrowLeft' || e.key === 'ArrowRight'
      const secondary = horizontal ? Math.abs(dy) : Math.abs(dx)
      let primary = 0
      if (e.key === 'ArrowRight' && dx > 4) primary = dx
      else if (e.key === 'ArrowLeft' && dx < -4) primary = -dx
      else if (e.key === 'ArrowDown' && dy > 4) primary = dy
      else if (e.key === 'ArrowUp' && dy < -4) primary = -dy
      else return
      const score = primary + secondary * 2
      if (score < bestScore) { bestScore = score; best = i }
    })
    if (best >= 0) {
      cards[best].focus({ preventScroll: true })
      cards[best].scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
      e.preventDefault()
    } else if (e.key === 'ArrowUp' && bars.length) {
      // 第一排再往上把焦点交还顶栏按钮（而不是面包屑当前项），形成上下闭环
      const headBtns = document.querySelectorAll('.header-actions button')
      const target = headBtns.length ? headBtns[headBtns.length - 1] : bars[bars.length - 1]
      target.focus({ preventScroll: true })
      e.preventDefault()
    }
  }
  document.addEventListener('keydown', tvNavHandler, true)
}

function openTvSetup() {
  // TV 客户端在 shouldOverrideUrlLoading 里拦截这个自定义 scheme
  window.location.href = 'waterfall-tv://setup'
}

async function loadSlideSettings() {
  try {
    const res = await fetch(`${baseUrl}/api/settings`)
    if (!res.ok) { checkAuthResp(res); return }
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
    const res = await fetch(`${baseUrl}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slide_delay: slideDelay.value, slide_loop: slideLoop.value })
    })
    if (!res.ok) {
      // 403 用下面这条专属提示，别让 checkAuthResp 再弹一次通用提示
      if (res.status === 401) checkAuthResp(res)
      return alert(res.status === 403
        ? '幻灯片设置是全局的，只有管理员可以修改'
        : '❌ 保存失败，请稍后重试')
    }
    const ret = await res.json()
    if (ret.code !== 0) return alert("❌" + (ret.msg || "保存失败"))
  } catch (e) {
    console.error("保存幻灯片设置失败", e)
    return alert('❌ 保存失败，请稍后重试')
  }
  settingShow.value = false
}

// 从整个媒体库随机取一批图片
// onWaiting：索引还在预热时逐轮回调，用于把「正在建索引」显示给用户
// shouldAbort：每轮检查一次取消条件（登出、用户按 ESC 退出全屏），
// 否则首次建索引的 90 秒等待期间会一直打请求、回来后还弹出幻灯片
async function fetchRandomImages(onWaiting = null, waitMs = RANDOM_INDEX_WAIT_MS, shouldAbort = null) {
  const deadline = Date.now() + waitMs
  while (Date.now() < deadline) {
    if (shouldAbort && shouldAbort()) return null
    // 单次请求也设上限：换批只有 8 秒窗口，首启 90 秒内单次最多 12 秒。
    // 连接挂起时不设超时会让调用方的 finally 永远不执行、状态机死锁。
    const timeoutMs = Math.min(RANDOM_FETCH_TIMEOUT_MS, Math.max(1000, deadline - Date.now()))
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    let j
    try {
      const res = await fetch(`${baseUrl}/api/random-images?limit=${RANDOM_BATCH_SIZE}`,
        { signal: ctrl.signal })
      if (!res.ok) { checkAuthResp(res); return null }
      j = await res.json()
    } catch (e) {
      // 网络异常 / 主动 abort / 响应解析失败：直接判定本次取数失败，
      // 由调用方 finally 复位 loading 标志，不留悬挂状态
      return null
    } finally {
      clearTimeout(timer)
    }
    if (j.code === 2) {
      // 索引还没建好：不是故障，继续等，但不超过 waitMs
      onWaiting?.()
      const left = deadline - Date.now()
      if (left <= 0) break
      await new Promise(r => setTimeout(r, Math.min(RANDOM_INDEX_RETRY_MS, left)))
      continue
    }
    if (j.code !== 0) return null
    return j.list || []
  }
  return null
}

// 首页随机幻灯片：点击后播放第一批（不影响预览里的顺序播放）
async function startRandomSlide() {
  // 等索引期间再点一次按钮即取消（手机没有 ESC 键）
  if (randomSlideLoading.value) {
    randomSlideCancelled = true
    return
  }
  randomSlideLoading.value = true
  randomSlideCancelled = false
  slideSessionId++   // 作废旧会话里可能还在跑的换批请求
  randomSlideHint.value = ''
  let warming = false
  const startedAt = Date.now()
  // 全屏必须由用户手势触发。首次建索引可能要等几十秒，等完再请求全屏
  // 浏览器会因手势过期而拒绝，所以先进全屏再等数据。
  // 必须 await：否则 fetch 失败时 exitSlide 可能赶在全屏 Promise 落地之前，
  // 结果页面被留在全屏而幻灯片已经关了。
  await openRootFullscreen()
  // 记录是否真的进了全屏：等待期间用户按 ESC 退全屏，就等于取消了这次启动
  const hadFullscreen = slideFullscreenOwned
  try {
    const list = await fetchRandomImages(() => {
      warming = true
      // 用真实经过时间，别拿重试次数估算（每轮还有请求本身的耗时）
      randomSlideHint.value = `正在建立图片索引（${Math.round((Date.now() - startedAt) / 1000)}s）`
    }, RANDOM_INDEX_WAIT_MS,
      () => randomSlideCancelled || !isLogin.value || (hadFullscreen && !slideFullscreenOwned))
    // 登出 / 按 ESC 退全屏 / 点按钮取消：等待循环已提前结束，静默退出，
    // 别弹错误框也别弹幻灯片；exitSlide() 负责把已请求的全屏退掉
    if (randomSlideCancelled || !isLogin.value || (hadFullscreen && !slideFullscreenOwned)) {
      exitSlide()
      return
    }
    if (list === null) {
      exitSlide()
      return alert(warming
        ? '图片索引还在建立中：媒体库越大首次启动越慢，过一会儿再试即可'
        : '❌ 随机幻灯片加载失败')
    }
    if (!list.length) {
      exitSlide()
      return alert('媒体库里没有可用于幻灯片的图片')
    }
    slideList.value = list
    randomSlideMode.value = true
    slideIndex.value = 0
    slideShow.value = true
    runSlide()
  } catch (e) {
    console.error('加载随机图片失败', e)
    exitSlide()
    // 等待期间可能已经登出，别给登录页弹一个幻灯片错误框
    if (isLogin.value) alert('❌ 加载图片失败，请稍后重试')
  } finally {
    randomSlideLoading.value = false
    randomSlideHint.value = ''
  }
}

// 每轮播完重新从全库抽一批，避免一直循环同一批图片
async function reloadRandomBatch(session) {
  if (randomBatchLoading.value) return false
  randomBatchLoading.value = true
  try {
    // 换批也要能取消：退出 / 登出后请求不该在后台跑满 8 秒再写回列表
    const list = await fetchRandomImages(null, RANDOM_BATCH_WAIT_MS,
      () => session !== slideSessionId || !slideShow.value)
    // 会话已失效（退出、登出、另起一次幻灯片）：丢弃结果，别污染新界面
    if (session !== slideSessionId || !slideShow.value) return false
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
  // 另起一次顺序幻灯片，让上一次随机幻灯片的在途换批结果作废
  slideSessionId++
  slideList.value = previewMediaList.value.filter(i => i.type === 'image')
  randomSlideMode.value = false
  if (slideList.value.length === 0) return alert('没有图片可以幻灯片')
  const idx = slideList.value.findIndex(x => x.path === previewItem.value.path)
  slideIndex.value = Math.max(idx, 0)
  closePreview()
  openRootFullscreen()
  slideShow.value = true
  runSlide()
}

// 我们自己请求的全屏是否还在生效：用来区分「用户按 ESC 退出全屏」和
// 「幻灯片里的视频全屏被退出」——后者不该把整个幻灯片关掉
let slideFullscreenOwned = false

// 最近一次「从全屏退到非全屏」的时刻。浏览器处理 Esc 的顺序不确定：有时先退
// 全屏再派发 keydown，keydown 到达时 fullscreenElement 已经清空，光看它就分不清
// 「这次 Esc 已经用来退全屏」还是「用户想关预览」。这条时间窗专门兜这种情况：
// 刚退过全屏的那一次 Esc 不再叠加关预览，600ms 后自动失效
let fullscreenExitAt = 0
let lastFullscreenEl = null

async function openRootFullscreen() {
  const docEl = document.documentElement
  const req = docEl.requestFullscreen || docEl.webkitRequestFullscreen || docEl.msRequestFullscreen
  if (req) {
    try {
      await req.call(docEl)
      slideFullscreenOwned = true
    } catch (e) {
      // 浏览器要求全屏必须由用户手势触发：等索引太久会走到这里，只当降级处理
      slideFullscreenOwned = false
      console.warn("无法进入全屏，浏览器策略限制", e)
    }
  }
}

// 前缀 API 的老浏览器（旧 Safari / 旧 Edge）没有标准属性，必须一起判断
function currentFullscreenElement() {
  return document.fullscreenElement
    || document.webkitFullscreenElement
    || document.msFullscreenElement
    || null
}

function exitSlide() {
  // 作废所有在途的换批请求，避免退出后结果回来覆盖新界面
  slideSessionId++
  slideBatchReloading = false
  // 幻灯片里滑过快进后退出，别把秒数提示留在列表页；
  // 幻灯片里的视频被卸载时补发的 pause 也要压掉
  onTouchCancel()
  muteVideoPlaybackHint()
  resetSurfaceTap()
  clearTimeout(slideTimer.value)
  slideShow.value = false
  randomSlideMode.value = false
  const exit = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen
  // 已经不在全屏时（用户按 ESC 退出）再调 exitFullscreen 一定 reject，要兜住
  if (exit && currentFullscreenElement()) {
    try {
      Promise.resolve(exit.call(document)).catch(() => {})
    } catch (e) { /* 忽略：退出全屏失败不影响关闭幻灯片界面 */ }
  }
  slideFullscreenOwned = false
}

function runSlide() {
  clearTimeout(slideTimer.value)
  const list = slideList.value
  if (!list.length) {
    currentSlide.value = {}
    return
  }
  // 换批 await 期间 slideIndex 可能等于 list.length，钳住避免 currentSlide=undefined
  const i = Math.min(Math.max(slideIndex.value, 0), list.length - 1)
  slideIndex.value = i
  // 从视频切到下一条时，被换掉的 <video> 会补一个 pause；那不是用户按的暂停
  muteVideoPlaybackHint()
  currentSlide.value = list[i]
  // 换批还没回来时不再另起计时器，等 slideNext 的 await 恢复后统一计时
  if (slideBatchReloading) return
  slideTimer.value = setTimeout(() => {
    slideNext()
  }, clampSlideDelay(slideDelay.value) * 1000)
}

async function slideNext() {
  // 换批 await 期间忽略新的翻页，避免两个流程交错写 slideList / slideIndex
  if (slideBatchReloading) return
  const session = slideSessionId
  slideIndex.value++
  if (slideIndex.value >= slideList.value.length) {
    if (!slideLoop.value) {
      exitSlide()
      return
    }
    if (randomSlideMode.value) {
      slideBatchReloading = true
      let ok = false
      try {
        ok = await reloadRandomBatch(session)
      } finally {
        // 无条件复位：换批期间的并发翻页已被开头守卫挡掉，
        // 若按会话判断，用户中途退出（会话已递增）会让标志永久卡 true
        slideBatchReloading = false
      }
      if (session !== slideSessionId || !slideShow.value) return
      if (!ok) shuffleSlideList()
    }
    slideIndex.value = 0
  }
  if (session !== slideSessionId || !slideShow.value) return
  runSlide()
}
function slidePrev() {
  if (slideBatchReloading) return
  slideIndex.value--
  if (slideIndex.value < 0) {
    if (slideLoop.value) slideIndex.value = slideList.value.length - 1
    else slideIndex.value = 0
  }
  runSlide()
}

// 预览：除媒体本身和交互控件外，点击任意空白区域都退出
// 视频预览时点周围空白不退出：播放中误触不该打断；退出走 × / Esc / 返回键。
// 图片预览保持原来「点图片外区域退出」的行为不变
function isVideoPreview() {
  return !!(previewItem.value && previewItem.value.type !== 'image')
}

function onPreviewMaskClick() {
  // 和 onPreviewBoxClick 一样要有手势兜底：图片横滑切张后，
  // 合成 click 若落在遮罩上且 touchend 的 preventDefault 没拦住，不该误关预览
  if (Date.now() < suppressPreviewClickUntil) return
  if (isVideoPreview()) return
  closePreview()
}

function onPreviewBoxClick(e) {
  // 视频横滑结束后浏览器仍可能合成 click（touchend 的 preventDefault 不是绝对可靠），
  // 这段时间内忽略「点空白退出」，避免刚快进完预览就被关掉
  if (Date.now() < suppressPreviewClickUntil) return
  if (isVideoPreview()) {
    // 视频预览：点画面只显示控制条，绝不切播放。底部那一条是原生控制条，
    // 用户点上面的播放/暂停按钮时撤掉防护，让浏览器自己切。
    // <video> 本体全屏时整块画面都归原生控制条管（点一下是显示/隐藏控制条、
    // 双击才是全屏行为），这里也一并放行，不去架防护
    const t = e.target
    const v = getActiveVideo()
    if (t && t.tagName === 'VIDEO' && v) {
      if (inControlsClickArea(e.clientY, v) || currentFullscreenElement() === v) {
        disarmPlaybackGuard(true)
      } else {
        handleSurfaceTap(v)
      }
    }
    return
  }
  const t = e.target
  if (!t) return
  // 点图片/视频本体（含视频原生控制条）不退出
  if (t.tagName === 'IMG' || t.tagName === 'VIDEO') return
  // 箭头、旋转、关闭等按钮各走自己的逻辑，不额外退出
  if (typeof t.closest === 'function' && t.closest('button')) return
  closePreview()
}

function closePreview() {
  // 手势状态与 HUD 一起清掉：刚滑完快进就按 Esc/返回时，
  // 那行「+30 秒」会飘在已关闭的列表上等 1.5 秒才消失。
  // 视频被卸载时浏览器还会补一个 pause 事件，也要一并压掉
  onTouchCancel()
  muteVideoPlaybackHint()
  resetSurfaceTap()
  // 关预览前先退出全屏：全屏元素被 v-if 卸载后虽然浏览器也会收尾，
  // 但显式退比依赖实现细节稳
  if (currentFullscreenElement()) {
    const exit = document.exitFullscreen || document.webkitExitFullscreen
    if (exit) {
      try { Promise.resolve(exit.call(document)).catch(() => {}) } catch (e) { /* 忽略 */ }
    }
  }
  previewShow.value = false
  previewItem.value = null
  previewMediaList.value = []
  previewCurrentIndex.value = 0
  // 界面主动关闭时把预览占用的那条历史退掉；popstate 会负责清标志
  if (previewHistoryPushed) {
    window.history.back()
  }
}

function onPopState(e) {
  // 预览占着一条历史：这次 pop 只用于关闭预览，保持当前目录与 URL 不变
  if (previewHistoryPushed) {
    previewHistoryPushed = false
    if (previewShow.value) closePreview()
    return
  }
  // 幻灯片没有自己的历史记录：手机/电视的返回键（安卓 back 走 web.goBack）
  // 会落到目录级 popstate 上。这里先关幻灯片——电视遥控器没有 Esc，界面上那个
  // 「退出全屏」按钮也点不到，不处理就成了死胡同——再把界面与刚退到的
  // 那条目录历史对齐（同目录时不动列表，避免白白重载一次）
  if (slideShow.value) {
    exitSlide()
    const backDir = e.state?.dir ?? getDirFromUrl()
    if (backDir !== currentDir.value) loadMedia(backDir, false)
    return
  }
  // 前进到预览那条历史时不做无谓的目录重载（预览本身不重新打开）
  if (e.state?.preview) return
  const dir = e.state?.dir ?? getDirFromUrl()
  loadMedia(dir, false)
}

// ========== 登录登出 ==========
async function doLogin() {
  if (loginLockRemaining.value > 0) return
  loginErr.value = ''
  try {
    const res = await fetch(`${baseUrl}/api/login`, {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(loginForm.value)
    })
    const ret = await res.json()
    if (res.status === 429) {
      // 阶梯锁定：detail 是 {msg, retry_after}，按钮上给实时倒计时
      const d = (ret.detail && typeof ret.detail === 'object') ? ret.detail : {}
      startLoginLock(d.retry_after)
      loginErr.value = d.msg || '登录失败次数过多，请稍后再试'
      return
    }
    if (!res.ok || ret.code !==0) {
      loginErr.value = (typeof ret.detail === 'string' && ret.detail) || "账号或密码错误"
      return
    }
    stopLoginLock()
    await checkLoginStatus()
  } catch(err) {
    loginErr.value = "网络异常"
  }
}

// 登出 / 会话失效时统一复位。否则下一位用户登录后，上一位管理员的
// 弹窗、用户列表、执行日志还会以残留 ref 的形式显示出来（跨账号泄露）。
function resetUiState() {
  // 复用退出流程：停定时器、退全屏、关界面、递增会话令牌作废旧请求，
  // 不再重复实现一遍 exitFullscreen 的前缀判断
  exitSlide()
  stopLoginLock()
  onTouchCancel()  // 复用：清 touchTracking / seek 状态 / HUD
  suppressPreviewClickUntil = 0
  loginErr.value = ''
  slideBatchReloading = false
  slideList.value = []
  currentSlide.value = {}
  slideIndex.value = 0
  randomSlideLoading.value = false
  randomSlideHint.value = ''
  randomSlideCancelled = true

  previewShow.value = false
  previewItem.value = null
  previewMediaList.value = []
  previewCurrentIndex.value = 0
  previewHistoryPushed = false

  settingShow.value = false
  changePwdModal.value = false
  userManageModal.value = false
  logModal.value = false
  failedFilesModal.value = false
  showUserDrop.value = false
  umView.value = 'list'
  editUser.value = null
  adminUserList.value = []
  dirOptions.value = []
  guardList.value = []
  guardMsg.value = ''
  logList.value = []
  cacheStats.value = { total: 0, cached: 0, uncached: 0, failed: 0,
                       failed_files: [], failed_files_truncated: false, last_finish_time: null }

  mediaList.value = []
  breadcrumbList.value = []
  currentDir.value = ''
  pendingLoad = null
}

async function doLogout() {
  await fetch(`${baseUrl}/api/logout`, {method:"POST"})
  // 停掉轮询链并复位进度，否则快速切换账号时会把上一位管理员的任务
  // 结束提示弹给下一位用户，或让新会话永久卡在「缓存处理中」
  stopStatusPoll()
  cacheRunning.value = false
  cachePercent.value = 0
  cacheTaskOwnedByMe = false
  resetUiState()
  isLogin.value = false
  userInfo.value = {}
  loginForm.value = {username:'', password:''}
  loginErr.value = ''
}

async function checkLoginStatus() {
  try {
    const res = await fetch(`${baseUrl}/api/whoami`)
    if (res.ok) {
      const ret = await res.json()
      isLogin.value = true
      userInfo.value = ret
      loginForm.value = {username:'', password:''}
      loginErr.value = ''
      const urlDir = getDirFromUrl()
      await loadMedia(urlDir, !!urlDir)
      await loadSlideSettings()
      initCheckCacheTask()
    } else {
      resetUiState()
      isLogin.value = false
      userInfo.value = {}
    }
  } catch(e) {
    resetUiState()
    isLogin.value = false
    userInfo.value = {}
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
    if (!res.ok) { checkAuthResp(res); return }
    const j = await res.json()
    if (j.code === 0) {
      cacheStats.value = {
        total: j.total,
        cached: j.cached,
        uncached: j.uncached,
        failed: j.failed || 0,
        failed_files: j.failed_files || [],
        failed_files_truncated: !!j.failed_files_truncated,
        last_finish_time: j.last_finish_time
      }
    }
  } catch (e) {
    console.error("加载缓存统计失败", e)
  }
}
function toggleUserDrop(){
  showUserDrop.value = !showUserDrop.value
  // /api/cache-stats 只允许管理员访问，普通用户点开下拉不必打这个 403
  if (showUserDrop.value && userInfo.value.is_admin) {
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
    if (!res.ok) { checkAuthResp(res); return }
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
    if (!res.ok) {
      checkAuthResp(res)   // 401 切登录页、403 提示降权
      pwdMsg.value = json.detail || "修改失败"
      return
    }
    if(json.code ===0){
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
function formatGuardLeft(sec) {
  const s = Math.max(0, Math.ceil(Number(sec) || 0))
  if (s >= 3600) return '1 小时'
  if (s >= 60) return `${Math.ceil(s / 60)} 分钟`
  return `${s} 秒`
}

async function loadLoginGuard(quiet = false) {
  if (!quiet) guardMsg.value = ''
  try {
    const res = await fetch(`${baseUrl}/api/admin/login-guard`)
    if (!res.ok) { checkAuthResp(res); return false }
    const j = await res.json()
    if (j.code === 0) {
      guardList.value = j.list || []
      return true
    }
  } catch (e) { /* 下面统一给提示 */ }
  if (!quiet) guardMsg.value = '读取登录锁定状态失败'
  return false
}

async function unlockGuard(item) {
  // item 为 null 表示「全部解锁」；否则按记录类型精确解锁
  const body = item
    ? { scope: item.kind === 'ip' ? 'ip' : 'account',
        username: item.username || null, ip: item.ip }
    : { all: true }
  try {
    const res = await fetch(`${baseUrl}/api/admin/login-unlock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    if (!res.ok) { checkAuthResp(res); guardMsg.value = '解锁失败'; return }
    const j = await res.json()
    const msg = `已解除 ${j.removed || 0} 条记录`
    // 刷新失败要如实说出来，否则提示说「已解除」但列表还是旧的
    const refreshed = await loadLoginGuard(true)
    guardMsg.value = refreshed ? msg : `${msg}，但列表刷新失败，请点「刷新」`
  } catch (e) {
    guardMsg.value = '网络异常，解锁未完成'
  }
}

function unlockAllGuard() {
  if (!guardList.value.length) return
  if (!confirm('确认解除全部账号与来源 IP 的登录锁定？')) return
  unlockGuard(null)
}

async function openUserManageModal(){
  showUserDrop.value = false
  userManageModal.value = true
  umView.value = 'list'
  editUser.value = null
  adminMsg.value = ""
  guardMsg.value = ""
  umDelConfirm.value.show = false
  await reloadDirOptions()
  await reloadAdminUserList()
  await loadLoginGuard()
}
function closeUserManageModal(){
  userManageModal.value = false
}
async function reloadDirOptions(){
  try{
    const res = await fetch("/api/admin/dirs")
    if (!res.ok) { checkAuthResp(res); return }
    const json = await res.json()
    if(json.code===0){
      dirOptions.value = json.options
    }
  }catch(e){}
}
async function reloadAdminUserList(){
  try{
    const res = await fetch("/api/admin/users")
    if (!res.ok) { checkAuthResp(res); return }
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
    if (!res.ok) {
      // 400 里是具体的校验原因（用户名非法、新名已存在），401/403 才走鉴权复位
      if (res.status === 401 || res.status === 403) checkAuthResp(res)
      const j = await res.json().catch(() => ({}))
      adminMsg.value = j.detail || `修改失败（${res.status}）`
      return
    }
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
  // 密码只在「全空白」时当成不修改（编辑留空），绝不能 trim 后再提交：
  // 否则管理员设定 "pass " 会被悄悄存成 "pass"，用户按自己输的密码永远登录不上
  const pwd = umForm.value.password
  const body = {
    username: username,
    password: pwd.trim() === '' ? null : pwd,
    allow_dirs: umForm.value.allow_dirs,
    is_admin: umForm.value.is_admin
  }
  try{
    const res = await fetch("/api/admin/user-save",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)
    })
    if (!res.ok) {
      // 校验失败（用户名不合法 / 目录越界 / 密码超长 / 不许取消最后一个管理员）
      // 都是 400，原因在 detail 里。不显示出来的话，点「保存」就是毫无反应
      if (res.status === 401 || res.status === 403) checkAuthResp(res)
      const j = await res.json().catch(() => ({}))
      adminMsg.value = j.detail || `保存失败（${res.status}）`
      return
    }
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
    if (!res.ok) {
      // 列表视图没有 msg-tip，400/404 的原因（例如「至少保留一名管理员」）
      // 只能用 alert 才看得见，否则确认框一关就像什么都没发生
      if (res.status === 401 || res.status === 403) checkAuthResp(res)
      const j = await res.json().catch(() => ({}))
      umDelConfirm.value.show = false
      alert("❌" + (j.detail || `删除失败（${res.status}）`))
      return
    }
    const json = await res.json()
    if(json.code===0){
      await reloadAdminUserList()
    }else{
      umDelConfirm.value.show = false
      alert("❌" + (json.detail || json.msg || "删除失败"))
      return
    }
  }catch(e){
    alert("❌网络异常，删除未完成")
  }
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
  // APK 接管 HTML5 视频原生全屏时（onShowCustomView），文档全屏可能同时退出、
  // fullscreenElement 变成 null；此时别把正在播放的幻灯片误关掉。
  // 浏览器里没有这个变量，undefined 为假，行为不变
  if (window.__albumVideoFullscreen) return
  const el = currentFullscreenElement()
  // 记下「刚退出全屏」的时刻，供 Esc 分支判断这一次 Esc 是不是已经用来退全屏了。
  // 关预览 / 关幻灯片时也会退全屏，那不属于按 Esc 退全屏，不记（否则紧接着
  // 打开下一个视频按 Esc 会被白吞一次）
  if (lastFullscreenEl && !el && previewShow.value) fullscreenExitAt = Date.now()
  lastFullscreenEl = el
  // 进全屏后 Chrome 把焦点留在控制条的全屏按钮上，会画一圈白色焦点框。
  // 那个按钮在 closed shadow DOM 里，CSS 选不中，只能把焦点松开；
  // 键盘操作走 document 捕获，不依赖焦点
  if (el) {
    const focusEl = document.activeElement
    if (focusEl && focusEl !== document.body && typeof focusEl.blur === 'function') {
      try { focusEl.blur() } catch (err) { /* 忽略 */ }
    }
  }
  // 原生控制条上的全屏按钮，进的就是 <video> 本体全屏。这里必须接受它：
  // 曾经试过「趁文档还在全屏态把全屏元素换成 .preview-box」，但那等于在
  // fullscreenchange 回调里重新发一次 requestFullscreen，没有用户手势，
  // Chrome 直接 NotAllowedError，代码随后退回内联 —— 表现就是「点全屏、
  // 闪一下又回到内联」，按钮像坏了。所以这里不做任何换层，只记录状态。
  // 全屏时预览层里的提示、× 不渲染（top layer 只画 <video>），但手势监听
  // 挂在 .preview-box 上，事件仍沿 DOM 冒泡，快进/音量照旧可用。
  // 全屏切换后画面尺寸变了，右上角的关闭按钮要重新贴边（内联时可见）
  if (previewShow.value) updateCloseBtnPos()
  if (el === document.documentElement) {
    // 整个页面进了全屏，说明是我们（或用户）要的幻灯片全屏
    slideFullscreenOwned = true
    return
  }
  if (el) {
    // 幻灯片里的 video 抢了全屏：退出它不该把整个幻灯片一起关掉
    slideFullscreenOwned = false
    return
  }
  if (slideFullscreenOwned && slideShow.value) exitSlide()
  slideFullscreenOwned = false
}

onMounted(() => {
  // 原生视频全屏时 WebView 收不到触摸事件，客户端回调这组接口；
  // 第一个是旧版 APK 的兼容入口，后两个是新的双轴手势接口
  window.__albumVideoSeekRatio = seekByRatioFromNative
  window.__albumVideoGestureStart = nativeGestureStart
  window.__albumVideoGestureUpdate = nativeGestureUpdate
  installTvNavigation()
  checkLoginStatus()
  // 捕获阶段：浏览器原生视频控件在 Fullscreen API 下会吞掉方向键，
  // 挂在冒泡阶段的监听收不到，全屏时就无法快进/调音量
  document.addEventListener('keydown', handleKeydown, true)
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('popstate', onPopState)
  document.addEventListener("click", onClickOutsideDrop)

  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('webkitfullscreenchange', onFullscreenChange)
  document.addEventListener('visibilitychange', onVisibilityChange)
  listRefreshTimer = setInterval(silentRefreshList, LIST_REFRESH_MS)
})

onUnmounted(() => {
  disposed = true
  clearTimeout(seekHudTimer)
  clearTimeout(surfaceRestoreTimer)
  lockPageScroll(false)
  delete window.__albumVideoSeekRatio
  delete window.__albumVideoGestureStart
  delete window.__albumVideoGestureUpdate
  if (tvNavHandler) document.removeEventListener('keydown', tvNavHandler, true)
  if (isTvMode) document.documentElement.classList.remove('tv-mode')
  document.removeEventListener('keydown', handleKeydown, true)
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('popstate', onPopState)
  document.removeEventListener("click", onClickOutsideDrop)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  clearInterval(listRefreshTimer)
  stopStatusPoll()
  clearTimeout(slideTimer.value)
  clearTimeout(resizeTimer)
  clearTimeout(imageLoadTimer)
  clearTimeout(closeBtnPosTimer)
  stopLoginLock()
})
</script>

<style scoped>
/* ==========================================================
   UI 主题：A 克制精致
   仅调整视觉层，不改变任何交互逻辑与瀑布流布局计算
   设计变量与全局 reset 统一定义在 src/style.css（main.js 已引入），
   这里不再重复一份 scoped 的 * 规则
   ========================================================== */

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
  /* 旧浏览器不认 safe center 时回退到普通 center，不能只写新语法
     （整条声明被丢弃会退化成 stretch，把弹窗拉满全屏） */
  align-items: center;
  justify-content: center;
  /* 新浏览器：内容超高时退化为起始对齐，避免居中把上半截顶出可视区且滚不到 */
  align-items: safe center;
  justify-content: safe center;
  padding: 18px;
  /* 遮罩自己承担滚动，配合 contain 切断向底层页面的滚动链 */
  overflow-y: auto;
  overscroll-behavior: contain;
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
  /* 上下对称，内联与全屏（padding:0）的画面区中心一致 */
  padding: 14px 18px;
}
.preview-image-area img,
.preview-image-area video {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  animation: mediaIn .24s ease;
  /* 点画面或按方向键后浏览器会给媒体元素画一圈 focus outline（蓝框），
     看着像整块画面被选中。媒体元素不需要焦点框：键盘操作全走 document
     的捕获监听，不依赖焦点，去掉不影响任何快捷键 */
  outline: none;
}
.preview-image-area img:focus,
.preview-image-area img:focus-visible,
.preview-image-area video:focus,
.preview-image-area video:focus-visible { outline: none }
/* 视频预览：底部只留文件名那一行，把画面高度还给视频 */
.preview-footer.footer-compact { padding: 6px 16px 10px; gap: 0 }
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
.setting-hint { font-size: 12px; color: var(--muted); margin: 10px 0 0; line-height: 1.5 }
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
.failed-truncate-tip {
  font-size: 12px;
  line-height: 1.5;
  color: var(--muted);
  background: var(--surface-2, rgba(128, 128, 128, .08));
  border-radius: 7px;
  padding: 8px 10px;
  margin: 0 0 10px;
}
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

/* 登录锁定（用户管理弹窗内） */
.guard-section { margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border) }
.guard-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap }
.guard-title { font-size: 14px; font-weight: 500; color: var(--text) }
.guard-count {
  display: inline-block; min-width: 18px; padding: 1px 6px; margin-left: 4px;
  border-radius: 10px; background: var(--surface-3); color: var(--text-2);
  font-size: 11px; text-align: center;
}
.guard-actions { display: flex; gap: 8px }
.guard-hint { font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 8px }
.guard-empty { font-size: 12px; color: var(--muted); padding: 14px 0 }
.guard-table { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden }
.guard-row {
  display: grid;
  grid-template-columns: 1.4fr 1.3fr .5fr 1fr 70px;
  gap: 8px; padding: 9px 12px; align-items: center;
  border-bottom: 1px solid var(--border); font-size: 12px; color: var(--text-2);
}
.guard-row:last-child { border-bottom: none }
.guard-row-head { background: var(--surface-2); color: var(--muted); font-weight: 500 }
.guard-ip { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all }
.guard-locked { color: var(--danger) }

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
  overscroll-behavior: contain;
}
.slide-content {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 成对对称：上下取同一个最大值、左右取同一个最大值。
     iPhone 竖屏 top(≈47px) 与 bottom(≈34px) 不相等，若分别取会让内容盒
     中心偏移、图片不在视口正中；成对取值既避开安全区又保持精确居中。 */
  padding-top: max(12px, env(safe-area-inset-top), env(safe-area-inset-bottom));
  padding-bottom: max(12px, env(safe-area-inset-top), env(safe-area-inset-bottom));
  padding-left: max(12px, env(safe-area-inset-left), env(safe-area-inset-right));
  padding-right: max(12px, env(safe-area-inset-left), env(safe-area-inset-right));
}
/* 按当前视口等比铺满，不预设任何方向；横屏宽图、竖屏长图都能完整显示 */
.slide-content img,
.slide-content video {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
}
.slide-name {
  position: absolute;
  bottom: max(56px, calc(env(safe-area-inset-bottom) + 44px));
  left: 0;
  right: 0;
  padding: 0 16px;
  text-align: center;
  color: rgba(255, 255, 255, .86);
  font-size: 13px;
  text-shadow: 0 2px 8px rgba(0, 0, 0, .8);
}
.slide-exit-btn {
  position: absolute;
  top: max(16px, env(safe-area-inset-top));
  right: max(16px, env(safe-area-inset-right));
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
.slide-prev-btn { left: max(12px, env(safe-area-inset-left)) }
.slide-next-btn { right: max(12px, env(safe-area-inset-right)) }

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
  .guard-row { grid-template-columns: 1.2fr 1fr .4fr .8fr 58px; font-size: 11px; padding: 8px 6px; gap: 4px }
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
  /* 100dvh 跟随 iOS Safari 地址栏收放后的可视高度；旧浏览器不认这个单位，
     整条声明被丢弃时会自动回落到上一行的 100vh，不会丢样式 */
  .preview-box {
    width: 100vw;
    height: 100vh;
    height: 100dvh;
    max-width: 100vw;
    max-height: 100vh;
    max-height: 100dvh;
  }
  .close-btn { top: 8px; right: 8px; width: 30px; height: 30px; font-size: 18px }
  .log-time { min-width: 0 }
  .log-item { gap: 8px; padding: 9px 12px }
}
/* 手机/平板横屏时可用高度很窄：控件收紧、文件名贴底，把画面尽量让给媒体。
   pointer:coarse 限定触屏设备，桌面把窗口拖矮不会误命中；放在所有响应式
   规则之后，避免被 max-width:480px 里的 44px / left:8px 反向覆盖。
   四边都用长写，不能用 padding 简写把上面的安全区避让重置掉。 */
@media (orientation: landscape) and (max-height: 560px) and (pointer: coarse) {
  .slide-content {
    padding-top: max(6px, env(safe-area-inset-top), env(safe-area-inset-bottom));
    padding-bottom: max(6px, env(safe-area-inset-top), env(safe-area-inset-bottom));
    padding-left: max(6px, env(safe-area-inset-left), env(safe-area-inset-right));
    padding-right: max(6px, env(safe-area-inset-left), env(safe-area-inset-right));
  }
  .slide-prev-btn, .slide-next-btn { width: 38px; height: 38px; font-size: 22px }
  .slide-prev-btn { left: max(8px, env(safe-area-inset-left)) }
  .slide-next-btn { right: max(8px, env(safe-area-inset-right)) }
  .slide-exit-btn { padding: 6px 10px; font-size: 11px }
  .slide-name { bottom: max(6px, env(safe-area-inset-bottom)); font-size: 11px }
}
/* ---------- TV：遥控器 / 10-foot 界面 ----------
   html.tv-mode 由 TV 客户端判定 UA 后加上，浏览器与手机端不受影响 */
/* tv-mode 挂在 <html> 上；scoped 样式必须让最后一个选择器落在组件内元素，
   写成单独的 .tv-mode 会被编译成 .tv-mode[data-v-xxx] 而永远匹配不到 */
.tv-mode .app-container { font-size: 18px }
.tv-mode .header { padding: 18px 36px; gap: 16px }
.tv-mode .app-title { font-size: 26px }
.tv-mode .header-actions { gap: 14px }
.tv-mode .search-box input { width: 280px; font-size: 18px; padding: 12px 34px 12px 42px }
.tv-mode .search-icon { width: 18px; height: 18px; left: 14px }
.tv-mode .sort-select { font-size: 18px; padding: 12px 34px 12px 16px }
.tv-mode .btn { font-size: 18px; padding: 12px 22px }
.tv-mode .breadcrumb { font-size: 18px; padding: 18px 36px 6px }
.tv-mode .breadcrumb-item { padding: 8px 14px }
.tv-mode .waterfall-wrap { width: calc(100% - 72px); margin: 20px 36px 40px }
.tv-mode .card-name { font-size: 17px; padding: 12px 14px }
.tv-mode .card-badge { font-size: 14px; padding: 6px 12px }
.tv-mode .card-overlay-name { font-size: 16px }
.tv-mode .media-card:focus,
.tv-mode .media-card:focus-visible {
  outline: 4px solid var(--accent);
  outline-offset: 3px;
  z-index: 20;
  transform: translateY(-4px) scale(1.03);
  box-shadow: 0 0 0 6px var(--accent-soft), var(--shadow);
}
.tv-mode .btn:focus-visible,
.tv-mode .breadcrumb-item:focus-visible,
.tv-mode .sort-select:focus-visible,
.tv-mode .search-box input:focus-visible {
  outline: 4px solid var(--accent);
  outline-offset: 3px;
}
.tv-mode .preview-name { font-size: 18px }
/* 遥控器没有可点的按钮，键位只能写在画面上（十英尺外也要看得清） */
.tv-key-hint {
  margin: 0;
  font-size: 18px;
  line-height: 1.5;
  color: #AAB1BD;
  text-align: center;
}
.tv-mode .img-action-bar button { font-size: 17px; padding: 12px 20px }
.tv-mode .close-btn { width: 52px; height: 52px; font-size: 28px }
.tv-mode .arrow-btn { width: 64px; height: 64px; font-size: 32px }
.tv-mode .slide-prev-btn,
.tv-mode .slide-next-btn { width: 64px; height: 64px; font-size: 34px }
.tv-mode .slide-exit-btn { padding: 12px 22px; font-size: 17px }
.tv-mode .slide-name { font-size: 18px }
/* 十英尺界面：整体等比放大，仍是同一套样式 */
.tv-mode .seek-hud { padding: 14px 28px; border-radius: 12px; font-size: 28px }
.tv-setup-btn { border-color: var(--accent) }

/* ---------- 视频操作提示：快进/后退、音量、播放/暂停共用一行 ----------
   视觉与手机客户端原生全屏那行提示对齐：深色半透明底 + 白字，单行居中 */
.seek-hud {
  position: fixed;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  z-index: 99999;
  pointer-events: none;
  padding: 8px 16px;
  border-radius: 8px;
  text-align: center;
  background: rgba(14, 16, 20, .8);
  color: #fff;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.3;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important }
}
</style>
