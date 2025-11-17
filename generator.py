import os

# Folders
V_FOLDER = "v"
TEMPLATE = "template.html"

os.makedirs(V_FOLDER, exist_ok=True)

def create_video_page(id, video_url, thumb_url, title="Clipfy Video", desc="Watch on Clipfy"):
    """Generate /v/<id>.html file"""

    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{DESCRIPTION}}", desc)
    html = html.replace("{{THUMB_URL}}", thumb_url)
    html = html.replace("{{VIDEO_URL}}", video_url)
    html = html.replace("{{PAGE_URL}}", f"https://clipfy.store/v/{id}.html")

    output_path = f"{V_FOLDER}/{id}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated: {output_path}")

# Example usage:
if __name__ == "__main__":
    create_video_page(
        id="12345",
        video_url="https://your-r2-link/video.mp4",
        thumb_url="https://clipfy.store/thumbs/12345.jpg",
        title="Test Video",
        desc="Inline playback test"
    )
