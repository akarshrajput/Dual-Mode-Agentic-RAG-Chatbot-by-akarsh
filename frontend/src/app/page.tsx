"use client";

import { useState, useRef, useEffect, FormEvent } from "react";

interface Citation {
  text: string;
  source: string;
  chunk_index: number;
  score: number;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool_used?: string[];
  citations?: Citation[];
  sql?: string;
  sql_rows?: any[];
  error?: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [openSection, setOpenSection] = useState<{ [key: string]: "none" | "citations" | "sql" }>({});
  const [backendReady, setBackendReady] = useState(false);
  const [backendChecking, setBackendChecking] = useState(true);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Backend health check with cold-start handling
  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    let cancelled = false;
    let timerInterval: NodeJS.Timeout;

    // Start elapsed timer
    const startTime = Date.now();
    timerInterval = setInterval(() => {
      if (!cancelled) {
        setElapsedSeconds(Math.floor((Date.now() - startTime) / 1000));
      }
    }, 1000);

    const checkHealth = async () => {
      while (!cancelled) {
        try {
          const res = await fetch(`${apiUrl}/health`, { signal: AbortSignal.timeout(5000) });
          if (res.ok) {
            if (!cancelled) {
              setBackendReady(true);
              setBackendChecking(false);
            }
            break;
          }
        } catch {
          // Backend not ready yet, retry
        }
        // Wait 3 seconds before retrying
        await new Promise((r) => setTimeout(r, 3000));
      }
    };

    checkHealth();

