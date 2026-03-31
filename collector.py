"""
Beginner-friendly collector script.

Goal:
1) Read source definitions from sources.json
2) Pull recent article links from each source
3) Group items by category
4) Render clean HTML using templates/weekly_update.html
5) Save the final page to output/index.html
"""

import json
import re
from collections import Counter
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from jinja2 import Environment, FileSystemLoader

# Base project folder (the folder where this collector.py file lives)
BASE_DIR = Path(__file__).resolve().parent

# Key file/folder paths used by this script
SOURCES_FILE = BASE_DIR / "sources.json"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_FILE = BASE_DIR / "output" / "index.html"
PAGE_TITLE = "Link Collector"
PAGE_INTRO = (
    "A weekly curated update of AML, anti-fraud, anti-financial crime, "
    "sanctions, and compliance developments relevant to practitioners."
)
REGION_ORDER = ["US", "International"]
REQUEST_TIMEOUT = 20
DEFAULT_ITEMS_PER_SOURCE = 2
MAX_TOTAL_ITEMS = 18
MAX_ITEMS_PER_REGION = {"US": 8, "International": 10}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}
INVALID_LINK_PATTERNS = (
    "/tag/",
    "/tags/",
    "/category/",
    "/categories/",
    "/topic/",
    "/topics/",
    "/author/",
    "/about",
    "/contact",
    "/careers",
    "/privacy",
    "/terms",
    "/search",
    "/subscribe",
    "/newsletter",
    "/login",
    "/signin",
    "/register",
    "/account",
)
US_HOST_PATTERNS = (
    "fincen.gov",
    "treasury.gov",
    "justice.gov",
    "occ.treas.gov",
    "federalreserve.gov",
    "sec.gov",
    "irs.gov",
)
GENERIC_TITLES = {
    "press releases",
    "news releases",
    "publications",
    "press release",
    "view press release",
    "see all updates",
    "see all",
    "skip to main content",
    "news & media",
    "speaking engagements",
    "read 2025 press release",
}
MONTH_NAME_PATTERN = (
    r"(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|"
    r"Sep|Sept|September|Oct|October|Nov|November|Dec|December)"
)


def load_sources():
    """
    Read sources.json and return the "sources" list.
    """
    with SOURCES_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    sources = data.get("sources", [])
    if not sources:
        raise ValueError("No sources found in sources.json")
    return sources


def get_source_region(source):
    """
    Split sources into US vs International for report grouping.
    """
    explicit_region = source.get("region")
    if explicit_region:
        return explicit_region

    hostname = urlparse(source.get("url", "")).netloc.lower()
    if any(pattern in hostname for pattern in US_HOST_PATTERNS):
        return "US"
    return "International"


def get_issue_date():
    """
    Return both machine-readable and display-friendly versions of today's date.
    """
    now = datetime.now()
    return {
        "iso": now.strftime("%Y-%m-%d"),
        "display": now.strftime("%B %d, %Y"),
        "generated_at": now.strftime("%B %d, %Y at %I:%M %p"),
    }


def clean_text(value):
    """
    Collapse whitespace so scraped text stays readable in the report.
    """
    return re.sub(r"\s+", " ", value or "").strip()


def shorten_text(value, limit):
    """
    Keep titles and summaries compact for the exported HTML widget.
    """
    cleaned = clean_text(value)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def safe_request(session, url):
    """
    Fetch a URL and return a response object or None if the request fails.
    """
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"  Warning: could not fetch {url} ({exc})")
        return None


def discover_feed_url(base_url, soup):
    """
    Look for an RSS/Atom feed advertised in the HTML page.
    """
    for link in soup.select("link[rel='alternate'][type]"):
        feed_type = (link.get("type") or "").lower()
        if "rss" in feed_type or "atom" in feed_type or "xml" in feed_type:
            href = link.get("href")
            if href:
                return urljoin(base_url, href)
    return None


def parse_feed_entries(feed_url, source, issue_date, limit):
    """
    Build items from an RSS or Atom feed.
    """
    parsed_feed = feedparser.parse(feed_url)
    items = []

    for entry in parsed_feed.entries[:limit]:
        link = entry.get("link")
        title = clean_text(entry.get("title", "Untitled article"))
        summary = clean_text(
            BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ")
        )

        if not link or not title:
            continue

        published = format_entry_date(entry, issue_date["iso"])
        items.append(
            build_item(
                source=source,
                title=title,
                link=link,
                summary=summary or f"Recent article discovered from {source['name']}.",
                date=published,
                priority=20,
            )
        )

    return items


