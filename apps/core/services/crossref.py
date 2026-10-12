import logging
import requests

logger = logging.getLogger(__name__)


class CrossRefService:
    """
    On-demand CrossRef integration for bibliographic auto-enrichment.
    Non-blocking, with strict timeouts and error fallbacks.
    """
    BASE_URL = "https://api.crossref.org/works/"

    @classmethod
    def clean_doi(cls, raw_doi: str) -> str:
        doi = raw_doi.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix):]
        return doi.strip()

    @classmethod
    def fetch_doi(cls, raw_doi: str, timeout: int = 5) -> dict:
        cleaned_doi = cls.clean_doi(raw_doi)
        if not cleaned_doi:
            return {"success": False, "error": "Invalid or empty DOI provided."}

        url = f"{cls.BASE_URL}{cleaned_doi}"
        headers = {
            "User-Agent": "PoornimaFacultyPortal/1.0 (mailto:admin@poornima.org)",
            "Accept": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 404:
                return {"success": False, "error": f"DOI '{cleaned_doi}' not found in CrossRef database."}
            if response.status_code != 200:
                return {"success": False, "error": f"CrossRef returned status {response.status_code}."}

            data = response.json().get("message", {})
            
            # Extract fields
            titles = data.get("title", [])
            title = titles[0] if titles else ""

            container_titles = data.get("container-title", [])
            journal_name = container_titles[0] if container_titles else ""

            publisher = data.get("publisher", "")
            volume = data.get("volume", "")
            issue = data.get("issue", "")
            page = data.get("page", "")

            # Publication Date
            issued = data.get("published-print") or data.get("published-online") or data.get("issued", {})
            date_parts = issued.get("date-parts", [[]])[0]
            year = str(date_parts[0]) if len(date_parts) > 0 else ""
            pub_date = "-".join(f"{p:02d}" for p in date_parts) if date_parts else ""

            # ISSN / ISBN
            issn_list = data.get("ISSN", [])
            issn = issn_list[0] if issn_list else ""

            isbn_list = data.get("ISBN", [])
            isbn = isbn_list[0] if isbn_list else ""

            # Authors
            authors_data = data.get("author", [])
            authors_list = []
            author_names = []
            for a in authors_data:
                given = a.get("given", "")
                family = a.get("family", "")
                full = f"{given} {family}".strip() or a.get("name", "")
                if full:
                    authors_list.append({"given": given, "family": family, "full_name": full})
                    author_names.append(full)

            return {
                "success": True,
                "data": {
                    "doi": cleaned_doi,
                    "title": title,
                    "journal_name": journal_name,
                    "publisher": publisher,
                    "publication_year": year,
                    "publication_date": pub_date,
                    "volume": volume,
                    "issue": issue,
                    "page_numbers": page,
                    "issn": issn,
                    "isbn": isbn,
                    "authors_text": ", ".join(author_names),
                    "authors": authors_list,
                }
            }

        except requests.Timeout:
            logger.warning(f"CrossRef lookup timed out for DOI: {cleaned_doi}")
            return {"success": False, "error": "CrossRef API request timed out (5s). Please fill details manually."}
        except Exception as e:
            logger.error(f"Error fetching DOI {cleaned_doi}: {e}", exc_info=True)
            return {"success": False, "error": f"Failed to connect to CrossRef: {str(e)}"}
