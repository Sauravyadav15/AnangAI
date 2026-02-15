"""
AnangAI Civic Portal API - applications.txt (Get Featured) + Admin-only auth.
"""
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from router import ask, discover_data_files, load_data, split_food_entries, split_place_entries, split_shops_entries, parse_food_entry, parse_place_entry, parse_shop_entry, parse_event_entry

app = FastAPI(title="AnangAI Civic Portal API")

# Hardcoded Admin credentials (backend check only). In production use env vars.
# List of (email_lower, password) that can access Founder's Portal.
ADMINS = [
    ("admin@anangai.com", "anang_admin_2024"),
    ("saurav@gmail.com", "saurav@qhacks"),
]
ADMIN_TOKEN = "anang_founder_portal_token"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|.*\.vercel\.app)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.txt"
# Get Featured submissions (name, email, business, status, etc.):
APP_PATH = BASE_DIR / "applications.txt"
# Uploaded license/identity documents from applications:
UPLOADS_DIR = BASE_DIR / "uploads"
PASSWORD_SALT = "anang_ai_partner_2024"

UPLOADS_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


def hash_password(password: str) -> str:
    return hashlib.sha256((PASSWORD_SALT + (password or "")).encode()).hexdigest()


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        return hash_password(password) == stored
    return (password or "") == stored


class LoginBody(BaseModel):
    email: str
    password: str


class RegisterBody(BaseModel):
    username: str = ""
    email: str
    password: str
    businessName: str = ""
    businessType: str = ""
    businessDescription: str = ""
    contact: str = ""


class ChatRequest(BaseModel):
    question: str
    language: str = "en"  # Language code: "en" for English, "fr" for French


class ApplicationIdBody(BaseModel):
    """Body for admin application approve/reject: id or email."""
    id: str | None = None
    email: str | None = None


def load_db():
    if not DB_PATH.exists():
        return {"users": []}
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_user_by_email(email: str):
    data = load_db()
    for u in data.get("users", []):
        if u.get("email") == email:
            return u, data
    return None, data


