import os
import re
import sys
import time
import logging
import unicodedata
import requests
import html
import feedparser
from datetime import datetime, timedelta
from difflib import SequenceMatcher

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
        "name": "Beanyman Sports",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCiVg6vRhuyjsWgHkDNOig6A"
    }
]

SEEN_FILE = "seen_news.txt"
SEEN_TITLES_FILE = "seen_titles.txt"
LOCK_FILE = "bot.lock"
LOG_FILE = "bot.log"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TITLE_SIMILARITY_THRESHOLD = 0.80
TITLE_WORD_OVERLAP_THRESHOLD = 0.70
SEEN_RETENTION_DAYS = 30
TELEGRAM_SEND_DELAY = 0.4
MAX_PER_RUN = 10

# Google News üzerinden gelen düşük kaliteli, clickbait, dedikodu veya
# rakip takım odaklı yayıncılar.
BLACKLISTED_PUBLISHERS = {
    # Tabloid, dedikodu ve clickbait agregatörler
    "football365", "football365.com", "the sun", "thesun.co.uk",
    "daily mail", "dailymail.co.uk", "daily mirror", "the mirror", "mirror.co.uk",
    "daily express", "express.co.uk", "daily star", "the daily star", "dailystar.co.uk",
    "teamtalk", "teamtalk.com", "caughtoffside", "caughtoffside.com",
    "givemesport", "givemesport.com", "talksport", "talksport.com",
    "planet football", "planetfootball.com", "fourfourtwo", "fourfourtwo.com",
    "sports mole", "sportsmole.co.uk", "football insider", "90min",
    "goal.com", "livescore", "onefootball", "dazn", "sportbible",
    "metro.co.uk", "aol.co.uk", "aol.com", "hayters.com",
    "sportsadda", "the football freak", "vavel.com",
    # Rakip takım taraftar siteleri ve yerel gazeteleri
    "this is anfield", "liverpool echo", "liverpoolecho.co.uk",
    "the anfield wrap", "daveockop", "liverpool fc",
    "arseblog", "arseblog news", "daily cannon", "pain in the arsenal",
    "football.london", "football london", "tottenham hotspur",
    "sunderland echo", "rangersnews.uk", "ipswich star",
    "east anglian daily times", "nottingham post", "sussexworld",
    "hampshire chronicle", "lancashire telegraph", "the mag",
    # Taraftar blogları / ikincil özet siteleri
    "city xtra", "cityxtra.co.uk", "esteemed kompany", "read man city",
}

