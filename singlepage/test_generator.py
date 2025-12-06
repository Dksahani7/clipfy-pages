
# test_generator.py
# Usage:
#   python3 test_generator.py abc123
# prints twitter + safe links

import sys
BASE = "https://clipfy.store/singlepage/player.html"  # change if needed

def make_links(videoid):
    videoid = videoid.strip()
    twitter = f"{BASE}?v={videoid}&t=1"
    safe = f"{BASE}?v={videoid}&safe=1"
    return twitter, safe

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_generator.py VIDEOID")
        return
    vid = sys.argv[1]
    tw, sf = make_links(vid)
    print("Twitter link:\n", tw)
    print("Safe link:\n", sf)

if __name__ == "__main__":
    main()
