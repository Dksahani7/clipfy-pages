#!/usr/bin/env python3
import os, json, uuid, subprocess, random, requests, html
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from PIL import Image, ImageFilter
import boto3
from github import Github, Auth

BOT_TOKEN = os.getenv("BOT_TOKEN")
STREAM_LOGIN = os.getenv("STREAMTAPE_LOGIN")
STREAM_KEY = os.getenv("STREAMTAPE_KEY")
SITE_DOMAIN = os.getenv("SITE_DOMAIN")
R2_PUBLIC = os.getenv("R2_PUBLIC_URL")
R2_BUCKET = os.getenv("R2_BUCKET")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("R2_SECRET_KEY")
)

gh = Github(auth=Auth.Token(GITHUB_TOKEN))
repo = gh.get_repo(GITHUB_REPO)

DEFAULT_TITLES = [
    "Hot Video 🔥",
    "Exclusive Content 💋",
    "Must Watch 👀",
    "Trending Now 🌟",
    "Special Video ❤️"
]

WAITING_TITLE, WAITING_NEW_TITLE, WAITING_THUMB = range(3)

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

def update_video_data(videoid, new_data):
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key="streamtape/index.json")
        data = json.loads(obj["Body"].read())
        for i, v in enumerate(data):
            if v.get("videoid") == videoid:
                data[i].update(new_data)
                break
        s3.put_object(
            Bucket=R2_BUCKET, Key="streamtape/index.json",
            Body=json.dumps(data),
            ContentType="application/json",
            ACL="public-read"
        )
        return True
    except:
        return False

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
    return None

def streamtape_upload(path, folder_id=None):
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

def make_thumbs(video, normal, blur):
    subprocess.run(["ffmpeg", "-y", "-i", video, "-ss", "00:00:01", "-vframes", "1", normal], check=True)
    Image.open(normal).filter(ImageFilter.GaussianBlur(25)).save(blur)

def r2_put(local, key):
    s3.upload_file(local, R2_BUCKET, key, ExtraArgs={"ACL": "public-read"})
    return f"{R2_PUBLIC}/{key}"

def json_update(entry):
    key = "streamtape/index.json"
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=key)
        data = json.loads(obj["Body"].read())
    except:
        data = []
    data.insert(0, entry)
    s3.put_object(
        Bucket=R2_BUCKET, Key=key,
        Body=json.dumps(data),
        ContentType="application/json",
        ACL="public-read"
    )

