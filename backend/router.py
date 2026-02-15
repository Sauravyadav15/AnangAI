import httpx
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from functools import lru_cache

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
# Get API key from environment variable, fallback to hardcoded (for development only)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Define folder paths
FOOD_DIR = BASE_DIR / "Food"
PLACES_DIR = BASE_DIR / "Places"
EVENTS_DIR = BASE_DIR / "Events"

# Keyword mapping to file types for smart search
FOOD_KEYWORD_MAP = {
    "restaurant": ["restaurants.txt"],
    "restaurants": ["restaurants.txt"],
    "dining": ["restaurants.txt"],
    "dine": ["restaurants.txt"],
    "eat": ["restaurants.txt"],
    "food": ["restaurants.txt", "bakeries.txt", "cafés_coffee_shops.txt", "breweries_pubs.txt"],
    "bakery": ["bakeries.txt"],
    "bakeries": ["bakeries.txt"],
    "bake": ["bakeries.txt"],
    "bread": ["bakeries.txt"],
    "pastry": ["bakeries.txt"],
    "cafe": ["cafés_coffee_shops.txt"],
    "café": ["cafés_coffee_shops.txt"],
    "coffee": ["cafés_coffee_shops.txt"],
    "espresso": ["cafés_coffee_shops.txt"],
    "latte": ["cafés_coffee_shops.txt"],
    "pub": ["breweries_pubs.txt"],
    "pubs": ["breweries_pubs.txt"],
    "brewery": ["breweries_pubs.txt"],
    "breweries": ["breweries_pubs.txt"],
    "beer": ["breweries_pubs.txt"],
    "brew": ["breweries_pubs.txt"],
    "ice cream": ["ice_cream_gelato.txt"],
    "gelato": ["ice_cream_gelato.txt"],
    "frozen": ["ice_cream_gelato.txt"],
    "dessert": ["ice_cream_gelato.txt", "bakeries.txt"],
    # Shops / local stores (shops.txt)
    "shop": ["shops.txt"],
    "shops": ["shops.txt"],
    "store": ["shops.txt"],
    "stores": ["shops.txt"],
    "clothing": ["shops.txt"],
    "clothes": ["shops.txt"],
    "fashion": ["shops.txt"],
    "boutique": ["shops.txt"],
    "thrift": ["shops.txt"],
    "footwear": ["shops.txt"],
    "shoe": ["shops.txt"],
    "shoes": ["shops.txt"],
    "bridal": ["shops.txt"],
    "gift": ["shops.txt"],
    "consignment": ["shops.txt"],
    "vintage": ["shops.txt"],
    "secondhand": ["shops.txt"],
    "second-hand": ["shops.txt"],
    "used": ["shops.txt"],
    "pre-loved": ["shops.txt"],
    "sustainable": ["shops.txt"],  # many thrift/consignment shops describe themselves this way
}

PLACE_KEYWORDS = ["place", "places", "visit", "visiting", "attraction", "attractions", "museum", "park", "tourist", "sightseeing", "landmark", "monument", "see", "sight", "explore", "exploring", "tour", "tours", "destination", "destinations", "good", "best", "recommend", "recommendation"]

EVENT_KEYWORDS = ["event", "events", "festival", "show", "concert", "meetup", "fair", "carnival", "exhibition", "music", "performance", "happening"]

# Stop words to exclude from keyword matching
STOP_WORDS = {"the", "a", "an", "some", "any", "about", "tell", "me", "okay", "ok", "good", "best", "please", "can", "you", "what", "where", "when", "how", "want", "see", "find", "looking", "like", "need", "this", "that", "city", "kingston"}

# Common misspellings / typos -> canonical form for intent and search
TYPO_TO_CANONICAL = {
    "resturant": "restaurant", "restaraunt": "restaurant", "restorant": "restaurant", "restaurants": "restaurants",
    "thrif": "thrift", "thrft": "thrift", "thift": "thrift", "thrift": "thrift",
    "cafee": "cafe", "cofee": "cafe", "coffee": "coffee", "cafe": "cafe",
    "bakary": "bakery", "bakerys": "bakeries", "bakeries": "bakeries",
    "cloths": "clothes", "clothing": "clothing", "clothes": "clothes",
    "consignement": "consignment", "consignment": "consignment",
    "vintge": "vintage", "vintage": "vintage",
    "boutiqe": "boutique", "boutique": "boutique",
    "footware": "footwear", "footwear": "footwear",
    "brewerys": "breweries", "brewery": "brewery", "breweries": "breweries",
    "gelatto": "gelato", "gelato": "gelato", "icecream": "ice cream",
    "attraction": "attraction", "attractions": "attractions",
    "recomend": "recommend", "reccomend": "recommend",
}


def _edit_distance(s1: str, s2: str) -> int:
    """Levenshtein edit distance between two strings."""
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    n, m = len(s1), len(s2)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[n][m]


def _best_fuzzy_keyword(word: str, candidates: List[str], max_edits: int = 2) -> Optional[str]:
    """Return the best-matching candidate for word (by edit distance) if within max_edits. Prefer exact match."""
    if not word or len(word) < 3:
        return None
    w = word.lower()
    if w in candidates:
        return w
    best = None
    best_d = max_edits + 1
    for c in candidates:
        if abs(len(c) - len(w)) > max_edits:
            continue
        d = _edit_distance(w, c)
        if d <= max_edits and d < best_d:
            best_d = d
            best = c
    return best


def normalize_question_for_keywords(question: str) -> str:
    """Normalize question for keyword lookup: replace known typos so intent is detected correctly."""
    words = question.lower().split()
    normalized = []
    all_map_keys = list(FOOD_KEYWORD_MAP.keys())
    for w in re.sub(r"[^\w\s]", " ", question.lower()).split():
        if len(w) < 2:
            continue
        canonical = TYPO_TO_CANONICAL.get(w, w)
        if canonical == w and len(w) >= 4:
            fuzzy = _best_fuzzy_keyword(w, all_map_keys, max_edits=2)
            if fuzzy:
                canonical = fuzzy
        normalized.append(canonical)
    return " ".join(normalized) if normalized else question.lower()


def expand_keywords_for_search(keywords: List[str]) -> List[str]:
    """Expand keywords with canonical forms so search matches despite typos. Used for entry text matching."""
    expanded = set()
    all_canonicals = set(FOOD_KEYWORD_MAP.keys()) | set(PLACE_KEYWORDS) | set(EVENT_KEYWORDS)
    for kw in keywords:
        if not kw or len(kw) < 2:
            continue
        k = kw.lower()
        expanded.add(k)
        canonical = TYPO_TO_CANONICAL.get(k, k)
        expanded.add(canonical)
        if len(k) >= 4:
            fuzzy = _best_fuzzy_keyword(k, list(all_canonicals), max_edits=2)
            if fuzzy:
                expanded.add(fuzzy)
    return [x for x in expanded if len(x) > 2]


