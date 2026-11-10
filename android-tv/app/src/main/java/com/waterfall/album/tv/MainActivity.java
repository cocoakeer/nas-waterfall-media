package com.waterfall.album.tv;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.KeyEvent;
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

/**
 * 瀑布相册 TV —— 遥控器 / 10-foot 界面版本。
 *
 * 与手机端共用同一套前端：UA 里带 WaterfallAlbumTV 标记，前端据此开启
 * tv-mode（大字号、更少列数、明显的焦点框、方向键按卡片位置空间导航）。
 * 原生层负责：
 *   1. 首次用遥控器填服务器地址（大输入框 + 常用片段快捷按钮，减少逐字符输入）
 *   2. 连接中 / 失败全部用原生大字状态页，不露出浏览器错误页
 *   3. 视频原生全屏（onShowCustomView），方向不锁死
 *   4. 返回键：退出全屏 → 回配置页 → 网页后退 → 退出确认对话框
 *
 * 刻意不使用 AndroidX Leanback，也不引用任何 R.* 资源 ID：构建链是
 * aapt2 → javac → d8，没有生成 R.java，所有 drawable 都在代码里构造。
 */
public class MainActivity extends Activity {

    private static final String PREF_NAME = "waterfall_album_tv";
    private static final String KEY_URL = "server_url";
    private static final String TV_UA_TAG = " WaterfallAlbumTV/1.0";
    /**
     * 遥控器导航兜底：连到尚未更新的服务端（没有 tv-mode 前端）时，
     * 由客户端自己给卡片加 tabindex、装方向键空间导航和焦点框。
     * 新版前端会先设置 window.__tvNavReady，这里就直接跳过，避免重复监听。
     */
    private static final String TV_FALLBACK_JS =
            "(function(){"
            + "if(window.__tvNavReady) return;window.__tvNavReady=true;"
            + "document.documentElement.classList.add('tv-mode');"
            + "var st=document.createElement('style');"
            + "st.textContent='.media-card:focus{outline:4px solid #5B82F7!important;"
            + "outline-offset:3px;z-index:20}';document.head.appendChild(st);"
            + "function mark(){var cs=document.querySelectorAll('.media-card');"
            + "for(var i=0;i<cs.length;i++){if(!cs[i].hasAttribute('tabindex'))"
            + "cs[i].setAttribute('tabindex','0');}"
            + "var bs=document.querySelectorAll('.breadcrumb-item');"
            + "for(var j=0;j<bs.length;j++){if(!bs[j].hasAttribute('tabindex'))"
            + "bs[j].setAttribute('tabindex','0');}"
            + "var a=document.activeElement;"
            // 只有焦点压根不在页面上时才给首卡：搜索框/按钮/弹窗正在用时不能抢焦点
            + "if(cs.length&&(!a||a===document.body||a===document.documentElement))cs[0].focus();}"
            + "mark();"
            + "if(window.MutationObserver)new MutationObserver(mark)"
            + ".observe(document.body,{childList:true,subtree:true});"
            + "document.addEventListener('keydown',function(e){"
            // div/span 上的 OK 键不会自动触发 click，旧服务端同样要显式补
            + "if(e.key==='Enter'||e.key===' '||e.key==='Spacebar'){"
            + "var h=document.activeElement;"
            + "if(h&&h.classList&&(h.classList.contains('media-card')||"
            + "h.classList.contains('breadcrumb-item'))){e.preventDefault();h.click();}"
            + "return;}"
            + "if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].indexOf(e.key)<0)return;"
            // 输入框/下拉框里的左右键要留给移动光标、切换选项，别把焦点抢到卡片
            + "var a=document.activeElement;"
            + "if(a&&(a.tagName==='INPUT'||a.tagName==='SELECT'||"
            + "a.tagName==='TEXTAREA'||a.isContentEditable))return;"
            + "if(document.querySelector('.preview-mask,.slide-root'))return;"
            + "var cards=Array.prototype.slice.call(document.querySelectorAll('.media-card'));"
            + "if(!cards.length)return;"
            + "var bars=Array.prototype.slice.call(document.querySelectorAll("
            + "'.header-actions button,.breadcrumb-item'));"
            + "var bi=bars.indexOf(document.activeElement);"
            + "if(bi>=0){if(e.key==='ArrowLeft'||e.key==='ArrowRight'){"
            + "var nb=bars[bi+(e.key==='ArrowRight'?1:-1)];"
            + "if(nb){nb.focus();e.preventDefault();}}"
            + "else if(e.key==='ArrowDown'){cards[0].focus();e.preventDefault();}"
            + "return;}"
            + "var i=cards.indexOf(document.activeElement);"
            + "if(i<0){cards[0].focus();e.preventDefault();return;}"
            + "var r=cards[i].getBoundingClientRect();"
            + "var cx=r.left+r.width/2,cy=r.top+r.height/2;"
            + "var best=-1,score=1e9;"
            + "for(var j=0;j<cards.length;j++){if(j===i)continue;"
            + "var t=cards[j].getBoundingClientRect();"
            + "var dx=t.left+t.width/2-cx,dy=t.top+t.height/2-cy;"
            + "var hor=e.key==='ArrowLeft'||e.key==='ArrowRight';"
            + "var sec=hor?Math.abs(dy):Math.abs(dx),pri=0;"
            + "if(e.key==='ArrowRight'&&dx>4)pri=dx;"
            + "else if(e.key==='ArrowLeft'&&dx<-4)pri=-dx;"
            + "else if(e.key==='ArrowDown'&&dy>4)pri=dy;"
            + "else if(e.key==='ArrowUp'&&dy<-4)pri=-dy;"
            + "else continue;"
            + "var sc=pri+sec*2;if(sc<score){score=sc;best=j;}}"
            + "if(best>=0){cards[best].focus();"
            + "cards[best].scrollIntoView({block:'nearest'});e.preventDefault();}"
            + "else if(e.key==='ArrowUp'&&bars.length){"
            + "var hb=document.querySelectorAll('.header-actions button');"
            + "var tg=hb.length?hb[hb.length-1]:bars[bars.length-1];"
            + "tg.focus();e.preventDefault();}"
            + "},true);})()";

