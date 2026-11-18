import json
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://smsfast.io"


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ru"}
    )
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")


def rows(html: str) -> list[list[str]]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
        if clean and any(clean):
            out.append(clean[:3])
    return out


def scrape_countries() -> list[dict]:
    seen: dict[int, str] = {}
    for page in range(1, 26):
        html = fetch(f"{BASE}/doc/countries?page={page}")
        got = rows(html)
        if not got:
            break
        added = 0
        for cells in got:
            if len(cells) < 2 or not cells[0].isdigit():
                continue
            cid = int(cells[0])
            if cid not in seen:
                seen[cid] = cells[1]
                added += 1
        print(f"page {page}: {len(got)} rows, +{added}, total {len(seen)}")
        if added == 0:
            break
    return [{"id": cid, "name": name} for cid, name in sorted(seen.items())]


def scrape_services(queries: list[str]) -> list[dict]:
    found: dict[str, str] = {}
    for query in queries:
        url = f"{BASE}/doc/services?search={urllib.parse.quote(query)}"
        html = fetch(url)
        for cells in rows(html):
            if len(cells) >= 2 and cells[0].isdigit():
                found[cells[1]] = cells[0]
        print(f"query {query!r}: {rows(html)[:6]}")
    return [{"name": n, "id": int(i)} for n, i in found.items()]


if __name__ == "__main__":
    countries = scrape_countries()
    print("countries total", len(countries))
    services = scrape_services(
        ["Telegram", "WhatsApp", "Google", "TikTok", "Discord", "Amazon", "Apple", "Другой"]
    )
    print("services", services)
    with open("scripts/provider_data.json", "w", encoding="utf-8") as fh:
        json.dump({"countries": countries, "services": services}, fh, ensure_ascii=False, indent=2)
    print("saved scripts/provider_data.json")
