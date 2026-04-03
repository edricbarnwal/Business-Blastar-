from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_from_directory, jsonify,
)
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import config

# ── App setup ────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ── MongoDB ──────────────────────────────────────────────
client = MongoClient(config.MONGO_URI)
db = client[config.DATABASE_NAME]
businesses = db[config.COLLECTION_NAME]
counters   = db[config.COUNTERS_COLLECTION]
shops_col  = db["business_shops"]
people_col = db["business_people"]

# ── Helpers ──────────────────────────────────────────────
IMAGES_DIR = config.IMAGES_DIR


def allowed_file(filename: str) -> bool:
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────────────────
#  Business ID helpers
# ─────────────────────────────────────────────────────────

def get_next_bsd_id() -> str:
    """Find the first available gap in BSD IDs."""
    existing_ids = businesses.distinct("business_id")
    existing_nums = set()
    for bid in existing_ids:
        if bid and bid.upper().startswith("BSD"):
            try:
                existing_nums.add(int(bid[3:]))
            except ValueError:
                continue
    next_num = 1
    while next_num in existing_nums:
        next_num += 1
    return f"BSD{next_num:03d}"


def get_next_shp_id() -> str:
    """Find the first available gap in SHP IDs."""
    existing_ids = shops_col.distinct("shop_id")
    existing_nums = set()
    for sid in existing_ids:
        if sid and sid.upper().startswith("SHP"):
            try:
                existing_nums.add(int(sid[3:]))
            except ValueError:
                continue
    next_num = 1
    while next_num in existing_nums:
        next_num += 1
    return f"SHP{next_num:03d}"


def get_next_per_id() -> str:
    """Find the first available gap in PER IDs."""
    existing_ids = people_col.distinct("person_id")
    existing_nums = set()
    for pid in existing_ids:
        if pid and pid.upper().startswith("PER"):
            try:
                existing_nums.add(int(pid[3:]))
            except ValueError:
                continue
    next_num = 1
    while next_num in existing_nums:
        next_num += 1
    return f"PER{next_num:03d}"


# ── Migrations ───────────────────────────────────────────

def _migrate_legacy_records():
    legacy = list(businesses.find({"business_id": {"$exists": False}}).sort("_id", 1))
    for doc in legacy:
        bsd_id = get_next_bsd_id()
        businesses.update_one(
            {"_id": doc["_id"]},
            {"$set": {"business_id": bsd_id}, "$unset": {"id": ""}},
        )


def _migrate_single_to_array():
    """Convert legacy single email/contact strings to arrays."""
    for doc in businesses.find():
        updates = {}
        if "email" in doc and not isinstance(doc.get("email"), list):
            val = doc["email"]
            updates["emails"] = [val] if val else []
            unsets = {"email": ""}
        else:
            unsets = {}
        if "contact" in doc and not isinstance(doc.get("contact"), list):
            val = doc["contact"]
            updates["contacts"] = [val] if val else []
            unsets["contact"] = ""
        if updates:
            op = {"$set": updates}
            if unsets:
                op["$unset"] = unsets
            businesses.update_one({"_id": doc["_id"]}, op)


_migrate_legacy_records()
_migrate_single_to_array()


# ══════════════════════════════════════════════════════════
#  BUSINESS ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Home / landing page."""
    total_biz   = businesses.count_documents({})
    total_shops = shops_col.count_documents({})
    return render_template("home.html", total_biz=total_biz, total_shops=total_shops)


@app.route("/directory")
def directory():
    """Business directory — card grid."""
    query = request.args.get("q", "").strip()

    mongo_filter = {}
    if query:
        mongo_filter["$or"] = [
            {"name":        {"$regex": query, "$options": "i"}},
            {"emails":      {"$regex": query, "$options": "i"}},
            {"contacts":    {"$regex": query, "$options": "i"}},
            {"location":    {"$regex": query, "$options": "i"}},
            {"business_id": {"$regex": query, "$options": "i"}},
            {"person.name": {"$regex": query, "$options": "i"}},
        ]

    biz_list = list(businesses.find(mongo_filter).sort("business_id", 1))
    for b in biz_list:
        b.pop("_id", None)

    return render_template(
        "index.html",
        businesses=biz_list,
        query=query,
    )


