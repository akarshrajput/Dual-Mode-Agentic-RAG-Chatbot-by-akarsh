import os
import json
from dotenv import load_dotenv
load_dotenv()

from tools import validate_sql, search_documents, query_orders
from agent import run_agent_loop

def test_sql_validation():
    print("Running SQL validation tests...")
    
    # 1. Valid cases
    valid_cases = [
        "SELECT * FROM orders",
        "SELECT count(*) FROM orders WHERE status = 'pending'",
        "SELECT customer, sum(amount) FROM orders GROUP BY customer ORDER BY sum(amount) DESC LIMIT 1",
        "SELECT order_id, product, amount FROM orders WHERE order_date >= '2026-05-01' AND order_date <= '2026-05-31'",
        "SELECT * FROM orders WHERE status = 'shipped' AND order_date LIKE '2026-06%';"
    ]
    for case in valid_cases:
        ok, err = validate_sql(case)
        assert ok, f"Expected valid query to pass, but failed: {case}. Error: {err}"
        
    # 2. Invalid cases: forbidden keywords
    invalid_keywords = [
        "SELECT * FROM orders UNION SELECT * FROM orders",
        "DROP TABLE orders",
        "SELECT * FROM orders; DROP TABLE orders",
        "INSERT INTO orders (order_id) VALUES ('1')",
        "DELETE FROM orders WHERE order_id = '1'",
        "UPDATE orders SET status = 'delivered'"
    ]
    for case in invalid_keywords:
        ok, err = validate_sql(case)
        assert not ok, f"Expected forbidden keyword query to fail, but passed: {case}"
        print(f"  Correctly rejected keyword in: {case} -> {err}")
        
    # 3. Invalid cases: unauthorized tables
    invalid_tables = [
        "SELECT * FROM users",
        "SELECT * FROM orders, customers",
        "SELECT * FROM orders JOIN clients ON orders.customer = clients.name"
    ]
    for case in invalid_tables:
        ok, err = validate_sql(case)
        assert not ok, f"Expected unauthorized table query to fail, but passed: {case}"
        print(f"  Correctly rejected table in: {case} -> {err}")
        
    # 4. Invalid cases: unauthorized columns/identifiers
    invalid_columns = [
        "SELECT unauthorized_column FROM orders",
        "SELECT * FROM orders WHERE random_field = 10",
        "SELECT order_id, md5(customer) FROM orders"
    ]
    for case in invalid_columns:
        ok, err = validate_sql(case)
        assert not ok, f"Expected unauthorized column/identifier query to fail, but passed: {case}"
        print(f"  Correctly rejected identifier in: {case} -> {err}")
        
    print("SQL validation tests passed!\n")

def test_document_search():
    print("Running document search tests...")
    # This queries Chroma DB which should be populated by ingest.py
    results = search_documents("How many leave days for marriage?")
    print(f"Found {len(results)} document chunks matching 'marriage leave'")
    for r in results:
        print(f"  - Source: {r['source']}, Chunk: {r['chunk_index']}, Score: {r['score']:.4f}")
        print(f"    Text: {r['text'][:100]}...")
    
    # Query something out of scope/non-existent
    results_empty = search_documents("What is the capital of France?")
    assert len(results_empty) == 0, "Expected 0 results for out-of-scope query"
    print("  Correctly got 0 results for out-of-scope query: 'capital of France'\n")

def test_routing_and_agent():
    print("Running agent routing and loop tests...")
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("  SKIPPING agent loop tests because GROQ_API_KEY is not set.\n")
        return
        
    # Test cases:
    # 1. SQL metrics query
    print("Testing SQL Query Routing...")
    generator = run_agent_loop("How many orders are pending?")
    response_text = ""
    metadata = None
    for line in generator:
        data = json.loads(line.strip())
        if "token" in data:
            response_text += data["token"]
        elif "metadata" in data:
            metadata = data["metadata"]
    print(f"Response: {response_text.strip()}")
    print(f"Metadata: {metadata}")
    assert metadata and "query_orders" in metadata["tool_used"], "Expected query_orders to run"
    
    # 2. Document policy query
    print("\nTesting Document Search Routing...")
    generator = run_agent_loop("What is the policy for bereavement leave?")
    response_text = ""
    metadata = None
    for line in generator:
        data = json.loads(line.strip())
        if "token" in data:
            response_text += data["token"]
        elif "metadata" in data:
            metadata = data["metadata"]
    print(f"Response: {response_text.strip()}")
    print(f"Metadata: {metadata}")
    assert metadata and "search_documents" in metadata["tool_used"], "Expected search_documents to run"
    
    # 3. Out-of-scope query
    print("\nTesting Out-of-scope Fallback...")
    generator = run_agent_loop("What is the speed of light?")
    response_text = ""
    metadata = None
    for line in generator:
        data = json.loads(line.strip())
        if "token" in data:
            response_text += data["token"]
        elif "metadata" in data:
            metadata = data["metadata"]
    print(f"Response: {response_text.strip()}")
    print(f"Metadata: {metadata}")
    assert response_text.strip() == "I don't have that information.", f"Expected fallback string, got: {response_text}"
    
    print("Agent routing tests passed!\n")

if __name__ == "__main__":
    test_sql_validation()
    test_document_search()
    test_routing_and_agent()
