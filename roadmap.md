**Roadmap**



* Setup : 

  * Création du projet Foundry, choix de l'environnement de Développement, Configurations de Connexion (Blocage : souscription Azure expirée)
  * Alternative : Google AI Studio.
* Génération d'un 1er fichier de données
* Baseline de l'agent

  * **1st version :** un commentaire --> traitement LLM --> output(sentiment) sous format défini. **(OK, point d'arrêt Google AI Studio)**

    * transformer cette capacité en outil : moins cher si le LLM est choisi moins puissant, plus de traçabilité sur chaque instance d'analyse
  * **2nd version :** 

    * commentaire --> AI Language Sentiment Analysis --> Sentiment, Confidence Percentage

      * "mixed" sentiment now handled. Custom confidence score calculated from the "negative" and "positive" sentiment confidence scores.
    * commentaire --> light LLM --> concerned Application functionality, alert level (not yet)

      * "agent\_reference" object given in the extra\_body parameter of the openai model call. **Not for this tool.**
    * commentaire --> Analysis --> saved in Database
    * Agent tools : 1. Sentiment Analysis, 2. Functionality Detection, 3. Database Connection, 
    * Agent skills : 4. General Analysis.
    * General 

      * detect language method implemented before Text Analysis tools.
      * detailed knowledge about the set of softwares concerned by the project and their associated services. --> **knowledge.py**







Questions / Detailed Steps : 



* In the SentimentAnalysisResult schema, how to make the percentage attribute a float between 0 et 1 ? 
* Pourquoi ne pas donner directement l'input à la fonction outil d'analyse de sentiment ? 
* Can tool functions be traced ? --> See after enabling log analytics 
* How to connect to a database or Dataverse Table from client Application ? (now)
* Definir le client TextAnalytics lors de la création de l'agent et non dans l'outil d'Analyse de Sentiment 
* Add detailed Knowledge about the different apps and their defined Functionalities (ongoing)
* Look into logs + Bills
* Integrate Log Insights
* Ajouter les vraies fonctionnalités de Targetym AI