    return () => {
      cancelled = true;
      clearInterval(timerInterval);
    };
  }, []);

  const toggleSection = (messageId: string, section: "citations" | "sql") => {
    setOpenSection((prev) => {
      const current = prev[messageId];
      if (current === section) {
        return { ...prev, [messageId]: "none" };
      }
      return { ...prev, [messageId]: section };
    });
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading || !backendReady) return;

    const userMessageText = input.trim();
    setInput("");
    setLoading(true);

    const userMessage: Message = {
      id: `msg-${Date.now()}-user`,
      role: "user",
      content: userMessageText,
    };

    const assistantMessageId = `msg-${Date.now()}-assistant`;
    const assistantMessagePlaceholder: Message = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
    };

    setMessages((prev) => [...prev, userMessage, assistantMessagePlaceholder]);

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

    try {
      const response = await fetch(`${apiUrl}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message: userMessageText }),
      });

      if (!response.ok || !response.body) {
        throw new Error("Failed to reach chatbot backend");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;

          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6).trim();
            if (dataStr === "[DONE]") continue;

            try {
              const data = JSON.parse(dataStr);
              if (data.token) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? { ...msg, content: msg.content + data.token }
                      : msg
                  )
                );
              } else if (data.metadata) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          tool_used: data.metadata.tool_used || [],
                          citations: data.metadata.citations || [],
                          sql: data.metadata.sql,
                          sql_rows: data.metadata.sql_rows,
                        }
                      : msg
                  )
                );
              } else if (data.error) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? { ...msg, error: data.error }
                      : msg
                  )
                );
              }
            } catch (err) {
              console.error("Error parsing JSON line:", err, dataStr);
            }
          }
        }
      }
    } catch (err: any) {
      console.error(err);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, error: err.message || "An unexpected error occurred." }
            : msg
        )
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        maxWidth: "960px",
        margin: "0 auto",
        padding: "20px",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden"
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "30px",
          borderBottom: "1px solid var(--border-color)",
          paddingBottom: "20px",
        }}
      >
        <div>
          <h1
            style={{
              margin: 0,
              fontSize: "28px",
              fontWeight: 700,
              letterSpacing: "-0.5px",
              background: "linear-gradient(135deg, #ffffff 0%, #a5b4fc 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            EMB Global Agent
          </h1>
          <p style={{ margin: "5px 0 0 0", color: "var(--text-secondary)", fontSize: "14px" }}>
            Dual-Mode RAG Chatbot (Document Semantics + Text-to-SQL DB)
          </p>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            background: "rgba(30, 41, 59, 0.4)",
            padding: "6px 12px",
            borderRadius: "20px",
            border: `1px solid ${backendReady ? 'rgba(16, 185, 129, 0.3)' : 'rgba(251, 191, 36, 0.3)'}`,
            fontSize: "13px",
            color: backendReady ? "#10b981" : "#fbbf24",
            fontWeight: 500,
            transition: "all 0.5s ease",
          }}
        >
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: backendReady ? "#10b981" : "#fbbf24",
              animation: backendReady ? "pulse 2s infinite" : "pulse 1s infinite",
            }}
          />
          {backendReady ? "System Online" : "Waking Up..."}
        </div>
      </header>

      {/* Cold-start banner */}
      {backendChecking && !backendReady && (
        <div
          style={{
            background: "linear-gradient(135deg, rgba(251, 191, 36, 0.08) 0%, rgba(245, 158, 11, 0.08) 100%)",
            border: "1px solid rgba(251, 191, 36, 0.25)",
            borderRadius: "12px",
            padding: "16px 20px",
            marginBottom: "20px",
            animation: "fadeIn 0.5s ease",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "10px" }}>
            <span style={{ fontSize: "20px" }}>☕</span>
            <div>
              <div style={{ color: "#fbbf24", fontWeight: 600, fontSize: "14px" }}>
                Backend is waking up on Render (free tier cold start)
              </div>
              <div style={{ color: "rgba(251, 191, 36, 0.7)", fontSize: "13px", marginTop: "2px" }}>
                This typically takes about 50–60 seconds. Please wait...
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                flex: 1,
                height: "4px",
                background: "rgba(251, 191, 36, 0.15)",
                borderRadius: "4px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${Math.min((elapsedSeconds / 60) * 100, 95)}%`,
                  background: "linear-gradient(90deg, #fbbf24, #f59e0b)",
                  borderRadius: "4px",
                  transition: "width 1s linear",
                }}
              />
            </div>
            <span style={{ color: "rgba(251, 191, 36, 0.8)", fontSize: "12px", fontWeight: 600, minWidth: "30px" }}>
              {elapsedSeconds}s
            </span>
          </div>
        </div>
      )}

      {/* Backend ready success banner (briefly shown) */}
      {backendReady && elapsedSeconds > 3 && elapsedSeconds < 8 && (
        <div
          style={{
            background: "linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(52, 211, 153, 0.08) 100%)",
            border: "1px solid rgba(16, 185, 129, 0.25)",
            borderRadius: "12px",
            padding: "12px 20px",
            marginBottom: "20px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
            animation: "fadeIn 0.5s ease",
          }}
        >
          <span style={{ fontSize: "18px" }}>✅</span>
          <span style={{ color: "#34d399", fontWeight: 600, fontSize: "14px" }}>
            Backend is live! You can start chatting now.
          </span>
        </div>
      )}

      <section
        style={{
          flex: 1,
          background: "var(--card-bg)",
          backdropFilter: "blur(12px)",
          border: "1px solid var(--border-color)",
          borderRadius: "var(--radius-lg)",
          overflowY: "auto",
          padding: "24px",
          marginBottom: "24px",
          display: "flex",
          flexDirection: "column",
          gap: "24px",
          boxShadow: "var(--shadow-primary)",
        }}
      >

        {messages.map((msg) => {
          const isUser = msg.role === "user";
          return (
            <div
              key={msg.id}
              className="message-item"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: isUser ? "flex-end" : "flex-start",
                maxWidth: "80%",
                alignSelf: isUser ? "flex-end" : "flex-start",
              }}
            >
              <div
                style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  color: isUser ? "#3b82f6" : "#818cf8",
                  marginBottom: "6px",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                }}
              >
                {isUser ? "You" : "EMB Assistant"}
              </div>

              <div
                style={{
                  background: isUser ? "var(--user-bubble-gradient)" : "var(--agent-bubble-bg)",
                  color: "#fff",
                  padding: "14px 18px",
                  borderRadius: isUser ? "16px 16px 2px 16px" : "16px 16px 16px 2px",
                  lineHeight: "1.6",
                  fontSize: "15px",
                  border: isUser ? "none" : "1px solid var(--border-color)",
                  boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                  whiteSpace: "pre-wrap",
                }}
              >
                {msg.content}

                {msg.error && (
                  <div
                    style={{
                      marginTop: "10px",
                      color: "#f87171",
                      background: "rgba(248, 113, 113, 0.1)",
                      border: "1px solid rgba(248, 113, 113, 0.2)",
                      padding: "8px 12px",
                      borderRadius: "6px",
                      fontSize: "13px",
                    }}
                  >
                    ⚠️ {msg.error}
                  </div>
                )}
              </div>

              {!isUser && msg.tool_used && msg.tool_used.length > 0 && (
                <div style={{ marginTop: "8px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  {msg.tool_used.map((tool) => {
                    const isRAG = tool === "search_documents";
                    return (
                      <span
                        key={tool}
                        style={{
                          background: isRAG
                            ? "linear-gradient(135deg, rgba(59, 130, 246, 0.15) 0%, rgba(99, 102, 241, 0.15) 100%)"
                            : "linear-gradient(135deg, rgba(139, 92, 246, 0.15) 0%, rgba(236, 72, 153, 0.15) 100%)",
                          color: isRAG ? "#60a5fa" : "#c084fc",
                          border: isRAG ? "1px solid rgba(59, 130, 246, 0.3)" : "1px solid rgba(139, 92, 246, 0.3)",
                          padding: "3px 10px",
                          borderRadius: "20px",
                          fontSize: "11px",
                          fontWeight: 600,
                          letterSpacing: "0.2px",
                        }}
                      >
                        ⚙️ {isRAG ? "Vector Search" : "SQL Query Engine"}
                      </span>
                    );
                  })}
                </div>
              )}

              {!isUser && (msg.citations?.length || 0) > 0 && (
                <div style={{ marginTop: "8px" }}>
                  <button
                    onClick={() => toggleSection(msg.id, "citations")}
                    style={{
                      background: "rgba(255,255,255,0.03)",
                      border: "1px solid var(--border-color)",
                      color: "var(--text-secondary)",
                      borderRadius: "6px",
                      cursor: "pointer",
                      padding: "4px 10px",
                      fontSize: "12px",
                      fontWeight: 500,
                      transition: "all 0.2s",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.08)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.03)")}
                  >
                    {openSection[msg.id] === "citations" ? "▼ Hide Citations" : `▶ View Citations (${msg.citations?.length})`}
                  </button>
                  
                  {openSection[msg.id] === "citations" && msg.citations && (
                    <div
                      style={{
                        marginTop: "8px",
                        background: "rgba(15, 23, 42, 0.6)",
                        border: "1px solid var(--border-color)",
                        padding: "12px",
                        borderRadius: "8px",
                        maxHeight: "220px",
                        overflowY: "auto",
                        width: "100%",
                      }}
                    >
                      {msg.citations.map((c, i) => (
                        <div
                          key={i}
                          style={{
                            marginBottom: "10px",
                            fontSize: "13px",
                            borderBottom: i < msg.citations!.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none",
                            paddingBottom: "8px",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", color: "#818cf8", fontWeight: 600, fontSize: "12px" }}>
                            <span>
                              [{i + 1}] {c.source} (Chunk {c.chunk_index})
                            </span>
                            <span style={{ color: "#34d399" }}>
                              Match: {(c.score * 100).toFixed(0)}%
                            </span>
                          </div>
                          <div style={{ color: "var(--text-secondary)", marginTop: "4px", fontStyle: "italic", fontSize: "12.5px" }}>
                            "{c.text}"
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {!isUser && msg.sql && (
                <div style={{ marginTop: "8px" }}>
                  <button
                    onClick={() => toggleSection(msg.id, "sql")}
                    style={{
                      background: "rgba(255,255,255,0.03)",
                      border: "1px solid var(--border-color)",
                      color: "var(--text-secondary)",
                      borderRadius: "6px",
                      cursor: "pointer",
                      padding: "4px 10px",
                      fontSize: "12px",
                      fontWeight: 500,
                      transition: "all 0.2s",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.08)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.03)")}
                  >
                    {openSection[msg.id] === "sql" ? "▼ Hide Generated SQL" : "▶ View Generated SQL"}
                  </button>
                  
                  {openSection[msg.id] === "sql" && (
                    <div
                      style={{
                        marginTop: "8px",
                        background: "rgba(15, 23, 42, 0.6)",
                        border: "1px solid var(--border-color)",
                        padding: "14px",
                        borderRadius: "8px",
                        width: "100%",
                      }}
                    >
                      <pre
                        style={{
                          margin: 0,
                          background: "#0f172a",
                          padding: "10px",
                          borderRadius: "4px",
                          fontSize: "12px",
                          overflowX: "auto",
                          color: "#38bdf8",
                          border: "1px solid rgba(56, 189, 248, 0.15)",
                          fontFamily: "monospace",
                        }}
                      >
                        {msg.sql}
                      </pre>
                      
                      {msg.sql_rows && (
                        <div style={{ marginTop: "12px" }}>
                          <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--text-secondary)", marginBottom: "6px" }}>
                            Database Records Return ({msg.sql_rows.length}):
                          </div>
                          
                          {msg.sql_rows.length > 0 ? (
                            <div style={{ overflowX: "auto", border: "1px solid var(--border-color)", borderRadius: "6px" }}>
                              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12.5px" }}>
                                <thead>
                                  <tr style={{ background: "rgba(255,255,255,0.03)" }}>
                                    {Object.keys(msg.sql_rows[0]).map((key) => (
                                      <th
                                        key={key}
                                        style={{
                                          borderBottom: "1px solid var(--border-color)",
                                          padding: "8px 12px",
                                          color: "#fff",
                                          fontWeight: 600,
                                          textAlign: "left",
                                        }}
                                      >
                                        {key}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {msg.sql_rows.map((row, idx) => (
                                    <tr key={idx} style={{ borderBottom: idx < msg.sql_rows!.length - 1 ? "1px solid var(--border-color)" : "none" }}>
                                      {Object.values(row).map((val: any, cellIdx) => (
                                        <td key={cellIdx} style={{ padding: "8px 12px", color: "var(--text-secondary)" }}>
                                          {String(val)}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <div style={{ fontSize: "12px", color: "#ef4444" }}>Empty result set returned.</div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </section>

      <form
        onSubmit={handleSubmit}
        style={{
          display: "flex",
          gap: "12px",
          background: "rgba(30, 41, 59, 0.4)",
          border: "1px solid var(--border-color)",
          padding: "8px",
          borderRadius: "var(--radius-md)",
          boxShadow: "0 4px 20px rgba(0,0,0,0.15)",
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask EMB Global agent..."
          disabled={loading || !backendReady}
          style={{
            flex: 1,
            background: "none",
            border: "none",
            outline: "none",
            padding: "12px 16px",
            fontSize: "15px",
            color: "#fff",
            opacity: backendReady ? 1 : 0.5,
          }}
        />
        <button
          type="submit"
          disabled={loading || !input.trim() || !backendReady}
          style={{
            background: loading || !input.trim() || !backendReady ? "rgba(255,255,255,0.05)" : "var(--accent-gradient)",
            color: loading || !input.trim() || !backendReady ? "rgba(255,255,255,0.3)" : "#fff",
            padding: "0 24px",
            border: "none",
            borderRadius: "var(--radius-sm)",
            fontSize: "14px",
            fontWeight: 600,
            cursor: loading || !input.trim() || !backendReady ? "not-allowed" : "pointer",
            transition: "opacity 0.2s",
          }}
        >
          {!backendReady ? "Waiting..." : loading ? "Thinking..." : "Send Query"}
        </button>
      </form>
    </div>
  );
}
