
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os
import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "popote.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "CHANGE-MOI-AVANT-MISE-EN-LIGNE")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("APP_ENV", "").lower() == "production"
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox").lower()
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "")
PAYPAL_API_BASE = "https://api-m.paypal.com" if PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        price_cents INTEGER NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS consumptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    );

    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        note TEXT,
        method TEXT NOT NULL DEFAULT 'manual',
        paypal_order_id TEXT UNIQUE,
        paypal_capture_id TEXT UNIQUE,
        status TEXT NOT NULL DEFAULT 'completed',
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    db.commit()

    # Petites migrations pour une base créée avec la V1.
    product_cols = {row["name"] for row in db.execute("PRAGMA table_info(products)").fetchall()}
    if "stock" not in product_cols:
        db.execute("ALTER TABLE products ADD COLUMN stock INTEGER NOT NULL DEFAULT 0")
        db.commit()

    cols = {row["name"] for row in db.execute("PRAGMA table_info(payments)").fetchall()}
    for col, sql_type, default in [
        ("method", "TEXT", "'manual'"),
        ("paypal_order_id", "TEXT", "NULL"),
        ("paypal_capture_id", "TEXT", "NULL"),
        ("status", "TEXT", "'completed'"),
    ]:
        if col not in cols:
            db.execute(f"ALTER TABLE payments ADD COLUMN {col} {sql_type} DEFAULT {default}")
    db.commit()

    admin = db.execute("SELECT id FROM users WHERE is_admin = 1 LIMIT 1").fetchone()
    if not admin:
        db.execute(
            "INSERT INTO users (name, password_hash, is_admin) VALUES (?, ?, 1)",
            ("popotier", generate_password_hash("ChangeMoi123!"))
        )
        db.commit()
    db.close()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        db.close()
        if not user or not user["is_admin"]:
            flash("Accès réservé au gestionnaire.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped

def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    db.close()
    return user

def user_balance_cents(user_id):
    db = get_db()
    spent = db.execute(
        "SELECT COALESCE(SUM(price_cents), 0) AS total FROM consumptions WHERE user_id = ?",
        (user_id,)
    ).fetchone()["total"]
    paid = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payments WHERE user_id = ?",
        (user_id,)
    ).fetchone()["total"]
    db.close()
    return spent - paid


def paypal_configured():
    return bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET)

