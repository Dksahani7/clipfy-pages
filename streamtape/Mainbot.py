#!/usr/bin/env python3
import os, json, uuid, subprocess, requests, html, re
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters, CallbackQueryHandler
from PIL import Image, ImageFilter, ImageDraw
import boto3
from github import Github, Auth
import asyncio
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
load_dotenv() 

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SITE_DOMAIN = os.getenv("SITE_DOMAIN")
R2_PUBLIC = os.getenv("R2_PUBLIC_URL")
R2_BUCKET = os.getenv("R2_BUCKET")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

UPLOAD_LOCK = asyncio.Lock()

# ================= CLIENTS =================
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("R2_SECRET_KEY")
)

gh = None
repo = None
try:
    if GITHUB_TOKEN and GITHUB_REPO:
        gh = Github(auth=Auth.Token(GITHUB_TOKEN))
        repo = gh.get_repo(GITHUB_REPO)
except Exception as e:
    print(f"⚠️ GitHub init failed: {e}")

# ================= CONFIG =================
DEFAULT_TITLE = "Clipfy Video"
HEADERS = {"User-Agent": "Mozilla/5.0"}
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/yourchannel")

# ================= VIRALKAND SCRAPING =================
def to_amp(url):
    """Convert URL to AMP version"""
    if url.endswith("/"):
        return url + "amp/"
    return url + "/amp/"

def get_posts_from_amp(page_url):
    """Scrape posts from AMP page using BeautifulSoup selectors"""
    try:
        amp_url = to_amp(page_url)
        r = requests.get(amp_url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Find all links that point to viralkand posts
        posts = soup.select("a[href*='viralkand.com/'][href*='-']")
        urls = list({a.get('href') for a in posts if a.get('href')})

        return urls
    except Exception as e:
        print(f"❌ AMP scrape error: {e}")
        return []

def extract_mp4(post_url):
    """Extract MP4 URL from post"""
    try:
        r = requests.get(post_url, headers=HEADERS, timeout=20)
        m = re.search(r'(https://[^"]+\.mp4)', r.text)
        return m.group(1) if m else None
    except Exception as e:
        print(f"⚠️ MP4 extract error: {e}")
        return None

def extract_title(post_url):
    """Extract title from post - removes all VIRALKAND.COM references"""
    try:
        r = requests.get(post_url, headers=HEADERS, timeout=20)
        m = re.search(r'<title>(.*?)</title>', r.text)
        if m:
            title = m.group(1)
            # Remove all variations of VIRALKAND references
            title = re.sub(r'[\s\-|]*VIRALKAND\.COM[\s\-|]*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'[\s\-|]*Viral Kand[\s\-|]*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'[\s\-|]*viralkand[\s\-|]*', '', title, flags=re.IGNORECASE)
            title = title.strip()
            return title if title else "Clipfy Video"
        return "Clipfy Video"
    except Exception as e:
        print(f"⚠️ Title extract error: {e}")
        return "Clipfy Video"

# ================= INDEX MANAGEMENT =================
INDEX_KEY = "index.json"

def read_index():
    """Read video list from R2"""
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=INDEX_KEY)
        data = json.loads(obj["Body"].read())
        if isinstance(data, list):
            return data
        return data.get("videos", [])
    except s3.exceptions.NoSuchKey:
        return []
    except Exception as e:
        print(f"⚠️ Read index error: {e}")
        return []

def is_already_uploaded(source_url=None, post_url=None, r2_url=None):
    """
    Check if video with same source URL, post URL, or R2 URL already exists
    Returns: (bool, video_entry or None)
    """
    try:
        videos = read_index()

        # Check by source_url (direct MP4 link)
        if source_url:
            for video in videos:
                if video.get("source_url") == source_url:
                    print(f"⚠️ Duplicate found by source_url: {video.get('videoid')}")
                    return True, video

        # Check by post_url (viralkand post)
        if post_url:
            for video in videos:
                if video.get("post_url") == post_url:
                    print(f"⚠️ Duplicate found by post_url: {video.get('videoid')}")
                    return True, video

        # Check by R2 URL (if video is already in R2)
        if r2_url:
            # Extract video ID from R2 URL
            # Example: https://r2.example.com/videos/tg_abc123.mp4
            for video in videos:
                stream_id = video.get("stream_id") or video.get("streamtape_id")
                if stream_id and f"videos/{stream_id}.mp4" in r2_url:
                    print(f"⚠️ Duplicate found by R2 URL: {video.get('videoid')}")
                    return True, video

        return False, None
    except Exception as e:
        print(f"⚠️ Duplicate check error: {e}")
        return False, None

def write_index(video_list):
    """Write video list to R2"""
    try:
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=INDEX_KEY,
            Body=json.dumps(video_list, indent=2),
            ContentType="application/json",
            ACL="public-read"
        )
        return True
    except Exception as e:
        print(f"❌ Write index error: {e}")
        return False

