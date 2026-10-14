import os
import sys
import json
import shutil
import glob
import re
import threading
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, make_response
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 * 1024  # 50GB max
app.secret_key = 'kaggle-shorts-studio-secret-key'

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
GLOBAL_UPLOADS = UPLOADS_DIR / "global"
SLOTS_UPLOADS = UPLOADS_DIR / "slots"
STAGING_DIR = BASE_DIR / "staging"
OUTPUT_DIR = BASE_DIR / "output"
NOTEBOOK_DIR = BASE_DIR / "notebook"

for p in [GLOBAL_UPLOADS, SLOTS_UPLOADS, STAGING_DIR / "dataset", STAGING_DIR / "kernel", OUTPUT_DIR]:
    p.mkdir(parents=True, exist_ok=True)

app_state = {
    "status": "idle",       # idle, syncing, pushing, running, complete, error
    "message": "Ready to upload shorts and process.",
    "progress": 0,
    "last_kernel_status": None,
    "logs": [],
    "output_file": None,
}

# Auto-detect existing output zip
for cand_zip in ["all_final_videos.zip", "all_final_shorts.zip"]:
    if (OUTPUT_DIR / cand_zip).exists():
        app_state["status"] = "complete"
        app_state["progress"] = 100
        app_state["message"] = f"Batch processing complete! {cand_zip} is ready."
        app_state["output_file"] = cand_zip
        sz = (OUTPUT_DIR / cand_zip).stat().st_size / (1024 * 1024)
        app_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] Output archive ready: {cand_zip} ({sz:.2f} MB)")
        break

def log(msg):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    print(entry)
    app_state["logs"].append(entry)
    if len(app_state["logs"]) > 250:
        app_state["logs"].pop(0)

DEFAULT_KAGGLE_USERNAME = "rathinnew"
DEFAULT_KAGGLE_KEY = "KGAT_10cab40726cd143c3e7d52696187fb7a"

def load_stored_credentials():
    kaggle_dir = Path.home() / ".kaggle"
    kaggle_json = kaggle_dir / "kaggle.json"

    u = None
    k = None

    if kaggle_json.exists():
        try:
            with open(kaggle_json) as f:
                data = json.load(f)
            u = data.get("username", "").strip()
            k = data.get("key", "").strip()
        except Exception:
            pass

    if not u or not k:
        u = DEFAULT_KAGGLE_USERNAME
        k = DEFAULT_KAGGLE_KEY
        try:
            kaggle_dir.mkdir(parents=True, exist_ok=True)
            with open(kaggle_json, "w") as f:
                json.dump({"username": u, "key": k}, f)
            os.chmod(kaggle_json, 0o600)
        except Exception:
            pass

    os.environ["KAGGLE_USERNAME"] = u
    os.environ["KAGGLE_KEY"] = k
    os.environ["KAGGLE_API_TOKEN"] = k
    return {"configured": True, "username": u, "key": k, "is_default": (u == DEFAULT_KAGGLE_USERNAME)}

def get_request_credentials(req=None):
    if req is None:
        from flask import request as req

    # 1. Check JSON body
    if req and req.is_json:
        data = req.get_json(silent=True) or {}
        u = data.get("kaggle_username") or data.get("username")
        k = data.get("kaggle_key") or data.get("key")
        if u and k:
            return str(u).strip(), str(k).strip()

    # 2. Check Custom Headers
    if req and req.headers:
        u = req.headers.get("X-Kaggle-Username")
        k = req.headers.get("X-Kaggle-Key")
        if u and k:
            return str(u).strip(), str(k).strip()

    # 3. Check Cookies
    if req and req.cookies:
        u = req.cookies.get("kaggle_username")
        k = req.cookies.get("kaggle_key")
        if u and k:
            return str(u).strip(), str(k).strip()

    return None, None

def get_kaggle_api(username=None, key=None):
    from kaggle.api.kaggle_api_extended import KaggleApi
    if not username or not key:
        username, key = get_request_credentials()

    if not username or not key:
        stored = load_stored_credentials()
        username = stored.get("username", DEFAULT_KAGGLE_USERNAME)
        key = stored.get("key", DEFAULT_KAGGLE_KEY)

    os.environ["KAGGLE_USERNAME"] = username
    os.environ["KAGGLE_KEY"] = key
    os.environ["KAGGLE_API_TOKEN"] = key

    api = KaggleApi()
    api.authenticate()
    return api

