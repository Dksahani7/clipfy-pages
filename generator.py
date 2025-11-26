import json
import os # 💡 os module फ़ाइल को चेक करने के लिए जोड़ा गया है

def get_all_video_data():
    # 🛑 YOUR LIVE DATA SOURCE HERE: Replace this list with a call to your database or file.
    # Note: Description field added here for completeness, though it should ideally come from a real source.
    return [
        { "title": "ये चीज़ें बदल देंगी आपकी ज़िंदगी | 5 Simple Habits", "creator": "The Motivator", "video_url": "/videos/v1.mp4", "thumb_url": "/thumbs/t1.jpg", "video_id": "v1", "time_ago": "3 days ago", "description": "The description for video 1." },
        { "title": "जब किसी ने नहीं देखा | Secret Workout Routine", "creator": "Fitness Guru", "video_url": "/videos/v2.mp4", "thumb_url": "/thumbs/t2.jpg", "video_id": "v2", "time_ago": "1 week ago", "description": "The description for video 2." },
        # ... more videos ...
    ]


def generate_html(video_url, page_name, thumb_url, title, description, time_ago):
    
    # 1. ⚙️ टेम्पलेट फ़ाइल चुनें और त्रुटि संभालें (Choose Template and Handle Errors)
    template_file = "template.html"
    fallback_file = "safe_template.html"
    
    if os.path.exists(template_file):
        file_to_use = template_file
    elif os.path.exists(fallback_file):
        file_to_use = fallback_file
    else:
        print(f"Error: Neither {template_file} nor {fallback_file} was found.")
        return None # या त्रुटि कोड वापस करें

    try:
        with open(file_to_use, "r") as f:
            template = f.read()
    except Exception as e:
        print(f"Error reading template file {file_to_use}: {e}")
        return None

    # 2. Prepare JSON Data for Injection
    all_videos_data = get_all_video_data()
    all_videos_json_str = json.dumps(all_videos_data)
    
    # 3. Inject ALL_VIDEOS_JSON 
    html = template.replace("{{ALL_VIDEOS_JSON}}", all_videos_json_str) 

    # 4. Replace Standard Placeholders
    html = html.replace("{{VIDEO_URL}}", video_url)
    html = html.replace("{{PLAYER_PAGE_URL}}", f"https://clipfy.store/v/{page_name}.html") 
    html = html.replace("{{THUMB_URL}}", thumb_url)
    html = html.replace("{{VIDEO_ID}}", page_name) 
    html = html.replace("{{TITLE}}", title)
    # 💡 Description placeholder added to the replacement list
    html = html.replace("{{DESCRIPTION}}", description) 
    html = html.replace("{{TIME_AGO}}", time_ago) 

    # 5. Write the final HTML file
    # सुनिश्चित करें कि 'v/' डायरेक्टरी मौजूद है
    if not os.path.exists("v"):
        os.makedirs("v")

    output_path = f"v/{page_name}.html"
    try:
        with open(output_path, "w") as f: 
            f.write(html)
    except Exception as e:
        print(f"Error writing output file {output_path}: {e}")
        return None

    return f"https://clipfy.store/v/{page_name}.html"

# 🚀 सभी वीडियो के लिए पेज बनाने का एक नया फ़ंक्शन
def generate_all_pages():
    print("Starting static site generation...")
    videos = get_all_video_data()
    
    for video in videos:
        # सुनिश्चित करें कि आपके डेटा में 'description' फील्ड मौजूद है
        description = video.get('description', 'No description provided.') 
        
        result_url = generate_html(
            video_url=video['video_url'],
            page_name=video['video_id'],
            thumb_url=video['thumb_url'],
            title=video['title'],
            description=description,
            time_ago=video['time_ago']
        )
        if result_url:
            print(f"Successfully generated: {result_url}")
        else:
            print(f"Failed to generate page for video ID: {video['video_id']}")
            
    print("Static site generation complete.")

# 💡 यदि आप इस स्क्रिप्ट को सीधे चलाते हैं, तो यह फंक्शन कॉल होगा
if __name__ == "__main__":
    generate_all_pages()
