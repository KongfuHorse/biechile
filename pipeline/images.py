"""Product photos for EU RASFF records and Singapore SFA recalls.

RASFF Window has no photos, but some measures link to a public warning page of a national
authority or a retailer. We open each linked page once, collect the larger images, ask Claude
which ones show the product, and store them (as small WebP files) in the Supabase Storage
bucket "rasff". Nothing is shown on the site until a person approves it in the admin page.
"""
import base64
import hashlib
import html
import io
import json
import re
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

from . import db, mt

BUCKET = "rasff"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36", "Accept-Language": "en,*;q=0.5"}
SKIP_IMG = re.compile(r"logo|icon|sprite|favicon|flag|banner|header|footer|avatar|social|facebook|twitter|"
                      r"linkedin|youtube|instagram|tiktok|pinterest|whatsapp|placeholder|loading|blank|pixel|"
                      r"\.svg(\?|$)|\.gif(\?|$)|captcha|cookie|badge|payment|newsletter", re.I)
MAX_CAND = 6


def measure_urls(rec):
    out = []
    for m in (((rec.get("raw") or {}).get("detail") or {}).get("product") or {}).get("measures") or []:
        for u in re.split(r"[\s;]+", (m or {}).get("url") or ""):
            u = u.strip()
            if u.startswith("http") and u not in out:
                out.append(u)
    return out


def _abs(base, u):
    u = html.unescape(u.strip())
    if not u or u.startswith("data:"):
        return ""
    return urljoin(base, u)


def candidates(page_url, text):
    """Image URLs from a page, best guesses first."""
    found = []
    for pat in (r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)'):
        found += re.findall(pat, text, re.I)
    body = re.sub(r"<(header|footer|nav)\b.*?</\1>", " ", text, flags=re.S | re.I)
    for tag in re.findall(r"<img\b[^>]*>", body, re.I):
        srcset = re.search(r'(?:data-)?srcset=["\']([^"\']+)', tag)
        if srcset:  # take the largest entry
            parts = [p.strip().split(" ")[0] for p in srcset.group(1).split(",") if p.strip()]
            if parts:
                found.append(parts[-1])
        for attr in ("data-src", "data-lazy-src", "data-original", "src"):
            m = re.search(attr + r'=["\']([^"\']+)', tag)
            if m:
                found.append(m.group(1))
                break
    # images loaded by script (Adobe AEM "cmp-image", used by several government sites): the original file is
    # in data-asset, and data-cmp-src is a template with {.width}
    for tag in re.findall(r'<div\b[^>]*data-cmp-src=[^>]*>', body, re.I):
        asset = re.search(r'data-asset=["\']([^"\']+)', tag)
        if asset and re.search(r"\.(jpe?g|png|webp)$", asset.group(1), re.I):
            found.append(asset.group(1))
        src = re.search(r'data-cmp-src=["\']([^"\']+)', tag)
        if src:
            widths = re.search(r'data-cmp-widths=["\']([^"\']+)', tag)
            w = max((int(x) for x in re.findall(r"\d+", widths.group(1))), default=0) if widths else 0
            found.append(src.group(1).replace("{.width}", f".{w}" if w else ""))
    found += re.findall(r'<a[^>]+href=["\']([^"\']+\.(?:jpe?g|png|webp))(?:\?[^"\']*)?["\']', body, re.I)
    out = []
    for u in found:
        a = _abs(page_url, u)
        if a and not SKIP_IMG.search(a) and a not in out:
            out.append(a)
    return out[:15]


def fetch_image(url):
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    if len(r.content) > 12_000_000:
        return None
    im = Image.open(io.BytesIO(r.content))
    im.load()
    w, h = im.size
    if min(w, h) < 180 or max(w, h) / max(1, min(w, h)) > 3.2:
        return None
    im = im.convert("RGB")
    im.thumbnail((900, 900))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=78, method=5)
    small = im.copy()
    small.thumbnail((512, 512))
    sbuf = io.BytesIO()
    small.save(sbuf, "JPEG", quality=80)
    g = im.convert("L").resize((8, 8))
    px = list(g.getdata())
    avg = sum(px) / 64
    ahash = "".join("1" if p > avg else "0" for p in px)  # same picture at another size gives the same hash
    return {"webp": buf.getvalue(), "jpeg_small": sbuf.getvalue(), "w": w, "h": h,
            "hash": hashlib.sha1(ahash.encode()).hexdigest()[:16]}


def ai_check(subject, product, imgs):
    """Ask Claude which images show the product. Returns list of (ok, note)."""
    if not mt.available() or not imgs:
        return [(None, "")] * len(imgs)
    content = [{"type": "text", "text":
                "These images come from a public product warning page. The warning is about:\n"
                f"Subject: {subject}\nProduct: {product}\n\n"
                "For each image (numbered from 0 in the order given), decide whether it is a photo of this "
                "specific product or its packaging or label. Logos, website banners, stock photos, people, "
                "maps, icons, and photos of other products are not. Return only a JSON array: "
                '[{"i": 0, "ok": true, "note": "short reason in Chinese"}].'}]
    for i, im in enumerate(imgs):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.b64encode(im["jpeg_small"]).decode()}})
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": mt.API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": mt.MODEL, "max_tokens": 1500, "messages": [{"role": "user", "content": content}]},
                      timeout=120)
    r.raise_for_status()
    text = "".join(c.get("text", "") for c in r.json().get("content", []))
    m = re.search(r"\[.*\]", text, re.S)
    res = [(None, "")] * len(imgs)
    if m:
        try:
            for d in json.loads(m.group(0)):
                if isinstance(d, dict) and isinstance(d.get("i"), int) and 0 <= d["i"] < len(imgs):
                    res[d["i"]] = (bool(d.get("ok")), str(d.get("note") or "")[:200])
        except ValueError:
            pass
    return res


