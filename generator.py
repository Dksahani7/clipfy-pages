def generate_html(video_url, page_name, thumb_url):
    with open("template.html", "r") as f:
        template = f.read()

    html = template.replace("{{VIDEO_URL}}", video_url)
    html = html.replace("{{PLAYER_URL}}", f"https://clipfy.store/v/{page_name}")
    html = html.replace("{{THUMB_URL}}", thumb_url)  # Direct thumbnail

    with open(f"v/{page_name}", "w") as f:
        f.write(html)

    return f"https://clipfy.store/v/{page_name}"