def load_data(file_path: Path) -> str:
    """Load data from file with multiple encoding attempts"""
    if not file_path.exists():
        print(f"⚠️ File '{file_path}' not found, skipping...")
        return None
    
    try:
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1']:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                    if content.strip():
                        return content.strip()
            except UnicodeDecodeError:
                continue
        
        with open(file_path, "rb") as f:
            content = f.read()
            if content:
                return content.decode('utf-8', errors='ignore').strip()
        
        return None
    except Exception as e:
        print(f"❌ Error reading '{file_path}': {e}")
        return None


def discover_data_files() -> Dict[str, List[Path]]:
    """Dynamically discover all data files in Food, Places, and Events folders"""
    data_files = {
        "food": [],
        "places": [],
        "events": []
    }
    
    # Discover Food files
    if FOOD_DIR.exists():
        for file_path in FOOD_DIR.glob("*.txt"):
            data_files["food"].append(file_path)
            print(f"✅ Discovered food file: {file_path.name}")
    
    # Discover Places files
    if PLACES_DIR.exists():
        for file_path in PLACES_DIR.glob("*.txt"):
            data_files["places"].append(file_path)
            print(f"✅ Discovered place file: {file_path.name}")
    
    # Discover Events files
    if EVENTS_DIR.exists():
        for file_path in EVENTS_DIR.glob("*.txt"):
            data_files["events"].append(file_path)
            print(f"✅ Discovered event file: {file_path.name}")
    
    return data_files


def generate_google_maps_url(location: str, name: str = "", city: str = "Kingston, ON") -> str:
    """Generate Google Maps URL from location address"""
    if not location:
        return ""
    # Combine name and location with city for better search results
    if name:
        query = f"{name}, {location}, {city}"
    else:
        query = f"{location}, {city}"
    # URL encode the query
    from urllib.parse import quote
    encoded_query = quote(query)
    return f"https://www.google.com/maps/search/?api=1&query={encoded_query}"


def parse_food_entry(entry_text: str) -> Dict:
    """Parse a food entry (restaurant, bakery, cafe, pub, etc.)"""
    entry = {}
    lines = entry_text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if line.startswith("Business Name:"):
            entry["name"] = line.replace("Business Name:", "").strip()
        elif line.startswith("Location:"):
            entry["location"] = line.replace("Location:", "").strip()
        elif line.startswith("Location URL:"):
            entry["url"] = line.replace("Location URL:", "").strip()
        elif line.startswith("Hours:"):
            entry["hours"] = line.replace("Hours:", "").strip()
        elif line.startswith("Local Sourcing:"):
            entry["local_sourcing"] = line.replace("Local Sourcing:", "").strip()
        elif line.startswith("Veg/Vegan Options:"):
            entry["veg_vegan"] = line.replace("Veg/Vegan Options:", "").strip()
        elif line.startswith("Green Plate Certification:"):
            entry["certification"] = line.replace("Green Plate Certification:", "").strip()
        elif line.startswith("Notes:"):
            entry["notes"] = line.replace("Notes:", "").strip()
    
    # If no URL found but location exists, generate Google Maps URL
    if not entry.get("url") and entry.get("location") and entry.get("name"):
        entry["url"] = generate_google_maps_url(entry["location"], entry["name"])
    
    return entry


def parse_place_entry(entry_text: str) -> Dict:
    """Parse a place entry, including Accessibility and Washrooms."""
    entry = {}
    lines = entry_text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if line.startswith("Place Name:"):
            entry["name"] = line.replace("Place Name:", "").strip()
        elif line.startswith("Location:"):
            entry["location"] = line.replace("Location:", "").strip()
        elif line.startswith("Location URL:"):
            entry["url"] = line.replace("Location URL:", "").strip()
        elif line.startswith("About:"):
            entry["about"] = line.replace("About:", "").strip()
        elif line.startswith("Hours:"):
            entry["hours"] = line.replace("Hours:", "").strip()
        elif line.startswith("Fees:"):
            entry["fees"] = line.replace("Fees:", "").strip()
        elif line.startswith("Accessibility:"):
            accessibility = line.replace("Accessibility:", "").strip()
            # Normalize accessibility values
            accessibility_lower = accessibility.lower()
            # Check for NULL (uppercase) first
            if accessibility.upper() == "NULL" or accessibility_lower in ["null", "none", ""]:
                entry["accessibility"] = "null"  # Keep as string for consistency
            elif "full access" in accessibility_lower or accessibility_lower == "yes":
                entry["accessibility"] = "Full Access"
            elif "partial access" in accessibility_lower or "partial" in accessibility_lower:
                entry["accessibility"] = "Partial Access"
            elif "accessible with assistance" in accessibility_lower:
                entry["accessibility"] = "Accessible with Assistance"
            elif "limited" in accessibility_lower:
                entry["accessibility"] = "Limited"
            else:
                # Try to extract key phrase from longer descriptions
                if "full" in accessibility_lower and "access" in accessibility_lower:
                    entry["accessibility"] = "Full Access"
                elif "partial" in accessibility_lower:
                    entry["accessibility"] = "Partial Access"
                elif "limited" in accessibility_lower:
                    entry["accessibility"] = "Limited"
                else:
                    entry["accessibility"] = "null"  # Default to null if can't determine
        elif line.startswith("Washrooms:"):
            washrooms = line.replace("Washrooms:", "").strip()
            # Normalize washroom values
            washrooms_lower = washrooms.lower()
            # Check for NULL (uppercase) first
            if washrooms.upper() == "NULL" or washrooms_lower in ["null", "none", ""]:
                entry["washrooms"] = "null"
            elif "accessible washrooms available" in washrooms_lower or "washrooms available" in washrooms_lower or washrooms_lower in ["available", "yes"]:
                entry["washrooms"] = "Available"
            elif "partial" in washrooms_lower or "partially accessible" in washrooms_lower:
                entry["washrooms"] = "Partial Available"
            elif "not available" in washrooms_lower or "not accessible" in washrooms_lower or washrooms_lower in ["no"]:
                entry["washrooms"] = "Not Available"
            else:
                # Try to determine availability from description
                if "available" in washrooms_lower:
                    entry["washrooms"] = "Available"
                elif "not" in washrooms_lower:
                    entry["washrooms"] = "Not Available"
                else:
                    entry["washrooms"] = "null"  # Default to null if can't determine
    
    # If no URL found but location exists, generate Google Maps URL
    if not entry.get("url") and entry.get("location") and entry.get("name"):
        entry["url"] = generate_google_maps_url(entry["location"], entry["name"])
    
    return entry


def parse_event_entry(line: str) -> Dict:
    """Parse an event entry (pipe-separated format: Name | Start Date | End Date | Venue | Location | URL)"""
    parts = [p.strip() for p in line.split('|')]
    if len(parts) >= 4:
        # Format: Event Name | Start Date | End Date | Venue | Location | URL
        start_date = parts[1] if len(parts) > 1 else ""
        end_date = parts[2] if len(parts) > 2 else ""
        
        # Format date range
        if start_date and end_date:
            if start_date == end_date:
                date_range = start_date
            else:
                date_range = f"{start_date} - {end_date}"
        elif start_date:
            date_range = start_date
        else:
            date_range = ""
        
        return {
            "name": parts[0],
            "start_date": start_date,
            "end_date": end_date,
            "date": date_range,  # Combined date range for display
            "venue": parts[3] if len(parts) > 3 else "",
            "location": parts[4] if len(parts) > 4 else "",
            "url": parts[5] if len(parts) > 5 else ""
        }
    return None


