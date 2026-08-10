# FSD RAG Generator

Two-step local pipeline:

1. **Model X** (`qwen2.5:7b`) streamlines messy Word FSDs → canonical Markdown  
2. **Ingest** those `.md` files into Chroma  
3. **Model Y** (`qwen2.5:1.5b`) writes a new FSD from your brief + retrieved examples  

Settings live in **`config.properties`**. Turn stages on/off with `normalize.enabled=Y/N` and `ingest.enabled=Y/N` (scripts still run manually; `N` = exit). GitHub = **code only**. Real `.docx` stay on disk.

SQLite keys files by **full path** (not short name). First run / empty DB = every file is NEW. Same name in two folders = two rows. Already `done` = skip.

| | Path |
|--|--|
| Git clone (OCI) | `/mmoneyhome/mobiquity/fsd-model` |
| Data (OCI, not git) | `/mmoneyhome/mobiquity/fsd-data` |
| What to commit | [docs/WHAT_IN_GIT.md](docs/WHAT_IN_GIT.md) |
| Full install | [docs/SETUP_OCI.md](docs/SETUP_OCI.md) |

```text
.docx (fsds) --X--> .md (normalized) --ingest--> index --Y+brief--> draft.md (output)
```

---

## Scripts

| Script | Role |
|--------|------|
| `src/normalize.py` | Model X: `fsd.dir` → `normalized.dir` (skip done; `normalize.enabled=N` exits) |
| `src/ingest.py` | Index `ingest.dir` (skip done; `--retry-failed` / `--force` / `--rebuild`; `ingest.enabled=N` exits) |
| `src/generate.py` | Model Y: brief → `output.dir` (filename stored in SQLite as draft) |
| `src/approve.py` | Mark draft good → `available_to_x/y=1` + `normalized/APPROVED` + re-index |
| `src/unlearn.py` | Set `status=unlearned`, drop from X/Y + Chroma |
| `src/status.py` | Print SQLite counts (`--failed`, `--generated`) |
| `src/db.py` | SQLite schema (`app.db`) |

---

## Windows (dev)

```powershell
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

cd "c:\FSD MODEL"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python src/normalize.py --limit 1
python src/status.py
python src/normalize.py
python src/normalize.py --retry-failed
python src/ingest.py
python src/ingest.py --retry-failed
python src/ingest.py --rebuild
python src/generate.py --brief-file data/sample_brief_sms.txt --out sms_otp_fsd.md
python src/status.py --generated
python src/approve.py --file data/output/sms_otp_fsd.md --name fsd_sms_otp.md
```

---

## OCI

```bash
cd /mmoneyhome/mobiquity
git clone https://github.com/madanamgoth/FSD-MODEL.git fsd-model
cd fsd-model
cp config.properties.example config.properties
# scp DOCX → /mmoneyhome/mobiquity/fsd-data/fsds/FSD/

source scripts/env.sh
pip install -r requirements.txt
python src/normalize.py --limit 1
python src/status.py
python src/normalize.py
python src/ingest.py
python src/ingest.py --rebuild
python src/generate.py --brief-file data/sample_brief_sms.txt --out sms_otp_fsd.md
python src/status.py --generated
```

Later: `git pull origin master` updates code only; `fsd-data` is untouched.
