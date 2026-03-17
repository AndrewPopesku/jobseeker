import urllib.parse
from curl_cffi import requests
from bs4 import BeautifulSoup


def search_indeed_jobs(query: str, location: str = "", num_results: int = 10) -> list[dict]:
    """
    Search for jobs on Indeed.

    Args:
        query: Job title, keywords, or company name to search for.
        location: City, state, or zip code (e.g. "New York, NY"). Leave empty for remote/all.
        num_results: Maximum number of job listings to return (default 10, max 50).

    Returns:
        A list of job dictionaries with keys: title, company, location, summary, url.
    """
    num_results = min(num_results, 50)
    params = {"q": query, "l": location}
    url = "https://www.indeed.com/jobs?" + urllib.parse.urlencode(params)

    try:
        session = requests.Session(impersonate="chrome124")
        session.get("https://www.indeed.com", timeout=15)
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return [{"error": f"Failed to fetch Indeed: {e}"}]

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []

    for card in soup.select("div.job_seen_beacon, div.tapItem")[:num_results]:
        title_el = card.select_one("h2.jobTitle span[title], h2.jobTitle a span")
        company_el = card.select_one("[data-testid='company-name'], span.companyName")
        location_el = card.select_one("[data-testid='text-location'], div.companyLocation")
        summary_el = card.select_one("div.job-snippet, ul.job-snippet")
        link_el = card.select_one("h2.jobTitle a")

        title = title_el.get_text(strip=True) if title_el else "N/A"
        company = company_el.get_text(strip=True) if company_el else "N/A"
        loc = location_el.get_text(strip=True) if location_el else "N/A"
        summary = summary_el.get_text(" ", strip=True) if summary_el else ""
        href = link_el.get("href", "") if link_el else ""
        job_url = ("https://www.indeed.com" + href) if href.startswith("/") else href

        if title != "N/A":
            jobs.append({
                "title": title,
                "company": company,
                "location": loc,
                "summary": summary,
                "url": job_url,
            })

    if not jobs:
        return [{"message": "No jobs found on Indeed. Try a different query or location."}]

    return jobs


def search_linkedin_jobs(query: str, location: str = "", num_results: int = 10) -> list[dict]:
    """
    Search for jobs on LinkedIn (public job listings, no login required).

    Args:
        query: Job title, keywords, or company name to search for.
        location: City, country, or region (e.g. "San Francisco, CA"). Leave empty for worldwide.
        num_results: Maximum number of job listings to return (default 10, max 25).

    Returns:
        A list of job dictionaries with keys: title, company, location, posted, url.
    """
    num_results = min(num_results, 25)
    params = {"keywords": query, "location": location, "count": num_results}
    url = "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(params)

    try:
        resp = requests.get(url, impersonate="chrome124", timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return [{"error": f"Failed to fetch LinkedIn: {e}"}]

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []

    for card in soup.select("div.base-card, li.jobs-search__results-list > div")[:num_results]:
        title_el = card.select_one(
            "h3.base-search-card__title, h3.job-search-card__title"
        )
        company_el = card.select_one(
            "h4.base-search-card__subtitle a, h4.base-search-card__subtitle"
        )
        location_el = card.select_one(
            "span.job-search-card__location, span.base-search-card__metadata"
        )
        posted_el = card.select_one("time")
        link_el = card.select_one("a.base-card__full-link, a[data-tracking-control-name]")

        title = title_el.get_text(strip=True) if title_el else "N/A"
        company = company_el.get_text(strip=True) if company_el else "N/A"
        loc = location_el.get_text(strip=True) if location_el else "N/A"
        posted = posted_el.get("datetime", posted_el.get_text(strip=True)) if posted_el else "N/A"
        job_url = link_el.get("href", "").split("?")[0] if link_el else "N/A"

        if title != "N/A":
            jobs.append({
                "title": title,
                "company": company,
                "location": loc,
                "posted": posted,
                "url": job_url,
            })

    if not jobs:
        return [{"message": "No jobs found or LinkedIn returned no results. Try a different query or location."}]

    return jobs


def get_job_description(url: str) -> dict:
    """
    Fetch the full job description from an Indeed or LinkedIn job posting URL.

    Args:
        url: The full URL of the job posting (from search results).

    Returns:
        A dictionary with keys: title, company, location, description, url.
    """
    is_indeed = "indeed.com" in url
    is_linkedin = "linkedin.com" in url

    if not (is_indeed or is_linkedin):
        return {"error": "URL must be from indeed.com or linkedin.com"}

    try:
        if is_indeed:
            session = requests.Session(impersonate="chrome124")
            session.get("https://www.indeed.com", timeout=15)
            resp = session.get(url, timeout=15)
        else:
            resp = requests.get(url, impersonate="chrome124", timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return {"error": f"Failed to fetch job page: {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    if is_indeed:
        title_el = soup.select_one("h1.jobsearch-JobInfoHeader-title, h1[data-testid='jobsearch-JobInfoHeader-title']")
        company_el = soup.select_one("[data-testid='inlineHeader-companyName'], div.jobsearch-CompanyInfoContainer a")
        location_el = soup.select_one("[data-testid='job-location'], div.jobsearch-JobInfoHeader-subtitle div")
        desc_el = soup.select_one("#jobDescriptionText, div.jobsearch-jobDescriptionText")
    else:
        title_el = soup.select_one("h1.top-card-layout__title, h1.job-details-jobs-unified-top-card__job-title")
        company_el = soup.select_one("a.topcard__org-name-link, span.job-details-jobs-unified-top-card__company-name a, a[class*='org-name']")
        location_el = soup.select_one("span.topcard__flavor--bullet, span.job-details-jobs-unified-top-card__bullet")
        desc_el = soup.select_one("div.description__text, div.show-more-less-html__markup")

    title = title_el.get_text(strip=True) if title_el else "N/A"
    company = company_el.get_text(strip=True) if company_el else "N/A"
    location = location_el.get_text(strip=True) if location_el else "N/A"
    description = desc_el.get_text("\n", strip=True) if desc_el else "Description not available"

    return {
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "url": url,
    }