    /** 前端 index.html 的标记；第二条兼容尚未更新的服务端 */
    private static final String APP_CHECK_JS =
            "(function(){"
            + "var m=document.querySelector('meta[name=waterfall-album]');"
            + "if(m && m.getAttribute('content')==='1') return '1';"
            + "var app=document.getElementById('app');"
            + "if(app && (document.title||'').indexOf('NAS媒体瀑布流')>=0) return '1';"
            + "return '';})()";

    private SharedPreferences prefs;
    private WebView web;
    private FrameLayout rootLayout;
    private View setupPanel;
    private View statusPanel;
    private EditText urlInput;
    private TextView statusTitle;
    private TextView statusDesc;
    private TextView statusUrl;
    private Button retryBtn;
    private Button setupBtn;
    private ProgressBar statusProgress;
    private String currentUrl = "";
    private boolean loadFailed = false;
    private boolean verifying = false;
    private int loadSeq = 0;

    /** HTML5 视频原生全屏 */
    private FrameLayout fullscreenContainer;
    private View customVideoView;
    private WebChromeClient.CustomViewCallback customViewCallback;
    private int savedSystemUiVisibility = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        buildUi();
        String saved = prefs.getString(KEY_URL, "");
        if (saved == null || saved.length() == 0) {
            showSetup();
        } else {
            loadServer(saved);
        }
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private GradientDrawable rounded(int color) {
        GradientDrawable g = new GradientDrawable();
        g.setCornerRadius(dp(10));
        g.setColor(color);
        return g;
    }

    /** 遥控器焦点态：聚焦时整块变蓝，10 英尺外也看得清。 */
    private StateListDrawable focusableBackground() {
        StateListDrawable s = new StateListDrawable();
        s.addState(new int[]{android.R.attr.state_focused},
                rounded(Color.parseColor("#FF5B82F7")));
        s.addState(new int[]{}, rounded(Color.parseColor("#FF232B36")));
        return s;
    }

    private Button bigButton(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextSize(18f);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setBackground(focusableBackground());
        b.setPadding(dp(22), dp(10), dp(22), dp(10));
        return b;
    }

