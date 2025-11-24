import json # JSON serialization के लिए ज़रूरी

# ⚠️ ध्यान दें: यह सिर्फ एक उदाहरण फंक्शन है।
# असल में, आपको यह डेटा डेटाबेस (MySQL/SQLite) या किसी JSON फ़ाइल से fetch करना होगा।
def get_all_video_data():
    """
    सभी वीडियो की जानकारी एक लिस्ट ऑफ़ डिक्ट्स (List of Dictionaries) के रूप में लौटाता है।
    
    असली सेटअप में, यह आपके डेटा सोर्स से डेटा खींचेगा।
    """
    # DUMMY DATA: Replace this with your actual data fetching logic
    # Make sure this list is comprehensive and includes all available videos.
    return [
        { 
            "title": "Healthy Relationship: The Secret Sauce of Success", 
            "creator": "Content Creator Name", 
            "video_url": "/videos/video-1.mp4", 
            "thumb_url": "/thumbs/thumb-1.jpg", 
            "video_id": "vid1", 
            "time_ago": "3 days ago" 
        },
        { 
            "title": "Body Positivity: Embrace Your True Self", 
            "creator": "Self Love Coach", 
            "video_url": "/videos/video-2.mp4", 
            "thumb_url": "/thumbs/thumb-2.jpg", 
            "video_id": "vid2", 
            "time_ago": "1 week ago" 
        },
        { 
            "title": "Consent is Clear: Understanding the Boundaries", 
            "creator": "Legal Advisor", 
            "video_url": "/videos/video-3.mp4", 
            "thumb_url": "/thumbs/thumb-3.jpg", 
            "video_id": "vid3", 
            "time_ago": "1 day ago" 
        },
        # Add more video objects here as your list grows
    ]


def generate_html(video_url, page_name, thumb_url, title, description, time_ago):
    """
    अपडेटेड फंक्शन जो टेम्पलेट को भरता है और सभी वीडियो डेटा इंजेक्ट करता है।
    
    :param title: Video Title (for Twitter Card)
    :param description: Video Description (for Twitter Card)
    :param time_ago: Time since upload (for display in 'post' section)
    """
    with open("template.html", "r") as f:
        template = f.read()

    # --- 1. Fetch All Videos Data ---
    all_videos_data = get_all_video_data()
    
    # --- 2. Serialize to JSON String and Inject ---
    # Python list को JavaScript array में बदलने के लिए JSON.stringify का उपयोग (dumps)
    all_videos_json_str = json.dumps(all_videos_data)
    
    # ⚠️ IMPORTANT: Replace the dummy array placeholder in template.html
    # हमने template.html में 'const ALL_VIDEOS = [];' को replace करने के लिए एक dummy variable यूज़ किया है।
    # यह सुनिश्चित करता है कि JavaScript को एक valid JSON array मिले।
    js_data_injection = f"const ALL_VIDEOS = {all_videos_json_str};"
    
    # Find the dummy line in the template and replace it with the actual data
    template = template.replace('const ALL_VIDEOS = [];', js_data_injection)


    # --- 3. Replace Standard Placeholders ---
    # अब हम सारे प्लेसहोल्डर्स को रिप्लेस करते हैं
    html = template.replace("{{VIDEO_URL}}", video_url)
    html = html.replace("{{PLAYER_PAGE_URL}}", f"https://clipfy.store/v/{page_name}") # Note: Corrected variable name from {{PLAYER_URL}} to {{PLAYER_PAGE_URL}} to match template.
    html = html.replace("{{THUMB_URL}}", thumb_url)
    
    # New Placeholders
    html = html.replace("{{VIDEO_ID}}", page_name) # Assuming page_name is the unique ID
    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{DESCRIPTION}}", description)
    html = html.replace("Loading...", time_ago) # Replacing the default text in timeAgo element

    # --- 4. Write the final HTML file ---
    with open(f"v/{page_name}", "w") as f:
        f.write(html)

    return f"https://clipfy.store/v/{page_name}"

# --- Example Usage (आप अपनी स्क्रिप्ट में इसे कैसे कॉल करेंगे) ---
if __name__ == '__main__':
    
    # मान लीजिए आप 'vid1' के लिए पेज बना रहे हैं
    final_url = generate_html(
        video_url="/videos/video-1.mp4",
        page_name="vid1", # This will be the {{VIDEO_ID}}
        thumb_url="/thumbs/thumb-1.jpg",
        title="Sex Education: समझ, सुरक्षा, रिश्ते और ज़िम्मेदारी",
        description="आज के समय में sex education सिर्फ एक chapter नहीं...",
        time_ago="10 hours ago"
    )
    print(f"HTML generated and saved to: {final_url}")
    
    # अब 'vid2' के लिए पेज बना रहे हैं
    final_url = generate_html(
        video_url="/videos/video-2.mp4",
        page_name="vid2",
        thumb_url="/thumbs/thumb-2.jpg",
        title="Body Positivity: Embrace Your True Self",
        description="अपनी body को accept करना ज़रूरी है...",
        time_ago="1 week ago"
    )
    print(f"HTML generated and saved to: {final_url}")