def meta_html(videoid, title, thumb, stream_id, safe=False):
    safe_title = html.escape(title)
    img = thumb if not safe else thumb.replace(".jpg", "_blur.jpg")
    q = f"?v={videoid}" + ("&safe=1" if safe else "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{safe_title}</title>
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{safe_title}">
<meta name="twitter:image" content="{img}">
<meta name="twitter:player" content="{SITE_DOMAIN}/player.html{q}">
<meta name="twitter:player:width" content="720">
<meta name="twitter:player:height" content="405">
<meta name="twitter:player:stream" content="https://streamtape.com/e/{stream_id}">
<meta name="twitter:player:stream:content_type" content="text/html">
<meta property="og:type" content="video.other">
<meta property="og:title" content="{safe_title}">
<meta property="og:image" content="{img}">
<meta property="og:video" content="https://streamtape.com/e/{stream_id}">
<meta property="og:video:type" content="text/html">
<meta http-equiv="refresh" content="0;url={SITE_DOMAIN}/player.html{q}">
</head><body></body></html>"""

def update_github_files(videoid, title, thumb, stream_id):
    try:
        path_normal = f"streamtape/v/{videoid}.html"
        path_safe = f"streamtape/v/{videoid}-safe.html"
        try:
            file_normal = repo.get_contents(path_normal, ref=GITHUB_BRANCH)
            repo.update_file(path_normal, "update", meta_html(videoid, title, thumb, stream_id), file_normal.sha, branch=GITHUB_BRANCH)
        except:
            repo.create_file(path_normal, "add", meta_html(videoid, title, thumb, stream_id), branch=GITHUB_BRANCH)
        try:
            file_safe = repo.get_contents(path_safe, ref=GITHUB_BRANCH)
            repo.update_file(path_safe, "update", meta_html(videoid, title, thumb, stream_id, True), file_safe.sha, branch=GITHUB_BRANCH)
        except:
            repo.create_file(path_safe, "add", meta_html(videoid, title, thumb, stream_id, True), branch=GITHUB_BRANCH)
        return True
    except Exception as e:
        print(f"GitHub update error: {e}")
        return False

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    titles = get_titles()
    keyboard = [
        [InlineKeyboardButton("📋 View Titles", callback_data="view_titles")],
        [InlineKeyboardButton("➕ Add Title", callback_data="add_title"), InlineKeyboardButton("➖ Remove Title", callback_data="remove_title")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"), InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"""🎬 **Clipfy Video Bot**

Welcome! Send me a video and I'll upload it to Streamtape with embed links.

📌 **Features:**
• Auto upload to Streamtape
• Daily folders for organization
• Random titles from your list
• Twitter/OG embed support
• Change title & thumbnail anytime

📝 **Current Titles:** {len(titles)}
📁 **Today's Folder:** {datetime.now().strftime("%Y-%m-%d")}

Send a video to get started!""",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "view_titles":
        titles = get_titles()
        text = "📋 **Current Titles:**\n\n"
        for i, t in enumerate(titles, 1):
            text += f"{i}. {t}\n"
        await query.edit_message_text(text, parse_mode="Markdown")
    
    elif data == "add_title":
        await query.edit_message_text("📝 Send me the new title to add:")
        context.user_data["waiting_for"] = "new_title"
    
    elif data == "remove_title":
        titles = get_titles()
        keyboard = []
        for i, t in enumerate(titles):
            keyboard.append([InlineKeyboardButton(f"❌ {t[:30]}", callback_data=f"del_{i}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_start")])
        await query.edit_message_text("Select title to remove:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("del_"):
        idx = int(data.split("_")[1])
        titles = get_titles()
        if 0 <= idx < len(titles):
            removed = titles.pop(idx)
            save_titles(titles)
            await query.edit_message_text(f"✅ Removed: {removed}")
        else:
            await query.edit_message_text("❌ Invalid selection")
    
    elif data == "stats":
        try:
            obj = s3.get_object(Bucket=R2_BUCKET, Key="streamtape/index.json")
            videos = json.loads(obj["Body"].read())
            total = len(videos)
        except:
            total = 0
        await query.edit_message_text(f"📊 **Stats:**\n\n🎬 Total Videos: {total}\n📅 Date: {datetime.now().strftime('%Y-%m-%d')}", parse_mode="Markdown")
    
    elif data == "help":
        await query.edit_message_text(
            """❓ **Help:**

1. Send any video to upload
2. Bot creates daily folders
3. Random title is assigned
4. Get Normal & Safe links
5. Use buttons to change title/thumb

**Commands:**
/start - Main menu
/titles - View titles""",
            parse_mode="Markdown"
        )
    
    elif data == "back_to_start":
        keyboard = [
            [InlineKeyboardButton("📋 View Titles", callback_data="view_titles")],
            [InlineKeyboardButton("➕ Add Title", callback_data="add_title"), InlineKeyboardButton("➖ Remove Title", callback_data="remove_title")],
            [InlineKeyboardButton("📊 Stats", callback_data="stats"), InlineKeyboardButton("❓ Help", callback_data="help")]
        ]
        await query.edit_message_text("🎬 **Clipfy Bot** - Main Menu", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    elif data.startswith("chg_title_"):
        videoid = data.replace("chg_title_", "")
        titles = get_titles()
        keyboard = []
        for i, t in enumerate(titles):
            keyboard.append([InlineKeyboardButton(t[:40], callback_data=f"set_title_{videoid}_{i}")])
        keyboard.append([InlineKeyboardButton("✏️ Custom Title", callback_data=f"custom_title_{videoid}")])
        await query.edit_message_text("Select new title:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("set_title_"):
        parts = data.replace("set_title_", "").split("_")
        videoid, idx = parts[0], int(parts[1])
        titles = get_titles()
        if 0 <= idx < len(titles):
            new_title = titles[idx]
            vdata = get_video_data(videoid)
            if vdata:
                update_video_data(videoid, {"title": new_title})
                update_github_files(videoid, new_title, vdata["thumb"], vdata["streamtape_id"])
                await query.edit_message_text(f"✅ Title updated to: {new_title}")
            else:
                await query.edit_message_text("❌ Video not found")
    
    elif data.startswith("custom_title_"):
        videoid = data.replace("custom_title_", "")
        context.user_data["custom_title_for"] = videoid
        await query.edit_message_text("📝 Send me the custom title:")
    
    elif data.startswith("chg_thumb_"):
        videoid = data.replace("chg_thumb_", "")
        context.user_data["new_thumb_for"] = videoid
        await query.edit_message_text("📷 Send me a new thumbnail image:")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if context.user_data.get("waiting_for") == "new_title":
        titles = get_titles()
        titles.append(text)
        save_titles(titles)
        context.user_data["waiting_for"] = None
        await update.message.reply_text(f"✅ Title added: {text}")
    
    elif context.user_data.get("custom_title_for"):
        videoid = context.user_data["custom_title_for"]
        vdata = get_video_data(videoid)
        if vdata:
            update_video_data(videoid, {"title": text})
            update_github_files(videoid, text, vdata["thumb"], vdata["streamtape_id"])
            await update.message.reply_text(f"✅ Title updated to: {text}")
        else:
            await update.message.reply_text("❌ Video not found")
        context.user_data["custom_title_for"] = None

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("new_thumb_for"):
        videoid = context.user_data["new_thumb_for"]
        vdata = get_video_data(videoid)
        if vdata:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            local = f"/tmp/{videoid}_new.jpg"
            blur_local = f"/tmp/{videoid}_new_blur.jpg"
            await file.download_to_drive(local)
            Image.open(local).filter(ImageFilter.GaussianBlur(25)).save(blur_local)
            thumb = r2_put(local, f"thumbs/{videoid}.jpg")
            r2_put(blur_local, f"thumbs/{videoid}_blur.jpg")
            update_video_data(videoid, {"thumb": thumb, "safe_thumb": thumb.replace(".jpg", "_blur.jpg")})
            update_github_files(videoid, vdata["title"], thumb, vdata["streamtape_id"])
            await update.message.reply_text("✅ Thumbnail updated!")
        else:
            await update.message.reply_text("❌ Video not found")
        context.user_data["new_thumb_for"] = None

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    try:
        await msg.reply_text("⬆️ Uploading to Streamtape...")
        
        f = await context.bot.get_file(msg.video.file_id)
        local = f"/tmp/{uuid.uuid4().hex}.mp4"
        await f.download_to_drive(local)
        
        folder_id = get_or_create_date_folder()
        stream_id = streamtape_upload(local, folder_id)
        
        titles = get_titles()
        title = random.choice(titles) if titles else "Clipfy Video"
        
        vid = uuid.uuid4().hex[:8]
        n = f"/tmp/{vid}.jpg"
        b = f"/tmp/{vid}_blur.jpg"
        make_thumbs(local, n, b)
        
        thumb = r2_put(n, f"thumbs/{vid}.jpg")
        r2_put(b, f"thumbs/{vid}_blur.jpg")
        
        json_update({
            "videoid": vid,
            "title": title,
            "thumb": thumb,
            "safe_thumb": thumb.replace(".jpg", "_blur.jpg"),
            "streamtape_id": stream_id,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
        update_github_files(vid, title, thumb, stream_id)
        
        keyboard = [
            [InlineKeyboardButton("✏️ Change Title", callback_data=f"chg_title_{vid}"),
             InlineKeyboardButton("📷 Change Thumb", callback_data=f"chg_thumb_{vid}")]
        ]
        
        await msg.reply_text(
            f"""✅ **Upload Complete!**

📌 **Title:** {title}

🔥 **Normal Link:**
{SITE_DOMAIN}/v/{vid}.html

🛡️ **Safe Link:**
{SITE_DOMAIN}/v/{vid}-safe.html

📁 Folder: {datetime.now().strftime("%Y-%m-%d")}""",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await msg.reply_text(f"❌ Error: {str(e)}")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start_command))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.VIDEO, handle_video))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.run_polling()