def paypal_access_token():
    if not paypal_configured():
        raise RuntimeError("PayPal n'est pas configuré.")
    response = requests.post(
        f"{PAYPAL_API_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]

def paypal_headers():
    return {
        "Authorization": f"Bearer {paypal_access_token()}",
        "Content-Type": "application/json",
    }

@app.context_processor
def inject_helpers():
    return {
        "current_user": current_user(),
        "format_eur": lambda cents: f"{cents/100:.2f} €".replace(".", ","),
        "paypal_client_id": PAYPAL_CLIENT_ID,
        "paypal_mode": PAYPAL_MODE,
    }

@app.route("/health")
def health():
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db.close()
        return {"status": "ok"}, 200
    except Exception:
        return {"status": "error"}, 500

@app.route("/")
def index():
    return redirect(url_for("dashboard" if "user_id" in session else "login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        password = request.form["password"]
        if len(name) < 2:
            flash("Nom trop court.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Le mot de passe doit faire au moins 6 caractères.", "error")
            return render_template("register.html")

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (name, password_hash) VALUES (?, ?)",
                (name, generate_password_hash(password))
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.close()
            flash("Ce nom est déjà utilisé.", "error")
            return render_template("register.html")
        db.close()
        flash("Compte créé. Tu peux te connecter.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form["name"].strip()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE name = ? AND active = 1", (name,)).fetchone()
        db.close()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Identifiants incorrects.", "error")
            return render_template("login.html")
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("admin" if user["is_admin"] else "dashboard"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    db = get_db()
    products = db.execute("SELECT * FROM products WHERE active = 1 AND stock > 0 ORDER BY name").fetchall()
    history = db.execute("""
        SELECT product_name, price_cents, created_at
        FROM consumptions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
    """, (user["id"],)).fetchall()
    db.close()
    balance = user_balance_cents(user["id"])
    return render_template("dashboard.html", products=products, history=history, balance=balance)

@app.post("/consume/<int:product_id>")
@login_required
def consume(product_id):
    user = current_user()
    db = get_db()

    # Verrou logique : on vérifie et décrémente dans la même transaction.
    product = db.execute(
        "SELECT * FROM products WHERE id = ? AND active = 1 AND stock > 0",
        (product_id,)
    ).fetchone()

    if not product:
        db.close()
        flash("Cette boisson est indisponible.", "error")
        return redirect(url_for("dashboard"))

    db.execute("""
        INSERT INTO consumptions (user_id, product_id, product_name, price_cents)
        VALUES (?, ?, ?, ?)
    """, (user["id"], product["id"], product["name"], product["price_cents"]))

    new_stock = product["stock"] - 1
    db.execute(
        "UPDATE products SET stock = ?, active = CASE WHEN ? <= 0 THEN 0 ELSE active END WHERE id = ?",
        (new_stock, new_stock, product["id"])
    )
    db.commit()
    db.close()

    if new_stock <= 0:
        flash(f"{product['name']} ajouté. Stock épuisé : produit maintenant indisponible.", "success")
    else:
        flash(f"{product['name']} ajouté à ton ardoise. Stock restant : {new_stock}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/pay")
@login_required
def pay():
    user = current_user()
    if user["is_admin"]:
        return redirect(url_for("admin"))
    balance = user_balance_cents(user["id"])
    return render_template(
        "pay.html",
        balance=balance,
        paypal_ready=paypal_configured(),
        paypal_client_id=PAYPAL_CLIENT_ID,
        paypal_mode=PAYPAL_MODE,
    )

@app.post("/api/paypal/orders")
@login_required
def paypal_create_order():
    user = current_user()
    if user["is_admin"]:
        return {"error": "Compte administrateur non autorisé."}, 403
    if not paypal_configured():
        return {"error": "PayPal n'est pas encore configuré."}, 503

    data = request.get_json(silent=True) or {}
    try:
        amount_cents = int(data.get("amount_cents", 0))
    except (TypeError, ValueError):
        return {"error": "Montant invalide."}, 400

    balance = user_balance_cents(user["id"])
    if amount_cents <= 0 or amount_cents > balance:
        return {"error": "Le montant doit être supérieur à 0 et ne peut pas dépasser l'ardoise."}, 400

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"user-{user['id']}",
            "custom_id": str(user["id"]),
            "description": f"Règlement Popote Bravo - {user['name']}",
            "amount": {
                "currency_code": "EUR",
                "value": f"{amount_cents / 100:.2f}"
            }
        }]
    }
    try:
        r = requests.post(
            f"{PAYPAL_API_BASE}/v2/checkout/orders",
            headers=paypal_headers(),
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException:
        return {"error": "Impossible de créer le paiement PayPal."}, 502

    order = r.json()
    return {"id": order["id"]}

@app.post("/api/paypal/orders/<order_id>/capture")
@login_required
def paypal_capture_order(order_id):
    user = current_user()
    if user["is_admin"]:
        return {"error": "Compte administrateur non autorisé."}, 403
    if not paypal_configured():
        return {"error": "PayPal n'est pas encore configuré."}, 503

    try:
        r = requests.post(
            f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
            headers=paypal_headers(),
            json={},
            timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException:
        return {"error": "La confirmation PayPal a échoué."}, 502

    result = r.json()
    if result.get("status") != "COMPLETED":
        return {"error": "Le paiement n'est pas confirmé.", "status": result.get("status")}, 400

    try:
        unit = result["purchase_units"][0]
        capture = unit["payments"]["captures"][0]
        capture_id = capture["id"]
        amount = capture["amount"]
        if amount["currency_code"] != "EUR":
            return {"error": "Devise PayPal inattendue."}, 400
        amount_cents = int(round(float(amount["value"]) * 100))
        custom_id = unit.get("custom_id")
    except (KeyError, IndexError, TypeError, ValueError):
        return {"error": "Réponse PayPal invalide."}, 502

    if str(user["id"]) != str(custom_id):
        return {"error": "Ce paiement ne correspond pas à ce compte."}, 403

    db = get_db()
    exists = db.execute(
        "SELECT id FROM payments WHERE paypal_capture_id = ? OR paypal_order_id = ?",
        (capture_id, order_id)
    ).fetchone()
    if not exists:
        current_balance = user_balance_cents(user["id"])
        # Empêche une déduction supérieure à la dette en cas de changements simultanés.
        if amount_cents > current_balance:
            db.close()
            return {"error": "Le paiement dépasse maintenant le montant restant dû. Contacte le popotier."}, 409

        db.execute("""
            INSERT INTO payments
            (user_id, amount_cents, note, method, paypal_order_id, paypal_capture_id, status)
            VALUES (?, ?, ?, 'paypal', ?, ?, 'completed')
        """, (
            user["id"],
            amount_cents,
            "Paiement PayPal confirmé",
            order_id,
            capture_id,
        ))
        db.commit()
    db.close()

    return {
        "ok": True,
        "amount_cents": amount_cents,
        "new_balance_cents": user_balance_cents(user["id"]),
        "capture_id": capture_id
    }

@app.post("/api/paypal/webhook")
def paypal_webhook():
    """
    Filet de sécurité pour la production.
    Configure PAYPAL_WEBHOOK_ID et abonne au minimum PAYMENT.CAPTURE.COMPLETED.
    La signature est vérifiée auprès de PayPal avant tout traitement.
    """
    if not paypal_configured() or not PAYPAL_WEBHOOK_ID:
        return "", 503

    event = request.get_json(silent=True)
    if not event:
        return "", 400

    verification_payload = {
        "auth_algo": request.headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": request.headers.get("PAYPAL-CERT-URL"),
        "transmission_id": request.headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": request.headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": request.headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": PAYPAL_WEBHOOK_ID,
        "webhook_event": event,
    }

    try:
        vr = requests.post(
            f"{PAYPAL_API_BASE}/v1/notifications/verify-webhook-signature",
            headers=paypal_headers(),
            json=verification_payload,
            timeout=15,
        )
        vr.raise_for_status()
        if vr.json().get("verification_status") != "SUCCESS":
            return "", 400
    except requests.RequestException:
        return "", 502

    if event.get("event_type") == "PAYMENT.CAPTURE.COMPLETED":
        resource = event.get("resource", {})
        capture_id = resource.get("id")
        custom_id = resource.get("custom_id")
        amount = resource.get("amount", {})
        supplementary = resource.get("supplementary_data", {})
        related = supplementary.get("related_ids", {})
        order_id = related.get("order_id")

        try:
            user_id = int(custom_id)
            if amount.get("currency_code") != "EUR":
                return "", 200
            amount_cents = int(round(float(amount["value"]) * 100))
        except (TypeError, ValueError, KeyError):
            return "", 200

        db = get_db()
        exists = db.execute(
            "SELECT id FROM payments WHERE paypal_capture_id = ?",
            (capture_id,)
        ).fetchone()
        user_exists = db.execute(
            "SELECT id FROM users WHERE id = ? AND is_admin = 0",
            (user_id,)
        ).fetchone()

        if not exists and user_exists:
            db.execute("""
                INSERT INTO payments
                (user_id, amount_cents, note, method, paypal_order_id, paypal_capture_id, status)
                VALUES (?, ?, ?, 'paypal', ?, ?, 'completed')
            """, (
                user_id,
                amount_cents,
                "Paiement PayPal confirmé par webhook",
                order_id,
                capture_id,
            ))
            db.commit()
        db.close()

    return "", 200

@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    members = db.execute("""
        SELECT u.id, u.name, u.active,
               COALESCE((SELECT SUM(c.price_cents) FROM consumptions c WHERE c.user_id = u.id), 0) AS spent,
               COALESCE((SELECT SUM(p.amount_cents) FROM payments p WHERE p.user_id = u.id), 0) AS paid
        FROM users u
        WHERE u.is_admin = 0
        ORDER BY u.name
    """).fetchall()
    products = db.execute("SELECT * FROM products ORDER BY active DESC, name").fetchall()
    db.close()
    total_due = sum((m["spent"] - m["paid"]) for m in members)
    return render_template("admin.html", members=members, products=products, total_due=total_due)

@app.post("/admin/products/add")
@admin_required
def add_product():
    name = request.form["name"].strip()
    try:
        price_cents = int(round(float(request.form["price"].replace(",", ".")) * 100))
        stock = int(request.form.get("stock", "0"))
    except ValueError:
        flash("Prix ou stock invalide.", "error")
        return redirect(url_for("admin"))

    if not name or price_cents < 0 or stock < 0:
        flash("Produit invalide.", "error")
        return redirect(url_for("admin"))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO products (name, price_cents, stock, active) VALUES (?, ?, ?, ?)",
            (name, price_cents, stock, 1 if stock > 0 else 0)
        )
        db.commit()
        flash("Boisson ajoutée.", "success")
    except sqlite3.IntegrityError:
        flash("Une boisson avec ce nom existe déjà.", "error")
    db.close()
    return redirect(url_for("admin"))

@app.post("/admin/products/<int:product_id>/edit")
@admin_required
def edit_product(product_id):
    name = request.form["name"].strip()
    requested_active = 1 if request.form.get("active") == "on" else 0

    try:
        price_cents = int(round(float(request.form["price"].replace(",", ".")) * 100))
        stock = int(request.form.get("stock", "0"))
    except ValueError:
        flash("Prix ou stock invalide.", "error")
        return redirect(url_for("admin"))

    if stock < 0:
        flash("Le stock ne peut pas être négatif.", "error")
        return redirect(url_for("admin"))

    active = requested_active if stock > 0 else 0

    db = get_db()
    try:
        db.execute(
            "UPDATE products SET name = ?, price_cents = ?, stock = ?, active = ? WHERE id = ?",
            (name, price_cents, stock, active, product_id)
        )
        db.commit()
        flash("Produit mis à jour.", "success")
    except sqlite3.IntegrityError:
        flash("Ce nom de produit existe déjà.", "error")
    db.close()
    return redirect(url_for("admin"))


@app.post("/admin/products/<int:product_id>/restock")
@admin_required
def restock_product(product_id):
    try:
        quantity = int(request.form["quantity"])
    except (KeyError, ValueError):
        flash("Quantité invalide.", "error")
        return redirect(url_for("admin"))

    if quantity <= 0:
        flash("La quantité doit être supérieure à 0.", "error")
        return redirect(url_for("admin"))

    db = get_db()
    product = db.execute(
        "SELECT id, name, stock FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if not product:
        db.close()
        flash("Produit introuvable.", "error")
        return redirect(url_for("admin"))

    new_stock = product["stock"] + quantity
    db.execute(
        "UPDATE products SET stock = ?, active = 1 WHERE id = ?",
        (new_stock, product_id)
    )
    db.commit()
    db.close()

    flash(f"{product['name']} réapprovisionné : +{quantity}. Nouveau stock : {new_stock}.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/payments/<int:user_id>")
@admin_required
def add_payment(user_id):
    try:
        amount_cents = int(round(float(request.form["amount"].replace(",", ".")) * 100))
    except ValueError:
        flash("Montant invalide.", "error")
        return redirect(request.referrer or url_for("admin"))

    if amount_cents <= 0:
        flash("Le paiement doit être supérieur à 0 €.", "error")
        return redirect(request.referrer or url_for("admin"))

    method = request.form.get("method", "manual").strip().lower()
    allowed_methods = {"cash", "transfer", "paypal_manual", "other", "manual"}
    if method not in allowed_methods:
        method = "manual"

    note = request.form.get("note", "").strip()

    db = get_db()
    user = db.execute(
        "SELECT id, name FROM users WHERE id = ? AND is_admin = 0 AND active = 1",
        (user_id,)
    ).fetchone()

    if not user:
        db.close()
        flash("Membre introuvable.", "error")
        return redirect(request.referrer or url_for("admin"))

    db.execute(
        "INSERT INTO payments (user_id, amount_cents, note, method, status) VALUES (?, ?, ?, ?, 'completed')",
        (user_id, amount_cents, note, method)
    )
    db.commit()
    db.close()

    flash(f"Paiement de {amount_cents/100:.2f} € enregistré pour {user['name']}.", "success")
    return redirect(request.referrer or url_for("admin"))


@app.post("/admin/payments/add")
@admin_required
def add_payment_global():
    try:
        user_id = int(request.form["user_id"])
        amount_cents = int(round(float(request.form["amount"].replace(",", ".")) * 100))
    except (KeyError, ValueError):
        flash("Sélectionne un membre et saisis un montant valide.", "error")
        return redirect(url_for("admin"))

    if amount_cents <= 0:
        flash("Le paiement doit être supérieur à 0 €.", "error")
        return redirect(url_for("admin"))

    method = request.form.get("method", "cash").strip().lower()
    if method not in {"cash", "transfer", "paypal_manual", "other"}:
        method = "other"

    note = request.form.get("note", "").strip()

    db = get_db()
    user = db.execute(
        "SELECT id, name FROM users WHERE id = ? AND is_admin = 0 AND active = 1",
        (user_id,)
    ).fetchone()

    if not user:
        db.close()
        flash("Membre introuvable.", "error")
        return redirect(url_for("admin"))

    db.execute(
        "INSERT INTO payments (user_id, amount_cents, note, method, status) VALUES (?, ?, ?, ?, 'completed')",
        (user_id, amount_cents, note, method)
    )
    db.commit()
    db.close()

    flash(f"Paiement de {amount_cents/100:.2f} € enregistré pour {user['name']}.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/member/<int:user_id>")
@admin_required
def member_detail(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ? AND is_admin = 0", (user_id,)).fetchone()
    if not user:
        db.close()
        flash("Membre introuvable.", "error")
        return redirect(url_for("admin"))
    consumptions = db.execute(
        "SELECT * FROM consumptions WHERE user_id = ? ORDER BY id DESC", (user_id,)
    ).fetchall()
    payments = db.execute(
        "SELECT * FROM payments WHERE user_id = ? ORDER BY id DESC", (user_id,)
    ).fetchall()
    db.close()
    return render_template(
        "member_detail.html",
        member=user,
        consumptions=consumptions,
        payments=payments,
        balance=user_balance_cents(user_id)
    )

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("APP_ENV") != "production")
