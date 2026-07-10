import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from pypdf import PdfReader
from groq import Groq

CURRENT_DIR = Path(__file__).resolve().parent
DATA_DIR_CANDIDATES = [CURRENT_DIR / "data", CURRENT_DIR.parent / "data"]
DB_PATH = CURRENT_DIR / "orders.db"

def _resolve_data_path(filename: str) -> Path:
    for data_dir in DATA_DIR_CANDIDATES:
        candidate = data_dir / filename
        if candidate.exists():
            return candidate
    return DATA_DIR_CANDIDATES[-1] / filename

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())

def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    words = text.split()
    chunks = []
    if not words:
        return chunks

    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size

    for start in range(0, len(words), step):
        chunk_words = words[start:start + chunk_size]
        if not chunk_words:
            continue
        chunks.append(" ".join(chunk_words))
        if start + chunk_size >= len(words):
            break
    return chunks

@lru_cache(maxsize=1)
def _load_document_chunks() -> list[dict]:
    chunks: list[dict] = []
    pdf_dirs = [data_dir for data_dir in DATA_DIR_CANDIDATES if data_dir.exists()]
    if not pdf_dirs:
        return chunks

    seen_files: set[Path] = set()
    for data_dir in pdf_dirs:
        for pdf_path in sorted(data_dir.glob("*.pdf")):
            if pdf_path in seen_files:
                continue
            seen_files.add(pdf_path)
        try:
            reader = PdfReader(str(pdf_path))
        except Exception:
            continue

        text_parts = []
        for page in reader.pages:
            extracted = page.extract_text() or ""
            if extracted:
                text_parts.append(extracted)

        for chunk_index, chunk in enumerate(chunk_text("\n".join(text_parts))):
            tokens = set(_tokenize(chunk))
            if tokens:
                chunks.append({
                    "text": chunk,
                    "source": pdf_path.name,
                    "chunk_index": chunk_index,
                    "tokens": tokens,
                })

    return chunks

def search_documents(query: str) -> list:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    scored_chunks = []
    for chunk in _load_document_chunks():
        overlap = len(query_tokens & chunk["tokens"])
        if not overlap:
            continue

        coverage = overlap / max(1, len(query_tokens))
        density = overlap / max(1, len(chunk["tokens"]))
        score = min(1.0, (coverage * 0.8) + (density * 0.2))

        if score >= 0.05:
            scored_chunks.append({
                "text": chunk["text"],
                "source": chunk["source"],
                "chunk_index": chunk["chunk_index"],
                "score": score,
            })

    scored_chunks.sort(key=lambda item: item["score"], reverse=True)
    return scored_chunks[:4]

VALID_IDENTIFIERS = {
    "orders", "order_id", "customer", "product", "amount", "status", "order_date",
    "select", "from", "where", "group", "by", "order", "limit", "as", "on", "join", 
    "left", "inner", "and", "or", "not", "in", "like", "between", "null", "desc", 
    "asc", "is", "case", "when", "then", "else", "end", "count", "sum", "avg", 
    "min", "max", "strftime", "date", "datetime", "having", "distinct", "coalesce",
    "julianday", "substr", "lower", "upper", "replace", "trim", "abs", "round"
}

def validate_sql(sql_str: str) -> tuple[bool, str]:
    query = sql_str.strip()
    if not query:
        return False, "Empty SQL query"
    
    if not query.upper().startswith("SELECT"):
        return False, "Only SELECT statements are allowed"
    
    if ";" in query[:-1]:
        return False, "Multiple SQL statements are not allowed"
    
    forbidden = ["DROP", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", 
                 "ATTACH", "PRAGMA", "REPLACE", "TRUNCATE", "UPSERT", 
                 "GRANT", "REVOKE", "EXEC", "EXECUTE", "UNION"]
    for word in forbidden:
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, query, re.IGNORECASE):
            return False, f"Forbidden keyword detected: {word}"
            
    matches = re.findall(r'\b(?:FROM|JOIN)\s+([a-zA-Z0-9_\(\"\`\']+)', query, re.IGNORECASE)
    for tbl in matches:
        tbl_clean = tbl.strip("()\"'`").lower()
        if tbl_clean and tbl_clean != "orders" and not tbl_clean.startswith("select"):
            return False, f"Unauthorized table access: {tbl_clean}"
            
    query_no_strings = re.sub(r"'[^']*'", "", query)
    query_no_strings = re.sub(r'"[^"]*"', "", query_no_strings)
    query_no_strings = re.sub(r'`[^`]*`', "", query_no_strings)
    
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', query_no_strings)
    for w in words:
        w_lower = w.lower()
        if w_lower not in VALID_IDENTIFIERS:
            return False, f"Unauthorized column or identifier: '{w}'"
            
    return True, ""

def query_orders(question: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"sql": "", "rows": [], "error": "GROQ_API_KEY is not set"}

    client = Groq(api_key=api_key)
    
    prompt = f"""You are a translator that converts natural language questions into single SQLite queries.
The table name is 'orders' and the schema is:
orders (
    order_id TEXT PRIMARY KEY,
    customer TEXT,
    product TEXT,
    amount INTEGER,
    status TEXT,
    order_date TEXT
)

Return ONLY the raw SQL query. Do not wrap in markdown blocks, do not explain.
Today is 15 June 2026. Relative date calculations should be based on this date.
Examples:
- Question: "How many pending orders do we have?"
  SQL: SELECT COUNT(*) FROM orders WHERE status = 'pending'
- Question: "What is the total revenue from Sneha Reddy?"
  SQL: SELECT SUM(amount) FROM orders WHERE customer = 'Sneha Reddy'
- Question: "Show orders shipped last month"
  SQL: SELECT * FROM orders WHERE status = 'shipped' AND order_date >= '2026-05-01' AND order_date <= '2026-05-31'
- Question: "Who is the top customer by spending this quarter?"
  SQL: SELECT customer, SUM(amount) FROM orders WHERE order_date >= '2026-04-01' AND order_date <= '2026-06-30' GROUP BY customer ORDER BY SUM(amount) DESC LIMIT 1

Question: {question}
SQL:"""

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You output only raw SQLite query strings."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.0
        )
        sql_query = chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return {"sql": "", "rows": [], "error": f"LLM translation error: {str(e)}"}
        
    # Clean SQL if model wrapped it in code blocks despite instructions
    if sql_query.startswith("```"):
        lines = sql_query.split("\n")
        # Remove first and last line if they contain triple backticks
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        sql_query = "\n".join(lines).strip()
    if sql_query.upper().startswith("SQL"):
        sql_query = sql_query[3:].strip()
        
    valid, err_msg = validate_sql(sql_query)
    if not valid:
        return {"sql": sql_query, "rows": [], "error": f"SQL Validation Error: {err_msg}"}
        
    try:
        if not DB_PATH.exists():
            from ingest import ingest_orders

            csv_path = _resolve_data_path("orders.csv")
            if not csv_path.exists():
                return {"sql": "", "rows": [], "error": "orders.csv is not available"}

            ingest_orders(str(csv_path), str(DB_PATH))

        db_uri = f"file:{DB_PATH}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        columns = [d[0] for d in cursor.description]
        results = cursor.fetchall()
        conn.close()
        
        rows = [dict(zip(columns, row)) for row in results]
        return {"sql": sql_query, "rows": rows, "error": None}
    except Exception as e:
        return {"sql": sql_query, "rows": [], "error": f"Database execution error: {str(e)}"}
