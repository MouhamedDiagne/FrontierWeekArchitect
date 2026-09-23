**Architecture**



* **Orchestration**

  * Un seul agent ou un système multi-agent ? 
  * Aspects différentiateurs : 

    * Un seul agent n'aura-t-il pas trop d'outils, de connaissances, trop de possibilités à chaque requête d'utilisateur ? 
    * Qu'est-ce qui permettra d'avoir la consommation la moins lourde en termes de tokens ? 
    * le temps de latence minimalisé
    * 
* **Model**

  * modèle gpt-5.4 disponible sur Foundry
  * Instructions : dépend des capacités de l'agent / versionné selon les changements qui se feront au cours du projet
* **Data**

  * données contextuelles : description des différentes applications, de leurs services, --> document Sharepoint ou inclus dans les Instructions
  * données opérationnelles : commentaires clients (date, application concernée, commentaire, ...) <---- fichier initial de Commentaires, formulaire client remplissable à tout moment, worflow intelligent de génération de commentaires --> DataVerse
  * données d'évaluation : basées sur les données opérationnelles, générées par l'IA, reflétant des simulations de retours client plausibles. --> fichier CSV.
* **Knowledge**

  * Documentation sur les différents Software d'Agiltym et les services qu'ils proposent chacun.
* **Tools**

  * outil de classification : commentaire client ----> sentiment associé, service/fonctionnalité concerné(e). --> Label + Percentage
  * outils de génération de rapport
  * outil de connexion aux bases de données (Dataverse)
* **Méthodes / Skills**

  * méthode d'analyse de commentaire unique
  * méthode d'analyse globale
  * méthode de génération de rapport
* **Interfaces Tiers** 

  * Formulaire, tables Dataverse, 
  * Power App pour l'interface utilisateur ? 

