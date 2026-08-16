
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
from io import BytesIO
import os
import requests
import qrcode
import uuid
import json
from pywebpush import webpush, WebPushException

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
PAYPAL_ME_URL = os.getenv("PAYPAL_ME_URL", "https://paypal.me/PopoteBellac").rstrip("/")
PAYPAL_API_BASE = "https://api-m.paypal.com" if PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@popote-bravo.local")

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
        low_stock_threshold INTEGER NOT NULL DEFAULT 5,
        category TEXT NOT NULL DEFAULT 'Boisson',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS consumptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        order_id TEXT,
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

    CREATE TABLE IF NOT EXISTS manual_debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL,
        note TEXT,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS payment_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL,
        method TEXT NOT NULL DEFAULT 'paypal',
        note TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        decided_at TEXT,
        decided_by INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(decided_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'info',
        link TEXT,
        dedupe_key TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        user_agent TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS monthly_ranking_notifications (
        month_key TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(month_key, user_id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    db.commit()

    # Petites migrations pour une base créée avec la V1.
    consumption_cols = {row["name"] for row in db.execute("PRAGMA table_info(consumptions)").fetchall()}
    if "order_id" not in consumption_cols:
        db.execute("ALTER TABLE consumptions ADD COLUMN order_id TEXT")
        db.commit()

    product_cols = {row["name"] for row in db.execute("PRAGMA table_info(products)").fetchall()}
    if "stock" not in product_cols:
        db.execute("ALTER TABLE products ADD COLUMN stock INTEGER NOT NULL DEFAULT 0")
        db.commit()
    if "low_stock_threshold" not in product_cols:
        db.execute("ALTER TABLE products ADD COLUMN low_stock_threshold INTEGER NOT NULL DEFAULT 5")
        db.commit()
    if "category" not in product_cols:
        db.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Boisson'")
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

init_db()

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
    manual_debts = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM manual_debts WHERE user_id = ?",
        (user_id,)
    ).fetchone()["total"]
    paid = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payments WHERE user_id = ?",
        (user_id,)
    ).fetchone()["total"]
    db.close()
    return spent + manual_debts - paid


def add_notification(db, user_id, title, message, kind="info", link=None, dedupe_key=None):
    if dedupe_key:
        existing = db.execute(
            "SELECT id FROM notifications WHERE user_id = ? AND dedupe_key = ? AND is_read = 0 LIMIT 1",
            (user_id, dedupe_key)
        ).fetchone()
        if existing:
            return
    db.execute("""
        INSERT INTO notifications (user_id, title, message, kind, link, dedupe_key)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, title, message, kind, link, dedupe_key))


def notify_admins(db, title, message, kind="warning", link="/admin/stock", dedupe_key=None):
    admins = db.execute("SELECT id FROM users WHERE is_admin = 1 AND active = 1").fetchall()
    for admin in admins:
        key = f"{dedupe_key}:{admin['id']}" if dedupe_key else None
        add_notification(db, admin["id"], title, message, kind, link, key)




def notify_member_debt_added(user_id, amount_cents, note=None):
    """Push envoyé lorsqu'un Popotier ajoute manuellement une dette."""
    amount = f"{amount_cents/100:.2f} €".replace(".", ",")
    body = f"Le Popotier a ajouté {amount} à ton ardoise."
    if note:
        body += f" Motif : {note}"
    send_push_to_user(
        user_id,
        "🧾 Nouvelle dette",
        body,
        "/dashboard",
        f"debt-added-{user_id}-{int(datetime.now().timestamp())}"
    )


def notify_admins_stockout(product_name):
    """Push uniquement au passage réel d'un stock positif à zéro."""
    send_push_to_admins(
        "🔴 Rupture de stock",
        f"{product_name} vient de passer à 0.",
        "/admin/consumptions",
        f"stockout-{product_name}"
    )



def send_previous_month_ranking_notifications():
    """
    Envoie une seule fois le bilan du mois précédent.
    Le classement additionne consommations + dettes manuelles du Popotier.
    """
    now = datetime.now()
    first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_end = first_this_month

    if first_this_month.month == 1:
        previous_start = first_this_month.replace(
            year=first_this_month.year - 1,
            month=12
        )
    else:
        previous_start = first_this_month.replace(
            month=first_this_month.month - 1
        )

    month_key = previous_start.strftime("%Y-%m")
    month_names = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"
    ]
    month_label = month_names[previous_start.month - 1]

    start_txt = previous_start.strftime("%Y-%m-%d %H:%M:%S")
    end_txt = previous_end.strftime("%Y-%m-%d %H:%M:%S")

    db = get_db()
    rows = db.execute("""
        SELECT
            u.id,
            u.name,
            COALESCE((
                SELECT SUM(c.price_cents)
                FROM consumptions c
                WHERE c.user_id = u.id
                  AND c.created_at >= ?
                  AND c.created_at < ?
            ), 0)
            +
            COALESCE((
                SELECT SUM(md.amount_cents)
                FROM manual_debts md
                WHERE md.user_id = u.id
                  AND md.created_at >= ?
                  AND md.created_at < ?
            ), 0) AS total_cents
        FROM users u
        WHERE u.is_admin = 0 AND u.active = 1
        ORDER BY total_cents DESC, u.name COLLATE NOCASE
    """, (
        start_txt, end_txt,
        start_txt, end_txt
    )).fetchall()

    already = {
        row["user_id"] for row in db.execute(
            "SELECT user_id FROM monthly_ranking_notifications WHERE month_key = ?",
            (month_key,)
        ).fetchall()
    }
    db.close()

    for position, row in enumerate(rows, start=1):
        if row["id"] in already:
            continue

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(position, "🏆")
        total = f"{row['total_cents']/100:.2f} €".replace(".", ",")

        if position == 1:
            body = (
                f"Classement de {month_label} terminé — "
                f"tu termines 1er avec {total}."
            )
        else:
            body = (
                f"Classement de {month_label} terminé — "
                f"tu termines {position}e avec {total}."
            )

        send_push_to_user(
            row["id"],
            f"{medal} Classement de {month_label}",
            body,
            "/classement",
            f"ranking-{month_key}-{row['id']}"
        )

        db2 = get_db()
        db2.execute("""
            INSERT OR IGNORE INTO monthly_ranking_notifications (month_key, user_id)
            VALUES (?, ?)
        """, (month_key, row["id"]))
        db2.commit()
        db2.close()


def push_configured():
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and VAPID_SUBJECT)


