import os
import time

# Play button overlay URL
PLAY_ICON_URL = "https://pub-51338658718349efb6e5193255e4131b.r2.dev/play.png"

def build_overlay_thumbnail(thumb_url):
    """Add play button overlay to thumbnail"""
    return (
        "https://clipfy.store/cdn-cgi/image/"
        f"overlay={PLAY_ICON_URL},"
        "overlay-width=250,"
        "overlay-height=250,"
        "overlay-gravity=center/"
        + thumb_url
    )

def generate_html(video_url, page_name, thumb_url):
    """Generate HTML page with overlay thumbnail"""
    with open("template.html", "r") as f:
        template = f.read()
    
    # Build overlay thumbnail URL
    thumb_overlay = build_overlay_thumbnail(thumb_url)
    
    # Replace variables
    html = template.replace("{{VIDEO_URL}}", video_url)
    html = html.replace("{{PLAYER_URL}}", f"https://clipfy.store/v/{page_name}")
    html = html.replace("{{THUMB_URL}}", thumb_overlay)  # Use overlay URL
    
    # Save final HTML
    with open(f"v/{page_name}", "w") as f:
        f.write(html)
    
    return f"https://clipfy.store/v/{page_name}"
