#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 Missing equipment image refresher
 ------------------------------------------------------------
 Reuses the Wiki request and image conventions used by the
 project crawler, but writes only missing image files.  CSV
 files and user data are never modified.
============================================================
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


DEFAULT_SOURCE_URL = "https://wiki.biligame.com/blhx/%E8%A3%85%E5%A4%87%E5%9B%BE%E9%89%B4"
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class MissingImage:
    """One image row whose target file is absent."""

    equipment_id: str
    equipment_name: str
    rarity_id: str
    image_path: str


@dataclass(frozen=True)
class RefreshResult:
    """One attempted image recovery and its provenance."""

    equipment_id: str
    equipment_name: str
    target_path: str
    source: str
    source_url: str
    status: str
    error: str = ""


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8-SIG CSV file."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def project_root(start: Path) -> Path:
    """Find the OCR worktree root from a script or caller path."""
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "data" / "equipment_library.csv").is_file():
            return candidate
    raise RuntimeError("Cannot find project root: data/equipment_library.csv is missing.")


def missing_targets(root: Path, equipment_ids: Optional[Sequence[str]] = None) -> list[MissingImage]:
    """Join the official library and image map without writing either file."""
    library = {
        str(row.get("equipment_id", "")).strip(): row
        for row in read_csv(root / "data" / "equipment_library.csv")
    }
    requested = {item.strip() for item in equipment_ids or () if item.strip()}
    output: list[MissingImage] = []
    for row in read_csv(root / "data" / "equipment_images.csv"):
        equipment_id = str(row.get("equipment_id", "")).strip()
        image_value = str(row.get("image_path", "")).strip()
        if not equipment_id or (requested and equipment_id not in requested) or not image_value:
            continue
        target = Path(image_value)
        if not target.is_absolute():
            target = root / target
        if target.is_file():
            continue
        library_row = library.get(equipment_id, {})
        output.append(
            MissingImage(
                equipment_id=equipment_id,
                equipment_name=str(library_row.get("name", "")).strip(),
                rarity_id=str(library_row.get("rarity_id", "")).strip(),
                image_path=image_value,
            )
        )
    return output


def _pick_srcset(srcset: str) -> Optional[str]:
    """Choose the highest resolution srcset candidate."""
    candidates: list[tuple[float, str]] = []
    for item in srcset.split(","):
        parts = item.strip().split()
        if not parts:
            continue
        score = 0.0
        if len(parts) > 1:
            descriptor = parts[-1]
            try:
                score = float(descriptor[:-1]) if descriptor[:-1] else 0.0
            except ValueError:
                score = 0.0
        candidates.append((score, parts[0]))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def _canonical_name(anchor: Any) -> str:
    """Recover the name from the URL, including the Wiki fragment T0/T1... ."""
    href = str(anchor.get("href", "")).strip()
    parsed = urlparse(href)
    path_name = unquote(parsed.path).rstrip("/").rsplit("/", 1)[-1]
    if parsed.fragment:
        path_name = f"{path_name}#{unquote(parsed.fragment)}"
    return " ".join(path_name.replace("_", " ").split()).strip()


def build_page_index(html: str, source_url: str) -> dict[str, str]:
    """Build canonical equipment-name -> full image URL mappings from Wiki HTML."""
    soup = BeautifulSoup(html, "html.parser")
    index: dict[str, str] = {}
    for container in soup.select("div.divsort"):
        anchor = container.find("a", href=True)
        image = container.find("img")
        if anchor is None or image is None:
            continue
        name = _canonical_name(anchor)
        if not name or name in index:
            continue
        srcset = str(image.get("srcset", ""))
        candidate = _pick_srcset(srcset) if srcset else None
        candidate = candidate or str(
            image.get("src")
            or image.get("data-src")
            or image.get("data-original")
            or image.get("data-lazy-src")
            or ""
        ).strip()
        if candidate:
            index[name] = urljoin(source_url, candidate)
    return index


