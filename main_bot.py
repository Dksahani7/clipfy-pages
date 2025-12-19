#!/usr/bin/env python3
import os, json, uuid, subprocess, random, requests, html, re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from PIL import Image, ImageFilter
import boto3
from github import Github, Auth
import asyncio
from typing import Optional

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
STREAM_LOGIN = os.getenv("STREAMTAPE_LOGIN")
STREAM_KEY = os.getenv("STREAMTAPE_KEY")
SITE_DOMAIN = os.getenv("SITE_DOMAIN")
R2_PUBLIC = os.getenv("R2_PUBLIC_URL")
R2_BUCKET = os.getenv("R2_BUCKET")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Global lock for safe updates
UPLOAD_LOCK = asyncio.Lock()

# ================= CLIENTS =================
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("R2_SECRET_KEY")
)

gh = Github(auth=Auth.Token(GITHUB_TOKEN))
repo = gh.get_repo(GITHUB_REPO)

# ================= CONFIG & DATA =================

DEFAULT_TITLES = [
    "Hot Video 🔥", "Exclusive Content 💋", "Must Watch 👀",
    "Trending Now 🌟", "Special Video ❤️"
]

def get_titles():
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key="config/titles.json")
        return json.loads(obj["Body"].read())
    except:
        save_titles(DEFAULT_TITLES)
        return DEFAULT_TITLES

def save_titles(titles):
    s3.put_object(
        Bucket=R2_BUCKET, Key="config/titles.json",
        Body=json.dumps(titles),
        ContentType="application/json",
        ACL="public-read"
    )

def get_blur_radius():
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key="config/blur.json")
        return json.loads(obj["Body"].read()).get("radius", 25)
    except:
        return 25

def set_blur_radius(radius: int):
    s3.put_object(
        Bucket=R2_BUCKET, Key="config/blur.json",
        Body=json.dumps({"radius": radius}),
        ContentType="application/json",
        ACL="public-read"
    )

def get_video_data(videoid):
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key="streamtape/index.json")
        data = json.loads(obj["Body"].read())
        for v in data:
            if v.get("videoid") == videoid:
                return v
    except:
        pass
    return None

def json_update(entry):
    """Safely updates the global video index."""
    key = "streamtape/index.json"
    data = []
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=key)
        data = json.loads(obj["Body"].read())
    except:
        pass

    if not any(e.get("streamtape_id") == entry["streamtape_id"] for e in data):
        data.insert(0, entry)
        s3.put_object(
            Bucket=R2_BUCKET, Key=key,
            Body=json.dumps(data),
            ContentType="application/json",
            ACL="public-read"
        )
        return True
    return False

def get_processed_stream_ids():
    """Returns set of already processed Streamtape IDs"""
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key="streamtape/index.json")
        data = json.loads(obj["Body"].read())
        return {v.get("streamtape_id") for v in data if v.get("streamtape_id")}
    except:
        return set()

# ================= STREAMTAPE API =================

def get_or_create_date_folder():
    today = datetime.now().strftime("%Y-%m-%d")
    r = requests.get(
        "https://api.streamtape.com/file/listfolder",
        params={"login": STREAM_LOGIN, "key": STREAM_KEY},
        timeout=30
    ).json()
    if r.get("status") == 200:
        folders = r.get("result", {}).get("folders", [])
        for f in folders:
            if f.get("name") == today:
                return f.get("id")

    cr = requests.get(
        "https://api.streamtape.com/file/createfolder",
        params={"login": STREAM_LOGIN, "key": STREAM_KEY, "name": today},
        timeout=30
    ).json()
    if cr.get("status") == 200:
        return cr.get("result", {}).get("folderid")

    raise Exception(f"Failed to get/create Streamtape folder: {cr.get('msg', 'Unknown error')}")