def add_video_to_index(video_entry):
    """Add new video to index (prevents duplicates)"""
    try:
        videos = read_index()

        # Check duplicate by stream_id (without .mp4 extension)
        stream_id = video_entry.get("stream_id") or video_entry.get("streamtape_id")
        if stream_id:
            # Normalize: remove .mp4 for comparison
            stream_id_clean = stream_id.replace(".mp4", "")
            exists = any(
                (v.get("stream_id", "").replace(".mp4", "") == stream_id_clean or 
                 v.get("streamtape_id", "").replace(".mp4", "") == stream_id_clean)
                for v in videos
            )
            if exists:
                print(f"⚠️ Video {stream_id} already exists in index")
                return False

        # Add to beginning of list
        videos.insert(0, video_entry)

        # Write back
        return write_index(videos)
    except Exception as e:
        print(f"❌ Add to index error: {e}")
        return False

# ================= DOWNLOAD FUNCTIONS =================
def partial_download(url: str, max_mb: int = 5) -> str:
    """Download only first N MB for thumbnail extraction"""
    try:
        max_bytes = max_mb * 1024 * 1024
        filename = f"partial_{uuid.uuid4().hex[:8]}.mp4"
        local_path = f"/tmp/{filename}"

        print(f"📥 Partial download (first {max_mb}MB) for thumbnail...")
        response = requests.get(url, timeout=60, stream=True)
        if response.status_code != 200:
            raise Exception(f"Download failed: {response.status_code}")

        with open(local_path, "wb") as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=1024*1024):
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded >= max_bytes:
                    break

        print(f"✅ Partial download: {downloaded / (1024*1024):.1f}MB")
        return local_path
    except Exception as e:
        raise Exception(f"Partial download error: {e}")

def full_download(url: str) -> str:
    """Download full video for Byse upload"""
    try:
        filename = f"remote_{uuid.uuid4().hex[:8]}.mp4"
        local_path = f"/tmp/{filename}"

        print(f"📥 Full download for Byse upload...")
        response = requests.get(url, timeout=300, stream=True)
        if response.status_code != 200:
            raise Exception(f"Download failed: {response.status_code}")

        file_size = 0
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024*1024):
                f.write(chunk)
                file_size += len(chunk)

        print(f"✅ Full download complete: {file_size / (1024*1024):.1f}MB")
        return local_path
    except Exception as e:
        raise Exception(f"Full download error: {e}")



