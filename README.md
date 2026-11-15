# WhatsApp Chat RAG

This is a backend for searching exported WhatsApp chats. A project can hold many `.zip` files. Each upload request sends one zip. The API unpacks the zips, keeps the chats, documents, and voice notes, splits them into chunks, stores embeddings in PostgreSQL with pgvector, and answers questions with an OpenAI-compatible model (OpenAI, Gemini, or a local Ollama server).

Each zip can contain:

- The chat is `chat.txt` or a file whose name starts with `WhatsApp Chat with`. Messages are grouped when they are less than one hour apart. A deleted message, a call, `<image omitted>`, and any line that ends with `(file attached)` is not stored as chat text. The `(file attached)` line is used only to copy the sender and time onto that file.
- `.txt`, `.pdf`, and `.docx` files are saved under `assets/files/<project id>/document/` and split with a normal text splitter.
- Audio (`.opus`, `.m4a`, `.mp3`, `.ogg`, `.wav`, `.aac`) is saved under `records/`, transcribed locally with faster-whisper on the CPU (`WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE_TYPE=int8`) in `SPEECH_LANGUAGE`, and chunked on its own. Overlap stays inside that one recording. The `base` model is downloaded into the API image when that image is built.
- Images are skipped.
- Every extracted file becomes its own row in `assets`, pointing at the zip it came from.

The usual order is upload, process, index, then search or answer.

## Endpoints

The project id in the path is a number, for example `1`. The first upload or process call creates that project.

| Method and path | What it does |
|---|---|
| `GET /api/v1/` | Returns the app name, version, primary language, generation model, and embedding model. |
| `POST /api/v1/data/upload/{project_id}` | Adds one zip to the project. Call it again to add another zip. Form field name is `file`. Content type must be `application/zip` or `application/x-zip-compressed`. The file must be smaller than `FILE_MAX_SIZE` megabytes. |
| `POST /api/v1/data/process/{project_id}` | Unpacks the project's zips, transcribes voice notes, and writes chunks. |
| `POST /api/v1/nlp/index/push/{project_id}` | Embeds the chunks and writes them to the vector table. Run this after process. |
| `GET /api/v1/nlp/index/info/{project_id}` | Returns the vector collection name and row count. |
| `POST /api/v1/nlp/index/search/{project_id}` | Returns the closest chunks for a question. |
| `POST /api/v1/nlp/index/answer/{project_id}` | Answers the question from those chunks. Arabic and English templates follow `PRIMARY_LANG` and `DEFAULT_LANG`. |
| `DELETE /api/v1/data/{project_id}` | Deletes that project's database rows, vector table, and files on disk. The method must be DELETE. |

Interactive docs: http://localhost:8000/docs

### Upload

`POST /api/v1/data/upload/1` with form-data field `file`.

Each call uploads one zip. Repeat the call to add more zips to the same project. A successful response contains `file_id`, which is the database id of that zip. Processing does not use that number. Leave `file_id` out of the process body to process every zip in the project.

### Process

`POST /api/v1/data/process/1`

```json
{ "chunk_size": 100, "overlap_size": 20, "do_reset": 1, "type": "all" }
```

`type` chooses what to process inside each zip: `all`, `chat`, `document`, or `record`. The default is `all`. `chunk_size` and `overlap_size` are character counts for documents and transcripts. `do_reset: 1` deletes previous chunks, child assets, and the vector table before processing again. Optional `file_id` is the stored name of one zip (`asset_name`), not the numeric id returned by upload. A name that is not a zip is rejected. Leave it out to process every zip in the project. The `base` Whisper model is already in the API image, so this call loads it from disk instead of downloading it.

### Index

`POST /api/v1/nlp/index/push/1`

```json
{ "do_reset": 0 }
```

`do_reset: 1` drops and recreates the vector table before inserting.

### Search and answer

Search and answer accept Arabic and English. The reply is written in the same language as the question. `PRIMARY_LANG` chooses the Arabic or English prompt, and `DEFAULT_LANG` is used when that prompt is missing.

`POST /api/v1/nlp/index/search/1` and `POST /api/v1/nlp/index/answer/1`

Arabic:

```json
{ "text": "ما هو اخر تعديل طلبو العميل؟", "limit": 5 }
```

English:

```json
{ "text": "What is the deadline I chose with the client?", "limit": 5 }
```

Search returns `results` with `text` and `score`. Answer returns `answer`, `full_prompt`, and `chat_history`.

## Data model

All tables are in the `minirag` database, schema `public`.

### `projects`

One row per project id you put in the URL.

| Column | Meaning |
|---|---|
| `project_id` | Integer primary key. This is the id in the URL. |
| `project_uuid` | Unique UUID. |
| `created_at`, `updated_at` | Timestamps. |

### `assets`

The uploaded zips, and each file extracted from them.

| Column | Meaning |
|---|---|
| `asset_id` | Integer primary key. |
| `asset_uuid` | Unique UUID. |
| `asset_type` | `zip` for each uploaded archive. `chat`, `document`, or `record` for a file extracted from one of those zips. |
| `asset_name` | Stored path. Each zip is a file name at the project root. Extracted files look like `document/notes.pdf` or `records/voice.opus`. |
| `asset_size` | Size in bytes. |
| `asset_config` | Optional JSON. Unused by the current pipeline. |
| `asset_project_id` | Foreign key to `projects.project_id`. |
| `asset_parent_id` | Null for each uploaded zip. For an extracted file, the `asset_id` of the zip it came from. |
| `created_at`, `updated_at` | Timestamps. |

