# Persister les analyses historiques dans Dataverse

## Objectif et périmètre du POC

Une analyse historique regroupe les retours déjà enregistrés, calcule des
clusters temporaires, puis produit deux objets structurés :

- `insights` : preuves analytiques, périmètre, clusters, métriques et limites ;
- `audience_report` : sélection de ces signaux pour un profil d'audience.

La table décrite ici conserve un **instantané immuable** de ces deux objets,
après une analyse réussie. Elle ne remplace pas la table des feedbacks et
n'écrit ni embeddings ni clusters permanents. Elle est volontairement simple
pour le POC : le code crée un enregistrement et peut relire le plus récent ;
il ne le met jamais à jour ni ne le supprime.

Cette persistance est réalisée par
`DataverseInsightAnalysisRepository` dans `app/dataverse.py`. Le modèle
applicatif correspondant est `FeedbackInsightsSnapshot` dans `app/models.py`.

## Table à créer

Créer la table dans le **même environnement Dataverse** que celui indiqué par
`DATAVERSE_URL`.

| Paramètre Dataverse | Valeur recommandée |
| --- | --- |
| Nom d’affichage | `Analyse d'insights` |
| Nom logique / schema name | `agil_insightanalysis` |
| Préfixe éditeur | `agil` |
| Propriété | **Organisation-owned** |
| Table type | Standard, sans activités, notes ni pièces jointes |
| Colonne principale | Nom d’affichage : `Nom de l'analyse` ; nom logique : `agil_agilname` |

Le choix *Organisation-owned* est adapté aux instantanés techniques du POC :
ils ne sont pas la propriété d'un commercial ou d'un utilisateur final. Si
une table *User or team-owned* est imposée par votre gouvernance, le code reste
compatible, mais les privilèges du compte applicatif devront toujours couvrir
la création et la lecture au niveau **Organisation**.

Après avoir créé les colonnes, enregistrer et **publier toutes les
personnalisations** avant de renseigner la variable d'environnement.

## Contrat de colonnes exact

Les noms logiques ci-dessous correspondent à
`DataverseInsightAnalysisColumnMap`. Ne pas les renommer : aucun paramètre de
configuration ne remappe actuellement cette table dans les points d'entrée
normaux de l'application.

| Nom d’affichage conseillé | Nom logique exact | Type Dataverse | Taille / comportement | Requis | Valeur écrite par le dépôt |
| --- | --- | --- | --- | --- | --- |
| Nom de l'analyse | `agil_agilname` | Une ligne de texte | 100 caractères | Oui (colonne principale) | `Insights <horodatage UTC>` |
| Référence d'analyse | `agil_analysisreference` | Une ligne de texte | 100 caractères | Oui | `insights-<UUID>` ; identifiant métier technique, sans clé alternative dans ce POC |
| Générée le | `agil_generatedat` | Date et heure | Préférer *Time zone independent* ; pas *Date only* | Oui | Horodatage UTC de la création de l'instantané |
| Source | `agil_source` | Une ligne de texte | 50 caractères | Oui | `conversation`, `manual` ou `scheduled` |
| Début de période | `agil_periodstart` | Date et heure | Préférer *Time zone independent* | Oui | Début inclus du périmètre analysé, en UTC |
| Fin de période | `agil_periodend` | Date et heure | Préférer *Time zone independent* | Oui | Fin exclusive du périmètre analysé, en UTC |
| Début de comparaison | `agil_comparisonstart` | Date et heure | Préférer *Time zone independent* | Non | Écrit seulement si une période de comparaison a été demandée |
| Fin de comparaison | `agil_comparisonend` | Date et heure | Préférer *Time zone independent* | Non | Écrit seulement si une période de comparaison a été demandée |
| Logiciel | `agil_softwareid` | Une ligne de texte | 100 caractères | Non | Identifiant logiciel du filtre, par exemple `targetym_ai` |
| Fonctionnalité | `agil_functionalityid` | Une ligne de texte | 255 caractères | Non | Identifiant de fonctionnalité du filtre, si fourni |
| Profil d'audience | `agil_audienceprofile` | Une ligne de texte | 50 caractères | Oui | Profil du rapport, par exemple `management`, `it`, `marketing` ou `support_sales` |
| Nombre total de feedbacks | `agil_totalfeedbacks` | Nombre entier | Min. 0 ; sans décimales | Oui | Nombre de feedbacks retenus dans le périmètre |
| Nombre de feedbacks clusterisés | `agil_clusteredfeedbacks` | Nombre entier | Min. 0 ; sans décimales | Oui | Nombre de feedbacks présents dans un cluster confirmé |
| Nombre de clusters | `agil_clustercount` | Nombre entier | Min. 0 ; sans décimales | Oui | Taille de la liste des clusters retournés |
| Insights JSON | `agil_insightsjson` | Plusieurs lignes de texte | Texte brut, longueur maximale **1 000 000** caractères | Oui | Sérialisation JSON de `FeedbackInsightsResult` |
| Rapport d'audience JSON | `agil_audiencereportsjson` | Plusieurs lignes de texte | Texte brut, longueur maximale **1 000 000** caractères | Oui | Sérialisation JSON de `AudienceReport` |
| Version du schéma | `agil_schemaversion` | Nombre entier | Min. 1 ; sans décimales | Oui | `1` dans la version actuelle du POC |

