import psutil
import requests
import time
import os
import subprocess
import json
import shutil
import ctypes
import platform
import re
import calendar
import threading
import socket
from datetime import datetime, timedelta
from collections import OrderedDict

def start_heartbeat():
    """Luồng chạy ngầm: cập nhật time.txt mỗi 20 giây."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_time = os.path.join(base_dir, "time.txt")
    
    def heartbeat_loop():
        while True:
            try:
                with open(file_time, "w") as f:
                    f.write(str(time.time()))
            except Exception as e:
                print(f"[manager] Lỗi ghi time.txt: {e}")
            time.sleep(10)  # 10s: đủ buffer dù watchdog poll 20s/vòng

    # Khởi tạo thread Daemon (tự động tắt khi manager.py tắt)
    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()
    print("[manager] Đã khởi động luồng Heartbeat (20s/lần).")

# Gọi hàm này khi bắt đầu chạy manager.py
start_heartbeat()

# --- 1. CẤU HÌNH ---
TOKEN = ""
CHAT_ID = ""

IS_WINDOWS = platform.system() == 'Windows'

if IS_WINDOWS:
    HOPTODESK_PATH = shutil.which("hoptodesk") or r"C:\Program Files\HopToDesk\HopToDesk.exe"
    DISK_PATH = 'C:'
else:
    HOPTODESK_PATH = shutil.which("hoptodesk") or "/usr/bin/hoptodesk"
    DISK_PATH = '/'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_TAI_CHINH = os.path.join(BASE_DIR, "finance_logs.json")
FILE_TRUY_CAP = os.path.join(BASE_DIR, "access_logs.txt")
FILE_IP_HISTORY = os.path.join(BASE_DIR, "ip_history.json")
FILE_CHART = os.path.join(BASE_DIR, "chart.png")
FILE_ENERGY_TOTAL = os.path.join(BASE_DIR, "energy_total.json")
FILE_HW_CACHE = os.path.join(BASE_DIR, "hw_cache.json")
FILE_EVN_CACHE = os.path.join(BASE_DIR, "evn_price_cache.json")
FILE_HEARTBEAT = os.path.join(BASE_DIR, "heartbeat.json")

# Thông số hệ thống cơ bản & Web Scraping
HW_SPECS = {
    "cpu_name": "Unknown", "cpu_tdp": 65,
    "ram_type": "Unknown", "ram_gb": 8, "ram_w_per_gb": 0.35,
    "disk_type": "Unknown", "disk_w": 5,
    "usb_count": 0, "usb_w": 2.5,
    "mb_w": 25
}

# Giá EVN chính thức gần nhất theo nguồn EVN/Bộ Công Thương
EVN_TIERS = [1984, 2050, 2380, 2998, 3350, 3460]
EVN_AVERAGE_PRICE = 2204.0655
EVN_PRICE_SOURCE = "EVN / QĐ 1279/QĐ-BCT ngày 09/05/năm nay"
EVN_LAST_UPDATE_TEXT = "Chưa cập nhật"
EVN_LAST_SUCCESS_UNIX = 0
ELECTRICITY_COUNTRY = "Việt Nam"   # Quốc gia dùng để tra giá điện (đổi bằng /change_national_electricity)

WATT_WARNING = 80
CRITICAL_WATT = 110

# ── GEMINI API (tùy chọn) — dùng để tra giá điện EVN qua AI và cho /languages ──
# ⚠️ QUAN TRỌNG: Đây PHẢI là Google AI Studio API key.
#    Lấy MIỄN PHÍ tại: https://aistudio.google.com/app/apikey
#    Lưu ý (từ 19/06/2026): Google đã đổi key mặc định từ dạng cũ "AIzaSy..." (Standard key)
#    sang dạng mới "AQ...." (Auth key). Key "AQ." mới này KHÔNG còn là Vertex AI OAuth token
#    như trước nữa — nó hoạt động bình thường với generativelanguage.googleapis.com qua
#    ?key=... y hệt key "AIza" cũ. Key "AIza" cũ vẫn dùng được nhưng sẽ ngừng hoạt động
#    hoàn toàn từ 09/2026, nên ưu tiên dùng key "AQ." mới khi tạo lại.
GEMINI_API_KEY = ""

def _gemini_key_looks_valid(key: str) -> bool:
    """Kiểm tra nhanh format key — không đảm bảo key còn hạn/đúng quyền, chỉ chặn lỗi sai định dạng rõ ràng.
    Chấp nhận cả 2 dạng: "AIza..." (Standard key, cũ) và "AQ...." (Auth key, mới từ 06/2026)."""
    if not key:
        return False
    if key.startswith("AQ."):
        return len(key) >= 20  # Auth key mới — hợp lệ
    if key.startswith("AIza"):
        return len(key) >= 30  # Standard key cũ — vẫn hợp lệ (đến trước 09/2026)
    return False

GEMINI_KEY_VALID = _gemini_key_looks_valid(GEMINI_API_KEY)
if GEMINI_API_KEY and not GEMINI_KEY_VALID:
    print(
        "[manager] ⚠️ CẢNH BÁO: GEMINI_API_KEY có vẻ SAI ĐỊNH DẠNG "
        f"(key hiện tại bắt đầu bằng '{GEMINI_API_KEY[:6]}...'). "
        "Key Google AI Studio hợp lệ phải bắt đầu bằng 'AIza' (cũ) hoặc 'AQ.' (mới, từ 06/2026). "
        "Mọi tính năng dùng Gemini (/capnhatgia, /languages) sẽ KHÔNG hoạt động cho đến khi sửa key đúng. "
        "Lấy key miễn phí tại: https://aistudio.google.com/app/apikey"
    )

# ── RAPL (đọc công suất CPU thực - Linux Intel/AMD) ──
_rapl_state = {"path": None, "energy": 0, "t": 0.0, "power_w": None}

POWER_PLANS = {
    "high": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "low": "a1841308-3541-4fab-bc81-f71556f20b4a"
}

last_update_id = 0
active_ips_global = set()
last_energy_tick = time.monotonic()  # FIX: biến global cho process_finance

# --- MẬT KHẨU LƯU FILE ---
FILE_PASSWORD = os.path.join(BASE_DIR, ".sudo_pass")  # file lưu mật khẩu

def load_saved_password():
    """Đọc mật khẩu đã lưu từ file. Trả về chuỗi rỗng nếu chưa có."""
    try:
        if os.path.exists(FILE_PASSWORD):
            with open(FILE_PASSWORD, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except:
        pass
    return ""

def save_password(pw):
    """Lưu mật khẩu vào file, giới hạn quyền đọc chỉ owner."""
    try:
        with open(FILE_PASSWORD, 'w', encoding='utf-8') as f:
            f.write(pw)
        try:
            os.chmod(FILE_PASSWORD, 0o600)
        except:
            pass
        return True
    except:
        return False

_pending_action = None

# Cấu hình Wake-on-LAN (để bật máy từ xa bằng /start)
WOL_MAC = "00:00:00:00:00:00"   # <-- Thay bằng MAC address của máy bạn
WOL_BROADCAST = "255.255.255.255"
WOL_PORT = 9

# --- 2. HÀM TIỆN ÍCH FILE ---
def ensure_json_file(path, default_obj):
    try:
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(default_obj, f, ensure_ascii=False, indent=2)
    except:
        pass


def load_json_safe(path, default_obj):
    ensure_json_file(path, default_obj)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if data is None:
                return default_obj.copy() if isinstance(default_obj, dict) else default_obj
            return data
    except:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(default_obj, f, ensure_ascii=False, indent=2)
        except:
            pass
        return default_obj.copy() if isinstance(default_obj, dict) else default_obj


def save_json_safe(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


def format_vnd(value):
    try:
        v = float(value)
        if v < 1:
            return f"{v:.4f} VNĐ"
        return f"{v:,.0f} VNĐ"
    except:
        return "0 VNĐ"


def get_total_finance_all_time():
    try:
        data = ram_cache["finance"]
    except NameError:
        data = load_json_safe(FILE_TAI_CHINH, {})
    total = 0.0
    for v in data.values():
        try:
            total += float(v)
        except:
            pass
    return total


def get_total_finance_by_month(month_num):
    data = load_json_safe(FILE_TAI_CHINH, {})
    try:
        month_num = int(month_num)
        if month_num < 1 or month_num > 12:
            return 0.0
    except:
        return 0.0

    year_now = datetime.now().year
    prefix = f"{year_now}-{month_num:02d}"
    total = 0.0
    for k, v in data.items():
        try:
            if str(k).startswith(prefix):
                total += float(v)
        except:
            pass
    return total


def get_total_kwh_all_time():
    data = load_json_safe(FILE_ENERGY_TOTAL, {})
    total = 0.0
    for v in data.values():
        try:
            total += float(v)
        except:
            pass
    return total


def get_total_kwh_month():
    try:
        data = ram_cache["energy_total"]
    except NameError:
        data = load_json_safe(FILE_ENERGY_TOTAL, {})
    now_month = datetime.now().strftime("%Y-%m")
    return float(data.get(now_month, 0.0))


def safe_float(v, default=0.0):
    try:
        return float(v)
    except:
        return default


# --- 3. CẬP NHẬT GIÁ ĐIỆN TỪ WEB ---
def load_evn_cache_if_any():
    global EVN_TIERS, EVN_AVERAGE_PRICE, EVN_PRICE_SOURCE, EVN_LAST_UPDATE_TEXT, EVN_LAST_SUCCESS_UNIX, ELECTRICITY_COUNTRY
    cache = load_json_safe(FILE_EVN_CACHE, {})
    if isinstance(cache, dict) and cache:
        tiers = cache.get("tiers")
        if isinstance(tiers, list) and len(tiers) >= 6:
            EVN_TIERS = tiers[:6]
        EVN_AVERAGE_PRICE    = safe_float(cache.get("average_price"), EVN_AVERAGE_PRICE)
        EVN_PRICE_SOURCE     = cache.get("source", EVN_PRICE_SOURCE)
        EVN_LAST_UPDATE_TEXT = cache.get("updated_at", EVN_LAST_UPDATE_TEXT)
        EVN_LAST_SUCCESS_UNIX = int(cache.get("updated_unix", 0) or 0)
        if cache.get("country"):
            ELECTRICITY_COUNTRY = cache["country"]


_gemini_last_call = 0.0          # timestamp lần gọi cuối
_GEMINI_MIN_INTERVAL = 4.0       # giây tối thiểu giữa 2 lần gọi

def _gemini_post(prompt_text, use_search=False, max_tokens=1024):
    """
    Gọi Gemini 3.1 Flash-Lite qua generateContent API.
    - Tự throttle: tối thiểu 4s giữa mỗi request.
    - KHÔNG retry: nếu lỗi (kể cả 429 rate-limit) thì báo lỗi ngay, không chờ/lặp lại.
    - use_search=True → bật Google Search grounding.
    """
    global _gemini_last_call

    if not GEMINI_API_KEY:
        return None, "Chưa cấu hình GEMINI_API_KEY"
    if not GEMINI_KEY_VALID:
        return None, (
            "GEMINI_API_KEY sai định dạng (phải bắt đầu bằng 'AIza' hoặc 'AQ.', lấy tại "
            "https://aistudio.google.com/app/apikey)."
        )

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-3.1-flash-lite:generateContent?key={GEMINI_API_KEY}")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens},
    }
    if use_search:
        payload["tools"] = [{"google_search": {}}]

    # Throttle: đảm bảo không gọi quá nhanh
    now = time.time()
    wait = _GEMINI_MIN_INTERVAL - (now - _gemini_last_call)
    if wait > 0:
        time.sleep(wait)

    try:
        _gemini_last_call = time.time()
        res = requests.post(url, json=payload, timeout=35)

        if res.status_code == 429:
            return None, "Gemini bị rate-limit (HTTP 429). Thử lại sau."

        if res.status_code in (400, 401, 403):
            err_detail = res.text[:200]
            if "API_KEY_INVALID" in err_detail or "API key not valid" in err_detail:
                return None, f"API key Gemini không hợp lệ (HTTP {res.status_code}). Kiểm tra lại GEMINI_API_KEY."
            return None, f"HTTP {res.status_code}: {err_detail}"

        if res.status_code != 200:
            return None, f"HTTP {res.status_code}: {res.text[:200]}"

        data = res.json()

        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))
            return None, f"Gemini API error: {err_msg}"

        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in parts if "text" in p).strip()
        if not text:
            return None, "Gemini trả về nội dung rỗng"
        return text, None

    except requests.exceptions.Timeout:
        return None, "Gemini timeout"
    except Exception as e:
        return None, str(e)


# ══════════════════════════════════════════════════════
# NGÔN NGỮ (mặc định English — /languages <tên> để đổi, lưu lại qua restart)
# Dùng CHUNG file lang_config.json với check_ping.py để giữ nhất quán.
# CHỈ dịch phần CHÚ THÍCH/MÔ TẢ. Tên lệnh (/on, /off, /kill, /huongdan, /capnhatgia...)
# KHÔNG BAO GIỜ bị dịch trong bất kỳ trường hợp nào.
# ══════════════════════════════════════════════════════
FILE_LANG = os.path.join(BASE_DIR, "lang_config.json")
DEFAULT_LANG = "english"

def load_current_lang() -> str:
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

FILE_LANG_CACHE = os.path.join(BASE_DIR, "lang_cache_manager.json")

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

def _gemini_translate(text_vi: str, target_lang: str) -> str:
    """
    Dịch một khối text tiếng Việt sang target_lang qua Gemini.
    Giữ nguyên mọi token bắt đầu bằng "/" (tên lệnh) không dịch.
    Trả về text gốc nếu lỗi (an toàn, không bao giờ làm vỡ bot).
    """
    if not GEMINI_API_KEY or not GEMINI_KEY_VALID:
        return text_vi
    prompt = (
        f"Translate the following text into {target_lang}. "
        f"This is a Telegram bot help menu. "
        f"CRITICAL RULES:\n"
        f"1. NEVER translate or modify any token starting with '/' (e.g. /on, /off, /kill, /huongdan, /capnhatgia, /change_national_electricity) — keep them EXACTLY as-is, including argument placeholders like <N>, <pw>, [tên].\n"
        f"2. Keep all emoji, markdown symbols (*, _, `), line breaks, and the box-drawing separator lines (══, ──) exactly in place.\n"
        f"3. Keep the overall structure/formatting identical, only translate the natural language words/descriptions.\n"
        f"4. Keep any {{placeholder}} (curly braces) tokens EXACTLY as-is, do not translate or remove them.\n"
        f"5. Return ONLY the translated text, no explanation, no markdown code fences.\n\n"
        f"Text to translate:\n{text_vi}"
    )
    text, err = _gemini_post(prompt, use_search=False, max_tokens=2048)
    if err or not text:
        print(f"[lang] ❌ Lỗi dịch: {err}")
        return text_vi
    return text

def t(key: str, **kwargs) -> str:
    """
    Lấy chuỗi text theo key.
    - 'vietnamese' → STRINGS_VI (gốc)
    - 'english'    → STRINGS_EN (dịch sẵn tay, KHÔNG cần Gemini — luôn nhanh, là mặc định)
    - ngôn ngữ khác → nếu đã dịch & cache rồi thì lấy luôn (nhanh);
                       nếu CHƯA cache thì trả bản tiếng Anh NGAY (không block lệnh Telegram),
                       đồng thời dịch ngầm ở thread riêng rồi lưu cache cho lần gọi sau.
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
            # KHÔNG gọi Gemini đồng bộ ở đây nữa (gây treo lệnh Telegram 4-35s).
            # Trả bản tiếng Anh ngay, dịch nền + cache để lần sau có ngay.
            text = STRINGS_EN.get(key, base_text)
            threading.Thread(
                target=_translate_and_cache_bg,
                args=(key, base_text, CURRENT_LANG),
                daemon=True,
            ).start()
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:
        return text


def _translate_and_cache_bg(key: str, base_text: str, lang: str) -> None:
    """Dịch 1 key qua Gemini ở thread nền rồi lưu vào cache — không block lệnh nào cả."""
    try:
        translated = _gemini_translate(base_text, lang)
        cache = _load_translation_cache()
        lang_l = lang.lower()
        lang_cache = cache.get(lang_l, {})
        lang_cache[key] = translated
        cache[lang_l] = lang_cache
        _save_translation_cache(cache)
    except Exception as e:
        print(f"[lang-bg] Lỗi dịch nền '{key}': {e}")

# ── Chuỗi văn bản: key → text. STRINGS_VI = gốc, STRINGS_EN = bản Anh viết sẵn tay. ──
STRINGS_VI = {
    "huongdan": (
        "📋 BẢNG HƯỚNG DẪN LỆNH\n"
        "══════════════════════\n"
        "🖥️ HỆ THỐNG\n"
        "  /check       — Kiểm tra script còn sống\n"
        "  /ping        — Đo độ trễ mạng\n"
        "  /temperature — Xem nhiệt độ CPU/GPU\n"
        "  /hardware    — Thông số chi tiết + wattage thực\n"
        "  /storage     — Dung lượng ổ cứng\n"
        "  /trash       — Dọn file rác hệ thống\n"
        "  /live        — Reset bảng live monitor\n"
        "──────────────────────\n"
        "⚡ ĐIỆN NĂNG\n"
        "  /tongdien            — Tổng kWh & tiền điện\n"
        "  /tiendienthang <N>   — Tiền điện tháng N (hoặc all)\n"
        "  /change_national_electricity [tên] — Xem/đổi quốc gia tra giá điện\n"
        "  /capnhatgia          — Cập nhật giá điện (Gemini AI)\n"
        "  /list day|week|month|year|all — Biểu đồ tiền điện\n"
        "──────────────────────\n"
        "🔋 NGUỒN ĐIỆN / CPU\n"
        "  /power low|balanced|high   — Đổi chế độ nguồn\n"
        "  /safe energy on|off        — Tự bảo vệ khi quá tải [{safe_status}]\n"
        "──────────────────────\n"
        "🌐 KẾT NỐI & REMOTE\n"
        "  /terminal                 — Thông tin SSH + HopToDesk + ZeroTier\n"
        "  /id                       — Xem HopToDesk ID\n"
        "  /run hoptodesk            — Khởi động HopToDesk\n"
        "  /stop hoptodesk           — Dừng hoàn toàn HopToDesk\n"
        "  /setrdpass <pw>           — Đặt mật khẩu HopToDesk\n"
        "  /setrdssh <pw>            — Đặt mật khẩu Windows để SSH/Termius (chỉ Windows)\n"
        "  /install ssh              — Cài/bật SSH server + in lệnh kết nối\n"
        "  /install hoptodesk        — Tự động cài HopToDesk (Linux)\n"
        "  /unistall hoptodesk       — Gỡ cài đặt HopToDesk\n"
        "  /ip                       — Lịch sử IP kết nối\n"
        "  /install zerotier         — Cài ZeroTier VPN tự động\n"
        "  /unistall zerotier        — Gỡ cài đặt ZeroTier\n"
        "  /network <id>             — Tham gia mạng ZeroTier\n"
        "  /unnetwork <id>           — Rời mạng ZeroTier\n"
        "  /networklist             — Xem danh sách mạng ZeroTier\n"
        "  /start                    — Gửi Wake-on-LAN bật máy từ xa\n"
        "  /languages <ngôn_ngữ>     — Đổi ngôn ngữ hiển thị (chỉ chú thích, không đổi tên lệnh)\n"
        "──────────────────────\n"
        "🔴 LỆNH NGUY HIỂM\n"
        "  /shutdown — Tắt máy\n"
        "  /restart  — Khởi động lại\n"
        "  /sleep    — Ngủ đông\n"
        "  /kill     — Dừng script (flush dữ liệu trước, watchdog sẽ tự khởi động lại)\n"
        "  /testpass <pass> — Cấp/kiểm tra quyền sudo (Linux)\n"
        "══════════════════════\n"
        "💡 Gõ /huongdan để xem lại bảng này.\n"
        "⚠️ /shutdown /restart /sleep cần /testpass trước (Linux)."
    ),
    "cmd_not_found": "❓ Lệnh '{cmd}' không tồn tại.\n👉 Gõ /huongdan để xem danh sách lệnh hợp lệ.",
    "kill_saving": "🛑 Đang lưu dữ liệu và tắt script...",
    "kill_offline_msg": (
        "🔴 *MANAGER ĐÃ TẮT — HỆ THỐNG OFFLINE*\n"
        "Dữ liệu đã được lưu an toàn.\n"
        "_(Watchdog sẽ tự khởi động lại trong vài giây và gửi bảng lệnh OFFLINE)_"
    ),
    "languages_usage": (
        "🌐 Đổi ngôn ngữ hiển thị (CHỈ phần chú thích/mô tả — tên lệnh KHÔNG đổi).\n"
        "Cú pháp: /languages <tên_ngôn_ngữ>\n"
        "Ví dụ: /languages english | /languages japanese | /languages vietnamese\n"
        "Ngôn ngữ hiện tại: *{current}*"
    ),
    "languages_no_key": (
        "❌ Chưa cấu hình đúng GEMINI_API_KEY (key phải bắt đầu bằng \"AIza...\" hoặc \"AQ.\") nên không thể "
        "dịch sang ngôn ngữ khác Tiếng Việt/English.\n"
        "💡 Lấy key miễn phí tại: https://aistudio.google.com/app/apikey"
    ),
    "languages_translating": "🔄 Đang dịch toàn bộ hệ thống sang *{lang}*... (lần đầu có thể mất ít phút do phải dịch nhiều khối lệnh)",
    "languages_done": "✅ Đã đổi ngôn ngữ hiển thị sang *{lang}*. Cài đặt này sẽ được giữ qua các lần /kill và khởi động lại.",
}

