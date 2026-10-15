# Déploiement Azure App Service (POC)

Le POC est publié sous la forme de deux Web Apps Linux qui partagent le plan
App Service B1 existant `agiltym-feedback-analyzer-poc` :

| Web App | Rôle | Exposition |
|---|---|---|
| `feedback-analyzer-api` | API FastAPI, accès Foundry, Azure AI Language et Dataverse | Accessible pour le POC, mais protégée par un en-tête secret. |
| `feedback-analyzer-ui` | Interface Streamlit | Application utilisée par les visiteurs. |

## Protection POC de l'API

L'API démarre avec `APP_ENVIRONMENT=production`. Dans ce mode, elle refuse de
démarrer si `API_ACCESS_TOKEN` est absent. Toutes les routes `/api/...`
requièrent l'en-tête `X-Feedback-API-Key`. La route `/health` reste publique
pour permettre le contrôle de disponibilité d'Azure.

La Web App Streamlit conserve le même secret sous le nom
`FEEDBACK_API_TOKEN` et l'envoie depuis son processus serveur. Le navigateur
ne reçoit pas ce secret.

L'API reçoit aussi une identité managée système. Le script lui attribue le rôle
**Foundry User** sur la ressource Foundry. C'est nécessaire car le code crée
une version d'agent au démarrage puis utilise les modèles et l'Agent Service
via `DefaultAzureCredential`. Le rôle est attribué par son identifiant stable
`53ca6127-db72-4b80-b1b0-d745d6d5456d`, conformément aux recommandations
Foundry lors du changement de noms des rôles.

Ce mécanisme convient à ce POC, mais il ne remplace pas une authentification
utilisateur, une limitation de débit, une stratégie d'accès réseau ou une
traçabilité complète pour une application publique de production.

## Déployer

Depuis la racine du dépôt, après `az login` :

```powershell
.\scripts\deploy_app_service.ps1
```

Le script :

1. lit les paramètres existants dans `.env` sans les afficher ;
2. active l'identité managée système de l'API et lui accorde le rôle **Foundry
   User** sur la ressource Foundry ;
3. génère un jeton aléatoire en mémoire ;
4. place les paramètres Azure, Dataverse et Foundry uniquement dans la Web App
   API, puis le jeton dans les deux Web Apps ;
5. prépare deux archives ZIP temporaires sans `.env` et utilise
   `requirements-runtime.txt`, qui exclut les dépendances locales d'évaluation ;
6. déploie l'API et Streamlit avec Oryx ;
7. configure les commandes de démarrage Linux.

Les commandes configurées sont :

```text
# API
gunicorn --bind=0.0.0.0:8000 --workers=1 --timeout 300 --worker-class uvicorn.workers.UvicornWorker app.api:app

# Interface
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8000 --server.headless true
```

Après le premier déploiement, ouvrir l'URL indiquée par le script. L'API peut
prendre un peu plus de temps à être prête : au démarrage, elle crée le client
Foundry et l'agent partagé.

## Vérifier et diagnostiquer

```powershell
az webapp log tail --resource-group foundry-hackathon-rg-be997e27 --name feedback-analyzer-api
az webapp log tail --resource-group foundry-hackathon-rg-be997e27 --name feedback-analyzer-ui
```

La vérification minimale est `GET https://<hôte-api>/health`, puis une analyse
ou une soumission de feedback depuis l'interface Streamlit.

Les valeurs des paramètres d'application se modifient dans le portail via
**Web App → Variables d'environnement**. Ne jamais téléverser `.env`, ni
placer `DATAVERSE_CLIENT_SECRET`, les clés Azure AI Language, ou le jeton API
dans le dépôt Git.