Les colonnes système (`createdon`, `modifiedon`, identifiant Dataverse et,
selon le type de propriété, propriétaire) sont gérées par Dataverse : ne pas
les ajouter au contrat applicatif. Les deux colonnes JSON doivent rester des
champs texte brut, **pas** des colonnes Rich Text, Lookup, Choice ou File.

`agil_source` et `agil_audienceprofile` sont volontairement des textes et non
des Choice : le dépôt envoie directement les valeurs stables de ses énumérations.
Les convertir en Choice imposerait des identifiants numériques spécifiques à
l'environnement et casserait le contrat actuel.

## Création dans Power Platform

1. Ouvrir [make.powerapps.com](https://make.powerapps.com), sélectionner
   l'environnement Dataverse utilisé par le projet, puis ouvrir **Solutions**.
2. Créer ou ouvrir une solution non gérée de POC avec l'éditeur au préfixe
   `agil`. Conserver la table et toutes ses colonnes dans cette solution ; cela
   rendra l'export et le suivi du schéma possibles.
3. Dans **Tables**, créer la table avec le nom logique
   `agil_insightanalysis`, la propriété *Organisation-owned* et la colonne
   principale `agil_agilname`.
4. Ajouter les colonnes de la table ci-dessus, avec exactement les noms
   logiques indiqués. Laisser les filtres facultatifs
   (`agil_comparisonstart`, `agil_comparisonend`, `agil_softwareid` et
   `agil_functionalityid`) non obligatoires.
5. Régler les longueurs des champs JSON à au moins `1 000 000` caractères
   (Dataverse accepte jusqu'à 1 048 576 caractères pour ce type de champ).
6. Enregistrer puis publier les personnalisations. Vérifier les noms logiques
   dans les propriétés de chaque colonne, et non seulement les libellés
   affichés.

Le nom donné à la variable ci-dessous est le **nom logique de table** attendu
par le client Python, donc `agil_insightanalysis` dans ce contrat. Ne pas
remplacer cette valeur par le nom affiché, ni par une collection OData
pluralisée.

## Configuration de l'application

Ajouter la variable suivante au fichier `.env` local, sans la commiter :

```dotenv
DATAVERSE_INSIGHT_ANALYSIS_TABLE=agil_insightanalysis
```

Les variables Dataverse existantes restent également nécessaires :

```dotenv
DATAVERSE_URL=https://<organisation>.crm.dynamics.com
DATAVERSE_TENANT_ID=<tenant-id>
DATAVERSE_CLIENT_ID=<application-client-id>
DATAVERSE_CLIENT_SECRET=<secret-value>
```

Redémarrer ensuite le processus Python / l'API FastAPI. `app/main.py` et
`app/api.py` créent `DataverseInsightAnalysisRepository` seulement lorsque
`DATAVERSE_INSIGHT_ANALYSIS_TABLE` est renseignée. En son absence, l'analyse
historique continue de fonctionner, mais aucun instantané n'est enregistré et
un message verbose indique que cette persistance est désactivée.

Si la variable est renseignée alors qu'une des autres variables Dataverse est
manquante, `from_environment()` échoue explicitement avec
`Dataverse insight-analysis configuration missing: ...`.

## Identité Entra ID et droits Dataverse

L'authentification reste celle déjà utilisée pour l'écriture des feedbacks :
le client Python construit un `ClientSecretCredential` à partir du tenant, de
l'application Entra ID et de son secret. Aucune nouvelle application Entra ID
ni aucun nouveau service Azure n'est requis.

Dans **Power Platform Admin Center**, ajouter l'application Entra existante
comme *Application user* de cet environnement, ou modifier l'utilisateur
d'application déjà associé à `DATAVERSE_CLIENT_ID`. Lui attribuer un rôle
Dataverse dédié, par exemple `Feedback Analyzer Insights Writer`, avec sur la
table `agil_insightanalysis` :

| Privilège | Profondeur recommandée | Motif |
| --- | --- | --- |
| Create | Organisation | `save_snapshot()` crée un enregistrement par analyse réussie. |
| Read | Organisation | `latest_snapshot()` lit le plus récent instantané pour les futurs écrans de tableau de bord. |
| Write | Aucun | Le dépôt ne met jamais à jour un instantané. |
| Delete | Aucun | Le dépôt ne supprime jamais un instantané. |
| Append / Append To | Aucun | La table POC ne crée aucune relation Lookup. |
| Assign / Share | Aucun | Aucun partage ni changement de propriétaire n'est effectué. |

Ne pas attribuer `System Administrator` pour contourner un refus `403`.
Conserver les droits déjà requis sur la table de feedbacks : l'analyse lit les
feedbacks existants avant de créer son instantané. Si la sécurité au niveau des
colonnes est activée dans l'environnement, l'utilisateur d'application doit
également pouvoir lire les deux colonnes JSON ; pour ce POC, il est préférable
de ne pas activer cette couche sur cette table.

Le secret client reste côté backend. Il ne doit jamais être placé dans
Streamlit, dans le navigateur, dans Git ou dans le contenu d'un feedback.

## Fonctionnement à l'exécution

1. L'agent appelle `analyze_feedback_insights` pour une demande historique.
2. `FeedbackInsightsService` lit les feedbacks nécessaires et produit des
   clusters temporaires ; il ne modifie aucune ligne de feedback.
3. `ProfiledInsightsReportBuilder` sélectionne les signaux pertinents pour le
   profil d'audience.
4. `FeedbackAnalyzerAgent.run_historical_analysis()` construit un
   `FeedbackInsightsSnapshot` avec un horodatage UTC et une source.
5. Si le dépôt d'instantanés est configuré,
   `DataverseInsightAnalysisRepository.save_snapshot()` sérialise les objets,
   contrôle la taille de chaque JSON, puis crée une ligne Dataverse.
6. L'identifiant Dataverse de cette ligne revient dans
   `InsightsAnalysisRunResult.insight_snapshot_id`. Le JSON renvoyé au modèle
   conversationnel reste limité à `insights` et `audience_report` ; l'identifiant
   interne n'est pas injecté dans le prompt.

Les valeurs de source supportées sont `conversation`, `manual` et
`scheduled`. Le parcours conversationnel actuel utilise `conversation`. Les
deux autres valeurs sont prévues pour les appels directs et la future
automatisation, sans changer le schéma de table.

`latest_snapshot()` relit seulement `agil_generatedat`, `agil_source`,
`agil_insightsjson` et `agil_audiencereportsjson`, triés par
`agil_generatedat desc` avec une limite de un enregistrement. Cette lecture ne
recalcule pas les clusters et ne modifie pas la table.

## Vérification et diagnostic

Après configuration :

1. Démarrer l'application avec le mode verbose.
2. Demander un rapport historique pour une période contenant quelques
   feedbacks.
3. Rechercher une ligne nouvelle dans `Analyse d'insights` et contrôler :
   - `agil_source = conversation` ;
   - les bornes de période sont en UTC ;
   - les compteurs correspondent au résultat retourné ;
   - les deux champs JSON contiennent du JSON valide ;
   - `agil_schemaversion = 1`.
4. Les logs attendus incluent la création de l'instantané et l'identifiant
   Dataverse retourné. Ils ne doivent pas contenir le secret client.

| Symptôme | Cause probable | Correction |
| --- | --- | --- |
| Persistance annoncée comme désactivée | `DATAVERSE_INSIGHT_ANALYSIS_TABLE` est absent ou vide | Ajouter `DATAVERSE_INSIGHT_ANALYSIS_TABLE=agil_insightanalysis`, puis redémarrer. |
| `404` à la création | Nom logique erroné, table non publiée ou mauvais environnement | Vérifier le nom exact `agil_insightanalysis`, publier, puis vérifier `DATAVERSE_URL`. |
| `403` avec `prvCreateagil_insightanalysis` | Le rôle de l'utilisateur d'application n'a pas Create | Ajouter Create au niveau Organisation sur cette table. |
| `403` à la lecture du dernier instantané | Privilège Read absent | Ajouter Read au niveau Organisation sur cette table. |
| `The insights snapshot exceeds the Dataverse text limit` | L'un des JSON dépasse 1 000 000 caractères | Réduire le périmètre ou le volume de clusters ; ne pas augmenter silencieusement la limite applicative sans décision de conception. |
| Erreur de JSON lors de `latest_snapshot()` | Une ligne a été modifiée manuellement ou créée avec un schéma incompatible | Restaurer un JSON produit par l'application ou supprimer/corriger la ligne selon la procédure de gouvernance. |

En cas d'échec de `save_snapshot()`, le dépôt lève
`DataverseInsightsPersistenceError` : l'analyse a pu être calculée, mais elle
ne doit pas être considérée comme durablement enregistrée. Aucun mécanisme de
retry, de mise à jour ou de rattrapage n'est ajouté dans ce POC.

## Données et sécurité

La table ne possède pas de colonne `raw_comment`, et le dépôt n'écrit pas de
commentaire brut comme champ séparé. Néanmoins, `agil_insightsjson` peut
contenir des résumés représentatifs, des identifiants de feedbacks, des dates
et des limitations. Si certains feedbacks n'ont pas de résumé exploitable, les
données analytiques peuvent utiliser un texte de repli. Ces JSON doivent donc
être traités comme des données potentiellement sensibles.

Pour rester dans le périmètre POC :

- accorder les seuls privilèges Create et Read nécessaires à l'application ;
- limiter l'accès humain à la table aux personnes qui ont besoin de consulter
  les rapports ;
- ne pas copier les JSON dans les logs, exports publics ou frontend ;
- conserver les dates au format UTC et les valeurs stables de profils/sources ;
- ne pas activer de mécanisme automatique d'archivage, de suppression ou de
  synchronisation externe sans décision explicite.

Avant une mise en production, définir la conservation des instantanés, les
droits de lecture humains, la politique de traitement des données personnelles,
et une stratégie de migration lorsque `agil_schemaversion` évoluera.