def streamtape_upload(path, folder_id=None):
    """Local file upload to Streamtape"""
    params = {"login": STREAM_LOGIN, "key": STREAM_KEY}
    if folder_id:
        params["folder"] = folder_id
    r = requests.get("https://api.streamtape.com/file/ul", params=params, timeout=30).json()
    if r.get("result") is None:
        raise Exception(f"Streamtape API error: {r.get('msg', 'Unknown error')}")

    upload_url = r["result"]["url"]
    up = requests.post(upload_url, files={"file1": open(path, "rb")}, timeout=600)
    up_json = up.json()

    if up_json.get("result") is None:
        raise Exception(f"Streamtape upload error: {up_json.get('msg', 'Unknown error')}")
    return up_json["result"]["id"]

def streamtape_remote_upload(url: str, folder_id: str):
    """Remote URL upload to Streamtape"""
    params = {
        "login": STREAM_LOGIN,
        "key": STREAM_KEY,
        "url": url,
        "folder": folder_id
    }
    r = requests.get("https://api.streamtape.com/file/remote_upload", params=params, timeout=30).json()

    if r.get("status") == 200 and r.get("result"):
        return r["result"]["remote_id"]
    else:
        raise Exception(f"Streamtape Remote Upload error: {r.get('msg', 'Unknown error')}")

async def check_remote_status(remote_id: str) -> str:
    """Checks remote upload status"""
    params = {
        "login": STREAM_LOGIN,
        "key": STREAM_KEY,
        "remote_id": remote_id
    }

    for _ in range(60):
        await asyncio.sleep(10)
        r = requests.get("https://api.streamtape.com/file/remote_upload_status", params=params, timeout=30).json()

        if r.get("status") == 200 and r.get("result"):
            job = r["result"][0]
            if job["status"] == 2:
                return job["file_code"]
            elif job["status"] == 3:
                raise Exception(f"Remote upload failed: {job.get('message', 'Unknown failure')}")
        else:
            raise Exception(f"Streamtape Status Check error: {r.get('msg', 'Unknown error')}")

    raise Exception("Remote upload timeout: The video took too long to process (10 minutes elapsed).")

def list_all_streamtape_videos():
    """Fetches all videos from Streamtape (across all folders)"""
    all_videos = []
    
    # Get all folders
    r = requests.get(
        "https://api.streamtape.com/file/listfolder",
        params={"login": STREAM_LOGIN, "key": STREAM_KEY},
        timeout=30
    ).json()
    
    if r.get("status") != 200:
        raise Exception(f"Failed to list folders: {r.get('msg', 'Unknown error')}")
    
    folders = r.get("result", {}).get("folders", [])
    
    # Add root folder files
    root_files = r.get("result", {}).get("files", [])
    all_videos.extend(root_files)
    
    # Get files from each folder
    for folder in folders:
        folder_id = folder.get("id")
        fr = requests.get(
            "https://api.streamtape.com/file/listfolder",
            params={"login": STREAM_LOGIN, "key": STREAM_KEY, "folder": folder_id},
            timeout=30
        ).json()
        
        if fr.get("status") == 200:
            folder_files = fr.get("result", {}).get("files", [])
            all_videos.extend(folder_files)
    
    return all_videos

# ================= THUMBNAILS & R2 =================

def make_thumbs(video, normal, blur):
    """Generates normal and blurred thumbnails"""
    try:
        tmp = normal + "_raw.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-ss", "00:00:01", "-t", "1",
             "-vframes", "1", tmp],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        TARGET_W, TARGET_H = 1280, 720
        radius = get_blur_radius()

        frame = Image.open(tmp).convert("RGB")
        fw, fh = frame.size

        scale = min(TARGET_W / fw, TARGET_H / fh)
        new_w = int(fw * scale)
        new_h = int(fh * scale)
        resized = frame.resize((new_w, new_h), Image.Resampling.LANCZOS)

        bg = frame.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius / 2))

        x = (TARGET_W - new_w) // 2
        y = (TARGET_H - new_h) // 2
        bg.paste(resized, (x, y))

        bg.save(normal, "JPEG", quality=90)

        safe_img = bg.filter(ImageFilter.GaussianBlur(radius))
        safe_img.save(blur, "JPEG", quality=90)

        os.remove(tmp)

    except Exception as e:
        raise Exception(f"Thumbnail generation failed: {e}")

def r2_put(local, key):
    s3.upload_file(local, R2_BUCKET, key, ExtraArgs={"ACL": "public-read"})
    return f"{R2_PUBLIC}/{key}"