# ================= THUMBNAIL (16:9 Perfect Letterbox) =================
def censor_thumbnail(img_path: str) -> str:
    """
    Center area blur + fire emoji overlay for adult content
    Returns path to censored image
    """
    try:
        img = Image.open(img_path).convert("RGB")
        w, h = img.size

        # Center box size (blur area)
        box_w = min(w // 3, 300)
        box_h = min(h // 3, 300)
        left = (w - box_w) // 2
        top = (h - box_h) // 2
        right = left + box_w
        bottom = top + box_h

        # Blur center region
        center = img.crop((left, top, right, bottom))
        center_blur = center.filter(ImageFilter.GaussianBlur(radius=20))
        img.paste(center_blur, (left, top))

        # Add fire emoji style overlay
        draw = ImageDraw.Draw(img)
        emoji_size = min(box_w, box_h) // 3

        # Two fire emojis
        positions = [
            (left + box_w * 0.35, top + box_h * 0.35),
            (left + box_w * 0.55, top + box_h * 0.45),
        ]

        for cx, cy in positions:
            x0 = int(cx - emoji_size / 2)
            y0 = int(cy - emoji_size / 2)
            x1 = int(cx + emoji_size / 2)
            y1 = int(cy + emoji_size / 2)

            # Outer circle (orange)
            draw.ellipse((x0, y0, x1, y1), fill=(255, 80, 0))

            # Inner circle (yellow)
            inner_pad = int(emoji_size * 0.2)
            draw.ellipse(
                (x0 + inner_pad, y0 + inner_pad, x1 - inner_pad, y1 - inner_pad),
                fill=(255, 160, 0),
            )

        # Save censored version
        censored_path = img_path.replace(".jpg", "_censored.jpg")
        img.save(censored_path, "JPEG", quality=90)
        print(f"🔒 Censored thumbnail created: {censored_path}")

        return censored_path

    except Exception as e:
        print(f"⚠️ Censor error: {e}")
        return img_path  # Return original if censoring fails


def extract_thumbnail_16_9(video_path: str, output_path: str, censor: bool = False):
    """
    Extract frame and fit to 16:9 with black bars (1280x720)
    If censor=True, applies blur + fire emoji to center
    """
    try:
        tmp_frame = output_path + "_raw.jpg"

        # Get video duration
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]

        try:
            duration_output = subprocess.run(
                probe_cmd, 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            duration = float(duration_output.stdout.strip() or "0")
            seek_time = max(2, duration * 0.25) if duration > 0 else 2
        except:
            seek_time = 2

        print(f"🎬 Extracting frame at {seek_time}s...")

        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, 
             "-ss", str(seek_time),
             "-vframes", "1", tmp_frame],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )

        TARGET_W, TARGET_H = 1280, 720
        TARGET_ASPECT = TARGET_W / TARGET_H  # 16:9 = 1.777...

        # Load frame
        frame = Image.open(tmp_frame).convert("RGB")
        fw, fh = frame.size
        frame_aspect = fw / fh

        print(f"📐 Original: {fw}x{fh} (ratio: {frame_aspect:.3f})")

        # Create black canvas
        canvas = Image.new('RGB', (TARGET_W, TARGET_H), color=(0, 0, 0))

        if abs(frame_aspect - TARGET_ASPECT) < 0.01:
            print("✅ Perfect 16:9 - resizing")
            resized = frame.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
            canvas = resized
        elif frame_aspect > TARGET_ASPECT:
            print("📏 Wider - adding top/bottom bars")
            new_w = TARGET_W
            new_h = int(TARGET_W / frame_aspect)
            resized = frame.resize((new_w, new_h), Image.Resampling.LANCZOS)
            y_offset = (TARGET_H - new_h) // 2
            canvas.paste(resized, (0, y_offset))
        else:
            print("📏 Taller - adding left/right bars")
            new_h = TARGET_H
            new_w = int(TARGET_H * frame_aspect)
            resized = frame.resize((new_w, new_h), Image.Resampling.LANCZOS)
            x_offset = (TARGET_W - new_w) // 2
            canvas.paste(resized, (x_offset, 0))

        # Add Play Button Overlay
        play_btn_path = "play_button.png"
        if os.path.exists(play_btn_path):
            try:
                play_btn = Image.open(play_btn_path).convert("RGBA")
                # Resize play button to ~20% of height (approx 144px)
                btn_h = 144
                btn_w = int(btn_h * (play_btn.width / play_btn.height))
                play_btn = play_btn.resize((btn_w, btn_h), Image.Resampling.LANCZOS)
                
                # Center the button
                offset_x = (TARGET_W - btn_w) // 2
                offset_y = (TARGET_H - btn_h) // 2
                canvas.paste(play_btn, (offset_x, offset_y), play_btn)
                print("🔘 Play button added to thumbnail")
            except Exception as e:
                print(f"⚠️ Play button overlay failed: {e}")

        canvas.save(output_path, "JPEG", quality=90)
        os.remove(tmp_frame)

        print(f"✅ Thumbnail created: {TARGET_W}x{TARGET_H}")

        # Apply censoring if requested
        if censor:
            censored_path = censor_thumbnail(output_path)
            return censored_path

        return output_path

    except subprocess.TimeoutExpired:
        raise Exception("Thumbnail extraction timeout (30s)")
    except Exception as e:
        raise Exception(f"Thumbnail generation failed: {e}")