def upload(path, data):
    r = requests.post(f"{db.URL}/storage/v1/object/{BUCKET}/{path}", data=data,
                      headers={**db._h(), "Content-Type": "image/webp", "x-upsert": "true",
                               "cache-control": "max-age=31536000"}, timeout=60)
    r.raise_for_status()


def _post(table, rows, conflict):
    r = requests.post(f"{db.URL}/rest/v1/{table}?on_conflict={conflict}", json=rows,
                      headers=db._h({"Prefer": "resolution=merge-duplicates,return=minimal"}), timeout=60)
    r.raise_for_status()


def process_record(rec, page_url):
    """Collect images for one record from one page. Returns (status, n_candidates)."""
    if page_url.lower().split("?")[0].endswith(".pdf"):
        return "skipped", 0
    if rec.get("src") == "SFA":
        from . import sfa
        try:
            page_text, final_url = sfa.get(page_url), page_url
        except Exception:
            return "error", 0
    else:
        try:
            r = requests.get(page_url, headers=UA, timeout=25)
        except requests.RequestException:
            return "error", 0
        if r.status_code >= 400:
            return f"http_{r.status_code}", 0
        if "html" not in r.headers.get("content-type", "html"):
            return "skipped", 0
        r.encoding = r.encoding or "utf-8"
        page_text, final_url = r.text, r.url
    imgs, seen = [], set()
    for u in candidates(final_url, page_text):
        try:
            im = fetch_image(u)
        except Exception:
            continue
        if im and im["hash"] not in seen:
            seen.add(im["hash"])
            im["url"] = u
            imgs.append(im)
        if len(imgs) >= MAX_CAND:
            break
    if not imgs:
        return "no_images", 0
    raw = rec.get("raw") or {}
    subject = ((raw.get("summary") or {}).get("subject") or ((raw.get("article") or {}).get("title")) or "")
    checks = ai_check(subject, rec.get("product_orig") or "", imgs)
    rows = []
    for im, (ok, note) in zip(imgs, checks):
        path = f"{rec['id']}/{im['hash']}.webp"
        upload(path, im["webp"])
        rows.append({"record_id": rec["id"], "page_url": page_url, "img_url": im["url"], "path": path,
                     "width": im["w"], "height": im["h"], "bytes": len(im["webp"]), "ai_ok": ok, "ai_note": note})
    _post("record_images", rows, "record_id,img_url")
    return "ok", len(rows)


def run(limit=400):
    """Process EU records whose warning pages have not been opened yet."""
    if not db.using_supabase():
        return 0, 0
    recs = db.fetch_table("records", "id,src,url,product_orig,raw", "&src=in.(EU,SFA)&order=pub_date.desc")
    done = {(p["record_id"], p["page_url"]) for p in db.fetch_table("image_pages", "record_id,page_url",
                                                                     "&order=record_id,page_url")}
    urls = lambda r: [r["url"]] if r["src"] == "SFA" else measure_urls(r)
    todo = [(r, u) for r in recs for u in urls(r) if (r["id"], u) not in done][:limit]
    pages = found = 0
    for rec, u in todo:
        try:
            status, n = process_record(rec, u)
        except requests.HTTPError as e:
            if "/storage/" in str(e) or "/rest/" in str(e):
                raise  # our own storage or database failed: stop, do not mark pages as done
            status, n = "error", 0
        except Exception as e:  # keep going; one bad page should not stop the run
            status, n = "error", 0
            print(f"  image error {rec['id']} {u}: {type(e).__name__}: {e}"[:300], flush=True)
        _post("image_pages", [{"record_id": rec["id"], "page_url": u, "status": status, "candidates": n}],
              "record_id,page_url")
        pages += 1
        found += n
    print(f"  images: {pages} pages opened, {found} candidate images", flush=True)
    return pages, found


def approved():
    """{record_id: [storage paths]} for approved images."""
    if not db.using_supabase():
        return {}
    out = {}
    for x in db.fetch_table("record_images", "record_id,path,page_url", "&status=eq.approved&order=record_id,id"):
        out.setdefault(x["record_id"], []).append({"path": x["path"], "page": x["page_url"]})
    return out


def download_approved(target_dir):
    """Copy approved images into the site so they are served from biechile.com."""
    import os
    n = 0
    for rid, items in approved().items():
        for it in items:
            dest = os.path.join(target_dir, it["path"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            r = requests.get(f"{db.URL}/storage/v1/object/public/{BUCKET}/{it['path']}", timeout=60)
            if r.ok:
                with open(dest, "wb") as f:
                    f.write(r.content)
                n += 1
    return n


def host(u):
    return urlparse(u).netloc.replace("www.", "")
