# FSD RAG — end-to-end commands (OCI)

Run these in order on `poc1-mm-madan2` as user `mobiquity`.  
Use `/mmoneyhome` (big disk). Do **not** fill `/` (30 GB root).

```text
.docx  --Model X-->  .md  --ingest-->  index  --Model Y + brief-->  new FSD.md
                         SQLite app.db tracks every file + status (incl. unlearn)
```


|             | Folder                                       | Format                  |
| ----------- | -------------------------------------------- | ----------------------- |
| **X in**    | `/mmoneyhome/mobiquity/fsd-data/fsds/FSD/`   | `.docx` (copy, not git) |
| **X out**   | `/mmoneyhome/mobiquity/fsd-data/normalized/` | `.md`                   |
| **Y in**    | `normalized/` via `index/` + your brief      | `.md` / text            |
| **Y out**   | `/mmoneyhome/mobiquity/fsd-data/output/`     | `.md` draft             |
| **Tracker** | `/mmoneyhome/mobiquity/fsd-data/app.db`      | SQLite (not git)        |


Code (git): `/mmoneyhome/mobiquity/fsd-model/`  
Data (not git): `/mmoneyhome/mobiquity/fsd-data/`

Statuses: `pending | running | done | failed | skipped | indexed | draft | approved | rejected | unlearned`

Stage switches in `config.properties` (you still run scripts manually):

```properties
normalize.enabled=N
ingest.enabled=Y
```

`N` → that script prints and exits (no Ollama). Generate is not gated by these flags.

**Current default:** skip Model X — `ingest.dir` points at raw `fsds/FSD` so ingest indexes `.docx` directly. To use X again later: `normalize.enabled=Y` and `ingest.dir=.../normalized`.

SQLite keys each file by **full absolute path**, not the short filename. Empty `app.db` = first run; every file on disk is NEW (insert row → process). Same name in two folders = two rows. Same path already `done` = skip (`--force` to redo). Ingest does **not** require a `normalize_jobs` row.

---

## 1) Disk check

```bash
df -h /
df -h /mmoneyhome
pwd
```

**Why:** confirm you are on `/mmoneyhome/mobiquity`, not the small root volume.

---

## 2) System packages

If `dnf` fails with `docker-ce-stable` 404, disable that repo first:

```bash
sudo dnf config-manager --disable docker-ce-stable 2>/dev/null || \
  sudo mv /etc/yum.repos.d/docker-ce.repo /etc/yum.repos.d/docker-ce.repo.disabled
sudo dnf clean all
```

Then:

```bash
sudo dnf install -y python3 python3-pip python3-devel python3-virtualenv git gcc gcc-c++ make curl tar sqlite
python3 --version
```

**Why:** Python + git + compiler for the venv packages. `sqlite` is only for optional peek commands.

---

## 3) Install Ollama + models

```bash
curl -fsSL https://ollama.com/install.sh | sh
mkdir -p /mmoneyhome/mobiquity/.ollama/models
echo 'export OLLAMA_MODELS=/mmoneyhome/mobiquity/.ollama/models' >> ~/.bashrc
source ~/.bashrc

ollama pull qwen2.5:1.5b          # Model Y — writes new FSD
ollama pull qwen2.5:7b            # Model X — streamlines 117 docs (slow)
ollama pull nomic-embed-text      # search embeddings
ollama list

curl http://127.0.0.1:11434
ollama run qwen2.5:1.5b "Say hello in one sentence"
```

**Why:** Ollama binary can live in `/usr` (small). Models must stay on `/mmoneyhome`.  
CPU-only warning is OK. If 7B is too slow later, set `normalize.model=qwen2.5:3b` in `config.properties`.

---

## 4) Git clone code (not the DOCX)

On the server:

```bash
export FSD_HOME=/mmoneyhome/mobiquity/fsd-model
export FSD_DATA=/mmoneyhome/mobiquity/fsd-data
mkdir -p "$FSD_DATA"/{fsds/FSD,normalized,index,output}

cd /mmoneyhome/mobiquity
git clone https://github.com/madanamgoth/FSD-MODEL.git fsd-model
cd fsd-model
cp config.properties.example config.properties
# edit flags if needed: normalize.enabled=Y   ingest.enabled=Y
```

**Why:** GitHub = scripts only. See [WHAT_IN_GIT.md](WHAT_IN_GIT.md).  
`config.properties.example` points at `/mmoneyhome/mobiquity/fsd-data/...` including `app.db`.

Later code update:

```bash
cd /mmoneyhome/mobiquity/fsd-model && git pull origin master
```

This does **not** delete `fsd-data`.

---

