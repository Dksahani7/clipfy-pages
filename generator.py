import json
import os
import time

# ------------------------------------
# LIVE VIDEO LIST (future: DB / R2)
# ------------------------------------
def get_all_video_data():
    return [
        {
            "title": "ये चीज़ें बदल देंगी आपकी ज़िंदगी | 5 Simple Habits",
            "creator": "The Motivator",
            "videourl": "/videos/v1.mp4",      # ✅ camelCase
            "thumburl": "/thumbs/t1.jpg",      # ✅ camelCase
            "videoid": "v1",                   # ✅ camelCase
            "timeago": "3 days ago",           # ✅ camelCase
            "description": "The description for video 1.",
            "views": 12500,                    # ✅ Added
            "likes": 850                       # ✅ Added
        },
        {
            "title": "जब किसी ने नहीं देखा | Secret Workout Routine",
            "creator": "Fitness Guru",
            "videourl": "/videos/v2.mp4",      # ✅ camelCase
            "thumburl": "/thumbs/t2.jpg",      # ✅ camelCase
            "videoid": "v2",                   # ✅ camelCase
            "timeago": "1 week ago",           # ✅ camelCase
            "description": "The description for video 2.",
            "views": 8900,                     # ✅ Added
            "likes": 420                       # ✅ Added
        }
    ]


# ------------------------------------
# CLEAN TITLE + SAFE TITLE
# ------------------------------------
def clean_text(t):
    bad = ["🔥", "😈", "sexy", "fuck", "dangerous"]
    for b in bad:
        t = t.replace(b, "")
    return t.strip()


# ------------------------------------
# MAKE BOTH PAGES
# ------------------------------------
def generate_both(video):

    videoid = video["videoid"]
    title = video["title"]
    safe_title = clean_text(title)

    description = video.get("description", "")
    safe_desc = clean_text(description)

    timeago = video["timeago"]
    videourl = video["videourl"]
    thumburl = video["thumburl"]
    views = video.get("views", 0)
    likes = video.get("likes", 0)

    # SAFE THUMBNAIL (blur via CF)
    safe_thumb = f"{thumburl}?blur=40"
    
    # API BASE (adjust as needed)
    api_base = "https://clipfy.store/api/"
    
    # ------------------------------------
    # LOAD TEMPLATES
    # ------------------------------------
    with open("template.html", "r", encoding="utf-8") as f:
        normal_template = f.read()

    with open("template_safe.html", "r", encoding="utf-8") as f:
        safe_template = f.read()

    # ------------------------------------
    # JSON FOR SUGGESTIONS
    # ------------------------------------
    all_videos = json.dumps(get_all_video_data(), ensure_ascii=False)

    # ------------------------------------
    # NORMAL PAGE
    # ------------------------------------
    normal_html = (
        normal_template
        .replace("{{VIDEO_URL}}", videourl)
        .replace("{{THUMB_URL}}", thumburl)
        .replace("{{VIDEO_ID}}", videoid)
        .replace("{{TITLE}}", title)
        .replace("{{DESCRIPTION}}", description)
        .replace("{{TIME_AGO}}", timeago)
        .replace("{{VIEWS}}", str(views))
        .replace("{{LIKES}}", str(likes))
        .replace("{{API_BASE}}", api_base)
        .replace("{{ALL_VIDEOS_JSON}}", all_videos)
        .replace("{{PLAYER_PAGE_URL}}", f"https://clipfy.store/v/{videoid}.html")
    )

    # ------------------------------------
    # SAFE PAGE (BLUR / CLEAN META)
    # ------------------------------------
    safe_html = (
        safe_template
        .replace("{{VIDEO_URL}}", videourl)
        .replace("{{THUMB_URL}}", safe_thumb)       # BLURRED IMAGE
        .replace("{{VIDEO_ID}}", videoid + "_safe") # ✅ Add _safe suffix
        .replace("{{TITLE}}", safe_title)           # SAFE TITLE
        .replace("{{DESCRIPTION}}", safe_desc)      # SAFE DESCRIPTION
        .replace("{{TIME_AGO}}", timeago)
        .replace("{{VIEWS}}", str(views))
        .replace("{{LIKES}}", str(likes))
        .replace("{{API_BASE}}", api_base)
        .replace("{{ALL_VIDEOS_JSON}}", all_videos)
        .replace("{{NORMAL_LINK}}", f"https://clipfy.store/v/{videoid}.html")
    )

    # ------------------------------------
    # SAVE FILES
    # ------------------------------------
    if not os.path.exists("v"):
        os.makedirs("v")

    with open(f"v/{videoid}.html", "w", encoding="utf-8") as f:
        f.write(normal_html)

    with open(f"v/{videoid}_safe.html", "w", encoding="utf-8") as f:
        f.write(safe_html)

    print(f"✔ Generated: {videoid}")

    return {
        "normal": f"https://clipfy.store/v/{videoid}.html",
        "safe": f"https://clipfy.store/v/{videoid}_safe.html"
    }


# ------------------------------------
# GENERATE ALL PAGES
# ------------------------------------
def generate_all_pages():
    videos = get_all_video_data()

    for video in videos:
        generate_both(video)

    print("\n🎉 DONE — All pages generated!")


# ------------------------------------
# AUTO RUN
# ------------------------------------
if __name__ == "__main__":
    generate_all_pages()
