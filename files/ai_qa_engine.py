# ai_qa_engine.py
import requests
import time
import re

# -----------------------------
# CONFIG
# -----------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "phi3"

CACHE = {}
CACHE_TTL = 60  # seconds


# -----------------------------
# SIMPLE QUESTION CLASSIFIER
# -----------------------------
def is_fee_related(question: str) -> bool:
    keywords = [
        "fee", "fees", "pending", "due", "dues",
        "payment", "paid", "collection",
        "academic year", "semester", "balance"
    ]
    q = question.lower()
    return any(k in q for k in keywords)


# -----------------------------
# FETCH DATA (RAG CONTEXT)
# -----------------------------
def fetch_ai_data(cursor):
    now = time.time()

    if "data" in CACHE and now - CACHE["time"] < CACHE_TTL:
        return CACHE["data"]

    cursor.execute("""
        SELECT SUM(
            COALESCE(tuition_fee,0) +
            COALESCE(practical_fee,0) +
            COALESCE(university_fee,0) +
            COALESCE(bus_fee,0) +
            COALESCE(stationary_fee,0) +
            COALESCE(internship_fee,0) +
            COALESCE(viva_fee,0)
        ) AS expected
        FROM fee
    """)
    expected = cursor.fetchone()["expected"] or 0

    cursor.execute("""
        SELECT COALESCE(SUM(paid_amount),0) AS collected
        FROM payment
    """)
    collected = cursor.fetchone()["collected"] or 0

    pending = expected - collected

    cursor.execute("""
        SELECT s.academic_year,
               SUM(
                   (
                       COALESCE(f.tuition_fee,0) +
                       COALESCE(f.practical_fee,0) +
                       COALESCE(f.university_fee,0)
                   ) -
                   COALESCE(p.paid_amount,0)
               ) AS pending
        FROM student s
        JOIN fee f ON s.id = f.student_id
        LEFT JOIN payment p ON f.id = p.fee_id
        GROUP BY s.academic_year
        ORDER BY pending DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    top_year = row["academic_year"] if row else "N/A"

    data = {
        "expected": expected,
        "collected": collected,
        "pending": pending,
        "top_year": top_year
    }

    CACHE["data"] = data
    CACHE["time"] = now
    return data


# -----------------------------
# GENERATE AI ANSWER (SMART LLM)
# -----------------------------
def generate_answer(question, data):
    fee_related = is_fee_related(question)

    if fee_related:
        # 🔒 RAG MODE (STRICT)
        prompt = f"""
You are an AI assistant for a college fee management system.

You MUST answer ONLY using the provided facts.
Do NOT invent numbers or assumptions.

FACTS:
- Total expected fee: ₹{data['expected']}
- Total collected fee: ₹{data['collected']}
- Total pending fee: ₹{data['pending']}
- Highest pending academic year: {data['top_year']}

Rules:
- Professional tone
- 2–3 sentences
- Explain clearly

User question:
{question}

Answer:
"""
    else:
        # 🌍 GENERAL AI MODE
        prompt = f"""
You are a helpful AI assistant.

Answer the user's question clearly and simply.
Do NOT include any fee numbers unless asked.

User question:
{question}

Answer:
"""

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 120
        }
    }

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=60
        )
        return response.json()["response"].strip()

    except requests.exceptions.ReadTimeout:
        return "AI is busy right now. Please try again in a moment."