# ==========================================
# Routes: Page & Credentials
# ==========================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/reset_credentials", methods=["POST"])
def reset_credentials():
    kaggle_dir = Path.home() / ".kaggle"
    kaggle_dir.mkdir(parents=True, exist_ok=True)
    kaggle_json = kaggle_dir / "kaggle.json"
    try:
        with open(kaggle_json, "w") as f:
            json.dump({"username": DEFAULT_KAGGLE_USERNAME, "key": DEFAULT_KAGGLE_KEY}, f)
        os.chmod(kaggle_json, 0o600)
    except Exception:
        pass
    os.environ["KAGGLE_USERNAME"] = DEFAULT_KAGGLE_USERNAME
    os.environ["KAGGLE_KEY"] = DEFAULT_KAGGLE_KEY
    os.environ["KAGGLE_API_TOKEN"] = DEFAULT_KAGGLE_KEY
    log(f"Reset Kaggle credentials to default: @{DEFAULT_KAGGLE_USERNAME}")

    resp = make_response(jsonify({"success": True, "username": DEFAULT_KAGGLE_USERNAME, "key": DEFAULT_KAGGLE_KEY}))
    resp.set_cookie("kaggle_username", DEFAULT_KAGGLE_USERNAME, max_age=31536000, samesite="Lax", path="/")
    resp.set_cookie("kaggle_key", DEFAULT_KAGGLE_KEY, max_age=31536000, samesite="Lax", path="/")
    return resp

@app.route("/api/credentials", methods=["GET", "POST"])
def credentials():
    if request.method == "GET":
        u, k = get_request_credentials()
        if u and k:
            preview = f"••••••••{k[-4:]}" if len(k) >= 8 else "••••••••"
            return jsonify({
                "configured": True,
                "username": u,
                "key_preview": preview,
                "is_default": (u == DEFAULT_KAGGLE_USERNAME)
            })
        return jsonify({
            "configured": False,
            "username": None,
            "key_preview": None,
            "is_default": False
        })

    data = request.get_json() or {}
    username = data.get("username", "").strip()
    key = data.get("key", "").strip()

    if not username or not key:
        return jsonify({"success": False, "error": "Both Username and API Key are required."}), 400

    try:
        api = get_kaggle_api(username, key)
        auth_method = str(api.get_config_value(api.CONFIG_NAME_AUTH_METHOD) or "")
        if auth_method == "ANONYMOUS":
            raise RuntimeError("Invalid credentials — Kaggle rejected the API token.")

        log(f"Verified & authenticated Kaggle account: @{username}")
        resp = make_response(jsonify({"success": True, "username": username, "key": key}))
        resp.set_cookie("kaggle_username", username, max_age=31536000, samesite="Lax", path="/")
        resp.set_cookie("kaggle_key", key, max_age=31536000, samesite="Lax", path="/")
        return resp
    except Exception as e:
        log(f"Kaggle authentication failed for @{username}: {e}")
        return jsonify({"success": False, "error": f"Authentication failed: {str(e)}"}), 400

# ==========================================
# Routes: Assets Management
# ==========================================

