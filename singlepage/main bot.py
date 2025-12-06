#!/usr/bin/env python3
# -------------------------------------------------------------
#  CLIPFY SINGLE-PAGE BOT  — FINAL MERGED VERSION (FULL FILE)
# -------------------------------------------------------------
# Purpose:
#  - Upload video files (Telegram) or accept R2 public video URLs
#  - Extract thumbnail, overlay play icon, create blurred safe thumb
#  - Upload assets to R2
#  - Maintain a SEPARATE singlepage/index.json on R2 (do NOT touch old metadata/index.json)
#  - Provide 2 links per video:
#       Twitter player link:  <SINGLEPAGE_BASE_URL>?v=VIDEOID&t=1
#       Safe link:            <SINGLEPAGE_BASE_URL>?v=VIDEOID&safe=1
#  - Commands: /link, /twitter, /safe
#  - Admin-only upload/thumbnail actions controlled by ADMIN_USER_ID env var (optional)
#
# Requirements:
#   pip install python-telegram-bot==20.7 python-dotenv boto3 pillow requests
#
# Environment variables expected:
#   BOT_TOKEN, ADMIN_USER_ID (optional), R2_ACCOUNT_ID, R2_ACCESS_KEY,
#   R2_SECRET_KEY, R2_BUCKET, R2_PUBLIC_URL, R2_ENDPOINT (optional),
#   SINGLEPAGE_BASE_URL, PLAY_ICON_URL (optional)
#
# -------------------------------------------------------------

import os
import sys
import time
import asyncio
import random
import subprocess
from uuid import uuid4
from pathlib import Path
import json
from dotenv import load_dotenv
import requests
from PIL import Image

import boto3
from boto3.s3.transfer import TransferConfig

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest

# ---------------- LOAD ENV ----------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is required in environment")
    sys.exit(1)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))  # 0 = no admin restriction

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET", "videos")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

SINGLEPAGE_BASE_URL = os.getenv("SINGLEPAGE_BASE_URL", "https://clipfy.store/singlepage/player.html")
PLAY_ICON_URL = os.getenv("PLAY_ICON_URL", "https://pub-51338658718349efb6e5193255e4131b.r2.dev/kindpng_2115738.png")

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")

# R2 endpoint default
if not R2_ENDPOINT:
    if R2_ACCOUNT_ID:
        R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    else:
        R2_ENDPOINT = None

# validate R2 public url
if not R2_PUBLIC_URL:
    print("ERROR: R2_PUBLIC_URL required (public base URL for uploaded objects)")
    sys.exit(1)

# ---------------- S3 CLIENT (R2) ----------------
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
)

transfer_config = TransferConfig(
    multipart_threshold=20 * 1024 * 1024,
    multipart_chunksize=10 * 1024 * 1024,
)

def r2_public_url(key: str) -> str:
    return f"{R2_PUBLIC_URL.rstrip('/')}/{key.lstrip('/')}"

# ---------------- singlepage index key (isolated) ----------------
SINGLEPAGE_INDEX_KEY = "singlepage/index.json"

def get_singlepage_index():
    try:
        resp = s3.get_object(Bucket=R2_BUCKET, Key=SINGLEPAGE_INDEX_KEY)
        body = resp["Body"].read()
        return json.loads(body)
    except s3.exceptions.NoSuchKey:
        return []
    except Exception as e:
        print("get_singlepage_index error:", e)
        return []

def put_singlepage_index(arr):
    s3.put_object(Bucket=R2_BUCKET, Key=SINGLEPAGE_INDEX_KEY, Body=json.dumps(arr, indent=2), ContentType="application/json")

def add_entry_to_index(entry: dict):
    arr = get_singlepage_index()
    # avoid duplicate entry by videoid
    arr = [x for x in arr if x.get("videoid") != entry.get("videoid")]
    arr.insert(0, entry)
    put_singlepage_index(arr)

# ---------------- utilities ----------------
def is_video_url(text: str) -> bool:
    if not isinstance(text, str): return False
    text = text.split("?")[0].lower()
    return text.endswith((".mp4", ".mov", ".webm", ".mkv"))

def run_cmd(cmd, timeout=30):
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return out.returncode == 0, out
    except Exception as e:
        print("run_cmd error", e)
        return False, None

# ---------------- thumbnail helpers ----------------
def make_thumbnail_from_file(video_path: Path, out_thumb: Path) -> bool:
    # try a few timestamps
    timestamps = ["00:00:01.5", "00:00:02", "00:00:00.5", "00:00:03"]
    for ts in timestamps:
        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", ts,
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
            str(out_thumb)
        ]
        ok, _ = run_cmd(cmd, timeout=20)
        if ok and out_thumb.exists() and out_thumb.stat().st_size > 0:
            return True
    return False

