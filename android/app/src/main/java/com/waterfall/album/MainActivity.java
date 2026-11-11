package com.waterfall.album;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 瀑布相册 —— NAS 媒体库的原生 WebView 客户端。
 *
 * 媒体文件、账号、缩略图都在 NAS 上，这里只负责：
 *   1. 首次启动记录服务器地址（仅存本机 SharedPreferences，不备份、不上传）
 *   2. 用同源 WebView 加载现有前端，因此不需要后端加 CORS
 *   3. 连接过程全部用原生状态页呈现：正在连接 / 失败原因 / 重试 / 改地址，
 *      不把浏览器的原始错误码、默认错误页或别的网站页面暴露给用户
 *   4. 全屏幻灯片跟随设备方向自适应：原生层不干预设备方向，
 *      manifest 里声明 configChanges，旋转时不重建 Activity，WebView 不重载、
 *      轮播不中断；横竖屏布局由网页端 CSS 媒体查询处理
 *   5. 返回键交给网页 history（与浏览器里「后退只关预览」一致）。
 *      幻灯片没有自己的历史记录，按返回键会走目录级 popstate，此时网页端
 *      会先退出幻灯片再对齐目录，所以返回键同样是「先关掉最上层的界面」
 *   6. HTML5 视频全屏由 onShowCustomView / onHideCustomView 接管：
 *      WebView 会把视频 View 交给宿主，挂到一个全屏黑色容器里。
 *      全程不调用 setRequestedOrientation，横竖屏跟随设备与系统方向设置；
 *      manifest 的 configChanges 保证旋转时不重建 Activity、播放不中断
 *   7. 视频手势：内联播放由网页端处理；进原生全屏后 WebView 收不到触摸事件，
 *      改由 dispatchTouchEvent 只观察不拦截，6px 即锁定横向（快进/后退）或
 *      纵向（音量）一个轴，把两轴比例回传给 __albumVideoGestureStart /
 *      __albumVideoGestureUpdate。位移→秒数、位移→音量公式只在网页端定义一份，
 *      全屏与内联手感一致；MOVE 阶段节流实时回显秒数，UP 才真正 seek
 *
 * 不申请存储/定位/通讯录权限，不加载任何第三方 SDK。
 */
public class MainActivity extends Activity {

    private static final String PREF_NAME = "waterfall_album";
    private static final String KEY_URL = "server_url";
    /**
     * 前端 index.html 里的标记，用来确认连上的确实是瀑布相册。
     * 第二条兼容旧版服务端（还没更新镜像时没有 meta，但 title 和 #app 在）：
     * 否则「先装新 APK、后更新镜像」会被误判成连错了地址。
     */
    private static final String APP_CHECK_JS =
            "(function(){"
            + "var m=document.querySelector('meta[name=waterfall-album]');"
            + "if(m && m.getAttribute('content')==='1') return '1';"
            + "var app=document.getElementById('app');"
            + "if(app && (document.title||'').indexOf('NAS媒体瀑布流')>=0) return '1';"
            + "return '';})()";

    private SharedPreferences prefs;
    private WebView web;
    private Button settingsBtn;
    private View statusPanel;
    private TextView statusIcon;
    private GradientDrawable statusIconBg;
    private ProgressBar statusProgress;
    private TextView statusTitle;
    private TextView statusDesc;
    private TextView statusUrl;
    private TextView statusTips;
    private Button retryBtn;
    private Button editBtn;
    private String currentUrl = "";
    private long lastBackPress = 0L;
    /** 本次加载已经失败：onPageFinished 别再把错误覆盖成「不是相册」 */
    private boolean loadFailed = false;
    /** 正在等待首次内容校验，避免页面内跳转也去查标记 */
    private boolean verifying = false;
    /**
     * 每次 loadServer 递增。evaluateJavascript 是异步的，用户中途改地址时
     * 旧回调若只靠 loadFailed/verifying 判断，会读到新加载重置后的值，
     * 用旧页面的结果把状态页关掉（或误报错误），把网页错误页重新露出来。
     */
    private int loadSeq = 0;

    /** HTML5 <video> 原生全屏：WebView 把视频 View 交给宿主后的挂载点 */
    private FrameLayout rootLayout;
    private FrameLayout fullscreenContainer;
    private View customVideoView;
    private WebChromeClient.CustomViewCallback customViewCallback;
    private int savedSystemUiVisibility = 0;

