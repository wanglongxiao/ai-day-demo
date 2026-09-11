# aiday-demo · Lumina · Dreamina Seedance 2.5

Select a gender and upload a front-facing half-body portrait. The app registers
the portrait in the Private Virtual Portrait Library and asynchronously creates
a cinematic Hong Kong video with **Dreamina Seedance 2.5**. Each submitted
browser window gets a unique `task_id`; a QR code lets the user reopen the task
page later and download the finished video.

## Features

- **Video agent pipeline** (background, state persisted to TOS):
  1. Upload the portrait to TOS (public-read).
  2. Create a per-project **asset group** (project ↔ asset-group one-to-one).
  3. Register the portrait as an asset, poll until `Active`.
  4. Generate with `dreamina-seedance-2-5-260628`. The portrait is **Image 1**;
     two fixed visual references are **Image 2** and **Image 3**. All three are
     passed strictly as `asset://<asset-id>`, never as raw image URLs. The full
     prompt is packaged from `docs/prompt_cantonese.txt`, prefixed with
     `人物性别是 - 男性。` or `人物性别是 - 女性。`. Auto-retry up to **3**
     times on failure.
  5. Re-host the signed video into the public bucket and verify readability.
- **Video settings (fixed / selectable):**
  - Audio effects/dialogue **on**, prompt explicitly requires **no BGM**;
    watermark **off**.
  - Aspect ratio: `21:9` / `16:9` / `9:16` — **default `16:9`**.
  - Duration: `10s` / `20s` / `30s` — **default `30s`**.
  - Resolution: `720p` / `480p` — **default `480p`**.
  - Fixed reference image assets (configurable via `.env`):
    - Image 2 → `REFERENCE_IMAGE_ASSET_2`
    - Image 3 → `REFERENCE_IMAGE_ASSET_3`
  - The finished video is re-hosted to public TOS with
    `Content-Disposition: attachment`, so it downloads directly in mobile
    browsers (iOS Safari/Chrome, Android) instead of opening an inline player.
- **Web UI:**
  - Top title: **“Step into the Lead Role with Lumina (Powered by Dreamina
    Seedance 2.5)”**, fully visible within two lines.
  - i18n: 繁體中文 (default) / English.
  - Responsive desktop / mobile layout.
  - On mobile, the two-line title and compact `繁中 / EN` selector share one
    header row; the demo image uses the same horizontal width as the form.
  - Responsive demo image loaded directly from
    `https://2026-ai-day.tos-cn-hongkong.bytepluses.com/assets/demo.jpg`,
    two accessible gender cards, gated image upload + preview, Generate button.
  - After submit: shows a QR code encoding the unique task URL.
  - The task page and backend video-task monitor poll every **60 seconds**.
  - Task page (via QR): shows *generating…*, *ready + download URL*, or
    *expired after 24h*.

## Layout

```
src/aiday_demo/
  config.py         # .env loader + settings
  tos_store.py      # TOS upload/read, public-read, content-type normalization
  asset_library.py  # signed AK/SK OpenAPI (CreateAssetGroup/CreateAsset/GetAsset)
  prompt_cantonese.txt # deployable exact copy of docs/prompt_cantonese.txt
  video_client.py   # SeeDance-2.5 generation (asset:// reference)
  task_manager.py   # task lifecycle + background worker, state on TOS
  server.py         # FastAPI routes + static SPA
app/static/         # index.html, styles.css, i18n.js, app.js
docs/               # API references and source prompt (NOT committed to GitHub)
```

## Prerequisites — BytePlus services to enable

