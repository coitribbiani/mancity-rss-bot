import os
import requests
import feedparser

# Taranacak RSS Kaynakları Listesi
RSS_FEEDS = [
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=Manchester+City&hl=en-GB&gl=GB&ceid=GB:en"
    },
    {
        "name": "Manchester Evening News",
        "url": "https://www.manchestereveningnews.co.uk/all-about/manchester-city-fc/?service=rss"
    },
    {
        "name": "BBC Sport",
        "url": "https://feeds.bbci.co.uk/sport/football/teams/manchester-city/rss.xml"
    },
    {
        "name": "Sky Sports",
        "url": "https://www.skysports.com/rss/12040"
    }
    {
        "name": "The Athletic",
        "url": "https://news.google.com/rss/search?q=Manchester+City+site:theathletic.com&hl=en-GB&gl=GB&ceid=GB:en"
    }
]

SEEN_FILE = "seen_news.txt"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(title, link, source_name):
    """Telegram kanalına kaynak bilgisiyle formatlı mesaj gönderir."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Uyarı: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlanmamış!")
        return False

    text = (
        f"⚽ <b>Manchester City Yeni Haber</b>\n\n"
        f"📰 {title}\n\n"
        f"📌 <b>Kaynak:</b> {source_name}\n"
        f"🔗 <a href='{link}'>Haberi Oku</a>\n\n"
        f"#ManCity #MCFC"
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
        print(f"[{source_name}] Bildirim gönderildi: {title}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Telegram gönderim hatası: {e}")
        return False

def load_seen_news():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_seen_news(seen_set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for item in sorted(seen_set):
            f.write(f"{item}\n")

def fetch_and_notify():
    seen_links = load_seen_news()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    total_new_count = 0

    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        url = feed_info["url"]

        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception as e:
            print(f"[{source_name}] Kaynak okuma hatası: {e}")
            continue

        if not feed.entries:
            continue

        # En yeni haberleri sırayla al (tersten gezerek kronolojik iletir)
        for entry in reversed(feed.entries):
            link = getattr(entry, "link", "").strip()
            title = getattr(entry, "title", "").strip()

            if not link or not title:
                continue

            if link not in seen_links:
                success = send_telegram_message(title, link, source_name)
                if success:
                    seen_links.add(link)
                    total_new_count += 1
                else:
                    # Token yoksa yerel testte yine de hafızaya al
                    seen_links.add(link)
                    total_new_count += 1

    if total_new_count > 0:
        save_seen_news(seen_links)
        print(f"Toplam {total_new_count} yeni haber işlendi.")
    else:
        print("Yeni haber yok.")

if __name__ == "__main__":
    fetch_and_notify()