@app.route("/insert", methods=["GET", "POST"])
def insert():
    """Insert a new business."""
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        emails   = [e.strip() for e in request.form.getlist("emails[]")   if e.strip()]
        contacts = [c.strip() for c in request.form.getlist("contacts[]") if c.strip()]
        website  = request.form.get("website",  "").strip()
        biz_type = request.form.get("type",     "").strip()
        location = request.form.get("location", "").strip()

        if not name:
            flash("Company name is required.", "error")
            return redirect(url_for("insert"))

        bsd_id = get_next_bsd_id()

        logo_filename = ""
        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename and allowed_file(logo_file.filename):
            ext = logo_file.filename.rsplit(".", 1)[1].lower()
            logo_filename = f"{bsd_id}.{ext}"
            logo_file.save(os.path.join(IMAGES_DIR, logo_filename))

        person_image_filename = ""
        person_image = request.files.get("person_image")
        if person_image and person_image.filename and allowed_file(person_image.filename):
            ext = person_image.filename.rsplit(".", 1)[1].lower()
            person_image_filename = f"{bsd_id}_person.{ext}"
            person_image.save(os.path.join(IMAGES_DIR, person_image_filename))

        new_business = {
            "business_id": bsd_id,
            "name":        name,
            "emails":      emails,
            "contacts":    contacts,
            "website":     website,
            "type":        biz_type,
            "location":    location,
            "logo":        logo_filename,
            "person": {
                "name":  request.form.get("person_name",  "").strip(),
                "title": request.form.get("person_title", "").strip(),
                "email": request.form.get("person_email", "").strip(),
                "image": person_image_filename,
            },
            "created_at": datetime.now().isoformat(),
        }
        businesses.insert_one(new_business)
        flash(f"Business '{name}' added as {bsd_id}!", "success")
        return redirect(url_for("directory"))

    return render_template("insert.html")


@app.route("/business/<bsd_id>")
def business_detail(bsd_id):
    """Full profile page for a single business."""
    biz = businesses.find_one({"business_id": bsd_id})
    if not biz:
        flash("Business not found.", "error")
        return redirect(url_for("directory"))
    biz.pop("_id", None)
    
    # Fetch connected people
    people = list(people_col.find({"business_id": bsd_id}).sort("created_at", -1))
    for p in people:
        p.pop("_id", None)
        
    return render_template("detail.html", biz=biz, people=people)


