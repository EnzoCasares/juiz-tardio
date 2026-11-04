from langchain_groq import ChatGroq
from app.config import GROQ_API_KEY

llm_groq = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.0,
    api_key=GROQ_API_KEY,
    timeout=30,
    max_retries=5,
)

llm_rapido = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.0,
    api_key=GROQ_API_KEY,
    timeout=30,
    max_retries=5,
)

llm_especialista = llm_groq
