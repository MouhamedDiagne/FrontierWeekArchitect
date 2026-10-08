# Ingestion externe de feedbacks — POC local

## Objectif et périmètre

L'endpoint `POST /api/feedbacks` reçoit un feedback explicitement soumis par
une source technique (à terme, par exemple un formulaire), l'analyse avec le
même pipeline que l'assistant, puis l'enregistre dans Dataverse. Il ne crée pas
de conversation Foundry et ne demande pas au modèle si le feedback doit être
analysé : l'appel HTTP explicite constitue cette décision.

Cette capacité est livrée uniquement comme **frontière locale de POC**. Elle
permet de tester le contrat HTTP depuis PowerShell ou depuis un futur client
local. Elle ne constitue pas encore une intégration avec un formulaire public,
un CRM ou un outil tiers.

L'implémentation se trouve dans :

- `app/api.py` : modèle `FeedbackSubmission` et route `submit_feedback()` ;
- `app/agents.py` : méthode
  `FeedbackAnalyzerAgent.analyze_and_save_feedback()` ;
- `app/dataverse.py` : écriture de la ligne analysée dans
  `DataverseFeedbackRepository.save()`.

## Démarrage local

Le backend doit être démarré sur la boucle locale uniquement :

```powershell
.\env\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

La documentation interactive FastAPI est alors disponible à :

```text
http://127.0.0.1:8000/docs
```

Avant le test, le fichier `.env` du backend doit contenir les configurations
déjà utilisées par l'analyse unitaire de feedback :

```env
PROJECT_CONNECTION_STRING=...
MODEL_DEPLOYMENT_NAME=...
AZURE_AI_LANGUAGE_ENDPOINT=...
AZURE_AI_LANGUAGE_KEY=...

