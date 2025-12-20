import json
import os
import re
import time
from datetime import datetime

import requests


# === Threads 帳號設定 ===
THREADS_USERNAME = "yuri_news_tw"
PROFILE_URL = f"https://www.threads.net/@{THREADS_USERNAME}"

# 關鍵字
KEYWORDS = ["今日", "新書"]

# Firecrawl 設定
FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

# 記錄上次非置頂貼文
STATE_FILE = "last_seen.json"

# 你帳號的置頂貼文數量
PINNED_COUNT = 3

# === Railway 環境變數 ===
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not FIRECRAWL_API_KEY:
    raise RuntimeError("❌ FIRECRAWL_API_KEY 尚未在 Railway Variables 設定")
if not DISCORD_WEBHOOK_URL:
    raise RuntimeError("❌ DISCORD_WEBHOOK_URL 尚未在 Railway Variables 設定")


# === 讀/寫 last_seen.json ===
def load_last_seen():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("last_code")
    except FileNotFoundError:
        return None


def save_last_seen(code: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_code": code}, f, ensure_ascii=False, indent=2)


# === Firecrawl 抓 HTML（Retry 已停用） ===
def firecrawl_scrape(url: str, attempt: int = 1) -> str | None:
    """呼叫 Firecrawl（retry 已註解）。"""

    payload = {
        "url": url,
        "formats": ["html"],
        "waitFor": 12000,      # 等 JS 載入較久
        "timeout": 30000,      # Firecrawl 自己的 timeout (ms)
        "maxAge": 0,           # 每次都抓最新，不用 cache
        "onlyMainContent": True,
    }

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            FIRECRAWL_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=40,   # requests 的 timeout（秒）
        )

        print("   Firecrawl 狀態碼：", resp.status_code)

        if resp.status_code >= 500 or resp.status_code == 408:
            raise RuntimeError(f"Firecrawl 回應 {resp.status_code}")

        resp.raise_for_status()
        data = resp.json()

        # 解析 Firecrawl 可能回傳的格式
        if "html" in data:
            return data["html"]
        if "data" in data and isinstance(data["data"], dict) and "html" in data["data"]:
            return data["data"]["html"]

        print("⚠ Firecrawl 回傳格式錯誤：", str(data)[:300])
        return None

    except Exception as e:
        print(f"⚠ Firecrawl 抓取失敗（第 {attempt} 次）：{e}")

        # === Retry 已停用（保留程式碼但註解） ===
        # if attempt == 1:
        #     print("   → 等 5 秒後再試一次...")
        #     time.sleep(5)
        #     return firecrawl_scrape(url, attempt=2)

        print("❌ Firecrawl 失敗，放棄這次抓取")
        return None


# === 用正則抓 Threads 連結 ===
POST_URL_RE = re.compile(
    r"https://www\.threads\.(?:net|com)/@[^/]+/post/([A-Za-z0-9_-]+)"
)


# === 取置頂之後的最新貼文 ===
def extract_latest_post_code_and_url(html: str):
    raw = POST_URL_RE.findall(html)
    if not raw:
        print("⚠ 找不到任何貼文連結")
        return None, None

    # 去重保持順序
    seen = set()
    codes = []
    for c in raw:
        if c not in seen:
            seen.add(c)
            codes.append(c)

    print("   抓到貼文代碼列表：", codes[:10])

    # 避免 index error
    if len(codes) <= PINNED_COUNT:
        code = codes[-1]  # fallback：抓最後一篇
    else:
        code = codes[PINNED_COUNT]

    url = f"https://www.threads.net/@{THREADS_USERNAME}/post/{code}"
    print(f"   選定貼文代碼：{code}")
    print(f"   貼文網址：{url}")
    return code, url


# === 檢查是否有關鍵字 ===
def post_matches_keywords(post_url: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        resp = requests.get(post_url, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print("⚠ 貼文讀取失敗：", e)
        return False

    found = False
    for kw in KEYWORDS:
        if kw in html:
            print(f"   ✅ 找到關鍵字：{kw}")
            found = True

    if not found:
        print("   ℹ 沒有關鍵字")
    return found


# === 推播 Discord ===
def send_to_discord(post_url: str):
    today = datetime.now().strftime("%Y-%m-%d")

    msg = (
        f"📚 **Threads 新書貼文通知｜{today}**\n\n"
        f"來源：@{THREADS_USERNAME}\n"
        f"連結：{post_url}"
    )

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=15)
        if resp.status_code not in (200, 204):
            print("❌ Discord 推播失敗：", resp.status_code, resp.text)
        else:
            print("✅ Discord 推播成功！")
    except Exception as e:
        print("⚠ Discord 錯誤：", e)


# === 主流程 ===
def main():
    print("🔍 監控 Threads ...")
    print("   帳號：", THREADS_USERNAME)
    print("   關鍵字：", KEYWORDS)

    last = load_last_seen()
    print("   上次非置頂貼文：", last)

    print(f"\n[{datetime.now()}] 抓取 Threads 主頁...")
    html = firecrawl_scrape(PROFILE_URL)

    if not html:
        print("⚠ 這輪沒抓到 HTML，跳過")
        return

    code, post_url = extract_latest_post_code_and_url(html)
    if not code:
        print("⚠ 沒找到貼文")
        return

    # A：避免重複抓 pinned（智慧化減少 Firecrawl 壓力）
    if code == last:
        print("ℹ 和上次相同 → 尚未有新貼文")
        return

    print("   ✅ 偵測到新貼文！")

    if post_matches_keywords(post_url):
        send_to_discord(post_url)
    else:
        print("   ✘ 沒符合關鍵字，不推播")

    # 永遠記下最新非置頂貼文
    save_last_seen(code)


if __name__ == "__main__":
    main()
