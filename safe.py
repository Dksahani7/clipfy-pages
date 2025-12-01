#!/usr/bin/env python3
# Clipfy bot — FINAL FULL VERSION (Unbreakable, WSL File Fix Applied)

import os
import time
import asyncio
import random
from uuid import uuid4
from pathlib import Path
from dotenv import load_dotenv
import subprocess
import shutil
import requests
from PIL import Image
import json

import boto3
from boto3.s3.transfer import TransferConfig
from github import Github

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.request import HTTPXRequest

# ---------------- LOAD ENV ----------------
load_dotenv()

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET", "videos")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

DEFAULT_PLAY_ICON = "https://pub-51338658718349efb6e5193255e4131b.r2.dev/kindpng_2115738.png"
PLAY_ICON_URL = os.getenv("PLAY_ICON_URL") or DEFAULT_PLAY_ICON

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
SITE_DOMAIN = os.getenv("SITE_DOMAIN")

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

# Use ffmpeg from PATH (works on all systems including Replit/Nix)
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

# ---------------- R2 CLIENT ----------------
if not R2_ENDPOINT:
    R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY
)

transfer_config = TransferConfig(
    multipart_threshold=20 * 1024 * 1024,
    multipart_chunksize=10 * 1024 * 1024
)

def r2_public_url(key: str) -> str:
    """Generates the full public URL for an R2 key."""
    return f"{R2_PUBLIC_URL.rstrip('/')}/{key.lstrip('/')}"

# ---------------- METADATA INDEX MANAGEMENT ----------------

INDEX_FILE_KEY = "metadata/index.json"

def get_video_index():
    """Fetches the LIVE video index (list of all videos) from R2 storage."""
    try:
        response = s3.get_object(Bucket=R2_BUCKET, Key=INDEX_FILE_KEY)
        content = response['Body'].read()
        return json.loads(content)
    except s3.exceptions.NoSuchKey:
        print("Index file not found on R2. Starting fresh.")
        return []
    except Exception as e:
        print(f"Error fetching video index: {e}")
        return []

def update_video_index(new_entry: dict):
    """Adds the new video entry to the index and updates index.json on R2."""
    video_list = get_video_index()
    if not any(item['video_id'] == new_entry['video_id'] for item in video_list):
        video_list.insert(0, new_entry)

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=INDEX_FILE_KEY,
        Body=json.dumps(video_list, indent=2),
        ContentType='application/json'
    )
    print(f"Metadata index updated with new video: {new_entry['video_id']}")


def ensure_index_exists():
    """Ensure the metadata/index.json file exists in the R2 bucket."""
    try:
        s3.head_object(Bucket=R2_BUCKET, Key=INDEX_FILE_KEY)
        print("Metadata index exists on R2.")
    except Exception:
        print("metadata/index.json not found - creating empty index on R2...")
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=INDEX_FILE_KEY,
            Body=json.dumps([]),
            ContentType='application/json'
        )
        print("Created empty metadata/index.json on R2.")


# ---------------- BOT DATA LOGIC ----------------

def get_all_video_data():
    """Returns the live list of all videos from R2 to be injected into the template."""
    return get_video_index()


def clean_text(text: str) -> str:
    """Small sanitizer used for safe page titles/descriptions."""
    if not text:
        return ""
    bad = ["hot", "sexy", "fuck", "dangerous", "18+", "18"]
    safe = str(text)
    for b in bad:
        safe = safe.replace(b, "")
    return " ".join(safe.split()).strip()

# ---------------- GITHUB CLIENT ----------------
gh = Github(GITHUB_TOKEN)
repo = gh.get_repo(GITHUB_REPO)

def create_or_update(repo, path: str, message: str, content: str):
    """
    Tries to create a file; if it fails (because the file exists), 
    it retrieves the file's SHA and updates the existing file.
    """
    try:
        repo.create_file(path, message, content)
    except Exception:
        try:
            file = repo.get_contents(path)
            repo.update_file(path, message, content, file.sha)
        except Exception as update_e:
            print(f"Critical GitHub Update Error for {path}: {update_e}")
            raise update_e


