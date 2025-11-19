import os
import time

def generate_html(video_url, page_name):
    with open("template.html", "r") as f:
        template = f.read()

    # Replace variables
    html = template.replace("{{VIDEO_URL}}", video_url)
    html = html.replace("{{PLAYER_URL}}", f"https://clipfy.store/v/{page_name}")

    # Save final HTML
    with open(f"v/{page_name}", "w") as f:
        f.write(html)

    return f"https://clipfy.store/v/{page_name}"