def send_push_to_user(user_id, title, body, url="/", tag=None):
    if not push_configured():
        return 0

    db = get_db()
    subscriptions = db.execute("""
        SELECT id, endpoint, p256dh, auth
        FROM push_subscriptions
        WHERE user_id = ?
    """, (user_id,)).fetchall()

    sent = 0
    stale_ids = []

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag or "popote-bravo"
    }, ensure_ascii=False)

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"]
            }
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=300
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                stale_ids.append(sub["id"])
        except Exception:
            # Le push ne doit jamais bloquer l'action métier.
            pass

    for sub_id in stale_ids:
        db.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub_id,))
    if stale_ids:
        db.commit()
    db.close()
    return sent


def send_push_to_admins(title, body, url="/admin", tag=None):
    db = get_db()
    admins = db.execute(
        "SELECT id FROM users WHERE is_admin = 1 AND active = 1"
    ).fetchall()
    db.close()

    total = 0
    for admin in admins:
        total += send_push_to_user(admin["id"], title, body, url, tag)
    return total


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


def user_pending_claims_cents(user_id):
    db = get_db()
    total = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payment_claims WHERE user_id = ? AND status = 'pending'",
        (user_id,)
    ).fetchone()["total"]
    db.close()
    return total

@app.context_processor
def inject_helpers():
    user = current_user()
    unread_notifications = 0
    if user:
        db = get_db()
        unread_notifications = db.execute(
            "SELECT COUNT(*) AS total FROM notifications WHERE user_id = ? AND is_read = 0",
            (user["id"],)
        ).fetchone()["total"]
        db.close()

    return {
        "current_user": user,
        "format_eur": lambda cents: f"{cents/100:.2f} €".replace(".", ","),
        "paypal_client_id": PAYPAL_CLIENT_ID,
        "paypal_mode": PAYPAL_MODE,
        "unread_notifications": unread_notifications,
        "vapid_public_key": VAPID_PUBLIC_KEY,
        "push_configured": push_configured(),
    }






@app.before_request
def maybe_send_monthly_ranking_push():
    if datetime.now().day <= 3:
        try:
            send_previous_month_ranking_notifications()
        except Exception:
            # Une notification ne doit jamais empêcher l'utilisation de Popote Bravo.
            pass


@app.route("/sw.js")
def service_worker():
    response = app.send_static_file("sw.js")
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.post("/push/subscribe")
@login_required
def push_subscribe():
    user = current_user()
    data = request.get_json(silent=True) or {}

    endpoint = data.get("endpoint", "")
    keys = data.get("keys") or {}
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")

    if not endpoint or not p256dh or not auth:
        return {"ok": False, "error": "Abonnement push invalide."}, 400

    db = get_db()
    db.execute("""
        INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            user_id = excluded.user_id,
            p256dh = excluded.p256dh,
            auth = excluded.auth,
            user_agent = excluded.user_agent
    """, (
        user["id"], endpoint, p256dh, auth,
        request.headers.get("User-Agent", "")[:500]
    ))
    db.commit()
    db.close()

    return {"ok": True}


@app.post("/push/unsubscribe")
@login_required
def push_unsubscribe():
    user = current_user()
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")

    if endpoint:
        db = get_db()
        db.execute(
            "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
            (user["id"], endpoint)
        )
        db.commit()
        db.close()

    return {"ok": True}


@app.post("/push/test")
@login_required
def push_test():
    user = current_user()
    sent = send_push_to_user(
        user["id"],
        "Popote Bravo",
        "Les notifications téléphone fonctionnent ✅",
        "/notifications",
        "push-test"
    )
    if sent:
        return {"ok": True}
    return {"ok": False, "error": "Aucun appareil abonné ou Push non configuré."}, 400


@app.route("/notifications")
@login_required
def notifications():
    user = current_user()
    db = get_db()
    items = db.execute("""
        SELECT *
        FROM notifications
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 80
    """, (user["id"],)).fetchall()
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user["id"],))
    db.commit()
    db.close()
    return render_template("notifications.html", notifications=items)


@app.post("/notifications/clear")
@login_required
def clear_notifications():
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM notifications WHERE user_id = ?", (user["id"],))
    db.commit()
    db.close()
    flash("Notifications effacées.", "success")
    return redirect(url_for("notifications"))