def format_entry_date(entry, fallback_date):
    """
    Convert feedparser date fields into the YYYY-MM-DD format used by the template.
    """
    for key in ("published", "updated"):
        raw_value = entry.get(key)
        if not raw_value:
            continue
        try:
            return parsedate_to_datetime(raw_value).strftime("%Y-%m-%d")
        except (TypeError, ValueError, IndexError):
            continue
    return fallback_date


def normalize_date_string(raw_value, fallback_date):
    """
    Convert scraped date text into YYYY-MM-DD when possible.
    """
    cleaned = clean_text(raw_value)
    if not cleaned:
        return fallback_date

    try:
        return date_parser.parse(cleaned, fuzzy=True, dayfirst=False).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return fallback_date


def extract_date_from_url(link):
    """
    Pull publication dates from common URL patterns.
    """
    patterns = (
        r"/(20\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/",
        r"/(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])/",
        r"/(20\d{2})/(0[1-9]|1[0-2])/",
    )

    for pattern in patterns:
        match = re.search(pattern, link)
        if not match:
            continue

        parts = match.groups()
        if len(parts) == 3:
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
        if len(parts) == 2:
            return f"{parts[0]}-{parts[1]}-01"

    return None


def extract_candidate_date_text(anchor):
    """
    Look for article date hints near the link.
    """
    date_texts = []

    parent = anchor.parent
    if parent is None:
        return date_texts

    for time_tag in parent.find_all("time", limit=2):
        date_texts.append(time_tag.get("datetime") or time_tag.get_text(" "))

    for selector in ("span", "p", "div"):
        for element in parent.find_all(selector, limit=5):
            text = clean_text(element.get_text(" "))
            if not text:
                continue

            if re.search(r"\b20\d{2}\b", text) or re.search(MONTH_NAME_PATTERN, text, re.IGNORECASE):
                date_texts.append(text)

    return date_texts


def extract_article_date(anchor, link, fallback_date):
    """
    Determine the best available date for an HTML-scraped article.
    """
    url_date = extract_date_from_url(link)
    if url_date:
        return url_date

    for candidate in extract_candidate_date_text(anchor):
        normalized = normalize_date_string(candidate, fallback_date)
        if normalized != fallback_date:
            return normalized

    return fallback_date


def is_generic_title(title):
    """
    Filter utility links that are not useful end-user article titles.
    """
    lowered = clean_text(title).lower()
    if lowered in GENERIC_TITLES:
        return True
    if lowered.startswith(("view ", "see all ", "read ", "skip to ")):
        return True
    return False


def is_candidate_link(link_url, source_url):
    """
    Filter out navigation and utility links so we keep article-like targets.
    """
    if not link_url:
        return False

    parsed_link = urlparse(link_url)
    parsed_source = urlparse(source_url)

    if parsed_link.scheme not in {"http", "https"}:
        return False

    if parsed_link.netloc and parsed_source.netloc not in parsed_link.netloc:
        return False

    normalized = link_url.lower()
    if any(pattern in normalized for pattern in INVALID_LINK_PATTERNS):
        return False

    if normalized.endswith((".jpg", ".jpeg", ".png", ".gif", ".pdf", ".svg", ".zip")):
        return False

    return True


def score_candidate_link(link_url, anchor_text, source):
    """
    Rank candidate links so article pages sort above generic navigation links.
    """
    score = 0
    lowered_url = link_url.lower()
    lowered_text = anchor_text.lower()

    keyword_groups = (
        "news",
        "blog",
        "article",
        "post",
        "press",
        "release",
        "publication",
        "update",
        "insight",
        "analysis",
        "sanctions",
        "fraud",
        "aml",
        "crime",
    )

    for keyword in keyword_groups:
        if keyword in lowered_url:
            score += 3
        if keyword in lowered_text:
            score += 2

    slash_count = lowered_url.count("/")
    if slash_count >= 4:
        score += 2

    if re.search(r"/\d{4}/\d{2}/", lowered_url):
        score += 4

    if len(anchor_text) >= 35:
        score += 2
    elif len(anchor_text) >= 18:
        score += 1

    if source.get("name", "").lower() in lowered_text:
        score -= 1

    if is_generic_title(anchor_text):
        score -= 6

    return score