def generate_both_versions(video_url: str, thumb_url: str, video_id: str, title: str, description: str, time_ago: str, thumb_blur_url: str = None):
    """
    Generate two HTML files in the GitHub repo: normal and safe (blurred preview for social meta).
    Returns tuple: (normal_url, safe_url)
    """
    page_name = f"{video_id}.html"
    safe_page_name = f"{video_id}_safe.html"

    try:
        template = repo.get_contents("template.html").decoded_content.decode()
        safe_template = repo.get_contents("template_safe.html").decoded_content.decode()
    except Exception as e:
        print(f"Error fetching templates: {e}")
        raise Exception("Could not fetch templates from GitHub. Ensure template.html and template_safe.html exist.")

    all_videos_data = get_all_video_data()
    all_videos_data = [v for v in all_videos_data if v.get('video_id') != video_id]
    random.shuffle(all_videos_data) 
    all_videos_json_str = json.dumps(all_videos_data)

    normal_html = template.replace("{{VIDEO_URL}}", video_url)
    normal_html = normal_html.replace("{{THUMB_URL}}", thumb_url)
    normal_html = normal_html.replace("{{PLAYER_PAGE_URL}}", f"{SITE_DOMAIN.rstrip('/')}/v/{page_name}")
    normal_html = normal_html.replace("{{VIDEO_ID}}", video_id)
    normal_html = normal_html.replace("{{TITLE}}", title)
    normal_html = normal_html.replace("{{DESCRIPTION}}", description)
    normal_html = normal_html.replace("{{TIME_AGO}}", time_ago)
    normal_html = normal_html.replace("{{ALL_VIDEOS_JSON}}", all_videos_json_str)

    safe_thumb = thumb_blur_url if thumb_blur_url else f"{thumb_url}?blur=10"
    safe_title = clean_text(title)
    safe_desc = clean_text(description)

    safe_html = safe_template.replace("{{VIDEO_URL}}", video_url)
    safe_html = safe_html.replace("{{THUMB_URL}}", safe_thumb)
    safe_html = safe_html.replace("{{PLAYER_PAGE_URL}}", f"{SITE_DOMAIN.rstrip('/')}/v/{safe_page_name}")
    safe_html = safe_html.replace("{{VIDEO_ID}}", video_id)
    safe_html = safe_html.replace("{{TITLE}}", safe_title)
    safe_html = safe_html.replace("{{DESCRIPTION}}", safe_desc)
    safe_html = safe_html.replace("{{TIME_AGO}}", time_ago)
    safe_html = safe_html.replace("{{ALL_VIDEOS_JSON}}", all_videos_json_str)

    create_or_update(repo, f"v/{page_name}", f"Update video page {page_name}", normal_html)
    create_or_update(repo, f"v/{safe_page_name}", f"Update safe video page {safe_page_name}", safe_html)

    return f"{SITE_DOMAIN.rstrip('/')}/v/{page_name}", f"{SITE_DOMAIN.rstrip('/')}/v/{safe_page_name}"


# ---------------- HELPER FUNCTIONS ----------------

async def safe_edit(msg, text):
    try:
        await msg.edit_text(text)
    except:
        pass


