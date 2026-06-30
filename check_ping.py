#!/usr/bin/env python3
"""
check_ping.py — Trình khởi động & Watchdog nhẹ cho manager.py
==============================================================
LUỒNG HOẠT ĐỘNG:
  1. check_ping.py khởi động → gửi tin OFFLINE ngay lập tức → chờ lệnh
  2. /on  → Mở manager.py → khi manager đã UP thì check_ping.py tự tắt
  3. manager.py nhận /kill → tắt, viết flag RESPAWN → check_ping.py tự khởi động lại
  4. /off (gửi khi check_ping đang chạy) → tắt check_ping.py luôn (tất cả đều tắt)

LƯU Ý:
  - Khi manager.py đang chạy, check_ping.py KHÔNG tồn tại (đã tự tắt)
  - Khi manager.py tắt (/kill), manager viết file RESPAWN_FLAG → check_ping bắt lên
  - check_ping được start_linux.sh / start_windows.bat khởi động lại qua vòng lặp shell
  - /terminal, /setrdpass, /run hoptodesk và HopToDesk/ZeroTier được xử lý bởi manager.py khi online
  - /languages <ngôn_ngữ> dịch toàn bộ phần CHÚ THÍCH/MÔ TẢ sang ngôn ngữ khác qua Gemini AI.
    Tên lệnh (/on, /off, /kill...) KHÔNG BAO GIỜ bị dịch, luôn giữ nguyên.
"""

import os, sys, time, subprocess, platform, ctypes, socket, threading, json, re
import requests

# ══════════════════════════════════════════════════════
# CẤU HÌNH
# ══════════════════════════════════════════════════════
TOKEN   = ""
CHAT_ID = ""

# Key Gemini dùng để dịch lệnh /languages — PHẢI là Google AI Studio key,
# bắt đầu bằng "AIza...". Lấy miễn phí tại: https://aistudio.google.com/app/apikey
# (key kiểu "AQ.xxx" là key Vertex AI/OAuth, KHÔNG dùng được ở đây và sẽ luôn báo lỗi)
GEMINI_API_KEY = ""

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
FILE_TIME     = os.path.join(BASE_DIR, "time.txt")          # heartbeat của manager
RESPAWN_FLAG  = os.path.join(BASE_DIR, "respawn.flag")      # manager viết khi /kill
FILE_PASSWORD = os.path.join(BASE_DIR, ".sudo_pass")
FILE_LANG     = os.path.join(BASE_DIR, "lang_config.json")  # ngôn ngữ hiện tại (dùng chung manager.py)

IS_WINDOWS = platform.system() == "Windows"

state = {
    "last_update_id": 0,
    "sudo_password": "",
}

# ══════════════════════════════════════════════════════
# NGÔN NGỮ (mặc định English — /languages <tên> để đổi, lưu lại qua restart)
# ══════════════════════════════════════════════════════
DEFAULT_LANG = "english"

