# Intégration Streamlit et API locale

## Objectif POC

Cette étape ajoute une frontière HTTP locale entre la maquette Streamlit et le
moteur Python existant. Elle n'ajoute ni ressource Azure, ni service externe
déployé. La persistance du dashboard réutilise uniquement la table Dataverse
optionnelle des snapshots documentée dans `dataverse_insight_snapshots.md`.

Le backend reste responsable des identifiants, de l'accès Foundry, de
l'enregistrement Dataverse et des appels d'outils. Streamlit est uniquement un
client HTTP d'affichage et de saisie.

## Endpoints

| Méthode | Route | Rôle |
| --- | --- | --- |
| `GET` | `/health` | État du processus API local ; son handler ne déclenche aucun appel Foundry ou Dataverse. |
| `POST` | `/api/conversations` | Crée une session POC en mémoire. |
| `POST` | `/api/conversations/{session_id}/messages` | Envoie un message validé à l'agent et retourne `ConversationTurnResult`. |
| `DELETE` | `/api/conversations/{session_id}` | Ferme la conversation Foundry et efface la session mémoire. |
| `POST` | `/api/feedbacks` | Analyse et sauvegarde un feedback explicitement soumis, sans créer de conversation. |
| `GET` | `/api/dashboard/latest` | Lit le dernier snapshot Dataverse et ses visualisations déterministes, sans relancer de clustering. |

Le schéma de réponse d'un message est le modèle existant
`ConversationTurnResult`. Il peut contenir `reply`, `analysis`,
`feedback_record_id`, `insights`, `audience_report`, `insight_snapshot_id` et,
pour un rapport historique, `visualizations`.

`POST /api/feedbacks` accepte `software_id`, `feedback` et optionnellement
`received_at` (ISO 8601 avec fuseau horaire). Il renvoie une analyse structurée
et `feedback_record_id`. Cette route est destinée à la future couche de
connecteurs, mais reste strictement locale et non authentifiée dans ce POC.

`GET /api/dashboard/latest` retourne le snapshot le plus récent ainsi qu'un
contrat de visualisation borné. Les types permis sont des KPI, graphiques en
barres ou lignes, distribution et table. Les données sont calculées par le
backend à partir des résultats d'insights déjà validés ; aucun SQL, code Python
ou instruction libre n'est produit ou exécuté par le modèle.

Chaque spécification porte un identifiant stable, un titre, une légende et une
caption. Le backend sélectionne les graphiques selon le profil du rapport et
les signaux disponibles plutôt que d'envoyer une galerie fixe. Le modèle reçoit
un guide compact de placement et peut insérer `[[visual:<id>]]` après le
paragraphe concerné. Streamlit ne rend qu'une spécification correspondante ;
les éléments non ancrés restent visibles après le texte.

Les sélecteurs de profil et de périmètre visibles dans la maquette Streamlit ne
filtrent pas encore l'API. Le dashboard affiche le profil et le périmètre qui
ont été enregistrés dans le dernier snapshot ; la sélection de ces paramètres
est aujourd'hui réalisée au cours de la conversation ou par les arguments du
job planifié.

## Cycle de vie

L'endpoint `/health` ne sonde pas les dépendances distantes à chaque appel.
En revanche, le cycle de vie FastAPI initialise l'agent et les dépôts avant que
l'API soit prête : un démarrage qui échoue à joindre ou configurer Foundry ou
Dataverse empêche donc aussi d'obtenir un état `ready`.

Au démarrage, `FeedbackAgentRuntime.start()` crée une seule instance de
`DataverseFeedbackRepository`, puis une seule version de
`FeedbackAnalyzerAgent`. L'agent n'est donc pas recréé à chaque requête.

Les sessions HTTP sont des UUID publics qui pointent vers les
`ConversationSession` réelles. Elles restent privées au processus et sont
sérialisées par un verrou : deux messages d'une même interface ne peuvent pas
inverser l'ordre d'une conversation Foundry.

Le menu **Historique** de l'en-tête conserve une liste de conversations seulement durant la
session Streamlit courante et permet de reprendre l'une d'elles. La barre latérale est supprimée. **Nouvelle
conversation** ajoute une nouvelle entrée sans supprimer les précédentes. Ce
n'est pas un historique persistant : après le redémarrage de Streamlit ou de
l'API, une session distante peut ne plus être disponible et l'interface invite
alors à recommencer une conversation.

À l'arrêt, les conversations connues sont fermées, puis
`FeedbackAnalyzerAgent.cleanup()` est appelé. Un arrêt brutal peut néanmoins
interrompre ce nettoyage : pour un POC local, il est acceptable de supprimer
ultérieurement toute version temporaire devenue inutilisée dans Foundry.

Le dashboard n'appelle jamais le service de clustering à l'ouverture de la
page. Il lit uniquement le dernier `FeedbackInsightsSnapshot` conservé dans
Dataverse. Si aucun snapshot n'existe, Streamlit affiche un état vide et invite
l'utilisateur à demander d'abord un rapport historique dans l'assistant.

Une visualisation est construite automatiquement après l'exécution réussie de
l'outil d'insights. L'agent décide de demander ou non l'analyse historique ;
lorsqu'elle est exécutée, le backend transforme ses résultats structurés en
spécifications de graphiques sûres. Streamlit les affiche avec ses composants
natifs, sans interpréter de code généré par le LLM.

## Vérification locale

1. Vérifier que `.env` contient les configurations Foundry, Azure Language et
   Dataverse déjà utilisées par l'application CLI.
2. Démarrer l'API sur `127.0.0.1:8000` avec la commande indiquée dans le
   README du frontend.
3. Ouvrir `http://127.0.0.1:8000/docs` : FastAPI affiche les routes locales.
4. Démarrer Streamlit, envoyer un message général, puis une demande explicite
   d'analyse de feedback.
5. Utiliser **Nouvelle conversation** et vérifier qu'une nouvelle session est
   créée au prochain message.
6. Lorsque la table de snapshots est configurée, demander un rapport historique
   puis ouvrir **Dashboard** : le dashboard doit afficher le dernier snapshot
   sans effectuer de nouvel appel d'embeddings.
7. Tester, si nécessaire, la soumission technique locale avec `POST
   /api/feedbacks`; consulter `external_feedback_ingestion.md` avant de relier
   un formulaire.

## Intervention externe requise

Aucune pour le chat et l'analyse unitaire tant que l'API et Streamlit restent
sur la machine locale. Pour le dashboard persistant et le script planifié, il
faut créer la table Dataverse de snapshots et attribuer ses droits Create/Read
à l'utilisateur applicatif ; voir `dataverse_insight_snapshots.md`.

Une authentification, un hébergement Azure, une exposition réseau ou une
intégration avec un formulaire externe nécessitent une décision et une
configuration séparées. Ne lancez pas l'API avec `--host 0.0.0.0` et ne donnez
pas l'URL actuelle à un service tiers : aucune protection contre les appels non
autorisés ni déduplication de formulaires n'est encore en place.
