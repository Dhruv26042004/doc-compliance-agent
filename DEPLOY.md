# Deploying for free

| Part | Free host | Free-tier limits that matter |
|---|---|---|
| Database | [Neon](https://neon.com) Postgres | 0.5 GB storage, 100 compute-hours a month, sleeps after 5 idle minutes |
| API | [Render](https://render.com) web service (Docker) | 512 MB RAM, sleeps after 15 idle minutes (about a minute to wake up), disk wiped on restart |
| Frontend | [Vercel](https://vercel.com) Hobby | Personal, non-commercial use |
| LLM | [Google AI Studio](https://aistudio.google.com) Gemini API | Daily request caps per model (Flash-Lite is generous; Flash allowed only 20 a day when tested) |
| CI | GitHub Actions | Free for public repositories |

Limits change: check each provider's pricing page before relying on them. No step below needs a paid plan.

## How the app fits a 512 MB host

The API image runs a **lite profile** on Render, set in [`render.yaml`](render.yaml):

- **Files are stored in Postgres** (`FILE_STORAGE=database`), because the free disk is wiped on every restart.
- **Retrieved examples are off** (`PIPELINE_FEWSHOT=false`). The embedding model needs about 200 MB more than the free plan has. In Phase 4 it made no significant difference on the held-out test set, so the prefilter, verifier, and routing are unchanged.
- **Word files are read as text** (`DOCX_CONVERT=false`, no LibreOffice in the image). PDFs keep full highlighting.

Measured under a hard 512 MB cap, the largest demo contract (28 pages, 141 clauses) peaked at **442 MB**. Locally, `docker compose` builds the full profile with LibreOffice and examples.

## Steps

### 1. Push the repository to GitHub

The repository must be public for free GitHub Actions minutes, and Render and Vercel deploy from it.

### 2. Create the database (Neon)

1. Sign up at neon.com and create a project.
2. Copy the connection string (`postgresql://...?sslmode=require`). The app adds the right driver prefix itself, and migrations run automatically when the API starts.

### 3. Deploy the API (Render)

1. In the Render dashboard: **New → Blueprint**, and pick your repository. Render reads `render.yaml`.
2. Fill in the secrets it asks for:
   - `DATABASE_URL`: the Neon connection string.
   - `GEMINI_API_KEY`: your key. Use a **new** key, not one that has been pasted anywhere.
   - `CORS_ORIGINS`: `["http://localhost:3000"]` for now; you will add the Vercel URL in step 5.
3. Add one more environment variable, **`ADMIN_TOKEN`**, set to a long random string. With it set, uploading, analyzing, batching, and deleting need the token, so strangers cannot spend your Gemini quota or delete the demo. Viewing and reviewing stay open.
4. Deploy. The first build takes about 10 minutes. Check `https://<your-service>.onrender.com/health` returns `"status":"ok"`.

### 4. Deploy the frontend (Vercel)

1. Import the repository in Vercel and set **Root Directory** to `frontend`.
2. Add the environment variable `NEXT_PUBLIC_API_URL` = `https://<your-service>.onrender.com`.
3. Deploy.

### 5. Connect them

In Render, set `CORS_ORIGINS` to `["https://<your-app>.vercel.app"]` and save; the service restarts. Preview deployments (`*.vercel.app`) are already allowed by `CORS_ORIGIN_REGEX`.

### 6. Load the demo data

From your machine (it reads CUAD locally and sends the contracts to the deployed API):

```bash
cd backend
uv sync
uv run python -m scripts.download_cuad --pdfs
uv run python -m scripts.seed_demo --api https://<your-service>.onrender.com --token <your ADMIN_TOKEN> --reset
```

This analyzes seven contracts on your Gemini key and takes a few minutes. Re-run it any time to restore the demo.

## After deploying

- **First visit after idle time is slow.** Render and Neon both sleep; the page shows a message and works after about a minute.
- **The audit log keeps everything.** `GET /audit/verify` should report `"valid": true`.
- **Visitors can review decisions.** That is the point of the demo; re-seed with `--reset` to restore the original state.
- **Alternative host for the full profile:** any container host with about 1 GB of RAM can run the image built with `docker build -f backend/Dockerfile --build-arg WITH_LIBREOFFICE=true .` and `PIPELINE_FEWSHOT=true`. Hugging Face Spaces' CPU tier has 16 GB, but whether it is still free for personal accounts was unclear when this was written.
