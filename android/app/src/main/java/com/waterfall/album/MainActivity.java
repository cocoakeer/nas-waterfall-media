package com.waterfall.album;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 瀑布相册 —— NAS 媒体库的原生 WebView 客户端。
 *
 * 媒体文件、账号、缩略图都在 NAS 上，这里只负责：
 *   1. 首次启动记录服务器地址（仅存本机 SharedPreferences，不备份、不上传）
 *   2. 用同源 WebView 加载现有前端，因此不需要后端加 CORS
 *   3. 全屏幻灯片跟随设备方向自适应：原生层不干预设备方向，
 *      manifest 里声明 configChanges，旋转时不重建 Activity，WebView 不重载、
 *      轮播不中断；横竖屏布局由网页端 CSS 媒体查询处理
 *   4. 返回键交给网页 history（与浏览器里「后退只关预览」一致）。
 *      幻灯片界面没有自己的历史记录，此时按返回键会触发目录级 popstate，
 *      不会直接关掉幻灯片；退出请用界面上的「退出全屏」按钮
 *
 * 不申请存储/定位/通讯录权限，不加载任何第三方 SDK。
 */
public class MainActivity extends Activity {

    private static final String PREF_NAME = "waterfall_album";
    private static final String KEY_URL = "server_url";

    private SharedPreferences prefs;
    private WebView web;
    private View errorPanel;
    private TextView errorText;
    private String currentUrl = "";
    private long lastBackPress = 0L;

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
        root.setBackgroundColor(Color.parseColor("#0E1014"));

        web = new WebView(this);
        configureWebView(web);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        errorPanel = buildErrorPanel();
        errorPanel.setVisibility(View.GONE);
        root.addView(errorPanel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        // 半透明小按钮：换 NAS / 换端口时随时能改地址，平时几乎不挡内容
        Button settingsBtn = new Button(this);
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
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && request.isForMainFrame()) {
                    showError("无法连接媒体库\n" + currentUrl + "\n\n" + error.getDescription());
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                           android.webkit.WebResourceResponse response) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                        && request.isForMainFrame() && response.getStatusCode() >= 400) {
                    showError("服务器返回 " + response.getStatusCode() + "\n" + currentUrl);
                }
            }
        });

        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                // 相册用不到摄像头/麦克风，一律拒绝，不弹系统权限框
                request.deny();
            }
        });
    }

    private View buildErrorPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setBackgroundColor(Color.parseColor("#0E1014"));
        panel.setPadding(dp(28), dp(24), dp(28), dp(24));

        TextView title = new TextView(this);
        title.setText("瀑布相册");
        title.setTextColor(Color.parseColor("#E9ECF1"));
        title.setTextSize(20f);
        title.setGravity(Gravity.CENTER);
        panel.addView(title);

        errorText = new TextView(this);
        errorText.setTextColor(Color.parseColor("#AAB1BD"));
        errorText.setTextSize(13f);
        errorText.setGravity(Gravity.CENTER);
        errorText.setPadding(0, dp(16), 0, dp(24));
        panel.addView(errorText);

        Button retry = new Button(this);
        retry.setText("重试");
        retry.setTextColor(Color.WHITE);
        retry.setBackgroundColor(Color.parseColor("#5B82F7"));
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (currentUrl.length() > 0) loadServer(currentUrl);
                else showServerDialog(true);
            }
        });
        panel.addView(retry, new LinearLayout.LayoutParams(
                dp(180), ViewGroup.LayoutParams.WRAP_CONTENT));

        Button edit = new Button(this);
        edit.setText("修改服务器地址");
        edit.setTextColor(Color.parseColor("#AAB1BD"));
        edit.setBackgroundColor(Color.TRANSPARENT);
        edit.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showServerDialog(false);
            }
        });
        panel.addView(edit, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return panel;
    }

    private void showError(String message) {
        errorText.setText(message);
        errorPanel.setVisibility(View.VISIBLE);
        errorPanel.bringToFront();
    }

    private void hideError() {
        errorPanel.setVisibility(View.GONE);
    }

    /** 允许直接填 192.168.1.10:8000，自动补 http:// 并去掉多余斜杠。 */
    private String normalizeUrl(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.length() == 0) return "";
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://" + s;
        }
        s = s.replaceAll("/+$", "");
        Uri uri = Uri.parse(s);
        String host = uri.getHost();
        String scheme = uri.getScheme();
        if (host == null || host.length() == 0) return "";
        if (!"http".equals(scheme) && !"https".equals(scheme)) return "";
        return s;
    }

    private void loadServer(String url) {
        currentUrl = url;
        prefs.edit().putString(KEY_URL, url).apply();
        hideError();
        web.loadUrl(url + "/");
    }

    private void showServerDialog(final boolean first) {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle(first ? "连接媒体库" : "服务器地址");
        builder.setMessage("输入 NAS 上瀑布相册服务的地址，例如\n"
                + "http://192.168.1.10:8000\n\n"
                + "地址只保存在本机，不会上传到任何地方。");
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setHint("http://192.168.1.10:8000");
        input.setText(prefs.getString(KEY_URL, ""));
        input.setSelection(input.getText().length());
        builder.setView(input);
        builder.setCancelable(!first);
        builder.setPositiveButton("连接", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                String url = normalizeUrl(input.getText().toString());
                if (url.length() == 0) {
                    Toast.makeText(MainActivity.this, "地址格式不对，请检查后重试",
                            Toast.LENGTH_SHORT).show();
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
        // 网页端用 history.pushState 管理预览，goBack() 会触发 popstate 关掉预览，
        // 与浏览器里「按后退只关预览」的行为一致
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
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
    protected void onPause() {
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
