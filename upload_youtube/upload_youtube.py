"""
YouTube Auto Upload - Boy Muscle Workout Channel

Cách dùng:
  python upload_youtube.py <thư_mục_video> [--token <token.pickle>] [--secrets <client_secrets.json>] [--headless]

Ví dụ:
  # Chạy bình thường (có GUI / trình duyệt)
  python upload_youtube.py D:\\Videos

  # VPS không có GUI — in URL ra terminal, paste code vào
  python upload_youtube.py /home/user/videos --headless

  # Chỉ định file token và secrets ở vị trí khác
  python upload_youtube.py /home/user/videos --token /etc/yt/token.pickle --secrets /etc/yt/client_secrets.json

Lần đầu chạy: xác thực OAuth 2.0 (mở trình duyệt hoặc dùng --headless trên VPS).
Các lần sau: dùng token đã lưu, không cần xác thực lại.
Token có thể copy sang máy/VPS khác để dùng lại.
"""

import sys
import os
import argparse
import pickle
import logging
import json
import time
import random
import re
from datetime import datetime
from pathlib import Path

import cv2
import mediapipe as mp_lib
import numpy as np

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from tqdm import tqdm

# ──────────────────────────────────────────────
# CẤU HÌNH MẶC ĐỊNH
# ──────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",       # cần cho thumbnails.set()
]

DEFAULT_DESCRIPTION = (
    "Please comment the Tik Tok ID you want to watch, and I will record it.\n"
    "My channel: https://www.youtube.com/@Boymuscleworkout2"
)
DEFAULT_TAGS     = ["workout", "gym", "fitness", "muscle", "tiktok"]
DEFAULT_PRIVACY  = "private"   # Upload ở chế độ riêng tư
CATEGORY_ID      = "17"        # Sports

UNITS_PER_UPLOAD = 1600
DAILY_QUOTA      = 100000

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}

# Anti-bot: delay ngẫu nhiên giữa các lần upload (giây)
MIN_DELAY = 30
MAX_DELAY = 90

# ──────────────────────────────────────────────
# PARSE ARGUMENTS
# ──────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="YouTube Auto Upload - Boy Muscle Workout")
    parser.add_argument(
        "folder", nargs="?", default=str(BASE_DIR.parent), 
        help="Path to folder containing videos (default: parent directory)"
    )
    parser.add_argument(
        "--token", default=None,
        help="Path to token.pickle (default: same folder as script)"
    )
    parser.add_argument(
        "--secrets", default=None,
        help="Path to client_secrets.json (default: same folder as script)"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Headless mode for VPS/no-GUI: prints auth URL instead of opening browser"
    )
    return parser.parse_args()

# ──────────────────────────────────────────────
# LOGGING — khởi tạo sau khi có BASE_DIR
# ──────────────────────────────────────────────

def setup_logging():
    log_file = BASE_DIR / "upload_log.txt"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)

log = setup_logging()

# ──────────────────────────────────────────────
# XÁC THỰC OAuth 2.0
# ──────────────────────────────────────────────

def get_authenticated_service(secrets_path: Path, token_path: Path, headless: bool):
    creds = None

    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        log.info(f"Đọc token từ: {token_path}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Làm mới access token...")
            creds.refresh(Request())
        else:
            if not secrets_path.exists():
                log.error(f"Không tìm thấy file client_secrets.json: {secrets_path}")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)

            if headless:
                # ── Chế độ VPS / không có trình duyệt ──────────────────
                # Dùng OOB flow: in URL ra, user mở trên máy khác, paste code vào
                flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
                auth_url, _ = flow.authorization_url(
                    access_type="offline",
                    include_granted_scopes="true",
                    prompt="consent",
                )
                print("\n" + "=" * 60)
                print("HEADLESS MODE — Làm theo các bước sau:")
                print("=" * 60)
                print("1. Mở link sau trên trình duyệt bất kỳ (máy khác cũng được):")
                print(f"\n   {auth_url}\n")
                print("2. Đăng nhập Gmail và cho phép quyền.")
                print("3. Copy đoạn code hiển thị trên trang web.")
                print("4. Paste vào đây rồi nhấn Enter:")
                code = input("   Authorization code: ").strip()
                flow.fetch_token(code=code)
                creds = flow.credentials
            else:
                # ── Chế độ bình thường — mở trình duyệt tự động ─────────
                log.info("Mở trình duyệt để xác thực...")
                creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
        log.info(f"Token đã lưu: {token_path}")
        log.info("Copy file token này sang máy/VPS khác để dùng lại, không cần đăng nhập lại.")

    return build("youtube", "v3", credentials=creds)

