# RAG Multi-User Knowledge Base

A multi-user RAG (Retrieval-Augmented Generation) knowledge base system with a web UI. Supports document upload (PDF/Word/TXT/Image OCR), manual QA pair entry, semantic search with LLM-enhanced answers, and conversation history.

## Screenshots

| | |
|---|---|
| ![登录页面](screenshots/login.png) | ![注册页面](screenshots/register.png) |
| ![上传文件](screenshots/upload.png) | ![手动录入](screenshots/manual.png) |
| ![普通对话](screenshots/chat.png) | ![知识库问答](screenshots/qa.png) |

## Features

- **Multi-user accounts** — each user has an isolated vector database
- **Document upload** — PDF, Word, TXT, images (auto OCR via PaddleOCR)
- **Manual entry** — batch add question-answer pairs
- **Semantic search** — BGE-M3 embeddings via ChromaDB
- **LLM-enhanced answers** — cites sources with `[1][2]` notation
- **Normal chat** — LLM also handles general conversation
- **Conversation history** — auto-saved, grouped by date, collapsible folders
- **Cross-network access** — optional bore/ngrok tunnel

## Quick Start

```bash
pip install -r requirements.txt
python rag_multi_user.py
```

Open http://127.0.0.1:5000 in your browser.

## Configuration

Edit these variables at the top of `rag_multi_user.py`:

| Variable | Default | Description |
|---|---|---|
| `LLM_API_KEY` | (your key) | 联达AI API key |
| `LLM_BASE_URL` | `https://lindaai.cn/v1` | LLM API endpoint |
| `LLM_MODEL` | `deepseek-v4-flash` | Model name |
| `app.secret_key` | `rag-secret-key-2024` | Flask session secret |

## Data Storage

| Data | Location |
|---|---|
| Vector store | `D:\rag_multi_db` (ChromaDB) |
| User accounts | `D:\rag_users.db` (SQLite) |
| Conversations | `D:\rag_conversations\{user}.json` |

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+K` | Focus chat input |
| `Ctrl+B` | Toggle knowledge base panel |
| `Ctrl+L` | New conversation |

## API Endpoints

| Method | Route | Description |
|---|---|---|
| POST | `/login` | User login |
| POST | `/register` | User registration |
| GET | `/logout` | Logout |
| POST | `/ask` | Ask a question (RAG + LLM) |
| POST | `/upload` | Upload a document |
| POST | `/add_batch` | Batch add manual QA pairs |
| GET | `/kb_docs` | List all knowledge base entries |
| POST | `/batch_delete` | Delete selected entries |
| POST | `/clear_all` | Clear all entries |
| GET/POST | `/conversations` | List / save conversations |
| DELETE | `/conversations/<id>` | Delete a conversation |

## Tunnel (External Access)

Edit `TUNNEL_MODE` in the script:
- `""` — no tunnel (default)
- `"ngrok"` — use pyngrok
- `"bore"` — use bore.pub
