import os
import requests
import feedparser

# RSS Kaynağı
RSS_URL = "https://news.google.com/rss/search?q=Manchester+City&hl=en-GB&gl=GB&ceid=GB:en"
SEEN_FILE = "seen_news.txt"

# Telegram Bilgileri (GitHub Actions Secrets veya .env üzerinden alınır)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(title, link):
    """Telegram kanalına/grubuna formatlı mesaj gönderir."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Uyarı: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlanmamış!")
        return False

    text = (
        f"⚽ <b>Manchester City Yeni Haber</b>\n\n"
        f"📰 {title}\n\n"
        f"🔗 <a href='{link}'>Haberi Oku</a>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"Telegram bildirimi gönderildi: {title}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Telegram gönderim hatası: {e}")
        return False

def load_seen_news():
    """Daha önce gönderilen haberleri dosyadan okur."""
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_seen_news(seen_set):
    """Gönderilen haberleri dosyaya kaydeder."""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for item in sorted(seen_set):
            f.write(f"{item}\n")

def fetch_and_notify():
    seen_links = load_seen_news()
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("RSS akışından haber çekilemedi veya akış boş.")
        return

    new_count = 0
    # Eskiden yeniye doğru tara (böylece kanala kronolojik sırayla düşer)
    for entry in reversed(feed.entries):
        link = entry.link.strip()
        title = entry.title.strip()

        if link not in seen_links:
            # Telegram'a gönder
            success = send_telegram_message(title, link)
            if success:
                seen_links.add(link)
                new_count += 1

    if new_count > 0:
        save_seen_news(seen_links)
        print(f"Toplam {new_count} yeni haber iletildi.")
    else:
        print("Yeni haber yok.")

if __name__ == "__main__":
    fetch_and_notify()