### `chunks`

Text that can be embedded and searched.

| Column | Meaning |
|---|---|
| `chunk_id` | Integer primary key. |
| `chunk_uuid` | Unique UUID. |
| `chunk_text` | The chunk text. |
| `chunk_metadata` | JSON. Chat chunks are plain text. Document and record chunks can include `sender` and `datetime` taken from the chat. |
| `chunk_order` | Order of the chunk inside that file, starting at 1. |
| `chunk_project_id` | Foreign key to `projects.project_id`. |
| `chunk_asset_id` | Foreign key to `assets.asset_id`. For a zip, this is the child file, not the zip itself. |
| `created_at`, `updated_at` | Timestamps. |

### Vector table

Created by the index endpoint, one table per project. The name is `collection_<embedding size>_<project id>`, for example `collection_3072_1` for Gemini embeddings or `collection_768_1` for a 768-dimension local model.

| Column | Meaning |
|---|---|
| `id` | Bigserial primary key. |
| `text` | Chunk text that was embedded. |
| `vector` | pgvector column. The dimension is `EMBEDDING_MODEL_SIZE`. |
| `metadata` | JSON copied from the chunk. |
| `chunk_id` | Foreign key to `chunks.chunk_id`. |

## Clone and run

Install Docker. From a shell:

```bash
git clone <your-repo-url>
cd mini-rag/docker/env
cp .env.example.app .env.app
cp .env.example.postgres .env.postgres
cp .env.example.grafana .env.grafana
cp .env.example.postgres-exporter .env.postgres-exporter
```

On Windows, run those commands in WSL or Git Bash. If the real env files are already present, do not overwrite them.

Edit `docker/env/.env.app` and set the model provider. Then start the stack:

```bash
cd ..
docker compose up --build -d
```

The API container runs database migrations on startup. After a code change:

```bash
cd docker
docker compose up --build -d fastapi
```

Postgres is published on host port **5433**.

## Ollama for free local models

Ollama speaks the OpenAI HTTP API. This project already has an OpenAI provider, so point that provider at Ollama. Keep `GENERATION_BACKEND` and `EMBEDDING_BACKEND` as `OPENAI`. Gemini is a separate provider and does not use this URL.

On the machine that runs Docker:

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

`llama3.2` answers questions. `nomic-embed-text` builds embeddings and its vector size is 768. If you pick another embedding model, set `EMBEDDING_MODEL_SIZE` to the size reported by `ollama show <model-name>`.

In `docker/env/.env.app`:

```env
GENERATION_BACKEND="OPENAI"
EMBEDDING_BACKEND="OPENAI"

OPENAI_API_KEY="ollama"
OPENAI_API_URL="http://host.docker.internal:11434/v1"

GENERATION_MODEL_ID="llama3.2"
EMBEDDING_MODEL_ID="nomic-embed-text"
EMBEDDING_MODEL_SIZE=768
```

`OPENAI_API_KEY` can be any non-empty string. Ollama does not check it, but an empty key makes the client send an invalid header. `host.docker.internal` is the Docker host. `localhost` inside the API container is the container itself, so it cannot reach Ollama on the host.

Restart the API after saving the file:

```bash
cd docker
docker compose up -d fastapi
```

Then upload, process, and index again. Changing `EMBEDDING_MODEL_SIZE` needs a new index (`do_reset: 1` on the push call) because the vector column width changes.

## Links

| What | URL |
|---|---|
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Nginx in front of the API | http://localhost |
| Grafana | http://localhost:3000 |
| Grafana dashboard import | http://localhost:3000/dashboard/import |
| Prometheus | http://localhost:9090 |
| Postgres from the host | `localhost:5433`, database `minirag` |

## Grafana

1. Open http://localhost:3000 and sign in with GF_SECURITY_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD.
2. Go to **Connections**, then **Data sources**, then **Add data source**, then **Prometheus**.
3. Set the URL to `http://prometheus:9090` and choose **Save & test**. Use that hostname. Grafana runs inside Docker, so `localhost:9090` is the Grafana container, not Prometheus.
4. Open http://localhost:3000/dashboard/import, paste one of the ids below, choose **Load**, select the Prometheus data source, then **Import**.

| Id | What it shows | Catalog page |
|---|---|---|
| `18739` | FastAPI request count and latency | https://grafana.com/grafana/dashboards/18739 |
| `12485` | PostgreSQL | https://grafana.com/grafana/dashboards/12485 |
| `1860` | CPU, memory, and disk from the node exporter | https://grafana.com/grafana/dashboards/1860 |

Prometheus scrapes the API, Postgres, and the host. The API metrics path is `/TrhBVe_m5gg2002_E5VVqS`.

## Planned: Google Cloud Speech-to-Text

Voice notes are transcribed on the server with faster-whisper on the CPU, using compute type `int8`. That stays the local default because it needs no cloud account and no GPU.

The speech backend already has a `GOOGLE` slot for a later provider. When this is deployed, transcription should move to Google Cloud Speech-to-Text. A hosted recognizer handles long audio and production load without keeping a Whisper model in the API container. That provider needs a Google Cloud project with the Speech-to-Text API enabled, a service account JSON file (`GOOGLE_APPLICATION_CREDENTIALS`), and a regional language code such as `ar-EG`. The Gemini API key is not a credential for that API.