def download_streamtape_screenshot(stream_id: str, local_path: str):
    """Downloads Streamtape's default screenshot"""
    thumb_url = f"https://streamtape.com/get_img.php?id={stream_id}&stream=1"

    try:
        r = requests.get(thumb_url, stream=True, timeout=15)
        if r.status_code == 200 and r.content and len(r.content) > 500:
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        return False
    except:
        return False

def get_streamtape_thumb(stream_id: str) -> str:
    return f"https://streamtape.com/get_img.php?id={stream_id}&stream=1"

def get_streamtape_splash_thumb(stream_id: str) -> str:
    """Fetch Streamtape thumbnail via API + fallback to direct URL (with retry logic)"""
    
    # METHOD 1: Try official getsplash API (best quality)
    for attempt in range(3):
        try:
            print(f"[Attempt {attempt+1}/3] Fetching getsplash API for {stream_id}...")
            splash_res = requests.get(
                "https://api.streamtape.com/file/getsplash",
                params={
                    "login": STREAM_LOGIN,
                    "key": STREAM_KEY,
                    "file": stream_id
                },
                timeout=15
            ).json()

            st_thumb_url = splash_res.get("result", {}).get("url")
            if not st_thumb_url:
                print(f"API returned empty URL for {stream_id}")
                continue

            print(f"Got API URL: {st_thumb_url}")
            
            # Download thumbnail image
            img_data = requests.get(st_thumb_url, timeout=15).content
            if not img_data or len(img_data) < 1000:
                print(f"Downloaded image too small: {len(img_data)} bytes")
                continue
            
            print(f"✅ API method SUCCESS: {len(img_data)} bytes downloaded")

            # Upload to R2
            thumb_key = f"thumbs/{stream_id}.jpg"
            s3.put_object(
                Bucket=R2_BUCKET,
                Key=thumb_key,
                Body=img_data,
                ContentType="image/jpeg",
                ACL="public-read"
            )

            return f"{R2_PUBLIC}/{thumb_key}"

        except Exception as e:
            print(f"API attempt {attempt+1} failed: {e}")
            if attempt < 2:
                import time
                time.sleep(2)  # Wait before retry
    
    # METHOD 2: Fallback to direct screenshot URL (as backup)
    print(f"API failed, trying direct screenshot URL for {stream_id}...")
    try:
        direct_url = f"https://streamtape.com/get_img.php?id={stream_id}&stream=1"
        img_data = requests.get(direct_url, timeout=15).content
        
        if img_data and len(img_data) > 1000:
            print(f"✅ Direct method SUCCESS: {len(img_data)} bytes downloaded")
            
            thumb_key = f"thumbs/{stream_id}.jpg"
            s3.put_object(
                Bucket=R2_BUCKET,
                Key=thumb_key,
                Body=img_data,
                ContentType="image/jpeg",
                ACL="public-read"
            )
            
            return f"{R2_PUBLIC}/{thumb_key}"
        else:
            print(f"Direct URL returned invalid image: {len(img_data)} bytes")
            
    except Exception as e:
        print(f"Direct method failed: {e}")
    
    print(f"❌ ALL methods failed for {stream_id}")
    return ""

# ================= META HTML & GITHUB =================

def meta_html_normal(videoid, title, thumb, stream_id):
    safe_title = html.escape(title)
    img = thumb
    PAGE_URL = f"{SITE_DOMAIN}/watch/{videoid}.html"
    PLAYER_URL = f"{SITE_DOMAIN}/streamtape/player.html?v={videoid}"

    return f"""<!doctype html>
<html prefix="og: http://ogp.me/ns#">                                                                                        
<head>
<meta charset="utf-8">
<title>{safe_title}</title>

<meta property="og:type" content="website">
<meta property="og:title" content="{safe_title}">
<meta property="og:description" content="Watch full video on Clipfy">
<meta property="og:image" content="{img}">
<meta property="og:url" content="{PAGE_URL}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{safe_title}">
<meta name="twitter:description" content="Watch full video on Clipfy">
<meta name="twitter:image" content="{img}">

<meta http-equiv="refresh" content="0;url={PLAYER_URL}">
</head>
<body></body>
</html>"""