def make_thumbnail(video_path: Path, thumb_path: Path) -> bool:
    """
    Robust thumbnail extractor with multiple fallback methods.
    Uses scale=1280:720:force_original_aspect_ratio=decrease to fit any video size.
    """
    timestamps = ["00:00:00.5", "00:00:01", "00:00:02", "00:00:00"]

    for ts in timestamps:
        try:
            cmd = [
                FFMPEG_BIN, "-y",
                "-ss", ts,
                "-i", str(video_path),
                "-vframes", "1",
                "-an",
                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
                str(thumb_path)
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
                print(f"Thumbnail extracted at {ts}")
                return True
        except Exception as e:
            print(f"Method 1 failed at {ts}: {e}")
            continue

    try:
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(video_path),
            "-vframes", "1",
            "-an",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
            "-q:v", "2",
            str(thumb_path)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
            print("Thumbnail extracted with padded method")
            return True
        else:
            print(f"Padded method failed: {result.stderr.decode() if result.stderr else 'Unknown error'}")
    except Exception as e:
        print(f"Padded method exception: {e}")

    try:
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(video_path),
            "-vf", "thumbnail=300,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
            "-frames:v", "1",
            "-an",
            str(thumb_path)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
            print("Thumbnail extracted with thumbnail filter")
            return True
        else:
            print(f"Thumbnail filter failed: {result.stderr.decode() if result.stderr else 'Unknown error'}")
    except Exception as e:
        print(f"Thumbnail filter exception: {e}")

    return False


def download_file(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=20)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Error downloading file: {e}")
        return False

def add_play_icon(thumb_path: Path, play_icon_url: str, out_path: Path) -> bool:
    """Overlay the play icon (PNG) at the center of the thumbnail."""
    tmp_icon = TEMP_DIR / f"play_{uuid4().hex}.png"

    if not download_file(play_icon_url, tmp_icon):
        print("Play icon download failed.")
        return False

    try:
        thumb = Image.open(thumb_path).convert("RGBA")
        icon = Image.open(tmp_icon).convert("RGBA")

        target_w = min(int(thumb.width * 0.15), 150)
        icon_ratio = icon.width / icon.height
        target_h = int(target_w / icon_ratio)

        if hasattr(Image, 'Resampling'):
            icon = icon.resize((target_w, target_h), Image.Resampling.LANCZOS)
        else:
            icon = icon.resize((target_w, target_h), Image.ANTIALIAS)

        x = (thumb.width - target_w) // 2
        y = (thumb.height - target_h) // 2

        thumb.paste(icon, (x, y), icon)

        rgb = thumb.convert("RGB")
        rgb.save(out_path, format="JPEG", quality=85)

        tmp_icon.unlink(missing_ok=True)
        return True

    except Exception as e:
        print(f"Error adding play icon: {e}")
        try:
            tmp_icon.unlink(missing_ok=True)
        except:
            pass
        return False


def process_custom_thumbnail(image_path: Path, output_path: Path) -> bool:
    """Process custom thumbnail with smooth filter (scale + pad + sharpen)."""
    try:
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(image_path),
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,unsharp=5:5:1.0:5:5:0.0",
            "-q:v", "2",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            print("Custom thumbnail processed successfully")
            return True
        else:
            print(f"Custom thumbnail processing failed: {result.stderr.decode() if result.stderr else 'Unknown'}")
            return False
    except Exception as e:
        print(f"Custom thumbnail error: {e}")
        return False


def update_video_thumbnail_in_index(video_id: str, new_thumb_url: str):
    """Update thumbnail URL in metadata index for a specific video."""
    video_list = get_video_index()
    for video in video_list:
        if video.get('video_id') == video_id:
            video['thumburl'] = new_thumb_url
            video['thumburl_blur'] = new_thumb_url
            break

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=INDEX_FILE_KEY,
        Body=json.dumps(video_list, indent=2),
        ContentType='application/json'
    )
    print(f"Metadata index updated with new thumbnail for: {video_id}")


def update_github_page_thumbnail(video_id: str, new_thumb_url: str):
    """Update thumbnail in GitHub pages (both normal and safe)."""
    try:
        gh = Github(GITHUB_TOKEN)
        repo = gh.get_repo(GITHUB_REPO)

        page_name = f"{video_id}.html"
        safe_page_name = f"{video_id}_safe.html"

        for pname in [f"v/{page_name}", f"v/{safe_page_name}"]:
            try:
                file_content = repo.get_contents(pname)
                html = file_content.decoded_content.decode('utf-8')

                import re
                html = re.sub(r'property="og:image" content="[^"]*"', f'property="og:image" content="{new_thumb_url}"', html)
                html = re.sub(r'name="twitter:image" content="[^"]*"', f'name="twitter:image" content="{new_thumb_url}"', html)
                html = re.sub(r'poster="[^"]*"', f'poster="{new_thumb_url}"', html)

                repo.update_file(pname, f"Update thumbnail for {video_id}", html, file_content.sha)
                print(f"Updated GitHub page: {pname}")
            except Exception as e:
                print(f"Error updating {pname}: {e}")

        return True
    except Exception as e:
        print(f"GitHub update error: {e}")
        return False


# ---------------- CALLBACK HANDLER FOR ADD THUMBNAIL ----------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("add_thumb:"):
        video_id = data.split(":")[1]
        context.user_data["pending_thumb_for"] = video_id
        await query.message.reply_text(
            f"📸 Send your custom thumbnail image (JPG/PNG) for video:\n`{video_id}`\n\nImage will be padded to 1280x720 (no crop).",
            parse_mode="Markdown"
        )


