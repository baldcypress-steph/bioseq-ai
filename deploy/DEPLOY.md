# Deploying BioSeq AI on DigitalOcean

BioSeq AI runs as three separate services. The app never loads a model; it calls
whatever OpenAI-compatible URL it is given.

```
                 ┌──────────────────────── Droplet ─────────────────────────┐
 Browser ──────► │ gateway (Caddy, HTTPS)                                   │
                 │   /      ──► app    (BioSeq AI, Streamlit)               │
                 │                       │ BIOSEQ_BASE_URL (private network)│
                 │                       ▼                                  │
 Laptop /        │   /v1/*  ──► model  (Ollama + Qwen3, open weights)       │
 benchmark ────► │   (needs Authorization: Bearer MODEL_API_KEY)            │
                 └──────────────────────────────────────────────────────────┘
```

Because the services are decoupled you can:
- run the model on the droplet and the app on your laptop, or the reverse;
- swap the model for a bigger one or another host by changing two settings;
- point the benchmark at the hosted model.

## Choosing a droplet for $25 of credit

Droplets are billed by the hour, and you stop paying when you **destroy** the droplet
(powering it off still costs money). There is no GPU in this budget, so the model runs on CPU.

| Droplet (Basic, Regular) | Model | Approx. cost | $25 lasts | Speed |
|---|---|---|---|---|
| 4 GB RAM / 2 vCPU | `qwen3:1.7b` (default) | about $24/month | about a month | a few seconds to a minute per step |
| 8 GB RAM / 4 vCPU | `qwen3:4b` | about $48/month | about 2 weeks | slower per token, better tool choices |

Check the current price on the droplet creation page. A sensible plan: deploy the
4 GB droplet for the judging window, and destroy it afterwards.

## Step 1: put the code on GitHub

The droplet clones your public repository. Push the project to GitHub first
(the hackathon requires a public repo anyway).

## Step 2: make an API key

On your Mac:

```bash
openssl rand -hex 32
```

Copy the output. It protects the model API so strangers can't use your droplet's CPU.

## Step 3: create the droplet

1. DigitalOcean → **Create → Droplets**.
2. Region: Toronto (TOR1) or the closest one to the judges.
3. Image: **Ubuntu 24.04 (LTS) x64**.
4. Size: **Basic → Regular → 4 GB / 2 CPUs**.
5. Authentication: SSH key (recommended) or a root password.
6. Open **Advanced options → Add Initialization scripts**. Paste the contents of
   [`cloud-init.yml`](cloud-init.yml), then edit the two lines marked `EDIT`:
   your API key and your GitHub username.
7. Click **Create Droplet** and copy its IP address.

Setup takes about 5–10 minutes: Docker is installed, the app is built, and the model
(about 1.4 GB for qwen3:1.7b) is downloaded.

## Step 4: open the app

Visit `http://YOUR_DROPLET_IP`. The first question is slow while the model loads into memory.

If the page doesn't load, SSH in and check:

```bash
ssh root@YOUR_DROPLET_IP
cd /opt/bioseq-ai
docker compose ps                 # all running? model-init "exited (0)" is normal
docker compose logs model-init    # model download progress
docker compose logs -f app
tail -50 /var/log/cloud-init-output.log   # if /opt/bioseq-ai doesn't exist yet
```

## Step 5 (optional): HTTPS with a domain

Point a domain's **A record** at the droplet IP, then on the droplet:

```bash
cd /opt/bioseq-ai
sed -i 's/^SITE_ADDRESS=.*/SITE_ADDRESS=bioseq.yourdomain.com/' .env
docker compose up -d
```

Caddy gets a certificate automatically.

## Use the hosted model from your laptop

The model API is OpenAI-compatible, so your local app, CLI and benchmark can use it:

```bash
export BIOSEQ_BASE_URL=http://YOUR_DROPLET_IP/v1
export BIOSEQ_API_KEY=your-api-key
export BIOSEQ_MODEL=qwen3:1.7b
bioseq ask examples/sample.fasta "What is the GC content of toy?"
python benchmark/run_benchmark.py --models qwen3:1.7b
```

Quick check that the key works:

```bash
curl -H "Authorization: Bearer your-api-key" http://YOUR_DROPLET_IP/v1/models
```

Without the key the gateway returns `401 Unauthorized`.

## Common changes

| Goal | What to do on the droplet (in `/opt/bioseq-ai`) |
|---|---|
| Update after pushing new code | `git pull && docker compose up -d --build` |
| Use qwen3:4b (8 GB droplet) | set `BIOSEQ_MODEL=qwen3:4b` in `.env`, then `docker compose up -d` |
| Use a model hosted elsewhere | set `BIOSEQ_BASE_URL` and `BIOSEQ_API_KEY` in `.env`; the model services can be removed |
| Run only the model service | `docker compose up -d model model-init gateway` |
| Stop paying | Destroy the droplet in the DigitalOcean dashboard |

## Security notes

- The app is public (anyone with the URL can use it), but visitors can't change the model
  endpoint (`BIOSEQ_LOCK_ENDPOINT=1`), so they can't make your server call other URLs.
- The model API is reachable only with the key; Ollama's own port is never exposed.
- `.env` holds your key and is listed in `.gitignore`; never commit it.
