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
    * commentaire --> light LLM --> concerned Application functionality, alert level (???)
    * commentaire --> Analysis --> saved in Database
    * Agent tools : 1. Sentiment Analysis, 2. Functionality Detection, 3. Database Connection, 
    * Agent skills : 4. General Analysis.







Questions / Detailed Steps : 



* Comment Azure AI Language gère les langues ? --> Detect Language method is now used in the code.
* In the SentimentAnalysisResult schema, how to make the percentage attribute a float between 0 et 1 ? 
* A quoi sert le "extra\_body" dans l'appel de l'API openai ?
* Pourquoi ne pas donner directement l'input à la fonction outil d'analyse de sentiment ? 
* How are "Mixed" sentiments handled at the moment ? --> solved
* Can tool functions be traced ? --> See after enabling log analytics
* How to connect to a database or Dataverse Table from client Application ? 
* Definir le client TextAnalytics lors de la création de l'agent et non dans l'outil d'Analyse de Sentiment (???)
* Add detailed Knowledge about the different apps and their defined Functionalities
* Look into logs
* Integrate Log Insights