ALLOWED_EXTS = {
    "video": {".mp4", ".mov", ".mkv", ".webm"},
    "voice": {".wav", ".mp3", ".m4a", ".flac", ".ogg"},
    "bgm": {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
    "outro": {".mp4", ".mov", ".mkv", ".webm"},
}

@app.route("/api/studio_state", methods=["GET"])
def studio_state():
    # 1. Global assets
    globals_data = {"voice": None, "bgm": None, "outro": None}
    for asset_type in ["voice", "bgm", "outro"]:
        matches = list(GLOBAL_UPLOADS.glob(f"{asset_type}.*"))
        if matches:
            f = matches[0]
            meta_f = GLOBAL_UPLOADS / f"{asset_type}.meta.json"
            orig_name = f.name
            if meta_f.exists():
                try:
                    with open(meta_f) as mf:
                        orig_name = json.load(mf).get("original_name", f.name)
                except Exception:
                    pass
            globals_data[asset_type] = {
                "filename": f.name,
                "original_name": orig_name,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2)
            }

    # 2. Slot video assets (1 to 10)
    slots_data = {}
    for slot_num in range(1, 11):
        slot_str = str(slot_num)
        slots_data[slot_str] = {"video": None}
        v_matches = [m for m in SLOTS_UPLOADS.glob(f"slot_{slot_num}_video.*") if not m.name.endswith(".meta.json")]
        if v_matches:
            vf = v_matches[0]
            orig_name = vf.name
            meta_f = SLOTS_UPLOADS / f"slot_{slot_num}_video.meta.json"
            if meta_f.exists():
                try:
                    with open(meta_f) as mf:
                        orig_name = json.load(mf).get("original_name", vf.name)
                except Exception:
                    pass
            slots_data[slot_str]["video"] = {
                "filename": vf.name,
                "original_name": orig_name,
                "size_mb": round(vf.stat().st_size / (1024 * 1024), 2)
            }

    return jsonify({
        "globals": globals_data,
        "slots": slots_data,
        "app_state": app_state
    })

@app.route("/api/upload_global", methods=["POST"])
def upload_global():
    if "file" not in request.files or "kind" not in request.form:
        return jsonify({"success": False, "error": "Missing file or kind"}), 400

    file = request.files["file"]
    kind = request.form["kind"].strip().lower()

    if kind not in ALLOWED_EXTS:
        return jsonify({"success": False, "error": f"Invalid kind: {kind}"}), 400

    orig_filename = file.filename or f"{kind}.bin"
    ext = Path(orig_filename).suffix.lower()

    if ext not in ALLOWED_EXTS[kind]:
        return jsonify({"success": False, "error": f"File extension '{ext}' not allowed for {kind}"}), 400

    # Remove existing
    for old_f in GLOBAL_UPLOADS.glob(f"{kind}.*"):
        old_f.unlink()

    dest = GLOBAL_UPLOADS / f"{kind}{ext}"
    file.save(dest)

    meta_file = GLOBAL_UPLOADS / f"{kind}.meta.json"
    with open(meta_file, "w") as mf:
        json.dump({"original_name": orig_filename}, mf)

    log(f"Uploaded Global {kind.upper()}: {orig_filename} ({dest.stat().st_size / (1024*1024):.2f} MB)")
    return jsonify({"success": True, "original_name": orig_filename, "size_mb": round(dest.stat().st_size / (1024*1024), 2)})

@app.route("/api/delete_global", methods=["POST"])
def delete_global():
    data = request.get_json() or {}
    kind = data.get("kind", "").strip().lower()
    if kind:
        for f in GLOBAL_UPLOADS.glob(f"{kind}.*"):
            f.unlink()
        log(f"Deleted Global {kind.upper()}")
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid kind"}), 400

@app.route("/api/upload_slot_file", methods=["POST"])
def upload_slot_file():
    if "file" not in request.files or "slot_num" not in request.form:
        return jsonify({"success": False, "error": "Missing file or slot_num"}), 400

    file = request.files["file"]
    slot_num = request.form["slot_num"].strip()

    orig_filename = file.filename or f"slot_{slot_num}.mp4"
    ext = Path(orig_filename).suffix.lower()

    if ext not in ALLOWED_EXTS["video"]:
        return jsonify({"success": False, "error": f"File extension '{ext}' not allowed for video"}), 400

    # Remove existing
    for old_f in SLOTS_UPLOADS.glob(f"slot_{slot_num}_video.*"):
        old_f.unlink()

    dest = SLOTS_UPLOADS / f"slot_{slot_num}_video{ext}"
    file.save(dest)

    meta_file = SLOTS_UPLOADS / f"slot_{slot_num}_video.meta.json"
    with open(meta_file, "w") as mf:
        json.dump({"original_name": orig_filename}, mf)

    log(f"Uploaded Slot [{slot_num}] Video: {orig_filename} ({dest.stat().st_size / (1024*1024):.2f} MB)")
    return jsonify({"success": True, "original_name": orig_filename, "size_mb": round(dest.stat().st_size / (1024*1024), 2)})

