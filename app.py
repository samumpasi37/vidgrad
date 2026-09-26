import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_file, render_template_string, redirect
import yt_dlp

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────
app = Flask(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change_moi")

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "facebook.com", "fb.watch",
    "instagram.com",
    "tiktok.com",
]

# Supabase est optionnel au démarrage : si les variables ne sont pas encore
# configurées, l'app démarre quand même (utile pour le premier déploiement).
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Supabase non initialisé: {e}")


def is_supported(url: str) -> bool:
    return bool(url) and any(domain in url for domain in SUPPORTED_DOMAINS)


# ──────────────────────────────────────────────────────────────
# Routes de base
# ──────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({
        "status": "en ligne",
        "message": "Backend VidGrab",
        "supabase_configure": supabase is not None,
    })


@app.route("/info", methods=["POST"])
def get_info():
    url = request.json.get("url") if request.is_json else None
    if not is_supported(url):
        return jsonify({"error": "URL manquante ou non supportée"}), 400

    ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = [
                {
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution", "audio"),
                    "filesize": f.get("filesize"),
                }
                for f in info.get("formats", [])
                if f.get("vcodec") != "none" or f.get("acodec") != "none"
            ]
            return jsonify({
                "platform": info.get("extractor_key"),
                "title": info.get("title"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader"),
                "formats": formats,
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download", methods=["POST"])
def download():
    data = request.json or {}
    url = data.get("url")
    format_id = data.get("format_id", "best")
    user_id = data.get("userId")

    if not is_supported(url):
        return jsonify({"error": "URL manquante ou non supportée"}), 400

    # Restriction qualité pour les utilisateurs gratuits
    is_premium = check_subscription(user_id) if user_id else False
    has_ad_reward = check_recent_ad_reward(user_id) if user_id else False

    if not is_premium and not has_ad_reward:
        format_id = "best[height<=480]"
    elif has_ad_reward and not is_premium:
        consume_ad_reward(user_id)

    file_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    ydl_opts = {
        "format": format_id,
        "outtmpl": output_path,
        "quiet": True,
        "merge_output_format": "mp4",
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return send_file(filename, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────
# Abonnement — vérification d'achat (Google Play)
# ──────────────────────────────────────────────────────────────
@app.route("/verify-purchase", methods=["POST"])
def verify_purchase():
    if supabase is None:
        return jsonify({"error": "Supabase non configuré"}), 500

    data = request.json or {}
    token = data.get("purchaseToken")
    product_id = data.get("productId")
    user_id = data.get("userId")

    # NOTE: implémente ici la vérification réelle auprès de Google Play
    # Developer API avant d'activer l'abonnement en production.
    is_valid, expiry = True, (datetime.utcnow() + timedelta(days=30)).isoformat()

    if is_valid:
        supabase.table("subscriptions").upsert({
            "user_id": user_id,
            "product_id": product_id,
            "platform": "android",
            "purchase_token": token,
            "expiry_date": expiry,
            "status": "active",
        }).execute()
        return jsonify({"success": True})

    return jsonify({"success": False}), 400


def check_subscription(user_id: str) -> bool:
    if supabase is None or not user_id:
        return False
    result = (
        supabase.table("subscriptions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .gte("expiry_date", datetime.utcnow().isoformat())
        .execute()
    )
    return len(result.data) > 0


# ──────────────────────────────────────────────────────────────
# SSV — Vérification côté serveur des pubs récompensées AdMob
# ──────────────────────────────────────────────────────────────
@app.route("/ssv/rewarded-callback", methods=["GET"])
def rewarded_callback():
    if supabase is None:
        return "Supabase non configuré", 500

    args = request.args
    transaction_id = args.get("transaction_id")
    user_id = args.get("user_id")
    reward_item = args.get("reward_item")

    if not transaction_id or not user_id:
        return "Paramètres manquants", 400

    # TODO production : vérifier la signature Google avant d'accepter la requête
    existing = (
        supabase.table("ad_rewards")
        .select("*")
        .eq("transaction_id", transaction_id)
        .execute()
    )
    if existing.data:
        return "OK", 200

    supabase.table("ad_rewards").insert({
        "user_id": user_id,
        "transaction_id": transaction_id,
        "reward_item": reward_item,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
    }).execute()

    return "OK", 200


def check_recent_ad_reward(user_id: str) -> bool:
    if supabase is None or not user_id:
        return False
    result = (
        supabase.table("ad_rewards")
        .select("*")
        .eq("user_id", user_id)
        .gte("expires_at", datetime.utcnow().isoformat())
        .execute()
    )
    return len(result.data) > 0


def consume_ad_reward(user_id: str):
    if supabase is None:
        return
    supabase.table("ad_rewards").delete().eq("user_id", user_id).execute()


# ──────────────────────────────────────────────────────────────
# Paiement manuel (WhatsApp) — panel admin
# ──────────────────────────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.args.get("password") != ADMIN_PASSWORD:
            return "Accès refusé", 403
        return f(*args, **kwargs)
    return wrapper


ADMIN_TEMPLATE = """
<h2>Demandes de paiement en attente</h2>
<table border="1" cellpadding="8">
  <tr><th>Utilisateur</th><th>Montant</th><th>Date</th><th>Action</th></tr>
  {% for p in pending %}
  <tr>
    <td>{{ p.user_id }}</td>
    <td>{{ p.amount }}$</td>
    <td>{{ p.created_at }}</td>
    <td>
      <a href="/admin/approve/{{ p.id }}?password={{ password }}">Activer</a> |
      <a href="/admin/reject/{{ p.id }}?password={{ password }}">Rejeter</a>
    </td>
  </tr>
  {% endfor %}
</table>
"""


@app.route("/admin")
@require_auth
def admin_panel():
    if supabase is None:
        return "Supabase non configuré", 500
    result = (
        supabase.table("pending_payments")
        .select("*")
        .eq("status", "pending")
        .execute()
    )
    return render_template_string(
        ADMIN_TEMPLATE, pending=result.data, password=request.args.get("password")
    )


@app.route("/admin/approve/<payment_id>")
@require_auth
def approve(payment_id):
    payment = (
        supabase.table("pending_payments")
        .select("*")
        .eq("id", payment_id)
        .single()
        .execute()
    )
    user_id = payment.data["user_id"]
    expiry = (datetime.utcnow() + timedelta(days=30)).isoformat()

    supabase.table("subscriptions").upsert({
        "user_id": user_id,
        "status": "active",
        "expiry_date": expiry,
    }).execute()

    supabase.table("pending_payments").update({
        "status": "approved",
        "approved_at": datetime.utcnow().isoformat(),
    }).eq("id", payment_id).execute()

    return redirect(f"/admin?password={ADMIN_PASSWORD}")


@app.route("/admin/reject/<payment_id>")
@require_auth
def reject(payment_id):
    supabase.table("pending_payments").update({"status": "rejected"}).eq(
        "id", payment_id
    ).execute()
    return redirect(f"/admin?password={ADMIN_PASSWORD}")


@app.route("/pending-payment", methods=["POST"])
def create_pending_payment():
    if supabase is None:
        return jsonify({"error": "Supabase non configuré"}), 500
    data = request.json or {}
    supabase.table("pending_payments").insert({
        "user_id": data.get("userId"),
        "amount": data.get("amount", 4),
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }).execute()
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