# ──────────────────────────────────────────────
# THEO DÕI FILE ĐÃ UPLOAD
# ──────────────────────────────────────────────

_uploaded_file = BASE_DIR / "uploaded.json"

def load_uploaded() -> dict:
    if _uploaded_file.exists():
        with open(_uploaded_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_uploaded(uploaded: dict):
    with open(_uploaded_file, "w", encoding="utf-8") as f:
        json.dump(uploaded, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────
# TRÍCH XUẤT THUMBNAIL TỪ VIDEO
# ──────────────────────────────────────────────

def _sharpness(img):
    """Đánh giá độ nét của ảnh (Laplacian variance)."""
    return cv2.Laplacian(img, cv2.CV_64F).var()


def _score_frame(frame, landmarks, mp_pose):
    """Cho điểm frame dựa trên kích thước body, visibility và độ nét."""
    h, w, _ = frame.shape

    ids = [
        mp_pose.PoseLandmark.LEFT_SHOULDER,
        mp_pose.PoseLandmark.RIGHT_SHOULDER,
        mp_pose.PoseLandmark.LEFT_ELBOW,
        mp_pose.PoseLandmark.RIGHT_ELBOW,
        mp_pose.PoseLandmark.LEFT_HIP,
        mp_pose.PoseLandmark.RIGHT_HIP,
    ]

    pts, vis = [], []
    for idx in ids:
        lm = landmarks[idx.value]
        pts.append([int(lm.x * w), int(lm.y * h)])
        vis.append(lm.visibility)

    pts = np.array(pts)
    x_min, y_min = pts.min(axis=0)
    x_max, y_max = pts.max(axis=0)

    area_score = ((x_max - x_min) * (y_max - y_min)) / (w * h)
    visibility_score = np.mean(vis)
    blur_score = _sharpness(frame) / 1000.0

    # ưu tiên body chiếm nhiều frame
    score = area_score * 0.7 + visibility_score * 0.2 + blur_score * 0.1
    return score, area_score


def _highlight_body(frame, segmentor):
    """Làm nổi bật body, blur background."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = segmentor.process(rgb)
    mask = (result.segmentation_mask > 0.3).astype(np.uint8) * 255

    blurred = cv2.GaussianBlur(frame, (41, 41), 0)
    body = cv2.bitwise_and(frame, frame, mask=mask)
    bg = cv2.bitwise_and(blurred, blurred, mask=cv2.bitwise_not(mask))
    return cv2.add(body, bg)


def _crop_upper(frame, landmarks):
    """Crop vùng body với margin."""
    h, w, _ = frame.shape
    pts = np.array([[int(lm.x * w), int(lm.y * h)] for lm in landmarks])
    x_min, y_min = pts.min(axis=0)
    x_max, y_max = pts.max(axis=0)
    margin = 60
    return frame[
        max(0, y_min - margin):min(h, y_max + margin),
        max(0, x_min - margin):min(w, x_max + margin)
    ]


def _enhance(img):
    """Tăng chất lượng ảnh: upscale, sharpen, adjust brightness."""
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    img = cv2.filter2D(img, -1, kernel)
    return cv2.convertScaleAbs(img, alpha=1.2, beta=10)


def generate_thumbnail(video_path: Path, output_dir: Path = None) -> Path | None:
    """
    Trích xuất thumbnail từ video bằng MediaPipe Pose.
    Chọn top 3 frame có body lớn nhất → ghép thành ảnh 1280x720.
    Trả về đường dẫn file thumbnail hoặc None nếu thất bại.
    """
    if output_dir is None:
        output_dir = video_path.parent

    mp_pose = mp_lib.solutions.pose
    pose = mp_pose.Pose(static_image_mode=True)
    segmentor = mp_lib.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.warning(f"Không mở được video để tạo thumbnail: {video_path.name}")
        return None

    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30
    frame_count = 0
    top_images = []  # [(score, img)]

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Mỗi 2 giây lấy 1 frame → giảm load
        if frame_count % (fps * 2) != 0:
            frame_count += 1
            continue

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = pose.process(rgb)

        if result.pose_landmarks:
            landmarks = result.pose_landmarks.landmark
            score, area = _score_frame(frame, landmarks, mp_pose)

            highlighted = _highlight_body(frame, segmentor)
            crop = _crop_upper(highlighted, landmarks)

            if crop.size > 0:
                img = _enhance(crop)

                # Giữ top 3
                if len(top_images) < 3:
                    top_images.append((score, img))
                else:
                    min_idx = int(np.argmin([s for s, _ in top_images]))
                    if score > top_images[min_idx][0]:
                        top_images[min_idx] = (score, img)

                top_images = sorted(top_images, key=lambda x: x[0], reverse=True)

                # Early stop nếu body đủ lớn
                if len(top_images) == 3 and area > 0.65:
                    log.info("  🔥 Early stop thumbnail (body đủ lớn)")
                    break

        frame_count += 1

    cap.release()
    pose.close()
    segmentor.close()

    if not top_images:
        log.warning(f"Không tìm được frame phù hợp cho thumbnail: {video_path.name}")
        return None

    # Ghép canvas 1280x720
    imgs = [img for _, img in top_images]
    while len(imgs) < 3:
        imgs.append(imgs[-1])

    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    w = 1280 // 3
    for i, img in enumerate(imgs):
        canvas[:, i * w:(i + 1) * w] = cv2.resize(img, (w, 720))

    # Lưu thumbnail
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', video_path.stem)
    thumb_path = output_dir / f"{clean_name}_thumb.jpg"
    cv2.imwrite(str(thumb_path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])
    log.info(f"  📸 Thumbnail: {thumb_path.name}")
    return thumb_path


# ──────────────────────────────────────────────
# SET THUMBNAIL
# ──────────────────────────────────────────────

def set_thumbnail(youtube, video_id: str, thumb_path: Path):
    """Upload custom thumbnail cho video đã upload."""
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
        ).execute()
        log.info(f"  🖼️  Thumbnail đã set cho video {video_id}")
        return True
    except HttpError as e:
        log.warning(f"  ⚠️  Không set được thumbnail: {e}")
        return False


# ──────────────────────────────────────────────
# UPLOAD MỘT VIDEO
# ──────────────────────────────────────────────

def upload_video(youtube, file_path: Path, thumb_path: Path = None) -> str:
    title = file_path.stem

    body = {
        "snippet": {
            "title": title,
            "description": DEFAULT_DESCRIPTION,
            "tags": DEFAULT_TAGS,
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": DEFAULT_PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }

    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    log.info(f"Đang upload: {file_path.name} ({file_size_mb:.1f} MB) [chế độ: {DEFAULT_PRIVACY}]")

    media = MediaFileUpload(
        str(file_path),
        mimetype="video/*",
        chunksize=10 * 1024 * 1024,
        resumable=True,
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    pbar = tqdm(total=100, desc=file_path.name[:40], unit="%", ncols=80)
    last_progress = 0

    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            pbar.update(progress - last_progress)
            last_progress = progress

    pbar.update(100 - last_progress)
    pbar.close()

    video_id = response["id"]
    log.info(f"Upload thành công! Video ID: {video_id} | Title: {title}")

    # Set thumbnail nếu có
    if thumb_path and thumb_path.exists():
        set_thumbnail(youtube, video_id, thumb_path)

    return video_id

# ──────────────────────────────────────────────
# XỬ LÝ LỖI VÀ RETRY
# ──────────────────────────────────────────────

def upload_with_retry(youtube, file_path: Path, thumb_path: Path = None, max_retries: int = 3):
    for attempt in range(1, max_retries + 1):
        try:
            return upload_video(youtube, file_path, thumb_path)
        except HttpError as e:
            status_code = e.resp.status
            error_body  = str(e)

            if status_code == 403 and "quotaExceeded" in error_body:
                log.error("Hết quota API hôm nay! Dừng upload, thử lại vào ngày mai.")
                raise SystemExit(1)

            if status_code == 403 and "uploadLimitExceeded" in error_body:
                log.error("Vượt giới hạn upload! Dừng upload.")
                raise SystemExit(1)

            if status_code == 403:
                log.error(f"Lỗi 403 Forbidden: {error_body}")
                raise

            if status_code in (500, 503):
                wait = 5 * attempt
                log.warning(f"Lỗi server {status_code}. Thử lại sau {wait}s (lần {attempt}/{max_retries})...")
                time.sleep(wait)
                continue

            log.error(f"HTTP error {status_code}: {error_body}")
            raise

    log.error(f"Upload thất bại sau {max_retries} lần thử: {file_path.name}")
    return None

# ──────────────────────────────────────────────
# QUÉT VIDEO
# ──────────────────────────────────────────────

def find_videos(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*")
        if p.suffix.lower() in VIDEO_EXTENSIONS and p.is_file()
    )

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    args = parse_args()

    input_folder  = Path(args.folder)
    secrets_path  = Path(args.secrets) if args.secrets else BASE_DIR / "client_secrets.json"
    token_path    = Path(args.token)   if args.token   else BASE_DIR / "token.pickle"
    headless      = args.headless

    if not input_folder.exists() or not input_folder.is_dir():
        print(f"Lỗi: Thư mục không tồn tại: {input_folder}")
        sys.exit(1)

    log.info("=" * 60)
    log.info("Boy Muscle Workout - YouTube Auto Upload")
    log.info(f"Thời gian bắt đầu : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Thư mục video     : {input_folder}")
    log.info(f"Token file        : {token_path}")
    log.info(f"Headless mode     : {'Bật' if headless else 'Tắt'}")
    log.info("=" * 60)

    video_files = find_videos(input_folder)

    if not video_files:
        log.info(f"Không tìm thấy video nào trong: {input_folder}")
        log.info("Hỗ trợ định dạng: .mp4, .mov, .avi, .mkv")
        return

    log.info(f"Tìm thấy {len(video_files)} video:")
    for f in video_files:
        log.info(f"  {f.relative_to(input_folder)}")

    uploaded = load_uploaded()
    pending  = [f for f in video_files
                if str(f.relative_to(input_folder)) not in uploaded]

    if not pending:
        log.info("Tất cả video đã được upload trước đó. Không có gì mới.")
        return

    log.info(f"Chưa upload: {len(pending)} | Đã upload trước đó: {len(uploaded)}")

    units_needed = len(pending) * UNITS_PER_UPLOAD
    log.info(f"Ước tính quota: {units_needed:,} units ({len(pending)} x {UNITS_PER_UPLOAD})")
    if units_needed > DAILY_QUOTA:
        log.warning(f"Quota mặc định ({DAILY_QUOTA:,}/ngày) không đủ. Sẽ upload đến khi hết quota.")

    youtube = get_authenticated_service(secrets_path, token_path, headless)
    log.info("Xác thực OAuth 2.0 thành công.")

    success_count = 0
    fail_count    = 0

    # Thư mục lưu thumbnail tạm
    thumb_dir = BASE_DIR / "_thumbnails"
    thumb_dir.mkdir(exist_ok=True)

    for i, file_path in enumerate(pending, 1):
        rel_key = str(file_path.relative_to(input_folder))
        log.info(f"\n[{i}/{len(pending)}] {rel_key}")

        # ── Bước 1: Trích xuất thumbnail ──
        log.info("  📸 Đang trích xuất thumbnail...")
        thumb_path = None
        try:
            thumb_path = generate_thumbnail(file_path, thumb_dir)
        except Exception as e:
            log.warning(f"  ⚠️  Lỗi tạo thumbnail (bỏ qua): {e}")

        # ── Bước 2: Upload video + set thumbnail ──
        try:
            video_id = upload_with_retry(youtube, file_path, thumb_path)
            if video_id:
                uploaded[rel_key] = {
                    "video_id"    : video_id,
                    "uploaded_at" : datetime.now().isoformat(),
                    "url"         : f"https://youtu.be/{video_id}",
                    "thumbnail"   : str(thumb_path) if thumb_path else None,
                }
                save_uploaded(uploaded)
                success_count += 1

                # ── Xóa file sau khi upload thành công ──
                try:
                    os.remove(file_path)
                    log.info(f"  🗑️ Đã xóa file video giải phóng dung lượng: {file_path.name}")
                    if thumb_path and thumb_path.exists():
                        os.remove(thumb_path)
                except Exception as e:
                    log.warning(f"  ⚠️ Lỗi khi xóa file {file_path.name}: {e}")
        except SystemExit:
            break
        except Exception as e:
            log.error(f"Lỗi với {file_path.name}: {e}")
            fail_count += 1
            continue

        # ── Bước 3: Anti-bot delay ──
        if i < len(pending):
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            log.info(f"  ⏳ Chờ {delay}s trước khi upload tiếp (anti-bot)...")
            time.sleep(delay)

    log.info("\n" + "=" * 60)
    log.info(f"Hoàn thành! Thành công: {success_count} | Thất bại: {fail_count}")
    log.info(f"Log: {BASE_DIR / 'upload_log.txt'}")
    log.info(f"Danh sách đã upload: {_uploaded_file}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