# Başlıkta geçerse haberi doğrudan çöpe atar (tüm kaynaklar için geçerli)
BLACKLIST_KEYWORDS = [
    # Reyting, fantezi futbol, tahmin ve eğlence içerikleri
    "ratings", "fpl", "fantasy", "quiz", "opinion", "column", "letters",
    "mailbag", "podcast", "have your say", "talking points",
    "winners and losers", "supercomputer", "mock draft", "archive",
    "prediction", "predictions", "predicts", "recap",
    "head-to-head", "head to head", "h2h",
    # Kadro tahminleri ve maç önü dizilişler
    "predicted xi", "lineup predicted", "predicted lineup", "predicted line-up",
    "starting lineup", "starting line-up", "starting xi", "confirmed team news",
    "line-ups", "lineups", "line ups", "combined xi", "man city xi",
    # Yayın, bilet ve izleme bilgileri
    "how to watch", "where to watch", "what time", "kick-off time",
    "stream", "streams", "tv channel", "tv info", "ticket", "tickets",
    # Dedikodu, söylenti, eski oyuncular ve yorumcu polemikleri
    "rumour", "rumours", "rumor", "rumors", "gossip", "paper talk",
    "paper round", "transfer talk", "transfer chatter", "media watch",
    "former star", "ex-player", "ex-man city", "former man city",
    "ex-manchester city", "former manchester city", "ex-city", "former city",
    "ex-premier league", "former premier league", "ex-united", "ex-man utd",
    "ex-liverpool", "ex-arsenal", "ex-chelsea", "ex-real madrid",
    "cult hero", "pundit", "pundits", "agent says", "agent hints", "advisor",
    "slams", "mocks", "banner", "bombshell", "turned down", "i rejected",
    "when i joined", "should've joined", "should have joined", "signed shirts",
    "police", "arrests", "bananas", "inflatable",
    # FFP / 115 suçlama davası spekülasyonları, politik polemikler ve ceza tahminleri
    "charges", "115 charges", "114 charges", "ffp", "financial fair play",
    "guilty verdict", "guilty verdicts", "points deduction", "expulsion",
    "expelled", "relegated", "relegation", "stripped of", "punishment",
    "punishments", "sanction", "sanctions", "settlement", "whistleblower",
    "mancini", "andy burnham", "burnham", "lisa nandy", "regulator", "hmrc",
    "illegal payments", "rule breaches", "cheating",
    # Kadın futbol takımı (kelime, lig ve oyuncu/teknik ekip isimleri)
    "women", "women's", "womens", "wsl", "uwcl", "wfc", "ladies", "she/her",
    "lionesses", "jeglertz", "lauren hemp", "hemp", "slegers",
    "lucy bronze", "khadija shaw", "bunny shaw", "gareth taylor",
    "alex greenwood", "risa shimizu", "mary fowler", "vivianne miedema",
    "miedema", "kerolin", "roebuck", "keating",
    # Alt yaş grupları, akademi ve e-spor
    "u18", "u18s", "u19", "u19s", "u21", "u21s", "u23", "u23s",
    "under-18", "under-19", "under-21", "under-23", "academy", "youth cup",
    "eds", "elite development squad", "wonderkid", "youngster", "scholarship",
    "esports", "e-sports",
    # Canlı yayın / maç takip içerikleri; kalıcı haber değeri taşımazlar.
    "live", "live blog", "live updates", "live stream", "live coverage",
    "watch live", "live commentary", "as it happened", "minute by minute",
    "match thread", "matchday live", "highlights", "listen live",
    # Rutin kulüp/video ve maç etrafı içerikleri.
    "watch", "team talk", "week ahead", "monday marker", "match report",
    "report:", "match preview", "preview:", "pre-match", "pre match",
    "post-match", "post match", "full-time", "full time", "matchday",
    "match day", "opposition view", "reaction",
    # Bahis / oran içerikleri
    "odds", "betting", "bet builder", "acca", "accumulator",
    "free bet", "best bets", "tips", "correct score", "each way",
]

# Man City ile doğrudan ilgili olduğunu doğrulamak için kullanılan kelimeler
REQUIRED_KEYWORDS = ["man city", "manchester city", "maresca", "etihad"]

# Kanalın yayın politikasına göre yalnızca kalıcı, paylaşmaya değer kulüp
# gelişmeleri gönderilir. Maç içeriği ve yorum başlıkları, yeni bir ifade ile
# yazılsalar bile bu listede bir sinyal taşımadıkça bildirim oluşturmaz.
# Not: "leaves", "deal", "released", "extension", "recovery", "manager", "coach"
# gibi tek başına çok genel olan ve alakasız haberlerde sıkça geçen kelimeler
# yerine doğrudan somut ifadeler kullanılır.
IMPORTANT_NEWS_KEYWORDS = [
    # Transfer, sözleşme ve kadro hareketleri
    "transfer", "signing", "signs", "signed", "contract",
    "contract extension", "extends contract", "new contract",
    "loan", "loaned", "joins", "joined", "departure",
    "release clause", "squad list", "registered", "registration", "promoted",
    "new deal", "transfer deal", "loan deal", "medical", "bid", "fee agreed",
    "reach agreement", "agrees terms", "personal terms",
    # Sakatlık ve oyuncunun müsaitliği
    "injury", "injured", "fitness", "surgery", "recovering",
    "ruled out", "unavailable", "returns from injury", "injury update",
    "injury blow", "injury boost", "injury scare",
    # Teknik ekip değişimleri
    "appointed", "appointment", "resigns",
    "new manager", "new head coach",
    # Kulübün maçtan yayımladığı fotoğraf seçkileri de fan hesabı için
    # paylaşılabilir içerik olarak kabul edilir.
    "gallery", "photo gallery", "picture special",
]

