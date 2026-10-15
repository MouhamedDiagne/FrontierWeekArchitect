# Monitoring Azure Monitor et traces Foundry

## Objectif et périmètre

Le backend du POC exporte désormais, de façon **optionnelle**, des traces
OpenTelemetry vers une ressource Application Insights existante. Aucun service
Azure, rôle RBAC ou table Dataverse n'est créé par le code. Cette couche
complète les traces serveur Foundry : les deux peuvent être consultées depuis
Foundry ou Application Insights une fois la ressource connectée au projet.

Les opérations couvertes sont volontairement limitées et ne contiennent pas de
texte client : analyse de sentiment, enrichissement, embeddings, clustering,
lecture/écriture Dataverse et sauvegarde de snapshots. Les attributs ajoutés
sont uniquement des données techniques ou agrégées (logiciel, modèle, taille de
lot, profil du rapport, nombre de feedbacks/clusters).

## Activation locale

La fonctionnalité reste désactivée tant que `OBSERVABILITY_ENABLED` n'est pas
vrai. Dans le fichier `.env` local, ajoutez les lignes suivantes en utilisant la
chaîne de connexion **déjà** associée à votre ressource Application Insights :

```dotenv
OBSERVABILITY_ENABLED=true
APPLICATIONINSIGHTS_CONNECTION_STRING=<chaîne-de-connexion-Application-Insights>

# Valeur recommandée pour des retours clients réels.
OBSERVABILITY_CAPTURE_MESSAGE_CONTENT=false

# L'instrumenteur Foundry GenAI reste désactivé par défaut dans ce POC.
OBSERVABILITY_ENABLE_FOUNDRY_GENAI_TRACING=false
```

`OTEL_SERVICE_NAME` est facultatif. Sans cette variable, le processus est nommé
selon son point d'entrée : `agiltym-feedback-api`, `agiltym-feedback-cli` ou
`agiltym-feedback-insight-job`.

Si vous souhaitez évaluer ultérieurement les spans GenAI clients expérimentaux,
ajoutez aussi `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` et
`OBSERVABILITY_ENABLE_FOUNDRY_GENAI_TRACING=true`, puis effectuez ce test sur
un environnement de développement. Ces spans restent séparés des traces métier
du POC, qui fonctionnent sans eux.

Redémarrez ensuite l'API, le CLI ou le job planifié. Une ligne
`[feedback-agent][telemetry]` confirmera l'état, sans jamais afficher la chaîne
de connexion. Ne relancez pas `app/deploy.sh` simplement pour activer les
traces : l'ajout des variables et le redémarrage suffisent.

## Connexion et droits à réaliser dans Azure

1. Dans le projet Microsoft Foundry : **Agents > Traces > Connect**, ou
   **Manage > Project details > Connected resources**, connectez la ressource
   Application Insights existante.
2. Accordez aux personnes qui consultent les traces le rôle **Log Analytics
   Reader** sur le workspace concerné. Si les tables sont protégées, ajoutez
   aussi **Privileged Monitoring Data Reader** conformément à la politique de
   votre organisation.
3. Redémarrez le service, envoyez un feedback de test non sensible puis ouvrez
   les traces dans Foundry et/ou Application Insights. L'ingestion peut prendre
   quelques minutes.

## Confidentialité

`OBSERVABILITY_CAPTURE_MESSAGE_CONTENT=false` force
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` avant
l'instrumentation Foundry. Les prompts, commentaires bruts, résumés, arguments
d'outil et payloads Dataverse ne sont donc pas ajoutés volontairement par le
code métier.

N'activez la capture de contenu (`true`) que pour une ressource de développement
séparée, avec une décision explicite de gouvernance, de rétention et de contrôle
d'accès. Les traces de modèles peuvent contenir des données sensibles.

## Limites POC

Cette étape n'ajoute ni alertes, ni tableaux de bord Azure dédiés, ni règles
KQL. Elle rend le flux observable et corrélable ; les seuils d'alerting et la
rétention devront être définis avant une mise en production.

Références Microsoft : [configurer les traces Foundry](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup), [instrumentation cliente Python](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side?tabs=python), [données présentes dans les traces](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-data).
