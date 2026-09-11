import os
import re
import sys
import time
import logging
import requests
import feedparser
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
SEEN_TITLES_FILE = "seen_titles.txt"
LOCK_FILE = "bot.lock"
LOG_FILE = "bot.log"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TITLE_SIMILARITY_THRESHOLD = 0.85

SEEN_RETENTION_DAYS = 30

TELEGRAM_SEND_DELAY = 0.4

MAX_PER_RUN = 15

# Başlıkta geçerse haberi doğrudan çöpe atar
BLACKLIST_KEYWORDS = [
    "ratings", "fpl", "fantasy", "quiz", "opinion", "predicted xi",
    "lineup predicted", "how to watch", "stream", "tv channel",
    "ticket", "former star", "ex-player", "agent says"
]

REQUIRED_KEYWORDS = ["man city", "manchester city", "maresca", "etihad"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


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
        logger.warning(f"Çeviri hatası: {e}")
        return text


def send_telegram_message(title, link, source_name):
    """Telegram kanalına Türkçe çevirili mesaj gönderir. Başarılıysa True, değilse False döner."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlanmamış!")
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
        logger.info(f"[{source_name}] Bildirim gönderildi: {title_tr}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"[{source_name}] Telegram gönderim hatası: {e}")
        return False


def load_timestamped_set(filepath):
    data = {}
    if not os.path.exists(filepath):
        return data

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            key = parts[0]
            if len(parts) > 1:
                try:
                    ts = datetime.fromisoformat(parts[1])
                except ValueError:
                    ts = datetime.now()
            else:
                ts = datetime.now()
            data[key] = ts
    return data


def save_timestamped_set(filepath, data_dict):
    cutoff = datetime.now() - timedelta(days=SEEN_RETENTION_DAYS)
    with open(filepath, "w", encoding="utf-8") as f:
        for key, ts in sorted(data_dict.items(), key=lambda x: x[1]):
            if ts < cutoff:
                continue
            f.write(f"{key}\t{ts.isoformat()}\n")


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


def is_duplicate_title(norm_title, recent_titles):
    """
    Aynı haberin farklı kaynaklarda (farklı link, benzer başlık) tekrar
    gönderilmesini önlemek için karşılaştırma yapar.
    recent_titles: normalize edilmiş başlıkların bulunduğu iterable
    (bu run'daki oturum başlıkları + diskten yüklenen geçmiş başlıklar).
    """
    for seen_title in recent_titles:
        ratio = SequenceMatcher(None, norm_title, seen_title).ratio()
        if ratio >= TITLE_SIMILARITY_THRESHOLD:
            return True
    return False

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        age_seconds = time.time() - os.path.getmtime(LOCK_FILE)
        if age_seconds < 900:  # 15 dakikadan yeni bir kilit varsa çalışmayı reddet
            logger.warning("Başka bir çalıştırma zaten sürüyor gibi görünüyor (lock dosyası mevcut). Çıkılıyor.")
            return False
        else:
            logger.warning("Eski/askıda kalmış bir lock dosyası bulundu, siliniyor.")

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError as e:
        logger.warning(f"Lock dosyası silinemedi: {e}")


def fetch_and_notify():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlı değil. "
            "Feed'ler çekilmeyecek, script sonlandırılıyor."
        )
        return

    seen_links = load_timestamped_set(SEEN_FILE)          # {link: datetime}
    seen_title_hist = load_timestamped_set(SEEN_TITLES_FILE)  # {norm_title: datetime}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    total_new_count = 0
    session_titles = []  # bu run'da yeni gönderilen normalize başlıklar

    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        url = feed_info["url"]

        if total_new_count >= MAX_PER_RUN:
            logger.info(f"MAX_PER_RUN ({MAX_PER_RUN}) sınırına ulaşıldı, kalan kaynaklar bu run'da atlanıyor.")
            break

        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception as e:
            logger.error(f"[{source_name}] Kaynak okuma hatası: {e}")
            continue

        if not feed.entries:
            continue

        for entry in reversed(feed.entries):
            if total_new_count >= MAX_PER_RUN:
                break

            try:
                link = getattr(entry, "link", "").strip()
                title = getattr(entry, "title", "").strip()

                if not link or not title:
                    continue

                norm_title = normalize_title(title)

                if link in seen_links:
                    continue

                if not is_relevant_news(title, source_name):
                    seen_links[link] = datetime.now()
                    continue

                if is_duplicate_title(norm_title, session_titles) or \
                   is_duplicate_title(norm_title, seen_title_hist.keys()):
                    seen_links[link] = datetime.now()
                    logger.info(f"[{source_name}] Benzer başlık zaten gönderilmiş, atlanıyor: {title}")
                    continue

                success = send_telegram_message(title, link, source_name)
                if success:
                    now = datetime.now()
                    seen_links[link] = now
                    seen_title_hist[norm_title] = now
                    session_titles.append(norm_title)
                    total_new_count += 1
                    time.sleep(TELEGRAM_SEND_DELAY)  # Telegram rate limit'ine karşı
                else:
                    
                    logger.warning(f"[{source_name}] Gönderim başarısız, sonraki çalıştırmada tekrar denenecek: {title}")

            except Exception as e:
                logger.exception(f"[{source_name}] Beklenmeyen hata, bu haber atlanıyor: {e}")
                continue

    save_timestamped_set(SEEN_FILE, seen_links)
    save_timestamped_set(SEEN_TITLES_FILE, seen_title_hist)

    if total_new_count > 0:
        logger.info(f"Toplam {total_new_count} yeni haber işlendi.")
    else:
        logger.info("Yeni haber yok.")


if __name__ == "__main__":
    if not acquire_lock():
        sys.exit(0)
    try:
        fetch_and_notify()
    finally:
        release_lock()