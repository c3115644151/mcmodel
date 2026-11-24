#!/usr/bin/env python3
"""Repair a Minecraft asset cache from its official SHA-1 indexed asset manifest.

The configured HTTPS proxy sometimes truncates large responses. This downloader
resumes each object with HTTP Range requests and verifies the official SHA-1
before placing it in the Gradle/Minecraft object cache.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index",
        type=Path,
        default=Path.home() / ".gradle/caches/minecraft/assets/indexes/asset-index.json",
        help="official asset index JSON downloaded by NeoGradle",
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        default=Path.home() / ".gradle/caches/minecraft/assets",
        help="Minecraft asset cache root containing the objects/ folder",
    )
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    args = parser.parse_args()

    manifest = json.loads(args.index.read_text(encoding="utf-8"))
    objects: dict[str, dict[str, int]] = manifest["objects"]
    proxy = urllib.request.ProxyHandler({"http": args.proxy, "https": args.proxy})
    opener = urllib.request.build_opener(proxy)
    todo: list[tuple[str, int, Path]] = []
    for name, info in objects.items():
        digest = info["hash"]
        target = args.asset_root / "objects" / digest[:2] / digest
        if target.is_file() and target.stat().st_size == info["size"] and sha1_file(target) == digest:
            continue
        todo.append((digest, info["size"], target))

    print(f"Asset index has {len(objects)} objects; {len(todo)} need repair/download.", flush=True)

    def fetch_one(entry: tuple[str, int, Path]) -> tuple[str, int]:
        digest, expected_size, target = entry
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".range-part")
        if partial.exists() and partial.stat().st_size > expected_size:
            partial.unlink()
        offset = partial.stat().st_size if partial.exists() else 0
        end = expected_size - 1
        attempts_without_progress = 0
        url = f"https://resources.download.minecraft.net/{digest[:2]}/{digest}"

        with partial.open("ab") as output:
            while offset < expected_size:
                request = urllib.request.Request(
                    url,
                    headers={
                        "Range": f"bytes={offset}-{end}",
                        "Accept-Encoding": "identity",
                        "User-Agent": "PastoralHome-Gradle-AssetCache/1.0",
                    },
                )
                try:
                    with opener.open(request, timeout=45) as response:
                        if response.status not in (200, 206):
                            raise RuntimeError(f"HTTP {response.status} for {digest}")
                        if offset and response.status != 206:
                            raise RuntimeError(f"Server ignored resume range at byte {offset} for {digest}")
                        content_range = response.headers.get("Content-Range", "")
                        if response.status == 206 and not content_range.startswith(f"bytes {offset}-"):
                            raise RuntimeError(f"Unexpected Content-Range {content_range!r} for {digest}")
                        try:
                            payload = response.read()
                        except http.client.IncompleteRead as exc:
                            payload = exc.partial
                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                    attempts_without_progress += 1
                    if attempts_without_progress >= 12:
                        raise RuntimeError(f"Repeated download failure for {digest} at byte {offset}: {exc}") from exc
                    time.sleep(min(0.25 * attempts_without_progress, 2.0))
                    continue

                payload = payload[: expected_size - offset]
                if payload:
                    output.write(payload)
                    output.flush()
                    offset += len(payload)
                    attempts_without_progress = 0
                else:
                    attempts_without_progress += 1
                    if attempts_without_progress >= 12:
                        raise RuntimeError(f"No response bytes for {digest} at byte {offset}")
                    time.sleep(min(0.25 * attempts_without_progress, 2.0))

        if partial.stat().st_size != expected_size or sha1_file(partial) != digest:
            raise RuntimeError(f"SHA-1/size verification failed for {digest} ({partial.stat().st_size}/{expected_size})")
        os.replace(partial, target)
        return digest, expected_size

    total_bytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(fetch_one, entry) for entry in todo]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            _, size = future.result()
            total_bytes += size
            if completed % 100 == 0 or completed == len(futures):
                print(f"Verified {completed}/{len(futures)} assets ({total_bytes:,} bytes fetched).", flush=True)

    print("Every asset in the official index now matches its SHA-1.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