def split_food_entries(content: str) -> List[str]:
    """Split food file content into individual entries"""
    # Entries are separated by double newlines or "Business Name:" markers
    entries = []
    current_entry = []
    lines = content.split('\n')
    
    for line in lines:
        if line.startswith("Business Name:") and current_entry:
            # Save previous entry
            entries.append('\n'.join(current_entry))
            current_entry = [line]
        else:
            current_entry.append(line)
    
    if current_entry:
        entries.append('\n'.join(current_entry))
    
    return [e.strip() for e in entries if e.strip() and not e.startswith("KINGSTON") and not e.startswith("===")]


def split_shops_entries(content: str) -> List[str]:
    """Split shops file content into individual entries (Store Name: or Business Name: ... separated by ---)."""
    entries = []
    current_entry = []
    lines = content.split('\n')
    for line in lines:
        is_new_entry = line.startswith("Store Name:") or line.startswith("Business Name:")
        if is_new_entry and current_entry:
            entries.append('\n'.join(current_entry))
            current_entry = [line]
        elif line.strip() == "---" or (line.strip().startswith("END OF") and current_entry):
            if current_entry:
                entries.append('\n'.join(current_entry))
            current_entry = []
        elif not (line.strip() == "---" or line.strip().startswith("END OF")):
            current_entry.append(line)
    if current_entry:
        entries.append('\n'.join(current_entry))
    return [e.strip() for e in entries if e.strip() and not e.startswith("KINGSTON") and not e.startswith("====")]


def parse_shop_entry(entry_text: str) -> Dict:
    """Parse a shop/store entry (Store Name or Business Name, Location, Hours of Operation or Hours, Info or Notes, Category)."""
    entry = {}
    lines = entry_text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line or line == "---":
            continue
        if line.startswith("Store Name:"):
            entry["name"] = line.replace("Store Name:", "").strip()
        elif line.startswith("Business Name:"):
            entry["name"] = line.replace("Business Name:", "").strip()
        elif line.startswith("Location:"):
            entry["location"] = line.replace("Location:", "").strip()
        elif line.startswith("Location URL:"):
            entry["url"] = line.replace("Location URL:", "").strip()
        elif line.startswith("Hours of Operation:") or line.startswith("Hours:"):
            entry["hours"] = (line.replace("Hours of Operation:", "").replace("Hours:", "").strip())
        elif line.startswith("Info:") or line.startswith("Notes:"):
            entry["notes"] = (line.replace("Info:", "").replace("Notes:", "").strip())
        elif line.startswith("Local Sourcing:"):
            entry["local_sourcing"] = line.replace("Local Sourcing:", "").strip()
        elif line.startswith("Category:"):
            entry["category"] = line.replace("Category:", "").strip()
    if not entry.get("url") and entry.get("location") and entry.get("name"):
        entry["url"] = generate_google_maps_url(entry["location"], entry["name"])
    return entry


def split_place_entries(content: str) -> List[str]:
    """Split places file content into individual entries"""
    entries = []
    current_entry = []
    lines = content.split('\n')
    
    for line in lines:
        if line.startswith("Place Name:") and current_entry:
            # Save previous entry
            entries.append('\n'.join(current_entry))
            current_entry = [line]
        else:
            current_entry.append(line)
    
    if current_entry:
        entries.append('\n'.join(current_entry))
    
    return [e.strip() for e in entries if e.strip() and not e.startswith("KINGSTON") and not e.startswith("===")]


# Cache data loading to avoid reloading on every request
_cached_data = None
_cache_timestamp = None

def load_all_data(force_reload: bool = False) -> Dict[str, Dict[str, List[Dict]]]:
    """Load all data from discovered files and organize by category.
    Uses caching to avoid reloading on every request."""
    global _cached_data, _cache_timestamp
    
    # Return cached data if available and not forcing reload
    if not force_reload and _cached_data is not None:
        return _cached_data
    
    data_files = discover_data_files()
    all_data = {
        "food": {},
        "places": {},
        "events": {}
    }
    
    # Load Food files (and shops.txt with shop parser)
    for file_path in data_files["food"]:
        file_name = file_path.stem
        content = load_data(file_path)
        if content:
            if file_name == "shops":
                entries = split_shops_entries(content)
                parsed_entries = [parse_shop_entry(e) for e in entries if e]
            else:
                entries = split_food_entries(content)
                parsed_entries = [parse_food_entry(e) for e in entries if e]
            all_data["food"][file_name] = parsed_entries
            print(f"✅ Loaded {len(parsed_entries)} entries from {file_name}")
    
    # Load Places files
    for file_path in data_files["places"]:
        file_name = file_path.stem
        content = load_data(file_path)
        if content:
            entries = split_place_entries(content)
            parsed_entries = [parse_place_entry(e) for e in entries if e]
            all_data["places"][file_name] = parsed_entries
            print(f"✅ Loaded {len(parsed_entries)} entries from {file_name}")
    
    # Load Events files
    for file_path in data_files["events"]:
        file_name = file_path.stem
        content = load_data(file_path)
        if content:
            # Events are one per line, pipe-separated
            lines = content.strip().split('\n')
            parsed_entries = []
            for line in lines:
                if line.strip() and '|' in line:
                    entry = parse_event_entry(line)
                    if entry:
                        parsed_entries.append(entry)
            all_data["events"][file_name] = parsed_entries
            print(f"✅ Loaded {len(parsed_entries)} entries from {file_name}")
    
    # Cache the data
    _cached_data = all_data
    _cache_timestamp = datetime.now()
    
    return all_data


def detect_query_specificity(question: str) -> Tuple[bool, List[str]]:
    """Detect if query is specific (targets one category) or vague (needs multiple categories).
    Uses typo-normalized question so misspellings (e.g. thrif, resturant) still map correctly."""
    question_lower = question.lower()
    # Normalize typos so "thrif stores" / "resturants" are detected
    normalized = normalize_question_for_keywords(question)
    search_text = question_lower + " " + normalized
    
    # Check for specific food type keywords (exact or typo-corrected)
    specific_files = []
    for keyword, files in FOOD_KEYWORD_MAP.items():
        if keyword in search_text:
            specific_files.extend(files)
    
    # Remove duplicates while preserving order
    specific_files = list(dict.fromkeys(specific_files))
    
    # Check for place keywords (in original or normalized)
    has_place_query = any(kw in search_text for kw in PLACE_KEYWORDS)
    
    # Check for event keywords
    has_event_query = any(kw in search_text for kw in EVENT_KEYWORDS)
    
    # If specific files found (e.g. thrift -> shops, restaurant -> restaurants), it's a specific query
    is_specific = len(specific_files) > 0
    
    # If query mentions multiple categories, treat as vague only when we don't have a clear food/shop ask.
    # E.g. "see thrift stores" has both "see" (place) and "thrift" (shops) - user wants shops, so keep specific.
    category_count = sum([
        len(specific_files) > 0,
        has_place_query,
        has_event_query
    ])
    if category_count > 1 and not specific_files:
        is_specific = False
    elif specific_files:
        # User asked for a specific food/shop type (thrift, restaurant, etc.) - prioritize that
        is_specific = True
    
    return is_specific, specific_files


