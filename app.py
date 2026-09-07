
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
import base64
import math
from io import BytesIO
import os
import requests
import qrcode
import uuid
import io
from PIL import Image
import json
from pywebpush import webpush, WebPushException


# Passkeys / Face ID / empreinte. Le try/except évite de bloquer l'application
# si la dépendance n'est pas encore installée pendant un test local.
try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
        base64url_to_bytes,
    )
    from webauthn.helpers.structs import (
        AuthenticatorAttachment,
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )
    WEBAUTHN_AVAILABLE = True
except ImportError:
    WEBAUTHN_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parent

PRODUCT_UPLOAD_DIR = BASE_DIR / "static" / "uploads" / "products"
PRODUCT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_PRODUCT_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_PRODUCT_IMAGE_BYTES = 6 * 1024 * 1024
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


    CREATE TABLE IF NOT EXISTS community_ideas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        image_blob BLOB,
        image_mime TEXT,
        status TEXT NOT NULL DEFAULT 'voting',
        official_note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS community_idea_votes (
        idea_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        vote TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(idea_id, user_id),
        FOREIGN KEY(idea_id) REFERENCES community_ideas(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS community_idea_reactions (
        idea_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        reaction TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(idea_id, user_id),
        FOREIGN KEY(idea_id) REFERENCES community_ideas(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS express_polls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_by INTEGER NOT NULL,
        category TEXT NOT NULL DEFAULT 'Nourriture',
        question TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS express_poll_votes (
        poll_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        vote TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(poll_id, user_id),
        FOREIGN KEY(poll_id) REFERENCES express_polls(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS user_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        badge_key TEXT NOT NULL,
        period_key TEXT NOT NULL DEFAULT '',
        metadata_json TEXT,
        awarded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, badge_key, period_key),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS user_profile_settings (
        user_id INTEGER PRIMARY KEY,
        frame_key TEXT NOT NULL DEFAULT 'classic',
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS profile_reactions (
        target_user_id INTEGER NOT NULL,
        actor_user_id INTEGER NOT NULL,
        reaction TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(target_user_id, actor_user_id),
        FOREIGN KEY(target_user_id) REFERENCES users(id),
        FOREIGN KEY(actor_user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS passkey_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        credential_id BLOB NOT NULL UNIQUE,
        public_key BLOB NOT NULL,
        sign_count INTEGER NOT NULL DEFAULT 0,
        transports TEXT,
        label TEXT NOT NULL DEFAULT 'Passkey',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_ideas_created_at ON community_ideas(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_idea_votes_idea ON community_idea_votes(idea_id);
    CREATE INDEX IF NOT EXISTS idx_express_status ON express_polls(status, expires_at);
    """)
    db.commit()

    # Petites migrations pour une base créée avec la V1.
    consumption_cols = {row["name"] for row in db.execute("PRAGMA table_info(consumptions)").fetchall()}
    if "order_id" not in consumption_cols:
        db.execute("ALTER TABLE consumptions ADD COLUMN order_id TEXT")
        db.commit()

    user_cols = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "passkey_user_handle" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN passkey_user_handle BLOB")
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
    if "image_path" not in product_cols:
        db.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
        db.commit()
    if "image_blob" not in product_cols:
        db.execute("ALTER TABLE products ADD COLUMN image_blob BLOB")
        db.commit()
    if "image_mime" not in product_cols:
        db.execute("ALTER TABLE products ADD COLUMN image_mime TEXT")
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



FRENCH_MONTHS = {
    1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
    5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
    9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
}

BADGE_DEFINITIONS = {
    "first_idea_validated": {
        "name": "Visionnaire", "icon": "💡", "rarity": "Rare",
        "description": "Première idée validée par la Popote.",
    },
    "express_10": {
        "name": "Décideur express", "icon": "⚡", "rarity": "Rare",
        "description": "10 votes express enregistrés.",
    },
    "product_discovered": {
        "name": "Explorateur", "icon": "🧭", "rarity": "Commun",
        "description": "Au moins 5 produits différents découverts.",
    },
    "payment_reglo": {
        "name": "Paiement réglo", "icon": "✅", "rarity": "Commun",
        "description": "3 paiements validés.",
    },
    "idea_month": {
        "name": "Idée du mois", "icon": "🏆", "rarity": "Épique",
        "description": "Idée la plus soutenue du mois.",
    },
    "pinch_month": {
        "name": "Pince du mois", "icon": "🦀", "rarity": "Épique",
        "description": "Dernière place du classement mensuel.",
    },
    "consumer_month": {
        "name": "Consommateur du mois", "icon": "👑", "rarity": "Légendaire",
        "description": "Première place du classement mensuel.",
    },
    "veteran": {
        "name": "Ancien de la Popote", "icon": "🎖️", "rarity": "Rare",
        "description": "Plus de 6 mois d'ancienneté.",
    },
    "fifty_entries": {
        "name": "Habitué", "icon": "⭐", "rarity": "Commun",
        "description": "50 consommations enregistrées.",
    },
}

RARITY_WEIGHT = {"Commun": 1, "Rare": 2, "Épique": 3, "Légendaire": 4}
PROFILE_REACTIONS = {"🔥", "😂", "🍻", "👀"}
IDEA_REACTIONS = PROFILE_REACTIONS


def _period_label(period_key):
    try:
        year, month = [int(x) for x in period_key.split("-")]
        return f"{FRENCH_MONTHS[month]} {year}"
    except Exception:
        return period_key


def _previous_month_key():
    now = datetime.now()
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


def _b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value):
    value = value.encode("ascii") if isinstance(value, str) else value
    return base64.urlsafe_b64decode(value + b"=" * (-len(value) % 4))


def webauthn_rp_id():
    return request.host.split(":", 1)[0]


def webauthn_origin():
    proto = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
    return f"{proto}://{request.host}"


def notify_all_active(title, message, link, tag, exclude_user_id=None):
    db = get_db()
    rows = db.execute(
        "SELECT id FROM users WHERE active = 1" + (" AND id != ?" if exclude_user_id else ""),
        ((exclude_user_id,) if exclude_user_id else ())
    ).fetchall()
    for row in rows:
        add_notification(db, row["id"], title, message, "info", link)
    db.commit()
    db.close()

    pushed = 0
    for row in rows:
        pushed += send_push_to_user(row["id"], title, message, link, tag)
    return len(rows), pushed


def _insert_badge(db, user_id, badge_key, period_key="", metadata=None):
    if badge_key not in BADGE_DEFINITIONS:
        return False
    cur = db.execute(
        """
        INSERT OR IGNORE INTO user_badges (user_id, badge_key, period_key, metadata_json)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, badge_key, period_key or "", json.dumps(metadata or {}, ensure_ascii=False))
    )
    return cur.rowcount > 0


def award_badges(user_id):
    """Calcule les badges sans faire dépendre le niveau du volume de boissons."""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return

    validated_ideas = db.execute(
        "SELECT COUNT(*) total FROM community_ideas WHERE user_id = ? AND status IN ('testing','available')",
        (user_id,)
    ).fetchone()["total"]
    if validated_ideas >= 1:
        _insert_badge(db, user_id, "first_idea_validated")

    express_votes = db.execute(
        "SELECT COUNT(*) total FROM express_poll_votes WHERE user_id = ?",
        (user_id,)
    ).fetchone()["total"]
    if express_votes >= 10:
        _insert_badge(db, user_id, "express_10")

    distinct_products = db.execute(
        "SELECT COUNT(DISTINCT COALESCE(product_id, product_name)) total FROM consumptions WHERE user_id = ?",
        (user_id,)
    ).fetchone()["total"]
    if distinct_products >= 5:
        _insert_badge(db, user_id, "product_discovered")

    total_entries = db.execute(
        "SELECT COUNT(*) total FROM consumptions WHERE user_id = ?",
        (user_id,)
    ).fetchone()["total"]
    if total_entries >= 50:
        _insert_badge(db, user_id, "fifty_entries")

    approved_payments = db.execute(
        "SELECT COUNT(*) total FROM payment_claims WHERE user_id = ? AND status = 'approved'",
        (user_id,)
    ).fetchone()["total"]
    if approved_payments >= 3:
        _insert_badge(db, user_id, "payment_reglo")

    age_days = db.execute(
        "SELECT CAST(julianday('now') - julianday(created_at) AS INTEGER) days FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()["days"] or 0
    if age_days >= 180:
        _insert_badge(db, user_id, "veteran")

    # Palmarès du mois précédent (calculé depuis l'historique existant).
    prev_key = _previous_month_key()
    ranking = db.execute("""
        SELECT u.id,
               COALESCE((SELECT SUM(c.price_cents) FROM consumptions c
                         WHERE c.user_id=u.id AND strftime('%Y-%m', c.created_at)=?),0)
             + COALESCE((SELECT SUM(md.amount_cents) FROM manual_debts md
                         WHERE md.user_id=u.id AND strftime('%Y-%m', md.created_at)=?),0) total_cents
        FROM users u
        WHERE u.is_admin=0 AND u.active=1
        ORDER BY total_cents DESC, u.name COLLATE NOCASE
    """, (prev_key, prev_key)).fetchall()
    if ranking and max(r["total_cents"] for r in ranking) > 0:
        label = _period_label(prev_key)
        if ranking[0]["id"] == user_id:
            _insert_badge(db, user_id, "consumer_month", prev_key, {"period_label": label})
        if len(ranking) > 1 and ranking[-1]["id"] == user_id:
            _insert_badge(db, user_id, "pinch_month", prev_key, {"period_label": label})

    # Idée du mois précédent.
    top_idea = db.execute("""
        SELECT i.id, i.user_id, i.title,
               COALESCE(SUM(CASE WHEN v.vote='yes' THEN 1 ELSE 0 END),0) yes_count
        FROM community_ideas i
        LEFT JOIN community_idea_votes v ON v.idea_id=i.id
        WHERE strftime('%Y-%m', i.created_at)=?
          AND i.status NOT IN ('rejected','archived')
        GROUP BY i.id
        ORDER BY yes_count DESC, i.id ASC
        LIMIT 1
    """, (prev_key,)).fetchone()
    if top_idea and top_idea["user_id"] == user_id and top_idea["yes_count"] >= 2:
        _insert_badge(db, user_id, "idea_month", prev_key, {
            "period_label": _period_label(prev_key), "idea_title": top_idea["title"]
        })

    db.commit()
    db.close()


def get_badges(user_id):
    award_badges(user_id)
    db = get_db()
    rows = db.execute("""
        SELECT badge_key, period_key, metadata_json, awarded_at
        FROM user_badges WHERE user_id=? ORDER BY id DESC
    """, (user_id,)).fetchall()
    db.close()
    badges = []
    for row in rows:
        definition = BADGE_DEFINITIONS.get(row["badge_key"])
        if not definition:
            continue
        item = dict(definition)
        item.update({"key": row["badge_key"], "period_key": row["period_key"], "awarded_at": row["awarded_at"]})
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        item["metadata"] = metadata
        if row["period_key"]:
            item["subtitle"] = metadata.get("period_label") or _period_label(row["period_key"])
        else:
            item["subtitle"] = ""
        badges.append(item)
    return badges


def profile_frame_choices(user_id, badges):
    choices = [{"key": "classic", "name": "Classique", "rarity": "Commun"}]
    rare_count = sum(1 for b in badges if RARITY_WEIGHT.get(b["rarity"], 0) >= 2)
    epic = any(RARITY_WEIGHT.get(b["rarity"], 0) >= 3 for b in badges)
    legendary = any(RARITY_WEIGHT.get(b["rarity"], 0) >= 4 for b in badges)
    if rare_count >= 1:
        choices.append({"key": "bronze", "name": "Bronze", "rarity": "Rare"})
    if rare_count >= 2:
        choices.append({"key": "silver", "name": "Argent", "rarity": "Rare"})
    if epic or legendary:
        choices.append({"key": "gold", "name": "Or", "rarity": "Épique"})
    if any(b["key"] == "pinch_month" and b["period_key"] == _previous_month_key() for b in badges):
        choices.append({"key": "pince", "name": "Pince du mois", "rarity": "Épique"})
    return choices


def build_profile(user_id, viewer_id=None):
    db = get_db()
    user = db.execute("SELECT id, name, active, is_admin, created_at FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        db.close()
        return None

    badges = get_badges(user_id)
    # get_badges ouvre sa propre connexion ; on conserve celle-ci pour les stats.
    vote_count = db.execute("SELECT COUNT(*) total FROM community_idea_votes WHERE user_id=?", (user_id,)).fetchone()["total"]
    express_count = db.execute("SELECT COUNT(*) total FROM express_poll_votes WHERE user_id=?", (user_id,)).fetchone()["total"]
    ideas_count = db.execute("SELECT COUNT(*) total FROM community_ideas WHERE user_id=?", (user_id,)).fetchone()["total"]
    validated_count = db.execute("SELECT COUNT(*) total FROM community_ideas WHERE user_id=? AND status IN ('testing','available')", (user_id,)).fetchone()["total"]
    payments_count = db.execute("SELECT COUNT(*) total FROM payment_claims WHERE user_id=? AND status='approved'", (user_id,)).fetchone()["total"]
    received_reactions = db.execute("SELECT COUNT(*) total FROM profile_reactions WHERE target_user_id=?", (user_id,)).fetchone()["total"]
    age_days = db.execute("SELECT CAST(julianday('now') - julianday(?) AS INTEGER) days", (user["created_at"],)).fetchone()["days"] or 0

    # Le niveau récompense l'implication, pas le fait de consommer davantage.
    xp = (
        min(vote_count + express_count, 150) * 6
        + ideas_count * 24
        + validated_count * 70
        + payments_count * 14
        + len(badges) * 42
        + min(received_reactions, 100) * 3
        + min(age_days, 730) // 7 * 4
    )
    level = max(1, 1 + xp // 220)
    level_start = (level - 1) * 220
    progress = min(100, max(0, round((xp - level_start) / 220 * 100)))

    tastes = db.execute("""
        SELECT c.product_name name, COALESCE(p.category,'') category, COUNT(*) qty
        FROM consumptions c
        LEFT JOIN products p ON p.id=c.product_id
        WHERE c.user_id=?
        GROUP BY c.product_name, COALESCE(p.category,'')
        ORDER BY qty DESC, c.product_name COLLATE NOCASE
        LIMIT 12
    """, (user_id,)).fetchall()
    top_product = tastes[0]["name"] if tastes else None
    top_drink = next((r["name"] for r in tastes if r["category"] == "Boisson"), None)
    top_food = next((r["name"] for r in tastes if r["category"] == "Nourriture"), None)

    food_names = " ".join(r["name"].lower() for r in tastes if r["category"] == "Nourriture")
    salty_words = ("chips", "pizza", "burger", "saucisson", "cacahu", "sandwich", "tacos", "fromage")
    sweet_words = ("bueno", "kinder", "chocol", "cookie", "bonbon", "biscuit", "oreo", "twix", "mars")
    salty_score = sum(food_names.count(w) for w in salty_words)
    sweet_score = sum(food_names.count(w) for w in sweet_words)
    food_style = "Plutôt salé" if salty_score > sweet_score else ("Plutôt sucré" if sweet_score else None)

    tags = []
    if top_drink:
        tags.append(f"Team {top_drink}")
    if food_style:
        tags.append(food_style)
    if top_food:
        tags.append(f"Fan de {top_food}")
    for b in badges:
        if b["key"] in ("pinch_month", "consumer_month") and b.get("subtitle"):
            tags.append(f"{b['name']} · {b['subtitle']}")
    tags = tags[:5]

    reaction_rows = db.execute("""
        SELECT reaction, COUNT(*) total FROM profile_reactions
        WHERE target_user_id=? GROUP BY reaction
    """, (user_id,)).fetchall()
    reactions = {r: 0 for r in ("🔥", "😂", "🍻", "👀")}
    for row in reaction_rows:
        reactions[row["reaction"]] = row["total"]
    my_reaction = None
    if viewer_id:
        row = db.execute("SELECT reaction FROM profile_reactions WHERE target_user_id=? AND actor_user_id=?", (user_id, viewer_id)).fetchone()
        my_reaction = row["reaction"] if row else None

    settings = db.execute("SELECT frame_key FROM user_profile_settings WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    frames = profile_frame_choices(user_id, badges)
    unlocked_keys = {f["key"] for f in frames}
    selected = settings["frame_key"] if settings and settings["frame_key"] in unlocked_keys else frames[-1]["key"]

    return {
        "user": user,
        "badges": badges,
        "frames": frames,
        "frame": selected,
        "xp": xp,
        "level": level,
        "progress": progress,
        "tags": tags,
        "top_product": top_product,
        "top_drink": top_drink,
        "top_food": top_food,
        "stats": {"ideas": ideas_count, "votes": vote_count + express_count, "validated": validated_count},
        "reactions": reactions,
        "my_reaction": my_reaction,
    }


def community_status_label(status):
    return {
        "voting": "En vote", "testing": "À tester", "available": "Disponible",
        "rejected": "Refusée", "archived": "Archivée",
    }.get(status, status)

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
        "webauthn_available": WEBAUTHN_AVAILABLE,
        "community_status_label": community_status_label,
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


@app.route("/idees")
@login_required
def ideas():
    user = current_user()
    db = get_db()
    db.execute("UPDATE express_polls SET status='closed' WHERE status='open' AND expires_at <= CURRENT_TIMESTAMP")
    db.commit()

    category = request.args.get("category", "").strip()
    sort = request.args.get("sort", "popular").strip()
    params = [user["id"], user["id"]]
    where = "WHERE i.status != 'archived'"
    if category in ("Boisson", "Nourriture"):
        where += " AND i.category = ?"
        params.append(category)
    if sort == "recent":
        order = "i.id DESC"
    elif sort == "validated":
        where += " AND i.status IN ('testing','available')"
        order = "i.id DESC"
    else:
        sort = "popular"
        order = "(yes_count - no_count) DESC, yes_count DESC, i.id DESC"

    rows = db.execute(f"""
        SELECT i.*, u.name author_name,
               COALESCE((SELECT COUNT(*) FROM community_idea_votes v WHERE v.idea_id=i.id AND v.vote='yes'),0) yes_count,
               COALESCE((SELECT COUNT(*) FROM community_idea_votes v WHERE v.idea_id=i.id AND v.vote='no'),0) no_count,
               (SELECT vote FROM community_idea_votes v WHERE v.idea_id=i.id AND v.user_id=?) my_vote,
               (SELECT reaction FROM community_idea_reactions r WHERE r.idea_id=i.id AND r.user_id=?) my_reaction
        FROM community_ideas i
        JOIN users u ON u.id=i.user_id
        {where}
        ORDER BY {order}
        LIMIT 80
    """, params).fetchall()

    idea_items = []
    for row in rows:
        item = dict(row)
        reactions = {r: 0 for r in ("🔥", "😂", "🍻", "👀")}
        for rr in db.execute("SELECT reaction, COUNT(*) total FROM community_idea_reactions WHERE idea_id=? GROUP BY reaction", (row["id"],)).fetchall():
            reactions[rr["reaction"]] = rr["total"]
        item["reactions"] = reactions
        total = item["yes_count"] + item["no_count"]
        item["percent_yes"] = round(item["yes_count"] / total * 100) if total else 0
        item["popular"] = item["yes_count"] >= 5 and item["percent_yes"] >= 70
        idea_items.append(item)

    open_polls = db.execute("""
        SELECT p.*, u.name author_name,
               COALESCE((SELECT COUNT(*) FROM express_poll_votes v WHERE v.poll_id=p.id AND v.vote='yes'),0) yes_count,
               COALESCE((SELECT COUNT(*) FROM express_poll_votes v WHERE v.poll_id=p.id AND v.vote='no'),0) no_count,
               (SELECT vote FROM express_poll_votes v WHERE v.poll_id=p.id AND v.user_id=?) my_vote,
               MAX(0, CAST((julianday(p.expires_at)-julianday('now'))*24*60 AS INTEGER)) minutes_left
        FROM express_polls p JOIN users u ON u.id=p.created_by
        WHERE p.status='open' AND p.expires_at > CURRENT_TIMESTAMP
        ORDER BY p.id DESC
    """, (user["id"],)).fetchall()
    closed_polls = db.execute("""
        SELECT p.*,
               COALESCE((SELECT COUNT(*) FROM express_poll_votes v WHERE v.poll_id=p.id AND v.vote='yes'),0) yes_count,
               COALESCE((SELECT COUNT(*) FROM express_poll_votes v WHERE v.poll_id=p.id AND v.vote='no'),0) no_count
        FROM express_polls p
        WHERE p.status='closed' OR p.expires_at <= CURRENT_TIMESTAMP
        ORDER BY p.id DESC LIMIT 5
    """).fetchall()
    db.close()
    return render_template("ideas.html", ideas=idea_items, open_polls=open_polls, closed_polls=closed_polls,
                           category=category, sort=sort)


@app.post("/idees/proposer")
@login_required
def idea_create():
    user = current_user()
    category = request.form.get("category", "").strip()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if category not in ("Boisson", "Nourriture"):
        flash("Choisis Boisson ou Nourriture.", "error")
        return redirect(url_for("ideas"))
    if len(title) < 2 or len(title) > 80:
        flash("Le nom de l'idée doit faire entre 2 et 80 caractères.", "error")
        return redirect(url_for("ideas"))
    if len(description) > 320:
        flash("La description est trop longue.", "error")
        return redirect(url_for("ideas"))

    db = get_db()
    duplicate = db.execute("""
        SELECT id FROM community_ideas
        WHERE lower(trim(title))=lower(trim(?)) AND status NOT IN ('rejected','archived')
        LIMIT 1
    """, (title,)).fetchone()
    if duplicate:
        db.close()
        flash("Cette idée existe déjà : vote directement pour elle 👀", "error")
        return redirect(url_for("ideas") + f"#idea-{duplicate['id']}")

    try:
        image_blob, image_mime = process_product_image(request.files.get("image"))
    except ValueError as exc:
        db.close()
        flash(str(exc), "error")
        return redirect(url_for("ideas"))

    cur = db.execute("""
        INSERT INTO community_ideas (user_id, category, title, description, image_blob, image_mime)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user["id"], category, title, description, image_blob, image_mime))
    idea_id = cur.lastrowid
    db.commit()
    db.close()

    notify_all_active(
        "💡 Nouvelle idée Popote",
        f"{user['name']} propose : {title}",
        f"/idees#idea-{idea_id}",
        f"idea-{idea_id}",
        exclude_user_id=user["id"],
    )
    flash("Ton idée est en ligne. À la Popote de voter ✨", "success")
    return redirect(url_for("ideas") + f"#idea-{idea_id}")


@app.get("/idees/<int:idea_id>/image")
@login_required
def idea_image(idea_id):
    db = get_db()
    row = db.execute("SELECT image_blob, image_mime FROM community_ideas WHERE id=?", (idea_id,)).fetchone()
    db.close()
    if not row or not row["image_blob"]:
        return "", 404
    return send_file(BytesIO(row["image_blob"]), mimetype=row["image_mime"] or "image/webp", max_age=86400)


@app.post("/idees/<int:idea_id>/vote")
@login_required
def idea_vote(idea_id):
    user = current_user()
    vote = request.form.get("vote", "")
    if vote not in ("yes", "no"):
        return redirect(url_for("ideas"))
    db = get_db()
    idea = db.execute("SELECT id, status FROM community_ideas WHERE id=?", (idea_id,)).fetchone()
    if not idea or idea["status"] in ("archived", "rejected"):
        db.close()
        flash("Ce vote n'est plus disponible.", "error")
        return redirect(url_for("ideas"))
    existing = db.execute("SELECT vote FROM community_idea_votes WHERE idea_id=? AND user_id=?", (idea_id, user["id"])).fetchone()
    if existing and existing["vote"] == vote:
        db.execute("DELETE FROM community_idea_votes WHERE idea_id=? AND user_id=?", (idea_id, user["id"]))
    else:
        db.execute("""
            INSERT INTO community_idea_votes (idea_id,user_id,vote) VALUES (?,?,?)
            ON CONFLICT(idea_id,user_id) DO UPDATE SET vote=excluded.vote, created_at=CURRENT_TIMESTAMP
        """, (idea_id, user["id"], vote))
    db.commit(); db.close()
    return redirect((request.referrer or url_for("ideas")).split("#")[0] + f"#idea-{idea_id}")


@app.post("/idees/<int:idea_id>/reaction")
@login_required
def idea_reaction(idea_id):
    user = current_user()
    reaction = request.form.get("reaction", "")
    if reaction not in IDEA_REACTIONS:
        return redirect(url_for("ideas"))
    db = get_db()
    existing = db.execute("SELECT reaction FROM community_idea_reactions WHERE idea_id=? AND user_id=?", (idea_id, user["id"])).fetchone()
    if existing and existing["reaction"] == reaction:
        db.execute("DELETE FROM community_idea_reactions WHERE idea_id=? AND user_id=?", (idea_id, user["id"]))
    else:
        db.execute("""
            INSERT INTO community_idea_reactions (idea_id,user_id,reaction) VALUES (?,?,?)
            ON CONFLICT(idea_id,user_id) DO UPDATE SET reaction=excluded.reaction, created_at=CURRENT_TIMESTAMP
        """, (idea_id, user["id"], reaction))
    db.commit(); db.close()
    return redirect((request.referrer or url_for("ideas")).split("#")[0] + f"#idea-{idea_id}")


@app.post("/idees/<int:idea_id>/statut")
@admin_required
def idea_status(idea_id):
    status = request.form.get("status", "")
    note = request.form.get("official_note", "").strip()[:220]
    allowed = {"voting", "testing", "available", "rejected", "archived"}
    if status not in allowed:
        flash("Statut invalide.", "error")
        return redirect(url_for("ideas"))
    db = get_db()
    idea = db.execute("SELECT i.*,u.name author_name FROM community_ideas i JOIN users u ON u.id=i.user_id WHERE i.id=?", (idea_id,)).fetchone()
    if not idea:
        db.close(); return redirect(url_for("ideas"))
    db.execute("UPDATE community_ideas SET status=?, official_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, note, idea_id))
    add_notification(db, idea["user_id"], "💡 Ton idée évolue", f"{idea['title']} : {community_status_label(status)}" + (f" — {note}" if note else ""), "info", f"/idees#idea-{idea_id}")
    db.commit(); db.close()
    if status in ("testing", "available"):
        award_badges(idea["user_id"])
    if status == "available":
        notify_all_active("✨ Une idée devient réalité", f"{idea['title']} est maintenant disponible à la Popote.", f"/idees#idea-{idea_id}", f"idea-available-{idea_id}")
    else:
        send_push_to_user(idea["user_id"], "💡 Ton idée évolue", f"{idea['title']} : {community_status_label(status)}", f"/idees#idea-{idea_id}", f"idea-status-{idea_id}-{status}")
    flash("Statut de l'idée mis à jour.", "success")
    return redirect(url_for("ideas") + f"#idea-{idea_id}")


@app.post("/idees/vote-express")
@admin_required
def express_create():
    admin_user = current_user()
    question = request.form.get("question", "").strip()
    category = request.form.get("category", "Nourriture")
    try:
        minutes = int(request.form.get("minutes", "120"))
    except ValueError:
        minutes = 120
    if category not in ("Boisson", "Nourriture"):
        category = "Nourriture"
    if len(question) < 3 or len(question) > 110:
        flash("Question invalide.", "error")
        return redirect(url_for("ideas"))
    if minutes not in (30, 60, 120, 240):
        minutes = 120
    db = get_db()
    cur = db.execute("""
        INSERT INTO express_polls (created_by, category, question, expires_at)
        VALUES (?, ?, ?, datetime('now', ?))
    """, (admin_user["id"], category, question, f"+{minutes} minutes"))
    poll_id = cur.lastrowid
    db.commit(); db.close()
    duration = "2 h" if minutes == 120 else (f"{minutes//60} h" if minutes >= 60 else f"{minutes} min")
    notify_all_active("⚡ Vote express", f"{question} · Vote ouvert pendant {duration}", f"/idees#express-{poll_id}", f"express-{poll_id}")
    flash("Vote express lancé et notification envoyée.", "success")
    return redirect(url_for("ideas") + f"#express-{poll_id}")


@app.post("/idees/vote-express/<int:poll_id>/vote")
@login_required
def express_vote(poll_id):
    user = current_user()
    vote = request.form.get("vote", "")
    if vote not in ("yes", "no"):
        return redirect(url_for("ideas"))
    db = get_db()
    poll = db.execute("SELECT * FROM express_polls WHERE id=?", (poll_id,)).fetchone()
    if not poll or poll["status"] != "open" or db.execute("SELECT ? <= CURRENT_TIMESTAMP expired", (poll["expires_at"],)).fetchone()["expired"]:
        if poll:
            db.execute("UPDATE express_polls SET status='closed' WHERE id=?", (poll_id,)); db.commit()
        db.close(); flash("Ce vote express est terminé.", "error")
        return redirect(url_for("ideas"))
    existing = db.execute("SELECT vote FROM express_poll_votes WHERE poll_id=? AND user_id=?", (poll_id, user["id"])).fetchone()
    if existing and existing["vote"] == vote:
        db.execute("DELETE FROM express_poll_votes WHERE poll_id=? AND user_id=?", (poll_id, user["id"]))
    else:
        db.execute("""
            INSERT INTO express_poll_votes (poll_id,user_id,vote) VALUES (?,?,?)
            ON CONFLICT(poll_id,user_id) DO UPDATE SET vote=excluded.vote, created_at=CURRENT_TIMESTAMP
        """, (poll_id, user["id"], vote))
    db.commit(); db.close(); award_badges(user["id"])
    return redirect(url_for("ideas") + f"#express-{poll_id}")


@app.post("/idees/vote-express/<int:poll_id>/close")
@admin_required
def express_close(poll_id):
    db = get_db(); db.execute("UPDATE express_polls SET status='closed', expires_at=CURRENT_TIMESTAMP WHERE id=?", (poll_id,)); db.commit(); db.close()
    flash("Vote express clôturé.", "success")
    return redirect(url_for("ideas") + f"#express-{poll_id}")


@app.route("/profil")
@login_required
def profile():
    user = current_user()
    return redirect(url_for("public_profile", user_id=user["id"]))


@app.route("/profil/<int:user_id>")
@login_required
def public_profile(user_id):
    viewer = current_user()
    profile_data = build_profile(user_id, viewer["id"])
    if not profile_data or not profile_data["user"]["active"]:
        flash("Profil introuvable.", "error")
        return redirect(url_for("profiles"))
    db = get_db()
    passkeys = []
    if viewer["id"] == user_id:
        passkeys = db.execute("SELECT id,label,created_at FROM passkey_credentials WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    db.close()
    return render_template("profile.html", profile=profile_data, is_owner=viewer["id"] == user_id, passkeys=passkeys)


@app.route("/profils")
@login_required
def profiles():
    viewer = current_user()
    db = get_db(); users = db.execute("SELECT id FROM users WHERE active=1 AND is_admin=0 ORDER BY name COLLATE NOCASE").fetchall(); db.close()
    cards = [build_profile(row["id"], viewer["id"]) for row in users]
    return render_template("profiles.html", profiles=[c for c in cards if c])


@app.post("/profil/<int:user_id>/reaction")
@login_required
def profile_reaction(user_id):
    viewer = current_user(); reaction = request.form.get("reaction", "")
    if reaction not in PROFILE_REACTIONS or viewer["id"] == user_id:
        return redirect(url_for("public_profile", user_id=user_id))
    db = get_db()
    target = db.execute("SELECT id FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
    if not target:
        db.close(); return redirect(url_for("profiles"))
    existing = db.execute("SELECT reaction FROM profile_reactions WHERE target_user_id=? AND actor_user_id=?", (user_id, viewer["id"])).fetchone()
    if existing and existing["reaction"] == reaction:
        db.execute("DELETE FROM profile_reactions WHERE target_user_id=? AND actor_user_id=?", (user_id, viewer["id"]))
    else:
        db.execute("""
            INSERT INTO profile_reactions(target_user_id,actor_user_id,reaction) VALUES(?,?,?)
            ON CONFLICT(target_user_id,actor_user_id) DO UPDATE SET reaction=excluded.reaction, created_at=CURRENT_TIMESTAMP
        """, (user_id, viewer["id"], reaction))
    db.commit(); db.close()
    return redirect(url_for("public_profile", user_id=user_id) + "#profile-reactions")


@app.post("/profil/cadre")
@login_required
def profile_frame():
    user = current_user(); badges = get_badges(user["id"]); choices = profile_frame_choices(user["id"], badges)
    frame = request.form.get("frame", "classic")
    if frame not in {c["key"] for c in choices}:
        flash("Ce cadre n'est pas encore débloqué.", "error")
        return redirect(url_for("profile"))
    db = get_db(); db.execute("""
        INSERT INTO user_profile_settings(user_id,frame_key) VALUES(?,?)
        ON CONFLICT(user_id) DO UPDATE SET frame_key=excluded.frame_key
    """, (user["id"], frame)); db.commit(); db.close()
    flash("Cadre de profil appliqué ✨", "success")
    return redirect(url_for("profile"))


@app.post("/passkeys/register/options")
@login_required
def passkey_register_options():
    if not WEBAUTHN_AVAILABLE:
        return {"ok": False, "error": "Passkeys indisponibles sur ce serveur."}, 503
    user = current_user(); db = get_db()
    handle = user["passkey_user_handle"] if "passkey_user_handle" in user.keys() else None
    if not handle:
        handle = os.urandom(32); db.execute("UPDATE users SET passkey_user_handle=? WHERE id=?", (sqlite3.Binary(handle), user["id"])); db.commit()
    creds = db.execute("SELECT credential_id FROM passkey_credentials WHERE user_id=?", (user["id"],)).fetchall(); db.close()
    options = generate_registration_options(
        rp_id=webauthn_rp_id(), rp_name="Popote Bravo", user_id=bytes(handle),
        user_name=user["name"], user_display_name=user["name"],
        exclude_credentials=[PublicKeyCredentialDescriptor(id=bytes(c["credential_id"])) for c in creds],
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    session["webauthn_reg_challenge"] = _b64url_encode(options.challenge)
    return app.response_class(options_to_json(options), mimetype="application/json")


@app.post("/passkeys/register/verify")
@login_required
def passkey_register_verify():
    if not WEBAUTHN_AVAILABLE:
        return {"ok": False, "error": "Passkeys indisponibles."}, 503
    user = current_user(); data = request.get_json(silent=True) or {}; challenge = session.pop("webauthn_reg_challenge", None)
    if not challenge:
        return {"ok": False, "error": "Session de création expirée."}, 400
    try:
        verification = verify_registration_response(
            credential=data,
            expected_challenge=_b64url_decode(challenge),
            expected_origin=webauthn_origin(), expected_rp_id=webauthn_rp_id(), require_user_verification=True,
        )
    except Exception as exc:
        return {"ok": False, "error": f"Impossible d'enregistrer Face ID / passkey : {exc}"}, 400
    transports = ((data.get("response") or {}).get("transports") or [])
    db = get_db(); db.execute("""
        INSERT OR REPLACE INTO passkey_credentials(user_id,credential_id,public_key,sign_count,transports,label)
        VALUES(?,?,?,?,?,?)
    """, (user["id"], sqlite3.Binary(verification.credential_id), sqlite3.Binary(verification.credential_public_key), verification.sign_count, json.dumps(transports), "Face ID / Passkey")); db.commit(); db.close()
    return {"ok": True}


@app.post("/passkeys/auth/options")
def passkey_auth_options():
    if not WEBAUTHN_AVAILABLE:
        return {"ok": False, "error": "Passkeys indisponibles."}, 503
    data = request.get_json(silent=True) or {}; name = (data.get("name") or "").strip()
    db = get_db(); user = db.execute("SELECT id,name,is_admin FROM users WHERE name=? AND active=1", (name,)).fetchone()
    if not user:
        db.close(); return {"ok": False, "error": "Aucune passkey disponible pour ce compte."}, 404
    creds = db.execute("SELECT credential_id FROM passkey_credentials WHERE user_id=?", (user["id"],)).fetchall(); db.close()
    if not creds:
        return {"ok": False, "error": "Aucune passkey enregistrée pour ce compte."}, 404
    options = generate_authentication_options(
        rp_id=webauthn_rp_id(),
        allow_credentials=[PublicKeyCredentialDescriptor(id=bytes(c["credential_id"])) for c in creds],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session["webauthn_auth_challenge"] = _b64url_encode(options.challenge); session["webauthn_auth_user_id"] = user["id"]
    return app.response_class(options_to_json(options), mimetype="application/json")


@app.post("/passkeys/auth/verify")
def passkey_auth_verify():
    if not WEBAUTHN_AVAILABLE:
        return {"ok": False, "error": "Passkeys indisponibles."}, 503
    data = request.get_json(silent=True) or {}; challenge = session.pop("webauthn_auth_challenge", None); user_id = session.pop("webauthn_auth_user_id", None)
    if not challenge or not user_id:
        return {"ok": False, "error": "Session Face ID expirée."}, 400
    try:
        credential_id = base64url_to_bytes(data.get("id", ""))
    except Exception:
        return {"ok": False, "error": "Passkey invalide."}, 400
    db = get_db(); cred = db.execute("SELECT * FROM passkey_credentials WHERE user_id=? AND credential_id=?", (user_id, sqlite3.Binary(credential_id))).fetchone(); user = db.execute("SELECT id,is_admin,active FROM users WHERE id=?", (user_id,)).fetchone()
    if not cred or not user or not user["active"]:
        db.close(); return {"ok": False, "error": "Passkey inconnue."}, 400
    try:
        verification = verify_authentication_response(
            credential=data, expected_challenge=_b64url_decode(challenge), expected_origin=webauthn_origin(),
            expected_rp_id=webauthn_rp_id(), credential_public_key=bytes(cred["public_key"]),
            credential_current_sign_count=cred["sign_count"], require_user_verification=True,
        )
    except Exception as exc:
        db.close(); return {"ok": False, "error": f"Authentification refusée : {exc}"}, 400
    db.execute("UPDATE passkey_credentials SET sign_count=? WHERE id=?", (verification.new_sign_count, cred["id"])); db.commit(); db.close()
    session.clear(); session["user_id"] = user["id"]
    return {"ok": True, "redirect": url_for("admin" if user["is_admin"] else "dashboard")}


@app.post("/passkeys/<int:credential_id>/delete")
@login_required
def passkey_delete(credential_id):
    user = current_user(); db = get_db(); db.execute("DELETE FROM passkey_credentials WHERE id=? AND user_id=?", (credential_id, user["id"])); db.commit(); db.close()
    flash("Passkey supprimée.", "success")
    return redirect(url_for("profile"))

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

    spent = db.execute(
        "SELECT COALESCE(SUM(price_cents), 0) AS total FROM consumptions WHERE user_id = ?",
        (claim["user_id"],)
    ).fetchone()["total"]
    manual_debts = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM manual_debts WHERE user_id = ?",
        (claim["user_id"],)
    ).fetchone()["total"]
    paid = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payments WHERE user_id = ?",
        (claim["user_id"],)
    ).fetchone()["total"]

    remaining_balance = spent + manual_debts - paid

    if claim["amount_cents"] > remaining_balance:
        db.close()
        flash(
            "Le montant déclaré dépasse maintenant l'ardoise restante.",
            "error"
        )
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

    push_subscriber_count = db.execute("""
        SELECT COUNT(DISTINCT ps.user_id) AS total
        FROM push_subscriptions ps
        JOIN users u ON u.id = ps.user_id
        WHERE u.active = 1
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
        push_subscriber_count=push_subscriber_count,
    )



@app.post("/admin/notifications/broadcast")
@admin_required
def admin_broadcast_notification():
    """Envoie une notification personnalisable à tous les comptes actifs."""
    title = request.form.get("title", "").strip()
    message = request.form.get("message", "").strip()

    if not title or not message:
        flash("Le titre et le message sont obligatoires.", "error")
        return redirect(url_for("admin"))

    if len(title) > 80:
        flash("Le titre est trop long (80 caractères maximum).", "error")
        return redirect(url_for("admin"))

    if len(message) > 320:
        flash("Le message est trop long (320 caractères maximum).", "error")
        return redirect(url_for("admin"))

    db = get_db()
    recipients = db.execute("""
        SELECT id, name
        FROM users
        WHERE active = 1
        ORDER BY id
    """).fetchall()

    if not recipients:
        db.close()
        flash("Aucun compte actif à notifier.", "error")
        return redirect(url_for("admin"))

    prepared = []
    for recipient in recipients:
        recipient_title = title.replace("{prenom}", recipient["name"])
        recipient_message = message.replace("{prenom}", recipient["name"])

        add_notification(
            db,
            recipient["id"],
            recipient_title,
            recipient_message,
            "info",
            "/notifications"
        )
        prepared.append((
            recipient["id"],
            recipient_title,
            recipient_message,
        ))

    db.commit()
    db.close()

    # Le tag commun évite d'empiler plusieurs copies d'une même campagne
    # sur un même appareil, tout en gardant une notification par utilisateur.
    campaign_tag = f"broadcast-{int(datetime.now().timestamp())}"
    pushed_devices = 0

    for user_id, recipient_title, recipient_message in prepared:
        pushed_devices += send_push_to_user(
            user_id,
            recipient_title,
            recipient_message,
            "/notifications",
            campaign_tag
        )

    flash(
        f"Notification envoyée à {len(prepared)} compte(s) actif(s) "
        f"et poussée sur {pushed_devices} appareil(s).",
        "success"
    )
    return redirect(url_for("admin"))


def process_product_image(file_storage):
    """Optimise une image produit et retourne (bytes_webp, mime)."""
    if not file_storage or not file_storage.filename:
        return None, None

    filename = secure_filename(file_storage.filename)
    if "." not in filename:
        raise ValueError("Format d'image invalide.")

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_PRODUCT_IMAGE_EXTENSIONS:
        raise ValueError("Formats acceptés : JPG, PNG ou WEBP.")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_PRODUCT_IMAGE_BYTES:
        raise ValueError("L'image est trop lourde (6 Mo maximum).")

    try:
        image = Image.open(file_storage.stream).convert("RGB")
        image.thumbnail((720, 720))
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=84, method=6)
        return buffer.getvalue(), "image/webp"
    except Exception as exc:
        raise ValueError("Impossible de lire cette image.") from exc



def delete_product_image_file(image_path):
    if not image_path:
        return
    try:
        target = BASE_DIR / "static" / image_path
        if target.exists() and PRODUCT_UPLOAD_DIR in target.resolve().parents:
            target.unlink()
    except Exception:
        pass


@app.get("/product-image/<int:product_id>")
def product_image(product_id):
    db = get_db()
    row = db.execute(
        "SELECT image_blob, image_mime FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()
    db.close()

    if not row or not row["image_blob"]:
        return ("", 404)

    return send_file(
        io.BytesIO(row["image_blob"]),
        mimetype=row["image_mime"] or "image/webp",
        max_age=86400,
        conditional=True,
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
        current = db.execute(
            "SELECT image_path, image_blob FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

        if request.form.get("delete_image") == "1" and current:
            if current["image_path"]:
                delete_product_image_file(current["image_path"])
            db.execute(
                "UPDATE products SET image_path = NULL, image_blob = NULL, image_mime = NULL WHERE id = ?",
                (product_id,),
            )

        image_file = request.files.get("image")
        if image_file and image_file.filename:
            try:
                image_blob, image_mime = process_product_image(image_file)
                if current and current["image_path"]:
                    delete_product_image_file(current["image_path"])
                db.execute(
                    "UPDATE products SET image_blob = ?, image_mime = ?, image_path = NULL WHERE id = ?",
                    (image_blob, image_mime, product_id),
                )
            except ValueError as exc:
                db.rollback()
                db.close()
                flash(str(exc), "error")
                return redirect(request.referrer or url_for("admin_consumptions"))

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
    product = db.execute("SELECT id, name, image_path FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        db.close()
        flash("Boisson introuvable.", "error")
        return redirect(request.referrer or url_for("admin_consumptions"))

    db.execute("UPDATE consumptions SET product_id = NULL WHERE product_id = ?", (product_id,))
    delete_product_image_file(product["image_path"])
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
