"""V4Career six-source collector: five public feeds + Google Jobs via Apify."""
from __future__ import annotations
import argparse, json, logging, os, re, sys, time, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from html import unescape
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from collectors.normalization import normalize_job
from collectors.repository import save_jobs
from collectors.source_catalog import JOB_PORTALS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("v4career.six_portals")
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "V4CareerJobCollector/1.0", "Accept": "application/json, application/rss+xml, application/xml, */*"})

TIMEOUT = (10, 45)

def get_json_with_retry(url, *, params=None, max_attempts=4):
    """GET JSON with bounded backoff for rate limits and temporary server errors."""
    last_response = None
    for attempt in range(max_attempts):
        response = HTTP.get(url, params=params, timeout=TIMEOUT)
        last_response = response
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            if attempt == max_attempts - 1:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else min(60, 5 * (2 ** attempt))
            except (TypeError, ValueError):
                delay = min(60, 5 * (2 ** attempt))
            delay = max(1, min(delay, 90))
            LOG.warning("Temporary HTTP %s from %s; retry %s/%s in %.0fs",
                        response.status_code, response.url, attempt + 1, max_attempts - 1, delay)
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response.json()
    if last_response is not None:
        last_response.raise_for_status()
    raise RuntimeError(f"No response received from {url}")

PORTALS = {
    "google-jobs": ("Google Jobs", "https://www.google.com/search?udm=8"),
    "jobicy": ("Jobicy", "https://jobicy.com/jobs"),
    "arbeitnow": ("Arbeitnow", "https://www.arbeitnow.com/"),
    "we-work-remotely": ("We Work Remotely", "https://weworkremotely.com/"),
    "remote-ok": ("Remote OK", "https://remoteok.com/"),
    "working-nomads": ("Working Nomads", "https://www.workingnomads.com/jobs"),
}
IT_TERMS = (
    "software", "developer", "development", "engineer", "engineering", "programmer",
    "programming", "frontend", "front-end", "backend", "back-end", "fullstack",
    "full-stack", "web developer", "mobile developer", "react", "angular", "vue",
    "node.js", "python", "java", "javascript", "typescript", "golang", "ruby",
    "php", ".net", "dotnet", "c++", "c#", "devops", "cloud", "aws", "azure", "gcp",
    "cybersecurity", "security engineer", "soc analyst", "data engineer",
    "data scientist", "data analyst", "machine learning", "artificial intelligence",
    "ai engineer", "ml engineer", "qa engineer", "automation tester", "software tester",
    "quality assurance", "sdet", "database", "sql", "dba", "system administrator",
    "network engineer", "site reliability", "sre", "platform engineer", "it support",
    "technical support", "solutions architect", "systems engineer", "embedded",
    "robotics", "blockchain", "ui developer", "ux engineer", "technical lead",
)
RESTRICTED = (
    "us only", "usa only", "united states only", "must be based in the us",
    "must reside in the us", "u.s. only", "canada only", "uk only",
    "united kingdom only", "europe only", "eu only", "australia only",
    "new zealand only", "germany only", "france only",
)

def txt(v):
    if v is None: return ""
    if isinstance(v, dict):
        for k in ("name", "label", "title", "raw", "value", "location"):
            if v.get(k) not in (None, ""): return txt(v[k])
        return ", ".join(txt(x) for x in v.values() if x not in (None, ""))
    if isinstance(v, (list, tuple, set)): return ", ".join(x for x in (txt(i) for i in v) if x)
    return str(v).strip()

def html_text(v):
    raw = txt(v)
    return BeautifulSoup(unescape(raw), "html.parser").get_text(" ", strip=True) or None if raw else None

def is_it(title, category=None, tags=None):
    s = " ".join((txt(title), txt(category), txt(tags))).lower()
    return any(term in s for term in IT_TERMS)

def eligible(location, remote=False, context=None):
    s = " ".join((txt(location), txt(context))).lower()
    if any(x in s for x in RESTRICTED): return False
    if "india" in s or re.search(r"\b(apac|asia pacific)\b", s): return True
    if any(x in s for x in ("worldwide", "anywhere", "global", "work from anywhere", "any location")): return True
    if remote and (not txt(location) or txt(location).lower() == "remote"): return True
    if re.search(r"\bremote\b", txt(location).lower()): return True
    return False

def unix_date(v):
    try: return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError): return None

def base_url(name):
    for p in JOB_PORTALS:
        if p["name"].strip().casefold() == name.casefold(): return p["base_url"]
    return next(v[1] for v in PORTALS.values() if v[0] == name)

