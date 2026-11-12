"""Collect raw internship / junior listings from job boards that allow it.

Sources (checked robots.txt, Nov 2026):
  - englishjobs.fr : English-speaking jobs in France (aggregator)
  - iagora.com     : internships abroad, with language tags
Not collected directly:
  - thelocal.fr            : robots.txt blocks Claude / AI agents
  - welcometothejungle.com : bot protection (403)
  - erasmuscareers.org     : bot protection (Cloudflare challenge)
  - linkedin.com, indeed   : terms forbid automated collection
These are found through web search instead.

Usage: python3 collect.py OUT.json
Writes a list of raw listings; filtering and role matching is done afterwards.
"""
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; personal-internship-digest/1.0)"
PAUSE = 1.5  # seconds between requests

ENGLISHJOBS = [
    "/in/lyon/internship", "/in/lyon/marketing", "/in/lyon/communication",
    "/in/lyon/brand", "/in/lyon/content", "/in/lyon/junior",
    "/jobs/marketing_internship", "/jobs/brand_internship", "/jobs/brand_strategy",
    "/jobs/market_research", "/jobs/content_strategy", "/jobs/content_internship",
    "/jobs/communication_internship", "/jobs/junior_marketing", "/jobs/marketing_assistant",
]
IAGORA_COUNTRIES = [
    "france", "netherlands", "germany", "spain", "belgium", "ireland",
    "poland", "portugal", "italy", "czech-republic", "austria", "denmark", "sweden",
]
IAGORA = [f"/work/en/internships/marketing/{c}" for c in IAGORA_COUNTRIES] + [
    "/work/en/internships/advertising/france",
    "/work/en/internships/communication/france",
]

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def guess_date(text, today):
    """'October 24' -> 2026-10-24 (previous year if that date is in the future)."""
    m = re.fullmatch(r"([A-Za-z]+) (\d{1,2})", text.strip())
    if not m or m.group(1).lower() not in MONTHS:
        low = text.strip().lower()
        if low in ("today", "just posted"):
            return today.isoformat()
        if low == "yesterday":
            return (today - dt.timedelta(days=1)).isoformat()
        m2 = re.fullmatch(r"(\d+) days? ago", low)
        if m2:
            return (today - dt.timedelta(days=int(m2.group(1)))).isoformat()
        return None
    d = dt.date(today.year, MONTHS[m.group(1).lower()], int(m.group(2)))
    if d > today:
        d = d.replace(year=d.year - 1)
    return d.isoformat()


def parse_englishjobs(page, path, today):
    out = []
    for item in re.split(r'class="job js-job', page)[1:]:
        item = item.split("<!-- end result -->")[0]
        href = re.search(r'<a href="([^"]+)"', item)
        title = re.search(r'itemprop="title">(.*?)</h3>', item, re.S)
        lis = [clean(x) for x in re.findall(r'<li class="flex text-sm[^"]*">(.*?)</li>', item, re.S)]
        info = [x for x in lis if x and not re.search(r"remote work|student|no experience|full.time|part.time|internship|contract", x, re.I)]
        tags = [clean(x) for x in re.findall(r'<span class="text-xs">(.*?)</span>', item, re.S)]
        snippet = re.search(r'class="mr-4 flex-1[^"]*">(.*?)</div>', item, re.S)
        date_raw = next((x for x in lis if guess_date(x, today)), "")
        rest = [x for x in info if x != date_raw]
        out.append({
            "source": "englishjobs.fr",
            "query": path,
            "title": clean(title.group(1)) if title else "",
            "company": rest[0] if rest else "",
            "location": rest[1] if len(rest) > 1 else "",
            "posted_raw": date_raw,
            "postedAt": guess_date(date_raw, today) if date_raw else None,
            "tags": tags,
            "snippet": clean(snippet.group(1))[:900] if snippet else "",
            "url": "https://englishjobs.fr" + html.unescape(href.group(1)) if href else "",
        })
    return out


def parse_iagora(page, path, today):
    out = []
    for m in re.finditer(r'<div class="listings-row[^"]*" id="listings-row-(\d+)">(.*?)<div class="listings-sep">', page, re.S):
        rid, item = m.group(1), m.group(2)
        a = re.search(r'<a href="(https://www\.iagora\.com/work/en/offer/[^"]+)">(.*?)</a>', item, re.S)
        line2 = re.search(r'<div class="line2">(.*?)</div>\s*</div>', item, re.S)
        tags = re.search(r'<span class="tags">(.*?)</span>', item, re.S)
        snip = re.search(r'<div class="snip[^"]*"[^>]*>(.*?)</div>', item, re.S)
        flag = re.search(r'flag_([a-z]{2})\.gif', item)
        l2 = clean(line2.group(1)) if line2 else ""
        parts = [p.strip() for p in l2.split("|")]
        out.append({
            "source": "iagora",
            "query": path,
            "id": rid,
            "title": clean(a.group(2)) if a else "",
            "company": parts[0] if parts else "",
            "location": parts[1] if len(parts) > 1 else "",
            "country_code": flag.group(1) if flag else "",
            "posted_raw": "",
            "postedAt": None,
            "tags": [t.strip() for t in clean(tags.group(1)).split(",")] if tags else [],
            "snippet": clean(snip.group(1)).strip("“”")[:900] if snip else "",
            "url": a.group(1) if a else "",
        })
    return out


def main(out_path):
    today = dt.date.today()
    rows, errors = [], []
    jobs = [("https://englishjobs.fr" + p, p, parse_englishjobs) for p in ENGLISHJOBS]
    jobs += [("https://www.iagora.com" + p, p, parse_iagora) for p in IAGORA]
    for url, path, parser in jobs:
        try:
            rows += parser(get(url), path, today)
        except Exception as e:  # keep going on one bad page
            errors.append(f"{url}: {e}")
        time.sleep(PAUSE)
    # de-duplicate by url, then by title+company
    seen, uniq = set(), []
    for r in rows:
        key = r["url"] or (r["title"].lower(), r["company"].lower())
        k2 = (r["title"].lower(), r["company"].lower())
        if key in seen or k2 in seen:
            continue
        seen.update([key, k2])
        uniq.append(r)
    json.dump({"collectedAt": today.isoformat(), "count": len(uniq), "errors": errors, "jobs": uniq},
              open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"{len(uniq)} unique listings, {len(errors)} errors")
    for e in errors:
        print("ERR", e)


if __name__ == "__main__":
    main(sys.argv[1])