def load_current_lang() -> str:
    """Đọc ngôn ngữ hiện tại từ file dùng chung với manager.py."""
    try:
        if os.path.exists(FILE_LANG):
            with open(FILE_LANG, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("current_lang", DEFAULT_LANG)
    except Exception:
        pass
    return DEFAULT_LANG

def save_current_lang(lang: str) -> None:
    try:
        data = {}
        if os.path.exists(FILE_LANG):
            try:
                with open(FILE_LANG, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["current_lang"] = lang
        with open(FILE_LANG, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

CURRENT_LANG = load_current_lang()

# ══════════════════════════════════════════════════════
# CHUỖI VĂN BẢN (key → text). Tên lệnh /on /off /kill... GIỮ NGUYÊN trong mọi bản dịch.
# STRINGS_VI = bản gốc tiếng Việt. STRINGS_EN = bản Anh viết sẵn tay (mặc định, không cần Gemini).
# Ngôn ngữ khác /languages <tên> sẽ dịch STRINGS_VI qua Gemini và cache lại.
# ══════════════════════════════════════════════════════
STRINGS_VI = {
    "offline_menu": (
        "🔴 *HỆ THỐNG ĐANG TẮT*\n"
        "══════════════════════\n"
        "Các lệnh khả dụng:\n"
        "  /on                  — Mở manager.py\n"
        "  /off                 — Tắt watchdog (toàn bộ tắt)\n"
        "  /testpass <mật_khẩu> — Cấp quyền Sudo (Linux)\n"
        "  /languages <ngôn_ngữ> — Đổi ngôn ngữ hiển thị\n"
        "══════════════════════\n"
        "💡 Gõ /on để bắt đầu.\n"
        "_(Khi online: /terminal, /id, /run hoptodesk, /network... khả dụng qua manager)_"
    ),
    "testpass_saved_win": "✅ [Watchdog] Đã lưu mật khẩu.",
    "testpass_ok": "✅ [Watchdog] Mật khẩu đúng! Đã mở khoá quyền Sudo và lưu lại.",
    "testpass_wrong": "❌ [Watchdog] Mật khẩu sudo không đúng. Thử lại.",
    "on_starting": "🔄 Đang khởi động manager.py... Vui lòng đợi.",
    "on_start_failed": "❌ Không thể khởi động manager.py. Kiểm tra log hệ thống.",
    "on_waiting_heartbeat": "⏳ Đã gửi lệnh khởi chạy. Đang chờ heartbeat xác nhận (tối đa 30s)...",
    "on_success": (
        "✅ *MANAGER.PY ĐÃ ONLINE!*\n"
        "Hệ thống đang hoạt động đầy đủ.\n"
        "Gõ /huongdan để xem danh sách lệnh.\n"
        "_(Watchdog đã tự tắt, sẽ tự khởi động lại nếu manager tắt)_"
    ),
    "on_timeout": "❌ Không nhận được heartbeat sau 30s. manager.py có thể bị lỗi khi khởi động.",
    "off_triggered": (
        "🛑 *Lệnh /off được kích hoạt!*\n"
        "Đang tắt toàn bộ hệ thống...\n"
        "_(Cả watchdog và manager đều sẽ dừng)_"
    ),
    "off_done": "✅ Đã tắt hoàn toàn. Gõ /on để bật lại khi cần.",
    "terminal_offline": (
        "⚠️ *Hệ thống đang OFFLINE*\n"
        "Lệnh `/terminal` chỉ khả dụng khi manager đang chạy.\n"
        "Gõ `/on` để khởi động manager, rồi dùng `/terminal` để xem thông tin kết nối."
    ),
    "setrdpass_offline": (
        "⚠️ *Hệ thống đang OFFLINE*\n"
        "Lệnh `/setrdpass` chỉ khả dụng khi manager đang chạy.\n"
        "Gõ `/on` để khởi động manager, rồi dùng `/setrdpass <mật_khẩu>`."
    ),
    "invalid_cmd_offline": (
        "❌ Lệnh `{typed_cmd}` không hợp lệ khi hệ thống OFFLINE.\n"
        "══════════════════════\n"
        "Chỉ được dùng 1 trong các lệnh sau:\n"
        "  /on                  — Mở manager.py\n"
        "  /off                 — Tắt watchdog (toàn bộ tắt)\n"
        "  /testpass <mật_khẩu> — Cấp quyền Sudo (Linux)\n"
        "  /languages <ngôn_ngữ> — Đổi ngôn ngữ hiển thị\n"
        "══════════════════════\n"
        "💡 Gõ /on để bắt đầu."
    ),
    "uac_required": (
        "⚠️ *[Watchdog - Windows] Yêu cầu quyền Administrator!*\n"
        "Đang gọi UAC. Vui lòng bấm 'Yes' trên màn hình máy."
    ),
    "languages_usage": (
        "🌐 Đổi ngôn ngữ hiển thị của watchdog.\n"
        "Cú pháp: /languages <tên_ngôn_ngữ>\n"
        "Ví dụ: /languages english | /languages japanese | /languages vietnamese\n"
        f"Ngôn ngữ hiện tại: *{{current}}*\n"
        "⚠️ Lưu ý: Tên lệnh (/on, /off, /kill...) KHÔNG đổi, chỉ phần mô tả/chú thích đổi."
    ),
    "languages_no_key": (
        "❌ Chưa cấu hình GEMINI_API_KEY trong check_ping.py / manager.py nên không thể dịch "
        "sang ngôn ngữ khác Tiếng Việt/English.\n"
        "💡 Lấy key miễn phí tại: https://aistudio.google.com/app/apikey "
        "(key phải bắt đầu bằng \"AIza...\")."
    ),
    "languages_translating": "🔄 Đang dịch toàn bộ hệ thống sang *{lang}*... (lần đầu có thể mất ít phút)",
    "languages_done": "✅ Đã đổi ngôn ngữ hiển thị sang *{lang}*. Cài đặt này sẽ được giữ qua các lần khởi động lại.",
}

STRINGS_EN = {
    "offline_menu": (
        "🔴 *SYSTEM IS OFF*\n"
        "══════════════════════\n"
        "Available commands:\n"
        "  /on                  — Start manager.py\n"
        "  /off                 — Shut down watchdog (everything off)\n"
        "  /testpass <password> — Grant Sudo permission (Linux)\n"
        "  /languages <language> — Change display language\n"
        "══════════════════════\n"
        "💡 Type /on to get started.\n"
        "_(When online: /terminal, /id, /run hoptodesk, /network... available via manager)_"
    ),
    "testpass_saved_win": "✅ [Watchdog] Password saved.",
    "testpass_ok": "✅ [Watchdog] Password correct! Sudo access unlocked and saved.",
    "testpass_wrong": "❌ [Watchdog] Wrong sudo password. Try again.",
    "on_starting": "🔄 Starting manager.py... Please wait.",
    "on_start_failed": "❌ Could not start manager.py. Check system logs.",
    "on_waiting_heartbeat": "⏳ Launch command sent. Waiting for heartbeat confirmation (up to 30s)...",
    "on_success": (
        "✅ *MANAGER.PY IS ONLINE!*\n"
        "The system is fully operational.\n"
        "Type /huongdan to see the command list.\n"
        "_(Watchdog has shut itself down, it will auto-restart if manager stops)_"
    ),
    "on_timeout": "❌ No heartbeat received after 30s. manager.py may have failed to start.",
    "off_triggered": (
        "🛑 *The /off command was triggered!*\n"
        "Shutting down the entire system...\n"
        "_(Both watchdog and manager will stop)_"
    ),
    "off_done": "✅ Fully shut down. Type /on to turn it back on when needed.",
    "terminal_offline": (
        "⚠️ *System is OFFLINE*\n"
        "The `/terminal` command is only available while manager is running.\n"
        "Type `/on` to start manager, then use `/terminal` to view connection info."
    ),
    "setrdpass_offline": (
        "⚠️ *System is OFFLINE*\n"
        "The `/setrdpass` command is only available while manager is running.\n"
        "Type `/on` to start manager, then use `/setrdpass <password>`."
    ),
    "invalid_cmd_offline": (
        "❌ Command `{typed_cmd}` is invalid while the system is OFFLINE.\n"
        "══════════════════════\n"
        "You can only use one of the following commands:\n"
        "  /on                  — Start manager.py\n"
        "  /off                 — Shut down watchdog (everything off)\n"
        "  /testpass <password> — Grant Sudo permission (Linux)\n"
        "  /languages <language> — Change display language\n"
        "══════════════════════\n"
        "💡 Type /on to get started."
    ),
    "uac_required": (
        "⚠️ *[Watchdog - Windows] Administrator privileges required!*\n"
        "Calling UAC. Please click 'Yes' on the computer screen."
    ),
    "languages_usage": (
        "🌐 Change the watchdog's display language.\n"
        "Usage: /languages <language_name>\n"
        "Example: /languages english | /languages japanese | /languages vietnamese\n"
        f"Current language: *{{current}}*\n"
        "⚠️ Note: Command names (/on, /off, /kill...) NEVER change, only descriptions/notes do."
    ),
    "languages_no_key": (
        "❌ GEMINI_API_KEY is not configured in check_ping.py / manager.py, so translation "
        "to languages other than Vietnamese/English is not possible.\n"
        "💡 Get a free key at: https://aistudio.google.com/app/apikey "
        "(key must start with \"AIza...\")."
    ),
    "languages_translating": "🔄 Translating the entire system to *{lang}*... (first time may take a few minutes)",
    "languages_done": "✅ Display language changed to *{lang}*. This setting will persist across restarts.",
}

# ══════════════════════════════════════════════════════
# DỊCH NGÔN NGỮ QUA GEMINI (chỉ dịch CHÚ THÍCH, KHÔNG đụng tên lệnh)
# ══════════════════════════════════════════════════════
def _gemini_translate(text_vi: str, target_lang: str) -> str:
    """
    Dịch một khối text tiếng Việt sang target_lang qua Gemini.
    Giữ nguyên mọi token bắt đầu bằng "/" (tên lệnh) không dịch.
    Trả về text gốc nếu lỗi (an toàn, không bao giờ làm vỡ bot).
    """
    if not GEMINI_API_KEY:
        return text_vi
    try:
        prompt = (
            f"Translate the following text into {target_lang}. "
            f"This is a Telegram bot menu. "
            f"CRITICAL RULES:\n"
            f"1. NEVER translate or modify any token starting with '/' (e.g. /on, /off, /testpass) — keep them EXACTLY as-is, including their argument placeholders like <password>.\n"
            f"2. Keep all emoji, markdown symbols (*, _, `), and line breaks exactly in place.\n"
            f"3. Keep the overall structure/formatting identical, only translate the natural language words.\n"
            f"4. Return ONLY the translated text, no explanation, no markdown code fences.\n\n"
            f"Text to translate:\n{text_vi}"
        )
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
        }
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code != 200:
            print(f"[lang] ❌ Gemini HTTP {res.status_code}: {res.text[:150]}")
            return text_vi
        data = res.json()
        if "error" in data:
            print(f"[lang] ❌ Gemini error: {data['error'].get('message','')[:150]}")
            return text_vi
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        translated = " ".join(p.get("text", "") for p in parts if "text" in p).strip()
        return translated if translated else text_vi
    except Exception as e:
        print(f"[lang] ❌ Lỗi dịch: {e}")
        return text_vi

def t(key: str, **kwargs) -> str:
    """
    Lấy chuỗi text theo key.
    - 'vietnamese' → dùng STRINGS_VI (gốc)
    - 'english'    → dùng STRINGS_EN (đã dịch sẵn tay, KHÔNG gọi Gemini — đảm bảo
                      luôn nhanh kể cả khi chưa cấu hình GEMINI_API_KEY)
    - ngôn ngữ khác → dịch qua Gemini, có cache vào file để không dịch lại mỗi lần
    kwargs dùng để .format() các biến runtime (vd: t("kill_msg", code=0)).
    """
    base_text = STRINGS_VI.get(key, key)
    lang_l = CURRENT_LANG.lower()

    if lang_l in ("vietnamese", "vi", "tiếng việt", "tieng viet"):
        text = base_text
    elif lang_l in ("english", "en"):
        text = STRINGS_EN.get(key, base_text)
    else:
        cache = _load_translation_cache()
        lang_cache = cache.get(lang_l, {})
        if key in lang_cache:
            text = lang_cache[key]
        else:
            text = _gemini_translate(base_text, CURRENT_LANG)
            lang_cache[key] = text
            cache[lang_l] = lang_cache
            _save_translation_cache(cache)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:
        return text

FILE_LANG_CACHE = os.path.join(BASE_DIR, "lang_cache_checkping.json")

def _load_translation_cache() -> dict:
    try:
        if os.path.exists(FILE_LANG_CACHE):
            with open(FILE_LANG_CACHE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

def _save_translation_cache(cache: dict) -> None:
    try:
        with open(FILE_LANG_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ══════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════
def send_msg(text: str, retries: int = 3) -> None:
    for attempt in range(retries):
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            return
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)

def sync_offset() -> None:
    """Đồng bộ offset để bỏ qua các tin cũ."""
    try:
        res = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1",
            timeout=8,
        ).json()
        if res.get("result"):
            state["last_update_id"] = res["result"][-1]["update_id"]
    except Exception:
        pass

def poll_once(timeout_sec: int = 20):
    """Long-poll một lần, trả về list message text nhận được."""
    try:
        url = (
            f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            f"?offset={state['last_update_id'] + 1}&limit=10&timeout={timeout_sec}"
        )
        res = requests.get(url, timeout=timeout_sec + 5).json()
        messages = []
        for upd in res.get("result", []):
            state["last_update_id"] = upd["update_id"]
            message = upd.get("message", {})
            text    = message.get("text", "").strip()
            cid     = str(message.get("chat", {}).get("id", ""))
            if text and cid == CHAT_ID:
                messages.append(text)
        return messages
    except Exception:
        return []

# ══════════════════════════════════════════════════════
# QUYỀN & MẬT KHẨU
# ══════════════════════════════════════════════════════
def load_saved_password() -> str:
    try:
        if os.path.exists(FILE_PASSWORD):
            with open(FILE_PASSWORD, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""

def save_password(pw: str) -> bool:
    try:
        with open(FILE_PASSWORD, "w") as f:
            f.write(pw)
        try:
            os.chmod(FILE_PASSWORD, 0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False

def _sudo_run(cmd_list):
    pw = state["sudo_password"] or load_saved_password()
    try:
        full = ["sudo", "-S"] + cmd_list if pw else ["sudo"] + cmd_list
        proc = subprocess.Popen(
            full, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True
        )
        out, err = proc.communicate(input=pw + "\n" if pw else None, timeout=10)
        return proc.returncode, out + err
    except Exception as e:
        return 1, str(e)

def test_sudo_password(password: str) -> bool:
    try:
        proc = subprocess.Popen(
            ["sudo", "-S", "true"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        proc.communicate(input=password + "\n", timeout=5)
        return proc.returncode == 0
    except Exception:
        return False

# ══════════════════════════════════════════════════════
# TIẾN TRÌNH
# ══════════════════════════════════════════════════════
def kill_manager():
    """Tắt manager.py nếu đang chạy."""
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["powershell", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%manager.py%'\" "
                 "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            _sudo_run(["pkill", "-f", "manager.py"])
    except Exception:
        pass

def start_manager() -> bool:
    """Khởi động manager.py dưới quyền phù hợp."""
    try:
        kill_manager()
        time.sleep(1.2)
        for f in [FILE_TIME, RESPAWN_FLAG]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

        python_bin = sys.executable
        if IS_WINDOWS:
            subprocess.Popen(
                [python_bin, os.path.join(BASE_DIR, "manager.py")],
                cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            pw = state["sudo_password"] or load_saved_password()
            if pw:
                proc = subprocess.Popen(
                    ["sudo", "-S", python_bin, os.path.join(BASE_DIR, "manager.py")],
                    cwd=BASE_DIR, stdin=subprocess.PIPE, text=True
                )
                proc.stdin.write(pw + "\n")
                proc.stdin.flush()
                proc.stdin.close()
            else:
                subprocess.Popen(
                    ["sudo", python_bin, os.path.join(BASE_DIR, "manager.py")],
                    cwd=BASE_DIR
                )
        return True
    except Exception as e:
        print(f"[watchdog] ❌ Lỗi start manager: {e}")
        return False

def manager_is_alive() -> bool:
    """Kiểm tra heartbeat của manager (time.txt cập nhật trong 20s)."""
    try:
        if not os.path.exists(FILE_TIME):
            return False
        last_time = float(open(FILE_TIME).read().strip())
        return (time.time() - last_time) <= 20
    except Exception:
        return False

# ══════════════════════════════════════════════════════
# XỬ LÝ LỆNH TELEGRAM (khi check_ping đang chạy)
# ══════════════════════════════════════════════════════
def get_offline_menu() -> str:
    return t("offline_menu")

def handle_command(text: str) -> bool:
    """
    Xử lý lệnh Telegram khi check_ping.py đang ở trạng thái chờ.
    Trả về True nếu cần thoát check_ping (đã mở manager thành công).
    """
    global CURRENT_LANG
    cmd = text.strip().lower()

    # ── /testpass ────────────────────────────────────────────────
    if text.lower().startswith("/testpass "):
        pw = text.split(" ", 1)[1].strip()
        if IS_WINDOWS:
            save_password(pw)
            send_msg(t("testpass_saved_win"))
        else:
            if test_sudo_password(pw):
                state["sudo_password"] = pw
                save_password(pw)
                send_msg(t("testpass_ok"))
            else:
                send_msg(t("testpass_wrong"))
        return False

    # ── /languages ───────────────────────────────────────────────
    elif cmd == "/languages" or cmd.startswith("/languages "):
        parts_lang = text.split(maxsplit=1)
        if len(parts_lang) == 1:
            send_msg(t("languages_usage", current=CURRENT_LANG))
            return False
        new_lang = parts_lang[1].strip()
        if not GEMINI_API_KEY and new_lang.lower() not in ("english", "en", "vietnamese", "vi", "tiếng việt", "tieng viet"):
            send_msg(t("languages_no_key"))
            return False
        send_msg(t("languages_translating", lang=new_lang))
        CURRENT_LANG = new_lang
        save_current_lang(new_lang)
        # Báo trễ tin nhắn done bằng ngôn ngữ MỚI (sau khi đã đổi CURRENT_LANG)
        send_msg(t("languages_done", lang=new_lang))
        return False

    # ── /on ──────────────────────────────────────────────────────
    elif cmd == "/on":
        send_msg(t("on_starting"))
        if not start_manager():
            send_msg(t("on_start_failed"))
            return False

        send_msg(t("on_waiting_heartbeat"))
        for _ in range(30):
            time.sleep(1)
            if manager_is_alive():
                send_msg(t("on_success"))
                print(f"[watchdog] ✅ Manager UP. Tự tắt check_ping. | {time.strftime('%H:%M:%S')}")
                return True  # → thoát check_ping

        send_msg(t("on_timeout"))
        return False

    # ── /off ─────────────────────────────────────────────────────
    elif cmd == "/off":
        send_msg(t("off_triggered"))
        kill_manager()
        try:
            if os.path.exists(RESPAWN_FLAG):
                os.remove(RESPAWN_FLAG)
        except Exception:
            pass
        try:
            open(os.path.join(BASE_DIR, "stop.flag"), "w").close()
        except Exception:
            pass
        send_msg(t("off_done"))
        print(f"[watchdog] 🛑 /off — Tắt hoàn toàn. | {time.strftime('%H:%M:%S')}")
        sys.exit(0)

    # ── /terminal khi offline ────────────────────────────────────
    elif cmd == "/terminal":
        send_msg(t("terminal_offline"))
        return False

    # ── /setrdpass khi offline ────────────────────────────────────
    elif text.lower().startswith("/setrdpass"):
        send_msg(t("setrdpass_offline"))
        return False

    # ── Lệnh không hợp lệ ────────────────────────────────────────
    elif cmd.startswith("/"):
        typed_cmd = cmd.split()[0]
        send_msg(t("invalid_cmd_offline", typed_cmd=typed_cmd))
        return False

    return False

# ══════════════════════════════════════════════════════
# KIỂM TRA QUYỀN KHI KHỞI ĐỘNG
# ══════════════════════════════════════════════════════
def check_and_setup_permissions():
    print("[watchdog] 🔍 Kiểm tra quyền hệ thống...")
    if IS_WINDOWS:
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            is_admin = False
        if not is_admin:
            send_msg(t("uac_required"))
            time.sleep(2)
            try:
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, " ".join(sys.argv), None, 1
                )
            except Exception as e:
                print(f"[watchdog] ❌ Lỗi UAC: {e}")
            sys.exit(0)
        else:
            print("[watchdog] ✅ Quyền Administrator OK (Windows).")
    else:
        # Trên Linux: Chỉ nạp mật khẩu cũ nếu có, không chặn vòng lặp bắt nhập mật khẩu nữa
        saved_pw = load_saved_password()
        if saved_pw:
            state["sudo_password"] = saved_pw
        print("[watchdog] ✅ Bỏ qua kiểm tra Sudo (Linux hoạt động bình thường).")

# ══════════════════════════════════════════════════════
# CHỜ MẠNG SẴN SÀNG (quan trọng khi máy vừa khởi động/boot)
# ══════════════════════════════════════════════════════
def wait_for_network(max_wait_sec: int = 60) -> bool:
    """
    Đợi mạng/Telegram API sẵn sàng, tối đa max_wait_sec giây.
    Trả về True nếu mạng OK, False nếu hết thời gian.
    Cần thiết vì máy mới boot xong thường chưa có mạng ngay (đặc biệt Windows
    khi script tự chạy qua Task Scheduler/Startup folder trước khi adapter mạng lên).
    """
    waited = 0
    interval = 2
    while waited < max_wait_sec:
        try:
            requests.get("https://api.telegram.org", timeout=3)
            return True
        except Exception:
            time.sleep(interval)
            waited += interval
    return False

# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    stop_flag = os.path.join(BASE_DIR, "stop.flag")
    if os.path.exists(stop_flag):
        try:
            os.remove(stop_flag)
        except Exception:
            pass
        print("[watchdog] stop.flag tìm thấy — thoát không restart.")
        sys.exit(0)

    print(f"[watchdog] 🔴 Khởi động... đang kiểm tra mạng | {time.strftime('%H:%M:%S')}")
    if not wait_for_network(max_wait_sec=60):
        print("[watchdog] ⚠️ Mạng vẫn chưa sẵn sàng sau 60s, vẫn thử gửi tin (có thể fail, retry sẽ tự lo).")

    # ── GỬI TIN OFFLINE NGAY LẬP TỨC — ưu tiên cao nhất, KHÔNG để bất cứ thứ gì
    #    (UAC, sudo check, xoá file flag...) làm chậm việc báo cho người dùng biết. ──
    send_msg(get_offline_menu())
    print(f"[watchdog] 🔴 Đã gửi tin OFFLINE. Đang chờ lệnh /on... | {time.strftime('%H:%M:%S')}")

    sync_offset()
    check_and_setup_permissions()

    # Xóa heartbeat cũ khi watchdog khởi động
    for f in [FILE_TIME, RESPAWN_FLAG]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception:
            pass

    # ── VÒNG LẶP CHỜ LỆNH ────────────────────────────────────────
    while True:
        try:
            messages = poll_once(timeout_sec=20)
            for text in messages:
                should_exit = handle_command(text)
                if should_exit:
                    sys.exit(0)
        except KeyboardInterrupt:
            print("[watchdog] Dừng bởi người dùng (Ctrl+C).")
            sys.exit(0)
        except Exception as e:
            print(f"[watchdog] Lỗi vòng lặp: {e}")
            time.sleep(2)
