import json
import os
import re

from utils.logger_manager import logger


def get_following_list_via_browser(cookies: dict) -> list:
    """
    Dùng Playwright (headless browser) để lấy danh sách following từ TikTok.
    Intercept network request /api/user/list/ để lấy dữ liệu có X-Bogus đúng.
    """
    from playwright.sync_api import sync_playwright

    following = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.6478.127 Safari/537.36"
            )
        )

        # Set cookies
        playwright_cookies = []
        for name, value in cookies.items():
            playwright_cookies.append({
                "name": name,
                "value": str(value),
                "domain": ".tiktok.com",
                "path": "/",
            })
        context.add_cookies(playwright_cookies)

        page = context.new_page()
        captured = []

        def handle_response(response):
            if "/api/user/list/" in response.url and "scene=21" in response.url:
                try:
                    data = response.json()
                    user_list = data.get("userList", [])
                    for u in user_list:
                        uid = u.get("user", {}).get("uniqueId")
                        if uid:
                            captured.append(uid)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            logger.info("Browser: loading TikTok following page...")
            page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)

            # lấy sec_uid từ page
            content = page.content()
            sec_uid_match = re.search(r'"secUid":"(.*?)"', content)
            username_match = re.search(r'"uniqueId":"(.*?)"', content)

            if not sec_uid_match:
                logger.error("Browser: could not find secUid, check cookies.")
                return []

            sec_uid = sec_uid_match.group(1)
            username = username_match.group(1) if username_match else "unknown"
            logger.info(f"Browser: logged in as @{username}")

            # navigate đến following page để trigger API call
            page.goto(
                f"https://www.tiktok.com/@{username}/following",
                wait_until="domcontentloaded",
                timeout=20000
            )
            page.wait_for_timeout(5000)

            # scroll để load thêm
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)

            following = list(dict.fromkeys(captured))  # dedup, giữ thứ tự
            logger.info(f"Browser: found {len(following)} following users")

        except Exception as e:
            logger.error(f"Browser error: {e}")
        finally:
            browser.close()

    return following


def update_watchlist(cookies: dict, watchlist_path: str):
    """
    Lấy following list và ghi vào watchlist.txt.
    Giữ lại comment (#) và không xóa user đã thêm tay.
    """
    following = get_following_list_via_browser(cookies)
    if not following:
        logger.warning("Could not fetch following list, watchlist not updated.")
        return

    # đọc file hiện tại để giữ comment và user thêm tay
    existing_manual = []
    if os.path.exists(watchlist_path):
        with open(watchlist_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    existing_manual.append(line.rstrip())

    with open(watchlist_path, "w", encoding="utf-8") as f:
        for comment in existing_manual:
            f.write(comment + "\n")
        if existing_manual:
            f.write("\n")
        f.write("# --- auto-fetched following list ---\n")
        for user in following:
            f.write(user + "\n")

    logger.info(f"Watchlist updated: {len(following)} users written to {watchlist_path}")