def r2_put(local, key, max_retries=3):
    """Upload file to R2 and return public URL with retry logic"""
    for attempt in range(max_retries):
        try:
            content_type = "video/mp4" if key.endswith(".mp4") else "image/jpeg"
            s3.upload_file(
                local,
                R2_BUCKET,
                key,
                ExtraArgs={
                    "ACL": "public-read",
                    "ContentType": content_type
                }
            )
            url = f"{R2_PUBLIC}/{key}"
            print(f"✅ Uploaded to R2: {url}")
            return url
        except Exception as e:
            print(f"❌ R2 upload failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise

# ================= HTML PAGE =================
def create_watch_page_html(videoid, title, thumb, stream_id):
    """
    Single redirect page with FULL OG meta tags
    IMPORTANT: stream_id should be WITHOUT .mp4 extension
    """
    safe_title = html.escape(title)
    page_url = f"{SITE_DOMAIN}/watch/{videoid}.html"

    # Player URL - will redirect to player.html
    player_url = f"{SITE_DOMAIN}/streamtape/player.html?v={videoid}"

    return f"""<!doctype html>
<html prefix="og: http://ogp.me/ns#">
<head>
<meta charset="utf-8">
<title>{safe_title}</title>

<!-- Open Graph Meta Tags (Facebook, WhatsApp, Discord) -->
<meta property="og:type" content="video.other">
<meta property="og:title" content="{safe_title}">
<meta property="og:description" content="Watch full video on Clipfy">
<meta property="og:image" content="{thumb}">
<meta property="og:image:width" content="1280">
<meta property="og:image:height" content="720">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:url" content="{page_url}">
<meta property="og:site_name" content="Clipfy">

<!-- Twitter Card Meta Tags -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{safe_title}">
<meta name="twitter:description" content="Watch full video on Clipfy">
<meta name="twitter:image" content="{thumb}">
<meta name="twitter:site" content="@clipfy">

<!-- SEO Meta Tags -->
<meta name="description" content="{safe_title} - Watch on Clipfy">
<meta name="keywords" content="video, clipfy, watch, {safe_title}">

<!-- Redirect after 0.5 seconds (gives crawlers time to read meta) -->
<meta http-equiv="refresh" content="0.5;url={player_url}">

<style>
body {{
  background: #0f141a;
  color: #fff;
  font-family: Arial, sans-serif;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  margin: 0;
}}
.loader {{
  text-align: center;
}}
.spinner {{
  width: 40px;
  height: 40px;
  border: 4px solid rgba(255,255,255,0.1);
  border-top-color: #ff2f5b;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}}
@keyframes spin {{
  to {{ transform: rotate(360deg); }}
}}
</style>
</head>
<body>
<div class="loader">
  <div class="spinner"></div>
  <p>Loading video...</p>
</div>

<!-- Fallback JavaScript redirect -->
<script>
setTimeout(function(){{
  location.href = "{player_url}";
}}, 500);
</script>
</body>
</html>"""

def update_github_page(videoid, title, thumb, stream_id):
    """Create/update watch page on GitHub"""
    if not repo:
        print("⚠️ GitHub not configured")
        return False
    try:
        path = f"watch/{videoid}.html"
        html_content = create_watch_page_html(videoid, title, thumb, stream_id)

        try:
            file = repo.get_contents(path, ref=GITHUB_BRANCH)
            repo.update_file(
                path, f"update {videoid}",
                html_content,
                file.sha, branch=GITHUB_BRANCH
            )
            print(f"✅ Updated GitHub page: {path}")
        except:
            repo.create_file(
                path, f"add {videoid}",
                html_content,
                branch=GITHUB_BRANCH
            )
            print(f"✅ Created GitHub page: {path}")
        return True
    except Exception as e:
        print(f"❌ GitHub error: {e}")
        return False

# ================= CORE PROCESSING =================
async def process_existing_r2_video(r2_video_url: str, msg, context: ContextTypes.DEFAULT_TYPE):
    """
    Process a video that's ALREADY in R2 (skip uploading)
    Only: download → thumbnail → update index
    
    Args:
        r2_video_url: Full R2 video URL (e.g., https://r2.example.com/videos/tg_abc123.mp4)
        msg: Telegram message object
        context: Telegram context
    """
    partial_video = None
    thumb_path = None

    try:
        # Extract videoid from R2 URL
        # Example: https://r2.example.com/videos/tg_abc123.mp4
        match = re.search(r'videos/(tg_[a-f0-9]+)\.mp4', r2_video_url)
        if not match:
            await msg.edit_text("❌ Invalid R2 video URL format")
            return
        
        videoid = match.group(1)
        print(f"🔍 Processing existing R2 video: {videoid}")

        # Step 1: Partial download for thumbnail
        try:
            await msg.edit_text("⏳ (1/4) Downloading first 10MB for thumbnail...")
        except:
            pass
        
        partial_video = partial_download(r2_video_url, max_mb=10)

        # Step 2: Extract thumbnail
        try:
            await msg.edit_text("🎞 (2/4) Extracting thumbnail...")
        except:
            pass
        
        thumb_path = f"/tmp/{videoid}_thumb.jpg"
        extract_thumbnail_16_9(partial_video, thumb_path, censor=False)

        # Step 3: Upload thumbnail to R2
        try:
            await msg.edit_text("☁️ (3/4) Uploading thumbnail to R2...")
        except:
            pass
        
        thumb_key = f"thumbs/{videoid}.jpg"
        thumb_url = r2_put(thumb_path, thumb_key)

        # Step 4: Update index with thumbnail URL
        try:
            await msg.edit_text("📝 (4/4) Updating video index...")
        except:
            pass

        # Read existing index
        async with UPLOAD_LOCK:
            videos = read_index()
            
            # Find and update the existing video entry
            video_found = False
            for video in videos:
                stream_id = video.get("stream_id") or video.get("streamtape_id")
                if stream_id == videoid:
                    video["thumb"] = thumb_url
                    print(f"✅ Updated thumbnail for {videoid}")
                    video_found = True
                    break
            
            if video_found:
                write_index(videos)
                
                # Update GitHub page with new thumbnail
                title = video.get("title", "Clipfy Video")
                update_github_page(videoid, title, thumb_url, videoid)
            else:
                raise Exception(f"Video {videoid} not found in index")

        # Final reply
        watch_link = f"{SITE_DOMAIN}/watch/{videoid}.html"
        caption = (
            f"🎬 <b>✅ Already in your library!</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"▶️ <b>Watch Video Here:</b>\n"
            f"🔗 <a href='{watch_link}'>{watch_link}</a>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 <i>Thumbnail updated & ready to share!</i>"
        )

        try:
            await msg.chat.send_message(
                text=caption,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
            try:
                await msg.delete()
            except:
                pass
        except Exception as e:
            print(f"⚠️ Post failed: {e}")
            await msg.chat.send_message(f"✅ Thumbnail updated!\n\n🔗 Watch: {watch_link}")

        print(f"✅ Successfully processed existing R2 video: {videoid}")

    except Exception as e:
        error_msg = str(e)
        print(f"❌ R2 processing error: {error_msg}")
        try:
            await msg.edit_text(f"❌ Error: {error_msg}")
        except:
            pass
    finally:
        # Cleanup
        for temp_file in [partial_video, thumb_path]:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

async def process_remote_link(url: str, title: str, msg, context: ContextTypes.DEFAULT_TYPE, post_url: str = None):
    """
    Optimized processing pipeline:
    1. Check for duplicates (NEW)
    2. Partial download → thumbnail
    3. Full download → R2 upload (video)
    4. R2 upload (thumbnail) → Index update → GitHub
    Sends separate message for each completed video

    Args:
        url: Direct video URL (MP4, etc)
        title: Video title
        msg: Telegram message object
        context: Telegram context
        post_url: Optional viralkand post URL (for duplicate checking)
    """
    partial_video = None
    full_video = None
    thumb_path = None

    try:
        # Step 0: Check for duplicates BEFORE processing
        is_duplicate, existing_video = is_already_uploaded(source_url=url, post_url=post_url)

        if is_duplicate:
            watch_link = f"{SITE_DOMAIN}/watch/{existing_video.get('videoid')}.html"
            await msg.edit_text(
                f"⏭️ Video already uploaded! Skipping...\n\n"
                f"📌 Title: {existing_video.get('title', 'Unknown')}\n"
                f"🔗 Watch: {watch_link}\n\n"
                f"✅ Duplicate detection working!"
            )
            print(f"⏭️ Skipped duplicate: {url[:60]}")
            return

        videoid = f"tg_{uuid.uuid4().hex[:8]}"

        # Step 1: Partial download for thumbnail (FAST)
        try:
            await msg.edit_text("⏳ (1/6) Downloading first 10MB for thumbnail...")
        except Exception as e:
            print(f"⚠️ Status update failed: {e}")
        partial_video = partial_download(url, max_mb=10)

        # Step 2: Extract thumbnail WITHOUT censoring (for metadata)
        try:
            await msg.edit_text("🎞 (2/6) Extracting thumbnail...")
        except Exception as e:
            pass
        thumb_path = f"/tmp/{videoid}.jpg"
        # Extract WITHOUT censor for clean metadata/OG tags
        extract_thumbnail_16_9(partial_video, thumb_path, censor=False)

        # Step 3: Full download
        try:
            await msg.edit_text("📥 (3/6) Downloading full video...")
        except Exception as e:
            pass
        full_video = full_download(url)

        # Step 4: Upload to R2
        try:
            await msg.edit_text("📤 (4/6) Uploading to R2...")
        except Exception as e:
            pass
        r2_put(full_video, f"videos/{videoid}.mp4")
        stream_id = videoid

        # Step 5: Upload thumbnail to R2
        try:
            await msg.edit_text("☁️ (5/6) Uploading thumbnail to R2...")
        except Exception as e:
            pass
        thumb_key = f"thumbs/{videoid}.jpg"
        thumb_url = r2_put(thumb_path, thumb_key)

        # Step 6: Create video entry
        try:
            await msg.edit_text("📝 (6/6) Updating video index...")
        except Exception as e:
            pass

        video_entry = {
            "videoid": videoid,
            "title": title,
            "desc": "",
            "thumb": thumb_url,
            "safe_thumb": "",
            "stream_id": stream_id,  # videoid
            "streamtape_id": stream_id,  # Backward compatibility
            "views": 0,
            "offline": False,
            "date": datetime.now().isoformat(),
            "source": "telegram_bot",
            "source_url": url,  # Track original video URL
            "post_url": post_url if post_url else ""  # Track viralkand post URL if applicable
        }

        # Update index and GitHub
        async with UPLOAD_LOCK:
            success = add_video_to_index(video_entry)
            if not success:
                raise Exception("Failed to update video index (might be duplicate)")

            # Create GitHub page
            update_github_page(videoid, title, thumb_url, stream_id)

        # Final reply - SINGLE professional post with link preview
        watch_link = f"{SITE_DOMAIN}/watch/{videoid}.html"

        # Create professional caption with title and link
        caption = (
            f"🎬 <b>{title}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"▶️ <b>Watch Full Video Here:</b>\n"
            f"🔗 <a href='{watch_link}'>{watch_link}</a>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 <i>Join our channel for more!</i>"
        )

        # Send as a text message so Telegram can generate the link preview automatically
        try:
            await msg.chat.send_message(
                text=caption,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
            # Delete the status message
            try:
                await msg.delete()
            except:
                pass
        except Exception as e:
            print(f"⚠️ Post failed: {e}")
            # Fallback
            await msg.chat.send_message(f"✅ Video Uploaded!\n\n🔗 Watch: {watch_link}")

        print(f"✅ Successfully processed: {videoid}")

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Processing error: {error_msg}")
        try:
            await msg.edit_text(f"❌ Error: {error_msg}")
        except:
            pass
    finally:
        # Cleanup
        for temp_file in [partial_video, full_video, thumb_path]:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

# ================= BOT HANDLERS =================
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages with video URLs or viralkand pages"""
    msg = update.message
    text = msg.text.strip()

    # Check if viralkand page URL
    if "viralkand.com" in text and not text.endswith(".mp4"):
        await handle_viralkand_page(msg, text)
        return

    # Find R2 URLs first (for existing videos)
    r2_pattern = re.compile(r'https?://[^ \n\r\t]*\.r2\.cloudflarestorage\.com.*?\.mp4(?:\?\S*)?', re.IGNORECASE)
    r2_links = list(set(r2_pattern.findall(text)))

    if r2_links:
        status_msg = await msg.reply_text(f"🔍 Found {len(r2_links)} R2 video(s). Processing...\n\n⏳ Starting...")

        for i, link in enumerate(r2_links, 1):
            if len(r2_links) > 1:
                await status_msg.edit_text(f"🔍 Processing video {i}/{len(r2_links)}...\n\n⏳ Downloading & extracting...")

            await process_existing_r2_video(link.strip(), status_msg, context)

            if i < len(r2_links):
                await asyncio.sleep(2)

        if len(r2_links) > 1:
            await status_msg.edit_text(f"✅ All {len(r2_links)} videos processed!")
        return

    # Find direct video URLs (other sources)
    url_pattern = re.compile(
        r'https?://[^ \n\r\t]+?\.(?:mp4|m4v|mov|webm|avi|mkv)(?:\?\S*)?',
        re.IGNORECASE
    )
    links = list(set(url_pattern.findall(text)))

    if not links:
        await msg.reply_text(
            "❌ No video links found.\n\n"
            "Send either:\n"
            "1. Direct video URL (.mp4, .webm, etc)\n"
            "2. Video already in R2 (R2 URL)\n"
            "3. Viralkand page URL (to scrape all videos)"
        )
        return

    status_msg = await msg.reply_text(f"🔍 Found {len(links)} video link(s). Processing...\n\n⏳ Starting...")

    for i, link in enumerate(links, 1):
        if len(links) > 1:
            await status_msg.edit_text(f"🔍 Processing video {i}/{len(links)}...\n\n⏳ Downloading & extracting...")

        await process_remote_link(link.strip(), DEFAULT_TITLE, status_msg, context)

        if i < len(links):
            await asyncio.sleep(2)

    if len(links) > 1:
        await status_msg.edit_text(f"✅ All {len(links)} videos processed!")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video files sent directly to bot"""
    msg = update.message
    video = msg.video

    status_msg = await msg.reply_text("📥 (1/5) Downloading video from Telegram...")

    try:
        # Step 1: Telegram download
        file = await video.get_file()
        local_path = f"/tmp/tg_{uuid.uuid4().hex[:8]}.mp4"
        await file.download_to_drive(local_path)

        await status_msg.edit_text("🎞 (2/5) Extracting thumbnail...")
        thumb_path = f"/tmp/{uuid.uuid4().hex[:8]}.jpg"
        extract_thumbnail_16_9(local_path, thumb_path)

        videoid = f"tg_{uuid.uuid4().hex[:8]}"

        await status_msg.edit_text("📤 (3/5) Uploading to R2...")
        r2_put(local_path, f"videos/{videoid}.mp4")
        stream_id = videoid

        await status_msg.edit_text("☁️ (4/5) Uploading thumbnail to R2...")
        thumb_url = r2_put(thumb_path, f"thumbs/{videoid}.jpg")

        await status_msg.edit_text("📝 (5/5) Updating index...")
        video_entry = {
            "videoid": videoid,
            "title": DEFAULT_TITLE,
            "desc": "",
            "thumb": thumb_url,
            "safe_thumb": "",
            "stream_id": stream_id,
            "streamtape_id": stream_id,
            "views": 0,
            "offline": False,
            "date": datetime.now().isoformat(),
            "source": "telegram_upload"
        }

        async with UPLOAD_LOCK:
            add_video_to_index(video_entry)
            update_github_page(videoid, DEFAULT_TITLE, thumb_url, stream_id)

        watch_link = f"{SITE_DOMAIN}/watch/{videoid}.html"

        # Create safe caption
        caption = (
            f"🎬 <b>Clipfy Video</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"▶️ <b>Watch Full Video Here:</b>\n"
            f"🔗 <a href='{watch_link}'>{watch_link}</a>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 <i>Join our channel for more!</i>"
        )

        try:
            await msg.reply_text(
                text=caption,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
        except Exception as e:
            print(f"⚠️ Post failed: {e}")
            # Fallback
            await msg.reply_text(f"✅ Video Uploaded!\n\n🔗 {watch_link}")

        # Cleanup
        for f in [local_path, thumb_path]:
            if os.path.exists(f):
                os.remove(f)

    except Exception as e:
        await status_msg.edit_text(f"❌ Upload failed: {str(e)[:100]}")
        print(f"Video upload error: {e}")

async def handle_viralkand_page(msg, page_url):
    """Handle viralkand page scraping with duplicate detection"""
    status_msg = await msg.reply_text("🔄 Scraping viralkand page...")

    try:
        posts = get_posts_from_amp(page_url)
        if not posts:
            await status_msg.edit_text("❌ No posts found on this viralkand page")
            return

        await status_msg.edit_text(f"✅ Found {len(posts)} post(s). Checking for duplicates...")

        success_count = 0
        skipped_count = 0

        for i, post in enumerate(posts, 1):
            try:
                # Check if this post was already uploaded
                is_duplicate, existing_video = is_already_uploaded(post_url=post)

                if is_duplicate:
                    print(f"⏭️ Skipping duplicate post {i}/{len(posts)}: {post}")
                    skipped_count += 1
                    continue

                title = extract_title(post)
                mp4_url = extract_mp4(post)

                if mp4_url:
                    # Create a temporary status message for each video to avoid "Message to edit not found"
                    temp_status = await msg.chat.send_message(
                        f"⏳ Processing {i}/{len(posts)}: {title[:40]}...\n"
                        f"✅ Uploaded: {success_count} | ⏭️ Skipped: {skipped_count}"
                    )
                    
                    # Pass the temporary message for status updates
                    await process_remote_link(mp4_url, title, temp_status, None, post_url=post)
                    success_count += 1
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"Error processing post {i}: {e}")
                continue

        # Final summary
        await status_msg.edit_text(
            f"✅ Page processing complete!\n\n"
            f"📤 Uploaded: {success_count} new video(s)\n"
            f"⏭️ Skipped: {skipped_count} duplicate(s)\n"
            f"📊 Total: {len(posts)} post(s) found"
        )
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Scraping error: {str(e)[:100]}")
        except:
            await msg.reply_text(f"❌ Scraping error: {str(e)[:100]}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start message"""
    video_count = len(read_index())

    keyboard = [
        [InlineKeyboardButton("🔄 Sync Missing Pages", callback_data="sync_github")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"""🎬 **Clipfy Bot - Video Upload System**

📹 **How to use:**
Send me either:
1. Direct video URL (.mp4, .webm, etc)
2. Video file directly (MP4, MOV, etc)

🔥 **Features:**
✅ Auto-upload to R2
✅ 16:9 thumbnail with letterbox
✅ Social media preview working
✅ Instant admin panel sync
✅ Auto GitHub page creation

🛠 **Admin Tools:**
• Use the button below to generate missing GitHub pages for videos uploaded from the panel.

📊 **Current Stats:**
Total videos: {video_count}

**Example:**
`https://example.com/video.mp4`""",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def sync_github_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan index and create missing GitHub pages"""
    query = update.callback_query
    if query:
        await query.answer()
        status_msg = await query.message.reply_text("🔍 Scanning index for missing GitHub pages...")
    else:
        status_msg = await update.message.reply_text("🔍 Scanning index for missing GitHub pages...")
    
    try:
        videos = read_index()
        if not videos:
            await status_msg.edit_text("❌ Index is empty.")
            return

        missing = []
        # Check GitHub for each video page
        for v in videos:
            videoid = v.get("videoid")
            if not videoid: continue
            
            path = f"watch/{videoid}.html"
            try:
                # We use a lightweight check
                repo.get_contents(path, ref=GITHUB_BRANCH)
            except:
                missing.append(v)

        if not missing:
            await status_msg.edit_text("✅ All videos already have GitHub pages!")
            return

        total = len(missing)
        await status_msg.edit_text(f"Found {total} missing pages. Starting generation...")
        
        success = 0
        for i, v in enumerate(missing, 1):
            videoid = v.get("videoid")
            title = v.get("title", DEFAULT_TITLE)
            thumb = v.get("thumb")
            stream_id = v.get("stream_id", videoid)
            
            try:
                await status_msg.edit_text(f"⏳ Syncing {i}/{total}: {videoid}...")
            except:
                pass
                
            if update_github_page(videoid, title, thumb, stream_id):
                success += 1
            
            # Small delay to avoid GitHub API rate limits
            await asyncio.sleep(0.5)

        await status_msg.edit_text(f"✅ Sync Complete!\n\n🚀 Generated {success}/{total} missing pages.")
        
    except Exception as e:
        print(f"❌ Sync error: {e}")
        await status_msg.edit_text(f"❌ Sync failed: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats"""
    try:
        videos = read_index()
        total = len(videos)
        live = sum(1 for v in videos if not v.get("offline", False))
        offline = total - live
        total_views = sum(v.get("views", 0) for v in videos)
        bot_videos = sum(1 for v in videos if v.get("source") == "telegram_bot")

        await update.message.reply_text(
            f"""📊 **System Statistics**

📹 Total: {total}
✅ Live: {live}
❌ Offline: {offline}
👁 Views: {total_views:,}
🤖 Bot Uploads: {bot_videos}

Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}""",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Automatic fix command - cleans up index:
    1. Removes duplicate entries by stream_id, source_url, post_url
    2. Fixes invalid stream IDs
    """
    status_msg = await update.message.reply_text("🔧 Starting automatic cleanup...\n\n⏳ Please wait...")

    try:
        # Step 1: Get current index
        await status_msg.edit_text("🔧 (1/3) Reading current index...")
        videos = read_index()
        initial_count = len(videos)

        await status_msg.edit_text("🔧 (2/3) Cleaning up duplicates...")

        # Step 2: Clean up index
        removed_duplicates = 0
        fixed_codes = 0

        seen_stream_ids = set()
        seen_source_urls = set()
        seen_post_urls = set()
        cleaned_videos = []

        for video in videos:
            stream_id = (video.get("stream_id") or video.get("streamtape_id", "")).replace(".mp4", "")
            source_url = video.get("source_url", "")
            post_url = video.get("post_url", "")

            # Check 1: Duplicate by stream_id?
            if stream_id and stream_id in seen_stream_ids:
                removed_duplicates += 1
                print(f"🗑️ Removed duplicate (stream_id): {video.get('videoid')}")
                continue

            # Check 2: Duplicate by source_url?
            if source_url and source_url in seen_source_urls:
                removed_duplicates += 1
                print(f"🗑️ Removed duplicate (source_url): {video.get('videoid')}")
                continue

            # Check 3: Duplicate by post_url?
            if post_url and post_url in seen_post_urls:
                removed_duplicates += 1
                print(f"🗑️ Removed duplicate (post_url): {video.get('videoid')}")
                continue

            # Check 4: Fix invalid stream_id (has .mp4 extension)
            if stream_id and ".mp4" in (video.get("stream_id", "") or video.get("streamtape_id", "")):
                video["stream_id"] = stream_id
                video["streamtape_id"] = stream_id
                fixed_codes += 1
                print(f"🔧 Fixed stream_id: {video.get('videoid')}")

            # Add to cleaned list
            cleaned_videos.append(video)

            if stream_id:
                seen_stream_ids.add(stream_id)
            if source_url:
                seen_source_urls.add(source_url)
            if post_url:
                seen_post_urls.add(post_url)

        # Step 3: Write cleaned index
        await status_msg.edit_text("🔧 (3/3) Writing cleaned index...")
        write_index(cleaned_videos)

        # Summary
        final_count = len(cleaned_videos)
        total_removed = initial_count - final_count

        await status_msg.edit_text(
            f"""✅ **Cleanup Complete!**

📊 **Summary:**
• Initial videos: {initial_count}
• Final videos: {final_count}
• Total removed: {total_removed}

🗑️ **Removed:**
• Duplicates: {removed_duplicates}

🔧 **Fixed:**
• Invalid codes: {fixed_codes}

✨ Index is now clean!"""
        )

        print(f"✅ Cleanup complete: {initial_count} → {final_count} videos")

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Fix command error: {error_msg}")
        await status_msg.edit_text(f"❌ Cleanup failed: {error_msg[:200]}")

# ================= MAIN =================
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not found!")
        exit(1)

    print("=" * 50)
    print("🚀 Clipfy Bot - Starting...")
    print("=" * 50)

    # Validate environment
    print(f"✅ Bot Token: {'✓' if BOT_TOKEN else '✗'}")
    print(f"✅ R2 Bucket: {R2_BUCKET if R2_BUCKET else '✗'}")
    print(f"✅ R2 Public: {R2_PUBLIC if R2_PUBLIC else '✗'}")

    print(f"✅ GitHub: {'✓' if repo else '✗'}")
    print(f"✅ Domain: {SITE_DOMAIN if SITE_DOMAIN else '✗'}")

    # Check index
    try:
        current_videos = read_index()
        print(f"✅ Index: ✓ ({len(current_videos)} videos)")
    except Exception as e:
        print(f"⚠️ Index: Failed - {e}")

    print("=" * 50)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("fix", fix_command))
    app.add_handler(CommandHandler("sync", sync_github_pages))
    
    # Callback Handlers
    app.add_handler(CallbackQueryHandler(sync_github_pages, pattern="^sync_github$"))

    # Message Handlers
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    print("✅ Bot is running...")
    print("📱 Ready to receive video links!")

    app.run_polling()