def make_thumbnail_from_url(url: str, out_thumb: Path) -> bool:
    timestamps = ["00:00:01.5", "00:00:02", "00:00:00.5"]
    for ts in timestamps:
        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", ts,
            "-i", url,
            "-vframes", "1",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
            str(out_thumb)
        ]
        ok, _ = run_cmd(cmd, timeout=25)
        if ok and out_thumb.exists() and out_thumb.stat().st_size > 0:
            return True
    return False

def add_play_icon(thumb_path: Path, out_path: Path, play_icon_url: str = PLAY_ICON_URL) -> bool:
    try:
        # download icon
        tmp_icon = TEMP_DIR / f"icon_{uuid4().hex}.png"
        r = requests.get(play_icon_url, timeout=15)
        r.raise_for_status()
        tmp_icon.write_bytes(r.content)

        base = Image.open(thumb_path).convert("RGBA")
        icon = Image.open(tmp_icon).convert("RGBA")

        # scale icon relative to base
        target_w = int(base.width * 0.18)
        if target_w < 40: target_w = 40
        icon_ratio = icon.width / icon.height
        icon = icon.resize((target_w, int(target_w / icon_ratio)))

        x = (base.width - icon.width) // 2
        y = (base.height - icon.height) // 2

        base.paste(icon, (x, y), icon)
        base.convert("RGB").save(out_path, quality=85)

        try: tmp_icon.unlink(missing_ok=True)
        except: pass
        return True
    except Exception as e:
        print("add_play_icon error:", e)
        return False

def make_blur_image(in_path: Path, out_path: Path) -> bool:
    try:
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(in_path),
            "-vf", "gblur=sigma=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black",
            str(out_path)
        ]
        ok, _ = run_cmd(cmd, timeout=20)
        return ok and out_path.exists()
    except Exception as e:
        print("make_blur_image error:", e)
        return False

# ---------------- R2 upload helpers ----------------
def upload_file_to_r2(local_path: Path, key: str, content_type: str = None):
    ExtraArgs = {}
    if content_type:
        ExtraArgs["ContentType"] = content_type
    s3.upload_file(str(local_path), R2_BUCKET, key, ExtraArgs=ExtraArgs, Config=transfer_config)
    return r2_public_url(key)

# ---------------- singlepage link maker ----------------
def make_singlepage_links(videoid: str):
    vid = videoid.strip()
    twitter = f"{SINGLEPAGE_BASE_URL}?v={vid}&t=1"
    safe = f"{SINGLEPAGE_BASE_URL}?v={vid}&safe=1"
    return twitter, safe

# ---------------- TELEGRAM HANDLERS ----------------

async def safe_edit(msg, text):
    try:
        await msg.edit_text(text)
    except:
        pass

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = ("Clipfy single-page bot\n\n"
           "Commands:\n"
           "/link VIDEOID — returns both links\n"
           "/twitter VIDEOID — returns twitter link\n"
           "/safe VIDEOID — returns safe link\n\n"
           "Send a video file (or a public R2 video URL) to upload.")
    await update.message.reply_text(txt)

async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /link VIDEOID")
    vid = args[0]
    tw, sf = make_singlepage_links(vid)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Twitter", url=tw)], [InlineKeyboardButton("Safe", url=sf)]])
    await update.message.reply_text(f"Links for `{vid}`:\n\nTwitter:\n{tw}\n\nSafe:\n{sf}", parse_mode="Markdown", reply_markup=kb)

async def cmd_twitter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /twitter VIDEOID")
    vid = args[0]
    tw, _ = make_singlepage_links(vid)
    await update.message.reply_text(tw)

async def cmd_safe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /safe VIDEOID")
    vid = args[0]
    _, sf = make_singlepage_links(vid)
    await update.message.reply_text(sf)

# Callback handler for inline buttons (e.g., add_thumb)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("add_thumb:"):
        vid = data.split(":", 1)[1]
        context.user_data["pending_thumb_for"] = vid
        await query.message.reply_text(f"Send the thumbnail image (JPG/PNG) to attach for video `{vid}`", parse_mode="Markdown")