BEANYMAN_SOURCE_NAME = "Beanyman Sports"
BEANYMAN_CITY_IDENTIFIERS = ["man city", "manchester city", "maresca"]
BEANYMAN_INTERVIEW_INDICATORS = [
    "press conference", "interview", "maresca", "pre-match", "post-match",
]

# Başka bir spora ait olduğu belli terimler. Başlıkta bunlardan biri geçip
# REQUIRED_KEYWORDS'ten hiçbiri geçmiyorsa haber, kaynağı ne olursa olsun elenir.
OTHER_SPORT_KEYWORDS = [
    "f1", "formula 1", "grand prix", "motogp", "moto gp",
    "tennis", "wimbledon", "atp", "wta", "us open", "roland garros",
    "nba", "nfl", "mlb", "nhl",
    "cricket", "ipl", "ashes",
    "rugby", "six nations",
    "boxing", "ufc", "mma",
    "darts", "snooker", "cycling", "tour de france",
    "golf", "ryder cup", "olympics",
]

# Rakip kulüp veya teknik direktör özneleri (başlık bunlarla başlayıp sadece
# "Man City maçı öncesi" diyorsa rakip takımın iç haberidir).
OPPONENT_SUBJECT_PREFIXES = (
    "liverpool", "arsenal", "man utd", "manchester united", "chelsea",
    "tottenham", "spurs", "newcastle", "aston villa", "brighton", "everton",
    "sunderland", "ipswich", "brentford", "fulham", "west ham", "wolves",
    "nottingham forest", "crystal palace", "bournemouth", "leicester",
    "southampton", "leeds", "bayern", "psg", "paris saint-germain",
    "real madrid", "barcelona", "inter", "juventus",
    "andoni iraola", "mikel arteta", "michael carrick", "arne slot",
    "dominik szoboszlai", "alexander isak", "cody gakpo", "virgil van dijk",
)

# Benzerlik karşılaştırmasında elenecek genel/dolgu kelimeler
TITLE_STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "after", "amid", "as", "with", "over", "by", "from", "up", "out",
    "is", "are", "was", "were", "be", "been", "will", "would", "could",
    "should", "has", "have", "had", "his", "her", "their", "its", "our",
    "man", "city", "citys", "manchester", "fc", "mcfc", "club", "clubs",
    "news", "update", "latest", "report", "reports", "says", "said",
    "ahead", "before", "into", "about", "new", "more", "who", "what",
    "why", "how", "when", "where",
}


def is_broad_search_source(url):
    return "news.google.com" in url


def extract_publisher_and_clean_title(raw_title, source_url):
    """Google News başlıklarının sonundaki ' - Yayıncı' kısmını ayıklar."""
    if is_broad_search_source(source_url) and " - " in raw_title:
        clean_title, publisher = raw_title.rsplit(" - ", 1)
        clean_title = clean_title.strip()
        publisher = publisher.strip()
        if clean_title and publisher:
            return clean_title, publisher
    return raw_title.strip(), ""