# ---------------- PHOTO HANDLER FOR CUSTOM THUMBNAIL ----------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if ADMIN_USER_ID and msg.from_user.id != ADMIN_USER_ID:
        return

    video_id = context.user_data.get("pending_thumb_for")
    if not video_id:
        return await msg.reply_text("No pending thumbnail request. First click 'Add Thumbnail' button on a video link.")

    progress = await msg.reply_text("Processing custom thumbnail...")

    try:
        photo = msg.photo[-1]
        tg_file = await photo.get_file()

        temp_input = TEMP_DIR / f"custom_{uuid4().hex}.jpg"
        temp_output = TEMP_DIR / f"custom_{video_id}_final.jpg"

        file_bytes = await tg_file.download_as_bytearray()
        with open(temp_input, "wb") as f:
            f.write(file_bytes)

        await safe_edit(progress, "Applying smooth filter...")

        if not process_custom_thumbnail(temp_input, temp_output):
            return await safe_edit(progress, "Failed to process image. Try another image.")

        await safe_edit(progress, "Adding play button...")

        final_thumb = TEMP_DIR / f"custom_{video_id}_play.jpg"
        if not add_play_icon(temp_output, PLAY_ICON_URL, final_thumb):
            final_thumb = temp_output

        await safe_edit(progress, "Uploading to R2...")

        key_thumb = f"thumbs/{video_id}.jpg"
        s3.upload_file(
            str(final_thumb),
            R2_BUCKET,
            key_thumb,
            ExtraArgs={"ContentType": "image/jpeg"}
        )
        new_thumb_url = r2_public_url(key_thumb)

        await safe_edit(progress, "Updating metadata...")
        update_video_thumbnail_in_index(video_id, new_thumb_url)

        await safe_edit(progress, "Updating GitHub pages...")
        update_github_page_thumbnail(video_id, new_thumb_url)

        context.user_data.pop("pending_thumb_for", None)

        normal_link = f"{SITE_DOMAIN.rstrip('/')}/v/{video_id}.html"
        safe_link = f"{SITE_DOMAIN.rstrip('/')}/v/{video_id}_safe.html"

        await safe_edit(progress, f"✅ Custom thumbnail added successfully!\n\nLink: {normal_link}\nSafe: {safe_link}")

        for f in [temp_input, temp_output, final_thumb]:
            try:
                if f.exists():
                    f.unlink()
            except:
                pass

    except Exception as e:
        import traceback
        traceback.print_exc()
        await safe_edit(progress, f"Error: {e}")