STRINGS_EN = {
    "huongdan": (
        "📋 COMMAND GUIDE\n"
        "══════════════════════\n"
        "🖥️ SYSTEM\n"
        "  /check       — Check if script is alive\n"
        "  /ping        — Measure network latency\n"
        "  /temperature — View CPU/GPU temperature\n"
        "  /hardware    — Detailed specs + real wattage\n"
        "  /storage     — Disk space usage\n"
        "  /trash       — Clean up system junk files\n"
        "  /live        — Reset the live monitor board\n"
        "──────────────────────\n"
        "⚡ ELECTRICITY\n"
        "  /tongdien            — Total kWh & electricity cost\n"
        "  /tiendienthang <N>   — Electricity cost for month N (or all)\n"
        "  /change_national_electricity [name] — View/change country for electricity pricing\n"
        "  /capnhatgia          — Update electricity prices (Gemini AI)\n"
        "  /list day|week|month|year|all — Electricity cost chart\n"
        "──────────────────────\n"
        "🔋 POWER / CPU\n"
        "  /power low|balanced|high   — Change power plan\n"
        "  /safe energy on|off        — Auto-protect on overload [{safe_status}]\n"
        "──────────────────────\n"
        "🌐 CONNECTION & REMOTE\n"
        "  /terminal                 — SSH + HopToDesk + ZeroTier info\n"
        "  /id                       — View HopToDesk ID\n"
        "  /run hoptodesk            — Start HopToDesk\n"
        "  /stop hoptodesk           — Fully stop HopToDesk\n"
        "  /setrdpass <pw>           — Set HopToDesk password\n"
        "  /setrdssh <pw>            — Set Windows password for SSH/Termius (Windows only)\n"
        "  /install ssh              — Install/enable SSH server + print connection command\n"
        "  /install hoptodesk        — Auto-install HopToDesk (Linux)\n"
        "  /unistall hoptodesk       — Uninstall HopToDesk\n"
        "  /ip                       — Connection IP history\n"
        "  /install zerotier         — Auto-install ZeroTier VPN\n"
        "  /unistall zerotier        — Uninstall ZeroTier\n"
        "  /network <id>             — Join a ZeroTier network\n"
        "  /unnetwork <id>           — Leave a ZeroTier network\n"
        "  /networklist             — View ZeroTier network list\n"
        "  /start                    — Send Wake-on-LAN to power on remotely\n"
        "  /languages <language>     — Change display language (notes only, command names stay the same)\n"
        "──────────────────────\n"
        "🔴 DANGEROUS COMMANDS\n"
        "  /shutdown — Shut down the machine\n"
        "  /restart  — Restart the machine\n"
        "  /sleep    — Sleep mode\n"
        "  /kill     — Stop the script (flushes data first, watchdog will auto-restart)\n"
        "  /testpass <pass> — Grant/check sudo permission (Linux)\n"
        "══════════════════════\n"
        "💡 Type /huongdan to view this table again.\n"
        "⚠️ /shutdown /restart /sleep require /testpass first (Linux)."
    ),
    "cmd_not_found": "❓ Command '{cmd}' does not exist.\n👉 Type /huongdan to see the list of valid commands.",
    "kill_saving": "🛑 Saving data and shutting down the script...",
    "kill_offline_msg": (
        "🔴 *MANAGER HAS STOPPED — SYSTEM OFFLINE*\n"
        "Data has been safely saved.\n"
        "_(Watchdog will auto-restart in a few seconds and send the OFFLINE command menu)_"
    ),
    "languages_usage": (
        "🌐 Change the display language (ONLY notes/descriptions — command names never change).\n"
        "Usage: /languages <language_name>\n"
        "Example: /languages english | /languages japanese | /languages vietnamese\n"
        "Current language: *{current}*"
    ),
    "languages_no_key": (
        "❌ GEMINI_API_KEY is not correctly configured (key must start with \"AIza...\" or \"AQ.\"), so "
        "translation to languages other than Vietnamese/English is not possible.\n"
        "💡 Get a free key at: https://aistudio.google.com/app/apikey"
    ),
    "languages_translating": "🔄 Translating the entire system to *{lang}*... (first time may take a few minutes due to the amount of command blocks)",
    "languages_done": "✅ Display language changed to *{lang}*. This setting will persist across /kill and restarts.",
}


def _update_evn_via_gemini(country: str):
    """
    2 bước:
      Bước 1 – Gemini + Google Search tìm thông tin thô về giá điện quốc gia.
      Bước 2 – Gemini parse thông tin thô đó thành JSON chuẩn (không dùng search,
                dùng response_mime_type để ép JSON thuần).
    """
    if not GEMINI_API_KEY:
        return None, "Chưa cấu hình GEMINI_API_KEY"
    try:
        # ── Bước 1: tìm thông tin thô ─────────────────────────────
        search_prompt = (
            f"Search for the latest residential electricity tariff / price tiers in {country} (năm nay). "
            f"Find: number of price tiers, price per kWh for each tier (in local currency, excluding VAT), "
            f"average price, official source/regulation name, and effective date. "
            f"Provide as much raw detail as possible."
        )
        raw_info, err = _gemini_post(search_prompt, use_search=True, max_tokens=1024)
        if err or not raw_info:
            return None, f"Bước 1 thất bại: {err}"

        # ── Bước 2: parse thành JSON ───────────────────────────────
        parse_prompt = (
            f"Based on the following electricity price information for {country}:\n\n"
            f"{raw_info}\n\n"
            f"Extract and return ONLY a valid JSON object (no explanation, no markdown, no code fences):\n"
            f'{{"country":"{country}",'
            f'"currency":"ISO currency code or symbol",'
            f'"tiers":[price_tier1, price_tier2, ...],'
            f'"tier_ranges":["0-X kWh","X+1-Y kWh","..."],'
            f'"average_price":average_price_excl_vat,'
            f'"source":"regulation or official source name",'
            f'"effective_date":"DD/MM/YYYY or MM/YYYY or YYYY"}}\n'
            f"Rules:\n"
            f"- tiers: list of numbers (price per kWh in local currency, NO VAT)\n"
            f"- If only 1 flat rate exists, tiers=[that_rate], tier_ranges=['flat rate']\n"
            f"- average_price: weighted average or flat rate if no tiers\n"
            f"- All values must be numbers, not strings\n"
            f"- Return ONLY the JSON, nothing else"
        )
        json_text, err = _gemini_post(parse_prompt, use_search=False, max_tokens=512)
        if err or not json_text:
            return None, f"Bước 2 thất bại: {err}"

        # Strip markdown fences nếu Gemini vẫn thêm vào
        json_text = re.sub(r'^```[a-z]*\s*|\s*```$', '', json_text.strip(), flags=re.MULTILINE).strip()

        d = json.loads(json_text)
        tiers = [float(x) for x in d.get("tiers", [])]
        if not tiers:
            return None, f"Không có dữ liệu tiers: {json_text[:200]}"

        return {
            "country":        d.get("country", country),
            "currency":       d.get("currency", "?"),
            "tiers":          tiers,
            "tier_ranges":    d.get("tier_ranges", []),
            "average_price":  float(d.get("average_price", tiers[0])),
            "source":         d.get("source", "Gemini/Google Search"),
            "effective_date": d.get("effective_date", ""),
            "raw_info":       raw_info,
        }, None

    except json.JSONDecodeError as e:
        return None, f"JSON parse lỗi: {e} | text: {json_text[:300]}"
    except Exception as e:
        return None, str(e)


def _parse_evn_html_prices(html):
    """Trích giá điện từ HTML EVN (6 bậc tăng dần, đơn vị đồng/kWh)."""
    raw = re.findall(r'\b(\d{1,2}[.,]\d{3})\b', html)
    candidates = []
    for r in raw:
        v = int(r.replace('.', '').replace(',', ''))
        if 1200 <= v <= 8000:
            candidates.append(v)
    seen, result = set(), []
    for v in candidates:
        if v not in seen:
            seen.add(v); result.append(v)
        if len(result) == 6:
            break
    if len(result) == 6 and all(result[i] < result[i+1] for i in range(5)):
        return result
    return None


def update_evn_prices_from_web(force=False):
    """
    Cập nhật giá điện theo thứ tự ưu tiên:
      1. Gemini AI + Google Search (2 bước: search → parse JSON)
      2. Parse HTML trang EVN chính thức (chỉ khi country == Việt Nam)
      3. Giữ giá hardcode (QĐ 1279/2025) làm fallback cuối (chỉ Việt Nam)
    """
    global EVN_TIERS, EVN_AVERAGE_PRICE, EVN_PRICE_SOURCE, EVN_LAST_UPDATE_TEXT, EVN_LAST_SUCCESS_UNIX

    country = ELECTRICITY_COUNTRY

    def _save_and_return(method_tag, msg):
        save_json_safe(FILE_EVN_CACHE, {
            "country": country,
            "tiers": EVN_TIERS, "average_price": EVN_AVERAGE_PRICE,
            "source": EVN_PRICE_SOURCE, "updated_at": EVN_LAST_UPDATE_TEXT,
            "updated_unix": EVN_LAST_SUCCESS_UNIX, "method": method_tag
        })
        return msg

    # ── 1. Gemini AI (2 bước) ─────────────────────────────────────
    if GEMINI_API_KEY:
        gd, gerr = _update_evn_via_gemini(country)
        if gd:
            tiers = gd["tiers"]
            EVN_TIERS             = [round(t) for t in tiers]
            EVN_AVERAGE_PRICE     = round(gd["average_price"], 4)
            EVN_PRICE_SOURCE      = gd["source"]
            EVN_LAST_UPDATE_TEXT  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            EVN_LAST_SUCCESS_UNIX = int(time.time())
            currency = gd.get("currency", "")
            ranges   = gd.get("tier_ranges", [])
            tier_str = " / ".join(
                f"{r}: {t:,.0f}" for r, t in zip(ranges, tiers)
            ) if ranges else " / ".join(f"{t:,.0f}" for t in tiers)
            eff_date = gd.get("effective_date", "")
            return _save_and_return("gemini",
                f"✅ Gemini AI cập nhật thành công!\n"
                f"🌍 Quốc gia: {gd.get('country', country)}\n"
                f"💱 Đơn vị: {currency}/kWh (chưa VAT)\n"
                f"📌 Bình quân: {EVN_AVERAGE_PRICE:,.4f} {currency}/kWh\n"
                f"⚡ Bậc giá: {tier_str}\n"
                f"🧾 Nguồn: {EVN_PRICE_SOURCE}"
                + (f"\n📅 Hiệu lực: {eff_date}" if eff_date else ""))
        print(f"[EVN Gemini] Lỗi: {gerr}")

    # ── 2. Parse HTML EVN (chỉ Việt Nam) ─────────────────────────
    if "việt nam" in country.lower() or "vietnam" in country.lower():
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        evn_urls = [
            "https://www.evn.com.vn/d6/news/Bieu-gia-ban-le-dien-sinh-hoat-tu-ngay-1152025-60-28-28538.html",
            "https://www.evn.com.vn/d/vi-VN/news/Bieu-gia-ban-le-dien-theo-Quyet-dinh-so-1279QD-BCT-ngay-0952025-cua-Bo-Cong-Thuong-60-28-502668",
        ]
        for url in evn_urls:
            try:
                res = requests.get(url, headers=headers, timeout=15)
                if res.status_code == 200:
                    parsed = _parse_evn_html_prices(res.text)
                    if parsed:
                        EVN_TIERS             = parsed
                        EVN_AVERAGE_PRICE     = round(
                            sum(parsed[i] * w for i, w in enumerate([50,50,100,100,100,9999])) / 10400, 4)
                        EVN_PRICE_SOURCE      = "EVN (parse HTML) năm nay"
                        EVN_LAST_UPDATE_TEXT  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        EVN_LAST_SUCCESS_UNIX = int(time.time())
                        return _save_and_return("html_parse",
                            f"✅ Parse HTML EVN thành công!\n"
                            f"📌 Bình quân ước tính: {EVN_AVERAGE_PRICE:,.4f} đ/kWh\n"
                            f"🏠 6 bậc: {' / '.join(f'{x:,}' for x in EVN_TIERS)} đ/kWh\n"
                            f"🧾 Nguồn: {EVN_PRICE_SOURCE}")
            except Exception as e:
                print(f"[EVN HTML] {url[:60]}: {e}")

        # ── 3. Fallback hardcode (chỉ Việt Nam) ──────────────────
        if EVN_LAST_SUCCESS_UNIX == 0:
            EVN_TIERS             = [1984, 2050, 2380, 2998, 3350, 3460]
            EVN_AVERAGE_PRICE     = 2204.0655
            EVN_PRICE_SOURCE      = "EVN / QĐ 1279/QĐ-BCT 09/05/2025 (hardcode)"
            EVN_LAST_UPDATE_TEXT  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            EVN_LAST_SUCCESS_UNIX = int(time.time())
            _save_and_return("hardcode", "")

    load_evn_cache_if_any()
    return (
        f"⚠️ Không kết nối được web, dùng giá điện cache gần nhất.\n"
        f"🌍 Quốc gia: {country}\n"
        f"📌 Bình quân: {EVN_AVERAGE_PRICE:,.4f}/kWh (chưa VAT)\n"
        f"🏠 Bậc: {' / '.join(f'{x:,}' for x in EVN_TIERS)}\n"
        f"🧾 Nguồn: {EVN_PRICE_SOURCE}\n"
        f"🕒 Cập nhật gần nhất: {EVN_LAST_UPDATE_TEXT}"
    )


# --- 4. THÔNG TIN PHẦN CỨNG CHI TIẾT ---

def _run_cmd(cmd, timeout=5, shell=True):
    """Chạy lệnh shell an toàn, trả về stdout string."""
    try:
        return subprocess.check_output(
            cmd, shell=shell, stderr=subprocess.DEVNULL,
            timeout=timeout
        ).decode(errors='ignore').strip()
    except Exception:
        return ""


def get_hardware_info():
    """Thu thập thông số phần cứng chi tiết từ nhiều nguồn."""
    info = {
        "cpu": "Unknown CPU", "ram_gb": 8, "disk": "SSD",
        "usb_count": 0,
        # Extended fields
        "cpu_cores_p": psutil.cpu_count(logical=False) or 1,
        "cpu_cores_l": psutil.cpu_count(logical=True) or 1,
        "cpu_freq_max_mhz": 0, "cpu_arch": platform.machine(),
        "ram_type": "Unknown", "ram_speed": "", "ram_slots": 0,
        "gpus": [],       # list of {"name", "vram_gb", "tdp_w", "type"}
        "disks_detail": [],  # list of {"name", "size", "model", "type"}
        "network_ifaces": [],
        "os_info": f"{platform.system()} {platform.release()}",
        "cpu_temp_c": None,
    }

    # ── CPU freq ──────────────────────────────────────────────────
    try:
        freq = psutil.cpu_freq()
        if freq:
            info["cpu_freq_max_mhz"] = round(freq.max or freq.current)
    except Exception:
        pass

    # ── CPU temp (Linux) ──────────────────────────────────────────
    try:
        temps = psutil.sensors_temperatures() or {}
        for sensor_name in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
            if sensor_name in temps and temps[sensor_name]:
                info["cpu_temp_c"] = round(temps[sensor_name][0].current, 1)
                break
    except Exception:
        pass

    if IS_WINDOWS:
        # ── CPU name ──────────────────────────────────────────────
        out = _run_cmd("wmic cpu get name /value")
        m = re.search(r'Name=(.+)', out)
        if m:
            info["cpu"] = m.group(1).strip()

        # ── RAM total + type ──────────────────────────────────────
        out = _run_cmd("wmic memorychip get Capacity,MemoryType,Speed /value")
        ram_bytes, slots = 0, 0
        for cap in re.findall(r'Capacity=(\d+)', out):
            ram_bytes += int(cap); slots += 1
        if ram_bytes:
            info["ram_gb"] = round(ram_bytes / (1024**3))
        info["ram_slots"] = slots
        type_map = {20:"DDR", 21:"DDR2", 24:"DDR3", 26:"DDR4", 34:"DDR5"}
        m = re.search(r'MemoryType=(\d+)', out)
        if m:
            info["ram_type"] = type_map.get(int(m.group(1)), f"Type{m.group(1)}")
        m = re.search(r'Speed=(\d+)', out)
        if m and int(m.group(1)) > 0:
            info["ram_speed"] = f"{m.group(1)}MHz"

        # ── Disk ──────────────────────────────────────────────────
        out = _run_cmd("wmic diskdrive get model,size,MediaType /value")
        models = re.findall(r'Model=(.+)', out)
        sizes  = re.findall(r'Size=(\d+)', out)
        mts    = re.findall(r'MediaType=(.+)', out)
        for i, model in enumerate(models):
            model = model.strip()
            size_gb = round(int(sizes[i]) / (1024**3)) if i < len(sizes) and sizes[i].isdigit() else 0
            mt = mts[i].strip() if i < len(mts) else ""
            disk_type = "HDD" if "Fixed" in mt or "hdd" in model.lower() else "SSD/NVMe"
            if "nvme" in model.lower() or "m.2" in model.lower():
                disk_type = "NVMe SSD"
            info["disks_detail"].append({
                "name": f"Disk{i}", "size": f"{size_gb}GB", "model": model[:40], "type": disk_type
            })
        info["disk"] = info["disks_detail"][0]["type"] if info["disks_detail"] else "SSD"

        # ── USB ───────────────────────────────────────────────────
        out = _run_cmd("wmic path Win32_USBControllerDevice get Dependent")
        info["usb_count"] = out.count("USB\\VID")

        # ── GPU ───────────────────────────────────────────────────
        out = _run_cmd("wmic path Win32_VideoController get name,AdapterRAM /value")
        names = re.findall(r'Name=(.+)', out)
        vrams = re.findall(r'AdapterRAM=(\d+)', out)
        for i, name in enumerate(names):
            name = name.strip()
            if not name or "Microsoft" in name:
                continue
            vram = round(int(vrams[i]) / (1024**3), 1) if i < len(vrams) and vrams[i].isdigit() else 0
            info["gpus"].append({"name": name[:50], "vram_gb": vram, "tdp_w": 0, "type": "GPU"})

    else:
        # ── CPU name (Linux) ─────────────────────────────────────
        out = _run_cmd("grep 'model name' /proc/cpuinfo | head -1")
        if ':' in out:
            info["cpu"] = out.split(':', 1)[1].strip()

        # ── RAM (Linux) ──────────────────────────────────────────
        info["ram_gb"] = round(psutil.virtual_memory().total / (1024**3))
        # Try dmidecode for DDR type and speed
        dmi = _run_cmd("dmidecode -t 17 2>/dev/null | grep -E 'Type:|Speed:|Number of Devices' | head -10", timeout=8)
        m = re.search(r'^\s*Type:\s*(DDR\d*)', dmi, re.M)
        if m:
            info["ram_type"] = m.group(1)
        m = re.search(r'Speed:\s*(\d+)\s*MT/s', dmi) or re.search(r'Speed:\s*(\d+)\s*MHz', dmi)
        if m:
            info["ram_speed"] = f"{m.group(1)}MHz"
        slots_m = re.search(r'Number of Devices:\s*(\d+)', dmi)
        if slots_m:
            info["ram_slots"] = int(slots_m.group(1))

        # ── Disks (Linux lsblk) ──────────────────────────────────
        out = _run_cmd("lsblk -d -o NAME,SIZE,ROTA,MODEL --noheadings 2>/dev/null")
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 2 or parts[0].startswith('loop'):
                continue
            name  = parts[0]
            size  = parts[1]
            rota  = parts[2] if len(parts) > 2 else '1'
            model = parts[3].strip() if len(parts) > 3 else 'Unknown'
            disk_type = "NVMe SSD" if name.startswith('nvme') else ("HDD" if rota == '1' else "SATA SSD")
            info["disks_detail"].append({"name": name, "size": size, "model": model[:40], "type": disk_type})
        info["disk"] = info["disks_detail"][0]["type"] if info["disks_detail"] else "SSD"

        # ── USB (Linux lsusb) ────────────────────────────────────
        out = _run_cmd("lsusb 2>/dev/null")
        info["usb_count"] = len([l for l in out.splitlines() if l.strip()])

        # ── GPU (Linux) ──────────────────────────────────────────
        out = _run_cmd("lspci 2>/dev/null | grep -E 'VGA|3D|Display'")
        for line in out.splitlines():
            if ':' in line:
                name = line.split(':', 2)[-1].strip()
                info["gpus"].append({"name": name[:60], "vram_gb": 0, "tdp_w": 0, "type": "GPU"})

    # ── NVIDIA GPU (cross-platform) ───────────────────────────────
    try:
        nv = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,power.limit",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        nv_gpus = []
        for line in nv.splitlines():
            p = [x.strip() for x in line.split(",")]
            nv_gpus.append({
                "name": p[0] if p else "NVIDIA GPU",
                "vram_gb": round(float(p[1]) / 1024, 1) if len(p) > 1 and p[1] not in ('N/A','') else 0,
                "tdp_w": round(float(p[2])) if len(p) > 2 and p[2] not in ('N/A','') else 0,
                "type": "NVIDIA"
            })
        if nv_gpus:
            info["gpus"] = nv_gpus  # nvidia-smi is more authoritative
    except Exception:
        pass

    # ── Network interfaces ────────────────────────────────────────
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == 2:  # AF_INET (IPv4)
                    info["network_ifaces"].append(f"{iface}({addr.address})")
                    break
    except Exception:
        pass

    return info