## 5) Copy 117 DOCX from Windows (once)

From your laptop (PowerShell):

```powershell
scp -r "C:\FSD MODEL\data\fsds\FSD\FSD-BASE" `
    "C:\FSD MODEL\data\fsds\FSD\FSD-WORD-DOCUMENT" `
    mobiquity@poc1-mm-madan2:/mmoneyhome/mobiquity/fsd-data/fsds/FSD/
```

On server, check:

```bash
ls /mmoneyhome/mobiquity/fsd-data/fsds/FSD
# expect: FSD-BASE   FSD-WORD-DOCUMENT
```

**Why:** Word files stay outside git. Only X reads `.docx`.

---

## 6) Python venv

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Why:** install Chroma, httpx, python-docx, pypdf into `.venv` on the big disk.  
Oracle Linux sqlite is often < 3.35 (Chroma needs ≥ 3.35). `requirements.txt` includes `pysqlite3-binary` on Linux so ingest works.

If ingest already failed with `unsupported version of sqlite3`:

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh
git pull origin master
pip install "pysqlite3-binary>=0.5.0"
python -c "import sys; sys.path.insert(0,'src'); import sqlite_compat; import sqlite3; print(sqlite3.sqlite_version)"
```

Expect a version ≥ 3.35, then rerun ingest.

---

## 7) Model X — streamline all FSDs (slow)

Set `normalize.enabled=Y` in `config.properties` (set `N` to disable this script).

`-u` / `PYTHONUNBUFFERED=1` so log lines appear immediately (not after the buffer fills).  
`nohup` + `&` keeps running after you close SSH.

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh
export PYTHONUNBUFFERED=1

# test 1 file first (empty DB → file is NEW → insert + run)
nohup python -u src/normalize.py --limit 1 > /mmoneyhome/mobiquity/fsd-data/normalize.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/normalize.log
# Ctrl+C stops tail only, not the job

python src/status.py

# all ~117 docs (often 12–36 hours on CPU)
# stop anytime; rerun skips status=done, skips status=unlearned
nohup python -u src/normalize.py > /mmoneyhome/mobiquity/fsd-data/normalize.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/normalize.log

python src/status.py
python src/status.py --failed
```

Still running?

```bash
ps aux | grep '[n]ormalize.py'
```

Retry only failed rows:

```bash
python src/normalize.py --retry-failed
```

Force one file again (background; quote paths with spaces):

```bash
nohup python -u src/normalize.py --file "/mmoneyhome/mobiquity/fsd-data/fsds/FSD/FSD-WORD-DOCUMENT/Comviva_mobiquity_Setaragan Integration_FSD_EAP-19675_V1.1 (signed off).docx" \
  > /mmoneyhome/mobiquity/fsd-data/normalize.log 2>&1 &
echo $!

nohup python -u src/normalize.py --force --file /mmoneyhome/mobiquity/fsd-data/fsds/FSD/FSD-BASE/foo.docx \
  > /mmoneyhome/mobiquity/fsd-data/normalize.log 2>&1 &
```

**Why:** X (`qwen2.5:7b`) rewrites messy Word into one Markdown template under `fsd-data/normalized/`.  
Every source + output filename + windows + error is stored in `app.db`.  
Y cannot use raw `.docx` well until this finishes.

---

## 8) Ingest — build search index

Set `ingest.enabled=Y` in `config.properties`.

### Skip Model X (current strategy) — index `.docx` directly

Normalize code stays in the repo; turn it off and point ingest at the raw library:

```properties
normalize.enabled=N
ingest.dir=/mmoneyhome/mobiquity/fsd-data/fsds/FSD
```

Ingest checks **SQLite `ingest_jobs` only** (full path). No `normalize_jobs` row required. No row = NEW → index. `done` = skip.

**Time (~117 `.docx`, 4 vCPU):** often **30–90 minutes** (extract + embed). Do **not** run ingest while normalize/generate is using Ollama.

One file (same pattern as normalize `--file`; quote paths with spaces):

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh

nohup python -u src/ingest.py --file "/mmoneyhome/mobiquity/fsd-data/fsds/FSD/FSD-WORD-DOCUMENT/Comviva_mobiquity_Setaragan Integration_FSD_EAP-19675_V1.1 (signed off).docx" \
  > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/ingest.log
# Ctrl+C stops tail only, not the job
```

All pending under `ingest.dir`:

```bash
nohup python -u src/ingest.py > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/ingest.log
```

Wipe old Chroma (e.g. previous normalized `.md` chunks) and re-index everything from `ingest.dir`:

```bash
nohup python -u src/ingest.py --rebuild > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
echo $!
```

Retry / force one file:

```bash
python src/ingest.py --retry-failed
nohup python -u src/ingest.py --force --file "/path/to/one.docx" \
  > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