def meta_html_safe(videoid, title, thumb, stream_id):
    safe_title = html.escape(title)
    img = thumb.replace(".jpg", "_blur.jpg")

    PAGE_URL = f"{SITE_DOMAIN}/watch/{videoid}-safe.html"
    PLAYER_URL = f"{SITE_DOMAIN}/streamtape/player.html?v={videoid}"

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{safe_title}</title>

<meta property="og:type" content="website">
<meta property="og:title" content="{safe_title}">
<meta property="og:description" content="Tap to watch full video">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1280">
<meta property="og:image:height" content="720">
<meta property="og:url" content="{PAGE_URL}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{img}">

</head>
<body>
<script>
  location.href = "{PLAYER_URL}";
</script>
</body>
</html>"""

def update_github_files(videoid, title, thumb, stream_id):
    try:
        path_normal = f"watch/{videoid}.html"
        path_safe = f"watch/{videoid}-safe.html"

        try:
            file_normal = repo.get_contents(path_normal, ref=GITHUB_BRANCH)
            repo.update_file(
                path_normal, "update normal meta",
                meta_html_normal(videoid, title, thumb, stream_id),
                file_normal.sha, branch=GITHUB_BRANCH
            )
        except:
            repo.create_file(
                path_normal, "add normal meta",
                meta_html_normal(videoid, title, thumb, stream_id),
                branch=GITHUB_BRANCH
            )

        try:
            file_safe = repo.get_contents(path_safe, ref=GITHUB_BRANCH)
            repo.update_file(
                path_safe, "update safe meta",
                meta_html_safe(videoid, title, thumb, stream_id),
                file_safe.sha, branch=GITHUB_BRANCH
            )
        except:
            repo.create_file(
                path_safe, "add safe meta",
                meta_html_safe(videoid, title, thumb, stream_id),
                branch=GITHUB_BRANCH
            )

        return True
    except Exception as e:
        print(f"GitHub update error: {e}")
        return False

# ================= CORE PROCESSING =================

async def process_video_and_send_result(msg, local_path, stream_id, source_type="telegram"):
    """Processes Local File Uploads"""
    n, b = None, None
    try:
        titles = get_titles()
        title = random.choice(titles) if titles else "Clipfy Video"
        vid = uuid.uuid4().hex[:8]
        n = f"/tmp/{vid}.jpg"
        b = f"/tmp/{vid}_blur.jpg"

        await msg.edit_text("🎞 Processing (Generating Thumbnails)...")
        make_thumbs(local_path, n, b)

        await msg.edit_text("☁️ Uploading Thumbnails to R2...")
        thumb = r2_put(n, f"thumbs/{vid}.jpg")
        r2_put(b, f"thumbs/{vid}_blur.jpg")

        async with UPLOAD_LOCK:
            json_update({
                "videoid": vid,
                "title": title,
                "thumb": thumb,
                "safe_thumb": thumb.replace(".jpg", "_blur.jpg"),
                "streamtape_id": stream_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": source_type
            })
            update_github_files(vid, title, thumb, stream_id)

        await msg.edit_text(
            f"""✅ **Upload Complete!**

📌 **Title:** {title}

🔥 **Normal Link:**
{SITE_DOMAIN}/watch/{vid}.html

🛡️ **Safe Link:**
{SITE_DOMAIN}/watch/{vid}-safe.html