@app.route("/classement")
@login_required
def classement():
    user = current_user()
    db = get_db()

    full_ranking = db.execute("""
        SELECT
            u.id,
            u.name,
            COALESCE((
                SELECT SUM(c.price_cents)
                FROM consumptions c
                WHERE c.user_id = u.id
                  AND strftime('%Y-%m', c.created_at) = strftime('%Y-%m', 'now')
            ), 0)
            +
            COALESCE((
                SELECT SUM(md.amount_cents)
                FROM manual_debts md
                WHERE md.user_id = u.id
                  AND strftime('%Y-%m', md.created_at) = strftime('%Y-%m', 'now')
            ), 0) AS total_cents
        FROM users u
        WHERE u.is_admin = 0 AND u.active = 1
        ORDER BY total_cents DESC, u.name COLLATE NOCASE
    """).fetchall()

    my_position = None
    my_total_cents = 0
    for position, row in enumerate(full_ranking, start=1):
        if row["id"] == user["id"]:
            my_position = position
            my_total_cents = row["total_cents"]
            break

    month_label = datetime.now().strftime("%m/%Y")
    db.close()

    return render_template(
        "classement.html",
        ranking=full_ranking,
        month_label=month_label,
        my_position=my_position,
        my_total_cents=my_total_cents,
    )

@app.route("/qr")
def qr_page():
    return render_template("qr.html", app_url=request.host_url.rstrip("/"))