@app.route("/api/delete_slot_file", methods=["POST"])
def delete_slot_file():
    data = request.get_json() or {}
    slot_num = data.get("slot_num")
    if slot_num:
        for f in SLOTS_UPLOADS.glob(f"slot_{slot_num}_video.*"):
            f.unlink()
        log(f"Deleted Slot [{slot_num}] Video")
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid slot_num"}), 400

@app.route("/api/clear_all", methods=["POST"])
def clear_all():
    for f in GLOBAL_UPLOADS.glob("*"):
        f.unlink()
    for f in SLOTS_UPLOADS.glob("*"):
        f.unlink()
    log("Cleared all uploaded assets.")
    return jsonify({"success": True})

# ==========================================
# Routes: Sync Dataset & Push Kernel
# ==========================================

def run_sync_and_launch(config):
    try:
        app_state["status"] = "syncing"
        app_state["progress"] = 10
        app_state["message"] = "Preparing batch shorts dataset..."
        log("=== Starting Batch Shorts Dataset Packaging ===")

        username = config.get("kaggle_username")
        key = config.get("kaggle_key")
        if not username or not key:
            u, k = get_request_credentials()
            username = username or u
            key = key or k
        if not username:
            raise RuntimeError("Kaggle credentials not configured!")

        dataset_slug = "batch-shorts-dataset"
        kernel_slug = "batch-shorts-generator"

        ds_dir = STAGING_DIR / "dataset"
        if ds_dir.exists():
            shutil.rmtree(ds_dir)

        for sub in ["videos", "voices", "bgms", "outros"]:
            (ds_dir / sub).mkdir(parents=True, exist_ok=True)

        # 1. Collect valid slots
        valid_slots = []
        for slot_num in range(1, 11):
            vid_matches = [m for m in SLOTS_UPLOADS.glob(f"slot_{slot_num}_video.*") if not m.name.endswith(".meta.json")]
            if vid_matches:
                valid_slots.append((slot_num, vid_matches[0]))

        if not valid_slots:
            raise RuntimeError("No short videos found! Please upload at least one video.")

        log(f"Found {len(valid_slots)} short video(s) to process.")

        # Copy videos
        for slot_idx, (slot_num, vid_path) in enumerate(valid_slots, start=1):
            ext_v = vid_path.suffix
            shutil.copy2(vid_path, ds_dir / "videos" / f"{slot_idx}_short{ext_v}")
            log(f"Queued Short [{slot_idx}]: '{vid_path.name}'")

        # 2. Copy Global Assets
        # Reference Voice
        voice_matches = [m for m in GLOBAL_UPLOADS.glob("voice.*") if not m.name.endswith(".meta.json")]
        if voice_matches:
            ext = voice_matches[0].suffix
            shutil.copy2(voice_matches[0], ds_dir / "voices" / f"global_voice{ext}")
            shutil.copy2(voice_matches[0], ds_dir / f"voice_ref{ext}")
            log(f"Applied Reference Voice: {voice_matches[0].name}")
        else:
            raise RuntimeError("Reference Voice is required for SeedVC voice conversion!")

        # BGM
        bgm_matches = [m for m in GLOBAL_UPLOADS.glob("bgm.*") if not m.name.endswith(".meta.json")]
        if bgm_matches:
            ext = bgm_matches[0].suffix
            shutil.copy2(bgm_matches[0], ds_dir / "bgms" / f"global_bgm{ext}")
            shutil.copy2(bgm_matches[0], ds_dir / f"bgm{ext}")
            log(f"Applied Background Music: {bgm_matches[0].name}")

        # Outro
        outro_matches = [m for m in GLOBAL_UPLOADS.glob("outro.*") if not m.name.endswith(".meta.json")]
        if outro_matches:
            ext = outro_matches[0].suffix
            shutil.copy2(outro_matches[0], ds_dir / "outros" / f"global_outro{ext}")
            shutil.copy2(outro_matches[0], ds_dir / f"outro{ext}")
            log(f"Applied Outro Clip: {outro_matches[0].name}")

        # Write config.json
        cfg_path = ds_dir / "config.json"
        with open(cfg_path, "w") as f:
            json.dump(config, f, indent=2)
        log(f"Generated config.json: {config}")

        # dataset-metadata.json
        meta_path = ds_dir / "dataset-metadata.json"
        ds_metadata = {
            "title": "Automated Batch Shorts Dataset",
            "id": f"{username}/{dataset_slug}",
            "licenses": [{"name": "CC0-1.0"}]
        }
        with open(meta_path, "w") as f:
            json.dump(ds_metadata, f, indent=2)

        app_state["progress"] = 30
        app_state["message"] = "Uploading batch shorts dataset to Kaggle Cloud..."
        log(f"Syncing dataset '{username}/{dataset_slug}' to Kaggle via API...")

        api = get_kaggle_api(username, key)
        exists = False
        try:
            existing = api.dataset_list(user=username, search=dataset_slug)
            for d in (existing or []):
                if getattr(d, 'ref', '') == f"{username}/{dataset_slug}":
                    exists = True
                    break
        except Exception as e:
            log(f"Dataset lookup notice: {e}")

        if exists:
            log(f"Dataset '{dataset_slug}' exists. Creating new version...")
            res = api.dataset_create_version(str(ds_dir), version_notes=f"Batch Shorts run {time.strftime('%Y-%m-%d %H:%M')}", dir_mode="zip")
            log(f"Dataset version created: {res}")
        else:
            log(f"Creating new private dataset '{dataset_slug}'...")
            res = api.dataset_create_new(str(ds_dir), public=False, dir_mode="zip")
            log(f"Dataset created: {res}")

        app_state["message"] = "Waiting for Kaggle to index dataset..."
        log("Waiting for Kaggle dataset to become READY...")
        for _ in range(25):
            try:
                ds_status = str(api.dataset_status(f"{username}/{dataset_slug}")).lower()
                if "ready" in ds_status:
                    log("✅ Dataset is READY on Kaggle!")
                    break
            except Exception:
                pass
            time.sleep(3)

        app_state["progress"] = 60
        app_state["status"] = "pushing"
        app_state["message"] = "Preparing & launching GPU Notebook..."
        log("=== Preparing Kernel for Background Execution ===")

        kernel_dir = STAGING_DIR / "kernel"
        if kernel_dir.exists():
            shutil.rmtree(kernel_dir)
        kernel_dir.mkdir(parents=True, exist_ok=True)

        master_nb_path = NOTEBOOK_DIR / "batch-shorts-notebook.ipynb"
        with open(master_nb_path) as f:
            nb = json.load(f)

        # Force RUN_MODE = 'batch'
        nb["cells"][5]["source"] = [
            "print('=== 5. Run Mode Switch ===')\n",
            "RUN_MODE = 'batch'   # Auto-set by Kaggle Batch Shorts Studio\n",
            "print(f\"RUN_MODE = '{RUN_MODE}'\")\n"
        ]

        target_nb_path = kernel_dir / "batch-shorts-notebook.ipynb"
        with open(target_nb_path, "w") as f:
            json.dump(nb, f, indent=1)

        # Attach dataset sources (including seedvc-master-models for 0s loading)
        dataset_sources = [f"{username}/{dataset_slug}"]
        try:
            for d in (api.dataset_list(user=username, search="seedvc-master-models") or []):
                if getattr(d, 'ref', '') == f"{username}/seedvc-master-models":
                    dataset_sources.append(f"{username}/seedvc-master-models")
                    log("⚡ Attached 'seedvc-master-models' dataset -> 0-second instant model loading!")
                    break
        except Exception as _e:
            log(f"Notice: {_e}")

        k_meta_path = kernel_dir / "kernel-metadata.json"
        k_metadata = {
            "id": f"{username}/{kernel_slug}",
            "title": "Batch Shorts Generator",
            "code_file": "batch-shorts-notebook.ipynb",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": "true",
            "enable_gpu": "true",
            "enable_tpu": "false",
            "enable_internet": "true",
            "dataset_sources": dataset_sources,
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": []
        }
        with open(k_meta_path, "w") as f:
            json.dump(k_metadata, f, indent=2)

        log(f"Pushing notebook '{username}/{kernel_slug}' with GPU enabled...")
        push_res = api.kernels_push(str(kernel_dir))
        log(f"Notebook push response: {push_res}")

        app_state["progress"] = 75
        app_state["status"] = "running"
        app_state["message"] = "Submitted! Kaggle GPU is now processing your shorts batch in background."
        log("🚀 Processing started on Kaggle GPU!")

    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = str(e)
        log(f"❌ Error during sync/run: {e}")