def is_blacklisted_publisher(publisher):
    if not publisher:
        return False
    norm_pub = unicodedata.normalize("NFKC", publisher).lower().strip()
    return norm_pub in BLACKLISTED_PUBLISHERS


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def send_telegram_message(title, link, source_name):
    """Telegram kanalına orijinal dilde haber mesajı gönderir."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlanmamış!")
        return False

    safe_title = html.escape(title)
    safe_source = html.escape(source_name)
    text = (
        f"⚽ <b>Manchester City News</b>\n\n"
        f"📰 {safe_title}\n\n"
        f"📌 <b>Kaynak:</b> {safe_source}\n"
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

    for attempt in range(2):
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 429:
                retry_after = int(response.json().get("parameters", {}).get("retry_after", 5))
                logger.warning(f"Telegram 429 hız sınırı, {retry_after} sn bekleniyor...")
                time.sleep(min(retry_after, 30))
                continue
            response.raise_for_status()
            logger.info(f"[{source_name}] Bildirim gönderildi: {title}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"[{source_name}] Telegram gönderim hatası: {e}")
            return False
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


BLACKLIST_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(k) for k in BLACKLIST_KEYWORDS) + r")(?!\w)",
    re.IGNORECASE,
)
IMPORTANT_NEWS_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(k) for k in IMPORTANT_NEWS_KEYWORDS) + r")(?!\w)",
    re.IGNORECASE,
)


def contains_blacklisted_keyword(title):
    """Süslü Unicode karakterleri normalleştirip tam kelime eşleştirir."""
    normalized_title = unicodedata.normalize("NFKC", title)
    return bool(BLACKLIST_PATTERN.search(normalized_title))


def contains_important_news_keyword(title):
    """Başlığın kanalın paylaşım politikasındaki ana konulardan birini taşıdığını doğrular."""
    normalized_title = unicodedata.normalize("NFKC", title)
    return bool(IMPORTANT_NEWS_PATTERN.search(normalized_title))


def is_beanyman_city_interview(title, link):
    """Beanyman'ın yalnızca City teknik direktörüyle ilgili videolarını kabul eder."""
    if "/shorts/" in link.lower():
        return False

    normalized_title = unicodedata.normalize("NFKC", title).lower()
    if "chelsea" in normalized_title and "man city" not in normalized_title and "manchester city" not in normalized_title:
        return False
    has_city_identifier = any(identifier in normalized_title for identifier in BEANYMAN_CITY_IDENTIFIERS)
    has_interview_indicator = any(indicator in normalized_title for indicator in BEANYMAN_INTERVIEW_INDICATORS)
    return has_city_identifier and has_interview_indicator


def is_opponent_match_injury_news(norm_title):
    """Rakip takımların Man City maçı öncesi kendi sakatlık/kadro haberlerini eler."""
    if norm_title.startswith(OPPONENT_SUBJECT_PREFIXES):
        if any(w in norm_title for w in ("injury", "injured", "fitness", "ruled out", "unavailable", "sweating on", "hit with")):
            return True
    if re.search(r"\b(ahead of|before|prior to|for)\s+(?:[\w\s]{0,20}\b)?(man city|manchester city|city)\s+(clash|trip|game|match|test|visit|showdown|tie)\b", norm_title):
        if not norm_title.startswith(("man city", "manchester city", "enzo maresca", "maresca", "erling haaland", "haaland", "city ")):
            return True
    if re.search(r"\b(clash|showdown|game|match|tie)\s+with\s+(man city|manchester city)\b", norm_title):
        if not norm_title.startswith(("man city", "manchester city", "enzo maresca", "maresca", "erling haaland", "haaland", "city ")):
            return True
    return False


def is_relevant_news(title, source_name, source_url, link=""):
    # Beanyman Sports, teknik direktörün basın toplantıları ve röportajları
    # için istisnai bir kaynak. Bu videolarda "LIVE" geçmesi normaldir ve
    # genel canlı yayın filtresine takılmamalıdır.
    if source_name == BEANYMAN_SOURCE_NAME:
        return is_beanyman_city_interview(title, link)

    clean_title, publisher = extract_publisher_and_clean_title(title, source_url)
    if is_blacklisted_publisher(publisher):
        return False

    norm_title = unicodedata.normalize("NFKC", clean_title).lower()

    # Chelsea ile ilgili Maresca geçmişi haberlerini (City adı geçmiyorsa) ele
    if "chelsea" in norm_title and "man city" not in norm_title and "manchester city" not in norm_title:
        return False

    # Rakip takımın "Man City maçı öncesi" kendi sakatlık haberlerini ele
    if is_opponent_match_injury_news(norm_title):
        return False

    # 1) Blacklist: her kaynak için geçerli
    if contains_blacklisted_keyword(clean_title):
        return False

    # Bildirimleri maç anlatımı ve yorumlardan arındırmak için, başlıkta
    # transfer/kadro, sakatlık ya da teknik ekip gelişimi bulunması zorunlu.
    if not contains_important_news_keyword(clean_title):
        return False

    has_required = any(req_word in norm_title for req_word in REQUIRED_KEYWORDS)

    # 2) Başka spora ait olduğu belli olan ama City ile ilgisi görünmeyen
    # başlıklar: kaynak ne olursa olsun elenir.
    if any(sport_word in norm_title for sport_word in OTHER_SPORT_KEYWORDS):
        if not has_required:
            return False

    # 3) Google News tabanlı geniş aramalarda City ile ilgili kelime zorunlu.
    if is_broad_search_source(source_url):
        if not has_required:
            return False

    return True