def parse_date_from_text(text: str) -> Optional[datetime]:
    """Parse date from text like 'feb 8', 'february 8', '8 feb', '8 february', 'feb 8 2026'"""
    text_lower = text.lower()
    
    # Month names mapping
    months = {
        'january': 1, 'jan': 1,
        'february': 2, 'feb': 2,
        'march': 3, 'mar': 3,
        'april': 4, 'apr': 4,
        'may': 5,
        'june': 6, 'jun': 6,
        'july': 7, 'jul': 7,
        'august': 8, 'aug': 8,
        'september': 9, 'sep': 9, 'sept': 9,
        'october': 10, 'oct': 10,
        'november': 11, 'nov': 11,
        'december': 12, 'dec': 12
    }
    
    # Try to find date patterns
    patterns = [
        r'(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:\s+(\d{4}))?',
        r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:\s+(\d{4}))?',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                try:
                    if groups[0].isdigit():
                        day = int(groups[0])
                        month_name = groups[1]
                        year = int(groups[2]) if len(groups) > 2 and groups[2] else 2026
                    else:
                        month_name = groups[0]
                        day = int(groups[1])
                        year = int(groups[2]) if len(groups) > 2 and groups[2] else 2026
                    
                    month = months.get(month_name)
                    if month and 1 <= day <= 31:
                        return datetime(year, month, day)
                except (ValueError, KeyError):
                    continue
    
    return None


def event_falls_on_date(event: Dict, target_date: datetime) -> bool:
    """Check if an event falls on or around a target date"""
    if not event.get("start_date") or not event.get("end_date"):
        return False
    
    try:
        # Parse event dates
        start_str = event["start_date"]
        end_str = event["end_date"]
        
        # Try to parse dates (format: "January 29, 2026" or "February 7, 2026")
        start_date = parse_date_from_text(start_str)
        end_date = parse_date_from_text(end_str)
        
        if not start_date or not end_date:
            return False
        
        # Check if target date falls within event date range
        return start_date <= target_date <= end_date
    except Exception:
        return False


def event_in_month(event: Dict, month: int, year: int = 2026) -> bool:
    """Check if an event occurs in a specific month"""
    if not event.get("start_date") or not event.get("end_date"):
        return False
    
    try:
        start_str = event["start_date"]
        end_str = event["end_date"]
        
        start_date = parse_date_from_text(start_str)
        end_date = parse_date_from_text(end_str)
        
        if not start_date or not end_date:
            return False
        
        # Check if event overlaps with the month
        # Event is in month if start or end is in month, or if event spans the month
        return (start_date.month == month and start_date.year == year) or \
               (end_date.month == month and end_date.year == year) or \
               (start_date <= datetime(year, month, 1) <= end_date) or \
               (start_date <= datetime(year, month, 28) <= end_date)
    except Exception:
        return False


def get_certification_priority(certification: str) -> int:
    """Get priority value for certification: Gold=3, Silver=2, Bronze=1, null/None=0"""
    if not certification or certification.lower() == 'null':
        return 0
    cert_lower = certification.lower().strip()
    if cert_lower == 'gold':
        return 3
    elif cert_lower == 'silver':
        return 2
    elif cert_lower == 'bronze':
        return 1
    return 0


def sort_food_entries_by_certification(entries: List[Dict]) -> List[Dict]:
    """Sort food entries by certification priority (Gold > Silver > Bronze > null)"""
    return sorted(entries, key=lambda e: get_certification_priority(e.get('certification', '')), reverse=True)


def search_in_entries(entries: List[Dict], keywords: List[str], location_keywords: List[str] = None, 
                     target_date: Optional[datetime] = None, target_month: Optional[int] = None,
                     return_all_if_no_keywords: bool = False, is_food: bool = False) -> List[Dict]:
    """Search entries for matching keywords, with optional date filtering for events"""
    matches = []
    
    # If no keywords and no location keywords and no date filter, and return_all flag is set, return all entries
    if return_all_if_no_keywords and not keywords and not location_keywords and not target_date and not target_month:
        return entries
    
    # Filter out stop words (caller may pass expanded/typo-corrected keywords)
    meaningful_keywords = [kw for kw in keywords if kw and kw.lower() not in STOP_WORDS and len(kw) > 2]
    
    for entry in entries:
        entry_text = ' '.join(str(v).lower() for v in entry.values() if v)
        
        # For events, check date filtering first
        if target_date and "start_date" in entry:
            if not event_falls_on_date(entry, target_date):
                continue
        elif target_month and "start_date" in entry:
            if not event_in_month(entry, target_month):
                continue
        
        # Match if any keyword appears in name, description, category, location, etc.
        if meaningful_keywords and any(kw.lower() in entry_text for kw in meaningful_keywords):
            matches.append(entry)
        # Check location if provided
        elif location_keywords:
            entry_location = str(entry.get("location", "")).lower()
            if any(loc.lower() in entry_location for loc in location_keywords):
                matches.append(entry)
        # If no keywords but date filter applied, include all matching events
        elif (target_date or target_month) and "start_date" in entry:
            matches.append(entry)
        # If return_all flag is set and no meaningful keywords, include entry
        elif return_all_if_no_keywords and not meaningful_keywords:
            matches.append(entry)
    
    # Sort food entries by certification priority if this is a food search
    if is_food and matches:
        matches = sort_food_entries_by_certification(matches)
    
    return matches