Enable the following in the [BytePlus console](https://console.byteplus.com/) with
one account, then create one IAM user whose AK/SK are used for everything below:

| Service | What to enable / create | Used for |
| --- | --- | --- |
| **IAM** | An IAM user + Access Key (AK/SK). Grant it TOS and ModelArk permissions. | `BYTEPLUS_AK` / `BYTEPLUS_SK` — authenticates TOS and the signed asset-library OpenAPI |
| **TOS** (Object Storage) | A bucket in your region (e.g. `cn-hongkong`) with **public-read** objects allowed. | Stores uploaded portraits, task state (`tasks/<task_id>/`), and the final public video. → `TOS_BUCKET` / `TOS_REGION` / `TOS_ENDPOINT` |
| **ModelArk** | Activate the platform and create **endpoints/inference access** for a chat model, an image model, and the **Dreamina Seedance 2.5** video model. Create an **API key**. | `ARK_API_KEY` + `CHAT_MODEL` / `IMAGE_MODEL` / `VIDEO_MODEL` endpoint ids, called at `LLM_BASE_URL` |
| **Private Virtual Portrait Library** (Asset OpenAPI) | Available through the ModelArk / OpenAPI gateway (`open.byteplusapi.com`); no separate signup, but the IAM AK/SK must be allowed to call `CreateAssetGroup` / `CreateAsset` / `GetAsset`. | Registers portraits as `asset://` references. → `ARK_OPENAPI_HOST` / `ARK_OPENAPI_REGION` / `ARK_ASSET_PROJECT` |
| **veFaaS** + **API Gateway** | Only needed for cloud deployment (see below). | Hosts the app as an elastic multi-instance function behind an HTTPS gateway |

**Register the two fixed reference portraits once**: upload the two reference
images to your asset library (the app's own `asset_library.py` calls, or the
console), then paste the returned asset-ids into `REFERENCE_IMAGE_ASSET_2` /
`REFERENCE_IMAGE_ASSET_3`.

## Configuration

All secrets and deployment-specific values live in `.env` (git-ignored). Copy the
template and fill in your own values:

```bash
cp .env.example .env
# then edit .env with the AK/SK, API key, bucket and model endpoint ids
```

`src/aiday_demo/config.py` loads `.env` at import time (no external dependency)
and never hardcodes a real credential. Keys:

| Key | Purpose |
| --- | --- |
| `BYTEPLUS_AK` / `BYTEPLUS_SK` | TOS + asset-library credentials (raw AK/SK) |
| `TOS_REGION` / `TOS_BUCKET` / `TOS_ENDPOINT` | Object storage |
| `LLM_BASE_URL` / `ARK_API_KEY` | ModelArk endpoint + API key |
| `CHAT_MODEL` / `IMAGE_MODEL` / `VIDEO_MODEL` | ModelArk endpoint ids (video = Dreamina Seedance 2.5) |
| `ARK_OPENAPI_HOST` / `ARK_OPENAPI_REGION` / `ARK_ASSET_PROJECT` | Asset library OpenAPI |
| `REFERENCE_IMAGE_ASSET_2` / `REFERENCE_IMAGE_ASSET_3` | Fixed Seedance reference image asset-ids |
| `HOST` / `PORT` | Server bind |
| `ACCESS_PASSWORD` | Optional cloud-only access gate (blank = disabled) |

> **Never commit `.env`.** It is git-ignored along with `docs/`, logs and
> `__pycache__`. On the cloud, the same keys are passed as veFaaS function
> **Envs**, so no secret ever ships in the code zip or the repo.

## Run locally

```bash
uv sync

# One-shot: (re)start the server and stream logs (tail -f server.log)
./run_local.sh            # restart + follow log
./run_local.sh logs       # just follow server.log
./run_local.sh stop       # stop the server
# → http://127.0.0.1:8000/
```

`run_local.sh` runs uvicorn in the background (pid in `.server.pid`), writes to
`server.log` (git-ignored), and then follows it like `tail -f server.log`.
Ctrl-C stops the log stream; the server keeps running (use `stop` to kill it).

Run the local unit tests without calling cloud APIs:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Or run it in the foreground directly:

```bash
.venv/bin/python -m aiday_demo
# → http://127.0.0.1:8000/
```

## Cloud deployment (Byteplus veFaaS + API Gateway)

Region `ap-southeast-1`. All secrets are passed as function **Envs** (never in the
code zip or repo). Deployment artifacts:

- [run.sh](run.sh) — native-python runtime entrypoint (uvicorn on port 8000,
  `PYTHONPATH=src`, single worker; scaling is by instances, state lives in TOS).
- [requirements.txt](requirements.txt) — deps installed by veFaaS
  `CreateDependencyInstallTask` (includes the arkruntime SDK's vendored
  transitive deps: `sniffio`, `anyio`, `httpx`, `distro`, …).

Deploy flow with the `bp` CLI (profile `aiday`):

```bash
# 1. configure credentials
bp configure set --profile aiday --region ap-southeast-1 \
  --access-key <AK> --secret-key <SK>

# 2. package (exclude .env/docs/.venv)
zip -r deploy.zip run.sh requirements.txt src app \
  -x "*/__pycache__/*" -x "*.pyc"

# 3. create function (secrets via --Envs), commit code (base64 inline zip)
bp vefaas CreateFunction ---profile aiday ---region ap-southeast-1 --body @create_fn.json
bp vefaas UpdateFunction ---profile aiday ---region ap-southeast-1 \
  --Id <fnId> --SourceType zip --Source "$(base64 < deploy.zip | tr -d '\n')"

# 4. install deps, then release  (RE-RUN deps install after every code update!)
bp vefaas CreateDependencyInstallTask ---profile aiday ---region ap-southeast-1 --FunctionId <fnId>
bp vefaas UpdateFunctionResource ---profile aiday ---region ap-southeast-1 \
  --FunctionId <fnId> --MinInstance 15 --MaxInstance 25
bp vefaas Release ---profile aiday ---region ap-southeast-1 --FunctionId <fnId> \
  --MaxInstance 25 --RollingStep 100 --TargetTrafficWeight 100

# 5. bind API gateway: service -> veFaas upstream -> route (path "/" all methods)
bp apig CreateGatewayService ---profile aiday ---region ap-southeast-1 --body @svc.json
bp apig CreateUpstream ---profile aiday ---region ap-southeast-1 --body @upstream.json   # SourceType=VeFaas
bp apig20221112 CreateRoute ---profile aiday ---region ap-southeast-1 --body @route.json
```

After `CreateRoute` the gateway prints the public HTTPS domain — that is the
final Web UI URL. The concrete function / gateway / route ids are
deployment-specific (kept out of this repo); read them back from
`bp vefaas GetFunction` and `bp apig` list commands for your own account.

### Multi-instance safety (elastic + idle-recycle)

veFaaS runs many stateless instances and recycles idle ones. The app is built
for that:

1. **Non-blocking endpoints** — submit/poll return immediately; generation runs
   off-request in a bounded per-instance thread pool.
2. **State in TOS** — every task's state is `tasks/<task_id>/state.json`; any
   instance can serve any task. Windows never collide (unique task_id paths).
3. **Stable task_id reconnect + self-heal** — a short TOS lease (owner +
   expiry), acquired through an ETag conditional write, ensures only one
   instance drives a task at a time. If
   the owning instance is recycled, the lease lapses and the next poll on *any*
   instance transparently resumes the task (asset/ark ids are persisted and each
   step is idempotent). Stale/late workers are ignored — no cross-task races, no
   gateway lock-ups.

## Key endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/task` | Create a task, returns `task_id` |
| `POST` | `/api/task/{id}/generate` | Submit portrait + required gender; optional ratio/duration/resolution |
| `GET` | `/api/task/{id}` | Poll task status / video URL |
| `GET` | `/api/qrcode?url=…` | PNG data-URI QR code |
| `GET` | `/health` | Health check |
