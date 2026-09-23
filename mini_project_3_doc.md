* **Agent Architect - Welcome: Build production-ready AI solutions**

  * Explorer - Build your first AI Agent, Agent Builder, No code required
  * Maker - Extend and orchestrate agents, Copilot Studio, Low-code capabilities
  * Architect - Production-ready AI solutions, Microsoft Foundry, Pro-code engineering control.
* **2. Agent Architect - Set up your Foundry environment**

  * TireForge Industries
  * **Build, Monitor, Evaluate, Orchestrate**
* **3. Agent Architect - Introduction to Microsoft Foundry**

  * **Microsoft Foundry -** unified Azure Plateform-as-a-Service offering for enterprise AI operations model builders and application developers.
* **4. Agent Architect - Monitor and trace agent behavior**

  * **Tracing**

    * how the agent reached its response
    * execution journey, model calls, tool usage, latency and errors, improves reliability
  * **Monitoring**

    * tracks how the agent performs aver time
    * Quality metrics, Safety Metrics, Cost Metrics, Alerts and regressions, Production Readiness
* **5. Agent Architect - Evaluate agent quality**

  * **Representative (GOlden) Dataset** 
  * **Collection Scenarios**
  * **Range of Evaluator Metrics : Coherence, Relevance, Groundedness, Task Adherence, Safety, Tool usage behavior**
  * **"Measurable results** that show that the agent consistently meets **defined quality thresholds."**
  * Run before deployment, after agent setup changes, and regularly to detect quality drift.
* **6. Agent Architect - Orchestrate multi-agent workflows**

  * 
* **7. Agent Architect - From prototype to production**
* **8. Final activity - Design and deliver a multi-agent solution**





**Build, Monitor and Evaluate AI Agents using the Microsoft Foundry SDK -** [**Link**](https://github.com/microsoft/FrontierWeekHack) 

* Setup
* Agent Design
* Observability 
* Quality Evaluation
* Multi-agent Orchestration



* Setup 

  * Fork repository 
  * Setup in Azure Codespaces
  * Deploy infrastructure
  * Verify resources created in Azure
  * Verify project accessibility in FOundry
  * Verify Model GPT-5.4 success deployment.
* Agent Design

  * Objective - Build : **1. An Anomaly Detection Agent, 2. A Fault** Diagnosis **Agent**
  * **AnomalyDetectionAgent** :

    * ***Initialize --> (***<i>self.agent, self.client, self.openai**)**</i>
    * ***Create -->*** <i>create Foundry client, create compatible openai client, create agent with foundry client</i>
    * ***Run -->*** <i>created openai conversation, user --> model (openai client), model (openai client)-->tool calls, program (retrieves tool calls) --> python function \& tool result, tool results --> model --> final answer</i>
  * **FaultDiagnosisAgent** :

    * ***Initialize --> (***<i>self.agent, self.client, self.openai\*\*)\*\*</i>
    * ***Create -->*** <i>create Foundry client, create compatible openai client, create agent with foundry client</i>
    * ***Run -->*** <i>reated openai conversation, user --> model call(openai client), model call(openai client) --> final answer(structured answer in prompts) \& conversation deletion</i>
    * Cet agent n'a pas besoin de faire appel à des outils: il reçoit déjà les données d'anomalie dans son prompt.
  * **Main** 
* **Observability**

  * Objective 

    * 1\. GenAI tracing for Foundry agents 
    * 2\. Agent Interactions visible as Traces in Application Insights 
    * 3\. Understanding of how to debug agent behaviout in production  
  * Why Monitor ?

    * Reliability — Detect when agents stop working (tool call failures, timeouts, empty responses) before users do
    * Performance — Track latency and token usage over time, catch regressions when you update a system prompt, and right-size your deployments for cost efficiency
    * Debugging — When something goes wrong, distributed traces give you a complete record of what the model reasoned, what tools were called, what they returned, and exactly where the chain broke
  * 

