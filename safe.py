#!/usr/bin/env python3
# Clipfy bot — FINAL FULL VERSION with Dynamic Suggested Videos

import os
import time
import asyncio
from uuid import uuid4
from pathlib import Path
from dotenv import load_dotenv
import subprocess
import shutil
import requests
from PIL import Image
import json # Added for JSON serialization

import boto3
from boto3.s3.transfer import TransferConfig
from github import Github

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes
)

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

# ---------------- METADATA INDEX MANAGEMENT (Dynamic Fix) ----------------

INDEX_FILE_KEY = "metadata/index.json"

def get_video_index():
    """Fetches the LIVE video index (list of all videos) from R2 storage."""
    try:
        response = s3.get_object(Bucket=R2_BUCKET, Key=INDEX_FILE_KEY)
        content = response['Body'].read()
        # Decode JSON content from the body
        return json.loads(content)
    except s3.exceptions.NoSuchKey:
        # If the index file doesn't exist, start with an empty list
        print("Index file not found on R2. Starting fresh.")
        return []
    except Exception as e:
        print(f"Error fetching video index: {e}")
        return []

def update_video_index(new_entry: dict):
    """Adds the new video entry to the index and updates index.json on R2."""
    video_list = get_video_index()
    # Check if entry already exists (using video_id as unique key)
    if not any(item['video_id'] == new_entry['video_id'] for item in video_list):
        video_list.append(new_entry)

    # Upload the updated JSON file back to R2
    s3.put_object(
        Bucket=R2_BUCKET,
        Key=INDEX_FILE_KEY,
        Body=json.dumps(video_list, indent=2),
        ContentType='application/json'
    )
    print(f"✅ Metadata index updated with new video: {new_entry['video_id']}")


def ensure_index_exists():
    """Ensure the metadata/index.json file exists in the R2 bucket.

    If it doesn't exist, create an empty list there so other operations are safe.
    """
    try:
        s3.head_object(Bucket=R2_BUCKET, Key=INDEX_FILE_KEY)
        print("✅ Metadata index exists on R2.")
    except Exception:
        print("⚠️ metadata/index.json not found — creating empty index on R2...")
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=INDEX_FILE_KEY,
            Body=json.dumps([]),
            ContentType='application/json'
        )
        print("✅ Created empty metadata/index.json on R2.")


# ---------------- BOT DATA LOGIC ----------------

def get_all_video_data():
    """Returns the live list of all videos from R2 to be injected into the template."""
    return get_video_index()


def clean_text(text: str) -> str:
    """Small sanitizer used for safe page titles/descriptions.

    Removes short unsafe words/emojis that are commonly used in clickbait titles.
    This is intentionally conservative.
    """
    if not text:
        return ""
    bad = ["💦", "🔥", "💋", "😈", "hot", "sexy", "fuck", "dangerous", "18+", "18"]
    safe = str(text)
    for b in bad:
        safe = safe.replace(b, "")
    # collapse whitespace
    return " ".join(safe.split()).strip()

# ---------------- GITHUB CLIENT ----------------
gh = Github(GITHUB_TOKEN)
repo = gh.get_repo(GITHUB_REPO)