DATAVERSE_URL=...
DATAVERSE_TENANT_ID=...
DATAVERSE_CLIENT_ID=...
DATAVERSE_CLIENT_SECRET=...
DATAVERSE_FEEDBACK_TABLE=...
```

Cette route ne lance pas de clustering ni de rapport historique. Elle n'a donc
pas besoin de `EMBEDDING_MODEL_DEPLOYMENT_NAME` ni de
`DATAVERSE_INSIGHT_ANALYSIS_TABLE` pour fonctionner.

## Contrat HTTP

### Requête

```text
POST http://127.0.0.1:8000/api/feedbacks
Content-Type: application/json
```

Le corps JSON accepte exclusivement les propriétés suivantes :

| Champ | Type | Obligatoire | Règle |
| --- | --- | --- | --- |
| `software_id` | chaîne | Oui | Entre 1 et 80 caractères ; les espaces externes sont supprimés et la valeur est normalisée en minuscules. Elle doit correspondre à un logiciel connu du catalogue du projet lors de l'analyse. |
| `feedback` | chaîne | Oui | Entre 1 et 4 000 caractères ; les espaces externes sont supprimés ; une chaîne vide est refusée. |
| `received_at` | date-heure ISO 8601 | Non | Doit comporter un fuseau, par exemple `Z` ou `+00:00`. Elle est convertie en UTC. Sans valeur, le backend utilise l'heure UTC de réception. |

Les champs supplémentaires sont refusés. Une date sans fuseau (par exemple
`2026-10-07T09:30:00`) est volontairement invalide afin d'éviter une date
ambigüe dans Dataverse.

Exemple :

```json
{
  "software_id": "targetym_ai",
  "feedback": "Depuis la mise à jour, l'export du rapport Pilotage produit un fichier vide.",
  "received_at": "2026-10-07T09:30:00Z"
}
```

### Réponse réussie

Une soumission complètement analysée **et enregistrée** retourne `201 Created`.
La réponse ne renvoie jamais le commentaire brut ; elle renvoie l'analyse
structurée et l'identifiant de la ligne Dataverse créée :

```json
{
  "analysis": {
    "sentiment": "negative",
    "percentage": 0.98,
    "language": "fr",
    "software": {
      "id": "targetym_ai",
      "name": "Targetym AI"
    },
    "feedback_type": "issue_report",
    "feedback_summary": "L'export du rapport Pilotage génère un fichier vide depuis la dernière mise à jour.",
    "primary_functionality": {
      "id": "reporting",
      "name": "Pilotage et reporting"
    },
    "problem_category": "data_quality_reporting"
  },
  "feedback_record_id": "<identifiant-Dataverse>"
}
```

`primary_functionality` et `problem_category` peuvent être `null` lorsqu'ils
ne s'appliquent pas à la nature du feedback. Les valeurs exactes dépendent du
catalogue de fonctionnalités et de l'analyse validée ; l'exemple ci-dessus
n'est pas une promesse de classification.

## Cycle d'exécution exact

1. FastAPI valide le corps avec `FeedbackSubmission`, qui étend
   `FeedbackInput` dans `app/api.py`. Une requête invalide n'atteint jamais
   l'agent.
2. La route `submit_feedback()` appelle
   `FeedbackAgentRuntime.submit_feedback()`. Un verrou de processus sérialise
   l'exécution avec les conversations du POC.
3. Le runtime appelle
   `FeedbackAnalyzerAgent.analyze_and_save_feedback()` dans `app/agents.py`,
   sans créer de `ConversationSession`.
4. Cette méthode valide de nouveau `software_id` et `feedback`, normalise
   `received_at` en UTC, puis exécute directement `analyze_feedback()`.
5. `analyze_feedback()` applique le pipeline de référence : Azure AI Language
   détecte la langue et le sentiment ; le modèle Foundry extrait la
   fonctionnalité principale, le type de feedback, la catégorie de problème
   si elle est applicable, et un résumé clair.
6. Après validation Pydantic de l'analyse, `_persist_analysis()` appelle
   `DataverseFeedbackRepository.save()`. Dataverse reçoit le commentaire brut,
   les dates de réception et d'analyse, le logiciel et les attributs enrichis.
7. Si l'écriture retourne un identifiant, l'API répond `201` avec
   `FeedbackSubmissionResult` (`analysis` et `feedback_record_id`).

L'analyse et la sauvegarde sont une seule opération applicative séquentielle,
mais pas une transaction distribuée. Si l'analyse réussit puis que Dataverse
refuse l'écriture, le client reçoit une erreur et aucun identifiant de ligne
n'est retourné, même si l'analyse a bien eu lieu en mémoire.

## Tests PowerShell locaux

### Soumission complète

Dans un second terminal PowerShell, après le démarrage de l'API :

```powershell
$body = @{
    software_id = "targetym_ai"
    feedback = "Depuis la mise à jour, l'export du rapport Pilotage produit un fichier vide."
    received_at = "2026-10-07T09:30:00Z"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/feedbacks" `
    -ContentType "application/json; charset=utf-8" `
    -Body $body
```

Vérifier ensuite que :

1. PowerShell affiche `analysis` et `feedback_record_id` ;
2. les traces backend indiquent l'analyse puis la création du record ;
3. une ligne apparaît dans `DATAVERSE_FEEDBACK_TABLE` avec le commentaire, le
   logiciel, les attributs analysés et les dates UTC.

### Horodatage automatique

Pour laisser le backend attribuer l'heure UTC de réception :

```powershell
$body = @{
    software_id = "dealym_crm"
    feedback = "La création d'une opportunité est beaucoup plus rapide depuis la dernière version."
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/feedbacks" `
    -ContentType "application/json; charset=utf-8" `
    -Body $body
```

### Vérification de validation

Une date sans fuseau doit être refusée par une réponse `422` :

```powershell
$body = @{
    software_id = "targetym_ai"
    feedback = "Test de validation de date."
    received_at = "2026-10-07T09:30:00"
} | ConvertTo-Json

try {
    Invoke-WebRequest `
        -Method Post `
        -Uri "http://127.0.0.1:8000/api/feedbacks" `
        -ContentType "application/json; charset=utf-8" `
        -Body $body
} catch {
    $_.Exception.Response.StatusCode.value__
}
```

## Erreurs et diagnostic

| Statut | Situation | Comportement client |
| --- | --- | --- |
| `201 Created` | Analyse et écriture Dataverse réussies | Exploiter `analysis` et conserver `feedback_record_id`. |
| `422 Unprocessable Entity` | JSON, champ, longueur, valeur vide ou `received_at` invalide | Corriger le payload ; aucun appel Azure, Foundry ou Dataverse n'est lancé. |
| `503 Service Unavailable` | Démarrage incomplet, indisponibilité Foundry/Azure Language/Dataverse, quota, ou autre erreur runtime | Réponse générique : `The feedback service is temporarily unavailable. Please try again.` Consulter les logs du backend ; les détails techniques ne sont pas exposés au client. |

La version POC ne traduit pas encore certains cas en statuts spécialisés : par
exemple une limitation de quota du modèle est actuellement renvoyée comme
`503`, et non comme `429`. Les messages détaillés et les commentaires sont
réservés aux logs serveur ; ils ne doivent pas être copiés dans un client ou un
formulaire.

## Sécurité et limites POC

- L'API est sûre seulement si elle est lancée avec `--host 127.0.0.1`. Le code
  FastAPI ne bloque pas à lui seul un lancement sur `0.0.0.0` : ne modifiez pas
  cette adresse et n'exposez pas ce port à un réseau ou à Internet.
- Il n'existe ni authentification HTTP, ni autorisation par rôle, ni gestion de
  CORS pour un navigateur tiers. Toute personne pouvant joindre l'endpoint
  pourrait soumettre des données et provoquer des appels Azure/Dataverse.
- Aucun formulaire public, webhook ou connecteur externe n'est activé par ce
  POC. Ne configurez pas un outil tiers pour appeler cette URL locale.
- Il n'y a pas encore de clé d'idempotence, de référence de soumission externe
  ni de journal de provenance. Un retry client après un délai ou une erreur
  incertaine peut créer un doublon Dataverse.
- Le backend stocke le commentaire brut dans la table de feedbacks pour
  permettre les analyses ultérieures. Le transport et la conservation de ces
  données doivent respecter les règles internes de confidentialité et de
  protection des données.
- Les requêtes sont sérialisées dans le processus pour rester déterministes et
  limiter les collisions du POC. Cette route n'est pas conçue pour un débit de
  production, ni pour absorber du spam ou des pics de formulaire.

## Décisions à prendre avant une vraie intégration de formulaire

Avant d'autoriser une source externe, il faut valider explicitement les choix
suivants. Ils ne sont volontairement pas implémentés dans ce POC :

1. **Source et identité** : type de formulaire, système émetteur, mode
   d'authentification, identité de l'utilisateur ou du service appelant, et
   méthode fiable pour choisir `software_id` plutôt que de faire confiance à
   une valeur libre du navigateur.
2. **Hébergement sécurisé** : adresse publique ou privée, HTTPS, filtrage
   réseau, gestion des origines CORS et stockage exclusif des secrets côté
   backend. Le frontend ne doit jamais recevoir les secrets Foundry, Azure AI
   Language ou Dataverse.
3. **Déduplication et traçabilité** : clé d'idempotence, identifiant externe de
   soumission, nom de la source et stratégie de retry. Ces informations
   impliqueront probablement des colonnes Dataverse supplémentaires et une
   évolution de contrat à décider avant développement.
4. **Protection des données** : informations personnelles autorisées,
   consentement, durée de conservation, politique de suppression, masquage ou
   détection de PII, et rôles Dataverse pouvant lire le commentaire brut.
5. **Résilience et exploitation** : limitation de débit, anti-spam, files ou
   retries contrôlés, réponse utilisateur en cas d'échec, suivi des erreurs et
   responsabilité de correction des doublons.
6. **Droits Dataverse** : l'utilisateur d'application doit au minimum disposer
   des privilèges nécessaires à la création de lignes dans
   `DATAVERSE_FEEDBACK_TABLE`, ainsi que des droits déjà requis par le modèle
   de table. Ne pas lui attribuer `System Administrator` pour contourner un
   refus de privilège.

Après ces décisions, l'intégration devra faire l'objet d'une étape dédiée :
choix de l'exposition du backend, mise en place de l'authentification, extension
contrôlée du modèle Dataverse et tests de soumission/retry. Aucun de ces
changements ne doit être déduit ou activé automatiquement à partir de ce
document.
