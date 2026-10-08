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
    * Database Configuration

      * one DataVerse table - Feedbacks - raw comment, timestamps, software, sentiment, confidence, extracted functionalities, language
      * Données générées artificiellement
      * Microsoft Entra ID to register the application, Power Platform Admin Center to link the registered application to the Power Platform environment, create a least privilege security role (in the needed tables of the environment) and affect it to the application.
    * **Reporting**.

      * 
    * General

      * detect language method implemented before Text Analysis tools.
      * detailed knowledge about the set of softwares concerned by the project and their associated services. --> **knowledge.py**
      * implement conversation
    * 







Questions / Detailed Steps :



* Pourquoi ne pas donner directement l'input à la fonction outil d'analyse de sentiment ?
* Can tool functions be traced ? --> See after enabling log analytics
* Look into logs + Bills
* Integrate Log Insights
* Ajouter les vraies fonctionnalités de Targetym AI
* Données à générer artificiellement :

  * Dans un Intervalle de temps défini --> Services --> Functionalities --> for each functionality --> define failures and/or successes --> create user feedbacks depending on these.
* Reporting :

  * Données Brutes --> Statements de Base --> KPI --> Rapport Complet
* Make the Agent support full conversation / let the agent choose tasks (not necessarily with Feedback Analysis)
* Update Dataverse tables
* Update Knowledge about new possible parameter values
* Generate necessary data, for data
* Add New Table for issue clusters
* Build analysis tool/service
* build a tool to get current date time.
* Bouton nouvelle conversation, 
* la barre d'envoi de message non flexible, 
* les boutons de questions essai qui ne marchent pas.
* les autres sessions de conversation. 
* ne pas demander a l'user des dates ou un format ISO. 
* "visualisation" du rapport non visible et graphiques pas plaisants visuellement, sans légende ou titre. 
* aussi, mettre chaque schéma à la suite du paragraphe correspondant s'il illustre un des paragraphes du texte. 
* pour les rapports, ajouter parfois des chiffres pour démontrer une observation. Exemple : "Targetym AI : Retours positifs sur le dossier salarié et l'espace salarié, avec une bonne satisfaction client. (80% de sentiments positifs.)"
* Parfois, les réponses doivent pouvoir citer quelques uns des raw feedbacks initiaux.	



* Un peu plus de verbose dans l'attente d'analyse
* 



Ordre conseillé

1\. Créer la couche FastAPI autour des services actuels.

2\. Brancher votre frontend Streamlit existant sur cette API : chat et analyse unitaire.

3\. Ajouter la table agil\_insightanalysis et l’enregistrement des snapshots.

4\. Construire le dashboard Streamlit à partir des feedbacks et des snapshots.

5\. Ajouter un script d’analyse planifiée, puis l’héberger avec Azure Function Timer Trigger ou Power Automate.

6\. Ajouter l’ingestion externe par formulaires, avec traçabilité de source et anti-doublon.

7\. Ajouter les visualisations pilotées par l’agent, sur la base d’un VisualizationSpec sécurisé.