def normalize_title(title, source_url=""):
    clean_title, _ = extract_publisher_and_clean_title(title, source_url)
    clean_title = unicodedata.normalize("NFKC", clean_title).lower()
    clean_title = re.sub(r"[^\w\s]", "", clean_title)
    clean_title = re.sub(r"\s+", " ", clean_title).strip()
    return clean_title


def extract_significant_words(norm_title):
    return {
        w for w in norm_title.split()
        if len(w) > 2 and w not in TITLE_STOPWORDS
    }


def is_duplicate_title(norm_title, recent_titles):
    words_a = extract_significant_words(norm_title)
    for seen_title in recent_titles:
        ratio = SequenceMatcher(None, norm_title, seen_title).ratio()
        if ratio >= TITLE_SIMILARITY_THRESHOLD:
            return True
        if len(words_a) >= 3:
            words_b = extract_significant_words(seen_title)
            if len(words_b) >= 3:
                overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
                if overlap >= TITLE_WORD_OVERLAP_THRESHOLD:
                    return True
    return False


def acquire_lock():
    if os.path.exists(LOCK_FILE):
        age_seconds = time.time() - os.path.getmtime(LOCK_FILE)
        if age_seconds < 900:
            logger.warning("Başka bir çalıştırma zaten sürüyor gibi görünüyor. Çıkılıyor.")
            return False
        else:
            logger.warning("Eski/askıda kalmış lock dosyası siliniyor.")

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
        logger.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID tanımlı değil. Çıkılıyor.")
        return

    seen_links = load_timestamped_set(SEEN_FILE)
    seen_title_hist = load_timestamped_set(SEEN_TITLES_FILE)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    total_new_count = 0
    session_titles = []

    for feed_info in RSS_FEEDS:
        source_name = feed_info["name"]
        url = feed_info["url"]

        if total_new_count >= MAX_PER_RUN:
            logger.info(f"MAX_PER_RUN ({MAX_PER_RUN}) sınırına ulaşıldı, kalan kaynaklar atlanıyor.")
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

                if link in seen_links:
                    continue

                if not is_relevant_news(title, source_name, url, link):
                    seen_links[link] = datetime.now()
                    continue

                clean_title, publisher = extract_publisher_and_clean_title(title, url)
                norm_title = normalize_title(title, url)

                if is_duplicate_title(norm_title, session_titles) or \
                   is_duplicate_title(norm_title, seen_title_hist.keys()):
                    seen_links[link] = datetime.now()
                    logger.info(f"[{source_name}] Benzer başlık zaten gönderilmiş, atlanıyor: {clean_title}")
                    continue

                display_source = f"{source_name} ({publisher})" if publisher else source_name
                success = send_telegram_message(clean_title, link, display_source)
                if success:
                    now = datetime.now()
                    seen_links[link] = now
                    seen_title_hist[norm_title] = now
                    session_titles.append(norm_title)
                    total_new_count += 1
                    time.sleep(TELEGRAM_SEND_DELAY)
                else:
                    logger.warning(f"[{source_name}] Gönderim başarısız: {clean_title}")

            except Exception as e:
                logger.exception(f"[{source_name}] Hata, haber atlanıyor: {e}")
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