📁 Folder: {datetime.now().strftime("%Y-%m-%d")}""",
            parse_mode="Markdown"
        )
    finally:
        if os.path.exists(local_path): os.remove(local_path)
        if n and os.path.exists(n): os.remove(n)
        if b and os.path.exists(b): os.remove(b)

async def remote_upload_and_process(chat_id, link: str, initial_msg, context: ContextTypes.DEFAULT_TYPE, is_manual=False, stream_id_override: Optional[str]=None):
    """Processes Remote Uploads and Manual Uploads"""
    n, b = None, None
    try:
        titles = get_titles()
        title = random.choice(titles) if titles else "Clipfy Video"
        vid = uuid.uuid4().hex[:8]
        n = f"/tmp/{vid}.jpg"
        b = f"/tmp/{vid}_blur.jpg"

        stream_id = stream_id_override
        source_type = "manual_upload" if is_manual else "remote_link"

        if not is_manual:
            await initial_msg.edit_text("⏳ (1/3) Uploading to Streamtape via Remote Upload...")
            folder_id = get_or_create_date_folder()
            remote_id = streamtape_remote_upload(link, folder_id)

            await initial_msg.edit_text(f"⏳ (2/3) Remote Upload Started. Checking status (ID: {remote_id})...")
            stream_id = await check_remote_status(remote_id)
        else:
            if not stream_id:
                raise Exception("Internal error: Stream ID not extracted for manual upload.")
            await initial_msg.edit_text("⏳ (1/2) Processing Manual Streamtape Upload...")

        await initial_msg.edit_text("🎞 (2/3) Processing (Attempting Streamtape Thumbnail Fetch)...")

        if not download_streamtape_screenshot(stream_id, n):
            await initial_msg.edit_text("⚠️ Streamtape screenshot failed. Using generic thumbnail.")
            img = Image.new('RGB', (1280, 720), color=(0, 0, 0))
            img.save(n, 'JPEG')

        radius = get_blur_radius()
        Image.open(n).filter(ImageFilter.GaussianBlur(radius)).save(b)

        await initial_msg.edit_text("☁️ (3/3) Uploading Thumbnails to R2...")
        thumb = r2_put(n, f"thumbs/{vid}.jpg")
        r2_put(b, f"thumbs/{vid}_blur.jpg")

        async with UPLOAD_LOCK:
            json_update({
                "videoid": vid,
                "title": title,
                "thumb": thumb,
                "safe_thumb": thumb.replace(".jpg", "_blur.jpg"),
                "streamtape_id": stream_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": source_type
            })
            update_github_files(vid, title, thumb, stream_id)

        await initial_msg.edit_text(
            f"""✅ **Process Complete!** ({'Manual Upload' if is_manual else 'Remote Link'})

📌 **Title:** {title}

🔥 **Normal Link:**
{SITE_DOMAIN}/watch/{vid}.html

🛡️ **Safe Link:**
{SITE_DOMAIN}/watch/{vid}-safe.html