def extract_link_summary(anchor):
    """
    Grab a little nearby text when available so cards show more than just the title.
    """
    pieces = []
    parent = anchor.parent

    if parent is not None:
        for element in parent.find_all(["p", "span"], limit=3):
            text = clean_text(element.get_text(" "))
            if text and text != clean_text(anchor.get_text(" ")):
                pieces.append(text)

    summary = " ".join(pieces)
    return shorten_text(summary, 140)


def parse_html_entries(response, source, issue_date, limit):
    """
    Scrape article-like links from the source landing page.
    """
    soup = BeautifulSoup(response.text, "lxml")
    feed_url = discover_feed_url(response.url, soup)
    if feed_url:
        feed_items = parse_feed_entries(feed_url, source, issue_date, limit)
        if feed_items:
            return feed_items

    candidates = []
    seen_links = set()

    for anchor in soup.find_all("a", href=True):
        title = clean_text(anchor.get_text(" "))
        if len(title) < 12:
            continue
        if is_generic_title(title):
            continue

        link = urljoin(response.url, anchor["href"])
        normalized = link.rstrip("/")
        if normalized in seen_links:
            continue

        if not is_candidate_link(link, source["url"]):
            continue

        score = score_candidate_link(link, title, source)
        if score < 3:
            continue

        seen_links.add(normalized)
        candidates.append(
            {
                "title": title,
                "link": link,
                "summary": extract_link_summary(anchor),
                "score": score,
                "date": extract_article_date(anchor, link, issue_date["iso"]),
            }
        )

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)

    items = []
    for candidate in candidates[:limit]:
        items.append(
            build_item(
                source=source,
                title=candidate["title"],
                link=candidate["link"],
                summary=(
                    candidate["summary"]
                    or f"Recent article discovered from the {source['name']} source page."
                ),
                date=candidate["date"],
                priority=candidate["score"],
            )
        )

    return items


def build_item(source, title, link, summary, date, priority=0, is_fallback=False):
    """
    Normalize one scraped article into the format the template expects.
    """
    return {
        "title": shorten_text(title, 120),
        "source": source.get("name", "Unknown Source"),
        "date": date,
        "summary": shorten_text(summary, 140),
        "link": link,
        "category": get_source_region(source),
        "topic_category": source.get("category", "Uncategorized"),
        "source_type": source.get("type", "web").replace("-", " ").title(),
        "priority": priority,
        "is_fallback": is_fallback,
    }


def build_source_fallback_item(source, issue_date, reason):
    """
    Keep the source visible even if scraping fails for that site.
    """
    return build_item(
        source=source,
        title=f"{source['name']} source page",
        link=source.get("url", "#"),
        summary="Click below to Open this Source for Current Updates",
        date=issue_date["iso"],
        priority=-100,
        is_fallback=True,
    )


def fetch_source_items(source, issue_date, session):
    """
    Pull live items from one source definition.
    """
    source_url = source.get("url")
    if not source_url:
        return [build_source_fallback_item(source, issue_date, "missing source URL")]

    response = safe_request(session, source_url)
    if response is None:
        return [build_source_fallback_item(source, issue_date, "request failed")]

    max_items = int(source.get("max_items", DEFAULT_ITEMS_PER_SOURCE))

    if source.get("type") == "rss":
        items = parse_feed_entries(source_url, source, issue_date, max_items)
    else:
        items = parse_html_entries(response, source, issue_date, max_items)

    if items:
        return items

    return [build_source_fallback_item(source, issue_date, "no article links matched")]


def build_items_from_sources(sources, issue_date):
    """
    Pull recent items from each source and combine them into one flat list.
    """
    items = []
    session = requests.Session()

    for source in sources:
        print(f"  Fetching recent items from {source.get('name', 'Unknown Source')}...")
        items.extend(fetch_source_items(source, issue_date, session))

    return limit_items_for_widget(items)


