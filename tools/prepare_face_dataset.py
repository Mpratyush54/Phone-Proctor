"""
Face Dataset Preparer (tools/prepare_face_dataset.py)

Extracts the FULL public LFW-funneled dataset (13,233 faces at 250x250, ~2.4GB
uncompressed) into data/face_crops/ so the synthetic-data generator can paste
real faces into its rendered webcam frames (rich sessions).

The archive is reused from the sklearn cache (~/scikit_learn_data/lfw_home/
lfw-funneled.tgz) if present, otherwise downloaded once from the official site
(~230MB). Extraction is done directly with tarfile so NO subset filtering is
applied -- every one of the 13,233 faces is written.

Logging: console + logs/prepare_face_dataset.log (timestamps, per-1000 progress,
download progress, ETA). A lock file prevents concurrent runs.

Usage:
    python tools/prepare_face_dataset.py [--out data/face_crops] [--limit 0]
"""

import argparse
import logging
import os
import shutil
import sys
import tarfile
import time
import urllib.request

_LFW_URL = "http://vis-www.cs.umass.edu/lfw/lfw-funneled.tgz"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _setup_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    log = logging.getLogger("face")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    log.addHandler(console)
    file_h = logging.FileHandler(os.path.join(log_dir, "prepare_face_dataset.log"), encoding="utf-8")
    file_h.setFormatter(fmt)
    log.addHandler(file_h)
    return log


def _dir_mb(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / (1024.0 * 1024.0)


def _find_cached_tgz():
    home = os.environ.get("SCIKIT_LEARN_DATA", os.path.expanduser("~/scikit_learn_data"))
    cand = os.path.join(home, "lfw_home", "lfw-funneled.tgz")
    return cand if os.path.isfile(cand) else None


def _download(url, dest, log):
    tmp = dest + ".part"
    log.info("Downloading %s -> %s", url, dest)
    req = urllib.request.urlopen(url)
    total = int(req.headers.get("Content-Length", 0))
    done = 0
    t0 = time.time()
    with open(tmp, "wb") as f:
        while True:
            chunk = req.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and done >= total - 8 * 1024 * 1024 and done % (8 * 1024 * 1024) == 0:
                pass
            if total and done % (16 * 1024 * 1024) == 0:
                log.info("downloaded %d/%d MB (%.1f MB/s)",
                         done // (1024 * 1024), total // (1024 * 1024),
                         (done / 1e6) / max(time.time() - t0, 1e-9))
    os.replace(tmp, dest)
    log.info("download complete: %d MB", os.path.getsize(dest) // (1024 * 1024))


def _acquire_lock(lock_path, log):
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        log.error("Another prepare_face_dataset.py run is in progress (lock %s exists).", lock_path)
        return False


def main():
    ap = argparse.ArgumentParser(description="Extract the full LFW-funneled face dataset")
    ap.add_argument("--out", default="data/face_crops", help="output crop directory")
    ap.add_argument("--limit", type=int, default=0, help="max crops (0 = all 13,233)")
    ap.add_argument("--log-dir", default="logs", help="directory for the log file")
    args = ap.parse_args()

    log = _setup_logging(args.log_dir)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    lock_path = out_dir + ".lock"
    if not _acquire_lock(lock_path, log):
        sys.exit(1)

    t0 = time.time()
    try:
        tgz = _find_cached_tgz()
        if not tgz:
            tgz = os.path.join(os.path.dirname(out_dir), "lfw-funneled.tgz")
            _download(_LFW_URL, tgz, log)
        log.info("Archive: %s (%d MB)", tgz, os.path.getsize(tgz) // (1024 * 1024))

        raw = os.path.join(os.path.dirname(out_dir), "_lfw_funneled_raw")
        if os.path.isdir(raw):
            shutil.rmtree(raw, ignore_errors=True)
        os.makedirs(raw)
        log.info("Extracting all 13,233 faces (250x250)...")
        with tarfile.open(tgz, "r:gz") as t:
            members = [m for m in t.getmembers() if m.isfile() and m.name.endswith(".jpg")]
            total = len(members)
            for i, m in enumerate(members, 1):
                t.extract(m, raw)
                if i % 1000 == 0:
                    log.info("extracted %d/%d", i, total)
        log.info("extracted %d images (%.1fs)", total, time.time() - t0)

        written = 0
        for root, _, files in os.walk(raw):
            for fname in sorted(files):
                if not fname.lower().endswith(".jpg"):
                    continue
                person = os.path.basename(root)
                src = os.path.join(root, fname)
                dst = os.path.join(out_dir, f"{person}_{fname}")
                shutil.copyfile(src, dst)
                written += 1
                if written % 2000 == 0:
                    log.info("copied %d crops (%d MB, %.1fs)", written, _dir_mb(out_dir), time.time() - t0)
                if args.limit and written >= args.limit:
                    break
            if args.limit and written >= args.limit:
                break

        shutil.rmtree(raw, ignore_errors=True)
        log.info("DONE: wrote %d crops to %s (%.0f MB raw-equivalent %.2f GB, %.1fs)",
                 written, out_dir, _dir_mb(out_dir), total * 250 * 250 * 3 / 1e9, time.time() - t0)
    finally:
        _release_lock(lock_path)


def _release_lock(lock_path):
    try:
        os.remove(lock_path)
    except OSError:
        pass


if __name__ == "__main__":
    main()