# Photo handler - for adding a custom thumbnail
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # restrict to admin if ADMIN_USER_ID set
    if ADMIN_USER_ID and msg.from_user.id != ADMIN_USER_ID:
        return
    pending_vid = context.user_data.get("pending_thumb_for")
    if not pending_vid:
        return await msg.reply_text("No pending thumbnail request. Use the Add Thumbnail button first.")
    progress = await msg.reply_text("Processing thumbnail...")
    try:
        photo = msg.photo[-1]
        tg_file = await photo.get_file()
        local_in = TEMP_DIR / f"thumb_in_{uuid4().hex}.jpg"
        local_out = TEMP_DIR / f"thumb_out_{pending_vid}.jpg"
        bytes_arr = await tg_file.download_as_bytearray()
        local_in.write_bytes(bytes_arr)

        # process: scale & add play icon
        ok = make_thumbnail_from_file(local_in, local_out)  # will try ffmpeg; this may not be ideal for static images but ok
        if not ok:
            # fallback: just copy input to out (resize by PIL)
            im = Image.open(local_in).convert("RGB")
            im = im.resize((1280, 720), Image.LANCZOS)
            im.save(local_out, quality=85)

        add_play_icon(local_out, local_out)

        key_thumb = f"thumbs/{pending_vid}.jpg"
        upload_file_to_r2(local_out, key_thumb, content_type="image/jpeg")
        thumb_url = r2_public_url(key_thumb)

        # blurred
        blur_local = TEMP_DIR / f"thumb_blur_{pending_vid}.jpg"
        make_blur_image(local_out, blur_local)
        key_blur = f"thumbs/{pending_vid}_blur.jpg"
        upload_file_to_r2(blur_local, key_blur, content_type="image/jpeg")
        blur_url = r2_public_url(key_blur)

        # update index entry if exists, else create minimal
        arr = get_singlepage_index()
        found = False
        for it in arr:
            if it.get("videoid") == pending_vid:
                it["thumb"] = thumb_url
                it["safe_thumb"] = blur_url
                found = True
                break
        if not found:
            new_entry = {
                "videoid": pending_vid,
                "videourl": "",  # unknown
                "thumb": thumb_url,
                "safe_thumb": blur_url,
                "title": f"Video {pending_vid[:6]}",
                "creator": "Clipfy",
                "views": 0,
                "likes": 0,
                "timeago": "unknown"
            }
            arr.insert(0, new_entry)
        put_singlepage_index(arr)

        context.user_data.pop("pending_thumb_for", None)
        await progress.edit_text(f"✅ Thumbnail uploaded and index updated.\nThumb: {thumb_url}\nSafe: {blur_url}")
    except Exception as e:
        print("handle_photo error:", e)
        await safe_edit(progress, f"Error: {e}")