def limit_items_for_widget(items):
    """
    Keep the final HTML compact enough for the GoDaddy widget.
    """
    limited_items = []

    for region in REGION_ORDER:
        region_items = [item for item in items if item["category"] == region]
        region_items.sort(
            key=lambda item: (
                not item["is_fallback"],
                item["priority"],
                sort_date_value(item["date"]),
                item["source"],
                item["title"],
            ),
            reverse=True,
        )
        limited_items.extend(region_items[: MAX_ITEMS_PER_REGION.get(region, MAX_TOTAL_ITEMS)])

    if len(limited_items) > MAX_TOTAL_ITEMS:
        limited_items.sort(
            key=lambda item: (
                not item["is_fallback"],
                item["priority"],
                sort_date_value(item["date"]),
                item["source"],
                item["title"],
            ),
            reverse=True,
        )
        limited_items = limited_items[:MAX_TOTAL_ITEMS]

    return sorted(
        limited_items,
        key=lambda item: (
            item["category"],
            sort_date_value(item["date"]),
            item["priority"],
            item["source"],
            item["title"],
        ),
        reverse=True,
    )


def sort_date_value(date_string):
    """
    Return a sortable timestamp so newest entries appear first.
    """
    try:
        return datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError:
        return datetime.min


def group_items_by_category(items):
    """
    Group items into a dictionary like:
    {
      "Regulatory": [item1, item2],
      "News": [item3, item4]
    }
    """
    grouped = {}
    for item in items:
        category = item["category"]
        grouped.setdefault(category, []).append(item)
    return grouped


def sort_grouped_items(grouped_items):
    """
    Return grouped items as an ordered list for predictable template rendering.
    """
    ordered_sections = []
    remaining_regions = sorted(
        category for category in grouped_items if category not in REGION_ORDER
    )

    for category in REGION_ORDER + remaining_regions:
        if category in grouped_items:
            entries = sorted(
                grouped_items[category],
                key=lambda item: (
                    sort_date_value(item["date"]),
                    item["priority"],
                    item["source"],
                    item["title"],
                ),
                reverse=True,
            )
            ordered_sections.append(
                {
                    "name": category,
                    "count": len(entries),
                    "source_count": len({item["source"] for item in entries}),
                    "entries": entries,
                }
            )

    return ordered_sections


def build_category_stats(items):
    """
    Create lightweight summary stats for the report header.
    """
    counts = Counter(item["category"] for item in items)
    stats = []

    for category in REGION_ORDER:
        if counts.get(category):
            stats.append({"name": category, "count": counts[category]})

    for category in sorted(counts):
        if category not in REGION_ORDER:
            stats.append({"name": category, "count": counts[category]})

    return stats


def render_and_save_html(grouped_items, issue_date, items):
    """
    Render the Jinja template and save final HTML to output/index.html.
    """
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("weekly_update.html")
    ordered_sections = sort_grouped_items(grouped_items)

    html = template.render(
        title=PAGE_TITLE,
        intro=PAGE_INTRO,
        issue_date=issue_date["display"],
        generated_at=issue_date["generated_at"],
        total_items=len(items),
        total_sources=len({item["source"] for item in items}),
        category_stats=build_category_stats(items),
        grouped_sections=ordered_sections,
    )
    html = compact_html_output(html)

    # Create output folder if it does not exist
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write the final HTML file
    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        file.write(html)


def compact_html_output(html):
    """
    Remove indentation and blank lines so the pasted widget HTML is much shorter.
    """
    return "".join(line.strip() for line in html.splitlines() if line.strip())


def main():
    """
    Run the full pipeline from JSON -> items -> grouped items -> HTML output.
    """
    try:
        print("Step 1/4: Loading sources...")
        sources = load_sources()
        issue_date = get_issue_date()

        print("Step 2/4: Building items...")
        items = build_items_from_sources(sources, issue_date)

        print("Step 3/4: Grouping by category...")
        grouped_items = group_items_by_category(items)

        print("Step 4/4: Rendering HTML...")
        render_and_save_html(grouped_items, issue_date, items)

        print(f"Done. Weekly update page created: {OUTPUT_FILE}")
    except FileNotFoundError as exc:
        print(f"File not found: {exc}")
    except json.JSONDecodeError as exc:
        print(f"JSON error in sources.json: {exc}")
    except ValueError as exc:
        print(f"Data error: {exc}")


if __name__ == "__main__":
    main()
