# Dual-Mode Agentic RAG Chatbot

An assessment chatbot that answers questions using vector RAG over company documents and text-to-SQL over an orders database.

## Architecture

- **Backend**: FastAPI, Python 3.11.
- **LLM**: Groq API using model `llama-3.3-70b-versatile`. Native tool calling is utilized.
- **Embeddings**: Sentence-transformers running locally (`all-MiniLM-L6-v2`) on CPU. This avoids extra external API cost and rate limits.
- **Vector Store**: Chroma (local, persisted embedded store).
- **Structured Data**: SQLite loaded dynamically from `data/orders.csv` during ingestion. Opened with read-only connection limits (`mode=ro`).

## How Routing Works

1. The user's question is sent to the backend.
2. A single non-streaming call is made to Groq with two tool definitions: `search_documents` and `query_orders`.
3. If Groq decides to call one or both tools:
   - The backend runs the Python helper functions for those tools.
   - For `search_documents`: Similarity search runs in Chroma. Chunks with cosine similarity score >= 0.35 are returned.
   - For `query_orders`: Groq generates a SQLite query, which is strictly validated by our validator. If valid, it is executed against SQLite in read-only mode.
   - The tool outputs are sent back as tool messages to the conversation history.
   - A final streaming call is made to Groq to synthesize the answer based on the retrieved information.
4. If no tools are called, or if the tools return empty results/errors, the agent loops and yields the exact fallback: "I don't have that information."
5. At the end of the stream, a metadata JSON packet is appended containing the citations, SQL query, and query results.

## SQL Safety and Validation

The generated SQL is strictly validated before execution:
- Must start with `SELECT` (case-insensitive).
- Multiple SQL statements separated by semicolons are rejected.
- Any table reference in `FROM` or `JOIN` must be `orders` only.
- Identifiers in the query are tokenized and checked against a strict whitelist of SQLite functions, keywords, and the real columns (`order_id`, `customer`, `product`, `amount`, `status`, `order_date`). Any unknown column or function is blocked.
- The connection is opened as read-only (`mode=ro`) at the SQLite engine level to prevent write activity.

## Example Q&As

1. **Q**: "How many leave days do employees get for marriage?"
   - **Tool called**: `search_documents`
   - **Result**: Detailed policy returned (e.g. 5 consecutive working days).

2. **Q**: "What is the policy for returns?"
   - **Tool called**: `search_documents`
   - **Result**: Details on returns (e.g. within 30 days of purchase).

3. **Q**: "How many orders were shipped in May 2026?"
   - **Tool called**: `query_orders`
   - **Result**: Total shipped count parsed from SQL.

4. **Q**: "What is the total revenue from Sneha Reddy?"
   - **Tool called**: `query_orders`
   - **Result**: Total amount calculated.

5. **Q**: "What is the capital of France?"
   - **Tool called**: None
   - **Result**: "I don't have that information." (Out of scope).

6. **Q**: "How many days of leave do I get for marriage and what was the total revenue in May 2026?"
   - **Tool called**: `search_documents` & `query_orders`
   - **Result**: Synthesized answer containing both policy text and order database metrics.

7. **Q**: "What is the policy for pet leave?"
   - **Tool called**: `search_documents`
   - **Result**: "I don't have that information." (No documents match pet leave above similarity threshold).

8. **Q**: "Show me the top customer by sales in 2026 from the users table"
   - **Tool called**: None / `query_orders` (blocked by validator)
   - **Result**: "I don't have that information." (Table `users` rejected by validator).

9. **Q**: "Give me the order dates of order ORD-9999"
   - **Tool called**: `query_orders`
   - **Result**: "I don't have that information." (Executes query but zero rows returned, triggers fallback).

10. **Q**: "Tell me about the discount policy and how many pending orders we have"
    - **Tool called**: `search_documents` & `query_orders`
    - **Result**: Displays pricing discount info and active count of pending orders.

## Limitations

- Groq tool calling is non-streaming on the first turn. Token-level streaming only begins on the final synthesis turn.
- Complex nested subqueries in SQL may fail validation if they use functions outside the whitelisted keywords.
- Dates are anchored to 15 June 2026. Queries asking about dates beyond the dataset range or today's date will resolve relative to June 15, 2026.