# ---------------- MAIN BOT HANDLER ----------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if ADMIN_USER_ID and msg.from_user.id != ADMIN_USER_ID:
        return await msg.reply_text("Not allowed.")

    progress = await msg.reply_text("Starting...")

    local_video = None
    local_thumb = None
    final_thumb = None
    new_uuid = None

    try:
        video = msg.video or (msg.document if msg.document and msg.document.mime_type.startswith("video/") else None)

        if not video:
            return await safe_edit(progress, "Send a video file.")

        tg_file = await video.get_file()

        new_uuid = uuid4().hex
        fname = video.file_name or f"{new_uuid}.mp4"
        local_video = TEMP_DIR / fname

        await safe_edit(progress, "Downloading video...")

        file_bytes = await tg_file.download_as_bytearray()
        with open(local_video, "wb") as f:
            f.write(file_bytes)

        await safe_edit(progress, "Extracting thumbnail...")
        local_thumb = TEMP_DIR / f"{new_uuid}_raw.jpg"

        if not await asyncio.get_event_loop().run_in_executor(None, lambda: make_thumbnail(local_video, local_thumb)):
            return await safe_edit(progress, "Could not extract thumbnail from video.")

        final_thumb = TEMP_DIR / f"{new_uuid}_final.jpg"

        await safe_edit(progress, "Adding play button...")

        loop = asyncio.get_event_loop()
        overlay_success = await loop.run_in_executor(None, lambda: add_play_icon(local_thumb, PLAY_ICON_URL, final_thumb))
        if not overlay_success:
            final_thumb = local_thumb


        key_video = f"videos/{new_uuid}.mp4"
        fsize = local_video.stat().st_size

        uploaded = {"v": 0}
        loop = asyncio.get_event_loop()

        def cb(bytes_amt):
            uploaded["v"] += bytes_amt
            pct = int(uploaded["v"] / fsize * 100)
            if pct % 10 == 0:
                asyncio.run_coroutine_threadsafe(
                    safe_edit(progress, f"Uploading Video {pct}%"),
                    loop
                )

        def upload_video():
            s3.upload_file(
                str(local_video),
                R2_BUCKET,
                key_video,
                ExtraArgs={"ContentType": "video/mp4"},
                Config=transfer_config,
                Callback=cb
            )

        await loop.run_in_executor(None, upload_video)
        video_url = r2_public_url(key_video)


        await safe_edit(progress, "Uploading thumbnail...")

        def upload_thumb():
            key_thumb = f"thumbs/{new_uuid}.jpg"
            s3.upload_file(
                str(final_thumb),
                R2_BUCKET,
                key_thumb,
                ExtraArgs={"ContentType": "image/jpeg"}
            )
            return r2_public_url(key_thumb)
        
        thumb_url = await loop.run_in_executor(None, upload_thumb)


        blur_thumb = TEMP_DIR / f"{new_uuid}_blur.jpg"
        blur_thumb_url = None

        await safe_edit(progress, "Blurring thumbnail...")

        def create_blur_thumbnail():
            try:
                cmd = [
                    FFMPEG_BIN, "-y",
                    "-i", str(final_thumb),
                    "-vf", "gblur=sigma=30",
                    str(blur_thumb)
                ]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=30)

                key_thumb_blur = f"thumbs/{new_uuid}_blur.jpg"
                s3.upload_file(
                    str(blur_thumb),
                    R2_BUCKET,
                    key_thumb_blur,
                    ExtraArgs={"ContentType": "image/jpeg"}
                )
                return r2_public_url(key_thumb_blur)
            except Exception as blur_e:
                print(f"Blur thumbnail generation failed: {blur_e}")
                return None

        blur_thumb_url = await loop.run_in_executor(None, create_blur_thumbnail)


        title_options = [
            "🔥 देसी भाभी की चूत फाड़ दी 🍆 मोटे लंड से 💦",
            "🌾 गांव वाली रंडी को जंगल में चोदा 😈 full HD",
            "😛 साली ने जीजा का लंड चूसा 🍑 पूरा निगल लिया",
            "📹 मम्मी की गांड़ मारते हुए वीडियो लीक 🔥",
            "🎓 स्कूल गर्ल की पहली चुदाई 🔥 क्लास में",
            "🚿 बहन भाई का बाथरूम सेक्स कैम ❤️‍🔥",
            "💔 पत्नी को दोस्त ने चोदा 🍆 पति देखता रहा",
            "😈 आंटी की चूत में क्रीमी स्पर्म भरा 💦",
            "📚 टीचर ने स्टूडेंट को डेस्क पर ठोका 🥵",
            "💑 नवविवाहित जोड़ी की सुहागरात चुदाई 🔥",
            "💥 ससुर ने बहू की सील तोड़ दी 🍆 रात भर",
            "🏠 पड़ोसन रंडी को जबरदस्ती चोदा 😈",
            "🛏 मेड सर्वेंट को मालिक ने रंडी बनाया 💦",
            "🩺 डॉक्टर ने पेशेंट की चूत चाटी 🍑 हार्डकोर",
            "📸 गर्लफ्रेंड की हिडन कैम चुदाई लीक 💥",
            "🍒 बड़ी चूचियों वाली माल को ठोका वाइल्ड 🔥",
            "⏱ 5 मिनट में 3 बार चोदा 😛 इस हॉट लड़की को",
            "💣 सबसे मोटा लंड ने चूत फाड़ दी चिल्लाई 😈",
            "😴 लड़की बेहोश हो गई मोटी चुदाई से 💦",
            "🧑‍🤝‍🧑 एक लड़की 4 मर्दों ने ठोका 🔥 रात भर",
            "👹 मॉन्स्टर कॉक ने इंडियन चूत नष्ट कर दी 🍆",
            "💦 अनलिमिटेड कमशॉट भाभी के मुंह पर 😍",
            "⏳ 2 मिनट भी नहीं टिकेगा इस टाइट चूत के आगे 😛",
            "👀 पीओवी तेरी बहन को चोद रहा हूं लाइव 🔥",
            "🔥 वाइफ ने लवर से चुदवा ली फुल वीडियो 🍑",
            "🏢 ऑफिस गर्ल को बॉस ने लिफ्ट में चोदा 🍆",
            "🌟 देसी टीन की पहली एनल बिना दर्द 💦",
            "🐶 भाभी की मोटी गांड डॉगी स्टाइल में ठोकी 😈",
            "🚗 स्कूल टीचर स्टूडेंट के साथ कार चुदाई 🔥",
            "🍒 Tight chut wali desi को chod diya hard 🔥",
            "💥 Bhabhi ki gaand phaar diya 10 inch se 💦",
            "🍑 College girl first creampie le liya real 😛",
            "😈 Aunty ne muh mein cum swallow expert 🔥",
            "🏨 Padosan randi ko zabardasti fuck kiya 😱 hotel me",
            "🔞 Stepmom chudai 69 pose wild desi style 🍆",
            "💼 Boss ne secretary chut chaati office table pe 😈",
            "🍆 Didi bhai ke lund pe ride nonstop 💦",
            "🎥 GF hidden cam chudai leaked full HD 🍑",
            "🔥 Big boobs maal dabaya thoka doggy mein 💥",
            "⏱ 5 min 3 baar chhod diya hot ladki ko 😛",
            "💣 Mota lund ne pussy destroy screaming loud 💦",
            "🎯 Try not to cum desi hardcore challenge 😍",
            "🏡 Village ladki real first fuck no fake 💥",
            "👀 Wife cheating neighbor caught on cam 🔥",
            "⚠️ Stepbro stepsis anal mar diya hard 🍆",
            "👩‍🌾 Maid ko master ne randi banaya bed pe 😈",
            "🩺 Doctor patient fingering to full fuck 🍑",
            "💑 Honeymoon sex tape pati patni leaked 🔥",
            "🚫 No condom creampie GF ke andar bhara 😛"
        ]


        generated_title = random.choice(title_options)

        upload_time_ago = "just now"


        await safe_edit(progress, "Creating Link...")

        normal_page, safe_page = await loop.run_in_executor(
            None,
            lambda: generate_both_versions(
                video_url=video_url,
                thumb_url=thumb_url,
                video_id=new_uuid,
                title=generated_title,
                description="",
                time_ago=upload_time_ago,
                thumb_blur_url=blur_thumb_url
            )
        )


        new_video_entry = {
            "title": generated_title,
            "creator": "Content Creator",
            "video_url": video_url,
            "thumburl": thumb_url,
            "video_id": new_uuid,
            "time_ago": upload_time_ago,
            "description": "",
            "player_page_url": normal_page,
            "player_page_safe_url": safe_page,
            "thumburl_blur": blur_thumb_url,
        }

        await loop.run_in_executor(None, lambda: update_video_index(new_video_entry))

        keyboard = [[InlineKeyboardButton("📸 Add Thumbnail", callback_data=f"add_thumb:{new_uuid}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await progress.edit_text(
            f"✅ Done!\n\nLink: {normal_page}\nSafe preview: {safe_page}",
            reply_markup=reply_markup
        )


    except Exception as e:
        import traceback
        traceback.print_exc()
        await safe_edit(progress, f"Critical Error:\n{e}")

    finally:
        try:
            if local_video and local_video.exists():
                local_video.unlink()
            if local_thumb and local_thumb.exists() and local_thumb != final_thumb:
                local_thumb.unlink()

            if new_uuid:
                final_thumb_path = TEMP_DIR / f"{new_uuid}_final.jpg"
                blur_thumb_path = TEMP_DIR / f"{new_uuid}_blur.jpg"

                if final_thumb_path.exists():
                    final_thumb_path.unlink()
                if blur_thumb_path.exists():
                    blur_thumb_path.unlink()
        except Exception as cleanup_error:
            print(f"Cleanup error: {cleanup_error}")

# ---------------- START ----------------
if __name__ == "__main__":
    print("Clipfy Bot Started...")
    print(f"Admin ID: {ADMIN_USER_ID}")
    print(f"Play Icon URL: {PLAY_ICON_URL}")

    try:
        ensure_index_exists()
    except Exception as e:
        print(f"Warning: Could not ensure index exists: {e}")

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=120.0,
        write_timeout=120.0,
        pool_timeout=30.0
    )

    app = ApplicationBuilder().token(BOT_TOKEN).request(request).get_updates_request(request).build()

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_media))

    print("Bot is now polling for messages...")
    app.run_polling()


