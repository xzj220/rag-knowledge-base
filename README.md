# 多用户 RAG 知识库问答系统

基于 Flask + ChromaDB + SentenceTransformer + LLM 的多用户知识库问答系统，支持文档上传、OCR 识别、手动录入、历史对话。

## 功能

- **多用户登录/注册** - 每个用户独立的知识库和对话历史
- **AI 对话** - 基于知识库的 RAG 问答，支持上下文记忆（最近 6 条）
- **知识库管理** - 上传文档（PDF/Word/TXT/图片）、手动录入、搜索、批量删除
- **OCR 识别** - 图片文字识别（需安装 PaddleOCR）
- **对话历史** - 按日期分组，支持删除单条对话
- **会话持久化** - 知识库和对话数据存在 `/data` 目录

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | Flask |
| 向量数据库 | ChromaDB |
| 嵌入模型 | BAAI/bge-small-zh-v1.5（33MB，中文优化） |
| LLM | OpenAI 兼容 API（默认联达AI，可切换） |
| 文档解析 | LangChain（PyPDFLoader / TextLoader / UnstructuredWordDocumentLoader） |
| OCR | PaddleOCR（可选） |

## 快速开始

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python rag_multi_user.py
```

访问 http://127.0.0.1:5000

### Railway 部署

1. Fork 此仓库到你的 GitHub
2. 在 [Railway](https://railway.com) 新建项目，选择 GitHub 仓库
3. Builder 选择 **Nixpacks**（默认）
4. Start Command 填 `python rag_multi_user.py`
5. 添加环境变量（可选）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATA_DIR` | 数据持久化目录 | `/data` |
| `LLM_API_KEY` | LLM API 密钥 | 内置测试 key |
| `LLM_BASE_URL` | LLM API 地址 | `https://lindaai.cn/v1` |
| `LLM_MODEL` | LLM 模型名 | `deepseek-v4-flash` |
| `EMBED_MODEL` | 嵌入模型 | `BAAI/bge-small-zh-v1.5` |
| `SECRET_KEY` | Flask 密钥 | 随机字符串 |

6. 部署成功后访问 `https://你的项目名.up.railway.app`

## 环境变量详解

### LLM 配置

系统使用 OpenAI 兼容的 API，默认使用联达AI（国内可直连）的 deepseek-v4-flash 模型。

如需切换其他 LLM：

```bash
# 切换到 OpenAI
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 切换到 DeepSeek 官方
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 嵌入模型

默认 `BAAI/bge-small-zh-v1.5`（33MB，中文专用，适合 Railway 免费版 512MB 内存）。

如需更好的检索效果（需要更多内存）：

```bash
EMBED_MODEL=BAAI/bge-m3       # 2.2GB，效果最好
EMBED_MODEL=all-MiniLM-L6-v2  # 80MB，英文优化
```

## 部署注意事项

### Railway 免费版限制

- **512MB 内存** - 选择 `bge-small-zh-v1.5` 嵌入模型（33MB）避免 OOM
- **无持久化存储** - 重新部署后上传的知识库数据会清空（对话历史保存在 JSON 文件，同样会丢失）
- **如需持久化** - 升级付费计划后，在 Volumes 添加挂载 `/data`

### 网络访问

- Railway 服务器在美国西部，确保 LLM API 可从美国访问
- 默认联达AI (`lindaai.cn`) 是国内服务，从美国可能无法连接，建议配置 OpenAI 或其他国际 API

## 项目结构

```
rag-knowledge-base/
├── rag_multi_user.py    # 主程序（Flask 应用 + 前端模板）
├── requirements.txt     # Python 依赖
├── Procfile            # Railway 启动配置
└── README.md           # 本文件
```

## 常见问题

**Q: 知识库上传后对话还是说"未找到相关材料"？**
A: 检查知识库面板是否有数据。如果刚上传，需要先存数据再提问。如果重新部署过，数据会丢失需要重新上传。

**Q: AI 对话返回"请求失败"？**
A: 检查 LLM_API_KEY 是否正确，以及 LLM_BASE_URL 是否可从当前网络环境访问。

**Q: 手动录入提示"处理失败"？**
A: 确保每行格式为 `问题+是+答案`（例如：`张三的电话是138xxxx`）。
