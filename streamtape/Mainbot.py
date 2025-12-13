#!/usr/bin/env python3
import os, json, uuid, subprocess, base64, requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from PIL import Image, ImageFilter
import boto3
from github import Github

# ========== ENV ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")

STREAM_LOGIN = os.getenv("STREAMTAPE_LOGIN")
STREAM_KEY   = os.getenv("STREAMTAPE_KEY")

SITE_DOMAIN  = os.getenv("SITE_DOMAIN")

R2_PUBLIC = os.getenv("R2_PUBLIC_URL")
R2_BUCKET = os.getenv("R2_BUCKET")

GITHUB_REPO   = os.getenv("GITHUB_REPO")
GITHUB_BRANCH= os.getenv("GITHUB_BRANCH","main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ========== CLIENTS ==========
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("R2_SECRET_KEY")
)

gh = Github(GITHUB_TOKEN)
repo = gh.get_repo(GITHUB_REPO)

# ========== HELPERS ==========
def streamtape_upload(path):
    r = requests.get(
        "https://api.streamtape.com/file/ul",
        params={"login": STREAM_LOGIN, "key": STREAM_KEY},
        timeout=30
    ).json()
    upload_url = r["result"]["url"]
    up = requests.post(upload_url, files={"file": open(path,"rb")}, timeout=600)
    return up.json()["result"]["filecode"]  # STREAMTAPE_ID

def make_thumbs(video, normal, blur):
    subprocess.run(["ffmpeg","-y","-i",video,"-ss","00:00:01","-vframes","1",normal],check=True)
    Image.open(normal).filter(ImageFilter.GaussianBlur(25)).save(blur)

def r2_put(local, key):
    s3.upload_file(local, R2_BUCKET, key, ExtraArgs={"ACL":"public-read"})
    return f"{R2_PUBLIC}/{key}"

def json_update(entry):
    key="streamtape/index.json"
    try:
        obj=s3.get_object(Bucket=R2_BUCKET,Key=key)
        data=json.loads(obj["Body"].read())
    except:
        data=[]
    data.insert(0,entry)
    s3.put_object(
        Bucket=R2_BUCKET,Key=key,
        Body=json.dumps(data),
        ContentType="application/json",
        ACL="public-read"
    )

def meta_html(videoid, title, thumb, stream_id, safe=False):
    img = thumb if not safe else thumb.replace(".jpg","_blur.jpg")
    q = f"?v={videoid}" + ("&safe=1" if safe else "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{title}</title>

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:image" content="{img}">
<meta name="twitter:player" content="{SITE_DOMAIN}/player.html{q}">
<meta name="twitter:player:width" content="720">
<meta name="twitter:player:height" content="405">
<meta name="twitter:player:stream" content="https://streamtape.com/e/{stream_id}">
<meta name="twitter:player:stream:content_type" content="text/html">

<meta property="og:type" content="video.other">
<meta property="og:title" content="{title}">
<meta property="og:image" content="{img}">
<meta property="og:video" content="https://streamtape.com/e/{stream_id}">
<meta property="og:video:type" content="text/html">

<meta http-equiv="refresh" content="0;url={SITE_DOMAIN}/player.html{q}">
</head><body></body></html>"""

# ========== BOT ==========
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg=update.message
    await msg.reply_text("⬆️ Uploading to Streamtape…")

    f=await context.bot.get_file(msg.video.file_id)
    local=f"/tmp/{uuid.uuid4().hex}.mp4"
    await f.download_to_drive(local)

    stream_id=streamtape_upload(local)

    vid=uuid.uuid4().hex[:8]
    n=f"/tmp/{vid}.jpg"; b=f"/tmp/{vid}_blur.jpg"
    make_thumbs(local,n,b)

    thumb=r2_put(n,f"thumbs/{vid}.jpg")
    r2_put(b,f"thumbs/{vid}_blur.jpg")

    json_update({
        "videoid":vid,
        "title":"Clipfy Video",
        "thumb":thumb,
        "safe_thumb":thumb.replace(".jpg","_blur.jpg"),
        "streamtape_id":stream_id
    })

    repo.create_file(f"streamtape/v/{vid}.html","add",meta_html(vid,"Clipfy Video",thumb,stream_id),branch=GITHUB_BRANCH)
    repo.create_file(f"streamtape/v/{vid}-safe.html","add",meta_html(vid,"Clipfy Video",thumb,stream_id,True),branch=GITHUB_BRANCH)

    await msg.reply_text(
f"""✅ DONE

🔥 Normal:
{SITE_DOMAIN}/v/{vid}.html

🛡️ Safe:
{SITE_DOMAIN}/v/{vid}-safe.html"""
    )

app=ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.VIDEO, handle_video))
app.run_polling()