def _build_session() -> Session:
    """Build the same polite retrying HTTP session as the main crawler."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "AzurLaneResearchTrackerCrawler/0.6.0",
            "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": DEFAULT_SOURCE_URL,
        }
    )
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _valid_image(path: Path) -> bool:
    """Accept readable square icons at least as large as the 108px ROI."""
    try:
        with Image.open(path) as image:
            image.load()
            return image.width == image.height and image.width >= 108
    except (OSError, ValueError):
        return False


def _atomic_copy(source: Path, target: Path) -> None:
    """Copy a known image atomically and validate the resulting file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{target.stem}.", suffix=target.suffix, dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        if not _valid_image(temporary):
            raise ValueError(f"invalid image: {source}")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_download(session: Session, url: str, target: Path, source_url: str) -> None:
    """Download and validate one image without leaving partial files."""
    target.parent.mkdir(parents=True, exist_ok=True)
    response = session.get(url, timeout=(10.0, 30.0), headers={"Referer": source_url})
    response.raise_for_status()
    content_type = str(response.headers.get("content-type", "")).lower()
    if "image" not in content_type and not response.content.startswith(b"\xff\xd8"):
        raise ValueError(f"unexpected content type: {content_type or 'unknown'}")
    with tempfile.NamedTemporaryFile(prefix=f".{target.stem}.", suffix=target.suffix, dir=target.parent, delete=False) as handle:
        handle.write(response.content)
        temporary = Path(handle.name)
    try:
        if not _valid_image(temporary):
            raise ValueError("downloaded file is not a square icon")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _default_reference_roots(root: Path) -> list[Path]:
    """Locate crawler-generated snapshots from sibling worktrees when available."""
    candidates = [
        root.parent / "AzurLaneResearchTracker" / "workdir" / "all_imgs",
        root.parent / "AzurLaneResearchTracker-ADB" / "data" / "images",
    ]
    return [path for path in candidates if path.is_dir()]


def refresh_missing_images(
    root: Path,
    targets: Sequence[MissingImage],
    source_url: str = DEFAULT_SOURCE_URL,
    reference_roots: Sequence[Path] = (),
    session: Optional[Session] = None,
    archive_dir: Optional[Path] = None,
) -> list[RefreshResult]:
    """Recover targets from Wiki first, then trusted crawler snapshots."""
    http = session or _build_session()
    response = http.get(source_url, timeout=(10.0, 30.0))
    response.raise_for_status()
    response.encoding = "utf-8"
    page_index = build_page_index(response.text, source_url)
    roots = list(reference_roots) or _default_reference_roots(root)
    results: list[RefreshResult] = []
    if archive_dir is None:
        archive_dir = root / "nn_training_lab" / "archive" / "equipment_image_refresh" / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    archive_dir.mkdir(parents=True, exist_ok=True)
    for item in targets:
        target_path = root / item.image_path if not Path(item.image_path).is_absolute() else Path(item.image_path)
        image_url = page_index.get(item.equipment_name, "")
        try:
            if image_url:
                _atomic_download(http, image_url, target_path, source_url)
                source = "wiki"
            else:
                reference = next(
                    (candidate / Path(item.image_path).parent.name / f"{item.equipment_id}.jpg" for candidate in roots if (candidate / Path(item.image_path).parent.name / f"{item.equipment_id}.jpg").is_file()),
                    None,
                )
                if reference is None:
                    reference = next((candidate / f"{item.equipment_id}.jpg" for candidate in roots if (candidate / f"{item.equipment_id}.jpg").is_file()), None)
                if reference is None:
                    raise FileNotFoundError("equipment is absent from current Wiki and reference snapshots")
                _atomic_copy(reference, target_path)
                source = f"reference:{reference}"
            archive_target = archive_dir / item.equipment_id / target_path.name
            _atomic_copy(target_path, archive_target)
            results.append(RefreshResult(item.equipment_id, item.equipment_name, str(target_path), source, image_url, "success"))
        except (OSError, ValueError, requests.RequestException) as exc:
            results.append(RefreshResult(item.equipment_id, item.equipment_name, str(target_path), "", image_url, "failed", str(exc)))
    (archive_dir / "refresh_manifest.json").write_text(
        json.dumps({"targets": [asdict(item) for item in targets], "results": [asdict(item) for item in results]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    root = project_root(Path(__file__))
    parser = argparse.ArgumentParser(description="Recover missing equipment images without changing CSV files.")
    parser.add_argument("--ids", nargs="*", help="Only recover these IDs; default is every missing image.")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Only list missing rows.")
    parser.set_defaults(project_root=root)
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    root: Path = args.project_root
    targets = missing_targets(root, args.ids)
    print(json.dumps({"missing_count": len(targets), "targets": [asdict(item) for item in targets]}, ensure_ascii=False, indent=2))
    if args.dry_run or not targets:
        return 0
    results = refresh_missing_images(root, targets, args.source_url, archive_dir=args.archive_dir)
    print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
    return 0 if all(item.status == "success" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