def find_relevant_context(question: str, all_data: Dict) -> Dict:
    """Find relevant context based on question specificity, with date filtering for events.
    Uses expanded keywords (typo-corrected + fuzzy) so descriptions/categories match even with misspellings."""
    question_lower = question.lower()
    # Extract words (allow hyphenated and apostrophes for "ice-cream", "don't")
    words = re.findall(r"\b[\w']+\b", question_lower)
    keywords = [w for w in words if len(w) > 2]
    meaningful_keywords = [kw for kw in keywords if kw.lower() not in STOP_WORDS]
    # Expand with canonical forms so "thrif" matches entries containing "thrift", etc.
    search_keywords = expand_keywords_for_search(meaningful_keywords)
    
    # Detect "full list" or "all" requests
    wants_full_list = any(phrase in question_lower for phrase in ["full list", "all", "complete list", "everything", "entire list"])
    
    # Extract date from question
    target_date = parse_date_from_text(question)
    target_month = None
    if target_date:
        target_month = target_date.month
    else:
        # Try to extract just month name
        months = ['january', 'february', 'march', 'april', 'may', 'june', 
                  'july', 'august', 'september', 'october', 'november', 'december',
                  'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec']
        for i, month_name in enumerate(months):
            if month_name in question_lower:
                target_month = (i % 12) + 1
                break
    
    # Extract location keywords
    location_keywords = []
    location_patterns = ["near", "nearby", "around", "close to", "on", "at", "in"]
    words = question_lower.split()
    for i, word in enumerate(words):
        if word in location_patterns and i + 1 < len(words):
            # Skip if it's a date pattern
            next_word = words[i+1] if i+1 < len(words) else ""
            if next_word.isdigit() or next_word in ['january', 'february', 'march', 'april', 'may', 'june', 
                                                     'july', 'august', 'september', 'october', 'november', 'december',
                                                     'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec']:
                continue
            # Get the location (next few words)
            location = ' '.join(words[i+1:min(i+4, len(words))])
            location_keywords.append(location)
    
    is_specific, specific_files = detect_query_specificity(question)
    
    relevant_context = {
        "food": {},
        "places": {},
        "events": {}
    }
    
    # Handle specific queries
    if is_specific and specific_files:
        # Search only in specific food files
        for file_name in specific_files:
            file_key = file_name.replace(".txt", "")
            if file_key in all_data["food"]:
                entries = all_data["food"][file_key]
                matches = search_in_entries(entries, search_keywords, location_keywords, is_food=True)
                if matches:
                    # Already sorted by certification in search_in_entries
                    relevant_context["food"][file_key] = matches if wants_full_list else matches[:10]
                else:
                    # If no matches, return entries based on full_list preference, sorted by certification
                    sorted_entries = sort_food_entries_by_certification(entries) if entries else []
                    relevant_context["food"][file_key] = sorted_entries if wants_full_list else sorted_entries[:1] if sorted_entries else []
    
    # Handle vague queries or queries without specific file matches
    elif not is_specific or not specific_files:
        # Check what categories are being asked - prioritize based on question intent
        # Strong place indicators
        strong_place_indicators = ["place", "places", "visit", "visiting", "attraction", "attractions", "sightseeing", "tourist", "destination", "see", "explore", "exploring", "museum", "museums", "park", "parks"]
        # Food indicators
        food_indicators = ["food", "eat", "restaurant", "cafe", "bakery", "pub", "dining", "meal", "cuisine"]
        # Event indicators  
        event_indicators = ["event", "events", "festival", "show", "concert", "happening"]
        
        # Count matches to determine primary intent
        place_count = sum(1 for kw in strong_place_indicators if kw in question_lower)
        food_count = sum(1 for kw in food_indicators if kw in question_lower)
        event_count = sum(1 for kw in event_indicators if kw in question_lower)
        
        # Determine primary intent - allow multiple categories when explicitly mentioned
        # Check for place-related phrases first (more reliable than single keywords)
        has_place_phrase = any(phrase in question_lower for phrase in [
            "places to visit", "place to visit", "places to see", "place to see",
            "good places", "best places", "places in", "visit", "visiting",
            "tourist attractions", "attractions", "sightseeing", "things to see"
        ])
        has_place_query = place_count > 0 or has_place_phrase or any(kw in question_lower for kw in PLACE_KEYWORDS)
        has_food_query = food_count > 0
        has_event_query = event_count > 0
        
        # Check for explicit requests for multiple categories (e.g., "places and restaurants")
        explicit_both = (has_place_query and has_food_query) or any(phrase in question_lower for phrase in [
            "places and restaurants", "restaurants and places", "places and food", "food and places",
            "attractions and restaurants", "restaurants and attractions", "places and dining", "dining and places"
        ])
        
        # If both places and food are explicitly mentioned, include both (places prioritized)
        if explicit_both:
            has_place_query = True
            has_food_query = True
            has_event_query = False  # Exclude events unless also mentioned
        # If only places mentioned (no food), exclude food and events
        # Also check for place phrases to catch vague queries like "good places to visit"
        elif (place_count > 0 or has_place_phrase) and food_count == 0:
            has_food_query = False
            has_event_query = False
            has_place_query = True  # Ensure places are included
        # If only food mentioned (no places), exclude places and events
        elif food_count > 0 and place_count == 0:
            has_place_query = False
            has_event_query = False
        # If only events mentioned, exclude food and places
        elif event_count > 0 and place_count == 0 and food_count == 0:
            has_food_query = False
            has_place_query = False
        
        # If no specific category mentioned, show all
        if not (has_food_query or has_place_query or has_event_query):
            has_food_query = has_place_query = has_event_query = True
        
        # Food: Return entries based on full_list preference, prioritized by certification
        if has_food_query:
            for file_key, entries in all_data["food"].items():
                if entries:
                    # Try to find matches first
                    # Use return_all_if_no_keywords for very vague queries
                    is_vague_food_query = len(meaningful_keywords) <= 3 and not location_keywords
                    matches = search_in_entries(entries, search_keywords, location_keywords, return_all_if_no_keywords=is_vague_food_query, is_food=True)
                    if matches:
                        # Already sorted by certification in search_in_entries
                        relevant_context["food"][file_key] = matches if wants_full_list else matches[:10]
                    else:
                        # If no keyword matches but it's a food query, return sample entries sorted by certification
                        sorted_entries = sort_food_entries_by_certification(entries)
                        relevant_context["food"][file_key] = sorted_entries if wants_full_list else sorted_entries[:10]
        
        # Places: Return entries based on full_list preference (prioritized - return more entries)
        if has_place_query:
            for file_key, entries in all_data["places"].items():
                if entries:
                    # For vague place queries, be more lenient - try keyword matching first
                    # Use return_all_if_no_keywords for very vague queries (like "good places to visit")
                    is_vague_place_query = (
                        len(meaningful_keywords) <= 3 and not location_keywords
                    ) or any(phrase in question_lower for phrase in [
                        "good places", "best places", "recommend", "some places", 
                        "tell me about", "places to visit", "place to visit",
                        "show me", "what places", "where to visit", "places in kingston"
                    ])
                    matches = search_in_entries(entries, search_keywords, location_keywords, return_all_if_no_keywords=is_vague_place_query)
                    if matches:
                        # Places are prioritized - return more entries (10 instead of 5) when not full list
                        relevant_context["places"][file_key] = matches if wants_full_list else matches[:10]
                    else:
                        # If no keyword matches but it's a place query, ALWAYS return entries anyway
                        # This ensures places are shown even for very vague queries
                        # Places are prioritized - return more entries (10 instead of 5) when not full list
                        relevant_context["places"][file_key] = entries if wants_full_list else entries[:10]
        
        # Events: Return entries with date filtering and full_list preference
        if has_event_query:
            for file_key, entries in all_data["events"].items():
                if entries:
                    # Apply date filtering if date/month specified
                    matches = search_in_entries(entries, keywords, location_keywords, target_date, target_month)
                    if matches:
                        # If full list requested, return all matches; otherwise limit
                        relevant_context["events"][file_key] = matches if wants_full_list else matches[:5]
                    elif target_date or target_month:
                        # Date filter applied but no matches - return empty
                        relevant_context["events"][file_key] = []
                    else:
                        # No date filter, return based on full_list preference
                        all_matches = search_in_entries(entries, keywords, location_keywords)
                        if all_matches:
                            relevant_context["events"][file_key] = all_matches if wants_full_list else all_matches[:3]
                        else:
                            relevant_context["events"][file_key] = entries if wants_full_list else entries[:1]
    
    return relevant_context