def load_applications():
    if not APP_PATH.exists():
        return {"applications": []}
    with open(APP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_applications(data):
    with open(APP_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_application_by_email(email: str):
    data = load_applications()
    email_lower = (email or "").strip().lower()
    for a in data.get("applications", []):
        if (a.get("email") or "").strip().lower() == email_lower:
            return a, data
    return None, data


def require_admin(authorization: str | None = Header(None)):
    """Dependency: require valid admin token in Authorization: Bearer <token>."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    token = authorization.replace("Bearer ", "").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True


def ensure_user(email: str, data: dict):
    users = data.get("users", [])
    for i, u in enumerate(users):
        if u.get("email") == email:
            return i, users
    users.append({
        "email": email,
        "password": "",
        "name": "",
        "progress": 1,
        "is_verified": False,
        "business_name": "",
        "business_description": "",
        "category": "",
        "address": "",
    })
    return len(users) - 1, users


# Allowed category_file values (file stems under Food/)
FEATURED_CATEGORY_FILES = {"bakeries", "breweries_pubs", "cafés_coffee_shops", "ice_cream_gelato", "restaurants", "shops"}
FOOD_DIR = BASE_DIR / "Food"


@app.post("/api/submit-application")
async def submit_application(
    name: str = Form(""),
    email: str = Form(...),
    contact: str = Form(""),
    category_file: str = Form(""),
    # Food fields
    businessName: str = Form(""),
    location: str = Form(""),
    hours: str = Form(""),
    localSourcing: str = Form(""),
    vegVegan: str = Form(""),
    greenPlateCert: str = Form(""),
    notes: str = Form(""),
    # Shops fields
    storeName: str = Form(""),
    hoursOperation: str = Form(""),
    info: str = Form(""),
    shopCategory: str = Form(""),
    # Legacy (keep for backward compat)
    businessType: str = Form(""),
    businessDescription: str = Form(""),
    license_file: UploadFile = File(None),
):
    """
    Public "Get Featured" submission. Saves ALL form data to applications.txt with status pending.
    applications.txt is the single source of truth for every Get Featured submission.
    On admin approve, selective data from this record is appended to the respective Food/*.txt file
    (e.g. shops -> shops.txt, restaurants -> restaurants.txt) using that file's required schema.
    """
    email = (email or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    cat = (category_file or "").strip()
    if cat and cat not in FEATURED_CATEGORY_FILES:
        raise HTTPException(status_code=400, detail="Invalid category")
    if not cat:
        raise HTTPException(status_code=400, detail="Category is required")
    apps_data = load_applications()
    for a in apps_data.get("applications", []):
        if (a.get("email") or "").strip().lower() == email.lower():
            raise HTTPException(status_code=409, detail="An application for this email already exists.")
    license_url = ""
    safe_email = email.replace("@", "_").replace(".", "_")
    if license_file and license_file.filename:
        suffix = Path(license_file.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"License file: allowed types {', '.join(ALLOWED_EXTENSIONS)}")
        dest_name = f"license_{safe_email}_{uuid.uuid4().hex[:8]}{suffix}"
        dest_path = UPLOADS_DIR / dest_name
        try:
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(license_file.file, f)
        except Exception as e:
            raise HTTPException(500, f"Save failed: {e}")
        license_url = dest_name
    # Display name: store name or business name
    biz_name = (storeName or businessName or "").strip() or (businessType or "").strip()
    app_id = str(uuid.uuid4())
    apps = apps_data.get("applications", [])
    # Store ALL data from Get Featured form so admin can review and we can append to Food/*.txt on approve
    apps.append({
        "id": app_id,
        "name": (name or "").strip(),
        "email": email,
        "contact": (contact or "").strip(),
        "category_file": cat,
        "biz_name": biz_name,
        "biz_cat": cat.replace("_", " ").title(),
        "biz_desc": (businessDescription or notes or info or "").strip(),
        "license_url": license_url,
        "status": "pending",
        # Food categories (restaurants, bakeries, cafes, breweries_pubs, ice_cream_gelato)
        "businessName": (businessName or "").strip(),
        "location": (location or "").strip(),
        "hours": (hours or "").strip(),
        "local_sourcing": (localSourcing or "").strip(),
        "veg_vegan": (vegVegan or "").strip(),
        "green_plate_cert": (greenPlateCert or "").strip() or "null",
        "notes": (notes or "").strip(),
        # Shops only
        "store_name": (storeName or "").strip(),
        "hours_operation": (hoursOperation or "").strip(),
        "info": (info or "").strip(),
        "shop_category": (shopCategory or "").strip(),
        # Legacy form fields (keep so we store everything from the page)
        "businessType": (businessType or "").strip(),
        "businessDescription": (businessDescription or "").strip(),
    })
    apps_data["applications"] = apps
    save_applications(apps_data)
    return {"id": app_id, "email": email, "message": "Application submitted. You will hear from admin@anangai.com regarding verification."}


# ---------- Admin (Founder's Portal) ----------
@app.post("/api/admin/login")
def admin_login(body: LoginBody):
    """Hardcoded admin auth. Returns token for use in Authorization header."""
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if (email, password) not in ADMINS:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return {"token": ADMIN_TOKEN}


@app.get("/api/admin/applications")
def admin_list_applications(_: bool = Depends(require_admin)):
    """Return all applications from applications.txt (admin only)."""
    data = load_applications()
    return data


def _find_application(data, app_id: str | None, email: str | None):
    """Return (index, app) or (None, None)."""
    apps = data.get("applications", [])
    email_lower = (email or "").strip().lower()
    for i, a in enumerate(apps):
        if app_id and a.get("id") == app_id:
            return i, a
        if email_lower and (a.get("email") or "").strip().lower() == email_lower:
            return i, a
    return None, None


def _append_application_to_food_file(app: dict) -> None:
    """
    On approve: read selective data from the application (saved in applications.txt)
    and append one entry to the correct Food/*.txt file using that file's exact schema.
    - shops -> shops.txt: Store Name, Location, Hours of Operation, Info, Category, ---
    - restaurants/bakeries/cafes/etc. -> Business Name, Location, Hours, Local Sourcing,
      Veg/Vegan Options, Green Plate Certification, Notes
    """
    cat_file = (app.get("category_file") or "").strip()
    if not cat_file or cat_file not in FEATURED_CATEGORY_FILES:
        return
    path = FOOD_DIR / f"{cat_file}.txt"
    if not path.exists():
        return
    # Require at least a name so we don't append empty entries (e.g. old applications)
    entry_name = (app.get("store_name") or app.get("biz_name") or app.get("businessName") or "").strip()
    if not entry_name:
        return
    if cat_file == "shops":
        # Exact schema required by shops.txt
        lines = [
            "",
            "Store Name: " + entry_name,
            "Location: " + (app.get("location") or ""),
            "Hours of Operation: " + (app.get("hours_operation") or app.get("hours") or ""),
            "Info: " + (app.get("info") or ""),
            "Category: " + (app.get("shop_category") or ""),
            "---",
        ]
    else:
        # Exact schema required by restaurants.txt, bakeries.txt, etc.
        lines = [
            "",
            "Business Name: " + entry_name,
            "Location: " + (app.get("location") or ""),
            "Hours: " + (app.get("hours") or app.get("hours_operation") or ""),
            "Local Sourcing: " + (app.get("local_sourcing") or ""),
            "Veg/Vegan Options: " + (app.get("veg_vegan") or ""),
            "Green Plate Certification: " + (app.get("green_plate_cert") or "null"),
            "Notes: " + (app.get("notes") or app.get("info") or ""),
        ]
    block = "\n".join(lines)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
    except Exception:
        pass


@app.post("/api/admin/applications/approve")
def admin_approve_application(body: ApplicationIdBody, _: bool = Depends(require_admin)):
    """Set application status to approved (admin only). Appends entry to the category Food/*.txt file."""
    app_id = (body.id or "").strip() or None
    email = (body.email or "").strip() or None
    if not app_id and not email:
        raise HTTPException(status_code=400, detail="Application id or email required")
    data = load_applications()
    i, a = _find_application(data, app_id, email)
    if i is None:
        raise HTTPException(status_code=404, detail="Application not found")
    a["status"] = "approved"
    _append_application_to_food_file(a)
    save_applications(data)
    return {"id": a.get("id"), "status": "approved"}


@app.post("/api/admin/applications/reject")
def admin_reject_application(body: ApplicationIdBody, _: bool = Depends(require_admin)):
    """Set application status to rejected (admin only). Body: { "id": "..." } or { "email": "..." }."""
    app_id = (body.id or "").strip() or None
    email = (body.email or "").strip() or None
    if not app_id and not email:
        raise HTTPException(status_code=400, detail="Application id or email required")
    data = load_applications()
    i, a = _find_application(data, app_id, email)
    if i is None:
        raise HTTPException(status_code=404, detail="Application not found")
    a["status"] = "rejected"
    save_applications(data)
    return {"id": a.get("id"), "status": "rejected"}


@app.get("/api/uploads/{filename}")
def serve_upload(filename: str):
    """Serve an uploaded file (e.g. license document). Filename must be safe (no path traversal)."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = UPLOADS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


@app.post("/api/finalize-account")
def finalize_account(body: LoginBody):
    """
    Create auth account: email + password. Email must exist in applications.txt.
    Saves to database.txt with hashed_password, role=partner, is_verified=false.
    Email is stored and matched lowercase.
    """
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    app_record, _ = get_application_by_email(email)
    if not app_record:
        raise HTTPException(status_code=400, detail="Please submit your business details first.")
    data = load_db()
    for u in data.get("users", []):
        if (u.get("email") or "").strip().lower() == email:
            raise HTTPException(status_code=409, detail="Account already exists. Please log in.")
    users = data.get("users", [])
    users.append({
        "email": email,
        "hashed_password": hash_password(password),
        "role": "partner",
        "is_verified": False,
        "progress": 1,
        "name": email.split("@")[0],
    })
    data["users"] = users
    save_db(data)
    return {
        "email": email,
        "business_name": app_record.get("biz_name", ""),
        "name": email.split("@")[0],
        "progress": 1,
        "status": "approved",
        "is_verified": False,
    }


@app.get("/api/dashboard-data/{email}")
def dashboard_data(email: str):
    """
    JOIN database.txt (auth) + applications.txt (business). Returns merged object.
    """
    email = email.strip()
    user, _ = get_user_by_email(email)
    app_record, _ = get_application_by_email(email)
    auth = {
        "email": email,
        "progress": 1,
        "is_verified": False,
        "status": "approved",
    }
    if user:
        auth["progress"] = user.get("progress", 1)
        auth["is_verified"] = user.get("is_verified", False)
        auth["status"] = user.get("status") or ("approved" if user.get("is_verified") else "pending_review")
    business = {
        "biz_name": "",
        "biz_cat": "",
        "biz_desc": "",
        "license_url": "",
        "status": "pending",
    }
    if app_record:
        business["biz_name"] = app_record.get("biz_name", "")
        business["biz_cat"] = app_record.get("biz_cat", "")
        business["biz_desc"] = app_record.get("biz_desc", "")
        business["license_url"] = app_record.get("license_url", "")
        business["status"] = app_record.get("status", "pending")
    return {"auth": auth, "business": business}


@app.post("/api/register")
async def register(
    username: str = Form(""),
    email: str = Form(...),
    password: str = Form(""),
    businessName: str = Form(""),
    businessType: str = Form(""),
    businessDescription: str = Form(""),
    contact: str = Form(""),
    drivers_license: UploadFile = File(None),
):
    """
    Legacy: full partner application (kept for backward compat). Prefer submit-application + finalize-account.
    """
    data = load_db()
    email = (email or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    for u in data.get("users", []):
        if u.get("email") == email:
            raise HTTPException(status_code=409, detail="Email already registered. Please log in.")
    safe_email = email.replace("@", "_").replace(".", "_")
    if drivers_license and drivers_license.filename:
        suffix = Path(drivers_license.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Driver's license: allowed types {', '.join(ALLOWED_EXTENSIONS)}")
        dest_name = f"drivers_license_{safe_email}{suffix}"
        dest_path = UPLOADS_DIR / dest_name
        try:
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(drivers_license.file, f)
        except Exception as e:
            raise HTTPException(500, f"Save failed: {e}")
    users = data.get("users", [])
    users.append({
        "email": email,
        "password": password or "",
        "name": (username or "").strip() or email.split("@")[0],
        "progress": 1,
        "is_verified": False,
        "business_name": (businessName or "").strip(),
        "business_description": (businessDescription or "").strip(),
        "category": (businessType or "").strip(),
        "address": (contact or "").strip(),
    })
    data["users"] = users
    save_db(data)
    return {"email": email, "message": "Application received. Our team is verifying your local status."}


@app.post("/api/signup")
def signup(body: LoginBody):
    """
    Simple sign up: email + password. Saves to database.txt with hashed_password.
    If email already exists, returns 409. Email is stored lowercase.
    """
    data = load_db()
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    for u in data.get("users", []):
        if (u.get("email") or "").strip().lower() == email:
            raise HTTPException(status_code=409, detail="Email already registered. Please log in.")
    name = email.split("@")[0]
    users = data.get("users", [])
    users.append({
        "email": email,
        "hashed_password": hash_password(password),
        "name": name,
        "progress": 1,
        "is_verified": False,
        "status": "approved",
    })
    data["users"] = users
    save_db(data)
    return {
        "email": email,
        "business_name": "",
        "name": name,
        "progress": 1,
        "status": "approved",
        "is_verified": False,
    }


@app.post("/api/login")
def login(body: LoginBody):
    """
    Authenticate by email and password. Checks hashed_password (new) or password (legacy).
    On success returns user object with business_name from application if available.
    Email comparison is case-insensitive so "User@Mail.com" matches "user@mail.com".
    """
    data = load_db()
    email = (body.email or "").strip()
    email_lower = email.lower()
    password = body.password or ""
    for u in data.get("users", []):
        if (u.get("email") or "").strip().lower() != email_lower:
            continue
        stored = u.get("hashed_password") or u.get("password") or ""
        if not verify_password(password, stored):
            continue
        app_record, _ = get_application_by_email(email)
        biz_name = ((app_record or {}).get("biz_name") or u.get("business_name") or "").strip()
        status = u.get("status") or ("approved" if u.get("is_verified") else "pending_review")
        return {
            "email": u.get("email", ""),
            "business_name": biz_name,
            "name": u.get("name", "") or email.split("@")[0],
            "progress": u.get("progress", 1),
            "status": status,
            "is_verified": u.get("is_verified", False),
        }
    raise HTTPException(status_code=401, detail="Invalid credentials")


def _user_status(u):
    return u.get("status") or ("approved" if u.get("is_verified") else "pending_review")


@app.get("/api/user")
def get_user(email: str = Query(..., description="User email")):
    """Get current user progress and verification status."""
    user, _ = get_user_by_email(email)
    if not user:
        return {"email": email, "progress": 1, "is_verified": False, "status": "pending_review"}
    out = dict(user)
    out["status"] = _user_status(user)
    return out


@app.get("/api/admin/pending")
def admin_pending():
    """Return all users with status == 'pending_review' (admin gate)."""
    data = load_db()
    pending = [
        {**u, "status": u.get("status") or "pending_review"}
        for u in data.get("users", [])
        if (u.get("status") or ("approved" if u.get("is_verified") else "pending_review")) == "pending_review"
    ]
    return {"users": pending}


class AdminActionBody(BaseModel):
    email: str


@app.post("/api/admin/approve")
def admin_approve(body: AdminActionBody):
    """Set user to status=approved and is_verified=true."""
    email = (body.email or "").strip()
    if not email:
        raise HTTPException(400, detail="Email is required")
    user, data = get_user_by_email(email)
    if not user:
        raise HTTPException(404, detail="User not found")
    users = data.get("users", [])
    i = next(idx for idx, u in enumerate(users) if u.get("email") == email)
    users[i]["status"] = "approved"
    users[i]["is_verified"] = True
    data["users"] = users
    save_db(data)
    return {"email": email, "status": "approved", "is_verified": True}


@app.post("/api/admin/reject")
def admin_reject(body: AdminActionBody):
    """Mark user as rejected (kept for audit; optionally filter from login)."""
    email = (body.email or "").strip()
    if not email:
        raise HTTPException(400, detail="Email is required")
    user, data = get_user_by_email(email)
    if not user:
        raise HTTPException(404, detail="User not found")
    users = data.get("users", [])
    i = next(idx for idx, u in enumerate(users) if u.get("email") == email)
    users[i]["status"] = "rejected"
    data["users"] = users
    save_db(data)
    return {"email": email, "status": "rejected"}


class ProgressBody(BaseModel):
    step: int | None = None  # If set, progress = max(current, step). Otherwise increment.


@app.patch("/api/user/progress")
def update_progress(
    email: str = Query(..., description="User email"),
    body: ProgressBody = Body(default=ProgressBody()),
):
    """
    Update user's progress. If body.step is provided: set progress = max(current, step).
    Otherwise increment by 1. Step 7 is completed when license is uploaded.
    """
    user, data = get_user_by_email(email)
    if not user:
        i, users = ensure_user(email, data)
        user = users[i]
    else:
        users = data.get("users", [])
        i = next(idx for idx, u in enumerate(users) if u.get("email") == email)

    current = user.get("progress", 1)
    if current >= 7:
        return {"email": email, "progress": 7, "is_verified": user.get("is_verified", False)}
    if body and body.step is not None:
        new_progress = max(current, min(7, body.step))
    else:
        new_progress = current + 1
    users[i]["progress"] = new_progress
    data["users"] = users
    save_db(data)
    return {"email": email, "progress": users[i]["progress"], "is_verified": user.get("is_verified", False)}


@app.get("/api/businesses")
def list_businesses(category: str | None = Query(None, description="Optional category filter")):
    """Return only verified businesses. Joins database (is_verified) + applications (biz_name, etc)."""
    data = load_db()
    verified = []
    for u in data.get("users", []):
        if not u.get("is_verified"):
            continue
        email = u.get("email", "")
        app_record, _ = get_application_by_email(email)
        name = (app_record.get("biz_name") or u.get("business_name") or "Unnamed").strip() or "Unnamed"
        desc = (app_record.get("biz_desc") or u.get("business_description") or "").strip()
        cat = (app_record.get("biz_cat") or u.get("category") or "Other").strip() or "Other"
        verified.append({
            "id": email.replace("@", "_").replace(".", "_"),
            "name": name,
            "description": desc,
            "category": cat,
            "address": u.get("address") or "",
            "sustainability": "",
            "live": False,
        })
    if category:
        verified = [b for b in verified if b["category"].lower() == category.lower()]
    return {"businesses": verified}


@app.post("/api/upload-license")
async def upload_license(
    file: UploadFile = File(...),
    email: str = Form(...),
):
    """
    Upload license document. Saves file; updates applications.txt (license_url) and database.txt (is_verified).
    """
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Allowed types: {', '.join(ALLOWED_EXTENSIONS)}")

    email = email.strip()
    safe_email = email.replace("@", "_").replace(".", "_")
    dest_name = f"license_{safe_email}{suffix}"
    dest_path = UPLOADS_DIR / dest_name

    try:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Save failed: {e}")

    app_record, app_data = get_application_by_email(email)
    if app_record:
        apps = app_data.get("applications", [])
        i = next(idx for idx, a in enumerate(apps) if a.get("email") == email)
        apps[i]["license_url"] = dest_name
        apps[i]["status"] = "approved"
        app_data["applications"] = apps
        save_applications(app_data)

    user, data = get_user_by_email(email)
    if not user:
        i, users = ensure_user(email, data)
        user = users[i]
    else:
        users = data.get("users", [])
        i = next(idx for idx, u in enumerate(users) if u.get("email") == email)

    users[i]["is_verified"] = True
    users[i]["progress"] = 7
    data["users"] = users
    save_db(data)

    return {
        "email": email,
        "progress": 7,
        "is_verified": True,
        "filename": dest_name,
    }


@app.post("/api/chat")
def chat_endpoint(request: ChatRequest):
    """
    Chat endpoint that uses RAG to answer questions about Kingston.
    Uses the ask() function from router.py to generate responses.
    """
    try:
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question cannot be empty")
        
        language = request.language or "en"  # Default to English
        answer = ask(question, language)
        
        if answer is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate response. Please check backend logs."
            )
        
        return {"answer": answer, "question": question}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/discovery/categories")
def get_discovery_categories():
    """
    Get all available data file categories for the discovery page.
    Returns a list of categories with their file names and display names.
    """
    try:
        data_files = discover_data_files()
        categories = []
        
        # Food categories
        for file_path in data_files["food"]:
            file_name = file_path.stem
            display_name = file_name.replace("_", " ").title()
            categories.append({
                "id": file_name,
                "label": display_name,
                "type": "food",
                "file": file_path.name
            })
        
        # Places categories
        for file_path in data_files["places"]:
            file_name = file_path.stem
            display_name = file_name.replace("_", " ").title()
            categories.append({
                "id": file_name,
                "label": display_name,
                "type": "places",
                "file": file_path.name
            })
        
        # Events categories
        for file_path in data_files["events"]:
            file_name = file_path.stem
            display_name = file_name.replace("_", " ").title()
            categories.append({
                "id": file_name,
                "label": display_name,
                "type": "events",
                "file": file_path.name
            })
        
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load categories: {str(e)}")


@app.get("/api/discovery/data")
def get_discovery_data(category_id: str = Query(..., description="Category ID (file name without extension)")):
    """
    Get all entries from a specific data file.
    Returns parsed entries ready for display.
    """
    try:
        data_files = discover_data_files()
        BASE_DIR = Path(__file__).resolve().parent
        
        # Find the file
        found_file = None
        file_type = None
        
        for file_path in data_files["food"]:
            if file_path.stem == category_id:
                found_file = file_path
                file_type = "food"
                break
        
        if not found_file:
            for file_path in data_files["places"]:
                if file_path.stem == category_id:
                    found_file = file_path
                    file_type = "places"
                    break
        
        if not found_file:
            for file_path in data_files["events"]:
                if file_path.stem == category_id:
                    found_file = file_path
                    file_type = "events"
                    break
        
        if not found_file:
            raise HTTPException(status_code=404, detail=f"Category '{category_id}' not found")
        
        # Load and parse the file
        content = load_data(found_file)
        if not content:
            return {"entries": []}
        
        entries = []
        
        if file_type == "food":
            if category_id == "shops":
                entry_texts = split_shops_entries(content)
                for entry_text in entry_texts:
                    entry = parse_shop_entry(entry_text)
                    if entry.get("name"):
                        entries.append(entry)
            else:
                entry_texts = split_food_entries(content)
                for entry_text in entry_texts:
                    entry = parse_food_entry(entry_text)
                    if entry.get("name"):
                        entries.append(entry)
        elif file_type == "places":
            entry_texts = split_place_entries(content)
            for entry_text in entry_texts:
                entry = parse_place_entry(entry_text)
                if entry.get("name"):
                    entries.append(entry)
        elif file_type == "events":
            lines = content.strip().split('\n')
            for line in lines:
                if line.strip() and '|' in line:
                    entry = parse_event_entry(line)
                    if entry and entry.get("name"):
                        entries.append(entry)
        
        return {"entries": entries, "category": category_id, "type": file_type}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load data: {str(e)}")


@app.get("/api/health")
def health():
    return {"status": "ok"}