# Main handler for video files
async def handle_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if ADMIN_USER_ID and msg.from_user.id != ADMIN_USER_ID:
        return await msg.reply_text("Not allowed.")

    progress = await msg.reply_text("Starting video upload...")
    try:
        video = msg.video or (msg.document if msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/") else None)
        if not video:
            return await safe_edit(progress, "No video found in message.")

        tg_file = await video.get_file()

        vid = uuid4().hex
        local_video = TEMP_DIR / f"{vid}.mp4"
        await safe_edit(progress, "Downloading video...")
        bytes_arr = await tg_file.download_as_bytearray()
        local_video.write_bytes(bytes_arr)

        await safe_edit(progress, "Extracting thumbnail...")
        raw_thumb = TEMP_DIR / f"{vid}_raw.jpg"
        ok_thumb = make_thumbnail_from_file(local_video, raw_thumb)
        if not ok_thumb:
            # attempt fallback: use ffmpeg without scale (best-effort)
            cmd = [FFMPEG_BIN, "-y", "-i", str(local_video), "-vframes", "1", str(raw_thumb)]
            run_cmd(cmd)
        final_thumb = TEMP_DIR / f"{vid}_final.jpg"
        if not add_play_icon(raw_thumb, final_thumb):
            # if overlay failed, fallback to raw_thumb
            final_thumb = raw_thumb

        await safe_edit(progress, "Uploading video to R2...")
        key_video = f"videos/{vid}.mp4"
        s3.upload_file(str(local_video), R2_BUCKET, key_video, ExtraArgs={"ContentType": "video/mp4"}, Config=transfer_config)
        video_url = r2_public_url(key_video)

        await safe_edit(progress, "Uploading thumbnail to R2...")
        key_thumb = f"thumbs/{vid}.jpg"
        s3.upload_file(str(final_thumb), R2_BUCKET, key_thumb, ExtraArgs={"ContentType": "image/jpeg"})
        thumb_url = r2_public_url(key_thumb)

        await safe_edit(progress, "Creating blurred thumbnail...")
        blur_local = TEMP_DIR / f"{vid}_blur.jpg"
        make_blur_image(final_thumb, blur_local)
        key_blur = f"thumbs/{vid}_blur.jpg"
        s3.upload_file(str(blur_local), R2_BUCKET, key_blur, ExtraArgs={"ContentType": "image/jpeg"})
        blur_url = r2_public_url(key_blur)

        # create index entry (singlepage index)
        entry = {
            "videoid": vid,
            "videourl": video_url,
            "thumb": thumb_url,
            "safe_thumb": blur_url,
            "title": f"Video {vid[:6]}",
            "creator": "Uploader",
            "views": random.randint(1000, 50000),
            "likes": random.randint(10, 2000),
            "timeago": "just now",
        }
        add_entry_to_index(entry)

        tw, sf = make_singlepage_links(vid)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Add custom thumbnail", callback_data=f"add_thumb:{vid}")]])

        await progress.edit_text(f"✅ Uploaded!\n\nTwitter: {tw}\nSafe: {sf}", reply_markup=kb)
    except Exception as e:
        print("handle_video_upload error:", e)
        await safe_edit(progress, f"Error: {e}")
    finally:
        # cleanup local files
        try:
            for f in TEMP_DIR.glob(f"*{vid}*"):
                try: f.unlink()
                except: pass
        except:
            pass

# Process public R2 video URL sent as text
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = (msg.text or "").strip()
    if not text:
        return
    # only handle if it's a direct video URL
    if is_video_url(text):
        # if ADMIN restriction, check
        if ADMIN_USER_ID and msg.from_user.id != ADMIN_USER_ID:
            return await msg.reply_text("Not allowed.")
        await process_r2_video_url(msg, text)

async def process_r2_video_url(msg, url: str):
    progress = await msg.reply_text("Processing remote video URL...")
    try:
        vid = uuid4().hex
        raw_thumb = TEMP_DIR / f"{vid}_raw.jpg"

        await safe_edit(progress, "Extracting thumbnail from URL...")
        ok = make_thumbnail_from_url(url, raw_thumb)
        if not ok:
            return await safe_edit(progress, "Could not extract thumbnail from URL.")

        final_thumb = TEMP_DIR / f"{vid}_final.jpg"
        add_play_icon(raw_thumb, final_thumb)

        await safe_edit(progress, "Uploading thumbnail...")
        key_thumb = f"thumbs/{vid}.jpg"
        s3.upload_file(str(final_thumb), R2_BUCKET, key_thumb, ExtraArgs={"ContentType": "image/jpeg"})
        thumb_url = r2_public_url(key_thumb)

        await safe_edit(progress, "Creating blurred thumbnail...")
        blur_local = TEMP_DIR / f"{vid}_blur.jpg"
        make_blur_image(final_thumb, blur_local)
        key_blur = f"thumbs/{vid}_blur.jpg"
        s3.upload_file(str(blur_local), R2_BUCKET, key_blur, ExtraArgs={"ContentType": "image/jpeg"})
        blur_url = r2_public_url(key_blur)

        # create entry and add to index (we don't upload video since it's remote)
        entry = {
            "videoid": vid,
            "videourl": url,
            "thumb": thumb_url,
            "safe_thumb": blur_url,
            "title": url.split("/")[-1].split("?")[0],
            "creator": "Remote Uploader",
            "views": random.randint(100, 20000),
            "likes": random.randint(0, 1000),
            "timeago": "just now",
        }
        add_entry_to_index(entry)

        tw, sf = make_singlepage_links(vid)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Add custom thumbnail", callback_data=f"add_thumb:{vid}")]])
        await progress.edit_text(f"✅ Done!\n\nTwitter: {tw}\nSafe: {sf}", reply_markup=kb)
    except Exception as e:
        print("process_r2_video_url error:", e)
        await safe_edit(progress, f"Error: {e}")
    finally:
        # cleanup
        try:
            for f in TEMP_DIR.glob(f"*{vid}*"):
                try: f.unlink()
                except: pass
        except:
            pass

# ---------------- START BOT ----------------
def main():
    print("Starting Clipfy single-page bot...")
    # basic checks
    try:
        subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, timeout=5)
    except Exception:
        print("Warning: ffmpeg not available or not in PATH. Thumbnail functions may fail.")

    req = HTTPXRequest(connect_timeout=30.0, read_timeout=120.0, write_timeout=120.0, pool_timeout=30.0)
    app = ApplicationBuilder().token(BOT_TOKEN).request(req).build()

    # commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("twitter", cmd_twitter))
    app.add_handler(CommandHandler("safe", cmd_safe))

    # callbacks / media
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("Bot polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