def clean_response_formatting(text: str) -> str:
    """Clean up response formatting by removing excessive blank lines, numbered lists, and fixing spacing"""
    if not text:
        return text
    
    # Remove numbered list patterns (1., 2., etc.) at start of lines
    lines = text.split('\n')
    cleaned_lines = []
    prev_blank = False
    
    for line in lines:
        stripped = line.strip()
        is_blank = not stripped
        
        # Remove numbered list prefixes (1., 2., 3., etc.)
        if not is_blank:
            # Remove patterns like "1. ", "2. ", "10. " at the start
            stripped = re.sub(r'^\d+\.\s+', '', stripped)
            # If line was modified, update it
            if stripped != line.strip():
                line = stripped
        
        # Skip consecutive blank lines (keep only one)
        if is_blank:
            if not prev_blank and cleaned_lines:  # Only add blank if previous wasn't blank and we have content
                cleaned_lines.append('')
            prev_blank = True
        else:
            cleaned_lines.append(line.rstrip())  # Remove trailing spaces
            prev_blank = False
    
    # Remove leading blank lines
    while cleaned_lines and not cleaned_lines[0].strip():
        cleaned_lines.pop(0)
    
    # Remove trailing blank lines
    while cleaned_lines and not cleaned_lines[-1].strip():
        cleaned_lines.pop()
    
    # Final pass: ensure no more than 2 consecutive newlines (for section breaks)
    result = '\n'.join(cleaned_lines)
    # Replace 3+ newlines with 2 newlines (for section breaks)
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result


def format_context_for_prompt(context_dict: Dict) -> str:
    """Format context dictionary into a readable string for the prompt. Places are prioritized when both places and food are present."""
    parts = []
    
    # Check if both places and food are present - prioritize places
    has_places = bool(context_dict.get("places"))
    has_food = bool(context_dict.get("food"))
    
    # Format Places entries FIRST (prioritized)
    if context_dict["places"]:
        place_parts = []
        for file_key, entries in context_dict["places"].items():
            if entries:
                place_parts.append(f"\n=== PLACES TO VISIT ===")
                for i, entry in enumerate(entries, 1):
                    place_parts.append(f"\n{i}. {entry.get('name', 'N/A')}")
                    if entry.get('location'):
                        place_parts.append(f"   Location: {entry['location']}")
                    if entry.get('url'):
                        place_parts.append(f"   Find Location: {entry['url']}")
                    if entry.get('about'):
                        place_parts.append(f"   About: {entry['about']}")
                    if entry.get('hours'):
                        place_parts.append(f"   Hours: {entry['hours']}")
                    if entry.get('fees'):
                        place_parts.append(f"   Fees: {entry['fees']}")
                    # Always include Accessibility and Washrooms for places (even if null) - these are critical fields
                    # Check if the field exists in the entry (was parsed from data)
                    if 'accessibility' in entry:
                        accessibility_value = entry.get('accessibility', 'null')
                        # Always include the line, even if value is null
                        place_parts.append(f"   Accessibility: {accessibility_value}")
                    # If accessibility field doesn't exist in entry, it means it wasn't in the source data
                    # In that case, we still want to show it as null so LLM knows to include it
                    if 'washrooms' in entry:
                        washrooms_value = entry.get('washrooms', 'null')
                        # Always include the line, even if value is null
                        place_parts.append(f"   Washrooms: {washrooms_value}")
        if place_parts:
            parts.append('\n'.join(place_parts))
    
    # Format Food entries (after places when both are present)
    if context_dict["food"]:
        food_parts = []
        for file_key, entries in context_dict["food"].items():
            if entries:
                category_name = file_key.replace("_", " ").title()
                food_parts.append(f"\n=== {category_name.upper()} ===")
                for i, entry in enumerate(entries, 1):
                    food_parts.append(f"\n{i}. {entry.get('name', 'N/A')}")
                    if entry.get('location'):
                        food_parts.append(f"   Location: {entry['location']}")
                    if entry.get('url'):
                        food_parts.append(f"   Find Location: {entry['url']}")
                    if entry.get('hours'):
                        food_parts.append(f"   Hours: {entry['hours']}")
                    if entry.get('notes'):
                        food_parts.append(f"   Notes: {entry['notes']}")
                    if entry.get('category'):
                        food_parts.append(f"   Category: {entry['category']}")
                    if entry.get('local_sourcing'):
                        food_parts.append(f"   Local Sourcing: {entry['local_sourcing']}")
                    if entry.get('veg_vegan'):
                        food_parts.append(f"   Veg/Vegan: {entry['veg_vegan']}")
                    if entry.get('certification') and entry.get('certification') != 'null':
                        food_parts.append(f"   Green Plate Certification: {entry['certification']}")
        if food_parts:
            parts.append('\n'.join(food_parts))
    
    # Format Events entries
    if context_dict["events"]:
        event_parts = []
        for file_key, entries in context_dict["events"].items():
            if entries:
                event_parts.append(f"\n=== EVENTS ===")
                for i, entry in enumerate(entries, 1):
                    event_parts.append(f"\n{i}. {entry.get('name', 'N/A')}")
                    if entry.get('date'):
                        event_parts.append(f"   Date: {entry['date']}")
                    if entry.get('venue'):
                        event_parts.append(f"   Venue: {entry['venue']}")
                    if entry.get('location'):
                        event_parts.append(f"   Location: {entry['location']}")
                    if entry.get('url'):
                        event_parts.append(f"   Find Location: {entry['url']}")
        if event_parts:
            parts.append('\n'.join(event_parts))
    
    return '\n\n'.join(parts) if parts else "No relevant data found."


