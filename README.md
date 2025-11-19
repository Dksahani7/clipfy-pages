# Clipfy Video Player

## Description
Clipfy is a video hosting and playback system that enables Twitter inline video playback with Twitter Player Card support.

## Features
- ✅ Twitter Player Card integration for inline playback
- ✅ Responsive video player
- ✅ Direct MP4 video streaming
- ✅ Clean and minimal UI
- ✅ URL-based video loading

## How to Use

### Method 1: Direct Player Link
Use the Player.html with video URL as a query parameter:

```
https://dksahani7.github.io/clipfy-pages/Player.html?video=YOUR_VIDEO_URL
```

**Example:**
```
https://dksahani7.github.io/clipfy-pages/Player.html?video=https://example.com/video.mp4
```

### Method 2: Share on Twitter
When you share the player URL on Twitter, it will automatically show an inline video player with:
- Video thumbnail
- Play button
- Full playback controls
- Responsive sizing (1280x720)

## Files

### Player.html
Main video player file with Twitter Player Card meta tags:
- Supports query parameter `?video=URL`
- Auto-plays video when loaded
- Black background with centered player
- Error handling for missing video URLs

### index.html
Video gallery page showcasing multiple videos from Clipfy.

## Twitter Card Meta Tags

The Player.html includes these Twitter Card meta tags:
```html
<meta name="twitter:card" content="player">
<meta name="twitter:title" content="Clipfy Video">
<meta name="twitter:description" content="Watch this video on Clipfy">
<meta name="twitter:player" content="[PLAYER_URL]">
<meta name="twitter:player:width" content="1280">
<meta name="twitter:player:height" content="720">
<meta name="twitter:player:stream" content="[VIDEO_URL]">
<meta name="twitter:player:stream:content_type" content="video/mp4">
```

## Setup

1. **Host your video files** on a server that supports direct MP4 streaming
2. **Use the Player.html URL** with your video URL as parameter
3. **Share on Twitter** - the video will play inline

## Example Usage

```bash
# If your video is at:
https://clipfy.store/videos/sample.mp4

# Your player URL will be:
https://dksahani7.github.io/clipfy-pages/Player.html?video=https://clipfy.store/videos/sample.mp4
```

## Browser Support
- ✅ Chrome
- ✅ Firefox
- ✅ Safari
- ✅ Edge
- ✅ Mobile browsers

## Notes
- Video URLs must be publicly accessible
- MP4 format recommended for best compatibility
- CORS headers may be required on your video hosting server
- Twitter validates Player Cards before showing them

## License
Open source - feel free to use and modify

## Author
Dksahani7

## Repository
https://github.com/Dksahani7/clipfy-pages
