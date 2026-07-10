import os
import json
import re
from groq import Groq

try:
    from tools import search_documents, query_orders
except ImportError:
    from backend.tools import search_documents, query_orders

SYSTEM_PROMPT = """You are a helpful assistant for EMB Global.
Today's date is 15 June 2026. Relative date calculations should be based on this date.
If you cannot answer the question using the retrieved information from the tools, or if the question is out of scope, answer: "I don't have that information."

When you decide to call a tool, you must follow the native tool call syntax. Make sure to always include the closing angle bracket '>' right after the tool name and before the JSON arguments, for example: <function=search_documents>{"query": "..."}</function> or <function=query_orders>{"question": "..."}</function>.
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
    
    # 1. Non-streaming call to check for tool choices
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.0
        )
    except Exception as e:
        yield json.dumps({"error": f"Groq API Error: {str(e)}"}) + "\n"
        return
        
    choice_msg = response.choices[0].message
    tool_calls = choice_msg.tool_calls
    
    tool_used = []
    citations = []
    sql_query = None
    sql_rows = None
    
    if tool_calls:
        messages.append(choice_msg)
        
        for call in tool_calls:
            func_name = call.function.name
            args = json.loads(call.function.arguments)
            tool_used.append(func_name)
            
            if func_name == "search_documents":
                query = args.get("query", "")
                results = search_documents(query)
                citations.extend(results)
                
                # If no valid document found, yield early fallback or pass empty content
                content = json.dumps(results) if results else "No documents found."
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": func_name,
                    "content": content
                })
                
            elif func_name == "query_orders":
                q = args.get("question", "")
                res = query_orders(q)
                sql_query = res.get("sql")
                sql_rows = res.get("rows")
                err = res.get("error")
                
                content = json.dumps(res)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": func_name,
                    "content": content
                })
        
        # Determine if we should trigger fallback before calling LLM again
        # If search was run but returned nothing AND sql was run but failed or returned nothing
        # (or if either run resulted in empty outcomes and no other tool succeeded)
        # Let's let the LLM synthesize, but guide it with system instructions.
        # Wait, if both tools returned empty/error, we can just yield fallback directly.
        # Let's check:
        has_docs = not ("search_documents" in tool_used and not citations)
        has_sql = not ("query_orders" in tool_used and (sql_rows is None or not sql_rows))
        
        if not has_docs or not has_sql:
            # Trigger immediate fallback to guarantee correctness and save latency/costs
            for chunk in ["I", " do", "n't", " have", " that", " information", "."]:
                yield json.dumps({"token": chunk}) + "\n"
            yield json.dumps({
                "metadata": {
                    "tool_used": tool_used,
                    "citations": citations,
                    "sql": sql_query,
                    "sql_rows": sql_rows
                }
            }) + "\n"
            return

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
        # No tool calls, output text directly (stream it locally)
        content = choice_msg.content or "I don't have that information."
        # If the LLM didn't call tools, make sure it didn't invent info.
        # Standardize fallback if it didn't call tools but didn't output the fallback string
        # e.g., if it gave general knowledge, override it with fallback if it doesn't match fallback
        if "I don't have that information" not in content:
            content = "I don't have that information."
            
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
