import json
import os

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


# ---------------------------------------
# GENERATE BOTH PAGES (NORMAL + SAFE)
# ---------------------------------------
def generate_both(video):

    video_id = video["video_id"]
    title = video["title"]
    description = video["description"]
    time_ago = video["time_ago"]
    video_url = video["video_url"]
    thumb_url = video["thumb_url"]

    # SAFE THUMBNAIL (20% BLUR)
    safe_thumb = f"{thumb_url}?blur=20"

    # LOAD TEMPLATES
    with open("template.html", "r", encoding="utf-8") as f:
        normal_template = f.read()

    with open("template_safe.html", "r", encoding="utf-8") as f:
        safe_template = f.read()

    # NORMAL PAGE (full JSON / JS)
    all_videos_json = json.dumps(get_all_video_data(), ensure_ascii=False)

    normal_html = (
        normal_template
        .replace("{{VIDEO_URL}}", video_url)
        .replace("{{THUMB_URL}}", thumb_url)
        .replace("{{VIDEO_ID}}", video_id)
        .replace("{{TITLE}}", title)
        .replace("{{DESCRIPTION}}", description)
        .replace("{{TIME_AGO}}", time_ago)
        .replace("{{ALL_VIDEOS_JSON}}", all_videos_json)
        .replace("{{PLAYER_PAGE_URL}}", f"https://clipfy.store/v/{video_id}.html")
    )

    # SAFE PAGE (no JSON – no unsafe loads)
    safe_html = (
        safe_template
        .replace("{{TITLE}}", title)
        .replace("{{DESCRIPTION}}", description)
        .replace("{{SAFE_BLUR_THUMB}}", safe_thumb)
        .replace("{{NORMAL_PLAYER_URL}}", f"https://clipfy.store/v/{video_id}.html")
        .replace("{{TIME_AGO}}", time_ago)
    )

    # SAVE OUTPUT FILES
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


def generate_all_pages():
    for video in get_all_video_data():
        generate_both(video)
    print("\n🎉 DONE — All pages generated!")


if __name__ == "__main__":
    generate_all_pages()

