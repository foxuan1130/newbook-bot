import json
import re
import os
from datetime import datetime
import requests

# === Threads 帳號名稱 ===
THREADS_USERNAME = "yuri_news_tw"
PROFILE_URL = f"https://www.threads.net/@{THREADS_USERNAME}"

# 關鍵字（可以自行增加 / 修改）
KEYWORDS = ["今日", "新書"]

# Firecrawl API endpoint
FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

# 記錄上次貼文代碼
STATE_FILE = "last_seen.json"

# === 從 Railway 環境變數讀取金鑰與 Webhook ===
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not FIRECRAWL_API_KEY:
    raise RuntimeError("❌ FIRECRAWL_API_KEY 尚未在 Railway Variables 設定")
if not DISCORD_WEBHOOK_URL:
    raise RuntimeError("❌ DISCORD_WEBHOOK_URL 尚未在 Railway Variables 設定")


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
    """呼叫 Firecrawl 抓 HTML"""
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["html"],
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

    # 支援不同格式
    if isinstance(data, dict):
        if "html" in data:
            return data["html"]
        if "data" in data and isinstance(data["data"], dict):
            if "html" in data["data"]:
                return data["data"]["html"]

    raise RuntimeError("Firecrawl 回傳格式異常:\n" + str(data)[:400])


POST_URL_RE = re.compile(
    r"https://www\.threads\.(?:net|com)/@[^/]+/post/([A-Za-z0-9_-]+)"
)


def extract_latest_post_code_and_url(html: str):
    matches = POST_URL_RE.findall(html)
    if not matches:
        print("⚠ 找不到任何 Threads 貼文連結")
        print("   HTML 預覽：\n", html[:600])
        return None, None

    code = matches[1]
    url = f"https://www.threads.net/@{THREADS_USERNAME}/post/{code}"
    print(f"   抓到貼文代碼: {code}")
    print(f"   預設貼文網址: {url}")
    return code, url


def post_matches_keywords(post_url: str) -> bool:
    """檢查貼文 HTML 是否包含關鍵字"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    try:
        resp = requests.get(post_url, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"⚠ 貼文讀取失敗：{e}")
        return False

    found = False
    for kw in KEYWORDS:
        if kw in html:
            print(f"   ✅ 找到關鍵字：{kw}")
            found = True

    if not found:
        print("   ℹ 沒有關鍵字，略過")
    return found


def send_to_discord(post_url: str):
    today = datetime.now().strftime("%Y-%m-%d")
    msg = (
        f"📚 **Threads 今日新書貼文通知｜{today}**\n\n"
        f"來源帳號：@{THREADS_USERNAME}\n"
        f"貼文連結：{post_url}"
    )

    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    if resp.status_code not in (200, 204):
        print("❌ Discord 推播失敗：", resp.status_code, resp.text)
    else:
        print("✅ Discord 推播成功！")


def main():
    print("🔍 使用 Firecrawl 監控 Threads 帳號...")
    print(f"   帳號：@{THREADS_USERNAME}")
    print(f"   關鍵字：{KEYWORDS}")

    # 讀取上次貼文
    last = load_last_seen()
    print("   上次貼文：", last)

    print(f"\n[{datetime.now()}] 抓取 Threads 主頁...")
    html = firecrawl_scrape(PROFILE_URL)

    code, post_url = extract_latest_post_code_and_url(html)
    if code is None:
        print("⚠ 沒有找到貼文，結束")
        return

    # 第一次執行，記錄但不推播
    if last is None:
        print("   第一次執行 → 只記錄，不推播")
        save_last_seen(code)
        return

    if code == last:
        print("   尚未有新貼文")
        return

    print("   ✅ 偵測到新貼文！")

    if post_matches_keywords(post_url):
        send_to_discord(post_url)
    else:
        print("   貼文沒關鍵字，不推播")

    save_last_seen(code)


if __name__ == "__main__":
    main()
