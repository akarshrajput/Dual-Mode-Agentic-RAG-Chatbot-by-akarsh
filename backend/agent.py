import os
import json
import re
from typing import Optional, Tuple
from groq import Groq

try:
    from tools import search_documents, query_orders
except ImportError:
    from backend.tools import search_documents, query_orders

SYSTEM_PROMPT = """You are a helpful assistant for EMB Global.
Today's date is 15 June 2026. Relative date calculations should be based on this date.

You have access to two tools:
1. search_documents — searches company policy PDFs (HR leave policy, returns policy, warranty policy, pricing & discounts policy, product FAQ). Use this for ANY question about company policies, employee benefits, product info, warranties, returns, pricing, or FAQs.
2. query_orders — queries the orders database. Use this for questions about sales, revenue, order counts, customer orders, or order status.

IMPORTANT INSTRUCTIONS:
- ALWAYS call a tool before answering. Do NOT answer from your own knowledge.
- When you receive document search results, carefully READ the retrieved text chunks and extract the answer from them. The answer IS in the retrieved text — look carefully.
- Only say "I don't have that information." if the retrieved documents truly do not contain any relevant information to answer the question.
- Provide clear, specific answers with details from the source documents.
"""

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Searches unstructured documents for company policies, guidelines, product FAQs, leave rules, returns, and warranty info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to match against document chunks."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_orders",
            "description": "Queries the structured orders database. Call this for questions about sales, revenue, order details, order dates, or customer orders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's natural language question. Pass the question directly as written by the user. Do NOT translate the question to SQL; the tool will perform the translation internally."
                    }
                },
                "required": ["question"]
            }
        }
    }
]


def _parse_failed_tool_call(error_body: dict) -> Tuple[Optional[str], Optional[dict]]:
    """Parse a function name and args from Groq's failed_generation field.

    When Llama generates a malformed text-based tool call like:
        <function=search_documents>{"query": "..."}</function>
    or  <function=search_documents{"query": "..."}</function>
    Groq returns a 400 with 'tool_use_failed' and the raw text in 'failed_generation'.
    This helper extracts the function name and JSON arguments so we can execute manually.
    """
    failed = error_body.get("error", {}).get("failed_generation", "")
    if not failed:
        return None, None

    # Pattern: <function=FUNC_NAME>JSON</function>  or  <function=FUNC_NAMEJSON</function>
    match = re.search(
        r'<function=(\w+)>?\s*(\{.*?\})\s*</function>',
        failed,
        re.DOTALL,
    )
    if not match:
        return None, None

    func_name = match.group(1)
    try:
        args = json.loads(match.group(2))
    except json.JSONDecodeError:
        return None, None

    return func_name, args


def _execute_tool(func_name: str, args: dict):
    """Execute a tool by name and return (result_content, tool_used, citations, sql_query, sql_rows)."""
    citations = []
    sql_query = None
    sql_rows = None

    if func_name == "search_documents":
        query = args.get("query", "")
        results = search_documents(query)
        citations.extend(results)
        content = json.dumps(results) if results else "No documents found."
    elif func_name == "query_orders":
        q = args.get("question", "")
        res = query_orders(q)
        sql_query = res.get("sql")
        sql_rows = res.get("rows")
        content = json.dumps(res)
    else:
        content = json.dumps({"error": f"Unknown tool: {func_name}"})

    return content, citations, sql_query, sql_rows


def run_agent_loop(user_message: str):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        yield json.dumps({"error": "GROQ_API_KEY is not set"}) + "\n"
        return

    client = Groq(api_key=api_key)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]
    
    tool_used = []
    citations = []
    sql_query = None
    sql_rows = None
    tool_calls = None
    fallback_tool = None  # Set when we recover from a failed tool call

    # 1. Non-streaming call to check for tool choices
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.0
        )
        choice_msg = response.choices[0].message
        tool_calls = choice_msg.tool_calls
    except Exception as e:
        error_str = str(e)
        # Check if this is a tool_use_failed error from Groq
        if "tool_use_failed" in error_str or "Failed to call a function" in error_str:
            # Parse the function call directly from the error string
            # (Groq uses Python repr format with single quotes, not valid JSON,
            #  so we extract the <function=...> pattern directly)
            func_match = re.search(
                r'<function=(\w+)>?\s*(\{.*?\})\s*</function>',
                error_str,
                re.DOTALL,
            )
            if func_match:
                func_name = func_match.group(1)
                try:
                    args = json.loads(func_match.group(2))
                    fallback_tool = (func_name, args)
                except json.JSONDecodeError:
                    pass

            if not fallback_tool:
                yield json.dumps({"error": f"Groq API Error: {error_str}"}) + "\n"
                return
        else:
            yield json.dumps({"error": f"Groq API Error: {error_str}"}) + "\n"
            return

    # Handle tool calls — either from the API response or recovered from failed_generation
    if tool_calls or fallback_tool:
        if tool_calls:
            messages.append(choice_msg)

            for call in tool_calls:
                func_name = call.function.name
                args = json.loads(call.function.arguments)
                tool_used.append(func_name)

                content, cit, sq, sr = _execute_tool(func_name, args)
                citations.extend(cit)
                if sq is not None:
                    sql_query = sq
                if sr is not None:
                    sql_rows = sr

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": func_name,
                    "content": content
                })
        else:
            # Recovered from failed_generation — execute manually
            func_name, args = fallback_tool
            tool_used.append(func_name)

            content, cit, sq, sr = _execute_tool(func_name, args)
            citations.extend(cit)
            if sq is not None:
                sql_query = sq
            if sr is not None:
                sql_rows = sr

            # Build messages as if the tool was called normally (use assistant + user context)
            messages.append({
                "role": "assistant",
                "content": f"I searched using {func_name} for the user's question."
            })
            messages.append({
                "role": "user",
                "content": f"Here are the results from {func_name}:\n{content}\n\nBased on these results, please answer the original question: {user_message}"
            })

        # 2. Final call (streaming) with tool outputs
        try:
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.0,
                stream=True
            )
            for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    yield json.dumps({"token": token}) + "\n"
        except Exception as e:
            yield json.dumps({"error": f"Streaming Error: {str(e)}"}) + "\n"
            return
            
    else:
        # No tool calls — the LLM may have answered directly or provided a fallback
        content = choice_msg.content or "I don't have that information."
            
        words = re.findall(r'\s+|\S+', content)
        for w in words:
            yield json.dumps({"token": w}) + "\n"
            
    # Yield final metadata packet
    yield json.dumps({
        "metadata": {
            "tool_used": tool_used,
            "citations": citations,
            "sql": sql_query,
            "sql_rows": sql_rows
        }
    }) + "\n"
