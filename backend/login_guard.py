"""登录失败阶梯锁定（账号 + IP 双维度）。

维度一 · (账号, 来源 IP)：沿用原有阶梯
    第 3 次 → 5 分钟 | 第 4 次 → 10 分钟 | 第 5 次 → 30 分钟 | 第 6 次+ → 60 分钟
    锁定到期后累计次数不重置（否则第 4 次永远升不到 10 分钟），登录成功即清零。
    换成组合键是为了消除定向 DoS：别人只知道用户名、从自己设备输错，
    只能锁住「他自己那台设备对该账号」的记录，真实用户完全不受影响。

维度二 · 来源 IP（跨账号）：10 分钟窗口内累计 10 次失败 → 限制 5 分钟，
    防止攻击者靠不断换账号 / 换设备绕开维度一。窗口自动滚动，正常用户
    偶尔输错不会越积越多。两个维度任一命中都拒绝，取剩余时间更长的那个。

其它规则：
  * 锁定期间的请求直接拒绝，不计数、不延长锁定，无法把账号永久钉死。
  * 不存在的用户名不建账号记录，防止用随机用户名撑爆状态文件。
  * 累计次数与解锁时间落盘到 CONFIG_PATH，容器重启不能绕过。
  * 状态文件 v2 带 IP；v1（无 IP）无法正确归属，导入时忽略而不是误锁。
"""
import json
import math
import os
import threading
import time

from .config import CONFIG_PATH

_GUARD_FILE = CONFIG_PATH / "login_guard.json"
_STATE_VERSION = 2

_LOCK_STEPS = {3: 300, 4: 600, 5: 1800, 6: 3600}
_MAX_LOCK_SEC = 3600
# IP 维度：窗口、阈值、锁定时长都可通过环境变量调整（反代后共用一个 IP 时调高阈值）
_IP_WINDOW_SEC = max(60, int(os.getenv("LOGIN_IP_WINDOW_SEC", "600")))
_IP_FAIL_THRESHOLD = max(3, int(os.getenv("LOGIN_IP_FAIL_THRESHOLD", "10")))
_IP_LOCK_SEC = max(60, int(os.getenv("LOGIN_IP_LOCK_SEC", "300")))
_MAX_RECORDS = 1000

_guard_lock = threading.Lock()
_accounts: dict = {}  # "username\x1fip" -> {"username","ip","fails","until"}
_ips: dict = {}       # ip -> {"fails","until","window_start"}

# 便于测试注入时间；生产里就是 time.time
_now = time.time


def _key(username: str, ip: str) -> str:
    # 用户名可能含 | 或 @，用单元分隔符避免拼接歧义
    return username + "\x1f" + ip


def _state_locked() -> dict:
    return {"v": _STATE_VERSION, "accounts": _accounts, "ips": _ips}


