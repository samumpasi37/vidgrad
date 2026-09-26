# VidGrab — Backend

## Contenu
- `app.py` — API Flask complète (téléchargement yt-dlp, abonnements, SSV AdMob, admin panel)
- `requirements.txt` — dépendances Python
- `Procfile` — commande de démarrage pour Render/Railway
- `.gitignore`

## Déploiement sur Render.com (gratuit)

1. Crée un repo GitHub et pousse ce dossier dedans :
   ```
   git init
   git add .
   git commit -m "Premier déploiement"
   git remote add origin https://github.com/TON_COMPTE/TON_REPO.git
   git branch -M main
   git push -u origin main
   ```

2. Sur render.com : **New +** → **Web Service** → connecte le repo.
   - Build Command : `pip install -r requirements.txt`
   - Start Command : `gunicorn app:app`
   - Plan : Free

3. Dans **Environment**, ajoute tes variables :
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `ADMIN_PASSWORD`

4. Une fois déployé, ton URL sera du type :
   ```
   https://ton-app.onrender.com
   ```

## Routes disponibles

| Route | Méthode | Rôle |
|---|---|---|
| `/` | GET | Vérifier que le serveur tourne |
| `/info` | POST | Récupérer infos/formats d'une vidéo |
| `/download` | POST | Télécharger une vidéo |
| `/verify-purchase` | POST | Activer un abonnement après achat |
| `/ssv/rewarded-callback` | GET | Callback AdMob (pub récompensée) |
| `/pending-payment` | POST | Créer une demande de paiement manuel |
| `/admin?password=...` | GET | Panel pour activer les paiements manuels |

## Tables Supabase nécessaires

Voir les scripts SQL fournis précédemment dans la conversation :
`subscriptions`, `pending_payments`, `ad_rewards`.

## Important avant mise en production

- Ajouter la vérification réelle des achats Google Play dans `verify_purchase()`.
- Ajouter la vérification de signature Google dans `rewarded_callback()`.
- Changer `ADMIN_PASSWORD` par une valeur forte, en variable d'environnement uniquement.
- Installer `ffmpeg` sur le serveur pour la fusion audio/vidéo en HD (sur Render, utiliser un buildpack ou une image Docker personnalisée si besoin).
