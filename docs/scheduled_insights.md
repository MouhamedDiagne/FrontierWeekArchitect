# Exécuter une analyse d'insights planifiée (POC)

## Objet et limites

`python -m app.insight_job` exécute **une** analyse historique directement
depuis le poste ou le serveur où se trouve le projet. Il lit les feedbacks
enrichis dans Dataverse, lance le clustering temporaire existant, construit le
rapport correspondant au profil demandé, puis crée un instantané dans la table
Dataverse des analyses d'insights.

Ce point d'entrée est volontairement réduit au périmètre POC : il ne passe pas
par une conversation utilisateur, ne crée pas de tâche Windows, ne relance pas
automatiquement un échec et ne modifie aucun feedback source. Chaque exécution
réussie crée un nouvel instantané immuable.

Le job utilise la même logique applicative que l'agent :

1. `run_historical_insight_job()` crée les dépôts Dataverse et prépare les
   clients Foundry nécessaires, sans créer de version d'agent ;
2. `FeedbackAnalyzerAgent.run_historical_analysis()` récupère les feedbacks,
   calcule les insights et produit le rapport d'audience ;
3. `DataverseInsightAnalysisRepository.save_snapshot()` écrit l'instantané ;
4. le job ferme l'agent dans tous les cas, puis retourne un résumé JSON au
   planificateur.

Le job ne crée ni conversation ni version temporaire d'agent Foundry. Il ne
demande pas non plus au modèle de décider s'il faut analyser les données : la
fréquence, le périmètre et le profil d'audience sont explicitement fournis en
arguments. Cela évite d'utiliser inutilement une conversation Foundry pour un
traitement batch.

## Prérequis locaux

Exécuter la commande depuis la racine du dépôt, dans le même environnement
virtuel Python que l'application :

```powershell
cd "C:\Users\Dell\Desktop\AGILTYM\FDE Roadmap\microsoft_transformation_week\mini project 3"
.\env\Scripts\python.exe -m app.insight_job --help
```

Le module charge automatiquement le fichier `.env` situé à la racine du projet.
Ne placez pas de secrets dans la commande, dans le planificateur, dans un script
versionné ou dans la sortie de log.

Les variables suivantes doivent déjà être configurées :

```dotenv
# Microsoft Foundry : agent, modèle de rédaction et embeddings
PROJECT_CONNECTION_STRING=<chaîne de connexion du projet Foundry>
MODEL_DEPLOYMENT_NAME=<nom exact du déploiement de chat>
AZURE_OPENAI_ENDPOINT=https://<ressource>.openai.azure.com
EMBEDDING_MODEL_DEPLOYMENT_NAME=<nom exact du déploiement d'embeddings>

# Dataverse : lecture des feedbacks et création de l'instantané
DATAVERSE_URL=https://<organisation>.crm.dynamics.com
DATAVERSE_TENANT_ID=<tenant-id>
DATAVERSE_CLIENT_ID=<application-client-id>
DATAVERSE_CLIENT_SECRET=<secret-value>
DATAVERSE_FEEDBACK_TABLE=<nom logique de la table feedback>
DATAVERSE_INSIGHT_ANALYSIS_TABLE=agil_insightanalysis
```

`AZURE_OPENAI_ENDPOINT` et `EMBEDDING_MODEL_DEPLOYMENT_NAME` sont obligatoires
pour le clustering : le premier indique au client OpenAI compatible où joindre
le déploiement d'embeddings, le second sélectionne ce déploiement. Si
`CLUSTER_LABELING_ENABLED=true`, le déploiement référencé par
`CLUSTER_LABEL_MODEL_DEPLOYMENT_NAME` doit aussi être disponible ; à défaut,
la valeur de `MODEL_DEPLOYMENT_NAME` est utilisée. Les paramètres de clustering
existants (`CLUSTER_MAX_FEEDBACKS`, `CLUSTER_MIN_SIZE`, etc.) continuent de
s'appliquer au job.

Le compte applicatif Entra ID utilisé par les variables Dataverse doit pouvoir :

- lire la table indiquée par `DATAVERSE_FEEDBACK_TABLE` ;
- créer et lire la table indiquée par `DATAVERSE_INSIGHT_ANALYSIS_TABLE`.