@app.route("/api/launch", methods=["POST"])
def launch_pipeline():
    if app_state["status"] in ["syncing", "pushing", "running"]:
        return jsonify({"success": False, "error": f"Job already in progress (Status: {app_state['status']})"}), 400

    config = request.get_json() or {}
    req_u, req_k = get_request_credentials()
    k_user = config.get("kaggle_username") or req_u
    k_key = config.get("kaggle_key") or req_k

    if not k_user or not k_key:
        return jsonify({"success": False, "error": "No Kaggle account connected! Please enter your credentials."}), 401

    final_config = {
        "kaggle_username": k_user,
        "kaggle_key": k_key,
        "cooldown_secs": int(config.get("cooldown_secs", 30)),
        "outro_ratio": config.get("outro_ratio", "every_3rd")
    }

    t = threading.Thread(target=run_sync_and_launch, args=(final_config,), daemon=True)
    t.start()

    return jsonify({"success": True, "message": "Batch shorts pipeline started!"})

@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify(app_state)

def monitor_kernel_background():
    """Background polling loop for active Kaggle kernel."""
    while True:
        try:
            if app_state["status"] == "running":
                req_u, req_k = get_request_credentials()
                if not req_u or not req_k:
                    stored = load_stored_credentials()
                    req_u = stored.get("username")
                    req_k = stored.get("key")

                if req_u and req_k:
                    api = get_kaggle_api(req_u, req_k)
                    kernel_ref = f"{req_u}/batch-shorts-generator"
                    st_resp = api.kernel_status(kernel_ref)
                    status_str = str(st_resp.get("status", "")).lower()
                    app_state["last_kernel_status"] = status_str

                    # Fetch live output log
                    try:
                        out_resp = api.kernel_output(kernel_ref)
                        log_text = out_resp.get("log", "")
                        if log_text:
                            for line in log_text.strip().split("\n")[-10:]:
                                if line and line not in app_state["logs"]:
                                    app_state["logs"].append(line)
                                    if len(app_state["logs"]) > 250:
                                        app_state["logs"].pop(0)
                    except Exception:
                        pass

                    if "complete" in status_str:
                        log("🎉 Kaggle kernel run completed! Downloading final outputs...")
                        app_state["message"] = "Processing completed! Downloading final archive..."
                        app_state["progress"] = 90

                        try:
                            api.kernels_output(kernel_ref, path=str(OUTPUT_DIR))
                            for z in ["all_final_videos.zip", "all_final_shorts.zip"]:
                                if (OUTPUT_DIR / z).exists():
                                    app_state["output_file"] = z
                                    break
                            app_state["status"] = "complete"
                            app_state["progress"] = 100
                            app_state["message"] = "All shorts successfully processed and ready to download!"
                            log("📦 Output archive successfully downloaded!")
                        except Exception as dl_e:
                            log(f"Download notice: {dl_e}")
                            app_state["status"] = "complete"
                            app_state["progress"] = 100

                    elif "error" in status_str or "cancel" in status_str:
                        app_state["status"] = "error"
                        app_state["message"] = f"Kaggle kernel ended with status: {status_str}"
                        log(f"❌ Kernel failed with status: {status_str}")

        except Exception as e:
            pass

        time.sleep(10)

threading.Thread(target=monitor_kernel_background, daemon=True).start()

@app.route("/api/download", methods=["GET"])
def download_archive():
    target = None
    for z in ["all_final_videos.zip", "all_final_shorts.zip"]:
        if (OUTPUT_DIR / z).exists():
            target = OUTPUT_DIR / z
            break

    if target:
        return send_file(str(target), as_attachment=True, download_name=target.name)
    return jsonify({"error": "No output archive found yet."}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🎬 Kaggle Batch Shorts Studio starting on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
