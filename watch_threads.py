import json
import re
from datetime import datetime

import requests

# === 這裡改成你的帳號名稱 ===
THREADS_USERNAME = "yuri_news_tw"
PROFILE_URL = f"https://www.threads.net/@{THREADS_USERNAME}"

# 關鍵字（可以自行增加 / 修改）
KEYWORDS = ["今日", "新書"]

# Firecrawl 設定：用 v1/scrape
FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

# 記錄上次看到的貼文代碼
STATE_FILE = "last_seen.json"

# 從 secrets.py 讀金鑰 & webhook
from secrets import FIRECRAWL_API_KEY, DISCORD_WEBHOOK_URL


def load_last_seen():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("last_code")
    except FileNotFoundError:
        return None


def save_last_seen(code: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_code": code}, f, ensure_ascii=False, indent=2)


def firecrawl_scrape(url: str) -> str:
    """
    呼叫 Firecrawl 抓取指定 URL 的 HTML 內容。
    這裡用 html 格式，比較容易用正則式找連結。
    """
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["html"],  # 要 html
        "waitFor": 5000,
    }

    resp = requests.post(
        FIRECRAWL_ENDPOINT,
        headers=headers,
        json=payload,
        timeout=40,
    )
    print("   Firecrawl 狀態碼：", resp.status_code)
    resp.raise_for_status()
    data = resp.json()

    # 兼容不同回傳格式
    if isinstance(data, dict):
        # 新版可能是 data.html
        if "html" in data:
            return data["html"]
        if "data" in data and isinstance(data["data"], dict):
            if "html" in data["data"]:
                return data["data"]["html"]

    raise RuntimeError("Firecrawl 回傳格式中找不到 html 欄位，實際內容：\n" + str(data)[:500])


# 捕捉 threads.net 或 threads.com 的 post 連結
POST_URL_RE = re.compile(
    r"https://www\.threads\.(?:net|com)/@[^/]+/post/([A-Za-z0-9_-]+)"
)


def extract_latest_post_code_and_url(html: str):
    """
    從 Firecrawl 抓回來的 HTML 中找出「第一個」貼文網址與代碼。
    """
    matches = POST_URL_RE.findall(html)
    if not matches:
        print("⚠ 找不到任何 Threads 貼文連結（https://www.threads.com/@.../post/...）。")
        # debug：印出部分 HTML 幫助檢查
        preview = html[:800]
        print("   HTML 預覽：")
        print(preview)
        return None, None

    code = matches[0]
    url = f"https://www.threads.net/@{THREADS_USERNAME}/post/{code}"
    print(f"   抓到最新貼文代碼: {code}")
    print(f"   預設貼文網址: {url}")
    return code, url


def post_matches_keywords(post_url: str) -> bool:
    """
    下載單一貼文頁面，檢查內容是否包含關鍵字。
    這裡用一般 requests 抓即可。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    try:
        resp = requests.get(post_url, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"   ⚠ 讀取貼文內容失敗：{e}")
        return False

    matched = False
    for kw in KEYWORDS:
        if kw and kw in html:
            print(f"   ✅ 貼文 HTML 中有關鍵字：{kw}")
            matched = True
    if not matched:
        print("   ℹ 貼文內容沒有符合的關鍵字，略過推播。")
    return matched


def send_to_discord(post_url: str):
    today = datetime.now().strftime("%Y-%m-%d")
    content = (
        f"📚 **Threads 今日新書貼文通知｜{today}**\n\n"
        f"來源帳號：@{THREADS_USERNAME}\n"
        f"貼文連結：{post_url}"
    )

    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": content})
    if resp.status_code not in (200, 204):
        print("❌ 發送到 Discord 失敗：", resp.status_code, resp.text)
    else:
        print("✅ 已發送新貼文通知到 Discord。")


def main():
    print("🔍 使用 Firecrawl 監控 Threads 貼文...")
    print(f"   帳號：@{THREADS_USERNAME}")
    print(f"   關鍵字： {KEYWORDS}")

    last_code = load_last_seen()
    print("   上次紀錄：", last_code)

    print(f"\n[{datetime.now()}] 抓取頁面...")
    html = firecrawl_scrape(PROFILE_URL)

    code, url = extract_latest_post_code_and_url(html)
    if code is None:
        print("⚠ 沒有找到任何貼文連結，結束。")
        return

    # 第一次執行：只記錄，不推播
    if last_code is None:
        print("   第一次執行，先記錄目前最新貼文代碼，不推播。")
        save_last_seen(code)
        return

    if code == last_code:
        print("   尚未有新貼文。")
        return

    print("   ✅ 偵測到新貼文！")
    # 有新貼文：先檢查關鍵字，再視情況推播
    if post_matches_keywords(url):
        send_to_discord(url)
    else:
        print("   此貼文不符合關鍵字條件，不發送到 Discord。")

    save_last_seen(code)


if __name__ == "__main__":
    main()
