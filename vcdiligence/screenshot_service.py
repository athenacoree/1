import datetime
import requests
from vcdiligence.logging_config import logger

def capture_screenshot(url: str, db_session=None) -> str | None:
    """
    Captures a screenshot of the specified URL using the free Microlink.io API.
    Utilizes local ScreenshotCache table to cache results for 30 days.
    Never raises exceptions that block the analysis flow.
    """
    if not url:
        return None

    # Check cache if DB session is available
    if db_session:
        try:
            from vcdiligence.database import ScreenshotCache
            thirty_days_ago = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=30)
            cached = db_session.query(ScreenshotCache).filter(
                ScreenshotCache.url == url,
                ScreenshotCache.captured_at >= thirty_days_ago
            ).order_by(ScreenshotCache.captured_at.desc()).first()

            if cached:
                logger.info(f"Screenshot cache hit for {url}: {cached.screenshot_url}")
                return cached.screenshot_url
        except Exception as e:
            logger.error(f"Error checking screenshot cache: {str(e)}")

    # Cache miss or no DB session, call Microlink API
    logger.info(f"Capturing screenshot via Microlink for {url}...")
    try:
        # Construct URL
        api_url = f"https://api.microlink.io/?url={requests.utils.quote(url)}&screenshot=true&meta=false&embed=screenshot.url"

        # We perform a GET request with an 8-second timeout
        response = requests.get(api_url, timeout=8)

        if response.status_code == 200:
            # Microlink.io embed=screenshot.url directly redirects or returns the image.
            # Wait, if we use embed=screenshot.url, the response might be the image binary itself,
            # or it might return the direct screenshot URL if we query without embed or by parsing response.
            # Let's check: if we query `https://api.microlink.io/?url={url}&screenshot=true&meta=false`,
            # it returns JSON: {"status": "success", "data": {"screenshot": {"url": "..."}}}
            # If we query with `embed=screenshot.url`, it redirects directly to the screenshot URL or returns the image binary.
            # Actually, to get the screenshot URL as a string cleanly, we can query WITHOUT embed or WITH embed but checking the final redirected URL!
            # If we query WITHOUT embed, i.e.:
            # https://api.microlink.io/?url={url}&screenshot=true&meta=false
            # It returns a JSON object where data.screenshot.url is the image URL. This is much cleaner and easier to parse!
            # Let's do that! That way we don't have to parse binary or deal with raw redirects.
            # Let's call: https://api.microlink.io/?url={url}&screenshot=true&meta=false
            # And parse the JSON to get data.screenshot.url.

            clean_api_url = f"https://api.microlink.io/?url={requests.utils.quote(url)}&screenshot=true&meta=false"
            res = requests.get(clean_api_url, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "success":
                    img_url = data.get("data", {}).get("screenshot", {}).get("url")
                    if img_url:
                        logger.info(f"Successfully captured screenshot via Microlink: {img_url}")

                        # Save to cache if DB session is available
                        if db_session:
                            try:
                                from vcdiligence.database import ScreenshotCache
                                new_cache = ScreenshotCache(
                                    url=url,
                                    screenshot_url=img_url
                                )
                                db_session.add(new_cache)
                                db_session.commit()
                                logger.info(f"Saved screenshot to cache for {url}")
                            except Exception as dberr:
                                logger.error(f"Failed to save screenshot to cache database: {str(dberr)}")
                                db_session.rollback()

                        return img_url

            # If the JSON approach failed, let's fallback to using the embed URL as a direct image source
            # i.e., "https://api.microlink.io/?url={url}&screenshot=true&meta=false&embed=screenshot.url" is itself a valid image URL!
            fallback_url = f"https://api.microlink.io/?url={requests.utils.quote(url)}&screenshot=true&meta=false&embed=screenshot.url"
            logger.info(f"Using fallback embed screenshot URL: {fallback_url}")
            return fallback_url

    except Exception as e:
        logger.error(f"Error calling Microlink screenshot API for {url}: {str(e)}")

    return None
