"""
Combined RSS feed generator for three Saudi municipal news sites:
  - eamana.gov.sa      (JS-rendered React app)
  - alriyadh.gov.sa    (server-rendered Next.js, no JS needed)
  - jeddah.gov.sa      (JS/AJAX-loaded content)

Produces ONE merged file: combined_news.xml (RSS 2.0), with a
<source> field on the description so you can tell which site each
item came from, plus tags to filter later if you want.

SETUP (one time):
    pip install playwright beautifulsoup4 requests
    playwright install chromium

USAGE:
    python combined_rss.py
"""

import datetime
import html
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT_FILE = Path(__file__).parent / "combined_news.xml"

# Only items whose title or summary contain at least one of these keywords
# will be kept in the final feed. Edit this list to adjust what gets through.
KEYWORD_WHITELIST = [
    "إغلاق",
    "افتتاح",
    "طريق",
    "شارع",
    "تطوير",
    "بالتعاون مع المرور",
    "بالتنسيق مع المرور",
    "إشارة",
    "دوار",
]


def matches_whitelist(item: dict) -> bool:
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    return any(keyword in text for keyword in KEYWORD_WHITELIST)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def render_with_browser(url: str, wait_ms: int = 2500) -> str:
    """Load a JS-heavy page with a real (headless) browser and return HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(wait_ms)
        content = page.content()
        browser.close()
        return content


# ---------------------------------------------------------------------------
# 1) eamana.gov.sa  -- JS-rendered React cards
# ---------------------------------------------------------------------------
def scrape_eamana() -> list[dict]:
    url = "https://www.eamana.gov.sa/mediacenter/news"
    base = "https://www.eamana.gov.sa"
    page_html = render_with_browser(url)
    soup = BeautifulSoup(page_html, "html.parser")
    items = []

    for h3 in soup.find_all("h3"):
        card = h3.find_parent("div")
        while card is not None and not card.find("a", href=True):
            card = card.find_parent("div")
        if card is None:
            continue

        title = h3.get_text(strip=True)
        summary_tag = h3.find_next_sibling("p")
        summary = summary_tag.get_text(strip=True) if summary_tag else ""

        link_tag = card.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        link = base + href if href.startswith("/") else (href or url)

        items.append(
            {
                "title": title,
                "summary": summary,
                "link": link,
                "source": "أمانة المنطقة الشرقية",
            }
        )

    return items


# ---------------------------------------------------------------------------
# 2) alriyadh.gov.sa -- server-rendered, no browser needed
# ---------------------------------------------------------------------------
def scrape_alriyadh() -> list[dict]:
    url = "https://www.alriyadh.gov.sa/ar/news"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # Each news block has an <h2> title followed later by a date (YYYY-MM-DD)
    # and a "التفاصيل" (read more) link pointing at the article.
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for more_link in soup.find_all("a", string="التفاصيل"):
        link = more_link["href"]
        if link.startswith("/"):
            link = "https://www.alriyadh.gov.sa" + link

        # Walk backwards through previous siblings/elements to find the
        # nearest h2 (title) and date text.
        title = None
        date_text = None
        block = more_link
        for _ in range(15):
            block = block.find_previous(["h2", "p"])
            if block is None:
                break
            text = block.get_text(strip=True)
            if title is None and block.name == "h2" and text:
                title = text
            if date_text is None and date_pattern.match(text):
                date_text = text
            if title and date_text:
                break

        if title:
            items.append(
                {
                    "title": title,
                    "summary": "",
                    "link": link,
                    "source": "أمانة منطقة الرياض",
                    "date_text": date_text,
                }
            )

    # De-duplicate (title appears both as a heading link and inside the
    # card, so the same article can otherwise show up twice).
    seen = set()
    deduped = []
    for item in items:
        if item["link"] not in seen:
            seen.add(item["link"])
            deduped.append(item)

    return deduped


# ---------------------------------------------------------------------------
# 3) jeddah.gov.sa -- AJAX-loaded content, best-effort generic extraction
# ---------------------------------------------------------------------------
def scrape_jeddah() -> list[dict]:
    url = "https://www.jeddah.gov.sa/MediaCenter/News/index.php"
    base = "https://www.jeddah.gov.sa/MediaCenter/News/"
    page_html = render_with_browser(url, wait_ms=4000)
    soup = BeautifulSoup(page_html, "html.parser")
    items = []

    # News cards live inside div#NewsTable, each card is a
    # div.CustomCardAllAuto containing an h3 (title), p (summary),
    # a date span, and a "المزيد" (read more) link.
    news_table = soup.find(id="NewsTable")
    container = news_table if news_table else soup

    for card in container.find_all("div", class_="CustomCardAllAuto"):
        h3 = card.find("h3")
        if not h3:
            continue
        title = h3.get_text(strip=True)

        p_tag = card.find("p")
        summary = p_tag.get_text(strip=True) if p_tag else ""

        link_tag = card.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        link = base + href if href and not href.startswith("http") else (href or url)

        items.append(
            {
                "title": title,
                "summary": summary,
                "link": link,
                "source": "أمانة جدة",
            }
        )

    # De-duplicate by link
    seen = set()
    deduped = []
    for item in items:
        if item["link"] not in seen:
            seen.add(item["link"])
            deduped.append(item)

    return deduped


# ---------------------------------------------------------------------------
# RSS building
# ---------------------------------------------------------------------------
def build_rss(all_items: list[dict]) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S %z"
    )

    entries = ""
    for item in all_items:
        description = f"[{item['source']}] {item.get('summary', '')}".strip()
        entries += f"""
    <item>
      <title>{html.escape(item['title'])}</title>
      <link>{html.escape(item['link'])}</link>
      <description>{html.escape(description)}</description>
      <guid>{html.escape(item['link'])}</guid>
      <pubDate>{now}</pubDate>
    </item>"""

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>أخبار الأمانات - مجمعة</title>
    <link>https://example.com</link>
    <description>خلاصة مجمعة من أمانة المنطقة الشرقية، أمانة الرياض، وأمانة جدة</description>
    <language>ar</language>{entries}
  </channel>
</rss>
"""
    OUTPUT_FILE.write_text(rss, encoding="utf-8")
    print(f"Wrote {len(all_items)} total items to {OUTPUT_FILE}")


def main():
    all_items = []

    print("Scraping eamana.gov.sa ...")
    try:
        eamana_items = scrape_eamana()
        print(f"  -> {len(eamana_items)} items")
        all_items.extend(eamana_items)
    except Exception as e:
        print(f"  !! eamana failed: {e}")

    print("Scraping alriyadh.gov.sa ...")
    try:
        alriyadh_items = scrape_alriyadh()
        print(f"  -> {len(alriyadh_items)} items")
        all_items.extend(alriyadh_items)
    except Exception as e:
        print(f"  !! alriyadh failed: {e}")

    print("Scraping jeddah.gov.sa ...")
    try:
        jeddah_items = scrape_jeddah()
        print(f"  -> {len(jeddah_items)} items")
        all_items.extend(jeddah_items)
    except Exception as e:
        print(f"  !! jeddah failed: {e}")

    if not all_items:
        print("No items found from any site.")
        return

    print(f"Total items before filtering: {len(all_items)}")
    filtered_items = [item for item in all_items if matches_whitelist(item)]
    print(f"Total items after keyword filtering: {len(filtered_items)}")

    if not filtered_items:
        print("No items matched the keyword whitelist. Feed not updated.")
        return

    build_rss(filtered_items)


if __name__ == "__main__":
    main()
