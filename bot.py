import os
import re
import requests
import feedparser
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from deep_translator import GoogleTranslator

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
    },
    {
        "name": "The Athletic",
        "url": "https://news.google.com/rss/search?q=Manchester+City+site:theathletic.com&hl=en-GB&gl=GB&ceid=GB:en"
    }
]

SEEN_FILE = "seen_news.txt"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Aynı haberin farklı kaynaklarda tekrar göndermemesi için başlık benzerlik eşiği (0-1)
TITLE_SIMILARITY_THRESHOLD = 0.85

# seen_news.txt içindeki kayıtların ne kadar süre saklanacağı (gün)
SEEN_RETENTION_DAYS = 30

# Telegram mesajları arasında bekleme (rate limit'e çarpmamak için)
TELEGRAM_SEND_DELAY = 0.4

# Başlıkta geçerse haberi doğrudan çöpe atar
BLACKLIST_KEYWORDS = [
    "ratings", "fpl", "fantasy", "quiz", "opinion", "predicted xi",
    "lineup predicted", "how to watch", "stream", "tv channel",
    "ticket", "former star", "ex-player", "agent says"
]

# Google News gibi genel kaynaklarda Manchester City'nin adının
# gerçekten başlıkta geçtiğini doğrulamak için zorunlu kelimeler
REQUIRED_KEYWORDS = ["man city", "manchester city", "maresca", "etihad"]


def translate_to_turkish(text):
    """Metni Türkçeye çevirir; hata veya limit durumunda orijinal metni döner."""
    if not text:
        return ""
    try:
        time.sleep(0.8)  # Google hız sınırına (rate limit) takılmamak için kısa bekleme
        translated = GoogleTranslator(source='auto', target='tr').translate(text)

        if not translated or not translated.strip():
            return text

        return translated
    except Exception as e:
        print(f"Çeviri hatası: {e}")
        return text


def send_telegram_message(title, link, source_name):
    """Telegram kanalına Türkçe çevirili mesaj gönderir. Başarılıysa True, değilse False döner."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Uyarı: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlanmamış!")
        return False

    title_tr = translate_to_turkish(title)

    text = (
        f"⚽ <b>Manchester City Yeni Haber</b>\n\n"
        f"🇹🇷 {title_tr}\n"
        f"🇬🇧 <i>{title}</i>\n\n"
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
        print(f"[{source_name}] Bildirim gönderildi: {title_tr}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Telegram gönderim hatası: {e}")
        return False


def load_seen_news():
    """
    seen_news.txt dosyasını okur. Dosya formatı: 'link\\ttimestamp'
    Eski formatla (sadece link) uyumluluk için timestamp yoksa bugünün
    tarihini varsayar.
    Döndürür: {link: datetime} sözlüğü
    """
    seen = {}
    if not os.path.exists(SEEN_FILE):
        return seen

    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            link = parts[0]
            if len(parts) > 1:
                try:
                    ts = datetime.fromisoformat(parts[1])
                except ValueError:
                    ts = datetime.now()
            else:
                ts = datetime.now()
            seen[link] = ts
    return seen


def save_seen_news(seen_dict):
    """
    seen_dict'i diske yazar; SEEN_RETENTION_DAYS'ten eski kayıtları temizler
    ki dosya sınırsız büyümesin.
    """
    cutoff = datetime.now() - timedelta(days=SEEN_RETENTION_DAYS)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for link, ts in sorted(seen_dict.items(), key=lambda x: x[1]):
            if ts < cutoff:
                continue
            f.write(f"{link}\t{ts.isoformat()}\n")


def is_relevant_news(title, source_name):
    """
    Haberin gerçekten alakalı olup olmadığını kontrol eder:
    - Blacklist'teki kelimelerden biri geçiyorsa (ratings, quiz, ticket vb.) reddeder.
    - Google News / MEN gibi genel kaynaklarda başlıkta City ile ilgili
      zorunlu kelimelerden biri geçmiyorsa reddeder (alakasız haberleri eler).
    """
    norm_title = title.lower()

    if any(bad_word in norm_title for bad_word in BLACKLIST_KEYWORDS):
        return False

    if source_name in ["Google News", "Manchester Evening News"]:
        if not any(req_word in norm_title for req_word in REQUIRED_KEYWORDS):
            return False

    return True


def normalize_title(title):
    """Benzerlik kıyaslaması için başlığı sadeleştirir."""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def is_duplicate_title(title, recent_titles):
    """
    Aynı haberin farklı kaynaklarda (farklı link, benzer başlık) tekrar
    gönderilmesini önlemek için bu turda zaten işlenmiş başlıklarla kıyaslar.
    """
    norm_title = normalize_title(title)
    for seen_title in recent_titles:
        ratio = SequenceMatcher(None, norm_title, seen_title).ratio()
        if ratio >= TITLE_SIMILARITY_THRESHOLD:
            return True
    return False


def fetch_and_notify():
    seen_links = load_seen_news()  # {link: datetime}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    total_new_count = 0
    session_titles = []

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

        for entry in reversed(feed.entries):
            link = getattr(entry, "link", "").strip()
            title = getattr(entry, "title", "").strip()

            if not link or not title:
                continue

            if link in seen_links:
                continue

            if not is_relevant_news(title, source_name):
                seen_links[link] = datetime.now()
                continue

            if is_duplicate_title(title, session_titles):
                seen_links[link] = datetime.now()
                print(f"[{source_name}] Benzer başlık zaten gönderildi, atlanıyor: {title}")
                continue

            success = send_telegram_message(title, link, source_name)
            if success:
                seen_links[link] = datetime.now()
                session_titles.append(normalize_title(title))
                total_new_count += 1
                time.sleep(TELEGRAM_SEND_DELAY)
            else:
                print(f"[{source_name}] Gönderim başarısız, sonraki çalıştırmada tekrar denenecek: {title}")

    if total_new_count > 0:
        save_seen_news(seen_links)
        print(f"Toplam {total_new_count} yeni haber işlendi.")
    else:
        save_seen_news(seen_links)
        print("Yeni haber yok.")


if __name__ == "__main__":
    fetch_and_notify()