# import helper that builds both normal + safe pages
def generate_both_versions(video_url: str, thumb_url: str, video_id: str, title: str, description: str, time_ago: str):
    """
    Generate two HTML files in the GitHub repo: normal and safe (blurred preview for social meta).
    Returns tuple: (normal_url, safe_url)
    """
    page_name = f"{video_id}.html"
    safe_page_name = f"{video_id}_safe.html"

    try:
        # Fetch two distinct templates from GitHub
        # NOTE: Ensure `template.html` and `template_safe.html` exist in your repo
        template = repo.get_contents("template.html").decoded_content.decode()
        safe_template = repo.get_contents("template_safe.html").decoded_content.decode()
    except Exception as e:
        print(f"Error fetching templates: {e}")
        raise Exception("Could not fetch templates from GitHub. Ensure template.html and template_safe.html exist.")

    # 2. Get All Videos Data and Prepare JSON (for suggested list)
    all_videos_data = get_all_video_data()
    all_videos_json_str = json.dumps(all_videos_data)

    # --- 1. NORMAL PAGE GENERATION ---
    normal_html = template.replace("{{VIDEO_URL}}", video_url)
    normal_html = normal_html.replace("{{THUMB_URL}}", thumb_url)
    normal_html = normal_html.replace("{{PLAYER_PAGE_URL}}", f"{SITE_DOMAIN.rstrip('/')}/v/{page_name}")
    normal_html = normal_html.replace("{{VIDEO_ID}}", video_id)
    normal_html = normal_html.replace("{{TITLE}}", title)
    normal_html = normal_html.replace("{{DESCRIPTION}}", description)
    normal_html = normal_html.replace("{{TIME_AGO}}", time_ago)
    normal_html = normal_html.replace("{{ALL_VIDEOS_JSON}}", all_videos_json_str)

    # --- 2. SAFE PAGE GENERATION (Ensure meta uses a blurred thumbnail) ---
    # safe pages should always use a blurred thumbnail for social previews.
    # We append '?blur=40' here because the repo's template_safe.html does not add it.
    # If your CDN does not support runtime blur query params, pre-generate a blurred
    # thumb and pass that (e.g. thumb_blur) instead — otherwise ?blur=40 generally works
    # with Cloudflare R2 + image transforms.
    safe_thumb = f"{thumb_url}?blur=40"

    # keep a cleaned version of title/description for safe page metadata
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

    # Create both files in the repo
    repo.create_file(f"v/{page_name}", f"Add video page {page_name}", normal_html)
    repo.create_file(f"v/{safe_page_name}", f"Add safe preview page {safe_page_name}", safe_html)

    return f"{SITE_DOMAIN.rstrip('/')}/v/{page_name}", f"{SITE_DOMAIN.rstrip('/')}/v/{safe_page_name}"

# NOTE: generate_page() was intentionally removed —
# we now always generate both a normal and a safe page using generate_both_versions().
# Keeping generate_page would be redundant and easy to mix up; generate_both_versions
# creates both files and is used everywhere in the handler.



# ---------------- HELPER FUNCTIONS ----------------

async def safe_edit(msg, text):
    try:
        await msg.edit_text(text)
    except:
        pass

def make_thumbnail(video_path: Path, thumb_path: Path) -> bool:
    """Extract single frame (1s or 2s) using ffmpeg."""
    # Try extracting at 1 second and produce a 1280x720 thumbnail while preserving aspect ratio.
    # If the frame is taller than 16:9, this adds vertical padding; if wider, it scales down.
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", "00:00:01",
        "-vframes", "1",
        "-vf", "scale=1280:-1:force_original_aspect_ratio=decrease,pad=1280:720:(1280-iw)/2:(720-ih)/2",
        str(thumb_path)
    ]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError:
        # Try fallback at 2s
        try:
            cmd[5] = "00:00:02"
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return True
        except:
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
    print(f"Attempting to overlay play icon from: {play_icon_url}")

    tmp_icon = TEMP_DIR / f"play_{uuid4().hex}.png"

    if not download_file(play_icon_url, tmp_icon):
        print("❌ Play icon download failed.")
        return False

    try:
        thumb = Image.open(thumb_path).convert("RGBA")
        icon = Image.open(tmp_icon).convert("RGBA")

        # --- SIZE FIX: Play button size ko 15% of thumbnail width, max 150px tak rakho ---
        target_w = min(int(thumb.width * 0.15), 150) # <- Size adjusted here

        # Keep aspect ratio
        icon_ratio = icon.width / icon.height
        target_h = int(target_w / icon_ratio)

        # Handle Pillow Version Differences (LANCZOS vs ANTIALIAS)
        if hasattr(Image, 'Resampling'):
            icon = icon.resize((target_w, target_h), Image.Resampling.LANCZOS)
        else:
            icon = icon.resize((target_w, target_h), Image.ANTIALIAS)

        # Calculate center position
        x = (thumb.width - target_w) // 2
        y = (thumb.height - target_h) // 2

        # Paste icon (using icon as mask for transparency)
        thumb.paste(icon, (x, y), icon)

        # Save as JPEG (RGB)
        rgb = thumb.convert("RGB")
        rgb.save(out_path, format="JPEG", quality=85)

        print("✅ Play button overlay successful!")
        tmp_icon.unlink(missing_ok=True)
        return True

    except Exception as e:
        print(f"❌ Error adding play icon: {e}")
        try:
            tmp_icon.unlink(missing_ok=True)
        except:
            pass
        return False