def _save_locked():
    """调用方必须持 _guard_lock。原子写；写失败不影响内存中的防护。"""
    tmp = _GUARD_FILE.with_name(_GUARD_FILE.name + ".tmp")
    try:
        tmp.write_text(json.dumps(_state_locked(), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _GUARD_FILE)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _clean_int(value, default=0, minimum=0):
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _clean_float(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def load_guard():
    """启动时恢复；旧版（无 IP）记录无法归属，宁可丢弃也不误锁真实用户。"""
    try:
        if not _GUARD_FILE.exists():
            return
        data = json.loads(_GUARD_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        if data.get("v") != _STATE_VERSION:
            # 明确的版本迁移：磁盘状态已不适用，内存也要同步从空状态开始，
            # 否则「以文件为准」不成立，旧进程残留的记录会一直留在管理界面里
            print("[LOGIN] 旧版登录锁定记录缺少来源 IP，已忽略（不会误锁真实用户）")
            with _guard_lock:
                _accounts.clear()
                _ips.clear()
            return
        accounts, ips = {}, {}
        for key, rec in (data.get("accounts") or {}).items():
            if not isinstance(key, str) or not isinstance(rec, dict):
                continue
            username = rec.get("username")
            ip = rec.get("ip")
            if not isinstance(username, str) or not isinstance(ip, str) or not username or not ip:
                continue
            fails = _clean_int(rec.get("fails", 0))
            if fails <= 0:
                continue
            accounts[key] = {"username": username, "ip": ip, "fails": fails,
                             "until": _clean_float(rec.get("until", 0))}
            if len(accounts) >= _MAX_RECORDS:
                break
        for ip, rec in (data.get("ips") or {}).items():
            if not isinstance(ip, str) or not isinstance(rec, dict) or not ip:
                continue
            fails = _clean_int(rec.get("fails", 0))
            if fails <= 0:
                continue
            ips[ip] = {"fails": fails, "until": _clean_float(rec.get("until", 0)),
                       "window_start": _clean_float(rec.get("window_start", 0))}
            if len(ips) >= _MAX_RECORDS:
                break
        with _guard_lock:
            _accounts.clear()
            _accounts.update(accounts)
            _ips.clear()
            _ips.update(ips)
    except Exception as exc:
        print(f"[LOGIN] 锁定状态读取失败（{exc}），本次从空状态开始")


def _evict_oldest(mapping):
    """状态表到上限时淘汰最老的一条。

    load_guard() 载入时会截断，但运行时同样要限规模：开了 TRUST_PROXY_HEADERS
    又没在代理层清洗 X-Forwarded-For 时，伪造来源可以把状态文件越写越大。
    """
    if not mapping:
        return
    oldest = min(mapping, key=lambda k: mapping[k].get("window_start", 0))
    mapping.pop(oldest, None)


def _remaining(rec, now) -> int:
    left = rec["until"] - now
    if left <= 0:
        return 0
    # 时钟回拨（NTP 校正、容器暂停恢复）会让 until 显得远在将来；
    # 锁定时长本身不会超过两个维度里最长的那档，超出部分一律截断
    ceiling = max(_MAX_LOCK_SEC, _IP_LOCK_SEC)
    return min(int(math.ceil(left)), ceiling)


def check_locked(username: str, ip: str):
    """返回 {"scope","seconds","msg"} 或 None。锁定期间不验证密码、不计数。

    两个维度可能同时锁着：取剩余时间更长的那个，否则倒计时到点后
    又会被另一条记录挡回来，出现「等完了还要再等」的跳变。
    """
    now = _now()
    hits = []
    changed = False
    with _guard_lock:
        iprec = _ips.get(ip)
        if iprec:
            left = _remaining(iprec, now)
            if left:
                hits.append({"scope": "ip", "seconds": left,
                             "msg": f"该网络登录失败次数过多，请在 {lock_label(left)} 后重试"})
            elif iprec["until"]:
                iprec["until"] = 0.0
                changed = True
        arec = _accounts.get(_key(username, ip))
        if arec:
            left = _remaining(arec, now)
            if left:
                hits.append({"scope": "account", "seconds": left,
                             "msg": f"密码连续输错 {arec['fails']} 次，请在 {lock_label(left)} 后重试"})
            elif arec["until"]:
                arec["until"] = 0.0
                changed = True
        # 到期清理必须落盘：原来一命中就 return，磁盘上仍留着过期的 until，
        # 容器重启后这把已经过期的锁会「复活」
        if changed:
            _save_locked()
    if not hits:
        return None
    return max(hits, key=lambda h: h["seconds"])


def record_failure(username: str, ip: str):
    """记一次密码错误；返回本次触发的锁定信息 dict，未触发则 None。"""
    now = _now()
    with _guard_lock:
        # --- 维度二：来源 IP，10 分钟滚动窗口 ---
        iprec = _ips.get(ip)
        if iprec is None:
            if len(_ips) >= _MAX_RECORDS:
                _evict_oldest(_ips)
            iprec = {"fails": 0, "until": 0.0, "window_start": now}
            _ips[ip] = iprec
        # 时钟回拨时 now < window_start，负数差值会让累计次数永远挂在旧窗口里
        if now < iprec["window_start"] or now - iprec["window_start"] > _IP_WINDOW_SEC:
            iprec["fails"] = 1
            iprec["window_start"] = now
        else:
            iprec["fails"] += 1
        ip_hit = None
        if iprec["fails"] >= _IP_FAIL_THRESHOLD:
            if iprec["until"] <= now:
                iprec["until"] = now + _IP_LOCK_SEC
            left = max(1, _remaining(iprec, now))
            ip_hit = {
                "scope": "ip", "seconds": left, "fails": iprec["fails"],
                "msg": f"该网络登录失败次数过多，已临时限制，请在 {lock_label(left)} 后重试",
                "log": f"来源 {ip} 在 {_IP_WINDOW_SEC // 60} 分钟内累计 "
                       f"{iprec['fails']} 次失败，限制 {lock_label(left)}",
            }

        # --- 维度一：(账号, IP) 阶梯 ---
        key = _key(username, ip)
        arec = _accounts.get(key)
        if arec is None:
            if len(_accounts) >= _MAX_RECORDS:
                _evict_oldest(_accounts)
            arec = {"username": username, "ip": ip, "fails": 0, "until": 0.0}
            _accounts[key] = arec
        arec["fails"] += 1
        n = arec["fails"]
        secs = _LOCK_STEPS.get(n)
        if secs is None and n > 6:
            secs = _MAX_LOCK_SEC
        acct_hit = None
        if secs:
            # 并发失败可能同时踩到不同档位：已锁着就不覆盖解锁时间
            if arec["until"] <= now:
                arec["until"] = now + secs
            left = max(1, _remaining(arec, now))
            acct_hit = {
                "scope": "account", "seconds": left, "fails": n,
                "msg": f"密码连续输错 {n} 次，请在 {lock_label(left)} 后重试",
                "log": f"{username}@{ip} 连续 {n} 次密码错误，锁定 {lock_label(left)}",
            }
        _save_locked()
        if ip_hit and acct_hit:
            return max((ip_hit, acct_hit), key=lambda h: h["seconds"])
        return ip_hit or acct_hit


def record_success(username: str, ip: str):
    """登录成功：清掉该(账号,IP)记录，并重置该来源 IP 的窗口计数。"""
    with _guard_lock:
        changed = _accounts.pop(_key(username, ip), None) is not None
        if _ips.pop(ip, None) is not None:
            changed = True
        if changed:
            _save_locked()


def snapshot():
    """管理员查看：当前所有失败/锁定记录（含两个维度），锁中的排前面。"""
    now = _now()
    out = []
    with _guard_lock:
        for rec in _accounts.values():
            left = _remaining(rec, now)
            out.append({"kind": "account", "username": rec["username"], "ip": rec["ip"],
                        "fails": rec["fails"], "left": left, "locked": left > 0})
        for ip, rec in _ips.items():
            left = _remaining(rec, now)
            out.append({"kind": "ip", "username": "", "ip": ip,
                        "fails": rec["fails"], "left": left, "locked": left > 0})
    out.sort(key=lambda x: (-x["left"], x["kind"], x["username"], x["ip"]))
    return out


def unlock(scope=None, username=None, ip=None, all_records=False) -> int:
    """管理员一键解锁，返回清掉的记录数。

    scope=account：清指定(账号, IP)；只给 username 时清该账号全部设备。
    scope=ip：清该来源 IP 的全局记录，以及该 IP 下所有账号记录。
    all_records=True：全部清空。
    """
    with _guard_lock:
        removed = 0
        if all_records:
            removed = len(_accounts) + len(_ips)
            _accounts.clear()
            _ips.clear()
        elif scope == "ip" and ip:
            if _ips.pop(ip, None) is not None:
                removed += 1
            for k in [k for k, v in _accounts.items() if v["ip"] == ip]:
                _accounts.pop(k, None)
                removed += 1
        elif scope == "account" and username and ip:
            # 必须同时给账号和 IP：原来缺省账号时会悄悄清掉该 IP 下所有账号
            # 记录却不解 IP 全局锁，管理员点了「解锁」却发现还是登不上
            if _accounts.pop(_key(username, ip), None) is not None:
                removed += 1
        elif username:
            for k in [k for k, v in _accounts.items() if v["username"] == username]:
                _accounts.pop(k, None)
                removed += 1
        else:
            return 0
        if removed:
            _save_locked()
        return removed


def lock_label(seconds) -> str:
    """把秒数说成人话，用于锁定提示、管理界面与执行日志。"""
    try:
        s = max(1, int(math.ceil(float(seconds))))
    except (TypeError, ValueError):
        return "1 分钟"
    if s >= 3600:
        return "1 小时"
    if s >= 60:
        m = int(math.ceil(s / 60))
        return f"{m} 分钟"
    return f"{s} 秒"


load_guard()  # 模块导入时恢复上次进程留下的锁定状态