# ── RAPL — đo công suất CPU thực (Intel/AMD Linux) ───────────────
def _get_rapl_path():
    candidates = [
        "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj",
        "/sys/class/powercap/intel-rapl:0/energy_uj",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None

def get_rapl_power_w():
    """Đọc công suất CPU package từ RAPL; cache 2s. Trả về W hoặc None."""
    s = _rapl_state
    if s["path"] is None:
        s["path"] = _get_rapl_path() or ""
    if not s["path"]:
        return None
    try:
        with open(s["path"]) as f:
            energy_now = int(f.read())
        t_now = time.monotonic()
        if s["t"] > 0 and t_now - s["t"] >= 0.5:
            delta = energy_now - s["energy"]
            if delta < 0:
                delta += 2**32           # counter wrap
            s["power_w"] = round(delta / 1e6 / (t_now - s["t"]), 1)
        s["energy"] = energy_now
        s["t"] = t_now
        return s["power_w"]
    except Exception:
        return None


def get_gpu_realtime_w():
    """Đo công suất GPU thực từ nvidia-smi hoặc AMD sysfs. Trả về W hoặc None."""
    # NVIDIA
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        vals = [float(x) for x in out.splitlines() if x.strip() not in ("N/A", "")]
        if vals:
            return round(sum(vals), 1)
    except Exception:
        pass
    # AMD sysfs (Linux)
    if not IS_WINDOWS:
        try:
            import glob as _g
            power_files = _g.glob("/sys/class/hwmon/hwmon*/power1_average")
            total = sum(int(open(f).read()) / 1e6 for f in power_files)
            if total > 1:
                return round(total, 1)
        except Exception:
            pass
    return None


def fetch_hardware_power_specs():
    """Quét phần cứng chi tiết, tra TDP từ web/Gemini, cập nhật HW_SPECS."""
    global HW_SPECS
    hw = get_hardware_info()

    HW_SPECS["cpu_name"]    = hw["cpu"]
    HW_SPECS["ram_gb"]      = hw["ram_gb"]
    HW_SPECS["usb_count"]   = hw["usb_count"]
    HW_SPECS["disk_type"]   = hw["disk"]
    HW_SPECS["disk_w"]      = 9 if "HDD" in hw["disk"] else (3 if "NVMe" in hw["disk"] else 5)
    HW_SPECS["ram_type"]    = hw.get("ram_type", "Unknown")
    HW_SPECS["ram_speed"]   = hw.get("ram_speed", "")
    HW_SPECS["ram_w_per_gb"] = 0.375  # ~3W per 8GB DDR4/5

    # GPU
    gpus = hw.get("gpus", [])
    if gpus:
        HW_SPECS["gpu_name"]  = gpus[0]["name"]
        HW_SPECS["gpu_vram"]  = gpus[0].get("vram_gb", 0)
        HW_SPECS["gpu_tdp"]   = gpus[0].get("tdp_w", 0)
        HW_SPECS["gpu_count"] = len(gpus)
    else:
        HW_SPECS.setdefault("gpu_name", "Không phát hiện GPU rời")
        HW_SPECS.setdefault("gpu_tdp", 0)
        HW_SPECS.setdefault("gpu_count", 0)

    # Extended info
    HW_SPECS["cpu_cores_p"]        = hw.get("cpu_cores_p", 1)
    HW_SPECS["cpu_cores_l"]        = hw.get("cpu_cores_l", 1)
    HW_SPECS["cpu_freq_max_mhz"]   = hw.get("cpu_freq_max_mhz", 0)
    HW_SPECS["disks_detail"]       = hw.get("disks_detail", [])
    HW_SPECS["network_ifaces"]     = hw.get("network_ifaces", [])
    HW_SPECS["os_info"]            = hw.get("os_info", "")

    # ── TDP lookup: ưu tiên Gemini, fallback DuckDuckGo ──────────
    if HW_SPECS.get("gpu_tdp", 0) == 0 or HW_SPECS.get("cpu_tdp", 65) == 65:
        cpu_name = hw["cpu"]
        # Thử Gemini trước nếu có key
        if GEMINI_API_KEY:
            try:
                q = f"Cho tôi TDP (watt) của CPU {cpu_name}. Chỉ trả về 1 số nguyên."
                txt, gerr = _gemini_post(q, use_search=True, max_tokens=20)
                if txt and not gerr:
                    nums = re.findall(r'\b(\d{2,3})\b', txt)
                    valid = [int(n) for n in nums if 15 <= int(n) <= 400]
                    if valid:
                        HW_SPECS["cpu_tdp"] = valid[0]
            except Exception:
                pass

        # Fallback: DuckDuckGo HTML scrape
        if HW_SPECS.get("cpu_tdp", 65) == 65:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                q = requests.utils.quote(f"{cpu_name} TDP watts")
                res = requests.get(f"https://html.duckduckgo.com/html/?q={q}",
                                   headers=headers, timeout=10)
                matches = re.findall(r'\b(\d{2,3})\s*(?:W|Watt|Watts)\b', res.text, re.I)
                valid   = [int(m) for m in matches if 15 <= int(m) <= 400]
                if valid:
                    HW_SPECS["cpu_tdp"] = max(set(valid), key=valid.count)
            except Exception:
                pass

    save_json_safe(FILE_HW_CACHE, HW_SPECS)
    return f"✅ Quét phần cứng xong. CPU: {HW_SPECS['cpu_name']} (TDP: {HW_SPECS['cpu_tdp']}W)"


# --- 5. HÀM GỬI TELEGRAM ---
def send_telegram(message):
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
        print("SEND STATUS:", res.status_code)
        print("RESPONSE:", res.text)
    except Exception as e:
        print("SEND ERROR:", e)


def send_telegram_return_id(message):
    """Gửi message và trả về message_id để có thể edit sau."""
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=15
        )
        return res.json().get("result", {}).get("message_id")
    except:
        return None