def store(name, raw_jobs, cap):
    normalized, seen, invalid = [], set(), 0
    for raw in raw_jobs:
        if len(normalized) >= cap: break
        try:
            job = normalize_job(raw)
            if job["url_hash"] in seen: continue
            seen.add(job["url_hash"]); normalized.append(job)
        except (ValueError, TypeError, AttributeError):
            invalid += 1
    result = save_jobs(name, base_url(name), normalized)
    result["invalid_records_skipped"] = invalid
    LOG.info("%s: found=%s inserted=%s updated=%s invalid=%s", name, result["found"], result["inserted"], result["updated"], invalid)
    return result

def jobicy(cap):
    out, seen = [], set()
    # Avoid the previous six-request fan-out (geo x industry), which can trigger 429.
    # Fetch at most two broad geographic feeds and filter IT roles locally.
    for geo in ("apac", "anywhere"):
        if len(out) >= cap:
            break
        params = {"count": min(100, max(20, cap - len(out))), "geo": geo}
        try:
            data = get_json_with_retry("https://jobicy.com/api/jobs", params=params)
        except requests.HTTPError as exc:
            # A region can be throttled independently; preserve results from the other region.
            LOG.warning("Jobicy %s feed unavailable after retries: %s", geo, exc)
            continue

        if not isinstance(data, dict):
            LOG.warning("Jobicy %s feed returned an unexpected response; skipping.", geo)
            continue
        if data.get("success") is False:
            LOG.warning("Jobicy API reported an error for %s: %s", geo, data.get("error"))
            continue

        for j in data.get("jobs", []):
            key = str(j.get("id") or j.get("jobSlug") or j.get("url") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            title, loc = j.get("jobTitle"), txt(j.get("jobGeo"))
            desc = html_text(j.get("jobDescription") or j.get("jobExcerpt"))
            if not is_it(title, j.get("jobIndustry"), j.get("jobType")) or not eligible(loc, True, desc):
                continue
            out.append({
                "external_id": key, "title": title, "company": j.get("companyName"),
                "location": loc or "Remote", "country": loc or None,
                "experience": j.get("jobLevel"), "salary_min": j.get("salaryMin"),
                "salary_max": j.get("salaryMax"), "salary_currency": j.get("salaryCurrency"),
                "salary_period": j.get("salaryPeriod"), "skills": j.get("jobIndustry") or [],
                "description": desc, "job_url": j.get("url"), "posted_at": j.get("pubDate"),
                "status": "active", "work_mode": "Remote",
                "employment_type": txt(j.get("jobType")) or None,
                "company_logo": j.get("companyLogo"), "posted_via": "Jobicy",
                "raw_metadata": {"jobicy": j},
            })
            if len(out) >= cap:
                break
        # Avoid cursor pagination on every run; keep API request volume low.
        time.sleep(2)
    return out


def arbeitnow(cap, pages):
    out, seen = [], set()
    for page in range(1, pages+1):
        if len(out) >= cap: break
        r = HTTP.get("https://www.arbeitnow.com/api/job-board-api", params={"page":page}, timeout=TIMEOUT); r.raise_for_status()
        data = r.json()
        for j in data.get("data", []):
            key = str(j.get("slug") or j.get("url") or "")
            if not key or key in seen: continue
            seen.add(key)
            title, loc = j.get("title"), j.get("location") or ""
            desc, remote = html_text(j.get("description")), bool(j.get("remote"))
            if not is_it(title, j.get("category"), j.get("tags")) or not eligible(loc, remote, desc): continue
            out.append({"external_id":key,"title":title,"company":j.get("company_name"),"location":loc or ("Remote" if remote else None),
                "country":loc or None,"skills":j.get("tags") or [],"description":desc,"job_url":j.get("url"),
                "posted_at":unix_date(j.get("created_at")),"status":"active","work_mode":"Remote" if remote else None,
                "employment_type":txt(j.get("job_types")) or None,"posted_via":"Arbeitnow","raw_metadata":{"arbeitnow":j}})
            if len(out) >= cap: break
        if not (data.get("links") or {}).get("next"): break
        time.sleep(.25)
    return out

def remote_ok(cap):
    r = HTTP.get("https://remoteok.com/api", timeout=TIMEOUT); r.raise_for_status()
    out, seen = [], set()
    for j in r.json():
        if not isinstance(j, dict) or not (j.get("position") or j.get("title")): continue
        title, loc = j.get("position") or j.get("title"), j.get("location") or ""
        tags, desc = j.get("tags") or [], html_text(j.get("description"))
        if not is_it(title, j.get("category"), tags) or not eligible(loc, True, " ".join((desc or "", txt(tags)))): continue
        url = j.get("url") or j.get("apply_url")
        key = str(j.get("id") or url or "")
        if not url or not key or key in seen: continue
        seen.add(key)
        out.append({"external_id":key,"title":title,"company":j.get("company"),"location":loc or "Remote",
            "country":loc or None,"salary_min":j.get("salary_min"),"salary_max":j.get("salary_max"),
            "salary_currency":j.get("salary_currency") or "USD","salary_period":j.get("salary_period") or "year",
            "skills":tags,"description":desc,"job_url":url,"posted_at":j.get("date") or j.get("created_at"),
            "status":"active","work_mode":"Remote","employment_type":j.get("job_type"),
            "company_logo":j.get("company_logo"),"posted_via":"Remote OK","raw_metadata":{"remote_ok":j}})
        if len(out) >= cap: break
    return out

def weworkremotely(cap):
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    out, seen = [], set()
    for feed in feeds:
        r = HTTP.get(feed, timeout=TIMEOUT); r.raise_for_status()
        root = ET.fromstring(r.content)
        entries = root.findall(".//item")
        for e in entries:
            title = e.findtext("title", default="").strip()
            link = e.findtext("link", default="").strip()
            desc = e.findtext("description", default="")
            pub = e.findtext("pubDate", default="")
            cats = " ".join(x.text or "" for x in e.findall("category"))
            context = " ".join((title, desc, cats))
            if not title or not link or link in seen: continue
            if not is_it(title, cats, desc) or not eligible("", True, context): continue
            seen.add(link)
            out.append({"external_id":link,"title":title,"company":title.split(":",1)[0].strip() if ":" in title else None,
                "location":"India / Worldwide remote eligibility","country":"India / Worldwide","skills":[cats] if cats else [],
                "description":html_text(desc),"job_url":link,"posted_at":pub,"status":"active","work_mode":"Remote",
                "posted_via":"We Work Remotely","raw_metadata":{"feed_url":feed,"rss_description":desc}})
            if len(out) >= cap: return out
    return out

def working_nomads(cap):
    r = HTTP.get("https://www.workingnomads.com/api/exposed_jobs/", timeout=TIMEOUT); r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else (data.get("jobs") or data.get("data") or data.get("results") or [])
    out, seen = [], set()
    for j in rows:
        if not isinstance(j, dict): continue
        title = j.get("title") or j.get("name")
        category, tags = j.get("category_name") or j.get("category"), j.get("tags") or j.get("skills") or []
        loc = j.get("location") or j.get("locations") or j.get("location_name") or ""
        desc = html_text(j.get("description") or j.get("description_text"))
        if not is_it(title, category, tags) or not eligible(loc, True, " ".join((desc or "",txt(tags),txt(category)))): continue
        url = j.get("url") or j.get("job_url") or j.get("link")
        if not url and j.get("slug"): url = "https://www.workingnomads.com/jobs/" + str(j["slug"]).lstrip("/")
        key = str(j.get("id") or j.get("slug") or url or "")
        if not url or not key or key in seen: continue
        seen.add(key)
        out.append({"external_id":key,"title":title,"company":j.get("company_name") or j.get("company"),
            "location":txt(loc) or "Remote","country":txt(loc) or None,"experience":j.get("experience_level") or j.get("seniority"),
            "skills":tags,"description":desc,"job_url":url,"posted_at":j.get("pub_date") or j.get("posted_at") or j.get("created_at"),
            "status":"active","work_mode":"Remote","employment_type":j.get("job_type") or j.get("employment_type"),
            "salary_min":j.get("salary_min"),"salary_max":j.get("salary_max"),
            "salary_currency":j.get("salary_currency") or "USD","salary_period":j.get("salary_period") or "year",
            "posted_via":"Working Nomads","raw_metadata":{"working_nomads":j}})
        if len(out) >= cap: break
    return out

def google_jobs(cap, token_account):
    from apify_client import ApifyClient
    if os.getenv("APIFY_ACCESS_APPROVED_GOOGLE_JOBS", "false").strip().lower() != "true":
        raise RuntimeError(
            "Google Jobs is a paid Apify Actor. Review pricing, then set "
            "APIFY_ACCESS_APPROVED_GOOGLE_JOBS=true in .env to enable it."
        )
    token = os.getenv(f"APIFY_API_TOKEN_{token_account}", "").strip() or os.getenv("APIFY_API_TOKEN", "").strip()
    if not token: raise RuntimeError(f"Google Jobs needs {f'APIFY_API_TOKEN_{token_account}'} in .env.")
    actor = os.getenv("APIFY_ACTOR_GOOGLE_JOBS", "themineworks~google-jobs-scraper").strip()
    queries = ["software engineer","full stack developer","python developer","java developer",
               "data engineer","data analyst","devops engineer","QA automation engineer"]
    run_input = {"queries":queries,"country":"in","datePosted":"week","maxItems":min(50,max(1,int(os.getenv("GOOGLE_JOBS_MAX_ITEMS","10"))))}
    LOG.info("Google Jobs Actor=%s country=India roles=%d maxItemsPerRole=%d",actor,len(queries),run_input["maxItems"])
    client = ApifyClient(token)
    run = client.actor(actor).call(run_input=run_input)
    if not run: raise RuntimeError("Apify returned no run result.")
    status = run.get("status") if isinstance(run,dict) else getattr(run,"status",None)
    if str(status).upper() != "SUCCEEDED": raise RuntimeError(f"Google Jobs Actor status: {status}")
    dataset = (run.get("defaultDatasetId") or run.get("default_dataset_id")) if isinstance(run,dict) else (getattr(run,"defaultDatasetId",None) or getattr(run,"default_dataset_id",None))
    if not dataset: raise RuntimeError("Google Jobs Actor returned no dataset ID.")
    out = []
    for j in client.dataset(dataset).iterate_items():
        if not isinstance(j,dict) or j.get("_type"): continue
        title, tags = j.get("title"), j.get("tags") or []
        if not is_it(title,None,tags): continue
        url = j.get("apply_url") or j.get("google_job_url")
        options = j.get("apply_options") or []
        if not url and options and isinstance(options[0],dict): url = options[0].get("url")
        if not url: continue
        out.append({"external_id":j.get("job_id"),"title":title,"company":j.get("company"),
            "location":j.get("location") or j.get("search_location") or "India","country":"India",
            "salary_min":j.get("salary_min"),"salary_max":j.get("salary_max"),
            "salary_currency":j.get("salary_currency"),"salary_period":j.get("salary_period"),
            "skills":tags or j.get("qualifications") or [],"description":j.get("description"),
            "job_url":url,"posted_at":j.get("posted_at"),"status":"active",
            "work_mode":"Remote" if j.get("is_remote") else None,"employment_type":j.get("employment_type"),
            "company_logo":j.get("company_logo_url"),"posted_via":j.get("source") or "Google Jobs",
            "apply_options":options,"raw_metadata":{"google_jobs":j}})
        if len(out) >= cap*len(queries): break
    return out

COLLECTORS = {
    "jobicy": lambda cap: jobicy(cap),
    "arbeitnow": lambda cap: arbeitnow(cap, max(1,min(20,(cap+19)//20))),
    "we-work-remotely": lambda cap: weworkremotely(cap),
    "remote-ok": lambda cap: remote_ok(cap),
    "working-nomads": lambda cap: working_nomads(cap),
}

def main():
    parser = argparse.ArgumentParser(description="Scrape the six additional V4Career sources.")
    parser.add_argument("--source", choices=["all",*PORTALS.keys()], default="all")
    parser.add_argument("--max-results", type=int, default=100, help="Maximum stored jobs per source; Google max per role.")
    parser.add_argument("--include-google", action="store_true", help="Enable the paid Google Jobs Apify Actor.")
    parser.add_argument("--token-account", choices=["COLLECTOR1","COLLECTOR2","COLLECTOR3"], default="COLLECTOR1")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if not 1 <= args.max_results <= 500: parser.error("--max-results must be 1..500")
    selected = list(COLLECTORS) if args.source == "all" else [args.source]
    if args.source == "all" and args.include_google: selected.insert(0,"google-jobs")
    if args.source == "google-jobs" and not args.include_google:
        parser.error("Google Jobs is a paid Apify Actor; add --include-google after reviewing pricing.")
    results, failures = [], []
    for i, source in enumerate(selected):
        try:
            LOG.info("Starting %s (%d/%d)",source,i+1,len(selected))
            if source == "google-jobs":
                raw = google_jobs(args.max_results,args.token_account)
                result = store("Google Jobs",raw,args.max_results*8)
            else:
                raw = COLLECTORS[source](args.max_results)
                result = store(PORTALS[source][0],raw,args.max_results)
            results.append(result)
        except Exception as exc:
            LOG.exception("%s failed",source); failures.append({"source":source,"error":str(exc)})
        if i < len(selected)-1 and args.delay > 0: time.sleep(args.delay)
    print(json.dumps({"selected_sources":selected,"succeeded":len(results),"failed":len(failures),"results":results,"failures":failures},indent=2,ensure_ascii=False))
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
