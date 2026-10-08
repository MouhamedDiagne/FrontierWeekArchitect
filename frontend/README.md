# Interface Streamlit — Agiltym Feedback Copilot

L'interface Streamlit est maintenant connectée à l'API locale du projet. Elle
ne contacte jamais directement Microsoft Foundry ou Dataverse et ne contient
aucun identifiant Azure ou Dataverse.

## Lancer le POC local

Depuis la racine du projet, dans deux terminaux utilisant le même environnement
virtuel :

```powershell
# Terminal 1 : backend local
.\env\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2 : interface
.\env\Scripts\streamlit.exe run frontend/streamlit_app.py
```

Par défaut, Streamlit utilise `http://127.0.0.1:8000`. Pour une autre adresse
locale, définissez avant de lancer Streamlit :

```powershell
$env:FEEDBACK_API_URL = "http://127.0.0.1:8000"
```

## Fonctionnement

1. L'API initialise une seule instance de `FeedbackAnalyzerAgent` au démarrage.
2. Lors du premier message, Streamlit crée une conversation via
   `POST /api/conversations` et conserve seulement un identifiant public de
   session dans son état serveur.
3. Chaque message est transmis avec
   `POST /api/conversations/{session_id}/messages`.
4. L'API renvoie le texte de l'agent et, lorsqu'ils existent, les résultats
   structurés d'analyse unitaire ou d'insights. Streamlit les affiche sans les
   recalculer.
5. La barre d'actions en haut de la page contient
   **Nouvelle conversation**, **Dashboard** et **Historique**. Le premier ouvre une session
   locale sans effacer les conversations déjà affichées ; le second ouvre le
   dernier snapshot historique enregistré dans Dataverse, sans relancer le
   clustering ni les embeddings.
6. Le menu **Historique** permet de reprendre une conversation, y compris depuis
   le dashboard. La barre latérale a été supprimée. Les messages et
   l'identifiant de conversation sont conservés pour la session navigateur en cours.

Lorsqu'un rapport historique est demandé dans le chat, le backend construit
aussi un ensemble borné de KPI, graphiques et tables à partir des résultats
structurés. Streamlit les rend avec des modèles d'affichage locaux : il n'exécute jamais
du SQL, du Python ou une instruction graphique fournie par le modèle.

Les sessions sont volontairement en mémoire pour ce POC. La liste visible est
conservée seulement durant la session Streamlit courante et les conversations
distantes sont perdues si l'API redémarre ; il suffit alors de commencer une
nouvelle conversation.

Les questions rapides sont de vrais envois de messages : elles utilisent le
même flux que le champ de discussion. Pendant le traitement, l'indicateur
**Analyse en cours** est rendu dans une zone réservée au-dessus du composeur,
afin que le champ d'envoi reste stable et accessible.

Lorsqu'un rapport contient des visualisations, Streamlit peut les placer juste
après le paragraphe concerné grâce à un marqueur sûr tel que
`[[visual:priority-signals]]`. Les visualisations restantes sont rendues après
le texte. Seules les spécifications bornées et validées par le backend sont
acceptées ; aucune instruction graphique libre du modèle n'est exécutée.

Le thème clair est fixé dans `.streamlit/config.toml` à la racine du projet.
Les réponses utilisent le Markdown natif (HTML du modèle désactivé). Les KPI
affichent leurs unités ; un résultat inconnu affiche `—`. Une seule catégorie
est présentée dans une carte compacte, plusieurs catégories dans un graphique.
Les tableaux affichent les statuts en français et les textes longs sur plusieurs lignes.

Après la mise à jour, redémarrer l'API et Streamlit depuis la racine du projet.
L'environnement local vérifié utilise Streamlit 1.65.0. Si nécessaire :

```powershell
.\env\Scripts\python.exe -m pip install -r frontend/requirements.txt
```

Le [rapport de modifications](../docs/frontend_design_updates.md) détaille
les fonctions, les corrections de calcul, les tests et les actions de validation.

## Sécurité et périmètre

L'API est conçue pour un lancement local et doit rester liée à `127.0.0.1` à ce
stade. Ne l'exposez pas sur Internet et n'utilisez pas `--host 0.0.0.0` avant
d'avoir convenu d'une authentification et d'un déploiement adapté.

Le dashboard nécessite qu'au moins un snapshot ait été enregistré dans la table
Dataverse `agil_insightanalysis`. Consultez
`../docs/dataverse_insight_snapshots.md` avant d'activer cette persistance.

L'API expose aussi `POST /api/feedbacks` pour un test d'ingestion local, mais
elle ne doit pas être reliée à un formulaire public : elle n'a ni
authentification, ni idempotence, ni traçabilité de source dans ce POC.
Consultez `../docs/external_feedback_ingestion.md` avant toute intégration.

La planification automatique est fournie seulement sous forme de commande
locale. Consultez `../docs/scheduled_insights.md`; aucune Azure Function ni
Power Automate n'est déployé par ce projet.