    private TextView bigText(String text, float size, String color) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(size);
        t.setTextColor(Color.parseColor(color));
        t.setGravity(Gravity.CENTER);
        return t;
    }

    private void buildUi() {
        rootLayout = new FrameLayout(this);
        rootLayout.setBackgroundColor(Color.parseColor("#0E1014"));

        web = new WebView(this);
        configureWebView(web);
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        rootLayout.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        setupPanel = buildSetupPanel();
        setupPanel.setVisibility(View.GONE);
        rootLayout.addView(setupPanel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        statusPanel = buildStatusPanel();
        statusPanel.setVisibility(View.GONE);
        rootLayout.addView(statusPanel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        setContentView(rootLayout);
    }

    private View buildSetupPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setBackgroundColor(Color.parseColor("#0E1014"));
        panel.setPadding(dp(60), dp(40), dp(60), dp(40));
        panel.setClickable(true);

        panel.addView(bigText("连接媒体库", 30f, "#E9ECF1"));
        TextView hint = bigText("输入 NAS 上瀑布相册服务的地址\n例如  http://192.168.1.10:8000",
                17f, "#AAB1BD");
        LinearLayout.LayoutParams hintLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hintLp.setMargins(0, dp(14), 0, dp(24));
        panel.addView(hint, hintLp);

        urlInput = new EditText(this);
        urlInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        urlInput.setSingleLine(true);
        urlInput.setTextSize(24f);
        urlInput.setTextColor(Color.WHITE);
        urlInput.setHintTextColor(Color.parseColor("#7B8492"));
        urlInput.setHint("http://192.168.1.10:8000");
        urlInput.setPadding(dp(20), dp(14), dp(20), dp(14));
        GradientDrawable inputBg = rounded(Color.parseColor("#FF1F232B"));
        inputBg.setStroke(dp(2), Color.parseColor("#FF5B82F7"));
        urlInput.setBackground(inputBg);
        LinearLayout.LayoutParams inputLp = new LinearLayout.LayoutParams(
                dp(560), ViewGroup.LayoutParams.WRAP_CONTENT);
        panel.addView(urlInput, inputLp);

        // 遥控器逐字符输入很慢，把最常输入的两段做成一键插入
        LinearLayout quick = new LinearLayout(this);
        quick.setOrientation(LinearLayout.HORIZONTAL);
        quick.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams quickLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        quickLp.setMargins(0, dp(18), 0, 0);
        Button ipPrefix = bigButton("192.168.1.");
        ipPrefix.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { insertText("192.168.1."); }
        });
        Button port = bigButton(":8000");
        port.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { insertText(":8000"); }
        });
        Button del = bigButton("删除");
        del.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { deleteOneChar(); }
        });
        Button clear = bigButton("清空");
        clear.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                urlInput.setText("http://");
                urlInput.setSelection(urlInput.getText().length());
                urlInput.requestFocus();
            }
        });
        for (Button b : new Button[]{ipPrefix, port, del, clear}) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.setMargins(dp(6), 0, dp(6), 0);
            quick.addView(b, lp);
        }
        panel.addView(quick, quickLp);

        Button connect = bigButton("连接");
        connect.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { submitSetup(); }
        });
        LinearLayout.LayoutParams connectLp = new LinearLayout.LayoutParams(
                dp(260), ViewGroup.LayoutParams.WRAP_CONTENT);
        connectLp.setMargins(0, dp(26), 0, 0);
        panel.addView(connect, connectLp);
        return panel;
    }

    private View buildStatusPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setBackgroundColor(Color.parseColor("#0E1014"));
        panel.setPadding(dp(60), dp(40), dp(60), dp(40));
        panel.setClickable(true);

        statusProgress = new ProgressBar(this);
        statusProgress.setIndeterminate(true);
        panel.addView(statusProgress, new LinearLayout.LayoutParams(dp(56), dp(56)));

        statusTitle = bigText("正在连接相册", 28f, "#E9ECF1");
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        titleLp.setMargins(0, dp(24), 0, 0);
        panel.addView(statusTitle, titleLp);

        statusDesc = bigText("正在打开服务器地址…", 18f, "#AAB1BD");
        statusDesc.setLineSpacing(dp(6), 1f);
        LinearLayout.LayoutParams descLp = new LinearLayout.LayoutParams(
                dp(700), ViewGroup.LayoutParams.WRAP_CONTENT);
        descLp.setMargins(0, dp(16), 0, 0);
        panel.addView(statusDesc, descLp);

        statusUrl = bigText("", 15f, "#7B8492");
        statusUrl.setSingleLine(true);
        statusUrl.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        LinearLayout.LayoutParams urlLp = new LinearLayout.LayoutParams(
                dp(700), ViewGroup.LayoutParams.WRAP_CONTENT);
        urlLp.setMargins(0, dp(12), 0, 0);
        panel.addView(statusUrl, urlLp);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams rowLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rowLp.setMargins(0, dp(30), 0, 0);
        retryBtn = bigButton("重试");
        retryBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                if (currentUrl.length() > 0) loadServer(currentUrl);
                else showSetup();
            }
        });
        setupBtn = bigButton("修改服务器地址");
        setupBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showSetup(); }
        });
        for (Button b : new Button[]{retryBtn, setupBtn}) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.setMargins(dp(10), 0, dp(10), 0);
            row.addView(b, lp);
        }
        panel.addView(row, rowLp);
        return panel;
    }

    private void insertText(String text) {
        Editable e = urlInput.getText();
        int start = Math.min(urlInput.getSelectionStart(), urlInput.getSelectionEnd());
        int end = Math.max(urlInput.getSelectionStart(), urlInput.getSelectionEnd());
        e.replace(start, end, text);
        urlInput.requestFocus();
    }

    private void deleteOneChar() {
        Editable e = urlInput.getText();
        int pos = urlInput.getSelectionStart();
        if (pos > 0) e.delete(pos - 1, pos);
        urlInput.requestFocus();
    }

    private void submitSetup() {
        String url = normalizeUrl(urlInput.getText().toString());
        if (url.length() == 0) {
            showError("地址格式不对", "请填 IP 或域名 + 端口，例如 192.168.1.10:8000");
            return;
        }
        loadServer(url);
    }

    /** 允许直接填 192.168.1.10:8000；补协议、丢掉误粘贴路径、校验端口范围。 */
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
        if (host.indexOf(':') >= 0 && !host.startsWith("[")) {
            host = "[" + host + "]";
        }
        String clean = scheme + "://" + host;
        if (port > 0) clean += ":" + port;
        return clean;
    }

    private void showSetup() {
        // 打开配置页就作废在途加载：旧地址稍后连上时 onPageFinished 不该再来盖掉
        // 配置页。所有入口（菜单键、返回键、按钮、waterfall-tv://setup）统一走这里，
        // 避免每个调用点各写一遍 loadSeq++ / stopLoading
        loadSeq++;
        if (web != null) web.stopLoading();
        loadFailed = false;
        verifying = false;
        statusPanel.setVisibility(View.GONE);
        setupPanel.setVisibility(View.VISIBLE);
        String saved = currentUrl.length() > 0 ? currentUrl : "http://";
        urlInput.setText(saved);
        urlInput.setSelection(urlInput.getText().length());
        urlInput.requestFocus();
    }

    private void loadServer(String url) {
        currentUrl = url;
        prefs.edit().putString(KEY_URL, url).apply();
        loadSeq++;
        loadFailed = false;
        verifying = true;
        setupPanel.setVisibility(View.GONE);
        statusProgress.setVisibility(View.VISIBLE);
        statusTitle.setText("正在连接相册");
        statusDesc.setText("正在打开服务器地址…");
        statusUrl.setText(url);
        retryBtn.setVisibility(View.GONE);
        setupBtn.setVisibility(View.GONE);
        statusPanel.setVisibility(View.VISIBLE);
        web.loadUrl(url + "/");
    }

    private void showError(String title, String desc) {
        if (loadFailed) return;
        loadFailed = true;
        verifying = false;
        web.stopLoading();
        statusProgress.setVisibility(View.GONE);
        statusTitle.setText(title);
        statusDesc.setText(desc);
        statusUrl.setText(currentUrl);
        retryBtn.setVisibility(View.VISIBLE);
        setupBtn.setVisibility(View.VISIBLE);
        statusPanel.setVisibility(View.VISIBLE);
    }

    private void showContent() {
        verifying = false;
        loadFailed = false;
        statusPanel.setVisibility(View.GONE);
        setupPanel.setVisibility(View.GONE);
        web.requestFocus();
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
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setMediaPlaybackRequiresUserGesture(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
            CookieManager.getInstance().setAcceptThirdPartyCookies(w, false);
        }
        // 前端靠这个标记开启 tv-mode：大字号、少列数、方向键空间导航、焦点框
        s.setUserAgentString(s.getUserAgentString() + TV_UA_TAG);

        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request == null ? null : request.getUrl();
                if (u != null && "waterfall-tv".equals(u.getScheme())
                        && "setup".equals(u.getHost())) {
                    showSetup();
                    return true;
                }
                return false;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (!request.isForMainFrame() || isStaleRequest(request)) return;
                CharSequence raw = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                        ? error.getDescription() : null;
                if (String.valueOf(raw).toLowerCase().contains("err_aborted")) return;
                showError("连不上相册", friendlyNetworkError(raw));
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse response) {
                if (!request.isForMainFrame() || isStaleRequest(request)) return;
                if (response.getStatusCode() >= 400) {
                    showError("服务没能正常响应",
                            "服务返回了 HTTP " + response.getStatusCode()
                            + "，确认地址和端口是不是相册服务。");
                }
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler,
                                           SslError error) {
                showError("HTTPS 证书不受信任",
                        "这个地址用了自签名证书。局域网里建议直接填 http:// 地址。");
                handler.cancel();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (loadFailed || !verifying) return;
                if (url == null || url.startsWith("about:") || isStalePage(url)) return;
                // 旧服务端没有 tv-mode 前端时，客户端自己补一套遥控器导航
                view.evaluateJavascript(TV_FALLBACK_JS, null);
                final int seq = loadSeq;
                view.evaluateJavascript(APP_CHECK_JS, new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if (seq != loadSeq || loadFailed || !verifying) return;
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
                // 忽略页面请求的横屏，方向跟随电视自身
                enterVideoFullscreen(videoView, callback);
            }

            @Override
            public void onHideCustomView() {
                exitVideoFullscreen();
            }
        });
    }

    private boolean isStaleRequest(WebResourceRequest request) {
        return request != null && request.getUrl() != null
                && isStaleUri(request.getUrl());
    }

    /** onPageFinished 也可能来自上一次地址的延迟回调，别让它污染新加载。 */
    private boolean isStalePage(String url) {
        return isStaleUri(Uri.parse(url));
    }

    private boolean isStaleUri(Uri req) {
        if (currentUrl.length() == 0) return false;
        Uri cur = Uri.parse(currentUrl);
        String rh = req.getHost();
        String ch = cur.getHost();
        if (rh == null || ch == null) return false;
        return !rh.equalsIgnoreCase(ch) || req.getPort() != cur.getPort();
    }

    private String friendlyNetworkError(CharSequence description) {
        String d = String.valueOf(description == null ? "" : description).toLowerCase();
        if (d.contains("err_connection_refused")) {
            return "这个端口上没有人应答。通常是端口写错，或者相册服务没启动。";
        }
        if (d.contains("err_name_not_resolved") || d.contains("unknown_host")) {
            return "找不到这个地址，检查一下 IP 或域名有没有写错。";
        }
        if (d.contains("timed_out") || d.contains("timeout")) {
            return "连接超时。电视和 NAS 可能不在同一个网络。";
        }
        if (d.contains("internet_disconnected") || d.contains("network_changed")) {
            return "电视当前没连上网络，检查网线或 Wi-Fi 后再试。";
        }
        if (d.contains("address_unreachable")) {
            return "这个地址不可达，确认电视和 NAS 在同一个网段。";
        }
        return "连接失败，请检查地址、端口和服务是否在运行。";
    }

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
        if (videoView.getParent() instanceof ViewGroup) {
            ((ViewGroup) videoView.getParent()).removeView(videoView);
        }
        fullscreenContainer.setClickable(true);
        fullscreenContainer.addView(videoView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER));
        rootLayout.addView(fullscreenContainer, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
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
        WebChromeClient.CustomViewCallback cb = customViewCallback;
        customVideoView = null;
        customViewCallback = null;
        if (cb != null) cb.onCustomViewHidden();
    }

    private void setVideoFullscreenFlag(boolean on) {
        if (web == null) return;
        web.evaluateJavascript(
                "window.__albumVideoFullscreen=" + (on ? "true" : "false") + ";", null);
    }

    private void hideSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
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

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // 遥控器菜单键 / 设置键随时可以改服务器地址，不必去够页面角落里的按钮
        if (keyCode == KeyEvent.KEYCODE_MENU || keyCode == KeyEvent.KEYCODE_SETTINGS) {
            // 视频全屏容器压在最上层，不先退出的话配置页会被它整个盖住
            if (customVideoView != null) exitVideoFullscreen();
            showSetup();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public void onBackPressed() {
        if (customVideoView != null) {
            exitVideoFullscreen();
            return;
        }
        if (statusPanel.getVisibility() == View.VISIBLE) {
            // 连不上时返回到改地址，比直接退出有用；在途加载由 showSetup 统一作废
            showSetup();
            return;
        }
        if (setupPanel.getVisibility() == View.VISIBLE) {
            confirmExit();
            return;
        }
        if (web.canGoBack()) {
            web.goBack();
            return;
        }
        confirmExit();
    }

    private void confirmExit() {
        new AlertDialog.Builder(this)
                .setTitle("退出瀑布相册 TV？")
                .setPositiveButton("退出", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int which) {
                        finish();
                    }
                })
                .setNegativeButton("继续浏览", null)
                .show();
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        if (fullscreenContainer != null) fullscreenContainer.requestLayout();
        if (customVideoView != null) hideSystemBars();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
        if (customVideoView != null) hideSystemBars();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    protected void onDestroy() {
        if (customVideoView != null) exitVideoFullscreen();
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