# ---------------- MAIN BOT HANDLER ----------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if ADMIN_USER_ID and msg.from_user.id != ADMIN_USER_ID:
        return await msg.reply_text("Not allowed.")

    progress = await msg.reply_text("⏳ Starting...")

    local_video = None
    local_thumb = None
    final_thumb = None

    try:
        video = msg.video or (msg.document if msg.document and msg.document.mime_type.startswith("video/") else None)

        if not video:
            return await safe_edit(progress, "Send a video file.")

        # 1. Download Video
        tg_file = await video.get_file()
        new_uuid = uuid4().hex # Generate UUID once for file name and video_id
        fname = video.file_name or f"{new_uuid}.mp4"
        local_video = TEMP_DIR / fname

        await safe_edit(progress, "📥 Downloading video...")
        await tg_file.download_to_drive(str(local_video))

        # 2. Extract Raw Thumbnail
        await safe_edit(progress, "🖼 Extracting thumbnail...")
        local_thumb = TEMP_DIR / (f"{new_uuid}_raw.jpg")
        if not make_thumbnail(local_video, local_thumb):
            return await safe_edit(progress, "❌ Could not extract thumbnail from video.")

        # 3. Overlay Play Button
        await safe_edit(progress, "🎨 Adding Play Button...")
        final_thumb = TEMP_DIR / (f"{new_uuid}_final.jpg")

        overlay_success = add_play_icon(local_thumb, PLAY_ICON_URL, final_thumb)

        if not overlay_success:
            print("⚠️ Overlay failed, using raw thumbnail.")
            final_thumb = local_thumb

        # 4. Upload Video
        key_video = f"videos/{new_uuid}.mp4"
        fsize = local_video.stat().st_size

        uploaded = {"v": 0}
        loop = asyncio.get_event_loop()

        def cb(bytes_amt):
            uploaded["v"] += bytes_amt
            pct = int(uploaded["v"] / fsize * 100)
            if pct % 10 == 0: # Update less frequently
                asyncio.run_coroutine_threadsafe(
                    safe_edit(progress, f"☁️ Uploading Video {pct}%"), loop
                )

        def upload_video_to_s3():
            s3.upload_file(
                str(local_video),
                R2_BUCKET,
                key_video,
                ExtraArgs={"ContentType": "video/mp4"},
                Config=transfer_config,
                Callback=cb
            )

        await loop.run_in_executor(None, upload_video_to_s3)
        video_url = r2_public_url(key_video)

        # 5. Upload Final Thumbnail
        key_thumb = f"thumbs/{new_uuid}.jpg"
        await safe_edit(progress, "📤 Uploading thumbnail...")

        s3.upload_file(
            str(final_thumb),
            R2_BUCKET,
            key_thumb,
            ExtraArgs={"ContentType": "image/jpeg"}
        )
        thumb_url = r2_public_url(key_thumb)

        # 6. Generate Metadata and Page
        await safe_edit(progress, "📝 Creating Link...")

        # --- Metadata Generation (Clickbait Titles) ---
        new_video_id = new_uuid  # The clean ID used for the .html file

        title_options = [
            "🥵 ये लड़की कैमरे के सामने क्या कर रही थी… आँखें हटेंगी नहीं!",
            "🔥 कमरे में अकेली थी… और फिर जो हुआ वो आप सोच भी नहीं सकते!",
            "😳 इस angle ने तो पूरा इंटरनेट पिघला दिया!",
            "😉 उसने सोचा कोई नहीं देख रहा… लेकिन कैमरा सब रिकॉर्ड कर रहा था!",
            "💦 ये clip देखने के बाद नींद उड़ जाएगी!",
            "🔥 इतने bold expressions… unbelievable!",
            "😍 उसका एक move… और दिल धड़कना रुक जाए!",
            "😈 इस video का last part… dangerous AF!",
            "😉 ये वीडियो अकेले में देखना, seriously!",
            "🥵 इतनी hot vibe? ये कैसे possible है!",
            "🔥 ये moment इतना close था कि सांसें थम जाएँ!",
            "😳 जिस तरह वो देख रही है… पूरा पक गया!",
            "🫣 ये देख कर पता नहीं क्यों body warm हो जाती है!",
            "💋 इस clip में उसकी eyes ही सबसे dangerous हैं!",
            "🔥 उसने जो move किया… वो 18+ से कम नहीं लगता!",
            "😉 इस वीडियो का end… बस WOW!",
            "😈 इतना bold कौन होता है camera on होते हुए?",
            "😍 इस clip में उसकी body language… next level!",
            "🥵 इतने seductive expressions… control करना मुश्किल!",
            "🔥 इस dress में वो literally आग थी!",
            "😳 ये वीडियो post ही नहीं करनी चाहिए थी… too hot!",
            "😉 उसने कैमरे को जो signal दिया… बस समझ जाओ!",
            "💦 ये vibe 18+ क्यों लग रही है?",
            "🔥 इस clip का zoomed moment — dangerous!",
            "😍 उसके बालों, चेहरे, हर चीज़ में कुछ अलग ही fire है!",
            "😈 इस angle को देखकर कोई भी पिघल जाएगा!",
            "😉 उसके moves इतने smooth… hypnotizing!",
            "🥵 इस video ने तो internet गर्म कर दिया!",
            "🔥 उसने जो pose मारा… बस वही viral हो गया!",
            "😳 ये clip देखने के बाद दिमाग गरम हो जाएगा!",
            "🔥 ये जो उसने किया… वो कोई नहीं करता!",
            "😉 इस video में हर second कुछ hot है!",
            "😍 ये beauty + attitude combo… lethal!",
            "😈 इस clip का middle moment… MOST intense!",
            "🥵 इस video ने सबको पागल कर दिया है!",
            "🔥 इस angle पर लाखों views आए हैं… कारण देखो!",
            "😉 इतनी bold vibe… देखने लायक!",
            "😳 उसने कैमरे के इतना पास आकर क्या किया?!",
            "💋 इस video का slow-motion part… irresistible!",
            "💦 उसने सोचा ये private है… पर clip leak हो गया!",
            "🔥 इस video की गर्मी स्क्रीन से बाहर आ रही है!",
            "😈 इस लड़की का confidence… insane!",
            "😉 इस clip को repeat करना पड़ेगा, trust me!",
            "🥵 उसकी body language… literally 🔥🔥🔥",
            "😍 आँखें उस पर से हटना impossible है!",
            "🔥 इस video में हर second seductive है!",
            "😳 उसने camera off समझ लिया था… पर on था!",
            "😉 इस तरह move कौन करता है live कैमरे पर?",
            "💋 ये clip soft है लेकिन vibes बहुत hard हैं!",
            "🔥 इस वीडियो ने viewers के दिमाग हिला दिए!"
        ]       
        
        
        
  
        import random
        generated_title = random.choice(title_options)
        
        upload_time_ago = "just now"
        # -----------------------------------------------

        normal_page, safe_page = await loop.run_in_executor(
            None,
            lambda: generate_both_versions(
                video_url=video_url,
                thumb_url=thumb_url,
                video_id=new_video_id,
                title=generated_title,
                description="",
                time_ago=upload_time_ago
            )
        )

        # 7. Update the Persistent Metadata Index on R2
        new_video_entry = {
            "title": generated_title,
            "creator": "Content Creator Name",
            "video_url": video_url,
            "thumb_url": thumb_url,
            "video_id": new_video_id,
            "time_ago": upload_time_ago,
            "description": "",
            "player_page_url": normal_page,
            "player_page_safe_url": safe_page,
        }

        await loop.run_in_executor(None, lambda: update_video_index(new_video_entry))

        await safe_edit(progress, f"🎉 **Done!**\n\nLink: {normal_page}\nSafe preview: {safe_page}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        await safe_edit(progress, f"❌ Error:\n{e}")

    finally:
        # Cleanup
        try:
            if local_video and local_video.exists():
                local_video.unlink()
            if local_thumb and local_thumb.exists() and local_thumb != final_thumb:
                local_thumb.unlink()
            if final_thumb and final_thumb.exists() and final_thumb != local_thumb:
                final_thumb.unlink()
        except Exception as cleanup_error:
            print(f"Cleanup error: {cleanup_error}")

# ---------------- START ----------------
if __name__ == "__main__":
    print("🚀 Clipfy Bot Started...")
    print(f"🔹 Admin ID: {ADMIN_USER_ID}")
    print(f"🔹 Play Icon URL: {PLAY_ICON_URL}")

    # Make sure index exists on R2 before starting
    try:
        ensure_index
