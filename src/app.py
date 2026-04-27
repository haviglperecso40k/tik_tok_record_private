import streamlit as st
import subprocess
import json
import os
import tempfile
import time
from cookies_txt_to_json import parse_netscape_cookie_file

st.set_page_config(page_title="TikTok Live Recorder", page_icon="🎥", layout="wide")

# Simple Authentication
def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == "admin6301": # Simple hardcoded password
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Vui lòng nhập mật khẩu", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Vui lòng nhập mật khẩu", type="password", on_change=password_entered, key="password")
        st.error("😕 Mật khẩu không đúng")
        return False
    else:
        return True

if check_password():
    st.title("🎥 TikTok Live Recorder WebUI")

    st.header("1. 🍪 Cập nhật Cookies (cookies.json)")
    st.info("Upload file `www.tiktok.com_cookies.txt` (Netscape format) để dùng tính năng đăng nhập.")
    uploaded_file = st.file_uploader("Upload file cookie", type="txt")
    if uploaded_file is not None:
        try:
            with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8') as f:
                f.write(uploaded_file.getvalue().decode('utf-8'))
                temp_path = f.name
            
            cookies = parse_netscape_cookie_file(temp_path)
            
            with open("cookies.json", "w", encoding="utf-8") as out:
                json.dump(cookies, out, indent=4)
            
            st.success(f"✅ Đã cập nhật `cookies.json` thành công với {len(cookies)} cookies!")
            os.remove(temp_path)
        except Exception as e:
            st.error(f"Lỗi khi xử lý cookie: {e}")

    def start_record(target):
        cmd = f"nohup python3 main.py -no-update-check -user {target} -mode automatic > record_{target}.log 2>&1 &"
        os.system(cmd)
        st.success(f"🔴 Đã bắt đầu record **@{target}**! Xem log ở mục bên dưới.")

    st.header("2. 🔴 Ghi hình Livestream")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        username_input = st.text_input("Nhập Username TikTok cần record (không cần @):")
    with col2:
        st.write("")
        st.write("")
        if st.button("🚀 Start Record", use_container_width=True, type="primary"):
            if username_input:
                start_record(username_input.strip().lstrip('@'))
            else:
                st.warning("Vui lòng nhập username!")

    st.subheader("⭐ Danh sách thường xuyên:")
    
    # Load frequent users
    if "freq_users" not in st.session_state:
        st.session_state["freq_users"] = []
        if os.path.exists("freq_users.json"):
            with open("freq_users.json", "r") as f:
                try:
                    st.session_state["freq_users"] = json.load(f)
                except:
                    st.session_state["freq_users"] = []
                
    with st.expander("Quản lý danh sách thường xuyên"):
        col_add1, col_add2, col_add3 = st.columns([3, 1, 1])
        with col_add1:
            new_freq = st.text_input("Thêm username vào danh sách thường xuyên:", key="new_freq_input")
        with col_add2:
            st.write("")
            st.write("")
            if st.button("➕ Thêm"):
                if new_freq and new_freq not in st.session_state["freq_users"]:
                    st.session_state["freq_users"].append(new_freq.strip().lstrip('@'))
                    with open("freq_users.json", "w") as f:
                        json.dump(st.session_state["freq_users"], f)
                    st.rerun()
        # Delete buttons
        if st.session_state["freq_users"]:
            st.write("Xoá khỏi danh sách:")
            del_cols = st.columns(4)
            to_delete = None
            for i, user in enumerate(st.session_state["freq_users"]):
                if del_cols[i % 4].button(f"🗑️ {user}", key=f"del_{user}"):
                    to_delete = user
            if to_delete:
                st.session_state["freq_users"].remove(to_delete)
                with open("freq_users.json", "w") as f:
                    json.dump(st.session_state["freq_users"], f)
                st.rerun()
            
    if st.session_state["freq_users"]:
        cols = st.columns(4)
        for i, user in enumerate(st.session_state["freq_users"]):
            if cols[i % 4].button(f"📹 {user}", key=f"rec_{user}"):
                start_record(user)

    st.header("3. 📝 Kiểm tra trạng thái")
    
    st.subheader("Tiến trình đang chạy ngầm:")
    try:
        ps_output = subprocess.check_output("ps aux | grep 'python3 main.py' | grep -v grep", shell=True).decode()
        if ps_output.strip():
            st.code(ps_output)
            
            # Parse processes to get targets and PIDs
            targets_running = []
            for line in ps_output.strip().split('\n'):
                if '-user' in line:
                    parts = line.split('-user')
                    if len(parts) > 1:
                        target = parts[1].strip().split()[0]
                        pid = line.split()[1]
                        targets_running.append((pid, target))
            
            if targets_running:
                st.write("Dừng tiến trình (Gửi Ctrl+C để tránh hỏng video):")
                cols = st.columns(4)
                for i, (pid, target) in enumerate(targets_running):
                    if cols[i % 4].button(f"🛑 Dừng {target}", key=f"stop_{pid}_{target}"):
                        os.system(f"kill -2 {pid}")
                        st.success(f"Đã gửi lệnh dừng (Ctrl+C) cho {target} (PID: {pid})")
                        time.sleep(1) # wait a little
                        st.rerun()

        else:
            st.info("Không có tiến trình record nào đang chạy.")
    except subprocess.CalledProcessError:
        st.info("Không có tiến trình record nào đang chạy.")

    st.subheader("Log ghi hình:")
    log_files = [f for f in os.listdir(".") if f.startswith("record_") and f.endswith(".log")]
    if log_files:
        colA, colB = st.columns([3, 1])
        with colA:
            selected_log = st.selectbox("Chọn file log để xem", log_files)
        with colB:
            st.write("")
            st.write("")
            if st.button("🔄 Làm mới log"):
                pass # Rerun to refresh
        if selected_log:
            with open(selected_log, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    st.code("".join(lines[-30:]))
                else:
                    st.write("*File log trống*")
    else:
        st.info("Chưa có file log nào được tạo. Bấm 'Start Record' hoặc chọn user thường xuyên để bắt đầu.")

    st.header("4. 🎬 Video đã Record thành công")
    mp4_files = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".mp4"):
                mp4_files.append(os.path.join(root, file))
    
    if mp4_files:
        for mp4 in sorted(mp4_files, reverse=True):
            st.write(f"✅ `{mp4}`")
    else:
        st.write("Chưa có video nào được lưu.")
