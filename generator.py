import json 

def get_all_video_data():
    # 🛑 YOUR LIVE DATA SOURCE HERE: Replace this list with a call to your database or file.
    # Ensure all video objects contain: title, creator, video_url, thumb_url, video_id, time_ago
    return [
        { "title": "ये चीज़ें बदल देंगी आपकी ज़िंदगी | 5 Simple Habits", "creator": "The Motivator", "video_url": "/videos/v1.mp4", "thumb_url": "/thumbs/t1.jpg", "video_id": "v1", "time_ago": "3 days ago" },
        { "title": "जब किसी ने नहीं देखा | Secret Workout Routine", "creator": "Fitness Guru", "video_url": "/videos/v2.mp4", "thumb_url": "/thumbs/t2.jpg", "video_id": "v2", "time_ago": "1 week ago" },
        # ... more videos ...
    ]


def generate_html(video_url, page_name, thumb_url, title, description, time_ago):
    with open("template.html", "r") as f:
        template = f.read()

    # 1. Prepare JSON Data for Injection
    all_videos_data = get_all_video_data()
    all_videos_json_str = json.dumps(all_videos_data)
    
    # 2. Inject ALL_VIDEOS_JSON (The BIG FIX)
    html = template.replace("{{ALL_VIDEOS_JSON}}", all_videos_json_str) 

    # 3. Replace Standard Placeholders
    html = html.replace("{{VIDEO_URL}}", video_url)
    html = html.replace("{{PLAYER_PAGE_URL}}", f"https://clipfy.store/v/{page_name}.html") 
    html = html.replace("{{THUMB_URL}}", thumb_url)
    html = html.replace("{{VIDEO_ID}}", page_name) 
    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{DESCRIPTION}}", description)
    html = html.replace("{{TIME_AGO}}", time_ago) 

    # 4. Write the final HTML file
    with open(f"v/{page_name}.html", "w") as f: # 💡 Ensure you are writing to the correct .html file
        f.write(html)

    return f"https://clipfy.store/v/{page_name}.html"
