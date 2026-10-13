"""Shared search metadata for desktop and mobile HTML."""

from fastapi import Request

PUBLIC_SITE_ORIGIN = "https://mapilog.xyz"


def is_presentation_parameter(key: str) -> bool:
    return key == "layout" or key.startswith("utm_") or key in {
        "gclid", "fbclid", "msclkid",
    }


def search_metadata(request: Request, *, private: bool = False) -> dict[str, str]:
    # Tracking and layout variants describe the same public content. Unknown
    # parameters remain excluded, along with search, filters and detail tabs.
    filtered = any(not is_presentation_parameter(key) for key in request.query_params)
    return {
        "robots": "noindex,follow" if private or filtered else "index,follow",
        "canonical": PUBLIC_SITE_ORIGIN + request.url.path,
    }
