import json
import os

# 🔥 LIVE VIDEO LIST — Bot R2 index ya DB se aayega future me
def get_all_video_data():
    return [
        {
            "title": "ये चीज़ें बदल देंगी आपकी ज़िंदगी | 5 Simple Habits",
            "creator": "The Motivator",
            "video_url": "/videos/v1.mp4",
            "thumb_url": "/thumbs/t1.jpg",
            "video_id": "v1",
            "time_ago": "3 days ago",
            "description": "The description for video 1."
        },
        {
            "title": "जब किसी ने नहीं देखा | Secret Workout Routine",
            "creator": "Fitness Guru",
            "video_url": "/videos/v2.mp4",
            "thumb_url": "/thumbs/t2.jpg",
            "video_id": "v2",
            "time_ago": "1 week ago",
            "description": "The description for video 2."
        }
    ]


# ✅ FINAL FUNCTION: TWO PAGES (normal + safe)
def generate_both(video):

    video_id = video["video_id"]
    title = video["title"]
    description = video.get("description", "")
    time_ago = video["time_ago"]
    video_url = video["video_url"]
    thumb_url = video["thumb_url"]

    # ------------------------
    # 1) LOAD TEMPLATES
    # ------------------------
    with open("template.html", "r", encoding="utf-8") as f:
        normal_template = f.read()

    with open("template_safe.html", "r", encoding="utf-8") as f:
        safe_template = f.read()

    # ------------------------
    # 2) JSON FOR SUGGESTIONS
    # ------------------------
    all_videos = json.dumps(get_all_video_data())

    # ------------------------
    # 3) NORMAL PAGE
    # ------------------------
    normal_html = normal_template\
        .replace("{{VIDEO_URL}}", video_url)\
        .replace("{{THUMB_URL}}", thumb_url)\
        .replace("{{VIDEO_ID}}", video_id)\
        .replace("{{TITLE}}", title)\
        .replace("{{DESCRIPTION}}", description)\
        .replace("{{TIME_AGO}}", time_ago)\
        .replace("{{ALL_VIDEOS_JSON}}", all_videos)\
        .replace("{{PLAYER_PAGE_URL}}", f"https://clipfy.store/v/{video_id}.html")

    # ------------------------
    # 4) SAFE PAGE (BLUR + NO PLAYER TAG)
    # ------------------------
    safe_html = safe_template\
        .replace("{{VIDEO_URL}}", video_url)\
        .replace("{{THUMB_URL}}", thumb_url)\
        .replace("{{VIDEO_ID}}", video_id)\
        .replace("{{TITLE}}", title)\
        .replace("{{DESCRIPTION}}", description)\
        .replace("{{TIME_AGO}}", time_ago)\
        .replace("{{ALL_VIDEOS_JSON}}", all_videos)\
        .replace("{{PLAYER_PAGE_URL}}", f"https://clipfy.store/v/{video_id}_safe.html")

    # ------------------------
    # 5) SAVE BOTH FILES
    # ------------------------
    if not os.path.exists("v"):
        os.makedirs("v")

    with open(f"v/{video_id}.html", "w", encoding="utf-8") as f:
        f.write(normal_html)

    with open(f"v/{video_id}_safe.html", "w", encoding="utf-8") as f:
        f.write(safe_html)

    print("✔ Generated:", video_id)
    return {
        "normal": f"https://clipfy.store/v/{video_id}.html",
        "safe": f"https://clipfy.store/v/{video_id}_safe.html"
    }


# ------------------------
# 🔥 GENERATE ALL PAGES
# ------------------------
def generate_all_pages():
    videos = get_all_video_data()

    for video in videos:
        generate_both(video)

    print("\n🎉 DONE — All pages generated!")


# ------------------------
# AUTO RUN
# ------------------------
if __name__ == "__main__":
    generate_all_pages()