def edit_telegram(message_id, message):
    """Chỉnh sửa message đã gửi — không tạo tin nhắn mới."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/editMessageText",
            data={"chat_id": CHAT_ID, "message_id": message_id, "text": message},
            timeout=15
        )
    except:
        pass


def send_telegram_photo(photo_path, caption=""):
    try:
        with open(photo_path, 'rb') as photo:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"photo": photo},
                timeout=30
            )
    except Exception as e:
        send_telegram(f"❌ Lỗi gửi ảnh: {e}")


def send_wol_packet(mac=None, broadcast=None, port=None):
    """Gửi Magic Packet Wake-on-LAN để bật máy từ xa."""
    import socket, struct
    mac = mac or WOL_MAC
    broadcast = broadcast or WOL_BROADCAST
    port = port or WOL_PORT
    mac_clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(mac_clean) != 12:
        return False, "MAC address không hợp lệ"
    try:
        mac_bytes = bytes.fromhex(mac_clean)
        magic = b'\xff' * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(magic, (broadcast, port))
        return True, "OK"
    except Exception as e:
        return False, str(e)


# --- 6. TIỆN ÍCH HỆ THỐNG ---
def prevent_sleep():
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000040)
        except:
            pass


def _set_linux_governor(governor):
    """
    Đặt CPU governor trên Linux.
    Thử theo thứ tự: sysfs trực tiếp → cpupower → cpufreq-set
    Trả về (True, tên_governor_thực_tế) hoặc (False, lý_do_lỗi)
    """
    import glob as _glob

    # Đọc danh sách governor khả dụng từ kernel
    available = []
    try:
        avail_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"
        with open(avail_path) as f:
            available = f.read().strip().split()
    except Exception:
        pass

    # "balanced" → ưu tiên schedutil (kernel mới) rồi mới ondemand
    if governor == "ondemand" and available:
        if "ondemand" not in available and "schedutil" in available:
            governor = "schedutil"
        elif "ondemand" not in available and "conservative" in available:
            governor = "conservative"

    if available and governor not in available:
        return False, (
            f"Governor '{governor}' không khả dụng trên kernel này.\n"
            f"Có sẵn: {', '.join(available)}"
        )

    # ── Cách 1: ghi thẳng vào sysfs (chạy tốt khi có quyền root) ──
    gov_paths = _glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor")
    if gov_paths:
        ok_count = 0
        for path in gov_paths:
            try:
                with open(path, "w") as f:
                    f.write(governor)
                ok_count += 1
            except Exception:
                pass
        if ok_count == len(gov_paths):
            return True, governor
        if ok_count > 0:
            return True, governor  # áp được một phần cũng tính OK

    # ── Cách 2: cpupower ──
    if shutil.which("cpupower"):
        rc = subprocess.run(
            ["cpupower", "frequency-set", "-g", governor],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        if rc == 0:
            return True, governor

    # ── Cách 3: cpufreq-set (từng core) ──
    if shutil.which("cpufreq-set"):
        cpu_count = os.cpu_count() or 1
        fails = 0
        for i in range(cpu_count):
            rc = subprocess.run(
                ["cpufreq-set", "-c", str(i), "-g", governor],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode
            if rc != 0:
                fails += 1
        if fails == 0:
            return True, governor

    # ── Không có cách nào ──
    return False, (
        "Không ghi được vào sysfs và không tìm thấy cpupower/cpufreq-set.\n"
        "💡 Thử: sudo apt install linux-tools-common  hoặc chạy script bằng sudo."
    )


def set_power_plan(mode):
    mode = (mode or "").strip().lower()
    if mode not in ("low", "balanced", "high"):
        return "❌ Chế độ không hợp lệ. Dùng: /power low | balanced | high"

    if IS_WINDOWS:
        try:
            subprocess.run(
                ["powercfg", "/setactive", POWER_PLANS[mode]],
                check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            labels = {"low": "Tiết kiệm điện", "balanced": "Cân bằng", "high": "Hiệu năng cao"}
            return f"✅ Windows: Đã chuyển sang [{labels[mode]}]."
        except Exception:
            return "❌ Windows: Không đổi được Power Plan (cần quyền Admin)."

    else:
        # Linux: map mode → governor
        gov_map = {
            "high":     "performance",
            "balanced": "ondemand",   # _set_linux_governor tự fallback sang schedutil nếu cần
            "low":      "powersave",
        }
        governor = gov_map[mode]
        ok, result = _set_linux_governor(governor)
        if ok:
            return (
                f"✅ Linux: CPU governor → [{result.upper()}]\n"
                f"   Chế độ: {mode.upper()}"
            )
        else:
            return f"❌ Linux: Không đặt được governor.\n{result}"


def clean_temp_files():
    temp_dirs = [os.environ.get('TEMP'), os.environ.get('TMP'), r'C:\Windows\Temp', r'C:\Windows\SoftwareDistribution\Download'] if IS_WINDOWS else ['/tmp', '/var/tmp', '/var/cache/apt/archives']
    deleted_size = 0
    for t_dir in set(filter(None, temp_dirs)):
        if os.path.exists(t_dir):
            for filename in os.listdir(t_dir):
                filepath = os.path.join(t_dir, filename)
                try:
                    if os.path.isfile(filepath) or os.path.islink(filepath):
                        deleted_size += os.path.getsize(filepath)
                        os.unlink(filepath)
                    elif os.path.isdir(filepath):
                        deleted_size += sum(os.path.getsize(os.path.join(d, f)) for d, _, files in os.walk(filepath) for f in files)
                        shutil.rmtree(filepath)
                except:
                    pass
    return round(deleted_size / (1024 * 1024), 2)


# --- 7. ĐIỆN NĂNG ---
def get_evn_tier_price(total_kwh_month):
    tiers = EVN_TIERS if isinstance(EVN_TIERS, list) and len(EVN_TIERS) >= 6 else [1984, 2050, 2380, 2998, 3350, 3460]
    if total_kwh_month <= 50:
        return tiers[0]
    elif total_kwh_month <= 100:
        return tiers[1]
    elif total_kwh_month <= 200:
        return tiers[2]
    elif total_kwh_month <= 300:
        return tiers[3]
    elif total_kwh_month <= 400:
        return tiers[4]
    else:
        return tiers[5]


def get_real_power_w(cpu_percent, ram_percent, disk_activity):
    """
    Tính công suất hệ thống. Ưu tiên đo thực (RAPL + GPU sensor),
    fallback về ước lượng dựa trên TDP khi sensor không khả dụng.
    """
    # ── CPU ───────────────────────────────────────────────────────
    rapl_w = get_rapl_power_w()
    if rapl_w is not None:
        cpu_w = rapl_w                       # Đo thực — chính xác nhất
    else:
        tdp = HW_SPECS.get("cpu_tdp", 65)
        cpu_w = max(tdp * 0.07, tdp * (cpu_percent / 100.0))

    # ── GPU ───────────────────────────────────────────────────────
    gpu_sensor_w = get_gpu_realtime_w()
    if gpu_sensor_w is not None:
        gpu_w = gpu_sensor_w
    else:
        gpu_tdp = HW_SPECS.get("gpu_tdp", 0)
        gpu_w   = gpu_tdp * 0.25 if gpu_tdp > 0 else 0   # ~25% tải nhẹ

    # ── RAM ───────────────────────────────────────────────────────
    ram_gb_used = (ram_percent / 100.0) * HW_SPECS.get("ram_gb", 8)
    ram_w = ram_gb_used * HW_SPECS.get("ram_w_per_gb", 0.375) + (HW_SPECS.get("ram_gb", 8) * 0.08)

    # ── Storage, USB, Mainboard ───────────────────────────────────
    disk_w = HW_SPECS.get("disk_w", 5) if disk_activity > 0 else 1.0
    usb_w  = HW_SPECS.get("usb_count", 0) * 0.5   # ~0.5W/thiết bị USB
    mb_w   = HW_SPECS.get("mb_w", 25)

    return round(cpu_w + gpu_w + ram_w + disk_w + usb_w + mb_w, 1)


def get_system_stats():
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent

    disk_io = psutil.disk_io_counters()
    disk_activity = 1 if disk_io else 0

    check_path = DISK_PATH if os.path.exists(DISK_PATH) else '/'
    disk_usage = psutil.disk_usage(check_path).percent

    net = psutil.net_io_counters()
    sent = round(net.bytes_sent / (1024 * 1024), 2) if net else 0
    recv = round(net.bytes_recv / (1024 * 1024), 2) if net else 0

    battery = psutil.sensors_battery() if hasattr(psutil, 'sensors_battery') else None
    is_plugged = battery.power_plugged if battery else True

    power_w = get_real_power_w(cpu, ram, disk_activity)
    return cpu, ram, disk_usage, sent, recv, power_w, is_plugged


def process_finance(power_w, is_plugged):
    global last_energy_tick, _dirty
    now = time.monotonic()
    elapsed = max(now - last_energy_tick, 0.001)
    last_energy_tick = now

    kwh_10s = (power_w / 1000) * (elapsed / 3600)
    now_month = datetime.now().strftime("%Y-%m")
    now_hour = datetime.now().strftime("%Y-%m-%d %H:00")

    # Cập nhật RAM cache — KHÔNG ghi đĩa mỗi giây
    current_month_kwh = safe_float(ram_cache["energy_total"].get(now_month, 0.0)) + kwh_10s
    ram_cache["energy_total"][now_month] = current_month_kwh

    current_tier_price = get_evn_tier_price(current_month_kwh)
    cost_10s = kwh_10s * current_tier_price

    ram_cache["finance"][now_hour] = safe_float(ram_cache["finance"].get(now_hour, 0.0)) + cost_10s

    _dirty = True
    return cost_10s


# --- 7b. TERMINAL / SSH ---

def _ssh_ensure_running() -> tuple:
    """
    Đảm bảo SSH server đang chạy. Nếu chưa có, tự cài và bật.
    Trả về (is_running: bool, port: int, note: str).
    """
    import shutil as _sh
    port = 22
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["powershell", "-Command",
                 "Get-Service -Name sshd -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status"],
                stderr=subprocess.DEVNULL, timeout=8
            ).decode(errors="ignore").strip()
            if "Running" in out:
                return True, port, "✅ SSH đang chạy"
            subprocess.run(
                ["powershell", "-Command",
                 "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue"],
                timeout=120, capture_output=True
            )
            subprocess.run(
                ["powershell", "-Command",
                 "Start-Service sshd; Set-Service -Name sshd -StartupType Automatic"],
                timeout=15, capture_output=True
            )
            out2 = subprocess.check_output(
                ["powershell", "-Command",
                 "Get-Service -Name sshd | Select-Object -ExpandProperty Status"],
                stderr=subprocess.DEVNULL, timeout=8
            ).decode(errors="ignore").strip()
            if "Running" in out2:
                return True, port, "✅ Đã cài và bật SSH tự động"
            return False, port, "❌ Không thể bật SSH tự động (thiếu quyền Admin?)"
        except Exception as e:
            return False, port, f"❌ Lỗi SSH: {e}"
    else:
        def _ssh_active():
            for svc in ("ssh", "sshd"):
                rc = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=4
                ).returncode
                if rc == 0:
                    return svc
            return None

        running_svc = _ssh_active()
        if running_svc:
            return True, port, "✅ SSH đang chạy"

        for svc in ("ssh", "sshd"):
            rc = subprocess.run(
                ["systemctl", "is-enabled", svc],
                capture_output=True, text=True, timeout=4
            ).returncode
            if rc == 0:
                _sudo_run_mgr(["systemctl", "enable", "--now", svc])
                if _ssh_active():
                    return True, port, "✅ Đã bật SSH (đã cài sẵn)"
                break

        pkg_mgr = _sh.which("apt-get") or _sh.which("apt")
        if pkg_mgr:
            send_telegram("⚙️ SSH chưa cài, đang tự cài openssh-server (30-60s)...")
            rc1, _ = _sudo_run_mgr(["apt-get", "install", "-y", "-q", "openssh-server"])
            _sudo_run_mgr(["systemctl", "enable", "--now", "ssh"])
            if _ssh_active():
                return True, port, "✅ Đã tự cài và bật SSH"
            return False, port, f"❌ Cài SSH xong nhưng không start được (code {rc1})"
        else:
            return False, port, "❌ Không tìm được apt-get. Tự cài: `sudo dnf install openssh-server -y && sudo systemctl enable --now sshd`"


def _sudo_run_mgr(cmd_list):
    """Chạy sudo với mật khẩu đã lưu (dùng trong manager)."""
    try:
        pw = load_saved_password()
        full = ["sudo", "-S"] + cmd_list if pw else ["sudo"] + cmd_list
        proc = subprocess.Popen(
            full, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True
        )
        out, err = proc.communicate(input=pw + "\n" if pw else None, timeout=15)
        return proc.returncode, out + err
    except Exception as e:
        return 1, str(e)



# ── HopToDesk & ZeroTier thay thế Tailscale/RustDesk ────────────────────────

# ── HopToDesk helpers ────────────────────────────────────────────────────────

def _find_hoptodesk_exe():
    """Tìm đường dẫn HopToDesk trên hệ thống (chống sót do case-sensitivity, PATH thiếu, hoặc path lạ)."""
    if HOPTODESK_PATH and os.path.isfile(HOPTODESK_PATH):
        return HOPTODESK_PATH

    # 1) Thử "which" với nhiều cách viết hoa/thường khác nhau
    for name in ("hoptodesk", "HopToDesk", "Hoptodesk", "HOPTODESK"):
        found = shutil.which(name)
        if found:
            return found

    if IS_WINDOWS:
        win_paths = [
            r"C:\Program Files\HopToDesk\HopToDesk.exe",
            r"C:\Program Files (x86)\HopToDesk\HopToDesk.exe",
            os.path.expanduser(r"~\AppData\Local\HopToDesk\HopToDesk.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\HopToDesk\HopToDesk.exe"),
            os.path.expandvars(r"%ProgramData%\HopToDesk\HopToDesk.exe"),
        ]
        for p in win_paths:
            if os.path.isfile(p):
                return p
        return None

    # 2) Hỏi trực tiếp dpkg xem package "hoptodesk" cài file binary vào đâu
    #    (đáng tin hơn việc đoán path cố định, vì version khác nhau có thể đặt path khác nhau)
    try:
        out = subprocess.run(
            ["dpkg", "-L", "hoptodesk"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                line = line.strip()
                if (line.endswith("/hoptodesk") or line.endswith("/HopToDesk")) and os.path.isfile(line) \
                        and os.access(line, os.X_OK):
                    return line
    except Exception:
        pass

    # 3) Quét các path/case phổ biến nhất trên Linux (kể cả AppImage, snap, flatpak)
    candidates = []
    for base in (
        "/usr/bin", "/usr/local/bin",
        "/usr/lib/hoptodesk", "/usr/lib/HopToDesk",
        "/opt/hoptodesk", "/opt/HopToDesk",
        "/opt/hoptodesk/bin", "/opt/HopToDesk/bin",
        "/var/lib/hoptodesk", "/var/lib/HopToDesk",
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/Applications"),
        os.path.expanduser("~/snap/bin"),
        # Flatpak export
        os.path.expanduser("~/.local/share/flatpak/exports/bin"),
        "/var/lib/flatpak/exports/bin",
    ):
        for name in ("hoptodesk", "HopToDesk", "Hoptodesk"):
            candidates.append(os.path.join(base, name))
    try:
        import glob as _glob
        candidates += _glob.glob(os.path.expanduser("~/**/HopToDesk*.AppImage"), recursive=True)
        candidates += _glob.glob(os.path.expanduser("~/**/hoptodesk*.AppImage"), recursive=True)
    except Exception:
        pass

    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    return None


def _is_hoptodesk_running():
    """Kiểm tra tiến trình hoptodesk đang chạy không."""
    for p in psutil.process_iter(['name']):
        try:
            if 'hoptodesk' in (p.info.get('name') or '').lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def _get_hoptodesk_id():
    """Lấy HopToDesk ID từ config file hoặc process."""
    config_paths = []
    if IS_WINDOWS:
        # Người dùng thường
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        windir = os.environ.get("WINDIR", r"C:\Windows")
        config_paths = [
            # User hiện tại (Roaming / Local)
            os.path.join(appdata,      r"HopToDesk\config\HopToDesk.toml"),
            os.path.join(appdata,      r"HopToDesk\HopToDesk.toml"),
            os.path.join(localappdata, r"HopToDesk\config\HopToDesk.toml"),
            os.path.join(localappdata, r"HopToDesk\HopToDesk.toml"),
            # ProgramData (system-wide)
            r"C:\ProgramData\HopToDesk\config\HopToDesk.toml",
            r"C:\ProgramData\HopToDesk\HopToDesk.toml",
            # Service account: LocalService (chạy dưới quyền service)
            os.path.join(windir, r"ServiceProfiles\LocalService\AppData\Roaming\HopToDesk\config\HopToDesk.toml"),
            os.path.join(windir, r"ServiceProfiles\LocalService\AppData\Roaming\HopToDesk\HopToDesk.toml"),
            # Service account: NetworkService
            os.path.join(windir, r"ServiceProfiles\NetworkService\AppData\Roaming\HopToDesk\config\HopToDesk.toml"),
            # SYSTEM account
            os.path.join(windir, r"system32\config\systemprofile\AppData\Roaming\HopToDesk\config\HopToDesk.toml"),
            os.path.join(windir, r"SysWOW64\config\systemprofile\AppData\Roaming\HopToDesk\config\HopToDesk.toml"),
            # Tìm theo expand user (backup)
            os.path.expanduser(r"~\AppData\Roaming\HopToDesk\config\HopToDesk.toml"),
            os.path.expanduser(r"~\AppData\Roaming\HopToDesk\HopToDesk.toml"),
            os.path.expanduser(r"~\AppData\Local\HopToDesk\config\HopToDesk.toml"),
        ]
    else:
        # Lấy home thực tế (kể cả khi chạy sudo)
        real_home = os.path.expanduser("~")
        # Nếu đang chạy sudo, cũng thử home của user gốc
        sudo_user = os.environ.get("SUDO_USER", "")
        sudo_home = f"/home/{sudo_user}" if sudo_user else ""

        config_paths = [
            # User hiện tại — thư mục config chuẩn (subdirectory config/)
            os.path.join(real_home, ".config/hoptodesk/config/HopToDesk.toml"),
            os.path.join(real_home, ".config/hoptodesk/HopToDesk.toml"),
            os.path.join(real_home, ".local/share/hoptodesk/config/HopToDesk.toml"),
            os.path.join(real_home, ".local/share/hoptodesk/HopToDesk.toml"),
            # Root (khi manager.py chạy bằng root/sudo)
            "/root/.config/hoptodesk/config/HopToDesk.toml",
            "/root/.config/hoptodesk/HopToDesk.toml",
            "/root/.local/share/hoptodesk/HopToDesk.toml",
            # System-wide
            "/etc/hoptodesk/HopToDesk.toml",
            "/var/lib/hoptodesk/config/HopToDesk.toml",
            "/var/lib/hoptodesk/HopToDesk.toml",
            # Snap
            os.path.join(real_home, "snap/hoptodesk/current/.config/hoptodesk/HopToDesk.toml"),
            # Flatpak
            os.path.join(real_home, ".var/app/com.hoptodesk.HopToDesk/config/hoptodesk/HopToDesk.toml"),
        ]
        # Thêm home của SUDO_USER nếu có
        if sudo_home:
            config_paths += [
                f"{sudo_home}/.config/hoptodesk/config/HopToDesk.toml",
                f"{sudo_home}/.config/hoptodesk/HopToDesk.toml",
                f"{sudo_home}/.local/share/hoptodesk/HopToDesk.toml",
            ]

    # ── Pass 1: Tìm key "id" (số thật) trong tất cả config paths ──
    for cfg in config_paths:
        if not cfg:
            continue
        try:
            if os.path.isfile(cfg):
                content = open(cfg, encoding="utf-8", errors="ignore").read()
                m = re.search(r'(?:^|\n)\s*id\s*=\s*["\']?(\d{6,12})["\']?', content, re.MULTILINE)
                if m:
                    return m.group(1).strip()
        except Exception:
            pass

    # ── Pass 2: Fallback glob trong /home và /root ──
    try:
        import glob as _glob
        for pattern in (
            "/home/*/.config/hoptodesk/*/HopToDesk.toml",
            "/home/*/.config/hoptodesk/HopToDesk.toml",
            "/home/*/.local/share/hoptodesk/HopToDesk.toml",
            "/root/.config/hoptodesk/*/HopToDesk.toml",
            "/root/.config/hoptodesk/HopToDesk.toml",
        ):
            for found in _glob.glob(pattern):
                try:
                    content = open(found, encoding="utf-8", errors="ignore").read()
                    m = re.search(r'(?:^|\n)\s*id\s*=\s*["\']?(\d{6,12})["\']?', content, re.MULTILINE)
                    if m:
                        return m.group(1).strip()
                except Exception:
                    pass
    except Exception:
        pass

    # ── Pass 3: Thử CLI --get-id (chính xác nhất) ──
    exe = _find_hoptodesk_exe()
    if exe:
        for flag in ("--get-id", "--id", "--getid"):
            try:
                out = subprocess.check_output(
                    [exe, flag], stderr=subprocess.DEVNULL, timeout=8
                ).decode(errors="ignore").strip()
                m = re.search(r'\b(\d{6,12})\b', out)
                if m:
                    return m.group(1)
            except Exception:
                pass

    # ── Pass 4: Nếu HopToDesk đang chạy, thử đọc từ /proc (Linux) ──
    if not IS_WINDOWS:
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'hoptodesk' in (proc.info.get('name') or '').lower():
                        # Thử đọc environ của process để lấy HOME, rồi tìm config
                        pid = proc.info['pid']
                        environ_path = f"/proc/{pid}/environ"
                        if os.path.isfile(environ_path):
                            env_data = open(environ_path, 'rb').read().decode(errors='ignore')
                            home_m = re.search(r'HOME=([^\x00]+)', env_data)
                            if home_m:
                                proc_home = home_m.group(1).strip()
                                for cfg_rel in (
                                    ".config/hoptodesk/config/HopToDesk.toml",
                                    ".config/hoptodesk/HopToDesk.toml",
                                ):
                                    cfg_p = os.path.join(proc_home, cfg_rel)
                                    if os.path.isfile(cfg_p):
                                        content = open(cfg_p, encoding="utf-8", errors="ignore").read()
                                        mm = re.search(r'(?:^|\n)\s*id\s*=\s*["\']?(\d{6,12})["\']?', content, re.MULTILINE)
                                        if mm:
                                            return mm.group(1).strip()
                except Exception:
                    pass
        except Exception:
            pass

    return "Chưa lấy được ID"


_hoptodesk_lock = threading.Lock()
_hoptodesk_starting = False
_hoptodesk_stopping = False


def hoptodesk_run():
    """Khởi động HopToDesk đúng 1 lần."""
    global _hoptodesk_starting
    with _hoptodesk_lock:
        if _hoptodesk_starting:
            send_telegram("⏳ HopToDesk đang trong quá trình khởi động, vui lòng chờ...")
            return
        if _is_hoptodesk_running():
            hid = _get_hoptodesk_id()
            send_telegram(f"ℹ️ HopToDesk đang chạy rồi.\n📍 ID: `{hid}`")
            return
        _hoptodesk_starting = True

    try:
        exe = _find_hoptodesk_exe()
        if not exe:
            send_telegram(
                "❌ Không tìm thấy HopToDesk trên máy!\n"
                "💡 Gõ /install hoptodesk để tự động cài đặt."
            )
            return

        send_telegram(f"🚀 Đang khởi động HopToDesk...")

        if IS_WINDOWS:
            subprocess.Popen(
                [exe],
                creationflags=subprocess.CREATE_NO_WINDOW,
                cwd=os.path.dirname(exe)
            )
        else:
            subprocess.Popen(
                [exe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        for _ in range(15):
            time.sleep(1)
            if _is_hoptodesk_running():
                time.sleep(2)
                hid = _get_hoptodesk_id()
                send_telegram(
                    f"✅ HopToDesk đã khởi động thành công!\n"
                    f"📍 ID: `{hid}`\n"
                    f"🔑 Dùng /setrdpass để đặt mật khẩu điều khiển."
                )
                return

        send_telegram(
            "⚠️ HopToDesk không khởi động được sau 15s.\n"
            "💡 Vui lòng thử lại /run hoptodesk hoặc kiểm tra logs."
        )
    except Exception as e:
        send_telegram(f"❌ Lỗi khởi động HopToDesk: {e}")
    finally:
        with _hoptodesk_lock:
            _hoptodesk_starting = False


def hoptodesk_stop():
    """Dừng hoàn toàn HopToDesk."""
    global _hoptodesk_stopping
    with _hoptodesk_lock:
        if _hoptodesk_stopping:
            send_telegram("⏳ HopToDesk đang trong quá trình dừng, vui lòng chờ...")
            return
        if not _is_hoptodesk_running():
            send_telegram("ℹ️ HopToDesk không đang chạy, không cần dừng.")
            return
        _hoptodesk_stopping = True

    try:
        send_telegram("🛑 Đang dừng HopToDesk...")
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/f", "/im", "HopToDesk.exe"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            subprocess.run(
                ["pkill", "-f", "hoptodesk"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

        for _ in range(8):
            time.sleep(1)
            if not _is_hoptodesk_running():
                send_telegram("✅ HopToDesk đã dừng hoàn toàn.")
                return

        send_telegram(
            "⚠️ HopToDesk chưa dừng hẳn sau 8s.\n"
            "💡 Thử lại /stop hoptodesk hoặc khởi động lại máy."
        )
    except Exception as e:
        send_telegram(f"❌ Lỗi dừng HopToDesk: {e}")
    finally:
        with _hoptodesk_lock:
            _hoptodesk_stopping = False


def hoptodesk_set_password(new_pass: str):
    """Đặt mật khẩu HopToDesk bằng CLI --password hoặc ghi config."""
    exe = _find_hoptodesk_exe()
    if not exe:
        send_telegram(
            "❌ Không tìm thấy HopToDesk!\n"
            "💡 Gõ /install hoptodesk để cài đặt."
        )
        return

    try:
        if IS_WINDOWS:
            result = subprocess.run(
                [exe, "--password", new_pass],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            result = subprocess.run(
                [exe, "--password", new_pass],
                capture_output=True, text=True, timeout=10
            )

        hid = _get_hoptodesk_id()
        if result.returncode == 0:
            send_telegram(
                f"✅ Đã đặt mật khẩu HopToDesk thành công!\n"
                f"📍 ID: `{hid}`\n"
                f"🔑 Mật khẩu: `{new_pass}`\n"
                f"⚠️ Lưu mật khẩu này lại để dùng khi kết nối từ xa."
            )
        else:
            send_telegram(
                f"⚠️ Lệnh đặt mật khẩu trả về code {result.returncode}.\n"
                f"Thử mở HopToDesk → Settings → đặt mật khẩu thủ công.\n"
                f"ID: `{hid}`"
            )
    except Exception as e:
        send_telegram(f"❌ Lỗi đặt mật khẩu HopToDesk: {e}")


def windows_set_account_password(new_pass: str):
    """
    Đặt/đổi mật khẩu đăng nhập của TÀI KHOẢN WINDOWS hiện tại.
    Dùng cho trường hợp SSH/Termius báo lỗi sai mật khẩu vì tài khoản
    Windows chưa từng có mật khẩu thật (chỉ dùng PIN/Windows Hello/auto-login).

    CHỈ chạy trên Windows. Cần quyền Admin (script đã tự nâng UAC lúc boot).

    ⚠️ CẢNH BÁO: Đây CHÍNH LÀ mật khẩu đăng nhập Windows lúc mở máy, không phải
    mật khẩu riêng của bot. Nếu tài khoản đang ở trạng thái "không mật khẩu",
    việc gán mật khẩu lần đầu qua lệnh admin (net user) — thay vì qua
    Settings > Sign-in options — có thể khiến dữ liệu mã hoá theo tài khoản cũ
    (Wi-Fi đã lưu, Credential Manager, mật khẩu lưu trong Chrome/Edge, file EFS...)
    không còn giải mã được. Cân nhắc trước khi dùng trên máy có dữ liệu quan trọng.
    """
    import getpass

    if not IS_WINDOWS:
        send_telegram("ℹ️ /setrdssh chỉ áp dụng cho Windows.")
        return

    username = getpass.getuser()

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False

    if not is_admin:
        send_telegram(
            "❌ Cần quyền Administrator để đổi mật khẩu Windows.\n"
            "💡 Script tự nâng quyền lúc khởi động — hãy /kill rồi chạy lại manager.py, "
            "hoặc tự mở lại bằng 'Run as administrator'."
        )
        return

    try:
        result = subprocess.run(
            ["net", "user", username, new_pass],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        out = (result.stdout + result.stderr).strip()

        if result.returncode == 0:
            # Khởi động lại sshd để chắc chắn áp dụng credential mới
            try:
                subprocess.run(
                    ["powershell", "-Command", "Restart-Service sshd -Force -ErrorAction SilentlyContinue"],
                    timeout=15, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

            send_telegram(
                f"✅ Đã đặt mật khẩu đăng nhập Windows cho user `{username}`.\n"
                f"📡 Dùng để SSH/Termius:\n"
                f"  User: `{username}`\n"
                f"  Pass: (mật khẩu bạn vừa gửi)\n\n"
                f"⚠️ Đây CŨNG LÀ mật khẩu mở máy Windows — nhớ kỹ, đừng làm mất.\n"
                f"⚠️ Nếu tài khoản trước đó dùng PIN/không mật khẩu, dữ liệu đã mã hoá theo "
                f"trạng thái cũ (Wi-Fi đã lưu, Credential Manager, password lưu trong Chrome/Edge...) "
                f"có thể không còn truy cập được."
            )
        else:
            hint = ""
            if "2245" in out or "policy" in out.lower():
                hint = "\n💡 Khả năng mật khẩu chưa đạt độ phức tạp Windows yêu cầu (≥8 ký tự, có hoa/thường/số/ký tự đặc biệt)."
            send_telegram(
                f"❌ Đặt mật khẩu thất bại (code {result.returncode}):\n{out[:300]}{hint}"
            )
    except Exception as e:
        send_telegram(f"❌ Lỗi đặt mật khẩu Windows: {e}")


def hoptodesk_install():
    """Tự động tải và cài đặt HopToDesk."""
    if IS_WINDOWS:
        send_telegram("📥 Đang tải và cài đặt HopToDesk cho Windows...")

        def _do_install_win():
            try:
                # Ưu tiên file installer đầy đủ (có service), fallback portable
                installer_urls = [
                    "https://download.hoptodesk.com/HopToDesk64-Installer.exe",
                    "https://www.hoptodesk.com/HopToDesk64-Installer.exe",
                    "https://download.hoptodesk.com/HopToDesk64.exe",
                    "https://www.hoptodesk.com/HopToDesk64.exe",
                    "https://github.com/HopToDesk/hoptodesk/releases/latest/download/HopToDesk64-Installer.exe",
                    "https://github.com/HopToDesk/hoptodesk/releases/latest/download/HopToDesk64.exe",
                ]
                exe_path = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "hoptodesk_setup.exe")
                downloaded = False
                for exe_url in installer_urls:
                    send_telegram(f"🔗 Đang thử tải: {exe_url}...")
                    try:
                        r = requests.get(exe_url, timeout=120, stream=True, allow_redirects=True)
                        if r.status_code == 200:
                            with open(exe_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            downloaded = True
                            break
                    except Exception:
                        continue
                if not downloaded:
                    send_telegram("❌ Không tải được file từ tất cả các URL. Tải thủ công tại https://www.hoptodesk.com/")
                    return
                send_telegram("📦 Đang cài đặt silent (có thể mất 30-60s)...")
                # Thử --silent-install trước (NSIS mới), nếu lỗi thì thử /S (NSIS cũ)
                installed = False
                for flag in (["--silent-install"], ["/S"], ["/SILENT"], ["/VERYSILENT"]):
                    result = subprocess.run(
                        [exe_path] + flag,
                        timeout=120,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        capture_output=True
                    )
                    if result.returncode == 0:
                        installed = True
                        break
                if not installed:
                    # Chạy không có flag (nếu là portable thì chỉ extract)
                    result = subprocess.run(
                        [exe_path],
                        timeout=120,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        capture_output=True
                    )
                # Chờ HopToDesk service/process xuất hiện
                send_telegram("⏳ Chờ HopToDesk khởi động sau cài đặt...")
                for _ in range(15):
                    time.sleep(2)
                    if _find_hoptodesk_exe():
                        break
                # Khởi động service nếu chưa chạy
                exe_installed = _find_hoptodesk_exe()
                if exe_installed and not _is_hoptodesk_running():
                    subprocess.Popen(
                        [exe_installed],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        cwd=os.path.dirname(exe_installed)
                    )
                    time.sleep(5)
                hid = _get_hoptodesk_id()
                send_telegram(
                    f"✅ Cài đặt HopToDesk thành công!\n"
                    f"📍 ID: `{hid}`\n"
                    f"🔑 Gõ /setrdpass <mật_khẩu> để đặt mật khẩu.\n"
                    f"🚀 Gõ /run hoptodesk nếu chưa chạy."
                )
            except Exception as e:
                send_telegram(f"❌ Lỗi cài HopToDesk (Windows): {e}")

        threading.Thread(target=_do_install_win, daemon=True).start()
        return

    send_telegram("📥 Đang tải và cài đặt HopToDesk cho Linux...")

    def _do_install():
        try:
            # Thử nhiều URL — HopToDesk thay đổi domain/path theo thời gian
            deb_urls = [
                "https://www.hoptodesk.com/hoptodesk.deb",
                "https://download.hoptodesk.com/hoptodesk.deb",
                "https://download.hoptodesk.com/hoptodesk-latest.deb",
                "https://github.com/HopToDesk/hoptodesk/releases/latest/download/hoptodesk.deb",
                "https://objects.githubusercontent.com/github-production-release-asset/hoptodesk/hoptodesk.deb",
            ]
            deb_path = "/tmp/hoptodesk_latest.deb"
            downloaded = False
            for deb_url in deb_urls:
                send_telegram(f"🔗 Đang thử tải: {deb_url}...")
                try:
                    r = requests.get(deb_url, timeout=120, stream=True, allow_redirects=True)
                    if r.status_code == 200:
                        with open(deb_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        downloaded = True
                        break
                except Exception:
                    continue
            if not downloaded:
                send_telegram(
                    "❌ Không tải được file từ tất cả các URL.\n"
                    "💡 Tải thủ công tại https://www.hoptodesk.com/ rồi chạy:\n"
                    "  sudo dpkg -i hoptodesk.deb\n"
                    "  sudo apt-get install -f\n"
                    "  sudo systemctl enable --now hoptodesk"
                )
                return

            send_telegram("📦 Đang cài đặt (dpkg)...")
            pw = load_saved_password()

            def _run_sudo(cmd_list, input_pw=None, timeout=90):
                """Chạy lệnh sudo, trả về (returncode, output)."""
                full = ["sudo", "-S"] + cmd_list if input_pw else ["sudo"] + cmd_list
                proc = subprocess.Popen(
                    full, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True
                )
                out, err = proc.communicate(
                    input=(input_pw + "\n") if input_pw else None,
                    timeout=timeout
                )
                return proc.returncode, (out + err)

            # Bước 1: dpkg -i
            rc, output = _run_sudo(["dpkg", "-i", deb_path], pw)

            # Bước 2: fix dependencies dù rc = 0 hay không (dpkg hay báo lỗi dep giả)
            send_telegram("🔧 Đang fix dependencies (apt-get install -f)...")
            _run_sudo(["apt-get", "install", "-f", "-y", "-q"], pw, timeout=120)

            # Kiểm tra lại xem binary có không
            exe = _find_hoptodesk_exe()
            if not exe:
                send_telegram(
                    f"❌ Cài xong nhưng không tìm thấy binary HopToDesk!\n"
                    f"Log dpkg:\n{output[:400]}\n"
                    f"💡 Thử chạy thủ công: sudo dpkg -i {deb_path}"
                )
                return

            # Bước 3: enable + start systemd service để chạy ở nền (KHÔNG phải GUI)
            send_telegram("⚙️ Đang enable & start HopToDesk service (systemd)...")
            svc_enabled = False
            # HopToDesk có thể đặt tên service khác nhau tuỳ phiên bản
            for svc_name in ("hoptodesk", "HopToDesk", "hoptodesk-service"):
                rc_en, _ = _run_sudo(["systemctl", "enable", "--now", svc_name], pw)
                if rc_en == 0:
                    svc_enabled = True
                    break
                # Thử start-only (nếu unit file không có enable)
                rc_st, _ = _run_sudo(["systemctl", "start", svc_name], pw)
                if rc_st == 0:
                    svc_enabled = True
                    break

            # Nếu systemd unit không tồn tại, tự tạo và start
            if not svc_enabled:
                send_telegram("⚙️ Không tìm thấy systemd unit, tạo service thủ công...")
                unit_content = (
                    "[Unit]\n"
                    "Description=HopToDesk remote desktop service\n"
                    "After=network.target\n\n"
                    "[Service]\n"
                    f"ExecStart={exe} --service\n"
                    "Restart=always\n"
                    "RestartSec=5\n"
                    "KillMode=process\n\n"
                    "[Install]\n"
                    "WantedBy=multi-user.target\n"
                )
                unit_path = "/etc/systemd/system/hoptodesk.service"
                try:
                    proc = subprocess.Popen(
                        ["sudo", "-S", "tee", unit_path],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, text=True
                    )
                    proc.communicate(input=(pw + "\n" if pw else "") + unit_content, timeout=10)
                    _run_sudo(["systemctl", "daemon-reload"], pw)
                    _run_sudo(["systemctl", "enable", "--now", "hoptodesk"], pw)
                    svc_enabled = True
                except Exception as ex:
                    send_telegram(f"⚠️ Không tạo được systemd unit: {ex}")

            # Fallback: chạy trực tiếp với --service flag nếu systemd thất bại
            if not svc_enabled or not _is_hoptodesk_running():
                send_telegram("⚠️ Systemd thất bại, chạy HopToDesk --service trực tiếp...")
                try:
                    subprocess.Popen(
                        [exe, "--service"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                    time.sleep(4)
                except Exception:
                    # Cuối cùng: chạy bình thường không có flag
                    subprocess.Popen(
                        [exe],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                    time.sleep(4)

            time.sleep(3)
            hid = _get_hoptodesk_id()
            if hid == "Chưa lấy được ID":
                send_telegram(
                    f"⚠️ HopToDesk đã cài nhưng chưa lấy được ID ngay.\n"
                    f"💡 Chờ 30s rồi gõ /run hoptodesk để lấy ID."
                )
            else:
                send_telegram(
                    f"✅ Cài đặt HopToDesk thành công!\n"
                    f"📍 ID: `{hid}`\n"
                    f"🔑 Gõ /setrdpass <mật_khẩu> để đặt mật khẩu điều khiển.\n"
                    f"🚀 Service đang chạy ở nền — có thể kết nối ngay!"
                )
        except Exception as e:
            send_telegram(f"❌ Lỗi cài HopToDesk: {e}")

    threading.Thread(target=_do_install, daemon=True).start()


def hoptodesk_uninstall():
    """Gỡ cài đặt HopToDesk."""
    send_telegram("🗑️ Đang gỡ cài đặt HopToDesk...")

    def _do_uninstall():
        try:
            hoptodesk_stop()
            time.sleep(2)
            if IS_WINDOWS:
                send_telegram("🗑️ Đang gỡ cài đặt HopToDesk trên Windows...")
                # Tìm UninstallString từ registry
                uninstalled = False
                try:
                    import winreg
                    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                        for subkey in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                       r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                            try:
                                key = winreg.OpenKey(root, subkey)
                                for i in range(winreg.QueryInfoKey(key)[0]):
                                    try:
                                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                                        if "hoptodesk" in name.lower():
                                            uninst = winreg.QueryValueEx(sub, "UninstallString")[0]
                                            subprocess.run(uninst + " /S", shell=True, timeout=60,
                                                           creationflags=subprocess.CREATE_NO_WINDOW)
                                            send_telegram("✅ Đã gỡ cài đặt HopToDesk thành công.")
                                            uninstalled = True
                                            return
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                except Exception as e:
                    send_telegram(f"❌ Lỗi gỡ HopToDesk: {e}")
                    return
                if not uninstalled:
                    send_telegram("⚠️ Không tìm thấy HopToDesk để gỡ. Có thể chưa cài?")
                return
            pw = load_saved_password()
            if pw:
                proc = subprocess.Popen(
                    ["sudo", "-S", "dpkg", "--purge", "hoptodesk"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True
                )
                out, err = proc.communicate(input=pw + "\n", timeout=30)
                rc = proc.returncode
            else:
                result = subprocess.run(
                    ["sudo", "dpkg", "--purge", "hoptodesk"],
                    capture_output=True, text=True, timeout=30
                )
                rc = result.returncode
                out = result.stdout
                err = result.stderr

            if rc == 0:
                send_telegram("✅ Đã gỡ cài đặt HopToDesk thành công.")
            else:
                send_telegram(f"⚠️ Gỡ cài đặt trả về code {rc}.\n{(out+err)[:300]}")
        except Exception as e:
            send_telegram(f"❌ Lỗi gỡ cài đặt HopToDesk: {e}")

    threading.Thread(target=_do_uninstall, daemon=True).start()


def ensure_hoptodesk_service():
    """Đảm bảo HopToDesk đang chạy khi manager khởi động, gửi ID qua Telegram."""
    exe = _find_hoptodesk_exe()
    if not exe:
        print("[manager] HopToDesk chưa cài — bỏ qua. Gõ /install hoptodesk để cài.")
        return

    if _is_hoptodesk_running():
        hid = _get_hoptodesk_id()
        print(f"[manager] HopToDesk đang chạy. ID: {hid}")
        send_telegram(
            f"🖥️ *HopToDesk sẵn sàng*\n"
            f"📍 ID: `{hid}`\n"
            f"🔑 Đặt mật khẩu: `/setrdpass <mật_khẩu>`"
        )
        return

    print("[manager] Khởi động HopToDesk service...")
    try:
        if IS_WINDOWS:
            # Thử start Windows service trước (nếu cài bản installer)
            started = False
            for svc_name in ("HopToDesk", "hoptodesk", "HopToDeskService"):
                rc = subprocess.run(
                    ["sc", "start", svc_name],
                    capture_output=True, timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW
                ).returncode
                if rc == 0:
                    started = True
                    break
            if not started:
                # Fallback: chạy exe trực tiếp
                subprocess.Popen(
                    [exe],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=os.path.dirname(exe)
                )
        else:
            # Ưu tiên systemd (chạy ở nền, không cần display)
            started_via_systemd = False
            for svc_name in ("hoptodesk", "HopToDesk", "hoptodesk-service"):
                rc = subprocess.run(
                    ["systemctl", "start", svc_name],
                    capture_output=True, timeout=10
                ).returncode
                if rc == 0:
                    started_via_systemd = True
                    break

            if not started_via_systemd:
                # Fallback 1: chạy với --service flag (ẩn, không cần display)
                try:
                    subprocess.Popen(
                        [exe, "--service"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                except Exception:
                    # Fallback 2: chạy bình thường
                    subprocess.Popen(
                        [exe],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
        time.sleep(5)
    except Exception as e:
        print(f"[manager] Lỗi start HopToDesk: {e}")

    if _is_hoptodesk_running():
        hid = _get_hoptodesk_id()
        print(f"[manager] HopToDesk ID: {hid}")
        send_telegram(
            f"🖥️ *HopToDesk sẵn sàng*\n"
            f"📍 ID: `{hid}`\n"
            f"🔑 Đặt mật khẩu: `/setrdpass <mật_khẩu>`"
        )
    else:
        print("[manager] ⚠️ Không start được HopToDesk.")
        send_telegram(
            "⚠️ Không thể tự khởi động HopToDesk.\n"
            "💡 Gõ /run hoptodesk để thử lại, hoặc /install hoptodesk để cài lại."
        )


# ── ZeroTier helpers ─────────────────────────────────────────────────────────

def _is_zerotier_running():
    """Kiểm tra zerotier-one service đang chạy."""
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["powershell", "-Command",
                 "Get-Service -Name ZeroTierOneService -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status"],
                stderr=subprocess.DEVNULL, timeout=6
            ).decode(errors="ignore").strip()
            return "Running" in out
        except Exception:
            return False
    else:
        try:
            rc = subprocess.run(
                ["systemctl", "is-active", "zerotier-one"],
                capture_output=True, timeout=5
            ).returncode
            return rc == 0
        except Exception:
            return shutil.which("zerotier-cli") is not None


def _zerotier_cli(args_list, timeout=10):
    """Chạy lệnh zerotier-cli, trả về (returncode, output)."""
    cli = shutil.which("zerotier-cli") or "/usr/sbin/zerotier-cli"
    try:
        result = subprocess.run(
            [cli] + args_list,
            capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as e:
        return 1, str(e)


def ssh_install_and_report():
    """
    Cài và bật SSH server (Windows + Linux).
    Gọi _ssh_ensure_running() rồi báo kết quả chi tiết qua Telegram.
    """
    import getpass
    send_telegram("🔧 Đang kiểm tra và cài SSH server...")

    ok, port, note = _ssh_ensure_running()

    hostname = socket.gethostname()
    current_user = getpass.getuser()

    # Lấy IP LAN
    local_ip = "N/A"
    try:
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == 2 and not a.address.startswith("127."):
                    local_ip = a.address
                    break
    except Exception:
        pass

    # Lấy ZeroTier IP nếu có
    zt_ip = None
    if _is_zerotier_running():
        try:
            _, zt_nets = _zerotier_cli(["listnetworks"], timeout=5)
            m = re.search(r'\b(10\.\d+\.\d+\.\d+|172\.2\d\.\d+\.\d+)\b', zt_nets)
            if m:
                zt_ip = m.group(1)
        except Exception:
            pass

    if ok:
        msg = (
            f"✅ SSH ĐÃ SẴN SÀNG!\n"
            f"{note}\n"
            f"══════════════════════\n"
            f"🏠 Máy: `{hostname}` | 👤 User: `{current_user}`\n\n"
            f"📡 *Kết nối LAN (cùng mạng WiFi):*\n"
            f"  `ssh {current_user}@{local_ip} -p {port}`\n"
        )
        if zt_ip:
            msg += (
                f"\n🌐 *Kết nối qua ZeroTier (bất kỳ đâu):*\n"
                f"  `ssh {current_user}@{zt_ip} -p {port}`\n"
            )
        else:
            msg += (
                f"\n💡 Chưa có ZeroTier → SSH chỉ dùng được khi cùng mạng LAN.\n"
                f"   Gõ /install zerotier rồi /network <id> để SSH từ iPhone qua mạng ZeroTier."
            )
        if IS_WINDOWS:
            msg += (
                f"\n\n⚠️ *Windows: Nhớ mở Firewall port 22:*\n"
                f"  `netsh advfirewall firewall add rule name=\"SSH\" protocol=TCP dir=in localport=22 action=allow`"
            )
    else:
        msg = (
            f"❌ KHÔNG THỂ BẬT SSH TỰ ĐỘNG\n"
            f"{note}\n"
            f"══════════════════════\n"
        )
        if IS_WINDOWS:
            msg += (
                "💡 Thử thủ công (chạy PowerShell Admin):\n"
                "  `Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0`\n"
                "  `Start-Service sshd`\n"
                "  `Set-Service -Name sshd -StartupType Automatic`"
            )
        else:
            msg += (
                "💡 Thử thủ công:\n"
                "  `sudo apt-get install -y openssh-server`\n"
                "  `sudo systemctl enable --now ssh`\n"
                "Sau đó gõ /testpass <mật_khẩu> để cấp quyền sudo cho bot."
            )

    send_telegram(msg)


def zerotier_install():
    """Tự động cài đặt ZeroTier."""
    send_telegram("📥 Đang cài đặt ZeroTier...")

    def _do_install():
        try:
            if IS_WINDOWS:
                msi_url = "https://download.zerotier.com/dist/ZeroTier%20One.msi"
                msi_path = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "zerotier_setup.msi")
                send_telegram(f"🔗 Đang tải ZeroTier MSI...")
                r = requests.get(msi_url, timeout=120, stream=True, allow_redirects=True)
                if r.status_code != 200:
                    send_telegram(f"❌ Không tải được file (HTTP {r.status_code}).")
                    return
                with open(msi_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                send_telegram("📦 Đang cài đặt silent...")
                result = subprocess.run(
                    ["msiexec", "/i", msi_path, "/quiet", "/norestart"],
                    timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if result.returncode == 0:
                    time.sleep(5)
                    if _is_zerotier_running():
                        send_telegram(
                            "✅ ZeroTier cài đặt thành công!\n"
                            "💡 Gõ /network <network_id> để join mạng ZeroTier của bạn."
                        )
                    else:
                        send_telegram("⚠️ Cài xong nhưng service chưa chạy. Thử khởi động lại máy.")
                else:
                    send_telegram(f"⚠️ msiexec trả về code {result.returncode}.\n💡 Kiểm tra quyền Admin.")
                return

            # Linux
            install_proc = subprocess.run(
                "curl -s https://install.zerotier.com | sudo bash",
                shell=True, capture_output=True, text=True, timeout=120,
                input=(load_saved_password() + "\n")
            )
            if install_proc.returncode != 0:
                send_telegram(f"❌ Cài ZeroTier thất bại:\n`{install_proc.stderr[-300:]}`")
                return

            _sudo_run_mgr(["systemctl", "enable", "--now", "zerotier-one"])
            time.sleep(3)

            if _is_zerotier_running():
                rc, out = _zerotier_cli(["info"])
                send_telegram(
                    f"✅ ZeroTier cài đặt thành công!\n"
                    f"ℹ️ {out}\n"
                    f"💡 Gõ /network <network_id> để join mạng ZeroTier của bạn."
                )
            else:
                send_telegram("❌ ZeroTier đã cài nhưng service không start được. Thử khởi động lại máy.")
        except Exception as e:
            send_telegram(f"❌ Lỗi cài ZeroTier: {e}")

    threading.Thread(target=_do_install, daemon=True).start()


def zerotier_uninstall():
    """Gỡ cài đặt ZeroTier."""
    send_telegram("🗑️ Đang gỡ cài đặt ZeroTier...")

    def _do_uninstall():
        try:
            if IS_WINDOWS:
                send_telegram("🗑️ Đang gỡ cài đặt ZeroTier trên Windows...")
                result = subprocess.run(
                    ["wmic", "product", "where", "name like '%ZeroTier%'", "call", "uninstall", "/nointeractive"],
                    timeout=60, capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if result.returncode == 0:
                    send_telegram("✅ Đã gỡ cài đặt ZeroTier thành công.")
                else:
                    # Fallback: tìm UninstallString từ registry
                    try:
                        import winreg
                        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                            for subkey in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                           r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                                try:
                                    key = winreg.OpenKey(root, subkey)
                                    for i in range(winreg.QueryInfoKey(key)[0]):
                                        try:
                                            sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                                            name = winreg.QueryValueEx(sub, "DisplayName")[0]
                                            if "zerotier" in name.lower():
                                                uninst = winreg.QueryValueEx(sub, "UninstallString")[0]
                                                subprocess.run(uninst + " /quiet", shell=True, timeout=60,
                                                               creationflags=subprocess.CREATE_NO_WINDOW)
                                                send_telegram("✅ Đã gỡ cài đặt ZeroTier thành công.")
                                                return
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                        send_telegram("⚠️ Không tìm thấy ZeroTier để gỡ. Có thể chưa cài?")
                    except Exception as e:
                        send_telegram(f"❌ Lỗi gỡ ZeroTier: {e}")
                return
            pw = load_saved_password()
            cmds = [
                ["systemctl", "disable", "--now", "zerotier-one"],
                ["apt-get", "remove", "--purge", "-y", "zerotier-one"],
            ]
            for cmd in cmds:
                _sudo_run_mgr(cmd)
            send_telegram("✅ Đã gỡ cài đặt ZeroTier.")
        except Exception as e:
            send_telegram(f"❌ Lỗi gỡ cài đặt ZeroTier: {e}")

    threading.Thread(target=_do_uninstall, daemon=True).start()


def zerotier_join(network_id: str):
    """Tham gia mạng ZeroTier theo network_id."""
    if not network_id or not re.match(r'^[0-9a-fA-F]{16}$', network_id):
        send_telegram(
            "❌ Network ID không hợp lệ (phải là 16 ký tự hex).\n"
            "Ví dụ: /network 8286ac0e47e2b743"
        )
        return
    send_telegram(f"🔗 Đang join ZeroTier network `{network_id}`...")

    def _do_join():
        try:
            if not _is_zerotier_running():
                send_telegram("⚠️ ZeroTier service chưa chạy. Gõ /install zerotier trước.")
                return
            rc, out = _zerotier_cli(["join", network_id])
            if rc == 0 or "200" in out:
                send_telegram(
                    f"✅ Đã gửi yêu cầu join network `{network_id}`!\n"
                    f"📌 Nếu mạng có authorization, cần approve trên ZeroTier Central:\n"
                    f"   https://my.zerotier.com/ → Networks → {network_id} → Members\n"
                    f"💡 Gõ /networklist để xem danh sách network đã join."
                )
            else:
                send_telegram(f"❌ Join thất bại:\n{out[:300]}")
        except Exception as e:
            send_telegram(f"❌ Lỗi join ZeroTier: {e}")

    threading.Thread(target=_do_join, daemon=True).start()


def zerotier_leave(network_id: str):
    """Rời khỏi mạng ZeroTier."""
    if not network_id or not re.match(r'^[0-9a-fA-F]{16}$', network_id):
        send_telegram(
            "❌ Network ID không hợp lệ (phải là 16 ký tự hex).\n"
            "Ví dụ: /unnetwork 8286ac0e47e2b743"
        )
        return
    send_telegram(f"🔓 Đang rời ZeroTier network `{network_id}`...")

    def _do_leave():
        try:
            rc, out = _zerotier_cli(["leave", network_id])
            if rc == 0 or "200" in out:
                send_telegram(f"✅ Đã rời network `{network_id}` thành công.")
            else:
                send_telegram(f"❌ Leave thất bại:\n{out[:300]}")
        except Exception as e:
            send_telegram(f"❌ Lỗi leave ZeroTier: {e}")

    threading.Thread(target=_do_leave, daemon=True).start()


def zerotier_list_networks():
    """Liệt kê các mạng ZeroTier đã join."""
    def _do_list():
        try:
            if not _is_zerotier_running():
                send_telegram("⚠️ ZeroTier service không chạy. Gõ /install zerotier trước.")
                return
            rc, out = _zerotier_cli(["listnetworks"])
            if rc != 0:
                send_telegram(f"❌ Lỗi liệt kê network:\n{out[:300]}")
                return
            lines_raw = out.strip().splitlines()
            if len(lines_raw) <= 1:
                send_telegram(
                    "📋 Chưa join mạng ZeroTier nào.\n"
                    "💡 Gõ /network <network_id> để tham gia mạng."
                )
                return
            msg = "🌐 *DANH SÁCH ZEROTIER NETWORKS*\n══════════════════════\n"
            for line in lines_raw[1:]:  # bỏ header
                parts_l = line.split()
                if len(parts_l) >= 8:
                    net_id   = parts_l[2]
                    name     = parts_l[3]
                    status   = parts_l[5]
                    zt_ip    = parts_l[8] if len(parts_l) > 8 else "N/A"
                    icon = "🟢" if status == "OK" else "🔴"
                    msg += f"{icon} `{net_id}` — {name}\n   IP: `{zt_ip}` | Status: {status}\n"
                else:
                    msg += f"• {line}\n"
            # Lấy ZeroTier ID của máy
            _, info_out = _zerotier_cli(["info"])
            if info_out:
                msg += f"──────────────────────\nℹ️ Node: {info_out}\n"
            msg += "💡 /network <id> join | /unnetwork <id> leave"
            send_telegram(msg)
        except Exception as e:
            send_telegram(f"❌ Lỗi liệt kê ZeroTier network: {e}")

    threading.Thread(target=_do_list, daemon=True).start()


# ── get_terminal_info — SSH + HopToDesk ID ───────────────────────────────────

def get_terminal_info() -> str:
    """
    Hiển thị thông tin SSH + HopToDesk ID để kết nối từ xa.
    ZeroTier IP (nếu có) cũng được hiển thị như kênh kết nối.
    """
    import getpass
    lines = ["🖥️ *THÔNG TIN KẾT NỐI TỪ XA*", "══════════════════════════"]

    hostname     = socket.gethostname()
    current_user = getpass.getuser()
    lines.append(f"🏠 Máy chủ: `{hostname}` | 👤 User: `{current_user}`")

    ssh_ok, ssh_port, _ = _ssh_ensure_running()

    # ── HopToDesk ────────────────────────────────────────────────
    lines.append("")
    lines.append("🖥️ *HopToDesk (Remote Desktop)*")
    hid = _get_hoptodesk_id()
    if _is_hoptodesk_running():
        lines.append(f"  ✅ Đang chạy — ID: `{hid}`")
    else:
        lines.append(f"  ⚠️ Chưa chạy. ID: `{hid}`")
        lines.append("  💡 Gõ /run hoptodesk để khởi động")
    lines.append("  📲 Cài HopToDesk trên máy điều khiển: https://www.hoptodesk.com/")

    # ── ZeroTier IP (nếu đang chạy) ──────────────────────────────
    if _is_zerotier_running():
        _, zt_nets = _zerotier_cli(["listnetworks"], timeout=5)
        zt_ips = re.findall(r'\b(10\.\d+\.\d+\.\d+|172\.2\d\.\d+\.\d+)\b', zt_nets)
        if zt_ips:
            lines.append("")
            lines.append("🌐 *ZeroTier (VPN)*")
            for ip in zt_ips:
                lines.append(f"  📍 IP: `{ip}`")
            if ssh_ok:
                lines.append(f"  SSH qua ZeroTier: `{zt_ips[0]}:{ssh_port}`")

    # ── SSH LAN ───────────────────────────────────────────────────
    if ssh_ok:
        local_ip = "N/A"
        try:
            for addrs in psutil.net_if_addrs().values():
                for a in addrs:
                    if a.family == 2 and not a.address.startswith("127."):
                        local_ip = a.address
                        break
        except Exception:
            pass
        lines.append("")
        lines.append("📡 *SSH LAN (chỉ dùng khi cùng mạng)*")
        lines.append(f"  Host: `{local_ip}` | Port: `{ssh_port}` | User: `{current_user}`")

    lines.append("")
    lines.append("══════════════════════════")
    lines.append("💡 Gõ /terminal để làm mới thông tin này.")
    return "\n".join(lines)





# --- 9. BIỂU ĐỒ ---
def _prepare_list_data(kind, data):
    now = datetime.now()
    parsed = []
    for dt_s, val in data.items():
        try:
            dt = datetime.strptime(dt_s, "%Y-%m-%d %H:%M")
            parsed.append((dt, safe_float(val)))
        except:
            continue

    parsed.sort(key=lambda x: x[0])

    if kind == "day":
        buckets = OrderedDict((f"{h:02d}h", 0.0) for h in range(24))
        for dt, val in parsed:
            if dt.date() == now.date():
                buckets[f"{dt.hour:02d}h"] += val
        labels = list(buckets.keys())
        values = [round(v, 2) for v in buckets.values()]
        total = sum(buckets.values())
        subtitle = "HÔM NAY"

    elif kind == "week":
        dates = [now.date() - timedelta(days=i) for i in range(6, -1, -1)]
        buckets = OrderedDict((d.strftime("%d/%m"), 0.0) for d in dates)
        for dt, val in parsed:
            key = dt.date().strftime("%d/%m")
            if key in buckets:
                buckets[key] += val
        labels = list(buckets.keys())
        values = [round(v, 2) for v in buckets.values()]
        total = sum(buckets.values())
        subtitle = "7 NGÀY GẦN NHẤT"

    elif kind == "month":
        year = now.year
        month = now.month
        days_in_month = calendar.monthrange(year, month)[1]
        buckets = OrderedDict((f"{d:02d}", 0.0) for d in range(1, days_in_month + 1))
        for dt, val in parsed:
            if dt.year == year and dt.month == month:
                buckets[f"{dt.day:02d}"] += val
        labels = [f"Ngày {k}" for k in buckets.keys()]
        values = [round(v, 2) for v in buckets.values()]
        total = sum(buckets.values())
        subtitle = "THÁNG HIỆN TẠI"

    elif kind == "year":
        year = now.year
        buckets = OrderedDict((f"T{m:02d}", 0.0) for m in range(1, 13))
        for dt, val in parsed:
            if dt.year == year:
                buckets[f"T{dt.month:02d}"] += val
        labels = list(buckets.keys())
        values = [round(v, 2) for v in buckets.values()]
        total = sum(buckets.values())
        subtitle = "NĂM HIỆN TẠI"

    else:  # all
        buckets = OrderedDict()
        for dt, val in parsed:
            key = dt.strftime("%d/%m/%Y")
            buckets[key] = buckets.get(key, 0.0) + val
        labels = list(buckets.keys())
        values = [round(v, 2) for v in buckets.values()]
        total = sum(buckets.values())
        subtitle = "TẤT CẢ NGÀY"

    return labels, values, total, subtitle


def generate_chart(kind):
    # Đọc từ RAM cache — không đọc đĩa
    try:
        data = ram_cache["finance"]
    except NameError:
        data = load_json_safe(FILE_TAI_CHINH, {})

    kind = (kind or "all").lower().strip()
    if kind not in ["day", "week", "month", "year", "all"]:
        kind = "all"

    labels, values, total, subtitle = _prepare_list_data(kind, data)

    if not labels:
        if kind == "day":
            labels = [f"{h:02d}h" for h in range(24)]
            values = [0.0] * 24
        elif kind == "week":
            labels = [(datetime.now().date() - timedelta(days=i)).strftime('%d/%m') for i in range(6, -1, -1)]
            values = [0.0] * 7
        elif kind == "month":
            days_in_month = calendar.monthrange(datetime.now().year, datetime.now().month)[1]
            labels = [f"Ng{d:02d}" for d in range(1, days_in_month + 1)]
            values = [0.0] * days_in_month
        elif kind == "year":
            labels = [f"T{m:02d}" for m in range(1, 13)]
            values = [0.0] * 12
        else:
            labels = ["Chưa có dữ liệu"]
            values = [0.0]

    # ── Vẽ bằng Pillow — nhẹ hơn matplotlib ~10 lần ──
    try:
        from PIL import Image, ImageDraw, ImageFont

        W, H       = 900, 420
        PAD_L      = 60
        PAD_R      = 20
        PAD_T      = 48
        PAD_B      = 72

        BG         = (24, 26, 36)
        BAR_BASE   = (52, 195, 120)
        BAR_HIGH   = (255, 210, 60)
        AXIS_COL   = (90, 95, 110)
        LABEL_COL  = (170, 175, 190)
        VALUE_COL  = (255, 220, 80)
        TITLE_COL  = (220, 225, 235)

        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        # Font — thử lấy font hệ thống, fallback về default
        try:
            font_title  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            font_label  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
            font_val    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except Exception:
            try:
                font_title = ImageFont.truetype("arial.ttf", 16)
                font_label = ImageFont.truetype("arial.ttf", 11)
                font_val   = ImageFont.truetype("arial.ttf", 10)
            except Exception:
                font_title = font_label = font_val = ImageFont.load_default()

        # Tiêu đề
        draw.text((W // 2, 14), f"Tiền điện — {subtitle}", fill=TITLE_COL,
                  font=font_title, anchor="mt")

        n       = len(labels)
        cw      = W - PAD_L - PAD_R          # chiều rộng vùng chart
        ch      = H - PAD_T - PAD_B          # chiều cao vùng chart
        max_val = max(values) if max(values) > 0 else 1
        slot    = cw // n
        bar_w   = max(3, slot - max(2, slot // 5))

        for i, (label, val) in enumerate(zip(labels, values)):
            x0    = PAD_L + i * slot + (slot - bar_w) // 2
            bar_h = int((val / max_val) * ch)
            y_top = PAD_T + ch - bar_h
            y_bot = PAD_T + ch

            # Màu: cao nhất = vàng, còn lại = xanh lá
            color = BAR_HIGH if val == max(values) and val > 0 else BAR_BASE
            if bar_h > 0:
                draw.rectangle([x0, y_top, x0 + bar_w, y_bot], fill=color)

            # Nhãn dưới thanh
            draw.text((x0 + bar_w // 2, H - PAD_B + 5), label,
                      fill=LABEL_COL, font=font_label, anchor="mt")

            # Giá trị trên thanh (chỉ hiện nếu bar đủ cao)
            if val > 0 and bar_h > 16:
                vtext = f"{int(val):,}"
                draw.text((x0 + bar_w // 2, y_top - 3), vtext,
                          fill=VALUE_COL, font=font_val, anchor="mb")

        # Đường trục X
        draw.line([(PAD_L, PAD_T + ch), (W - PAD_R, PAD_T + ch)],
                  fill=AXIS_COL, width=1)

        # Tổng ở góc dưới phải
        draw.text((W - PAD_R, H - 16),
                  f"Tổng: {format_vnd(total)}",
                  fill=LABEL_COL, font=font_label, anchor="rb")

        img.save(FILE_CHART, "PNG", optimize=True)

    except ImportError:
        # ── Fallback: biểu đồ text gửi thẳng qua Telegram ──
        max_val = max(values) if values and max(values) > 0 else 1
        lines   = [f"📊 {subtitle}"]
        for label, val in zip(labels, values):
            bar = "█" * int((val / max_val) * 15)
            lines.append(f"{label:>7} {bar or '·'} {format_vnd(val)}")
        lines.append(f"\n💸 Tổng: {format_vnd(total)}\n🧾 {EVN_PRICE_SOURCE}")
        send_telegram("\n".join(lines))
        return None

    except Exception as e:
        return f"❌ Lỗi tạo biểu đồ: {e}"

    send_telegram(
        f"📊 BIỂU ĐỒ TIỀN ĐIỆN: {subtitle}\n"
        f"💸 Tổng trong phạm vi này: {format_vnd(total)}\n"
        f"🧾 Nguồn giá: {EVN_PRICE_SOURCE}"
    )
    try:
        send_telegram_photo(FILE_CHART, f"📊 {subtitle}")
    except Exception as e:
        return f"❌ Tạo biểu đồ xong nhưng gửi ảnh lỗi: {e}"

    return None


def handle_list_command(arg):
    if not arg:
        arg = "all"
    arg = arg.lower().strip()
    if arg in ["day", "week", "month", "year", "all"]:
        err = generate_chart(arg)
        if err:
            send_telegram(err)
    else:
        send_telegram("❌ Lệnh không hợp lệ. Dùng: /list day|week|month|year|all")


# --- 10. BÁO CÁO TIỀN ĐIỆN ---
def send_tiendienthang_report(arg):
    arg = (arg or "").strip().lower()
    total_all = get_total_finance_all_time()

    if arg == "all" or arg == "":
        msg = (
            f"💰 TỔNG TIỀN ĐIỆN TỪ LÚC CHẠY FILE ĐẾN HIỆN TẠI:\n"
            f"• Tổng toàn bộ: {format_vnd(total_all)}\n"
            f"• Nguồn giá: {EVN_PRICE_SOURCE}"
        )
        send_telegram(msg)
        return

    try:
        month_num = int(arg)
        if month_num < 1 or month_num > 12:
            send_telegram("⚠️ Tháng không hợp lệ. Dùng 1 đến 12 hoặc all.")
            return

        total_month = get_total_finance_by_month(month_num)
        msg = (
            f"💰 TỔNG TIỀN ĐIỆN\n"
            f"• Tháng {month_num:02d}: {format_vnd(total_month)}\n"
            f"• Tổng từ lúc chạy file đến hiện tại: {format_vnd(total_all)}\n"
            f"• Nguồn giá: {EVN_PRICE_SOURCE}"
        )
        send_telegram(msg)
    except:
        send_telegram("⚠️ Cú pháp: /tiendienthang <số_tháng> hoặc /tiendienthang all")


def send_tongdien_report():
    now_month = datetime.now().strftime("%Y-%m")
    total_kwh_month = get_total_kwh_month()
    total_kwh_all = get_total_kwh_all_time()
    tong_tien = get_total_finance_all_time()
    tier_price = get_evn_tier_price(total_kwh_month)

    msg_dien = (
        f"⚡ TỔNG ĐIỆN NĂNG & TIỀN ĐIỆN:\n"
        f"Tháng này ({now_month}): {total_kwh_month:.3f} kWh\n"
        f"Tổng từ trước đến nay: {total_kwh_all:.3f} kWh\n"
        f"💸 Tổng tiền điện hiện tại: {format_vnd(tong_tien)}\n"
        f"📌 Giá điện bậc thang đang áp dụng: {tier_price:,.0f} VNĐ/kWh\n"
        f"🧾 Nguồn giá: {EVN_PRICE_SOURCE}"
    )
    send_telegram(msg_dien)


# --- 11. LỆNH TELEGRAM ---

def _do_dangerous_cmd(cmd, password_input):
    """
    Xử lý /shutdown /restart /sleep:
    - Đọc mật khẩu từ file .sudo_pass
    - Nếu file chưa có pass → thực thi thẳng (sudo NOPASSWD)
    - Nếu file có pass → dùng luôn, không cần nhập lại
    """
    global _pending_action
    _pending_action = None
    labels = {"/shutdown": "tắt máy", "/restart": "khởi động lại", "/sleep": "ngủ đông"}
    label = labels.get(cmd, cmd)
    _execute_dangerous_cmd(cmd, label)


def _setup_sudoers_nopasswd(password):
    """
    Ghi rule NOPASSWD vào /etc/sudoers.d/manager_bot bằng cách dùng
    'su -c' với mật khẩu root/user để có quyền ghi.
    Chỉ cần chạy 1 lần qua /confirm <pass>.
    """
    username = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    sudoers_line = (
        f"{username} ALL=(ALL) NOPASSWD: "
        f"/usr/sbin/shutdown, /usr/sbin/reboot, "
        f"/bin/systemctl suspend, /usr/bin/systemctl suspend, "
        f"/bin/systemctl poweroff, /usr/bin/systemctl poweroff, "
        f"/bin/systemctl reboot, /usr/bin/systemctl reboot\n"
    )
    sudoers_file = "/etc/sudoers.d/manager_bot"
    cmd = f"echo '{sudoers_line}' > {sudoers_file} && chmod 440 {sudoers_file}"
    try:
        proc = subprocess.Popen(
            ["su", "-c", cmd, "root"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        _, err = proc.communicate(input=(password + "\n").encode(), timeout=15)
        if proc.returncode == 0:
            return True, ""
        return False, err.decode(errors="ignore")
    except Exception as e:
        return False, str(e)


def _sudo_run(args):
    """Chạy sudo --non-interactive — yêu cầu đã có NOPASSWD trong sudoers."""
    try:
        proc = subprocess.Popen(
            ["sudo", "--non-interactive"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        _, err = proc.communicate(timeout=15)
        return proc.returncode, err.decode(errors="ignore")
    except Exception as e:
        return -1, str(e)


def _execute_dangerous_cmd(cmd, label):
    """
    Thực thi lệnh tắt/restart/sleep.
    Linux: dùng _sudo_run_mgr (lấy pass từ .sudo_pass, cấp qua /testpass).
    Windows: dùng os.system trực tiếp.
    """
    send_telegram(f"⚠️ Đang thực hiện: {label}...")
    time.sleep(2)

    if cmd == "/shutdown":
        if IS_WINDOWS:
            os.system("shutdown /s /f /t 1")
        else:
            pw = load_saved_password()
            if pw:
                rc, err = _sudo_run_mgr(["shutdown", "now"])
            else:
                rc, err = _sudo_run_mgr(["systemctl", "poweroff"])
            if rc != 0:
                send_telegram(
                    f"❌ Lệnh shutdown thất bại (code {rc}).\n{err[:300]}\n"
                    f"💡 Gõ /testpass <mật_khẩu> để cấp quyền sudo rồi thử lại."
                )

    elif cmd == "/restart":
        if IS_WINDOWS:
            os.system("shutdown /r /f /t 1")
        else:
            rc, err = _sudo_run_mgr(["reboot"])
            if rc != 0:
                send_telegram(
                    f"❌ Lệnh reboot thất bại (code {rc}).\n{err[:300]}\n"
                    f"💡 Gõ /testpass <mật_khẩu> để cấp quyền sudo rồi thử lại."
                )

    elif cmd == "/sleep":
        if IS_WINDOWS:
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        else:
            rc, err = _sudo_run_mgr(["systemctl", "suspend"])
            if rc != 0:
                send_telegram(
                    f"❌ Lệnh suspend thất bại (code {rc}).\n{err[:300]}\n"
                    f"💡 Gõ /testpass <mật_khẩu> để cấp quyền sudo rồi thử lại."
                )


def check_telegram_commands():
    """Legacy wrapper — giờ chỉ dùng để flush; lệnh thực xử lý trong _telegram_thread."""
    pass   # Thread riêng đã lo toàn bộ polling


def _telegram_thread():
    """
    Thread polling lệnh Telegram — long polling 20s.
    Phản hồi lệnh trong <0.5s thay vì phải đợi đến lượt vòng lặp chính (1s+).
    """
    global last_update_id, _pending_action, _live_monitor_mid, CURRENT_LANG
    while True:
        try:
            url = (f"https://api.telegram.org/bot{TOKEN}/getUpdates"
                   f"?offset={last_update_id + 1}&timeout=20&limit=10")
            res = requests.get(url, timeout=25).json()
            if not res.get('result'):
                continue

            for upd in res['result']:
                last_update_id = upd['update_id']
                raw_msg = upd.get('message', {}).get('text', '').strip()  # giữ nguyên hoa/thường gốc
                msg = raw_msg.lower()
                if not msg:
                    continue
                parts = msg.split()

                if msg.startswith("/power"):
                    if len(parts) > 1:
                        send_telegram(set_power_plan(parts[1]))
                    else:
                        send_telegram("Dùng: /power low|balanced|high")

                elif msg.startswith("/tiendienthang"):
                    try:
                        arg = parts[1] if len(parts) > 1 else "all"
                        send_tiendienthang_report(arg)
                    except:
                        send_telegram("Chưa có dữ liệu.")

                elif msg.startswith("/storage"):
                    disk_path = DISK_PATH if os.path.exists(DISK_PATH) else '/'
                    disk = psutil.disk_usage(disk_path)
                    send_telegram(
                        f"💽 TÌNH TRẠNG Ổ CỨNG ({disk_path}):\n"
                        f"Tổng: {disk.total/(1024**3):.1f} GB\n"
                        f"Đã dùng: {disk.used/(1024**3):.1f} GB ({disk.percent}%)\n"
                        f"Trống: {disk.free/(1024**3):.1f} GB"
                    )

                elif msg.startswith("/list"):
                    arg = parts[1] if len(parts) > 1 else "all"
                    handle_list_command(arg)

                elif msg == "/ip":
                    # Lịch sử kết nối HopToDesk (access logs)
                    try:
                        hist = load_json_safe(FILE_IP_HISTORY, {})
                        if hist:
                            out = "🌐 LỊCH SỬ IP KẾT NỐI:\n"
                            for ip, info in hist.items():
                                st = "🟢 ONLINE" if info.get('status') == "ONLINE" else "🔴 OFFLINE"
                                out += f"{st} - {ip}\n   (Vào/Ra: {info.get('last_online', info.get('last_offline', 'N/A'))})\n"
                            send_telegram(out[:4000])
                        else:
                            send_telegram("Chưa có lịch sử kết nối nào.")
                    except:
                        send_telegram("Chưa có lịch sử kết nối.")

                elif msg == "/id":
                    hid = _get_hoptodesk_id()
                    running = "🟢 Đang chạy" if _is_hoptodesk_running() else "🔴 Chưa chạy"
                    send_telegram(f"🖥️ HopToDesk ID: `{hid}`\nTrạng thái: {running}")

                elif msg == "/run hoptodesk":
                    threading.Thread(target=hoptodesk_run, daemon=True).start()

                elif msg == "/stop hoptodesk":
                    threading.Thread(target=hoptodesk_stop, daemon=True).start()

                elif msg.startswith("/setrdpass"):
                    pw_arg = msg[len("/setrdpass"):].strip()
                    if not pw_arg:
                        send_telegram(
                            "🔑 Đặt mật khẩu điều khiển HopToDesk:\n"
                            "Cú pháp: /setrdpass <mật_khẩu>\n"
                            "Ví dụ:   /setrdpass MyPass123\n"
                            "⚠️ Không đặt mật khẩu quá đơn giản!"
                        )
                    else:
                        threading.Thread(target=hoptodesk_set_password, args=(pw_arg,), daemon=True).start()

                elif msg.startswith("/setrdssh"):
                    pw_arg = msg[len("/setrdssh"):].strip()
                    if not IS_WINDOWS:
                        send_telegram(
                            "ℹ️ /setrdssh chỉ dùng cho Windows.\n"
                            "Trên Linux, SSH dùng password Linux có sẵn — gõ /testpass <mật_khẩu> "
                            "để cấp quyền sudo cho bot (password đó cũng chính là password SSH)."
                        )
                    elif not pw_arg:
                        send_telegram(
                            "🔑 Đặt/đổi mật khẩu đăng nhập Windows (dùng để SSH qua Termius):\n"
                            "Cú pháp: /setrdssh <mật_khẩu>\n"
                            "Ví dụ:   /setrdssh MyPass123!\n"
                            "⚠️ Đây là mật khẩu mở máy Windows THẬT — đặt đủ mạnh và nhớ kỹ!\n"
                            "⚠️ Nếu tài khoản đang không có mật khẩu (chỉ dùng PIN), việc đặt lần đầu "
                            "qua lệnh này có thể làm mất quyền truy cập Wi-Fi đã lưu / Credential Manager / "
                            "password lưu trong Chrome-Edge cũ."
                        )
                    else:
                        threading.Thread(target=windows_set_account_password, args=(pw_arg,), daemon=True).start()

                elif msg == "/install hoptodesk":
                    threading.Thread(target=hoptodesk_install, daemon=True).start()

                elif msg in ("/unistall hoptodesk", "/uninstall hoptodesk"):
                    threading.Thread(target=hoptodesk_uninstall, daemon=True).start()

                elif msg == "/install zerotier":
                    threading.Thread(target=zerotier_install, daemon=True).start()

                elif msg == "/install ssh":
                    threading.Thread(target=ssh_install_and_report, daemon=True).start()

                elif msg in ("/unistall zerotier", "/uninstall zerotier"):
                    threading.Thread(target=zerotier_uninstall, daemon=True).start()

                elif msg.startswith("/network "):
                    net_id = msg[len("/network "):].strip()
                    zerotier_join(net_id)

                elif msg.startswith("/unnetwork "):
                    net_id = msg[len("/unnetwork "):].strip()
                    zerotier_leave(net_id)

                elif msg == "/networklist":
                    zerotier_list_networks()

                elif msg == "/terminal":
                    send_telegram("🔍 Đang thu thập thông tin kết nối từ xa... Vui lòng đợi.")
                    def _do_terminal():
                        try:
                            info = get_terminal_info()
                            if info:
                                send_telegram(info)
                        except Exception as e:
                            send_telegram(f"❌ Lỗi lấy thông tin terminal: {e}")
                    threading.Thread(target=_do_terminal, daemon=True).start()

                elif msg == "/temperature":
                    temp_msg = "🌡️ NHIỆT ĐỘ HỆ THỐNG:\n"
                    has_data = False
                    if hasattr(psutil, "sensors_temperatures"):
                        try:
                            temps = psutil.sensors_temperatures()
                            if temps:
                                has_data = True
                                for name, entries in temps.items():
                                    for i, entry in enumerate(entries):
                                        label = entry.label if entry.label else f"Core {i}"
                                        temp_msg += f"🔹 {name.upper()} ({label}): {entry.current}°C\n"
                        except Exception:
                            pass
                    if not has_data and IS_WINDOWS:
                        try:
                            import wmi
                            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                            for s in w.Sensor():
                                if s.SensorType == "Temperature":
                                    temp_msg += f"🔹 {s.Name}: {s.Value:.1f}°C\n"
                                    has_data = True
                        except Exception:
                            pass
                    if not has_data and IS_WINDOWS:
                        try:
                            raw = subprocess.check_output(
                                "wmic /namespace:\\\\root\\wmi PATH MSAcpi_ThermalZoneTemperature get CurrentTemperature",
                                shell=True, stderr=subprocess.DEVNULL
                            ).decode(errors='ignore').strip().splitlines()
                            for i, tc in enumerate([int(x.strip()) for x in raw if x.strip().isdigit()]):
                                temp_msg += f"🔹 Thermal Zone {i}: {(tc-2732)/10.0:.1f}°C\n"
                                has_data = True
                        except Exception:
                            pass
                    if not has_data:
                        temp_msg += ("⚠️ Windows: Cài OpenHardwareMonitor + pip install wmi\n"
                                     if IS_WINDOWS else "⚠️ Không đọc được cảm biến nhiệt độ.")
                    send_telegram(temp_msg)

                elif msg == "/live":
                    _live_monitor_mid = None
                    send_telegram("📡 Live monitor đã reset — tin nhắn mới sẽ xuất hiện ngay.")

                elif msg == "/start":
                    ok, reason = send_wol_packet()
                    if ok:
                        send_telegram(f"🟢 Đã gửi Magic Packet WoL!\n📡 MAC: {WOL_MAC}\n⏳ Chờ ~30s rồi /ping.")
                    else:
                        send_telegram(f"❌ Không gửi được WOL: {reason}")

                elif msg.startswith("/confirm "):
                    # /confirm giữ lại để tương thích, nhưng redirect sang /testpass
                    send_telegram(
                        "ℹ️ Lệnh /confirm đã được thay bằng /testpass.\n"
                        "💡 Để cấp quyền sudo, dùng:\n"
                        "  /testpass <mật_khẩu>\n"
                        "Lệnh này hoạt động cả khi hệ thống ONLINE lẫn OFFLINE."
                    )

                elif parts[0] in ("/shutdown", "/restart", "/sleep"):
                    _do_dangerous_cmd(parts[0], None)

                elif msg == "/testpass":
                    pw = load_saved_password()
                    pw_info = (f"🔑 Pass: {len(pw)} ký tự | 3đầu:'{pw[:3]}' | 3cuối:'{pw[-3:]}'"
                               if pw else "⚠️ Chưa có mật khẩu. Gõ: /testpass <pass> để cấp.")
                    if IS_WINDOWS:
                        try:
                            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                        except:
                            is_admin = False
                        send_telegram(f"🖥️ Windows — {'✅ Đang chạy Admin' if is_admin else '⚠️ Chưa Admin'}.\n{pw_info}")
                    else:
                        rc, err = _sudo_run_mgr(["true"])
                        if rc == 0:
                            send_telegram(f"✅ Sudo OK (pass từ .sudo_pass).\n{pw_info}")
                        else:
                            send_telegram(f"❌ Sudo thất bại (code {rc}):\n{err[:200]}\n{pw_info}\n💡 Gõ /testpass <mật_khẩu> để cấp quyền.")

                elif msg == "/kill":
                    send_telegram(t("kill_saving"))
                    flush_to_disk()
                    # Ghi respawn.flag NGAY LẬP TỨC để launcher (start_windows.bat /
                    # start_linux.sh) phát hiện tức thì và khởi động lại check_ping.py,
                    # thay vì phải đợi heartbeat (time.txt) hết hạn 30-35s mới biết manager đã chết.
                    # Đây chính là nguyên nhân "/kill xong không restart" trên Windows trước đây —
                    # thực ra nó đang đợi rất lâu chứ không phải treo vĩnh viễn.
                    try:
                        respawn_flag_path = os.path.join(BASE_DIR, "respawn.flag")
                        open(respawn_flag_path, "w").close()
                    except Exception as e:
                        print(f"[manager] ⚠️ Không ghi được respawn.flag: {e}")
                    send_telegram(t("kill_offline_msg"))
                    time.sleep(1.5)   # chờ Telegram request gửi xong trước khi exit
                    os._exit(0)

                elif msg == "/ping":
                    t0 = time.time()
                    try:
                        requests.get("https://google.com", timeout=3)
                        send_telegram(f"🏓 PONG!\n📡 Online\n⏱ Độ trễ: {round((time.time()-t0)*1000)}ms")
                    except:
                        send_telegram("❌ Mạng chập chờn hoặc rớt!")

                elif msg.startswith("/safe energy"):
                    global SAFE_ENERGY_ENABLED
                    arg = parts[2] if len(parts) > 2 else ""
                    if arg == "on":
                        SAFE_ENERGY_ENABLED = True
                        send_telegram("🛡️ Safe Energy BẬT — tự điều chỉnh CPU khi quá tải.")
                    elif arg == "off":
                        SAFE_ENERGY_ENABLED = False
                        send_telegram("⚡ Safe Energy TẮT — máy chạy full power, không giới hạn.")
                    else:
                        status = "BẬT ✅" if SAFE_ENERGY_ENABLED else "TẮT ❌"
                        send_telegram(f"🛡️ Safe Energy: {status}\nDùng: /safe energy on|off")

                elif msg == "/check":
                    send_telegram(f"✅ HỆ THỐNG ONLINE\n💻 HĐH: {platform.system()}\n🛡️ Script đang trực chiến.")

                elif msg == "/trash":
                    send_telegram("🧹 Đang dọn dẹp rác...")
                    send_telegram(f"✨ Hoàn tất! Giải phóng: {clean_temp_files()} MB.")

                elif msg == "/tongdien":
                    try:
                        flush_to_disk(); send_tongdien_report()
                    except:
                        send_telegram("❌ Chưa đủ dữ liệu điện năng.")

                elif msg.startswith("/change_national_electricity"):
                    global ELECTRICITY_COUNTRY
                    # Dùng raw_msg để giữ hoa/thường tên quốc gia gốc (vd "Japan" thay vì "japan")
                    parts_cmd_raw = raw_msg.split(maxsplit=1)
                    if len(parts_cmd_raw) == 1:
                        # Xem quốc gia hiện tại
                        send_telegram(
                            f"🌍 Quốc gia tra giá điện hiện tại: *{ELECTRICITY_COUNTRY}*\n"
                            f"📌 Để đổi: /change_national_electricity <tên quốc gia>\n"
                            f"Ví dụ: /change_national_electricity Japan | /change_national_electricity Germany | /change_national_electricity Việt Nam"
                        )
                    else:
                        new_country = parts_cmd_raw[1].strip()
                        ELECTRICITY_COUNTRY = new_country
                        cache = load_json_safe(FILE_EVN_CACHE, {})
                        cache["country"] = new_country
                        save_json_safe(FILE_EVN_CACHE, cache)
                        send_telegram(
                            f"✅ Đã đổi quốc gia tra giá điện → *{new_country}*\n"
                            f"💡 Gõ /capnhatgia để cập nhật giá điện ngay."
                        )

                elif msg == "/capnhatgia":
                    send_telegram("🔄 Đang tìm giá điện mới nhất (Gemini → HTML → cache)...")
                    result = update_evn_prices_from_web(force=True)
                    send_telegram(result)

                elif msg == "/hardware":
                    send_telegram("🔍 Đang quét phần cứng và đo điện năng thực...")
                    cpu_now    = psutil.cpu_percent(interval=0.3)
                    ram_vm     = psutil.virtual_memory()
                    ram_now    = ram_vm.percent
                    ram_used   = round(ram_vm.used / (1024**3), 1)
                    ram_total  = round(ram_vm.total / (1024**3), 1)

                    rapl_w = get_rapl_power_w()
                    if rapl_w is not None:
                        cpu_w_now = rapl_w; cpu_w_source = "RAPL đo thực"
                    else:
                        tdp = HW_SPECS.get("cpu_tdp", 65)
                        cpu_w_now = round(max(tdp*0.07, tdp*(cpu_now/100.0)), 1)
                        cpu_w_source = f"ước lượng TDP {tdp}W"

                    gpu_w_now    = get_gpu_realtime_w()
                    gpu_w_source = "sensor đo thực" if gpu_w_now is not None else "N/A"
                    gpu_w_now    = gpu_w_now or 0.0

                    temp_str = ""
                    try:
                        for s in ("coretemp","k10temp","zenpower","cpu_thermal"):
                            sensor_t = (psutil.sensors_temperatures() or {}).get(s)
                            if sensor_t:
                                temp_str = f" | 🌡️ {sensor_t[0].current:.0f}°C"; break
                    except Exception:
                        pass

                    disks = HW_SPECS.get("disks_detail", [])
                    disk_lines = ""; disk_w_total = 0.0
                    for d in disks[:4]:
                        w = 7 if d["type"]=="HDD" else (3 if "NVMe" in d["type"] else 2.5)
                        disk_w_total += w
                        disk_lines += f"   • {d['name']} {d['model'][:22]}({d['size']},{d['type']},~{w}W)\n"
                    if not disk_lines:
                        disk_w_total = HW_SPECS.get("disk_w", 5)
                        disk_lines = f"   • {HW_SPECS.get('disk_type','Unknown')} (~{disk_w_total}W)\n"

                    gn = HW_SPECS.get("gpu_name","")
                    gpu_lines = f"   • {gn}" if gn and "không" not in gn.lower() else "   • iGPU / Không phát hiện GPU rời"
                    if HW_SPECS.get("gpu_tdp"):
                        gpu_lines += f" (TDP {HW_SPECS['gpu_tdp']}W)"
                    gpu_lines += "\n"
                    if not gn or "không" in gn.lower():
                        gpu_w_now = max(gpu_w_now, 5.0)

                    ram_type_str = HW_SPECS.get("ram_type","DDR4")
                    if HW_SPECS.get("ram_speed"):
                        ram_type_str += f"-{HW_SPECS['ram_speed']}"
                    mb_w  = HW_SPECS.get("mb_w", 25)
                    usb_w = HW_SPECS.get("usb_count", 0) * 0.5
                    ram_w = round((ram_used / 8) * 3.0, 1)
                    total_w = round(cpu_w_now + gpu_w_now + ram_w + disk_w_total + mb_w + usb_w, 1)

                    tier   = get_evn_tier_price(get_total_kwh_month())
                    per_hr = round(total_w / 1000 * tier, 0)

                    cores_p = HW_SPECS.get("cpu_cores_p", 1)
                    cores_l = HW_SPECS.get("cpu_cores_l", 1)
                    fmax    = HW_SPECS.get("cpu_freq_max_mhz", 0)
                    freq_str = f" Boost {fmax/1000:.1f}GHz" if fmax > 0 else ""

                    send_telegram(
                        f"💻 THÔNG SỐ PHẦN CỨNG CHI TIẾT\n"
                        f"══════════════════════════════\n"
                        f"🔲 CPU: {HW_SPECS['cpu_name']}\n"
                        f"   {cores_p}P×{cores_l}T{freq_str} | Tải: {cpu_now:.0f}%{temp_str}\n"
                        f"   Tiêu thụ: {cpu_w_now:.1f}W ({cpu_w_source})\n\n"
                        f"💾 RAM: {ram_total}GB {ram_type_str}\n"
                        f"   {ram_used}GB/{ram_total}GB ({ram_now:.0f}%) ~{ram_w}W\n\n"
                        f"🎮 GPU:\n{gpu_lines}"
                        f"   Tiêu thụ: {gpu_w_now:.1f}W ({gpu_w_source})\n\n"
                        f"💿 Ổ CỨNG:\n{disk_lines}\n"
                        f"🔌 Board ~{mb_w}W | USB {HW_SPECS.get('usb_count',0)} thiết bị ~{usb_w:.1f}W\n"
                        f"🌐 {HW_SPECS.get('os_info','')}\n"
                        f"══════════════════════════════\n"
                        f"⚡ TỔNG TIÊU THỤ LÚC NÀY: {total_w}W\n"
                        f"   CPU {cpu_w_now:.1f} + GPU {gpu_w_now:.1f} + RAM {ram_w:.1f}"
                        f" + Disk {disk_w_total:.1f} + Board {mb_w} + USB {usb_w:.1f}\n"
                        f"══════════════════════════════\n"
                        f"💸 TIỀN ĐIỆN (bậc {tier:,}đ/kWh):\n"
                        f"   1h  : {per_hr:,.0f}đ  |  "
                        f"24h : {per_hr*24:,.0f}đ  |  "
                        f"30d : {per_hr*24*30:,.0f}đ\n"
                        f"🧾 {EVN_PRICE_SOURCE}"
                    )

                elif msg == "/huongdan":
                    safe_status = "BẬT ✅" if SAFE_ENERGY_ENABLED else "TẮT ❌"
                    send_telegram(t("huongdan", safe_status=safe_status))

                elif msg.startswith("/languages"):
                    # Dùng raw_msg để giữ hoa/thường tên ngôn ngữ gốc (vd "Japanese")
                    lang_parts_raw = raw_msg.split(maxsplit=1)
                    if len(lang_parts_raw) == 1:
                        send_telegram(t("languages_usage", current=CURRENT_LANG))
                    else:
                        new_lang = lang_parts_raw[1].strip()
                        is_builtin = new_lang.lower() in (
                            "english", "en", "vietnamese", "vi", "tiếng việt", "tieng viet"
                        )
                        if not is_builtin and not GEMINI_KEY_VALID:
                            send_telegram(t("languages_no_key"))
                        else:
                            send_telegram(t("languages_translating", lang=new_lang))
                            CURRENT_LANG = new_lang
                            save_current_lang(new_lang)
                            # Gửi tin "done" bằng ngôn ngữ MỚI (sau khi đã đổi CURRENT_LANG)
                            send_telegram(t("languages_done", lang=new_lang))

                elif msg.startswith("/"):
                    send_telegram(t("cmd_not_found", cmd=msg.split()[0]))

        except Exception as e:
            import traceback
            print(f"[_telegram_thread] ❌ LỖI: {e}")
            traceback.print_exc()
            time.sleep(2)   # chờ khi lỗi mạng rồi thử lại


# ══════════════════════════════════════════════════════
# ── KIỂM TRA VÀ TỰ THIẾT LẬP QUYỀN HẠN LÚC KHỞI ĐỘNG ──
# ══════════════════════════════════════════════════════
def check_and_setup_permissions():
    """Kiểm tra quyền hệ điều hành lúc khởi động. Bắt vòng lặp chờ pass nếu thiếu quyền."""
    print("[Boot check_ping] 🔍 Kiểm tra quyền hệ thống...")
    
    if IS_WINDOWS:
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        except:
            is_admin = False
            
        if not is_admin:
            print("[Boot check_ping] 🛡️ Chưa có quyền Admin. Đang gọi UAC để tự thăng cấp...")
            # Gửi thông báo qua Telegram trước khi văng
            send_telegram(
                "⚠️ **[Watchdog - Windows] Thiếu quyền Administrator!**\n"
                "Đã gọi bảng UAC. Vui lòng mở màn hình máy tính và bấm 'Yes' để cấp quyền. "
                "Sau khi bấm, hệ thống sẽ tự động khởi động lại với quyền cao nhất."
            )
            try:
                ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
            except Exception as e:
                print(f"[Boot check_ping] ❌ Lỗi gọi UAC: {e}")
                send_telegram(f"❌ [Watchdog] Lỗi không thể gọi UAC trên Windows: {e}")
            sys.exit(0)
        else:
            print("[Boot check_ping] ✅ Đã chạy dưới quyền Administrator trên Windows.")
            # Có thể bỏ comment dòng dưới nếu muốn nó báo luôn khi boot thành công trên Win
            # send_msg("✅ [Watchdog - Windows] Đã khởi động thành công với quyền Administrator.")
    else:
        # ---- PHẦN DÀNH CHO LINUX ĐÃ LÀM Ở TRÊN ----
        rc, _ = _sudo_run(["true"])
        if rc == 0:
            print("[Boot check_ping] ✅ Đã cấu hình NOPASSWD hoặc mật khẩu hợp lệ. Sẵn sàng.")
        else:
            print("[Boot check_ping] ❌ Cần cấp quyền Sudo. Đang chờ qua Telegram...")
            send_telegram(
                "⚠️ **[Watchdog - Linux] Yêu cầu cấp quyền Sudo!**\n"
                "Watchdog chưa có quyền để khởi động lại `manager.py`.\n\n"
                "Vui lòng gửi lệnh:\n"
                "`/testpass <mật_khẩu>`\n"
                "Sau đó dùng `/confirm` để lưu lại và tiếp tục."
            )
            
            global last_update_id
            while True:
                try:
                    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&limit=20&timeout=3"
                    res = requests.get(url, timeout=10).json()
                    for upd in res.get("result", []):
                        last_update_id = upd["update_id"]
                        message = upd.get("message", {})
                        text = message.get("text", "").strip()
                        
                        if text and str(message.get("chat", {}).get("id")) == CHAT_ID:
                            if process_telegram_command(text):
                                print("[Boot check_ping] ✅ Đã nhận mật khẩu qua Telegram. Khởi động tiếp.")
                                return  # Thoát vòng lặp cài đặt, tiếp tục chạy code bên dưới
                except Exception:
                    pass
                time.sleep(2)
check_and_setup_permissions()
# --- 12. LIVE MONITOR TỰ ĐỘNG (edit message mỗi 1 giây, chạy mãi) ---
_live_monitor_mid = None  # message_id của tin nhắn live

def _live_monitor_loop():
    """Chạy trong thread riêng, gửi 1 tin nhắn rồi edit mỗi 1 giây liên tục."""
    global _live_monitor_mid
    time.sleep(3)  # chờ script khởi động xong
    while True:
        try:
            cpu_l, ram_l, _, _, _, pwr_l, plug_l = get_system_stats()
            now_m = datetime.now().strftime("%Y-%m")
            kwh_so_far = safe_float(ram_cache["energy_total"].get(now_m, 0.0))
            tier = get_evn_tier_price(kwh_so_far)
            tong_tien = sum(safe_float(v) for v in ram_cache["finance"].values())
            text = (
                f"📡 LIVE MONITOR\n"
                f"🕒 {datetime.now().strftime('%H:%M:%S')}  |  "
                f"{'🔌 Cắm sạc' if plug_l else '🔋 Dùng Pin'}\n"
                f"──────────────────\n"
                f"💻 CPU: {cpu_l:.0f}%  |  RAM: {ram_l:.0f}%\n"
                f"⚡ Tiêu thụ: {pwr_l:.1f} W\n"
                f"──────────────────\n"
                f"📊 kWh tháng {now_m}: {kwh_so_far:.5f} kWh\n"
                f"🏷️ Bậc giá hiện tại: {tier:,} VNĐ/kWh\n"
                f"💸 Tổng tiền điện: {format_vnd(tong_tien)}\n"
                f"──────────────────\n"
                f"👤 Online: {len(active_ips_global)} người"
            )
            if _live_monitor_mid is None:
                _live_monitor_mid = send_telegram_return_id(text)
            else:
                edit_telegram(_live_monitor_mid, text)
        except Exception:
            pass
        time.sleep(5)


def start_live_monitor():
    t = threading.Thread(target=_live_monitor_loop, daemon=True)
    t.start()


def refresh_price_if_due():
    global EVN_LAST_SUCCESS_UNIX
    now = int(time.time())
    if EVN_LAST_SUCCESS_UNIX <= 0:
        load_evn_cache_if_any()
        if EVN_LAST_SUCCESS_UNIX <= 0:
            update_evn_prices_from_web(force=True)
        return

    if now - EVN_LAST_SUCCESS_UNIX >= 86400:
        update_evn_prices_from_web(force=True)


# --- 13. KHỞI TẠO ---
prevent_sleep()

ensure_json_file(FILE_TAI_CHINH, {})
ensure_json_file(FILE_TRUY_CAP, {})
ensure_json_file(FILE_IP_HISTORY, {})
ensure_json_file(FILE_ENERGY_TOTAL, {})
ensure_json_file(FILE_HW_CACHE, HW_SPECS)
ensure_json_file(FILE_EVN_CACHE, {})

load_evn_cache_if_any()

max_retry = 20
retry = 0

while retry < max_retry:
    try:
        requests.get("https://api.telegram.org", timeout=3)
        print("✅ OK")
        break
    except:
        retry += 1
        print(f"Retry {retry}")
        time.sleep(1)

if retry == max_retry:
    print("❌ Mạng quá tệ, bỏ qua...")

# Gửi tin NGAY — không chờ EVN/hardware nữa
cpu, ram, dsk, snt, rcv, pwr, plugged = get_system_stats()
hid = _get_hoptodesk_id()
os_name = platform.system()

send_telegram(
    f"🚀 HỆ THỐNG ĐÃ TRỰC CHIẾN ({os_name})!\n"
    f"🖥️ HopToDesk ID: {hid}\n"
    f"🖥️ CPU: {HW_SPECS['cpu_name']}\n"
    f"🔋 Điện hiện tại: {pwr:.1f}W\n"
    f"🔌 Nguồn: {'Cắm sạc' if plugged else 'Dùng Pin'}\n"
    f"📌 Giá điện: {EVN_PRICE_SOURCE} (đang cập nhật...)"
)

# Cập nhật EVN + hardware ở nền — không block vòng lặp chính
def _background_init():
    # Đảm bảo HopToDesk service đang chạy
    ensure_hoptodesk_service()
    update_evn_prices_from_web(force=True)
    fetch_hardware_power_specs()
    send_telegram(
        f"✅ Cập nhật hoàn tất!\n"
        f"🖥️ CPU: {HW_SPECS['cpu_name']} (TDP: {HW_SPECS['cpu_tdp']}W)\n"
        f"📌 Giá điện: {EVN_PRICE_SOURCE}"
    )

threading.Thread(target=_background_init, daemon=True).start()

# ── Khởi động thread lệnh Telegram (long polling — phản hồi tức thì) ──
threading.Thread(target=_telegram_thread, daemon=True).start()

# Khởi động live monitor tự động (edit message mỗi 1 giây, không cần gõ lệnh)
start_live_monitor()

try:
    _flush = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1",timeout=5).json()
    if _flush.get('result'):
        last_update_id = _flush['result'][-1]['update_id']
except Exception:
        pass

last_rep = time.time()
last_clean = time.time()
last_warn = 0
last_warn_power = 0
last_daily_price_refresh_check = time.time()
check=0
last_rep_potion=time.time()
SAFE_ENERGY_ENABLED = True   # /safe energy on/off để bật/tắt tự bảo vệ tài nguyên

import atexit, signal, glob, shutil

# ─── BUFFER RAM TOÀN CỤC ───────────────────────────────────────────────────────
_dirty = False
_last_flush = 0
FLUSH_INTERVAL = 300  # Ghi đĩa tối đa mỗi 5 phút

ram_cache = {
    "energy_total": load_json_safe(FILE_ENERGY_TOTAL, {}),
    "finance":      load_json_safe(FILE_TAI_CHINH, {}),
}

def flush_to_disk():
    global _dirty, _last_flush
    if not _dirty:
        return
    try:
        save_json_safe(FILE_ENERGY_TOTAL, ram_cache["energy_total"])
        save_json_safe(FILE_TAI_CHINH,    ram_cache["finance"])
        _dirty = False
        _last_flush = time.time()
    except Exception as e:
        send_telegram(f"❌ Lỗi ghi đĩa: {e}")

# Ghi đĩa khi thoát chương trình (Ctrl+C, kill, tắt máy...)
atexit.register(flush_to_disk)
signal.signal(signal.SIGTERM, lambda *_: (flush_to_disk(), exit(0)))


# ─── VÒNG LẶP CHÍNH ────────────────────────────────────────────────────────────
while True:
    try:
        cpu, ram, disk, sent, recv, pwr, plugged = get_system_stats()

        # ─── CẢNH BÁO ĐIỆN NĂNG ───
        if pwr >= CRITICAL_WATT and plugged:
            send_telegram(f"🔥 BÁO ĐỘNG ĐỎ: NGUỒN ĐIỆN QUÁ TẢI ({pwr:.1f}W)!")
            time.sleep(5)
        elif pwr >= WATT_WARNING and plugged and (time.time() - last_warn_power >= 300):
            send_telegram(f"⚠️ Cảnh báo điện năng: {pwr:.1f}W. Gõ '/power low' để tiết kiệm.")
            last_warn_power = time.time()

        # ─── CẢNH BÁO QUÁ TẢI TÀI NGUYÊN ───
        if (cpu >= 95 or ram >= 95) and time.time() - last_warn > 300:
            send_telegram(f"⚠️ QUÁ TẢI TÀI NGUYÊN: CPU {cpu}% - RAM {ram}%")
            last_warn = time.time()
            check = check + 1
        if (cpu >= 95 or ram >= 95) and time.time() - last_rep_potion > 30:
            check = check + 1
            last_rep_potion = time.time()

        # ─── XỬ LÝ KHI QUÁ TẢI LIÊN TỤC (CHECK > 5) ───
        if SAFE_ENERGY_ENABLED and check > 5:
            has_connection = False

            try:
                import psutil
                for conn in psutil.net_connections(kind='tcp'):
                    if conn.status == 'ESTABLISHED' and conn.laddr.port in [21116, 21117, 21118, 21119]:
                        has_connection = True
                        break
            except Exception:
                pass

            if has_connection:
                if IS_WINDOWS:
                    subprocess.run(
                        "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e",
                        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    if shutil.which("cpupower"):
                        subprocess.run("cpupower frequency-set -g ondemand", shell=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        for gov in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"):
                            try:
                                with open(gov, "w") as f:
                                    f.write("ondemand")
                            except Exception:
                                pass

                send_telegram("🔋 Phát hiện kết nối từ xa! Đã chuyển về [BALANCED].")

            else:
                if IS_WINDOWS:
                    subprocess.run(
                        "powercfg /setactive a1841308-3541-4fab-bc81-f71556f20b4a",
                        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    try:
                        for gov in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"):
                            with open(gov, "w") as f:
                                f.write("powersave")
                    except Exception:
                        if shutil.which("cpupower"):
                            subprocess.run("cpupower frequency-set -g powersave", shell=True,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                send_telegram("🍃 Máy trống và quá tải! Đã kích hoạt [POWERSAVE].")

            check = 0

        # ─── LƯU VÀO RAM (KHÔNG GHI ĐĨA) ───
        process_finance(pwr, plugged)
        prevent_sleep()

        # ─── HEARTBEAT: Ghi timestamp để check_ping.py biết manager còn sống ───
        try:
            with open(FILE_HEARTBEAT, "w") as _hb:
                _hb.write(str(time.time()))
        except Exception:
            pass

        # ─── FLUSH THÔNG MINH: Ghi đĩa mỗi 5 phút nếu có dữ liệu mới ───
        if _dirty and (time.time() - _last_flush >= FLUSH_INTERVAL):
            flush_to_disk()

        # (Lệnh Telegram được xử lý bởi _telegram_thread riêng — long poll, phản hồi tức thì)

        # ─── AUTO UPDATE GIÁ ĐIỆN MỖI GIỜ ───
        if time.time() - last_daily_price_refresh_check >= 3600:
            refresh_price_if_due()
            last_daily_price_refresh_check = time.time()

        # ─── DỌN RÁC MỖI GIỜ ───
        if time.time() - last_clean >= 3600:
            cleaned = clean_temp_files()
            if cleaned > 50:
                send_telegram(f"🧹 Đã tự động dọn: {cleaned} MB rác hệ thống.")
            last_clean = time.time()

        # ─── BÁO CÁO MỖI 5 PHÚT ───
        if time.time() - last_rep >= 300:
            try:
                now_m = datetime.now().strftime("%Y-%m")
                e_data = ram_cache["energy_total"]  # Đọc từ RAM thay vì đĩa
                current_tier = get_evn_tier_price(e_data.get(now_m, 0))
            except:
                current_tier = EVN_TIERS[2]

            msg = (
                f"📊 TÌNH TRẠNG (5p):\n"
                f"💻 CPU: {cpu}% | RAM: {ram}%\n"
                f"⚡ Tiêu thụ: {pwr:.1f}W\n"
                f"💸 Bậc giá điện: {current_tier} VNĐ/kWh\n"
                f"👤 User Online: {len(active_ips_global)}"
            )
            send_telegram(msg)
            last_rep = time.time()

        time.sleep(1)
    except Exception:
        time.sleep(1)