Les détails de la table d'instantanés, de ses colonnes et des privilèges sont
documentés dans [dataverse_insight_snapshots.md](dataverse_insight_snapshots.md).
Sans `DATAVERSE_INSIGHT_ANALYSIS_TABLE`, le job échoue volontairement : un job
planifié n'est considéré comme réussi que si son résultat est durablement
enregistré.

## Lancer une analyse manuellement

Les dates sont obligatoirement ISO 8601 avec un fuseau horaire explicite. La
période est semi-ouverte : `start-date` est inclus et `end-date` est exclu.
Utilisez `Z` pour travailler en UTC et éviter toute ambiguïté lors du passage à
l'heure d'été.

Exemple : analyse mensuelle de Targetym AI destinée au management.

```powershell
.\env\Scripts\python.exe -m app.insight_job `
  --start-date "2026-10-01T00:00:00Z" `
  --end-date "2026-11-01T00:00:00Z" `
  --software-id targetym_ai `
  --audience-profile management `
  --source manual `
  --verbose
```

Les profils acceptés sont : `management`, `it`, `marketing` et
`support_sales`. Les filtres `--software-id` et `--functionality-id` sont
optionnels ; leur valeur doit correspondre aux identifiants canoniques déjà
employés dans le projet, et non à un libellé libre.

Exemple avec une période de comparaison complète :

```powershell
.\env\Scripts\python.exe -m app.insight_job `
  --start-date "2026-10-01T00:00:00Z" `
  --end-date "2026-11-01T00:00:00Z" `
  --comparison-start-date "2026-09-01T00:00:00Z" `
  --comparison-end-date "2026-10-01T00:00:00Z" `
  --software-id targetym_ai `
  --audience-profile it `
  --source manual