📁 Streamtape ID: `{stream_id}`""",
            parse_mode="Markdown"
        )

    except Exception as e:
        await initial_msg.edit_text(f"❌ **Failed to process link:**\n`{str(e)}`", parse_mode="Markdown")
    finally:
        if n and os.path.exists(n): os.remove(n)
        if b and os.path.exists(b): os.remove(b)

# ================= SYNC FEATURE =================

async def sync_streamtape_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Syncs unprocessed Streamtape videos"""
    msg = update.message if update.message else update.callback_query.message
    
    status_msg = await msg.reply_text("🔄 **Starting Streamtape Sync...**\n\nFetching all videos from Streamtape...", parse_mode="Markdown")
    
    try:
        # Get all Streamtape videos
        all_videos = list_all_streamtape_videos()
        
        # Get already processed IDs (normalize to strings for safe comparison)
        processed_ids = {str(x) for x in get_processed_stream_ids()}

        # Filter unprocessed videos (avoid type-mismatch and empty IDs)
        new_videos = []
        for v in all_videos:
            sid = v.get("linkid")
            if sid is None:
                continue
            sid = str(sid)
            if sid and sid not in processed_ids:
                new_videos.append(v)
        
        if not new_videos:
            await status_msg.edit_text("✅ **Sync Complete!**\n\nNo new videos found. All videos are already processed.", parse_mode="Markdown")
            return
        
        await status_msg.edit_text(f"🔍 **Found {len(new_videos)} new video(s) to process!**\n\nStarting sync...", parse_mode="Markdown")
        
        success_count = 0
        error_count = 0
        
        for i, video in enumerate(new_videos, 1):
            stream_id = video.get("linkid")
            video_name = video.get("name", "Unknown")

            await status_msg.edit_text(
                f"🔄 **Processing {i}/{len(new_videos)}**\n\n"
                f"📹 Video: `{video_name[:40]}`\n"
                f"🆔 ID: `{stream_id}`",
                parse_mode="Markdown"
            )

            # --- Skip thumbnail / image files and non-video entries ---
            name = (video.get("name") or "").lower()
            if name.endswith((".jpg", ".jpeg", ".png", ".webp")):
                await status_msg.edit_text(f"⏭️ Skipping image file: `{video.get('name','')}`", parse_mode="Markdown")
                continue
            if name.startswith("thumb_"):
                await status_msg.edit_text(f"⏭️ Skipping streamtape auto-thumb: `{video.get('name','')}`", parse_mode="Markdown")
                continue
            if not name.endswith(".mp4"):
                await status_msg.edit_text(f"⏭️ Skipping non-mp4 file: `{video.get('name','')}`", parse_mode="Markdown")
                continue

            try:
                # Fetch Streamtape thumbnail and proxy via R2 (handles hotlink protection)
                final_r2_thumb = get_streamtape_splash_thumb(stream_id)
                
                if not final_r2_thumb:
                    await status_msg.edit_text(f"⏭️ Skipping (thumbnail fetch failed): `{video_name[:40]}`", parse_mode="Markdown")
                    continue

                title = random.choice(get_titles()) if get_titles() else "Clipfy Video"

                async with UPLOAD_LOCK:
                    json_update({
                        "videoid": stream_id,
                        "title": title,
                        "thumb": final_r2_thumb,
                        "streamtape_id": stream_id,
                        "source": "sync",
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

                success_count += 1

            except Exception as e:
                error_count += 1
                print(f"Error processing {stream_id}: {e}")
        
        # Final report
        await status_msg.edit_text(
            f"""✅ **Sync Complete!**

📊 **Results:**
✅ Successfully synced: {success_count}
❌ Errors: {error_count}
📁 Total processed: {len(new_videos)}

All synced videos are now live on website listing.""",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ **Sync Failed:**\n`{str(e)}`", parse_mode="Markdown")

# ================= BOT HANDLERS =================

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Telegram video uploads"""
    msg = update.message
    local = None
    initial_msg = await msg.reply_text("⏳ Uploading Telegram video...\n\n(1/3) Downloading video...")

    try:
        f = await context.bot.get_file(msg.video.file_id)
        local = f"/tmp/{uuid.uuid4().hex}.mp4"
        await f.download_to_drive(local)

        await initial_msg.edit_text("⏳ (2/3) ⬆️ Uploading to Streamtape...")
        folder_id = get_or_create_date_folder()
        stream_id = streamtape_upload(local, folder_id)

        await process_video_and_send_result(initial_msg, local, stream_id, "telegram")

    except Exception as e:
        await initial_msg.edit_text(f"❌ **Error during Telegram Video Upload:**\n`{str(e)}`", parse_mode="Markdown")
    finally:
        if local and os.path.exists(local): os.remove(local)

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages containing links"""
    msg = update.message
    text = msg.text

    url_pattern = re.compile(
        r'https?://(?:www\.)?(?:streamtape\.com/(?:v|e)/[a-zA-Z0-9]+|streampe\.(?:net|com)/v/[a-zA-Z0-9]+|[^ \n\r\t]+?\.(?:mp4|m4v|mov|webm)(?:\?\S*)?)', 
        re.IGNORECASE
    )

    links = list(set(url_pattern.findall(text)))

    if not links:
        return await handle_text(update, context, called_by_link_handler=True)

    initial_msg = await msg.reply_text(f"🔍 Found {len(links)} video link(s). Starting processing queue...")

    for i, link_str in enumerate(links):
        link_str = link_str.strip()

        await initial_msg.edit_text(f"➡️ **Processing Link {i+1} of {len(links)}...**\n`{link_str}`", parse_mode="Markdown")

        is_streamtape_manual = 'streamtape.com/v/' in link_str or 'streamtape.com/e/' in link_str
        stream_id = None

        if is_streamtape_manual:
            match = re.search(r'(v|e)/([a-zA-Z0-9]+)', link_str)
            if match:
                stream_id = match.group(2)

        try:
            if stream_id:
                await remote_upload_and_process(msg.chat_id, link_str, initial_msg, context, is_manual=True, stream_id_override=stream_id)
            else:
                await remote_upload_and_process(msg.chat_id, link_str, initial_msg, context)

        except Exception as e:
            await msg.reply_text(f"❌ **Failed to process link {i+1}:**\n`{link_str}`\n**Error:** `{str(e)}`", parse_mode="Markdown")

        if i < len(links) - 1:
            await initial_msg.edit_text(f"✅ Link {i+1} finished. Preparing for Link {i+2}...")

    await initial_msg.edit_text(f"✅ **All {len(links)} link(s) processed.**")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, called_by_link_handler=False):
    """Handles regular text input"""
    text = update.message.text

    if context.user_data.get("waiting_for") == "new_title":
        titles = get_titles()
        titles.append(text)
        save_titles(titles)
        context.user_data["waiting_for"] = None
        await update.message.reply_text(f"✅ Title added: {text}")
    elif not called_by_link_handler:
        pass


# ... (Pichle code ke aage ka hissa)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 View Titles", callback_data="view_titles")],
        [InlineKeyboardButton("➕ Add Title", callback_data="add_title"),
         InlineKeyboardButton("➖ Remove Title", callback_data="remove_title")],
        [InlineKeyboardButton("🔄 Sync Streamtape Videos", callback_data="sync_videos")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"),
         InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🎬 **Clipfy Video Bot**\n\n"
        f"Aap mujhe koi bhi **Video** bhej sakte hain ya **Streamtape/Direct Link** "
        f"paste kar sakte hain. Main unhe process karke aapko Normal aur Safe links de dunga.\n\n"
        f"**Current Blur Radius:** `{get_blur_radius()}`\n"
        f"**Titles Loaded:** `{len(get_titles())}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# ================= CALLBACK HANDLERS =================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "view_titles":
        titles = get_titles()
        text = "📋 **Current Titles:**\n\n" + "\n".join([f"- {t}" for t in titles])
        await query.edit_message_text(text, parse_mode="Markdown")

    elif query.data == "add_title":
        context.user_data["waiting_for"] = "new_title"
        await query.edit_message_text("📝 Agla message jo aap bhejenge wo Title ki list mein add ho jayega. Title bhejiye:")

    elif query.data == "remove_title":
        titles = get_titles()
        if len(titles) > 1:
            removed = titles.pop()
            save_titles(titles)
            await query.edit_message_text(f"✅ Last title remove kar diya gaya: `{removed}`", parse_mode="Markdown")
        else:
            await query.edit_message_text("⚠️ Kam se kam ek title hona zaroori hai.")

    elif query.data == "sync_videos":
        await sync_streamtape_videos(update, context)

    elif query.data == "stats":
        try:
            obj = s3.get_object(Bucket=R2_BUCKET, Key="streamtape/index.json")
            data = json.loads(obj["Body"].read())
            count = len(data)
        except:
            count = 0
        await query.edit_message_text(f"📊 **Bot Stats**\n\nTotal Videos Processed: `{count}`", parse_mode="Markdown")

    elif query.data == "help":
        help_text = (
            "📖 **Help Guide**\n\n"
            "1. **Video Bhejein:** Seedha Telegram se video file upload karein.\n"
            "2. **Link Bhejein:** Streamtape ka link ya kisi MP4 file ka direct URL paste karein.\n"
            "3. **Sync:** Streamtape par pehle se uploaded videos ko website listing me live karta hai (no extra pages).\n\n"
            "Note: Manual uploads (Telegram/Remote) will still generate thumbnails and update GitHub/R2 as before."
        )
        await query.edit_message_text(help_text, parse_mode="Markdown")

# ================= MAIN RUNNER =================

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN environment variable nahi mila!")
        exit(1)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("sync", sync_streamtape_videos))

    # Message Handlers
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    
    # Callback Handlers (Buttons)
    app.add_handler(CallbackQueryHandler(button_callback))

    print("🚀 Clipfy Bot Start ho gaya hai...")
    app.run_polling()
    