def ask(question: str, language: str = "en"):
    """
    Ask a question using RAG with OpenRouter across multiple data types.
    
    Args:
        question: The user's question
        language: Language code ("en" for English, "fr" for French)
    """
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your_api_key_here":
        return "❌ Error: OPENROUTER_API_KEY is not set. Please configure it in your .env file or update router.py. Get your key from https://openrouter.ai/keys"
    
    # Load all data
    print("Loading data from all files...")
    all_data = load_all_data()
    
    if not any(all_data.values()):
        print("❌ No data loaded from any file")
        return None
    
    total_entries = sum(len(entries) for category in all_data.values() for entries in category.values())
    print(f"✅ Total entries loaded: {total_entries}")
    
    # Find relevant context
    context_dict = find_relevant_context(question, all_data)
    print(f"✅ Found relevant context")
    
    # Format context for prompt
    combined_context = format_context_for_prompt(context_dict)
    
    # Check if we have any data in context
    has_context_data = any(
        len(entries) > 0 
        for category in context_dict.values() 
        for entries in category.values()
    )
    
    # If no context data but we have data available, try intelligent fallback
    if (not combined_context or combined_context == "No relevant data found." or not has_context_data):
        question_lower = question.lower()
        
        # Check what the user is asking for - use same logic as find_relevant_context
        strong_place_indicators = ["place", "places", "visit", "visiting", "attraction", "attractions", "sightseeing", "tourist", "destination", "see", "explore", "exploring", "museum", "museums", "park", "parks"]
        place_count = sum(1 for kw in strong_place_indicators if kw in question_lower)
        
        # Check for place-related phrases (more reliable for vague queries)
        has_place_phrase = any(phrase in question_lower for phrase in [
            "places to visit", "place to visit", "places to see", "place to see",
            "good places", "best places", "places in", "visit", "visiting",
            "tourist attractions", "attractions", "sightseeing", "things to see"
        ])
        has_place_query = place_count > 0 or has_place_phrase or any(kw in question_lower for kw in PLACE_KEYWORDS)
        has_food_query = any(kw in question_lower for kw in ["food", "eat", "restaurant", "cafe", "bakery", "pub", "dining"]) and not has_place_query
        has_event_query = any(kw in question_lower for kw in EVENT_KEYWORDS) and not has_place_query
        
        # If places are mentioned, ONLY return places (no food/events)
        if has_place_query:
            has_food_query = False
            has_event_query = False
        
        # If no category detected, assume general query (show all)
        if not (has_place_query or has_food_query or has_event_query):
            has_place_query = has_food_query = has_event_query = True
        
        # Create fallback context with available data
        fallback_context = {"food": {}, "places": {}, "events": {}}
        wants_full_list = any(phrase in question_lower for phrase in ["full list", "all", "complete list", "everything", "entire list"])
        
        # Get available data counts
        total_places = sum(len(entries) for entries in all_data["places"].values())
        total_food = sum(len(entries) for entries in all_data["food"].values())
        total_events = sum(len(entries) for entries in all_data["events"].values())
        
        # Normal fallback - return data for requested categories
        if has_place_query and total_places > 0:
            for file_key, entries in all_data["places"].items():
                if entries:
                    fallback_context["places"][file_key] = entries if wants_full_list else entries[:5]
        
        if has_food_query and total_food > 0:
            for file_key, entries in all_data["food"].items():
                if entries:
                    fallback_context["food"][file_key] = entries if wants_full_list else entries[:3]
        
        if has_event_query and total_events > 0:
            for file_key, entries in all_data["events"].items():
                if entries:
                    fallback_context["events"][file_key] = entries if wants_full_list else entries[:3]
        
        # If user asked for places but no places data, show alternatives only if explicitly requested
        if has_place_query and total_places == 0 and (total_food > 0 or total_events > 0):
            # Only show alternatives if user also mentioned food/events, otherwise be clear about missing data
            if not (has_food_query or has_event_query):
                return "I don't have any places data available at the moment. However, I can help you with restaurants, cafes, or events. Would you like to see those instead?"
        
        # Format fallback context
        fallback_combined = format_context_for_prompt(fallback_context)
        
        if fallback_combined and fallback_combined != "No relevant data found.":
            combined_context = fallback_combined
            context_dict = fallback_context  # Update context_dict for prompt
        elif total_places == 0 and total_food == 0 and total_events == 0:
            return "I couldn't find any relevant information in the database. Please try rephrasing your question."
        else:
            return "I found some information, but it might not match your exact query. Try asking more specifically, for example: 'show me places to visit', 'what restaurants are there?', or 'events in February'."
    
    # Determine response language and create language-specific instructions
    if language == "fr":
        language_instruction = "\n\nCRITICAL LANGUAGE INSTRUCTION: You MUST respond entirely in French. All text, including section headers, labels, and descriptions, must be in French. Use French translations: 'Location' → 'Emplacement', 'Hours' → 'Heures', 'Find Location' → 'Trouver l'emplacement', 'About' → 'À propos', 'Fees' → 'Frais', 'Date' → 'Date', 'Venue' → 'Lieu', 'Notes' → 'Notes', 'Veg/Vegan' → 'Végétarien/Végan', 'Green Plate Certification' → 'Certification Green Plate', 'Accessibility' → 'Accessibilité', 'Washrooms' → 'Toilettes'."
        section_headers = "**CAFÉS**, **RESTAURANTS**, **BOULANGERIES**, **PUBS**, **MAGASINS**, **LIEUX**, **ÉVÉNEMENTS**"
        example_format = """
**CAFÉS**

**Kingston Coffee House**
• Emplacement: 1046 Princess St
• Heures: Lun-Dim: 7h00 - 18h00
• Notes: Un café local connu pour son atmosphère chaleureuse
• Végétarien/Végan: Oui

**LIEUX**

**Fort Henry**
• Emplacement: 1 Fort Henry Dr.
• Trouver l'emplacement: [URL]
• À propos: Une forteresse militaire britannique massive du 19e siècle
• Heures: Quotidien: 10h00 – 17h00 (mai–sept)
• Frais: ~20,00 $ - 25,00 $
• Accessibilité: Accès partiel - Les bâtiments historiques varient en accessibilité
• Toilettes: Toilettes accessibles disponibles
"""
    else:
        language_instruction = "\n\nCRITICAL LANGUAGE INSTRUCTION: You MUST respond entirely in English. All text, including section headers, labels, and descriptions, must be in English."
        section_headers = "**CAFÉS**, **RESTAURANTS**, **BAKERIES**, **PUBS**, **SHOPS**, **PLACES**, **EVENTS**"
        example_format = """
**CAFÉS**

**Kingston Coffee House**
• Location: 1046 Princess St
• Hours: Mon-Sun: 7:00am - 6:00pm
• Notes: A local coffee shop known for its cozy atmosphere
• Veg/Vegan: Yes

**PLACES**

**Fort Henry**
• Location: 1 Fort Henry Dr.
• Find Location: [URL]
• About: A massive 19th-century British military fortress
• Hours: Daily: 10:00 AM – 5:00 PM (May–Sept)
• Fees: ~$20.00 - $25.00
• Accessibility: Partial Access - Historic buildings vary in accessibility
• Washrooms: Accessible washrooms available
"""
    
    # Create intelligent prompt
    prompt = f"""You are a friendly, helpful city guide assistant for Kingston, Ontario. Your goal is to give the user the best possible answer using ONLY the data below.

INTERPRETATION & INTENT:
- Interpret the user's question by intent, not just exact words. If they ask for "thrif stores", "cheap clothes", "secondhand shops", or "places to buy used stuff", use the SHOPS data (thrift, consignment, vintage) and answer helpfully.
- Ignore minor typos and misspellings (e.g. resturant, cafee, thrif, cloths). Assume they mean the closest sensible category (restaurant, cafe, thrift, clothes) and answer from the relevant data.
- If the question could match several types (e.g. "stores" = shops or places), prefer the category that has matching data and give a clear, concrete answer. Do not say "I don't have information" if the data below clearly contains relevant entries—use them.
- CRITICAL: If the user asks about "places", "places to visit", "good places", "best places", "attractions", "things to see", or similar place-related queries, you MUST show PLACES data. Places are the TOP PRIORITY when mentioned.
- When both PLACES and RESTAURANTS/FOOD are requested, ALWAYS show PLACES first (prioritize places section), then show restaurants/food sections after.
- Be conversational and concise. Lead with the most relevant results; add a short friendly line if helpful (e.g. "Here are some great places to visit in Kingston:").

Available Data:
{combined_context}

User Question: {question}

CRITICAL FORMATTING RULES - FOLLOW EXACTLY:

1. Section Headers: Use {section_headers} as section headers (bold markdown)

2. Item Format - Each business/place/event name should be a BOLD HEADER (not numbered):
   
   For Shops (stores, clothing, boutiques, etc.): When data includes "Category:" use section **SHOPS** and format as:
   **Store Name**
   • Location: [address]
   • Find Location: [URL from data - ONLY if available]
   • Hours: [hours]
   • Notes: [description if available]
   • Category: [e.g. WOMEN'S CLOTHING, FOOTWEAR]
   • Local Sourcing: [if available]
   
   For Food Places:
   **Business Name**
   • Location: [address]
   • Find Location: [URL from data - ONLY include if URL is available in the data]
   • Hours: [hours]
   • Notes: [description if available]
   • Veg/Vegan: [options if applicable]
   • Green Plate Certification: [Gold/Silver/Bronze - ONLY include if certification is available and not null]
   
   For Places:
   **Place Name**
   • Location: [address]
   • Find Location: [URL from data - ONLY include if URL is available in the data]
   • About: [description]
   • Hours: [hours]
   • Fees: [price]
   • Accessibility: [MUST include this line if "Accessibility:" appears in the data below - use the exact value from data: Full Access, Partial Access, Limited, Accessible with Assistance, or null]
   • Washrooms: [MUST include this line if "Washrooms:" appears in the data below - use the exact value from data: Available, Partial Available, Not Available, or null]
   
   For Events:
   **Event Name**
   • Date: [date or date range]
   • Venue: [venue name]
   • Location: [address]
   • Find Location: [URL from data - ONLY include if URL is available in the data]

3. DO NOT use numbered lists (no "1.", "2.", etc.)
4. DO NOT use dashes (-) - ONLY use bullet points (•)
5. Put exactly ONE blank line between each item
6. Put exactly ONE blank line after section headers
7. If information is missing, skip that line entirely (don't write "N/A", "TBD", or empty fields)

8. CRITICAL FOR PLACES - Accessibility and Washrooms: When displaying Places, you MUST include both "Accessibility:" and "Washrooms:" lines if they appear in the data below. These fields are ESSENTIAL for users with accessibility needs. Even if the value is "null" or "NULL" in the data, still include the line (e.g., "• Accessibility: null" or "• Washrooms: null"). Look for these fields in the context data - they are formatted as "Accessibility: [value]" and "Washrooms: [value]" in the data provided below. DO NOT SKIP THESE FIELDS - they are critical information.

9. For Places, ALWAYS include: **Place Name**, Location, "Find Location: [URL]" if URL is available, About, Hours, Fees, AND both Accessibility and Washrooms lines (as specified in rule 8 above). Missing these fields is a critical error.

10. CRITICAL FOR RESTAURANTS/FOOD - Green Plate Certification: When displaying restaurants, cafes, bakeries, or any food establishments, you MUST include the "Green Plate Certification:" line if it appears in the data below (even if the value is "null"). This shows sustainability certification (Gold, Silver, Bronze) which is important information. DO NOT SKIP THIS FIELD.
11. For Events, include: **Event Name**, Date (or Date Range), Venue, Location, and "Find Location: [URL]" if URL is available in the data
12. For Food Places, ALWAYS include: **Business Name**, Location, "Find Location: [URL]" if URL is available, Hours, Notes, Veg/Vegan options (if available), AND Green Plate Certification (Gold/Silver/Bronze) if it appears in the data (even if null). Missing Green Plate Certification when it's in the data is an error.
12a. For Shops (stores, clothing, boutiques), include: **Store Name**, Location, "Find Location: [URL]" if available, Hours, Notes, Category, Local Sourcing if available

13. Order items logically (alphabetically or by relevance). When both PLACES and RESTAURANTS sections are present, PLACES section must come FIRST.

14. SMART QUERY HANDLING:
    - If user asks for "full list", "all events", "complete list", "everything" - show ALL matching items
    - If user asks for events on a specific date (e.g., "events on feb 8") - show ALL events that fall on that date (including events that start before and end after that date)
    - If user asks for events in a month (e.g., "events in february") - show ALL events in that month
    - For vague queries without "full list" - show a sample (3-5 items) from each category
    - Apply similar logic for food, shops, and places: "all restaurants" = full list, vague query = sample
    - Match by meaning: "thrift"/"secondhand"/"consignment"/"vintage" → use SHOPS data; "cheap clothes" or "used clothing" → SHOPS. Always prefer giving a helpful answer from the data over saying you don't have information.

EXAMPLE FORMAT:
{example_format}

CRITICAL: Follow this format exactly. No numbering, no extra blank lines, clean and consistent.

Answer:"""
    
    # Call OpenRouter API
    print("Calling OpenRouter API...")
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Sauravyadav15/AnangAI",
                    "X-Title": "Kingston City Guide RAG System"
                },
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.6
                }
            )
            
            print(f"Response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"❌ Error: {response.status_code}")
                print(f"Response: {response.text}")
                
                # Provide helpful error messages
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", "Unknown error")
                except:
                    error_msg = response.text[:200] if response.text else "Unknown error"
                
                if response.status_code == 401:
                    return f"❌ API Authentication Error: {error_msg}. The OpenRouter API key is invalid or expired. Please:\n1. Get a new API key from https://openrouter.ai/keys\n2. Create a .env file in the backend folder with: OPENROUTER_API_KEY=your_key_here\n3. Or update the OPENROUTER_API_KEY in router.py"
                elif response.status_code == 429:
                    return "❌ Rate limit exceeded. Please try again in a moment."
                elif response.status_code >= 500:
                    return "❌ OpenRouter API is temporarily unavailable. Please try again later."
                else:
                    return f"❌ API Error ({response.status_code}): {error_msg}"
            
            result = response.json()
            print(f"✅ API Response received")
            
            if "choices" not in result:
                print(f"⚠️ Unexpected response structure:")
                print(result)
                return None
            
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not answer:
                print("⚠️ No content in response:")
                print(result)
            
            # Clean up the response formatting
            answer = clean_response_formatting(answer)
            
            return answer
            
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    question = "i wanna visit some place nearby water famous in this city and want to eat some japanese food"
    print(f"\n🔍 Question: {question}")
    print("=" * 50)
    
    answer = ask(question)
    
    if answer:
        print("\n✅ ANSWER:")
        print("=" * 50)
        print(answer)
    else:
        print("\n❌ No answer received.")