```

Les deux arguments de comparaison doivent toujours être fournis ensemble. Le
job valide également les bornes de période avant de contacter Foundry ou
Dataverse.

## Sortie JSON et codes de sortie

Sans `--verbose`, la sortie standard contient une seule ligne JSON compacte,
adaptée à une collecte par un planificateur :

```json
{
  "status": "completed",
  "snapshot_id": "<identifiant Dataverse>",
  "source": "scheduled",
  "audience_profile": "management",
  "scope": {
    "start_date": "2026-10-01T00:00:00Z",
    "end_date": "2026-11-01T00:00:00Z",
    "comparison_start_date": null,
    "comparison_end_date": null,
    "software_id": "targetym_ai",
    "functionality_id": null
  },
  "metrics": {
    "total_feedbacks": 42,
    "clustered_feedbacks": 31,
    "cluster_count": 4
  }
}
```

Cette sortie ne contient ni commentaire brut, ni secret, ni contenu intégral
des clusters. Le rapport complet est conservé dans l'instantané Dataverse.
Avec `--verbose`, les messages de progression sont aussi écrits avant ce JSON
sur la sortie standard : ne parsez donc pas cette sortie comme un document JSON
unique dans ce mode. Les diagnostics `[ERROR]` sont écrits sur la sortie
d'erreur ; ils restent côté processus et ne doivent pas être copiés vers une
interface publique.

| Code | Signification | Action recommandée |
| --- | --- | --- |
| `0` | Analyse et persistance terminées. | Contrôler occasionnellement l'instantané Dataverse créé. |
| `2` | Arguments invalides ou période incohérente. | Corriger les options et les dates de la tâche. |
| `3` | Initialisation impossible. | Vérifier `.env`, accès Foundry, accès Dataverse et la table d'instantanés. |
| `4` | Analyse, embeddings, clustering ou persistance en échec. | Consulter le diagnostic `[ERROR]`, puis résoudre la cause avant une nouvelle exécution. |
| `5` | Analyse réussie, mais nettoyage de l'agent en échec. | Vérifier les logs ; l'instantané peut déjà exister. |
| `130` | Interruption manuelle du processus. | Relancer seulement après avoir vérifié qu'aucune exécution équivalente n'est encore en cours. |

Un échec ne déclenche pas de mécanisme de retry dans le code POC. Cela évite
de créer des exécutions concurrentes ou des instantanés multiples sans règle
d'idempotence explicitement définie.

## Nettoyage et sécurité d'exécution

Le job appelle `agent.cleanup()` dans un bloc `finally`, y compris si
l'initialisation, les embeddings, Dataverse ou le clustering échouent. Le
nettoyage libère le client Foundry créé pour l'exécution locale. Si une erreur
principale existe déjà, elle reste l'erreur remontée ; un problème de nettoyage
est alors ajouté au diagnostic sans masquer la cause initiale.

Ne lancez pas deux jobs dont les périodes se chevauchent volontairement au
même moment. Le modèle de données accepte plusieurs instantanés, mais le POC
ne déduplique pas ces résultats et ne verrouille pas les analyses concurrentes.
Pour une cadence quotidienne ou hebdomadaire, laissez une marge suffisante
entre l'heure de déclenchement et la durée observée du job.

## Préparer une tâche dans le Planificateur de tâches Windows

La création de la tâche est une action externe à faire par l'administrateur du
poste ou du serveur. Le projet **ne crée aucune tâche automatiquement**.

1. Vérifier d'abord la commande manuelle avec `--source manual` et confirmer
   qu'un instantané est présent dans Dataverse.
2. Ouvrir **Planificateur de tâches** (`taskschd.msc`) puis choisir **Créer une
   tâche** — pas *Créer une tâche de base* — afin de régler précisément le
   compte, le dossier de travail et les journaux.
3. Dans **Général**, donner un nom explicite, par exemple
   `Feedback Insights - Targetym AI - Daily`. Utiliser un compte de service ou
   un compte Windows dédié ayant accès au dossier du projet et au réseau.
4. Dans **Déclencheurs**, choisir la cadence POC désirée (par exemple tous les
   jours à 01:15). Commencer par une cadence quotidienne ; ne planifier une
   exécution horaire qu'après avoir mesuré le volume de feedbacks, la durée et
   la consommation de tokens.
5. Dans **Actions**, choisir *Démarrer un programme* et renseigner :

   | Champ Windows | Valeur exemple |
   | --- | --- |
   | Programme/script | `C:\Users\Dell\Desktop\AGILTYM\FDE Roadmap\microsoft_transformation_week\mini project 3\env\Scripts\python.exe` |
   | Ajouter des arguments | `-m app.insight_job --start-date "2026-10-01T00:00:00Z" --end-date "2026-11-01T00:00:00Z" --software-id targetym_ai --audience-profile management --source scheduled --verbose` |
   | Démarrer dans | `C:\Users\Dell\Desktop\AGILTYM\FDE Roadmap\microsoft_transformation_week\mini project 3` |

   Les dates de l'exemple sont fixes pour illustrer le contrat. Avant de créer
   une tâche récurrente, il faut décider comment calculer dynamiquement la
   fenêtre journalière, hebdomadaire ou mensuelle. Le CLI POC attend des dates
   explicites et n'interprète pas des expressions telles que « hier ».

6. Dans **Conditions** et **Paramètres**, éviter les exécutions parallèles :
   sélectionner l'option équivalente à *Ne pas démarrer une nouvelle instance*
   si une instance est déjà en cours. Prévoir aussi un délai maximal raisonnable
   et conserver un historique de tâches activé pendant la phase de test.
7. Exécuter la tâche manuellement depuis le Planificateur, puis vérifier le
   code de retour, les journaux et la nouvelle ligne Dataverse avec
   `agil_source = scheduled`.

### Gestion des dates dans une tâche récurrente

Le Planificateur de tâches ne calcule pas nativement les fenêtres ISO 8601
attendues par le module. Pour le POC, deux approches raisonnables existent :

- créer temporairement une tâche avec une fenêtre fixe pour valider les droits
  et le parcours de bout en bout ;
- après validation, utiliser un petit script PowerShell local **approuvé et
  revu** qui calcule une fenêtre UTC puis appelle exactement le même module.

Ce script de calcul n'est pas fourni ni installé automatiquement ici : il
constitue une décision de fonctionnement (cadence, fuseau, rattrapage en cas
d'absence) qui doit être validée avant ajout au projet. Ne remplacez pas les
dates par l'heure locale sans définir explicitement la convention métier.

## Ce qui n'est pas déployé

Cette implémentation ne déploie **ni Azure Function, ni Logic App, ni Power
Automate, ni routine Foundry**. Le Planificateur de tâches Windows est
simplement l'option locale la plus légère pour démontrer l'automatisation dans
le POC.

Migrer vers Azure Functions, Power Automate ou tout autre service d'exécution
gérée demanderait une décision ultérieure : nouveau service Azure, identité
managée ou gestion de secrets, stratégie de planification et de retry,
supervision, coûts et contrôle de concurrence. Aucun de ces éléments ne doit
être ajouté sans accord préalable, afin de conserver le projet dans son
périmètre POC actuel.