@app.route("/qr.png")
def qr_image():
    target = request.host_url.rstrip("/") + "/"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(target)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png", max_age=300)

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


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = current_user()

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not check_password_hash(user["password_hash"], current_password):
            flash("Le mot de passe actuel est incorrect.", "error")
            return render_template("change_password.html")

        if len(new_password) < 8:
            flash("Le nouveau mot de passe doit faire au moins 8 caractères.", "error")
            return render_template("change_password.html")

        if new_password != confirm_password:
            flash("Les deux nouveaux mots de passe ne correspondent pas.", "error")
            return render_template("change_password.html")

        if check_password_hash(user["password_hash"], new_password):
            flash("Le nouveau mot de passe doit être différent de l'ancien.", "error")
            return render_template("change_password.html")

        db = get_db()
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user["id"])
        )
        db.commit()
        db.close()

        flash("Mot de passe modifié avec succès.", "success")
        return redirect(url_for("admin" if user["is_admin"] else "dashboard"))

    return render_template("change_password.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    db = get_db()

    # On conserve les ruptures visibles. Un produit désactivé manuellement avec du stock
    # reste masqué ; un produit à stock 0 reste visible en "Rupture".
    products = db.execute("""
        SELECT *
        FROM products
        WHERE active = 1 OR stock = 0
        ORDER BY category COLLATE NOCASE,
                 CASE WHEN stock = 0 THEN 1 ELSE 0 END,
                 name COLLATE NOCASE
    """).fetchall()

    raw_history = db.execute("""
        SELECT id, product_id, product_name, price_cents, order_id, created_at
        FROM consumptions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 120
    """, (user["id"],)).fetchall()

    # Regroupement par commande. Pour les anciennes consommations sans order_id,
    # les lignes enregistrées à la même seconde sont regroupées.
    grouped = []
    groups = {}
    order_sequence = []
    for row in raw_history:
        key = row["order_id"] or f"legacy:{row['created_at']}"
        if key not in groups:
            groups[key] = {
                "order_id": row["order_id"],
                "created_at": row["created_at"],
                "items": {},
                "total_cents": 0,
                "can_cancel": False,
            }
            order_sequence.append(key)

        item = groups[key]["items"].setdefault(
            row["product_name"],
            {"name": row["product_name"], "quantity": 0, "total_cents": 0}
        )
        item["quantity"] += 1
        item["total_cents"] += row["price_cents"]
        groups[key]["total_cents"] += row["price_cents"]

    for key in order_sequence[:20]:
        group = groups[key]
        group["items"] = list(group["items"].values())
        if group["order_id"]:
            can_cancel = db.execute("""
                SELECT CASE WHEN MIN(created_at) >= datetime('now', '-30 seconds') THEN 1 ELSE 0 END AS ok
                FROM consumptions
                WHERE user_id = ? AND order_id = ?
            """, (user["id"], group["order_id"])).fetchone()["ok"]
            group["can_cancel"] = bool(can_cancel)
        grouped.append(group)

    claims = db.execute("""
        SELECT id, amount_cents, method, note, status, created_at
        FROM payment_claims
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
    """, (user["id"],)).fetchall()

    month_spent = db.execute("""
        SELECT COALESCE(SUM(price_cents), 0) AS total
        FROM consumptions
        WHERE user_id = ?
          AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
    """, (user["id"],)).fetchone()["total"]

    pending_claim_count = db.execute("""
        SELECT COUNT(*) AS total
        FROM payment_claims
        WHERE user_id = ? AND status = 'pending'
    """, (user["id"],)).fetchone()["total"]

    last_order = None
    last_order_id = session.pop("last_order_id", None)
    if last_order_id:
        rows = db.execute("""
            SELECT product_name, COUNT(*) AS quantity,
                   SUM(price_cents) AS total_cents,
                   MIN(created_at) AS created_at
            FROM consumptions
            WHERE user_id = ? AND order_id = ?
            GROUP BY product_name
            ORDER BY product_name COLLATE NOCASE
        """, (user["id"], last_order_id)).fetchall()
        if rows:
            total = sum(r["total_cents"] for r in rows)
            can_cancel = db.execute("""
                SELECT CASE WHEN MIN(created_at) >= datetime('now', '-30 seconds') THEN 1 ELSE 0 END AS ok
                FROM consumptions WHERE user_id = ? AND order_id = ?
            """, (user["id"], last_order_id)).fetchone()["ok"]
            last_order = {
                "order_id": last_order_id,
                "items": rows,
                "total_cents": total,
                "can_cancel": bool(can_cancel),
            }

    db.close()

    balance = user_balance_cents(user["id"])
    pending_claims = user_pending_claims_cents(user["id"])
    estimated_balance = max(0, balance - pending_claims)

    return render_template(
        "dashboard.html",
        products=products,
        history_groups=grouped,
        claims=claims,
        balance=balance,
        pending_claims=pending_claims,
        pending_claim_count=pending_claim_count,
        estimated_balance=estimated_balance,
        month_spent=month_spent,
        last_order=last_order,
    )

@app.post("/consume/<int:product_id>")
@login_required
def consume(product_id):
    user = current_user()
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 1

    if quantity < 1:
        flash("Quantité invalide.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    product = db.execute(
        "SELECT * FROM products WHERE id = ? AND active = 1 AND stock > 0",
        (product_id,)
    ).fetchone()

    if not product or quantity > product["stock"]:
        available = product["stock"] if product else 0
        db.close()
        flash(f"Stock insuffisant : {available} disponible(s).", "error")
        return redirect(url_for("dashboard"))

    order_id = uuid.uuid4().hex
    for _ in range(quantity):
        db.execute("""
            INSERT INTO consumptions (user_id, product_id, product_name, price_cents, order_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user["id"], product["id"], product["name"], product["price_cents"], order_id))

    new_stock = product["stock"] - quantity
    db.execute(
        "UPDATE products SET stock = ?, active = CASE WHEN ? <= 0 THEN 0 ELSE active END WHERE id = ?",
        (new_stock, new_stock, product["id"])
    )

    became_out_of_stock = product["stock"] > 0 and new_stock == 0
    if became_out_of_stock:
        notify_admins(
            db,
            "Rupture de stock",
            f"{product['name']} : rupture de stock.",
            "danger",
            "/admin/stock",
            f"stock:{product['id']}:zero"
        )

    db.commit()
    db.close()

    if became_out_of_stock:
        notify_admins_stockout(product["name"])

    total_cents = product["price_cents"] * quantity
    session["last_order_id"] = order_id
    flash(
        f"✓ {quantity} × {product['name']} ajouté{'s' if quantity > 1 else ''} — "
        f"{total_cents / 100:.2f} €".replace(".", ","),
        "success"
    )
    return redirect(url_for("dashboard"))


@app.post("/cart/checkout")
@login_required
def cart_checkout():
    user = current_user()
    if user["is_admin"]:
        return redirect(url_for("admin"))

    requested = {}
    for key, value in request.form.items():
        if not key.startswith("qty_"):
            continue
        try:
            product_id = int(key.split("_", 1)[1])
            quantity = int(value)
        except (ValueError, IndexError):
            continue
        if quantity > 0:
            requested[product_id] = quantity

    if not requested:
        flash("Ton panier est vide.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    placeholders = ",".join("?" for _ in requested)
    products = db.execute(
        f"SELECT * FROM products WHERE id IN ({placeholders})",
        tuple(requested.keys())
    ).fetchall()
    product_map = {p["id"]: p for p in products}

    # Validation complète AVANT d'écrire quoi que ce soit.
    for product_id, quantity in requested.items():
        product = product_map.get(product_id)
        if not product or not product["active"] or product["stock"] <= 0:
            db.close()
            flash("Un produit du panier n'est plus disponible.", "error")
            return redirect(url_for("dashboard"))
        if quantity > product["stock"]:
            db.close()
            flash(
                f"Stock insuffisant pour {product['name']} : "
                f"{product['stock']} disponible(s).",
                "error"
            )
            return redirect(url_for("dashboard"))

    order_id = uuid.uuid4().hex
    total_cents = 0
    total_articles = 0
    summary = []
    stockouts = []

    for product_id, quantity in requested.items():
        product = product_map[product_id]
        for _ in range(quantity):
            db.execute("""
                INSERT INTO consumptions
                    (user_id, product_id, product_name, price_cents, order_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user["id"], product["id"], product["name"],
                product["price_cents"], order_id
            ))

        new_stock = product["stock"] - quantity
        db.execute(
            "UPDATE products SET stock = ?, active = CASE WHEN ? <= 0 THEN 0 ELSE active END WHERE id = ?",
            (new_stock, new_stock, product["id"])
        )

        if new_stock <= product["low_stock_threshold"]:
            title = "Rupture de stock" if new_stock == 0 else "Stock faible"
            notify_admins(
                db, title,
                f"{product['name']} : {new_stock} restant(s).",
                "danger" if new_stock == 0 else "warning",
                "/admin/stock",
                f"stock:{product['id']}:{'zero' if new_stock == 0 else 'low'}"
            )

        line_total = product["price_cents"] * quantity
        total_cents += line_total
        total_articles += quantity
        summary.append(f"{quantity} × {product['name']}")

    db.commit()
    db.close()

    for product_name in stockouts:
        notify_admins_stockout(product_name)

    session["last_order_id"] = order_id
    total_txt = f"{total_cents / 100:.2f}".replace(".", ",")
    flash(
        f"✓ {total_articles} article(s) ajouté(s) — {total_txt} €",
        "success"
    )
    return redirect(url_for("dashboard"))


@app.post("/orders/<order_id>/cancel")
@login_required
def cancel_order(order_id):
    user = current_user()
    db = get_db()

    rows = db.execute("""
        SELECT product_id, product_name, COUNT(*) AS quantity
        FROM consumptions
        WHERE user_id = ? AND order_id = ?
          AND created_at >= datetime('now', '-30 seconds')
        GROUP BY product_id, product_name
    """, (user["id"], order_id)).fetchall()

    total_rows = db.execute("""
        SELECT COUNT(*) AS total
        FROM consumptions
        WHERE user_id = ? AND order_id = ?
    """, (user["id"], order_id)).fetchone()["total"]

    eligible_rows = sum(r["quantity"] for r in rows)

    if total_rows == 0 or eligible_rows != total_rows:
        db.close()
        flash("Le délai de 30 secondes pour annuler cette commande est dépassé.", "error")
        return redirect(url_for("dashboard"))

    for row in rows:
        if row["product_id"] is not None:
            product = db.execute(
                "SELECT id, stock FROM products WHERE id = ?",
                (row["product_id"],)
            ).fetchone()
            if product:
                db.execute(
                    "UPDATE products SET stock = stock + ?, active = 1 WHERE id = ?",
                    (row["quantity"], row["product_id"])
                )

    db.execute(
        "DELETE FROM consumptions WHERE user_id = ? AND order_id = ?",
        (user["id"], order_id)
    )
    db.commit()
    db.close()

    flash("Commande annulée et stock restauré.", "success")
    return redirect(url_for("dashboard"))


@app.route("/declare-payment", methods=["GET", "POST"])
@login_required
def declare_payment():
    user = current_user()
    if user["is_admin"]:
        return redirect(url_for("admin"))

    official_balance = user_balance_cents(user["id"])
    pending_total = user_pending_claims_cents(user["id"])
    available = max(0, official_balance - pending_total)

    prefill_cents = 0
    try:
        if request.args.get("amount"):
            prefill_cents = int(round(float(request.args["amount"].replace(",", ".")) * 100))
    except ValueError:
        prefill_cents = 0
    if prefill_cents <= 0 or prefill_cents > available:
        prefill_cents = available

    if request.method == "POST":
        try:
            amount_cents = int(round(float(request.form["amount"].replace(",", ".")) * 100))
        except (KeyError, ValueError):
            flash("Montant invalide.", "error")
            return redirect(url_for("declare_payment"))

        note = request.form.get("note", "").strip()

        if amount_cents <= 0 or amount_cents > available:
            flash("Le montant déclaré est invalide.", "error")
            return redirect(url_for("declare_payment"))

        db = get_db()
        db.execute("""
            INSERT INTO payment_claims (user_id, amount_cents, method, note, status)
            VALUES (?, ?, 'paypal', ?, 'pending')
        """, (user["id"], amount_cents, note))
        db.commit()
        db.close()

        send_push_to_admins(
            "💳 Paiement à valider",
            f"{user['name']} déclare un paiement de {amount_cents/100:.2f} €.".replace(".", ","),
            "/admin",
            f"payment-claim-{user['id']}"
        )
        flash("Paiement déclaré : en attente de validation du popotier.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "declare_payment.html",
        official_balance=official_balance,
        pending_total=pending_total,
        available=available,
        prefill_cents=prefill_cents,
        paypal_me_url=PAYPAL_ME_URL
    )

@app.post("/admin/payment-claims/<int:claim_id>/approve")
@admin_required
def approve_payment_claim(claim_id):
    admin_user = current_user()
    db = get_db()
    claim = db.execute("""
        SELECT pc.*, u.name AS user_name
        FROM payment_claims pc JOIN users u ON u.id = pc.user_id
        WHERE pc.id = ?
    """, (claim_id,)).fetchone()

    if not claim or claim["status"] != "pending":
        db.close()
        flash("Déclaration introuvable ou déjà traitée.", "error")
        return redirect(url_for("admin"))

    spent = db.execute("SELECT COALESCE(SUM(price_cents),0) total FROM consumptions WHERE user_id=?",
                       (claim["user_id"],)).fetchone()["total"]
    paid = db.execute("SELECT COALESCE(SUM(amount_cents),0) total FROM payments WHERE user_id=?",
                      (claim["user_id"],)).fetchone()["total"]

    if claim["amount_cents"] > spent - paid:
        db.close()
        flash("Le montant dépasse la dette officielle restante.", "error")
        return redirect(url_for("admin"))

    note = "PayPal déclaré par le membre, validé par le popotier"
    if claim["note"]:
        note += " — " + claim["note"]

    db.execute("""INSERT INTO payments (user_id, amount_cents, note, method, status)
                  VALUES (?, ?, ?, 'paypal_manual', 'completed')""",
               (claim["user_id"], claim["amount_cents"], note))
    db.execute("""UPDATE payment_claims
                  SET status='approved', decided_at=CURRENT_TIMESTAMP, decided_by=?
                  WHERE id=?""", (admin_user["id"], claim_id))
    add_notification(
        db,
        claim["user_id"],
        "Paiement validé",
        f"Ton paiement de {claim['amount_cents']/100:.2f} € a été validé par le popotier.".replace(".", ","),
        "success",
        "/dashboard"
    )
    db.commit()
    send_push_to_user(
        claim["user_id"],
        "✅ Paiement validé",
        f"Ton paiement de {claim['amount_cents']/100:.2f} € a été validé.".replace(".", ","),
        "/dashboard",
        f"payment-approved-{claim_id}"
    )
    db.close()
    flash(f"Paiement de {claim['amount_cents']/100:.2f} € validé pour {claim['user_name']}.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/payment-claims/<int:claim_id>/reject")
@admin_required
def reject_payment_claim(claim_id):
    admin_user = current_user()
    db = get_db()
    claim = db.execute(
        "SELECT user_id, amount_cents, status FROM payment_claims WHERE id=?",
        (claim_id,)
    ).fetchone()
    if not claim or claim["status"] != "pending":
        db.close()
        flash("Déclaration introuvable ou déjà traitée.", "error")
        return redirect(url_for("admin"))

    db.execute("""UPDATE payment_claims
                  SET status='rejected', decided_at=CURRENT_TIMESTAMP, decided_by=?
                  WHERE id=?""", (admin_user["id"], claim_id))
    add_notification(
        db,
        claim["user_id"],
        "Paiement refusé",
        f"Ta déclaration de {claim['amount_cents']/100:.2f} € a été refusée. Vérifie le paiement avec le popotier.".replace(".", ","),
        "danger",
        "/dashboard"
    )
    db.commit()
    send_push_to_user(
        claim["user_id"],
        "❌ Paiement refusé",
        f"Ta déclaration de {claim['amount_cents']/100:.2f} € a été refusée.".replace(".", ","),
        "/dashboard",
        f"payment-rejected-{claim_id}"
    )
    db.close()
    flash("Déclaration refusée.", "success")
    return redirect(url_for("admin"))

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


@app.post("/consumptions/<int:consumption_id>/undo")
@login_required
def undo_consumption(consumption_id):
    user = current_user()
    if user["is_admin"]:
        return redirect(url_for("admin"))

    db = get_db()
    consumption = db.execute("""
        SELECT * FROM consumptions
        WHERE id = ? AND user_id = ?
          AND created_at >= datetime('now', '-30 seconds')
    """, (consumption_id, user["id"])).fetchone()

    if not consumption:
        db.close()
        flash("Le délai d'annulation est dépassé ou cette consommation n'existe plus.", "error")
        return redirect(url_for("dashboard"))

    if consumption["product_id"]:
        product = db.execute("SELECT stock FROM products WHERE id = ?", (consumption["product_id"],)).fetchone()
        if product:
            new_stock = product["stock"] + 1
            db.execute(
                "UPDATE products SET stock = ?, active = 1 WHERE id = ?",
                (new_stock, consumption["product_id"])
            )

    db.execute("DELETE FROM consumptions WHERE id = ?", (consumption_id,))
    db.commit()
    db.close()
    flash("Consommation annulée et stock restauré.", "success")
    return redirect(url_for("dashboard"))

@app.post("/admin/consumptions/<int:consumption_id>/delete")
@admin_required
def admin_delete_consumption(consumption_id):
    db = get_db()
    consumption = db.execute("SELECT * FROM consumptions WHERE id = ?", (consumption_id,)).fetchone()
    if not consumption:
        db.close()
        flash("Consommation introuvable.", "error")
        return redirect(url_for("admin"))

    user_id = consumption["user_id"]
    if consumption["product_id"]:
        product = db.execute("SELECT stock FROM products WHERE id = ?", (consumption["product_id"],)).fetchone()
        if product:
            new_stock = product["stock"] + 1
            db.execute(
                "UPDATE products SET stock = ?, active = 1 WHERE id = ?",
                (new_stock, consumption["product_id"])
            )

    db.execute("DELETE FROM consumptions WHERE id = ?", (consumption_id,))
    db.commit()
    db.close()
    flash("Consommation supprimée et stock restauré.", "success")
    return redirect(url_for("member_detail", user_id=user_id))



@app.route("/admin/comptes")
@admin_required
def admin_accounts():
    db = get_db()
    members = db.execute("""
        SELECT u.id, u.name, u.active,
               COALESCE((SELECT SUM(c.price_cents)
                         FROM consumptions c WHERE c.user_id = u.id), 0)
               + COALESCE((SELECT SUM(md.amount_cents)
                           FROM manual_debts md WHERE md.user_id = u.id), 0) AS spent,
               COALESCE((SELECT SUM(p.amount_cents)
                         FROM payments p WHERE p.user_id = u.id), 0) AS paid
        FROM users u
        WHERE u.is_admin = 0
        ORDER BY u.name COLLATE NOCASE
    """).fetchall()
    db.close()
    return render_template("admin_accounts.html", members=members)


@app.route("/admin/consommations")
@admin_required
def admin_consumptions():
    db = get_db()
    products = db.execute("""
        SELECT *
        FROM products
        ORDER BY active DESC, name COLLATE NOCASE
    """).fetchall()
    db.close()
    return render_template("admin_consumptions.html", products=products)


@app.route("/admin/stock")
@admin_required
def admin_stock():
    db = get_db()
    products = db.execute("""
        SELECT id, name, stock, low_stock_threshold, active
        FROM products
        ORDER BY
            CASE WHEN stock = 0 THEN 0
                 WHEN stock <= low_stock_threshold THEN 1
                 ELSE 2 END,
            stock ASC,
            name COLLATE NOCASE
    """).fetchall()
    db.close()
    return render_template("stock.html", products=products)

@app.route("/admin")
@admin_required
def admin():
    db = get_db()

    members = db.execute("""
        SELECT u.id, u.name, u.active,
               COALESCE((SELECT SUM(c.price_cents)
                         FROM consumptions c WHERE c.user_id = u.id), 0)
               + COALESCE((SELECT SUM(md.amount_cents)
                           FROM manual_debts md WHERE md.user_id = u.id), 0) AS spent,
               COALESCE((SELECT SUM(p.amount_cents)
                         FROM payments p WHERE p.user_id = u.id), 0) AS paid
        FROM users u
        WHERE u.is_admin = 0
        ORDER BY u.name COLLATE NOCASE
    """).fetchall()

    pending_claims = db.execute("""
        SELECT pc.*, u.name AS user_name
        FROM payment_claims pc
        JOIN users u ON u.id = pc.user_id
        WHERE pc.status = 'pending'
        ORDER BY pc.id ASC
    """).fetchall()

    consumptions_24h = db.execute("""
        SELECT COUNT(*) AS total
        FROM consumptions
        WHERE created_at >= datetime('now', '-24 hours')
    """).fetchone()["total"]

    low_stock_count = db.execute("""
        SELECT COUNT(*) AS total
        FROM products
        WHERE stock <= low_stock_threshold
    """).fetchone()["total"]

    db.close()

    total_due = sum((m["spent"] - m["paid"]) for m in members)

    return render_template(
        "admin.html",
        members=members,
        total_due=total_due,
        pending_claims=pending_claims,
        pending_claims_count=len(pending_claims),
        consumptions_24h=consumptions_24h,
        low_stock_count=low_stock_count,
    )

@app.post("/admin/products/add")
@admin_required
def add_product():
    name = request.form["name"].strip()
    category = request.form.get("category", "Boisson").strip()
    if category not in {"Boisson", "Nourriture"}:
        category = "Boisson"
    try:
        price_cents = int(round(float(request.form["price"].replace(",", ".")) * 100))
        stock = int(request.form.get("stock", "0"))
        low_stock_threshold = int(request.form.get("low_stock_threshold", "5"))
    except ValueError:
        flash("Prix, stock ou seuil invalide.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    if not name or price_cents < 0 or stock < 0 or low_stock_threshold < 0:
        flash("Produit invalide.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO products (name, price_cents, stock, low_stock_threshold, category, active) VALUES (?, ?, ?, ?, ?, ?)",
            (name, price_cents, stock, low_stock_threshold, category, 1 if stock > 0 else 0)
        )
        db.commit()
        flash("Boisson ajoutée.", "success")
    except sqlite3.IntegrityError:
        flash("Une boisson avec ce nom existe déjà.", "error")
    db.close()
    return redirect(request.referrer or url_for("admin_consumptions"))

@app.post("/admin/products/<int:product_id>/edit")
@admin_required
def edit_product(product_id):
    name = request.form["name"].strip()
    requested_active = 1 if request.form.get("active") == "on" else 0
    category = request.form.get("category", "Boisson").strip()
    if category not in {"Boisson", "Nourriture"}:
        category = "Boisson"

    try:
        price_cents = int(round(float(request.form["price"].replace(",", ".")) * 100))
        stock = int(request.form.get("stock", "0"))
        low_stock_threshold = int(request.form.get("low_stock_threshold", "5"))
    except ValueError:
        flash("Prix, stock ou seuil invalide.", "error")
        return redirect(request.referrer or url_for("admin"))

    if stock < 0 or low_stock_threshold < 0:
        flash("Le stock et le seuil ne peuvent pas être négatifs.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    active = requested_active if stock > 0 else 0

    db = get_db()
    try:
        db.execute(
            "UPDATE products SET name = ?, price_cents = ?, stock = ?, low_stock_threshold = ?, category = ?, active = ? WHERE id = ?",
            (name, price_cents, stock, low_stock_threshold, category, active, product_id)
        )
        db.commit()
        flash("Produit mis à jour.", "success")
    except sqlite3.IntegrityError:
        flash("Ce nom de produit existe déjà.", "error")
    db.close()
    return redirect(request.referrer or url_for("admin_consumptions"))




@app.post("/admin/products/<int:product_id>/stock-step")
@admin_required
def product_stock_step(product_id):
    try:
        step = int(request.form.get("step", "0"))
    except ValueError:
        step = 0

    if step not in {-1, 1}:
        flash("Ajustement de stock invalide.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    db = get_db()
    product = db.execute(
        "SELECT id, name, stock FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if not product:
        db.close()
        flash("Produit introuvable.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    new_stock = max(0, product["stock"] + step)

    db.execute(
        "UPDATE products SET stock = ?, active = CASE WHEN ? > 0 THEN 1 ELSE 0 END WHERE id = ?",
        (new_stock, new_stock, product_id)
    )
    db.commit()
    db.close()

    if product["stock"] > 0 and new_stock == 0:
        notify_admins_stockout(product["name"])

    flash(f"Stock de {product['name']} : {new_stock}.", "success")
    return redirect(request.referrer or url_for("admin_consumptions"))


@app.post("/admin/products/<int:product_id>/set-stock")
@admin_required
def set_product_stock(product_id):
    try:
        stock = int(request.form["stock"])
    except (KeyError, ValueError):
        flash("Stock invalide.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    if stock < 0:
        flash("Le stock ne peut pas être négatif.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    db = get_db()
    product = db.execute("SELECT id, name, stock FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        db.close()
        flash("Boisson introuvable.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    if abs(stock - product["stock"]) >= 10 and request.form.get("confirm_large") != "CONFIRMER":
        db.close()
        flash("Ce gros ajustement de stock demande une confirmation renforcée.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    db.execute(
        "UPDATE products SET stock = ?, active = CASE WHEN ? > 0 THEN 1 ELSE 0 END WHERE id = ?",
        (stock, stock, product_id)
    )
    db.commit()
    db.close()

    if product["stock"] > 0 and stock == 0:
        notify_admins_stockout(product["name"])

    flash(f"Stock de {product['name']} mis à {stock}.", "success")
    return redirect(request.referrer or url_for("admin_consumptions"))

@app.post("/admin/products/<int:product_id>/delete")
@admin_required
def delete_product(product_id):

    db = get_db()
    product = db.execute("SELECT id, name FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        db.close()
        flash("Boisson introuvable.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    db.execute("UPDATE consumptions SET product_id = NULL WHERE product_id = ?", (product_id,))
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    db.close()
    flash(f"{product['name']} supprimé du catalogue.", "success")
    return redirect(request.referrer or url_for("admin_consumptions"))

@app.post("/admin/products/<int:product_id>/restock")
@admin_required
def restock_product(product_id):
    try:
        quantity = int(request.form["quantity"])
    except (KeyError, ValueError):
        flash("Quantité invalide.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    if quantity <= 0:
        flash("La quantité doit être supérieure à 0.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    db = get_db()
    product = db.execute(
        "SELECT id, name, stock FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if not product:
        db.close()
        flash("Produit introuvable.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    new_stock = product["stock"] + quantity
    db.execute(
        "UPDATE products SET stock = ?, active = 1 WHERE id = ?",
        (new_stock, product_id)
    )
    db.commit()
    db.close()

    flash(f"{product['name']} réapprovisionné : +{quantity}. Nouveau stock : {new_stock}.", "success")
    return redirect(request.referrer or url_for("admin_consumptions"))

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



@app.post("/admin/members/<int:user_id>/delete")
@admin_required
def delete_member(user_id):
    if request.form.get("confirm_delete") != "SUPPRIMER":
        flash("Suppression non confirmée.", "error")
        return redirect(request.referrer or url_for("admin_accounts"))

    db = get_db()
    user = db.execute(
        "SELECT id, name FROM users WHERE id = ? AND is_admin = 0",
        (user_id,)
    ).fetchone()
    if not user:
        db.close()
        flash("Membre introuvable.", "error")
        return redirect(request.referrer or url_for("admin_accounts"))

    db.execute("DELETE FROM payment_claims WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM consumptions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    db.close()

    flash(f"Compte {user['name']} supprimé définitivement.", "success")
    return redirect(request.referrer or url_for("admin_accounts"))

@app.post("/admin/members/<int:user_id>/update")
@admin_required
def update_member(user_id):
    name = request.form.get("name", "").strip()
    active = 1 if request.form.get("active") == "on" else 0

    if len(name) < 2:
        flash("Nom trop court.", "error")
        return redirect(request.referrer or url_for("admin_accounts"))

    db = get_db()
    try:
        db.execute(
            "UPDATE users SET name = ?, active = ? WHERE id = ? AND is_admin = 0",
            (name, active, user_id)
        )
        db.commit()
        flash("Membre mis à jour.", "success")
    except sqlite3.IntegrityError:
        flash("Ce nom est déjà utilisé.", "error")
    db.close()
    return redirect(request.referrer or url_for("admin_accounts"))

@app.post("/admin/members/<int:user_id>/reset-password")
@admin_required
def reset_member_password(user_id):
    new_password = request.form.get("new_password", "")
    if len(new_password) < 8:
        flash("Le nouveau mot de passe doit faire au moins 8 caractères.", "error")
        return redirect(request.referrer or url_for("admin_accounts"))

    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id = ? AND is_admin = 0", (user_id,)).fetchone()
    if not user:
        db.close()
        flash("Membre introuvable.", "error")
        return redirect(request.referrer or url_for("admin_accounts"))

    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id)
    )
    db.commit()
    db.close()
    flash("Mot de passe du membre réinitialisé.", "success")
    return redirect(request.referrer or url_for("admin_accounts"))


@app.post("/admin/members/<int:user_id>/add-debt")
@admin_required
def add_member_debt(user_id):
    admin_user = current_user()
    try:
        amount_cents = int(round(float(request.form["amount"].replace(",", ".")) * 100))
    except (KeyError, ValueError):
        flash("Montant de dette invalide.", "error")
        return redirect(request.referrer or url_for("admin_accounts"))

    note = request.form.get("note", "").strip()

    if amount_cents <= 0:
        flash("La dette doit être supérieure à 0 €.", "error")
        return redirect(request.referrer or url_for("admin_accounts"))

    db = get_db()
    user = db.execute(
        "SELECT id, name FROM users WHERE id = ? AND is_admin = 0",
        (user_id,)
    ).fetchone()
    if not user:
        db.close()
        flash("Membre introuvable.", "error")
        return redirect(url_for("admin_accounts"))

    db.execute("""
        INSERT INTO manual_debts (user_id, amount_cents, note, created_by)
        VALUES (?, ?, ?, ?)
    """, (user_id, amount_cents, note, admin_user["id"]))

    add_notification(
        db,
        user_id,
        "Dette ajoutée",
        f"Le popotier a ajouté {amount_cents/100:.2f} € à ton ardoise"
        + (f" : {note}" if note else "."),
        "warning",
        "/dashboard"
    )
    db.commit()
    db.close()

    notify_member_debt_added(user_id, amount_cents, note)

    flash(
        f"Dette de {amount_cents/100:.2f} € ajoutée à {user['name']}.".replace(".", ","),
        "success"
    )
    return redirect(request.referrer or url_for("admin_accounts"))


@app.route("/admin/member/<int:user_id>")
@admin_required
def member_detail(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ? AND is_admin = 0", (user_id,)).fetchone()
    if not user:
        db.close()
        flash("Membre introuvable.", "error")
        return redirect(url_for("admin_accounts"))

    consumptions = db.execute(
        "SELECT * FROM consumptions WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    payments = db.execute(
        "SELECT * FROM payments WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    manual_debts = db.execute(
        "SELECT * FROM manual_debts WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    db.close()

    return render_template(
        "member_detail.html",
        member=user,
        consumptions=consumptions,
        payments=payments,
        manual_debts=manual_debts,
        balance=user_balance_cents(user_id)
    )
