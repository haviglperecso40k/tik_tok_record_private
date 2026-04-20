"""
Import following list từ TikTok Data Export vào watchlist.txt

Cách dùng:
  python import_following.py <path_to_following.json>

File following.json lấy từ:
  TikTok Settings -> Privacy -> Personalization and data -> Download your data (JSON format)
"""
import json
import os
import sys


def import_from_tiktok_export(json_path: str, watchlist_path: str = None):
    if watchlist_path is None:
        watchlist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist.txt')

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # TikTok export format: {"Following": {"Following": [{"Date": "...", "UserName": "..."}]}}
    # hoặc: {"Activity": {"Following List": {"ItemFavoriteList": [{"UserName": "..."}]}}}
    usernames = []

    # thử format 1
    following = data.get('Following', {}).get('Following', [])
    for item in following:
        u = item.get('UserName') or item.get('username')
        if u:
            usernames.append(u.lstrip('@'))

    # thử format 2 (Activity)
    if not usernames:
        following2 = data.get('Activity', {}).get('Following List', {}).get('ItemFavoriteList', [])
        for item in following2:
            u = item.get('UserName') or item.get('username')
            if u:
                usernames.append(u.lstrip('@'))

    # thử format 3 (flat list)
    if not usernames and isinstance(data, list):
        for item in data:
            u = item.get('UserName') or item.get('username') or item.get('uniqueId')
            if u:
                usernames.append(u.lstrip('@'))

    if not usernames:
        print(f"Không tìm thấy following list. Keys trong file: {list(data.keys())}")
        return

    with open(watchlist_path, 'w', encoding='utf-8') as f:
        f.write("# Auto-imported from TikTok Data Export\n")
        for u in usernames:
            f.write(u + "\n")

    print(f"Đã import {len(usernames)} users vào {watchlist_path}")
    print(f"Sample: {usernames[:5]}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    import_from_tiktok_export(sys.argv[1])
