#!/bin/bash
# start_linux.sh — Launcher & Respawn loop cho check_ping.py / manager.py
# =========================================================================
# LUỒNG:
#   1. Tạo venv nếu chưa có, cài gói cần thiết
#   2. Chạy check_ping.py
#   3. Nếu check_ping thoát với respawn.flag → restart lại check_ping
#   4. Nếu có stop.flag → thoát hẳn (người dùng đã /off)
# =========================================================================

cd "$(dirname "$0")"

VENV_DIR="venv_linux"

echo "🔍 Kiểm tra môi trường Python..."
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙️ Chưa có venv. Đang tạo..."
    python3 -m venv "$VENV_DIR"
    echo "📦 Đang cài gói cần thiết..."
    "$VENV_DIR"/bin/pip install --upgrade pip -q
    "$VENV_DIR"/bin/pip install requests psutil pillow paramiko -q
    echo "✅ Cài đặt hoàn tất!"
else
    # Kiểm tra paramiko đã cài chưa (cho tính năng /terminal)
    if ! "$VENV_DIR"/bin/python -c "import paramiko" 2>/dev/null; then
        echo "📦 Cài bổ sung paramiko..."
        "$VENV_DIR"/bin/pip install paramiko -q
    fi
fi

echo ""
echo "🚀 Khởi động Watchdog..."
echo "   Ctrl+C để dừng hoàn toàn, hoặc gõ /off qua Telegram."
echo ""

# Vòng lặp respawn — check_ping.py tự tắt khi manager UP
# Shell sẽ restart check_ping khi manager /kill
while true; do
    # Kiểm tra stop.flag — người dùng gõ /off
    if [ -f "stop.flag" ]; then
        rm -f "stop.flag"
        echo "🛑 Phát hiện stop.flag — Tắt hoàn toàn theo lệnh /off."
        break
    fi

    echo "[$(date '+%H:%M:%S')] 🔄 Khởi chạy check_ping.py..."
    "$VENV_DIR"/bin/python check_ping.py
    EXIT_CODE=$?

    # Kiểm tra lại stop.flag sau khi check_ping thoát
    if [ -f "stop.flag" ]; then
        rm -f "stop.flag"
        echo "🛑 stop.flag — Tắt hoàn toàn."
        break
    fi

    # Nếu check_ping thoát do manager đã UP (exit 0 sau /on thành công)
    # thì chờ manager tắt rồi mới restart check_ping
    echo "[$(date '+%H:%M:%S')] ⏳ check_ping đã tắt (code $EXIT_CODE). Đang theo dõi manager..."

    # Chờ manager sống (có time.txt)
    WAITED=0
    while [ $WAITED -lt 120 ]; do
        if [ -f "time.txt" ]; then
            break
        fi
        sleep 2
        WAITED=$((WAITED+2))
    done

    # Giờ chờ manager chết (time.txt không cập nhật hoặc có respawn.flag)
    echo "[$(date '+%H:%M:%S')] 🟢 Manager đang chạy. Chờ tín hiệu dừng..."
    while true; do
        if [ -f "stop.flag" ]; then
            rm -f "stop.flag"
            echo "🛑 stop.flag trong vòng chờ manager — Tắt hoàn toàn."
            exit 0
        fi
        if [ -f "respawn.flag" ]; then
            rm -f "respawn.flag"
            echo "[$(date '+%H:%M:%S')] 🔁 respawn.flag — Manager đã /kill. Restart check_ping..."
            break
        fi
        # Kiểm tra time.txt còn tươi không (20s timeout)
        if [ -f "time.txt" ]; then
            FILE_TIME=$(cat time.txt 2>/dev/null | tr -d '[:space:]')
            NOW=$(date +%s)
            if [ -n "$FILE_TIME" ]; then
                FILE_INT=${FILE_TIME%.*}
                DIFF=$((NOW - FILE_INT))
                if [ $DIFF -gt 30 ]; then
                    echo "[$(date '+%H:%M:%S')] ⚠️ Heartbeat mất (${DIFF}s). Manager có vẻ đã chết. Restart check_ping..."
                    break
                fi
            fi
        fi
        sleep 3
    done

    echo "[$(date '+%H:%M:%S')] 🔄 Restart check_ping.py trong 2s..."
    sleep 2
done

echo "✅ Launcher đã thoát."
