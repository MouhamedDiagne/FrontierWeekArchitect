import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")

client = genai.Client(api_key=GEMINI_API_KEY)

interaction = client.interactions.create(
    model=GEMINI_MODEL,
    input="Classify this comment into 'Positive', 'Negative', 'Mixte' or 'Neutral'. Respond only with one label. \n Comment : \n 'The Administration service is too slow to charge.'"
)

print(interaction.output_text)