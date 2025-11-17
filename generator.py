#!/usr/bin/env python3
"""
Clipfy Video Pages Generator
Automatically generates video pages from template and creates index page
"""

import os
import json
from pathlib import Path

# Configuration
TEMPLATE_FILE = 'template.html'
INDEX_FILE = 'index.html'
VIDEO_DIR = 'v'
THUMBS_DIR = 'thumbs'

# Video data - Add your videos here
VIDEOS = [
    {
        'id': 'video1',
        'title': 'Sample Video 1',
        'description': 'This is a sample video description',
        'video_url': '../media.mp4',
        'thumbnail': '../thumbs/thumb1.jpg'
    },
    # Add more videos here
]

def load_template():
    """Load the HTML template"""
    with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
        return f.read()

def generate_video_page(video_data, template):
    """Generate a video page from template"""
    page_content = template
    page_content = page_content.replace('{{VIDEO_TITLE}}', video_data['title'])
    page_content = page_content.replace('{{VIDEO_URL}}', video_data['video_url'])
    page_content = page_content.replace('{{VIDEO_DESCRIPTION}}', video_data['description'])
    return page_content

def generate_index_page(videos):
    """Generate the index page with all videos"""
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Clipfy - Video Gallery</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: Arial, sans-serif;
            background: #000;
            color: #fff;
        }
        header {
            padding: 20px;
            background: #111;
            text-align: center;
            border-bottom: 2px solid #e50914;
        }
        h1 {
            color: #e50914;
            font-size: 32px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        .video-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 30px;
        }
        .video-card {
            background: #111;
            border-radius: 8px;
            overflow: hidden;
            transition: transform 0.3s;
            cursor: pointer;
        }
        .video-card:hover {
            transform: scale(1.05);
        }
        .video-card img {
            width: 100%;
            height: 180px;
            object-fit: cover;
        }
        .video-info {
            padding: 15px;
        }
        .video-info h3 {
            font-size: 18px;
            margin-bottom: 8px;
        }
        .video-info p {
            font-size: 14px;
            color: #aaa;
            line-height: 1.4;
        }
        a {
            text-decoration: none;
            color: inherit;
        }
    </style>
</head>
<body>
    <header>
        <h1>🎥 Clipfy - Video Gallery</h1>
    </header>
    <div class="container">
        <div class="video-grid">
'''
    
    for video in videos:
        html += f'''
            <a href="v/{video['id']}.html">
                <div class="video-card">
                    <img src="{video['thumbnail']}" alt="{video['title']}">
                    <div class="video-info">
                        <h3>{video['title']}</h3>
                        <p>{video['description']}</p>
                    </div>
                </div>
            </a>
'''
    
    html += '''
        </div>
    </div>
</body>
</html>'''
    
    return html

def main():
    """Main function to generate all pages"""
    print('Clipfy Video Pages Generator')
    print('=' * 50)
    
    # Create directories if they don't exist
    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(THUMBS_DIR, exist_ok=True)
    
    # Load template
    print('Loading template...')
    template = load_template()
    
    # Generate video pages
    print(f'Generating {len(VIDEOS)} video pages...')
    for video in VIDEOS:
        page_content = generate_video_page(video, template)
        output_path = os.path.join(VIDEO_DIR, f"{video['id']}.html")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(page_content)
        print(f"  ✓ Generated: {output_path}")
    
    # Generate index page
    print('Generating index page...')
    index_content = generate_index_page(VIDEOS)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        f.write(index_content)
    print(f"  ✓ Generated: {INDEX_FILE}")
    
    print('\n✓ All done! Your video pages are ready.')
    print(f'  - Video pages: {VIDEO_DIR}/')
    print(f'  - Index page: {INDEX_FILE}')

if __name__ == '__main__':
    main()