```

Still running?

```bash
ps aux | grep '[i]ngest.py'
python src/status.py
```

### After Model X again

```properties
normalize.enabled=Y
ingest.dir=/mmoneyhome/mobiquity/fsd-data/normalized
```

Then run normalize, then ingest as before (indexes `.md`).

**Why:** turns files under `ingest.dir` into vectors in `fsd-data/index/`. Same filename in different folders = two rows (full path is the key).

---

## 9) Model Y — generate one new FSD

Do **not** run generate while normalize/ingest is still using Ollama.

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh
ps aux | grep -E '[n]ormalize.py|[i]ngest.py|[g]enerate.py'
python src/status.py
```

Foreground (short test):

```bash
python src/generate.py --brief-file data/sample_brief_sms.txt --out sms_otp_test.md
python src/generate.py --brief "Feature: SMS OTP. Actors: App, Auth, Notification API, SMS Gateway. OTP 6 digits, 5 min." --out quick_test.md
```

Background (survives closing SSH; 7B ≈ 10–30 min, 1.5B ≈ 2–10 min):

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh

nohup python -u src/generate.py \
  --brief-file data/sample_brief_sms.txt \
  --out sms_otp_test.md \
  > /mmoneyhome/mobiquity/fsd-data/generate.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/generate.log
# Ctrl+C stops tail only, not the job
```

Your own brief file (iteration 2 — use a **new** `--out` name):

```bash
# write /mmoneyhome/mobiquity/fsd-data/brief_sms_otp_v2.txt  (richer facts)
nohup python -u src/generate.py \
  --brief-file /mmoneyhome/mobiquity/fsd-data/brief_sms_otp_v2.txt \
  --out sms_otp_test_v2.md \
  > /mmoneyhome/mobiquity/fsd-data/generate.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/generate.log
```

```bash
ls -la /mmoneyhome/mobiquity/fsd-data/output/
python src/status.py --generated
```

Log should show `Chunks in index: …` and retrieved sources (after approve, look for `fsd_sms_otp.md`).

**Why:** Y (`ollama.model`, often `qwen2.5:7b`) searches Chroma and writes a draft. SQLite `generate_jobs` + `documents` get `status=draft`, `available_to_x=0`, `available_to_y=0` until you approve.

---

## 10) Make a good draft available to X and Y (approve)

Foreground:

```bash
python src/approve.py \
  --file /mmoneyhome/mobiquity/fsd-data/output/sms_otp_test.md \
  --name fsd_sms_otp.md \
  --notes "good SMS pattern"
python src/status.py --generated
```

Background (re-embeds into Chroma; a few minutes):

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh
ps aux | grep -E '[n]ormalize.py|[i]ngest.py|[g]enerate.py|[a]pprove.py'

nohup python -u src/approve.py \
  --file /mmoneyhome/mobiquity/fsd-data/output/sms_otp_test.md \
  --name fsd_sms_otp.md \
  --notes "good SMS pattern" \
  > /mmoneyhome/mobiquity/fsd-data/approve.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/approve.log
```

Done when you see `Indexed … chunk(s)` and `available_to_x=1 available_to_y=1`.  
Example: 749 chunks + 16 approved = **765**.

```bash
ls /mmoneyhome/mobiquity/fsd-data/normalized/APPROVED/
python src/status.py --generated
```

Iteration 2 (new name, do not overwrite unless you intend to):

```bash
nohup python -u src/approve.py \
  --file /mmoneyhome/mobiquity/fsd-data/output/sms_otp_test_v2.md \
  --name fsd_sms_otp_v2.md \
  --notes "richer brief iteration 2" \
  > /mmoneyhome/mobiquity/fsd-data/approve.log 2>&1 &
```

**Why:** copies the draft into `normalized/APPROVED`, sets `available_to_x=1 available_to_y=1`, re-indexes. Next generate can retrieve it.

Bad draft (do **not** feed to X/Y):

```bash
python src/approve.py \
  --file /mmoneyhome/mobiquity/fsd-data/output/sms_otp_test.md \
  --reject --notes "wrong actors"
```

---

## 11) Unlearn (status → unlearned)

Stop using a file for X and Y (SQLite + Chroma):

```bash
python src/unlearn.py --file /mmoneyhome/mobiquity/fsd-data/normalized/FSD-BASE/foo.md --notes "outdated"
# same effect:
python src/ingest.py --delete /mmoneyhome/mobiquity/fsd-data/normalized/FSD-BASE/foo.md
python src/status.py
```