@app.route("/business/<bsd_id>/update", methods=["GET", "POST"])
def update_business(bsd_id):
    """Edit an existing business record."""
    biz = businesses.find_one({"business_id": bsd_id})
    if not biz:
        flash("Business not found.", "error")
        return redirect(url_for("directory"))

    if request.method == "POST":
        emails   = [e.strip() for e in request.form.getlist("emails[]")   if e.strip()]
        contacts = [c.strip() for c in request.form.getlist("contacts[]") if c.strip()]

        person_image_filename = biz.get("person", {}).get("image", "")
        person_image = request.files.get("person_image")
        if person_image and person_image.filename and allowed_file(person_image.filename):
            if person_image_filename:
                old_path = os.path.join(IMAGES_DIR, person_image_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            ext = person_image.filename.rsplit(".", 1)[1].lower()
            person_image_filename = f"{bsd_id}_person.{ext}"
            person_image.save(os.path.join(IMAGES_DIR, person_image_filename))

        updates = {
            "name":     request.form.get("name",     "").strip(),
            "emails":   emails,
            "contacts": contacts,
            "website":  request.form.get("website",  "").strip(),
            "type":     request.form.get("type",     "").strip(),
            "location": request.form.get("location", "").strip(),
            "person": {
                "name":  request.form.get("person_name",  "").strip(),
                "title": request.form.get("person_title", "").strip(),
                "email": request.form.get("person_email", "").strip(),
                "image": person_image_filename,
            },
            "updated_at": datetime.now().isoformat(),
        }

        if not updates["name"]:
            flash("Company name is required.", "error")
            return redirect(url_for("update_business", bsd_id=bsd_id))

        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename and allowed_file(logo_file.filename):
            if biz.get("logo"):
                old_path = os.path.join(IMAGES_DIR, biz["logo"])
                if os.path.exists(old_path):
                    os.remove(old_path)
            ext = logo_file.filename.rsplit(".", 1)[1].lower()
            logo_filename = f"{bsd_id}.{ext}"
            logo_file.save(os.path.join(IMAGES_DIR, logo_filename))
            updates["logo"] = logo_filename

        businesses.update_one({"business_id": bsd_id}, {"$set": updates})
        flash(f"Business '{updates['name']}' updated successfully!", "success")
        return redirect(url_for("business_detail", bsd_id=bsd_id))

    biz.pop("_id", None)
    return render_template("update.html", biz=biz)


@app.route("/business/<bsd_id>/delete", methods=["POST"])
def delete_business(bsd_id):
    """Delete a business and its logo."""
    biz = businesses.find_one({"business_id": bsd_id})
    if not biz:
        flash("Business not found.", "error")
        return redirect(url_for("directory"))
    if biz.get("logo"):
        logo_path = os.path.join(IMAGES_DIR, biz["logo"])
        if os.path.exists(logo_path):
            os.remove(logo_path)
    businesses.delete_one({"business_id": bsd_id})
    flash(f"Business {bsd_id} deleted.", "success")
    return redirect(url_for("directory"))


# ══════════════════════════════════════════════════════════
#  PEOPLE ROUTES  (collection: business_people)
# ══════════════════════════════════════════════════════════

@app.route("/people")
def people_directory():
    """Directory of all business people."""
    query = request.args.get("q", "").strip()

    mongo_filter = {}
    if query:
        mongo_filter["$or"] = [
            {"name": {"$regex": query, "$options": "i"}},
            {"title": {"$regex": query, "$options": "i"}},
            {"email": {"$regex": query, "$options": "i"}},
            {"linkedin": {"$regex": query, "$options": "i"}},
            {"contact": {"$regex": query, "$options": "i"}},
            {"business_name": {"$regex": query, "$options": "i"}},
        ]

    people_list = list(people_col.find(mongo_filter).sort("created_at", -1))
    for p in people_list:
        p.pop("_id", None)

    return render_template("people/index.html", people=people_list, query=query)


@app.route("/business/<bsd_id>/add_person", methods=["POST"])
def add_person(bsd_id):
    """Add a new person to a business."""
    biz = businesses.find_one({"business_id": bsd_id})
    if not biz:
        flash("Business not found.", "error")
        return redirect(url_for("directory"))
        
    name = request.form.get("person_name", "").strip()
    title = request.form.get("person_title", "").strip()
    email = request.form.get("person_email", "").strip()
    contact = request.form.get("person_contact", "").strip()
    linkedin = request.form.get("person_linkedin", "").strip()

    if not name:
        flash("Person name is required.", "error")
        return redirect(url_for("business_detail", bsd_id=bsd_id))

    per_id = get_next_per_id()

    image_filename = ""
    person_image = request.files.get("person_image")
    if person_image and person_image.filename and allowed_file(person_image.filename):
        ext = person_image.filename.rsplit(".", 1)[1].lower()
        image_filename = f"{per_id}.{ext}"
        person_image.save(os.path.join(IMAGES_DIR, image_filename))

    new_person = {
        "person_id": per_id,
        "business_id": bsd_id,
        "business_name": biz.get("name", ""),
        "business_logo": biz.get("logo", ""),
        "name": name,
        "title": title,
        "email": email,
        "contact": contact,
        "linkedin": linkedin,
        "image": image_filename,
        "created_at": datetime.now().isoformat(),
    }
    people_col.insert_one(new_person)
    flash(f"Person '{name}' added successfully!", "success")
    return redirect(url_for("business_detail", bsd_id=bsd_id))


@app.route("/people/<per_id>/delete", methods=["POST"])
def delete_person(per_id):
    """Delete a person."""
    person = people_col.find_one({"person_id": per_id})
    if not person:
        flash("Person not found.", "error")
        return redirect(url_for("people_directory"))
        
    bsd_id = person.get("business_id")
    
    if person.get("image"):
        img_path = os.path.join(IMAGES_DIR, person["image"])
        if os.path.exists(img_path):
            os.remove(img_path)
            
    people_col.delete_one({"person_id": per_id})
    flash(f"Person {person.get('name', per_id)} deleted.", "success")
    
    referrer = request.referrer
    if referrer and f"/business/{bsd_id}" in referrer:
        return redirect(url_for("business_detail", bsd_id=bsd_id))
    return redirect(url_for("people_directory"))


# ══════════════════════════════════════════════════════════
#  SHOPS ROUTES  (collection: business_shops)
# ══════════════════════════════════════════════════════════

@app.route("/shops")
def shops():
    """Shops directory — card grid."""
    query = request.args.get("q", "").strip()

    mongo_filter = {}
    if query:
        mongo_filter["$or"] = [
            {"name":     {"$regex": query, "$options": "i"}},
            {"shop_id":  {"$regex": query, "$options": "i"}},
            {"location": {"$regex": query, "$options": "i"}},
            {"emails":   {"$regex": query, "$options": "i"}},
        ]

    shop_list = list(shops_col.find(mongo_filter).sort("shop_id", 1))
    for s in shop_list:
        s.pop("_id", None)

    return render_template("shops/index.html", shops=shop_list, query=query)


@app.route("/shops/insert", methods=["GET", "POST"])
def shops_insert():
    """Insert a new shop."""
    if request.method == "POST":
        name     = request.form.get("name",     "").strip()
        emails   = [e.strip() for e in request.form.getlist("emails[]")   if e.strip()]
        contacts = [c.strip() for c in request.form.getlist("contacts[]") if c.strip()]
        website  = request.form.get("website",  "").strip()
        location = request.form.get("location", "").strip()
        category = request.form.get("category", "").strip()

        if not name:
            flash("Shop name is required.", "error")
            return redirect(url_for("shops_insert"))

        shp_id = get_next_shp_id()

        logo_filename = ""
        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename and allowed_file(logo_file.filename):
            ext = logo_file.filename.rsplit(".", 1)[1].lower()
            logo_filename = f"{shp_id}.{ext}"
            logo_file.save(os.path.join(IMAGES_DIR, logo_filename))

        new_shop = {
            "shop_id":  shp_id,
            "name":     name,
            "emails":   emails,
            "contacts": contacts,
            "website":  website,
            "location": location,
            "category": category,
            "logo":     logo_filename,
            "created_at": datetime.now().isoformat(),
        }
        shops_col.insert_one(new_shop)
        flash(f"Shop '{name}' added as {shp_id}!", "success")
        return redirect(url_for("shops"))

    return render_template("shops/insert.html")


@app.route("/shops/<shp_id>")
def shop_detail(shp_id):
    """Full profile page for a single shop."""
    shop = shops_col.find_one({"shop_id": shp_id})
    if not shop:
        flash("Shop not found.", "error")
        return redirect(url_for("shops"))
    shop.pop("_id", None)
    return render_template("shops/detail.html", shop=shop)


@app.route("/shops/<shp_id>/update", methods=["GET", "POST"])
def shop_update(shp_id):
    """Edit an existing shop record."""
    shop = shops_col.find_one({"shop_id": shp_id})
    if not shop:
        flash("Shop not found.", "error")
        return redirect(url_for("shops"))

    if request.method == "POST":
        emails   = [e.strip() for e in request.form.getlist("emails[]")   if e.strip()]
        contacts = [c.strip() for c in request.form.getlist("contacts[]") if c.strip()]

        updates = {
            "name":     request.form.get("name",     "").strip(),
            "emails":   emails,
            "contacts": contacts,
            "website":  request.form.get("website",  "").strip(),
            "location": request.form.get("location", "").strip(),
            "category": request.form.get("category", "").strip(),
            "updated_at": datetime.now().isoformat(),
        }

        if not updates["name"]:
            flash("Shop name is required.", "error")
            return redirect(url_for("shop_update", shp_id=shp_id))

        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename and allowed_file(logo_file.filename):
            if shop.get("logo"):
                old_path = os.path.join(IMAGES_DIR, shop["logo"])
                if os.path.exists(old_path):
                    os.remove(old_path)
            ext = logo_file.filename.rsplit(".", 1)[1].lower()
            logo_filename = f"{shp_id}.{ext}"
            logo_file.save(os.path.join(IMAGES_DIR, logo_filename))
            updates["logo"] = logo_filename

        shops_col.update_one({"shop_id": shp_id}, {"$set": updates})
        flash(f"Shop '{updates['name']}' updated successfully!", "success")
        return redirect(url_for("shop_detail", shp_id=shp_id))

    shop.pop("_id", None)
    return render_template("shops/update.html", shop=shop)


@app.route("/shops/<shp_id>/delete", methods=["POST"])
def shop_delete(shp_id):
    """Delete a shop."""
    shop = shops_col.find_one({"shop_id": shp_id})
    if not shop:
        flash("Shop not found.", "error")
        return redirect(url_for("shops"))
    if shop.get("logo"):
        logo_path = os.path.join(IMAGES_DIR, shop["logo"])
        if os.path.exists(logo_path):
            os.remove(logo_path)
    shops_col.delete_one({"shop_id": shp_id})
    flash(f"Shop {shp_id} deleted.", "success")
    return redirect(url_for("shops"))


# ── Images ───────────────────────────────────────────────

@app.route("/images/<path:filename>")
def serve_image(filename):
    """Serve images from the shared Images directory."""
    return send_from_directory(IMAGES_DIR, filename)


# ── Run ──────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)