    /** 原生视频全屏下的横滑快进/后退：WebView 收不到触摸，只能由 Activity 观察 */
    private TextView fullscreenHud;
    private float seekDownX = 0f;
    private float seekDownY = 0f;
    private boolean seekTracking = false;
    /** 0 未定 / 1 横向快进后退 / 2 纵向音量，一次手势只锁一个轴 */
    private int seekAxis = 0;
    private long lastGesturePreviewAt = 0L;
    /** 作废上一次全屏遗留的 HUD 定时回调，别让它把新一次全屏的提示提前隐藏 */
    private int hudSeq = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        buildUi();

        String saved = prefs.getString(KEY_URL, "");
        if (saved == null || saved.length() == 0) {
            showServerDialog(true);
        } else {
            loadServer(saved);
        }
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        rootLayout = root;
        root.setBackgroundColor(Color.parseColor("#0E1014"));

        web = new WebView(this);
        configureWebView(web);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        // 不透明状态页盖在 WebView 上：连接中 / 出错时用户只看到原生界面，
        // 不会露出浏览器的默认错误页。WebView 保持 VISIBLE（不设 GONE），
        // 这样页面里的 JS 仍能正常执行，内容校验才能拿到标记。
        statusPanel = buildStatusPanel();
        statusPanel.setVisibility(View.GONE);
        root.addView(statusPanel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        // 半透明小按钮：换 NAS / 换端口时随时能改地址，平时几乎不挡内容
        settingsBtn = new Button(this);
        settingsBtn.setText("设置");
        settingsBtn.setTextSize(11f);
        settingsBtn.setTextColor(Color.parseColor("#DDE9ECF1"));
        settingsBtn.setBackgroundColor(Color.parseColor("#66232B36"));
        settingsBtn.setAlpha(0.55f);
        settingsBtn.setPadding(0, 0, 0, 0);
        FrameLayout.LayoutParams btnLp = new FrameLayout.LayoutParams(dp(46), dp(46));
        btnLp.gravity = Gravity.BOTTOM | Gravity.END;
        btnLp.rightMargin = dp(12);
        btnLp.bottomMargin = dp(16);
        settingsBtn.setLayoutParams(btnLp);
        settingsBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showServerDialog(false);
            }
        });
        root.addView(settingsBtn);

        setContentView(root);
    }

    private void configureWebView(WebView w) {
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        // 页面来自网络，不需要本地文件/ContentProvider 访问，收紧攻击面
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        // 幻灯片里的视频需要自动播放（前端已静音）
        s.setMediaPlaybackRequiresUserGesture(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
            CookieManager.getInstance().setAcceptThirdPartyCookies(w, false);
        }
        s.setUserAgentString(s.getUserAgentString() + " WaterfallAlbum/1.0");

        w.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (!request.isForMainFrame() || isStaleRequest(request)) return;
                CharSequence raw = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                        ? error.getDescription() : null;
                // loadUrl 打断上一次加载会报 ERR_ABORTED，那不是故障，
                // 更不能让它把刚发起的新地址状态页盖成错误
                if (String.valueOf(raw).toLowerCase().contains("err_aborted")) return;
                showError("连不上相册", friendlyNetworkError(raw));
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse response) {
                if (!request.isForMainFrame() || isStaleRequest(request)) return;
                int code = response.getStatusCode();
                if (code < 400) return;
                showError("服务没能正常响应", friendlyHttpError(code));
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler,
                                           SslError error) {
                // 默认行为是静默取消加载，WebView 会露出系统错误页；这里给出人话提示。
                // 先弹提示再 cancel：cancel 可能同步触发 onReceivedError，
                // showError 的「只保留第一条」守卫会挡住那次覆盖
                showError("HTTPS 证书不受信任",
                        "这个地址用了自签名证书。局域网里建议直接填 http:// 地址，"
                        + "或把正式证书装到手机上。");
                handler.cancel();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (loadFailed || !verifying) return;
                if (url == null || url.startsWith("about:")) return;
                final int seq = loadSeq;
                // 端口填错连到 NAS 管理页时，HTTP 是 200、页面也能打开，
                // 只有校验页面标记才能发现「这不是相册」
                view.evaluateJavascript(APP_CHECK_JS, new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if (seq != loadSeq) return;   // 期间换了地址，丢弃旧结果
                        if (loadFailed || !verifying) return;
                        String marker = value == null ? "" : value.replace("\"", "").trim();
                        if ("1".equals(marker)) {
                            showContent();
                        } else {
                            showError("这个地址不是瀑布相册",
                                    "页面能打开，但内容不对。最常见是漏写了 :8000 端口，"
                                    + "结果连到了 NAS 的管理页面或别的网站。");
                        }
                    }
                });
            }
        });

        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                // 相册用不到摄像头/麦克风，一律拒绝，不弹系统权限框
                request.deny();
            }

            @Override
            public void onShowCustomView(View videoView,
                                         WebChromeClient.CustomViewCallback callback) {
                enterVideoFullscreen(videoView, callback);
            }

            @Override
            public void onShowCustomView(View videoView, int requestedOrientation,
                                         WebChromeClient.CustomViewCallback callback) {
                // 页面常常在这里请求横屏，故意忽略：方向完全跟随设备/系统设置，
                // 不调用 setRequestedOrientation，横屏竖屏都能全屏播放
                enterVideoFullscreen(videoView, callback);
            }

            @Override
            public void onHideCustomView() {
                exitVideoFullscreen();
            }
        });
    }

    /**
     * 把 WebView 交出来的视频 View 挂成全屏。容器是 MATCH_PARENT 的黑色层，
     * 旋转时系统自动重新测量，不需要重建 Activity 也不需要手动改方向。
     * 不隐藏 WebView 本身，避免打断仍在进行的媒体播放。
     */
    private void enterVideoFullscreen(View videoView,
                                      WebChromeClient.CustomViewCallback callback) {
        if (customVideoView != null || videoView == null || rootLayout == null) {
            if (callback != null) callback.onCustomViewHidden();
            return;
        }
        customVideoView = videoView;
        customViewCallback = callback;

        fullscreenContainer = new FrameLayout(this);
        fullscreenContainer.setBackgroundColor(Color.BLACK);
        // 部分厂商的 WebView 交出来的视频 View 还挂在原父容器上，
        // 直接 addView 会抛 IllegalStateException，必须先摘干净
        if (videoView.getParent() instanceof ViewGroup) {
            ((ViewGroup) videoView.getParent()).removeView(videoView);
        }
        // 拦住触摸，别让全屏容器空白处穿透到下面的网页
        fullscreenContainer.setClickable(true);
        fullscreenContainer.addView(videoView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER));
        rootLayout.addView(fullscreenContainer, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        // 快进/后退提示叠在视频之上：后 addView 的 View 在 z 序最上层。
        // 文案、配色、圆角、字号都跟网页端那行提示对齐，全屏与内联看起来是一个东西
        fullscreenHud = new TextView(this);
        fullscreenHud.setTextColor(Color.WHITE);
        fullscreenHud.setTextSize(15f);
        fullscreenHud.setGravity(Gravity.CENTER);
        GradientDrawable hudBg = new GradientDrawable();
        hudBg.setCornerRadius(dp(8));
        hudBg.setColor(Color.parseColor("#CC0E1014"));
        fullscreenHud.setBackground(hudBg);
        fullscreenHud.setPadding(dp(16), dp(8), dp(16), dp(8));
        fullscreenHud.setVisibility(View.GONE);
        fullscreenContainer.addView(fullscreenHud, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        hideSystemBars();
        setVideoFullscreenFlag(true);
    }

    private void exitVideoFullscreen() {
        if (customVideoView == null) return;
        setVideoFullscreenFlag(false);
        restoreSystemBars();
        if (fullscreenContainer != null) {
            fullscreenContainer.removeView(customVideoView);
            rootLayout.removeView(fullscreenContainer);
            fullscreenContainer = null;
        }
        fullscreenHud = null;
        seekTracking = false;
        seekAxis = 0;
        hudSeq++;
        WebChromeClient.CustomViewCallback cb = customViewCallback;
        customVideoView = null;
        customViewCallback = null;
        if (cb != null) cb.onCustomViewHidden();
    }

    /**
     * 只观察、不拦截：事件仍完整交给 super 分发，原生视频控制条和暂停/播放
     * 都不受影响。全屏时把横/纵两轴比例回传给网页，由网页 seek 与调音量。
     */
    @Override
    public boolean dispatchTouchEvent(MotionEvent ev) {
        if (customVideoView != null) trackFullscreenSeek(ev);
        return super.dispatchTouchEvent(ev);
    }

    private void trackFullscreenSeek(MotionEvent ev) {
        // HUD 没建好也要能滑：只是不显示回显文字，seek/音量照常生效
        if (fullscreenContainer == null || web == null) return;
        int action = ev.getActionMasked();
        int w = fullscreenContainer.getWidth();
        int h = fullscreenContainer.getHeight();
        if (action == MotionEvent.ACTION_DOWN) {
            // 只把最底下 10% 留给原生控制条的进度条，其余位置都能手势
            seekTracking = ev.getPointerCount() == 1 && ev.getY() < h * 0.90f;
            if (!seekTracking) return;
            seekDownX = ev.getX();
            seekDownY = ev.getY();
            seekAxis = 0;
            lastGesturePreviewAt = 0L;
            // 让网页记下按下时的时间与音量基准，后续只回传两轴比例
            web.evaluateJavascript(
                    "window.__albumVideoGestureStart && window.__albumVideoGestureStart()", null);
        } else if (action == MotionEvent.ACTION_MOVE) {
            if (!seekTracking) return;
            if (ev.getPointerCount() != 1) { cancelFullscreenSeek(); return; }
            float dx = ev.getX() - seekDownX;
            float dy = ev.getY() - seekDownY;
            float ax = Math.abs(dx);
            float ay = Math.abs(dy);
            // 6px 即锁定方向，斜滑不会在快进和音量之间来回跳
            if (seekAxis == 0) {
                if (Math.max(ax, ay) < 6) return;
                seekAxis = ax > ay * 1.1f ? 1 : 2;
            }
            long now = System.currentTimeMillis();
            if (now - lastGesturePreviewAt < 60) return;   // 节流，别每帧调一次 JS
            lastGesturePreviewAt = now;
            callGestureJs(seekAxis == 1 && w > 0 ? dx / w : 0f,
                    seekAxis == 2 && h > 0 ? dy / h : 0f, false);
        } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            if (!seekTracking) return;
            // 用抬手时的最终坐标，不能用中途某次 MOVE 的 x：滑出去又滑回来不该快进
            float dx = ev.getX() - seekDownX;
            float dy = ev.getY() - seekDownY;
            // 与轴锁定阈值保持一致（6px），别让小幅滑动白做一次
            boolean valid = action == MotionEvent.ACTION_UP && seekAxis != 0
                    && Math.max(Math.abs(dx), Math.abs(dy)) > 6;
            seekTracking = false;
            if (!valid) { hideFullscreenHud(); return; }
            callGestureJs(seekAxis == 1 && w > 0 ? dx / w : 0f,
                    seekAxis == 2 && h > 0 ? dy / h : 0f, true);
        }
    }

    /** 横向比例给快进、纵向比例给音量；公式只在前端定义一份 */
    private void callGestureJs(float xr, float yr, boolean commit) {
        web.evaluateJavascript(
                "window.__albumVideoGestureUpdate && window.__albumVideoGestureUpdate("
                        + xr + "," + yr + "," + (commit ? "true" : "false") + ")",
                new ValueCallback<String>() {
                    @Override public void onReceiveValue(String value) {
                        applyFullscreenHudText(value, commit);
                    }
                });
    }

    /** MOVE 阶段实时更新秒数/音量，UP 阶段显示最终结果并延时收起 */
    private void applyFullscreenHudText(String value, boolean commit) {
        String txt = value == null ? "" : value.trim();
        if (txt.length() >= 2 && txt.startsWith("\"") && txt.endsWith("\"")) {
            txt = txt.substring(1, txt.length() - 1).replace("\\\"", "\"");
        }
        if (txt.length() == 0 || "null".equals(txt) || fullscreenHud == null) {
            if (commit) hideFullscreenHud();
            return;
        }
        fullscreenHud.setText(txt);
        fullscreenHud.setVisibility(View.VISIBLE);
        if (commit) {
            final int seq = ++hudSeq;
            fullscreenHud.postDelayed(new Runnable() {
                @Override public void run() {
                    if (seq == hudSeq) hideFullscreenHud();
                }
            }, 1200);
        }
    }

    private void hideFullscreenHud() {
        if (fullscreenHud != null) fullscreenHud.setVisibility(View.GONE);
    }

    private void cancelFullscreenSeek() {
        seekTracking = false;
        seekAxis = 0;
        hideFullscreenHud();
    }

    /** 告诉网页「现在是原生视频全屏」，避免全屏事件把幻灯片误关掉。 */
    private void setVideoFullscreenFlag(boolean on) {
        if (web == null) return;
        web.evaluateJavascript(
                "window.__albumVideoFullscreen=" + (on ? "true" : "false") + ";", null);
    }

    private void hideSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                // 只做 hide/show，不改 systemBarsBehavior：
                // 行为标志是全局的，退出全屏后残留会改变整个 App 的手势
                c.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
            }
        } else {
            View decor = getWindow().getDecorView();
            savedSystemUiVisibility = decor.getSystemUiVisibility();
            decor.setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
    }

    private void restoreSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                c.show(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(savedSystemUiVisibility);
        }
    }

    /**
     * 判断这个请求是否来自旧地址。loadUrl 切换地址后，上一次加载的错误回调
     * 仍可能延迟到达，绝不能让它把新地址的状态页盖成错误。
     */
    private boolean isStaleRequest(WebResourceRequest request) {
        if (request == null || request.getUrl() == null) return false;
        Uri req = request.getUrl();
        Uri cur = Uri.parse(currentUrl);
        String reqHost = req.getHost();
        String curHost = cur.getHost();
        if (reqHost == null || curHost == null) return false;
        return !reqHost.equalsIgnoreCase(curHost) || req.getPort() != cur.getPort();
    }

    /** 把浏览器底层错误翻译成中文人话，绝不把原始错误码摆给用户看。 */
    private String friendlyNetworkError(CharSequence description) {
        String d = String.valueOf(description == null ? "" : description).toLowerCase();
        if (d.contains("err_connection_refused")) {
            return "这个端口上没有人应答。通常是端口写错，或者相册服务没启动。";
        }
        if (d.contains("err_name_not_resolved") || d.contains("unknown_host")) {
            return "找不到这个地址，检查一下 IP 或域名有没有写错。";
        }
        if (d.contains("timed_out") || d.contains("timeout")) {
            return "连接超时。手机和 NAS 可能不在同一个网络，或者 NAS 正忙。";
        }
        if (d.contains("internet_disconnected") || d.contains("network_changed")) {
            return "手机当前没连上网络，连上 Wi-Fi 后再试。";
        }
        if (d.contains("address_unreachable") || d.contains("access_denied")) {
            return "这个地址不可达，确认手机和 NAS 在同一个网段。";
        }
        if (d.contains("connection_reset") || d.contains("connection_closed")) {
            return "连接被服务断开了，稍后重试一次。";
        }
        if (d.contains("cleartext_not_permitted")) {
            return "系统不允许明文 HTTP 访问，检查地址是否写成了 http://。";
        }
        if (d.contains("ssl") || d.contains("cert")) {
            return "HTTPS 证书有问题，局域网里建议改用 http:// 地址。";
        }
        return "连接失败，请检查地址、端口和服务是否在运行。";
    }

    private String friendlyHttpError(int code) {
        if (code == 404) {
            return "这个地址能连上，但没有找到相册页面。多半是端口填成了别的服务的端口。";
        }
        if (code == 401 || code == 403) {
            return "服务拒绝了这次访问，确认地址和端口是不是相册服务。";
        }
        if (code >= 500) {
            return "服务在线但暂时不可用（HTTP " + code + "），稍后再试。";
        }
        return "服务返回了 HTTP " + code + "，确认地址是不是相册服务。";
    }

    private Button styledButton(String text, boolean primary) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextSize(13f);
        b.setAllCaps(false);
        b.setPadding(dp(18), dp(6), dp(18), dp(6));
        if (primary) {
            b.setTextColor(Color.WHITE);
            GradientDrawable bg = new GradientDrawable();
            bg.setCornerRadius(dp(9));
            bg.setColor(Color.parseColor("#5B82F7"));
            b.setBackground(bg);
        } else {
            b.setTextColor(Color.parseColor("#AAB1BD"));
            b.setBackgroundColor(Color.TRANSPARENT);
        }
        return b;
    }

    private View buildStatusPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setBackgroundColor(Color.parseColor("#0E1014"));
        panel.setPadding(dp(30), dp(24), dp(30), dp(24));
        // 拦住点击，别让手指透过状态页点到下面那个网页
        panel.setClickable(true);

        FrameLayout iconBox = new FrameLayout(this);
        statusIconBg = new GradientDrawable();
        statusIconBg.setShape(GradientDrawable.OVAL);
        statusIconBg.setColor(Color.parseColor("#F26363"));
        statusIcon = new TextView(this);
        statusIcon.setText("!");
        statusIcon.setTextColor(Color.WHITE);
        statusIcon.setTextSize(22f);
        statusIcon.setGravity(Gravity.CENTER);
        statusIcon.setBackground(statusIconBg);
        iconBox.addView(statusIcon, new FrameLayout.LayoutParams(dp(52), dp(52)));
        statusProgress = new ProgressBar(this);
        statusProgress.setIndeterminate(true);
        iconBox.addView(statusProgress,
                new FrameLayout.LayoutParams(dp(30), dp(30), Gravity.CENTER));
        panel.addView(iconBox, new LinearLayout.LayoutParams(dp(52), dp(52)));

        statusTitle = new TextView(this);
        statusTitle.setTextColor(Color.parseColor("#E9ECF1"));
        statusTitle.setTextSize(19f);
        statusTitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        titleLp.setMargins(0, dp(20), 0, 0);
        panel.addView(statusTitle, titleLp);

        statusDesc = new TextView(this);
        statusDesc.setTextColor(Color.parseColor("#AAB1BD"));
        statusDesc.setTextSize(14f);
        statusDesc.setGravity(Gravity.CENTER);
        statusDesc.setLineSpacing(dp(4), 1f);
        LinearLayout.LayoutParams descLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        descLp.setMargins(0, dp(12), 0, 0);
        panel.addView(statusDesc, descLp);

        statusUrl = new TextView(this);
        statusUrl.setTextColor(Color.parseColor("#7B8492"));
        statusUrl.setTextSize(12f);
        statusUrl.setGravity(Gravity.CENTER);
        statusUrl.setSingleLine(true);
        statusUrl.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        LinearLayout.LayoutParams urlLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        urlLp.setMargins(0, dp(10), 0, 0);
        panel.addView(statusUrl, urlLp);

        statusTips = new TextView(this);
        statusTips.setTextColor(Color.parseColor("#7B8492"));
        statusTips.setTextSize(12.5f);
        statusTips.setLineSpacing(dp(4), 1f);
        statusTips.setText("可以试试：\n"
                + "• 手机和 NAS 连的是同一个 Wi-Fi\n"
                + "• 地址写成 http://192.168.1.10:8000，别漏端口\n"
                + "• 先用电脑浏览器打开这个地址，确认能看到相册");
        LinearLayout.LayoutParams tipsLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        tipsLp.setMargins(0, dp(20), 0, 0);
        panel.addView(statusTips, tipsLp);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams rowLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rowLp.setMargins(0, dp(26), 0, 0);

        retryBtn = styledButton("重试", true);
        retryBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (currentUrl.length() > 0) loadServer(currentUrl);
                else showServerDialog(true);
            }
        });
        editBtn = styledButton("修改服务器地址", false);
        editBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showServerDialog(false);
            }
        });
        LinearLayout.LayoutParams btnLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        btnLp.setMargins(dp(6), 0, dp(6), 0);
        row.addView(retryBtn, btnLp);
        row.addView(editBtn, btnLp);
        panel.addView(row, rowLp);
        return panel;
    }

    private void showLoading(String url) {
        loadFailed = false;
        verifying = true;
        statusIcon.setVisibility(View.GONE);
        statusProgress.setVisibility(View.VISIBLE);
        statusTitle.setText("正在连接相册");
        statusDesc.setText("正在打开服务器地址…");
        statusUrl.setText(url);
        statusTips.setVisibility(View.GONE);
        retryBtn.setVisibility(View.GONE);
        editBtn.setVisibility(View.GONE);
        statusPanel.setVisibility(View.VISIBLE);
        settingsBtn.setVisibility(View.GONE);
    }

    private void showError(String title, String desc) {
        // 一次加载可能连着来几个错误回调（网络错误 + HTTP 错误 + SSL 错误），
        // 只保留第一条，避免提示被后到的通用文案覆盖
        if (loadFailed) return;
        loadFailed = true;
        verifying = false;
        web.stopLoading();
        statusProgress.setVisibility(View.GONE);
        statusIcon.setVisibility(View.VISIBLE);
        statusTitle.setText(title);
        statusDesc.setText(desc);
        statusUrl.setText(currentUrl);
        statusTips.setVisibility(View.VISIBLE);
        retryBtn.setVisibility(View.VISIBLE);
        editBtn.setVisibility(View.VISIBLE);
        statusPanel.setVisibility(View.VISIBLE);
        settingsBtn.setVisibility(View.GONE);
    }

    private void showContent() {
        verifying = false;
        loadFailed = false;
        statusPanel.setVisibility(View.GONE);
        settingsBtn.setVisibility(View.VISIBLE);
    }

    /**
     * 允许直接填 192.168.1.10:8000；自动补 http://、丢掉误粘贴的路径和空格、
     * 校验端口范围。粘了整条链接（http://ip:8000/photos）也只取根地址。
     */
    private String normalizeUrl(String raw) {
        String s = raw == null ? "" : raw.trim().replaceAll("\\s+", "");
        if (s.length() == 0) return "";
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://" + s;
        }
        Uri uri;
        try {
            uri = Uri.parse(s);
        } catch (Exception e) {
            return "";
        }
        String host = uri.getHost();
        String scheme = uri.getScheme();
        if (host == null || host.length() == 0) return "";
        if (!"http".equals(scheme) && !"https".equals(scheme)) return "";
        int port = uri.getPort();
        if (port < -1 || port == 0 || port > 65535) return "";
        // IPv6 字面量要包一层方括号，否则拼出来的 URL 无法解析
        if (host.indexOf(':') >= 0 && !host.startsWith("[")) {
            host = "[" + host + "]";
        }
        String clean = scheme + "://" + host;
        if (port > 0) clean += ":" + port;
        return clean;
    }

    private void loadServer(String url) {
        currentUrl = url;
        prefs.edit().putString(KEY_URL, url).apply();
        loadSeq++;
        showLoading(url);
        web.loadUrl(url + "/");
    }

    private void showServerDialog(final boolean first) {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle(first ? "连接媒体库" : "服务器地址");
        builder.setMessage("输入 NAS 上瀑布相册服务的地址\n"
                + "例如 http://192.168.1.10:8000\n\n"
                + "地址只保存在本机，不会上传到任何地方。");
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setHint("http://192.168.1.10:8000");
        String saved = prefs.getString(KEY_URL, "");
        input.setText(saved == null ? "" : saved);
        input.setSelection(input.getText().length());
        builder.setView(input);
        builder.setCancelable(!first);
        builder.setPositiveButton("连接", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                String url = normalizeUrl(input.getText().toString());
                if (url.length() == 0) {
                    Toast.makeText(MainActivity.this,
                            "地址格式不对：请填 IP 或域名 + 端口，例如 192.168.1.10:8000",
                            Toast.LENGTH_LONG).show();
                    if (first) showServerDialog(true);
                    return;
                }
                loadServer(url);
            }
        });
        if (!first) builder.setNegativeButton("取消", null);
        builder.show();
    }

    @Override
    public void onBackPressed() {
        // 原生视频全屏时先退出全屏，不要走网页后退，更不要弹出「再按一次退出」
        if (customVideoView != null) {
            exitVideoFullscreen();
            return;
        }
        // 状态页盖着的时候别把返回键喂给看不见的网页，直接走「再按一次退出」
        if (statusPanel == null || statusPanel.getVisibility() != View.VISIBLE) {
            // 网页端用 history.pushState 管理预览，goBack() 会触发 popstate 关掉预览，
            // 与浏览器里「按后退只关预览」的行为一致
            if (web != null && web.canGoBack()) {
                web.goBack();
                return;
            }
        }
        long now = System.currentTimeMillis();
        if (now - lastBackPress < 2000) {
            super.onBackPressed();
        } else {
            lastBackPress = now;
            Toast.makeText(this, "再按一次退出瀑布相册", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        // manifest 里声明了 configChanges，旋转不重建 Activity；
        // 全屏视频容器主动请求一次重新测量，横竖屏切换后立刻铺满新尺寸
        if (fullscreenContainer != null) fullscreenContainer.requestLayout();
        // 配置变化会把状态栏重新显示出来，仍在视频全屏就再收一次
        if (customVideoView != null) hideSystemBars();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
        // 从后台切回来时系统可能把状态栏还回来了，仍在视频全屏就再收一次
        if (customVideoView != null) hideSystemBars();
    }

    @Override
    protected void onDestroy() {
        // 全屏中直接退出 Activity 时也要归还视频 View 并回调，避免媒体资源泄漏
        if (customVideoView != null) exitVideoFullscreen();
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