Background:

```bash
nohup python -u src/unlearn.py \
  --file /mmoneyhome/mobiquity/fsd-data/normalized/APPROVED/fsd_sms_otp.md \
  --notes "outdated" \
  > /mmoneyhome/mobiquity/fsd-data/unlearn.log 2>&1 &
echo $!
```

**Why:** `status=unlearned`, `available_to_x=0`, `available_to_y=0`, vectors removed.  
`normalize.py` / `ingest.py` skip that file unless you `--force`.

---

## Daily (after first setup)

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh
ps aux | grep -E '[n]ormalize.py|[i]ngest.py|[g]enerate.py'

nohup python -u src/generate.py --brief-file /mmoneyhome/mobiquity/fsd-data/my_brief.txt --out new_fsd.md \
  > /mmoneyhome/mobiquity/fsd-data/generate.log 2>&1 &
echo $!
tail -f /mmoneyhome/mobiquity/fsd-data/generate.log

python src/status.py --generated
# if good:
nohup python -u src/approve.py --file /mmoneyhome/mobiquity/fsd-data/output/new_fsd.md --name fsd_new.md \
  --notes "approved" > /mmoneyhome/mobiquity/fsd-data/approve.log 2>&1 &
```

---

## Background cheat sheet (`nohup`)

`source scripts/env.sh` once per SSH login. `-u` = live log. `Ctrl+C` on `tail` does **not** stop the job. Run **only one** of X / ingest / Y / approve at a time (shared Ollama).

```bash
source /mmoneyhome/mobiquity/fsd-model/scripts/env.sh

# X — one file / all / named file
nohup python -u src/normalize.py --limit 1 > /mmoneyhome/mobiquity/fsd-data/normalize.log 2>&1 &
nohup python -u src/normalize.py > /mmoneyhome/mobiquity/fsd-data/normalize.log 2>&1 &
nohup python -u src/normalize.py --file "/path/to/file.docx" > /mmoneyhome/mobiquity/fsd-data/normalize.log 2>&1 &
echo $!; tail -f /mmoneyhome/mobiquity/fsd-data/normalize.log

# ingest (with normalize.enabled=N + ingest.dir=.../fsds/FSD → indexes .docx)
nohup python -u src/ingest.py --file "/mmoneyhome/mobiquity/fsd-data/fsds/FSD/FSD-WORD-DOCUMENT/Comviva_mobiquity_Setaragan Integration_FSD_EAP-19675_V1.1 (signed off).docx" \
  > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
nohup python -u src/ingest.py > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
nohup python -u src/ingest.py --rebuild > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
echo $!; tail -f /mmoneyhome/mobiquity/fsd-data/ingest.log

# Y
nohup python -u src/generate.py --brief-file data/sample_brief_sms.txt --out sms_otp_test.md \
  > /mmoneyhome/mobiquity/fsd-data/generate.log 2>&1 &
echo $!; tail -f /mmoneyhome/mobiquity/fsd-data/generate.log

# approve (index + available_to_x/y=1)
nohup python -u src/approve.py --file /mmoneyhome/mobiquity/fsd-data/output/sms_otp_test.md \
  --name fsd_sms_otp.md --notes "good SMS pattern" \
  > /mmoneyhome/mobiquity/fsd-data/approve.log 2>&1 &
echo $!; tail -f /mmoneyhome/mobiquity/fsd-data/approve.log

# still running?
ps aux | grep -E '[n]ormalize.py|[i]ngest.py|[g]enerate.py|[a]pprove.py'
```

Only re-run X/ingest when you add a new DOCX (new path = new DB row) or `--force` an overwrite:

```bash
python src/normalize.py              # new paths only (skips done + unlearned)
python src/normalize.py --retry-failed
python src/ingest.py                 # new .md only (skips already indexed)
python src/ingest.py --retry-failed
# or background: nohup python -u src/ingest.py > /mmoneyhome/mobiquity/fsd-data/ingest.log 2>&1 &
python src/ingest.py --rebuild       # optional full Chroma refresh
python src/status.py
```

Optional peek:

```bash
sqlite3 /mmoneyhome/mobiquity/fsd-data/app.db ".tables"
sqlite3 /mmoneyhome/mobiquity/fsd-data/app.db "SELECT id, kind, filename, status, available_to_x, available_to_y FROM documents ORDER BY id DESC LIMIT 20;"
sqlite3 /mmoneyhome/mobiquity/fsd-data/app.db "SELECT id, output_name, status, available_to_x, available_to_y FROM generate_jobs ORDER BY id DESC LIMIT 10;"
```

