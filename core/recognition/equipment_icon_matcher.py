#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        装备图标匹配器 (equipment_icon_matcher.py)            ║
║  【一句话解释】把截图里的装备图标和 data/images 装备图库比对。 ║
║  【类比理解】它像拿着装备图鉴逐张对照，像才认，不像就 unknown。║
║  【数据流】截图/卡片图 → 图标ROI → OpenCV预处理 → 图库检索。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.utils.path_manager import PathManager

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - 本机缺 OpenCV 时允许降级
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - 极简环境兜底
    _np = None


# ============================================================
# 🧱 第二部分：结果对象
# ============================================================

RoiRegion = Tuple[int, int, int, int]
RatioRegion = Tuple[float, float, float, float]
ImagePair = Tuple[Any, Any, Any, Any]


@dataclass(frozen=True)
class EquipmentIconCandidate:
    """单个装备图标候选结果。"""

    equipment_id: str
    confidence: float
    image_path: str
    rank: int
    method: str
    score_detail: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        """转换成 JSON/CSV 友好的字典。"""
        return {
            "equipment_id": self.equipment_id,
            "confidence": float(self.confidence),
            "image_path": self.image_path,
            "rank": int(self.rank),
            "method": self.method,
            "score_detail": dict(self.score_detail),
        }


@dataclass(frozen=True)
class EquipmentIconMatchResult:
    """装备图标匹配批次结果。"""

    success: bool
    status: str
    message: str
    equipment_id: str = "unknown"
    confidence: float = 0.0
    icon_roi: Optional[RoiRegion] = None
    matched_image_path: str = ""
    candidates: Tuple[EquipmentIconCandidate, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换成可序列化 payload。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "equipment_id": self.equipment_id,
            "confidence": float(self.confidence),
            "icon_roi": list(self.icon_roi) if self.icon_roi else None,
            "matched_image_path": self.matched_image_path,
            "candidates": [item.to_dict() for item in self.candidates],
            "warnings": list(self.warnings),
        }


# ============================================================
# 🏗️ 第三部分：装备图标匹配器
# ============================================================

class EquipmentIconMatcher:
    """
    基于 data/images 的装备图标图库检索器。

    输入:
        装备卡片图标、完整装备卡片，或测试注入的 reference_images。
    输出:
        EquipmentIconMatchResult，包含 best id、top-N 候选和 unknown 原因。
    使用示例:
        matcher = EquipmentIconMatcher()
        result = matcher.match_card(card_image, card_type="equipment")
    """

    DEFAULT_ICON_RATIOS: Dict[str, Tuple[RatioRegion, ...]] = {
        "equipment": (
            (0.05, 0.08, 0.82, 0.68),
            (0.00, 0.00, 0.90, 0.78),
        ),
        "fragment": (
            (0.00, 0.00, 0.30, 1.00),
            (0.02, 0.06, 0.24, 0.86),
        ),
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        gallery_csv_path: Optional[str | Path] = None,
        gallery_csv_paths: Optional[Sequence[str | Path]] = None,
        project_root: Optional[str | Path] = None,
        cv2_module: Optional[Any] = None,
        np_module: Optional[Any] = None,
        reference_images: Optional[Mapping[str, Any]] = None,
        reference_paths: Optional[Mapping[str, str]] = None,
    ) -> None:
        """初始化匹配器；图库采用延迟加载，避免 GUI 启动变慢。"""
        self.project_root = Path(project_root) if project_root is not None else PathManager.get_project_root()
        # 未显式注入配置时，直接调用入口也必须和截图流水线使用同一套图库。
        # 显式传入空字典仍表示调用方要求最小配置，便于测试和隔离环境。
        self.config = (
            self._load_default_matching_config(self.project_root)
            if config is None
            else dict(config)
        )
        configured_gallery = self.config.get("gallery_csv_path") or self.config.get("gallery_path")
        raw_gallery_path = gallery_csv_path if gallery_csv_path is not None else configured_gallery
        configured_paths = self.config.get("gallery_csv_paths")
        supplemental_paths = self.config.get("supplemental_gallery_csv_paths", ())
        if gallery_csv_paths is not None:
            raw_gallery_paths = list(gallery_csv_paths)
        elif isinstance(configured_paths, (list, tuple)) and configured_paths:
            raw_gallery_paths = list(configured_paths)
        else:
            raw_gallery_paths = [raw_gallery_path or (self.project_root / "data" / "equipment_images.csv")]
            if isinstance(supplemental_paths, (list, tuple)):
                raw_gallery_paths.extend(supplemental_paths)
        resolved_gallery_paths: List[Path] = []
        for raw_path in raw_gallery_paths:
            resolved = self._resolve_config_path(raw_path)
            if resolved not in resolved_gallery_paths:
                resolved_gallery_paths.append(resolved)
        self.gallery_csv_paths = tuple(resolved_gallery_paths)
        self.gallery_csv_path = self.gallery_csv_paths[0] if self.gallery_csv_paths else (
            self.project_root / "data" / "equipment_images.csv"
        )
        self.threshold = float(self.config.get("threshold", 0.82))
        self.ambiguous_margin = float(self.config.get("ambiguous_margin", 0.025))
        self.top_n = max(1, int(self.config.get("top_n", 5)))
        self.target_size = self._target_size_from_config(self.config.get("target_size", [96, 96]))
        (
            self.structure_weight,
            self.color_weight,
            self.edge_weight,
            self.hash_weight,
            self.region_weight,
        ) = self._score_weights_from_config()
        self.region_grid = self._region_grid_from_config(self.config.get("region_grid", [3, 3]))
        self.region_keep_ratio = max(0.34, min(1.0, float(self.config.get("region_keep_ratio", 0.72))))
        self.region_refine_top_k = max(1, int(self.config.get("region_refine_top_k", 32)))
        self.min_icon_size = self._target_size_from_config(self.config.get("min_icon_size", [12, 12]))
        self.icon_ratios = self._icon_ratios_from_config(self.config.get("icon_ratios"))
        self._cv2 = cv2_module
        self._np = np_module
        self._reference_images = dict(reference_images or {})
        self._reference_paths = dict(reference_paths or {})
        self._gallery: List[Dict[str, Any]] = []
        self._gallery_loaded = False
        self._gallery_warnings: List[str] = []

    def check_status(self) -> Dict[str, Any]:
        """检查 OpenCV/NumPy 和图库配置是否可用，但不强制加载全部图片。"""
        cv2_available = self._get_cv2() is not None
        np_available = self._get_np() is not None
        has_injected_gallery = bool(self._reference_images)
        gallery_csv_exists = self.gallery_csv_path.exists()
        return {
            "available": bool(cv2_available and np_available and (has_injected_gallery or gallery_csv_exists)),
            "dependencies": {
                "opencv_cv2": cv2_available,
                "numpy": np_available,
            },
            "gallery_csv_path": str(self.gallery_csv_path),
            "gallery_csv_exists": bool(gallery_csv_exists),
            "gallery_csv_paths": [str(path) for path in self.gallery_csv_paths],
            "gallery_sources_configured": len(self.gallery_csv_paths),
            "gallery_source_exists": [path.is_file() for path in self.gallery_csv_paths],
            "gallery_loaded": bool(self._gallery_loaded),
            "gallery_loaded_rows": len(self._gallery),
            "gallery_loaded_equipment_ids": len({item["equipment_id"] for item in self._gallery}),
            "gallery_warnings": list(self._gallery_warnings),
            "injected_gallery_count": len(self._reference_images),
            "threshold": self.threshold,
            "ambiguous_margin": self.ambiguous_margin,
            "target_size": list(self.target_size),
        }

    def reload(self) -> None:
        """清空内存图库；爬虫更新 data/images 后可调用它重建索引。"""
        self._gallery = []
        self._gallery_loaded = False
        self._gallery_warnings = []

    def load_image(self, image_path: str | Path) -> Any:
        """用 OpenCV 读取图片，主要供本地调试或预览工具使用。"""
        cv2_module = self._require_cv2()
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"图标图片不存在: {path}")
        image = cv2_module.imread(str(path), getattr(cv2_module, "IMREAD_COLOR", 1))
        if image is None or getattr(image, "size", 0) == 0:
            raise ValueError(f"图标图片无法读取或已损坏: {path}")
        return image

    def match_file(
        self,
        image_path: str | Path,
        mode: str = "icon",
        card_type: str = "equipment",
        top_n: Optional[int] = None,
    ) -> EquipmentIconMatchResult:
        """从磁盘图片直接匹配装备图标。"""
        unavailable = self._dependency_warning()
        if unavailable:
            return EquipmentIconMatchResult(False, "unavailable", unavailable, warnings=(unavailable,))
        try:
            image = self.load_image(image_path)
        except Exception as exc:
            return EquipmentIconMatchResult(False, "error", str(exc), warnings=(str(exc),))
        if mode == "card":
            return self.match_card(image, card_type=card_type, top_n=top_n)
        return self.match_icon(image, top_n=top_n)

    def match_card(
        self,
        card_image: Any,
        card_type: str = "equipment",
        icon_roi: Optional[Sequence[int | float]] = None,
        top_n: Optional[int] = None,
    ) -> EquipmentIconMatchResult:
        """从装备/碎片卡片中裁出图标区域后匹配装备 ID。"""
        try:
            parent_roi = self._full_image_roi(card_image)
            roi_candidates = self._resolve_icon_rois(parent_roi, card_type, icon_roi)
        except Exception as exc:
            return EquipmentIconMatchResult(False, "error", str(exc), warnings=(str(exc),))

        best_result: Optional[EquipmentIconMatchResult] = None
        for roi in roi_candidates:
            result = self.match_icon(card_image, icon_roi=roi, top_n=top_n)
            if result.status == "success":
                return result
            if best_result is None or result.confidence > best_result.confidence:
                best_result = result
        if best_result is not None:
            return best_result
        return EquipmentIconMatchResult(True, "unknown", "没有可用的装备图标 ROI。")

    def match_icon(
        self,
        image: Any,
        icon_roi: Optional[Sequence[int]] = None,
        top_n: Optional[int] = None,
        reference_vertical_ratio: Optional[float] = None,
    ) -> EquipmentIconMatchResult:
        """匹配一张已经裁好的装备图标，或从 image 的 icon_roi 裁剪后匹配。"""
        unavailable = self._dependency_warning()
        if unavailable:
            return EquipmentIconMatchResult(False, "unavailable", unavailable, warnings=(unavailable,))

        try:
            self._ensure_gallery()
            query_pair, safe_roi = self._prepare_icon(image, icon_roi)
        except Exception as exc:
            return EquipmentIconMatchResult(False, "error", str(exc), warnings=(str(exc),))

        if not self._gallery:
            message = "装备图标图库为空，无法识别 equipment_id。"
            return EquipmentIconMatchResult(True, "no_gallery", message, icon_roi=safe_roi, warnings=tuple(self._gallery_warnings))

        ranked_records: List[Tuple[Dict[str, Any], ImagePair, EquipmentIconCandidate]] = []
        for item in self._gallery:
            prepared = self._reference_prepared_for_ratio(item, reference_vertical_ratio)
            ranked_records.append(
                (
                    item,
                    prepared,
                    self._candidate_from_scores(
                        item,
                        self._score_pair(query_pair, prepared, include_region=False),
                        method="template_color_fusion",
                    ),
                )
            )

        ranked_records.sort(key=lambda record: record[2].confidence, reverse=True)
        refine_limit = min(
            len(ranked_records),
            max(self.region_refine_top_k, int(top_n if top_n is not None else self.top_n)),
        )
        ranked: List[EquipmentIconCandidate] = []
        for index, (item, prepared, candidate) in enumerate(ranked_records):
            if self.region_weight > 0.0 and index < refine_limit:
                candidate = self._candidate_from_scores(
                    item,
                    self._score_pair(query_pair, prepared, include_region=True),
                    method="template_color_region_fusion",
                )
            ranked.append(candidate)

        ranked.sort(key=lambda candidate: candidate.confidence, reverse=True)
        top_limit = max(1, int(top_n if top_n is not None else self.top_n))
        top_candidates = tuple(
            EquipmentIconCandidate(
                item.equipment_id,
                item.confidence,
                item.image_path,
                index + 1,
                item.method,
                item.score_detail,
            )
            for index, item in enumerate(ranked[:top_limit])
        )
        best = top_candidates[0]
        second_distinct = self._first_distinct_candidate(ranked, best.equipment_id)
        second_distinct_confidence = second_distinct.confidence if second_distinct is not None else 0.0
        margin = best.confidence - second_distinct_confidence

        if best.confidence < self.threshold:
            message = f"最高匹配分 {best.confidence:.3f} 低于阈值 {self.threshold:.3f}，返回 unknown。"
            return EquipmentIconMatchResult(
                True,
                "unknown",
                message,
                confidence=best.confidence,
                icon_roi=safe_roi,
                candidates=top_candidates,
                warnings=tuple(self._gallery_warnings),
            )
        if second_distinct is not None and margin < self.ambiguous_margin:
            message = (
                f"Top1/次高不同装备分差 {margin:.3f} 小于 {self.ambiguous_margin:.3f}，"
                "返回 unknown 避免错认。"
            )
            return EquipmentIconMatchResult(
                True,
                "ambiguous",
                message,
                confidence=best.confidence,
                icon_roi=safe_roi,
                candidates=top_candidates,
                warnings=tuple(self._gallery_warnings),
            )

        return EquipmentIconMatchResult(
            True,
            "success",
            "装备图标匹配完成。",
            equipment_id=best.equipment_id,
            confidence=best.confidence,
            icon_roi=safe_roi,
            matched_image_path=best.image_path,
            candidates=top_candidates,
            warnings=tuple(self._gallery_warnings),
        )

    @staticmethod
    def _candidate_from_scores(
        item: Mapping[str, Any],
        scores: Tuple[float, float, float, float, float, float],
        method: str,
    ) -> EquipmentIconCandidate:
        """把多特征分数包装成候选对象。"""
        structure_score, color_score, edge_score, hash_score, region_score, confidence = scores
        return EquipmentIconCandidate(
            equipment_id=str(item["equipment_id"]),
            confidence=confidence,
            image_path=str(item["image_path"]),
            rank=0,
            method=method,
            score_detail={
                "structure": structure_score,
                "color": color_score,
                "edge": edge_score,
                "hash": hash_score,
                "region": region_score,
            },
        )

    @staticmethod
    def _first_distinct_candidate(
        ranked: Sequence[EquipmentIconCandidate],
        equipment_id: str,
    ) -> Optional[EquipmentIconCandidate]:
        """找到第一个不同 equipment_id 的候选；同装备多样本不参与 ambiguous 分差。"""
        for candidate in ranked:
            if candidate.equipment_id != equipment_id:
                return candidate
        return None

    def _ensure_gallery(self) -> None:
        """延迟加载装备图库，并把参考图预处理成固定尺寸。"""
        if self._gallery_loaded:
            return
        self._gallery_loaded = True
        self._gallery = []
        self._gallery_warnings = []

        if self._reference_images:
            for equipment_id, image in self._reference_images.items():
                try:
                    self._gallery.append(
                        {
                            "equipment_id": str(equipment_id),
                            "image_path": self._reference_paths.get(str(equipment_id), ""),
                            "source_image": image,
                            "prepared": self._prepare_icon(image, None)[0],
                            "ratio_cache": {},
                        }
                    )
                except Exception as exc:
                    self._gallery_warnings.append(f"{equipment_id}: {exc}")
            return

        cv2_module = self._require_cv2()
        for equipment_id, image_path in self._load_gallery_rows():
            resolved_path = self._resolve_gallery_path(image_path)
            try:
                image = cv2_module.imread(str(resolved_path), getattr(cv2_module, "IMREAD_COLOR", 1))
                if image is None or getattr(image, "size", 0) == 0:
                    raise ValueError("图片无法读取")
                self._gallery.append(
                    {
                        "equipment_id": equipment_id,
                        "image_path": str(resolved_path),
                        "source_image": image,
                        "prepared": self._prepare_icon(image, None)[0],
                        "ratio_cache": {},
                    }
                )
            except Exception as exc:
                self._gallery_warnings.append(f"{equipment_id}: {resolved_path}: {exc}")

    def _load_gallery_rows(self) -> Tuple[Tuple[str, str], ...]:
        """只读加载所有装备图库来源，并按 ``equipment_id + image_path`` 去重。"""
        rows: List[Tuple[str, str]] = []
        seen: set[Tuple[str, str]] = set()
        for gallery_path in self.gallery_csv_paths:
            if not gallery_path.exists():
                self._gallery_warnings.append(f"装备图片映射文件不存在: {gallery_path}")
                continue
            try:
                with gallery_path.open("r", encoding="utf-8-sig", newline="") as file:
                    for row in csv.DictReader(file):
                        equipment_id = str(row.get("equipment_id", "")).strip()
                        image_path = str(row.get("image_path", "")).strip()
                        key = (equipment_id, image_path)
                        if equipment_id and image_path and key not in seen:
                            seen.add(key)
                            rows.append(key)
            except (OSError, csv.Error) as exc:
                self._gallery_warnings.append(f"装备图片映射文件无法读取: {gallery_path}: {exc}")
        return tuple(rows)

    def _prepare_icon(self, image: Any, icon_roi: Optional[Sequence[int]]) -> Tuple[ImagePair, RoiRegion]:
        """裁剪、缩放并生成灰度/彩色双视图，供结构分和颜色分使用。"""
        cv2_module = self._require_cv2()
        np_module = self._require_np()
        if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
            raise ValueError("装备图标图像为空。")

        safe_roi = self._full_image_roi(image) if icon_roi is None else self._validate_roi(image, icon_roi)
        x, y, width, height = safe_roi
        min_width, min_height = self.min_icon_size
        if width < min_width or height < min_height:
            raise ValueError(
                f"装备图标 ROI 过小: {(width, height)} < {(min_width, min_height)}，"
                "疑似截图/卡片不完整。"
            )
        crop = image[y:y + height, x:x + width]
        if crop is None or getattr(crop, "size", 0) == 0:
            raise ValueError("装备图标 ROI 裁剪为空。")

        resized_color = self._resize(crop, self.target_size, cv2_module)
        if len(resized_color.shape) == 2:
            gray = resized_color
            color = np_module.stack([resized_color, resized_color, resized_color], axis=2)
        else:
            color = resized_color
            gray = cv2_module.cvtColor(resized_color, cv2_module.COLOR_BGR2GRAY)
        edge = self._edge_view(gray, cv2_module)
        perceptual_hash = self._difference_hash(gray, np_module)
        return (
            gray.astype("float32"),
            color.astype("float32"),
            edge.astype("float32"),
            perceptual_hash,
        ), safe_roi

    def _score_pair(
        self,
        query: ImagePair,
        reference: ImagePair,
        include_region: bool = True,
    ) -> Tuple[float, float, float, float, float, float]:
        """融合结构、颜色、边缘和感知哈希，降低相似背景或相似轮廓的误认。"""
        query_gray, query_color, query_edge, query_hash = query
        ref_gray, ref_color, ref_edge, ref_hash = reference
        structure_score = self._template_score(query_gray, ref_gray)
        color_score = self._color_score(query_color, ref_color)
        edge_score = self._template_score(query_edge, ref_edge)
        hash_score = self._hash_score(query_hash, ref_hash)
        region_score = self._region_score(query, reference) if include_region else 0.0
        if include_region:
            confidence = (
                self.structure_weight * structure_score
                + self.color_weight * color_score
                + self.edge_weight * edge_score
                + self.hash_weight * hash_score
                + self.region_weight * region_score
            )
        else:
            total = max(1e-6, self.structure_weight + self.color_weight + self.edge_weight + self.hash_weight)
            confidence = (
                self.structure_weight * structure_score
                + self.color_weight * color_score
                + self.edge_weight * edge_score
                + self.hash_weight * hash_score
            ) / total
        return (
            max(0.0, min(1.0, structure_score)),
            max(0.0, min(1.0, color_score)),
            max(0.0, min(1.0, edge_score)),
            max(0.0, min(1.0, hash_score)),
            max(0.0, min(1.0, region_score)),
            max(0.0, min(1.0, confidence)),
        )

    def _region_score(self, query: ImagePair, reference: ImagePair) -> float:
        """
        计算遮挡容忍的分块分数。

        装备页可能在图标角落叠加强化等级、数量或“装备中”小人标记。
        这里把图标切成网格，只平均较好的若干块，避免单个角落遮挡拖垮整图。
        """
        if self.region_weight <= 0.0:
            return 0.0
        query_gray, query_color, query_edge, _ = query
        ref_gray, ref_color, ref_edge, _ = reference
        rows, cols = self.region_grid
        height, width = int(query_gray.shape[0]), int(query_gray.shape[1])
        if rows <= 0 or cols <= 0 or height < rows or width < cols:
            return 0.0

        scores: List[float] = []
        for row in range(rows):
            y0 = int(round(height * row / rows))
            y1 = int(round(height * (row + 1) / rows))
            for col in range(cols):
                x0 = int(round(width * col / cols))
                x1 = int(round(width * (col + 1) / cols))
                if y1 <= y0 or x1 <= x0:
                    continue
                structure = self._template_score(query_gray[y0:y1, x0:x1], ref_gray[y0:y1, x0:x1])
                color = self._color_score(query_color[y0:y1, x0:x1], ref_color[y0:y1, x0:x1])
                edge = self._template_score(query_edge[y0:y1, x0:x1], ref_edge[y0:y1, x0:x1])
                scores.append(0.45 * structure + 0.35 * color + 0.20 * edge)
        if not scores:
            return 0.0

        scores.sort(reverse=True)
        keep_count = max(1, int(round(len(scores) * self.region_keep_ratio)))
        kept = scores[:keep_count]
        return sum(kept) / float(len(kept))

    def _template_score(self, query_gray: Any, ref_gray: Any) -> float:
        """优先使用 cv2.matchTemplate，同尺寸场景下等价于模板相关性。"""
        cv2_module = self._get_cv2()
        np_module = self._require_np()
        if cv2_module is not None and hasattr(cv2_module, "matchTemplate"):
            try:
                score_map = cv2_module.matchTemplate(
                    query_gray,
                    ref_gray,
                    getattr(cv2_module, "TM_CCOEFF_NORMED", 5),
                )
                return self._correlation_to_similarity(float(np_module.max(score_map)))
            except Exception:
                pass
        return self._normalized_correlation(query_gray, ref_gray)

    def _color_score(self, query_color: Any, ref_color: Any) -> float:
        """用平均绝对色差做颜色分，简单稳定且不依赖额外模型。"""
        np_module = self._require_np()
        diff = np_module.abs(query_color.astype("float32") - ref_color.astype("float32"))
        score = 1.0 - float(np_module.mean(diff)) / 255.0
        return max(0.0, min(1.0, score))

    def _hash_score(self, query_hash: Any, ref_hash: Any) -> float:
        """用差分哈希衡量粗轮廓相似度，作为模板分的轻量补充。"""
        np_module = self._require_np()
        try:
            total = int(query_hash.size)
            if total <= 0:
                return 0.0
            distance = int(np_module.count_nonzero(query_hash != ref_hash))
            return max(0.0, min(1.0, 1.0 - distance / float(total)))
        except Exception:
            return 0.0

    def _reference_prepared_for_ratio(self, item: Dict[str, Any], ratio: Optional[float]) -> ImagePair:
        """底部半截图标只和图库同等可见比例的上半部分比对。"""
        if ratio is None:
            return item["prepared"]
        try:
            normalized_ratio = max(0.20, min(1.0, float(ratio)))
        except (TypeError, ValueError):
            return item["prepared"]
        if normalized_ratio >= 0.98:
            return item["prepared"]

        ratio_key = f"{normalized_ratio:.3f}"
        cache = item.setdefault("ratio_cache", {})
        if ratio_key in cache:
            return cache[ratio_key]

        source_image = item.get("source_image")
        if source_image is None or not hasattr(source_image, "shape"):
            return item["prepared"]
        crop_height = max(1, int(round(int(source_image.shape[0]) * normalized_ratio)))
        top_crop = source_image[:crop_height, :]
        prepared = self._prepare_icon(top_crop, None)[0]
        cache[ratio_key] = prepared
        return prepared

    def _normalized_correlation(self, first: Any, second: Any) -> float:
        """NumPy 兜底相关性，避免 fake cv2 测试必须完整实现 OpenCV。"""
        np_module = self._require_np()
        a = first.astype("float32").reshape(-1)
        b = second.astype("float32").reshape(-1)
        a_centered = a - float(np_module.mean(a))
        b_centered = b - float(np_module.mean(b))
        denom = float(np_module.linalg.norm(a_centered) * np_module.linalg.norm(b_centered))
        if denom <= 1e-6:
            return 1.0 if bool(np_module.allclose(a, b)) else 0.0
        return self._correlation_to_similarity(float(np_module.dot(a_centered, b_centered) / denom))

    @staticmethod
    def _correlation_to_similarity(score: float) -> float:
        """把相关系数 [-1, 1] 映射到相似度 [0, 1]，便于多特征融合。"""
        if score <= -1.0:
            return 0.0
        if score >= 1.0:
            return 1.0
        return max(0.0, min(1.0, (score + 1.0) / 2.0))

    def _edge_view(self, gray: Any, cv2_module: Any) -> Any:
        """生成边缘视图；OpenCV 精简测试替身缺少 Canny 时用灰度兜底。"""
        if hasattr(cv2_module, "Canny"):
            try:
                return cv2_module.Canny(gray, 50, 150)
            except Exception:
                pass
        return gray

    def _difference_hash(self, gray: Any, np_module: Any) -> Any:
        """生成 8x8 差分哈希，给装备大轮廓一个廉价签名。"""
        cv2_module = self._require_cv2()
        try:
            resized = cv2_module.resize(gray, (9, 8))
            return (resized[:, 1:] > resized[:, :-1]).reshape(-1)
        except Exception:
            return np_module.zeros((64,), dtype=bool)

    def _resolve_icon_rois(
        self,
        parent_roi: RoiRegion,
        card_type: str,
        explicit_roi: Optional[Sequence[int | float]],
    ) -> Tuple[RoiRegion, ...]:
        """把显式 ROI 或配置比例 ROI 转换成卡片内绝对 ROI。"""
        if explicit_roi is not None:
            return (self._child_roi(parent_roi, explicit_roi),)
        ratios = self.icon_ratios.get(card_type, self.icon_ratios["equipment"])
        return tuple(self._ratio_roi(parent_roi, ratio) for ratio in ratios)

    def _score_weights_from_config(self) -> Tuple[float, float, float, float, float]:
        """读取并归一化图标匹配多特征权重。"""
        structure = max(0.0, float(self.config.get("structure_weight", 0.65)))
        edge = max(0.0, float(self.config.get("edge_weight", 0.0)))
        hash_weight = max(0.0, float(self.config.get("hash_weight", 0.0)))
        region = max(0.0, float(self.config.get("region_weight", 0.0)))
        if "color_weight" in self.config:
            color = max(0.0, float(self.config.get("color_weight", 0.0)))
        else:
            color = max(0.0, 1.0 - structure - edge - hash_weight - region)
        total = structure + color + edge + hash_weight + region
        if total <= 1e-6:
            return 0.65, 0.35, 0.0, 0.0, 0.0
        return structure / total, color / total, edge / total, hash_weight / total, region / total

    def _child_roi(self, parent: RoiRegion, child_roi: Sequence[int | float]) -> RoiRegion:
        """解析相对卡片的图标 ROI；float 0~1 表示比例。"""
        values = tuple(child_roi)
        if len(values) != 4:
            raise ValueError("图标 ROI 必须包含 x, y, width, height。")
        if all(isinstance(item, float) and 0.0 <= item <= 1.0 for item in values):
            return self._ratio_roi(parent, values)  # type: ignore[arg-type]
        parent_x, parent_y, parent_width, parent_height = parent
        x, y, width, height = (int(round(float(item))) for item in values)
        return self._clamp_roi((parent_x + x, parent_y + y, width, height), parent_x, parent_y, parent_width, parent_height)

    def _ratio_roi(self, parent: RoiRegion, ratio: RatioRegion) -> RoiRegion:
        """把比例 ROI 转成绝对 ROI。"""
        parent_x, parent_y, parent_width, parent_height = parent
        rel_x, rel_y, rel_width, rel_height = ratio
        roi = (
            parent_x + int(round(parent_width * rel_x)),
            parent_y + int(round(parent_height * rel_y)),
            max(1, int(round(parent_width * rel_width))),
            max(1, int(round(parent_height * rel_height))),
        )
        return self._clamp_roi(roi, parent_x, parent_y, parent_width, parent_height)

    @staticmethod
    def _clamp_roi(roi: RoiRegion, parent_x: int, parent_y: int, parent_width: int, parent_height: int) -> RoiRegion:
        """确保图标 ROI 不越过卡片边界。"""
        x, y, width, height = roi
        max_x = parent_x + parent_width
        max_y = parent_y + parent_height
        x = min(max(parent_x, int(x)), max_x - 1)
        y = min(max(parent_y, int(y)), max_y - 1)
        width = max(1, min(int(width), max_x - x))
        height = max(1, min(int(height), max_y - y))
        return x, y, width, height

    @staticmethod
    def _full_image_roi(image: Any) -> RoiRegion:
        """返回整张图片 ROI。"""
        if image is None or not hasattr(image, "shape") or len(image.shape) < 2:
            raise ValueError("图像为空，无法确定图标区域。")
        return 0, 0, int(image.shape[1]), int(image.shape[0])

    def _validate_roi(self, image: Any, roi: Sequence[int]) -> RoiRegion:
        """检查 ROI 是否在图像边界内。"""
        if len(tuple(roi)) != 4:
            raise ValueError("图标 ROI 必须包含四个整数。")
        x, y, width, height = (int(item) for item in roi)
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError(f"图标 ROI 非法: {(x, y, width, height)}")
        if x + width > image_width or y + height > image_height:
            raise ValueError(f"图标 ROI 越界: {(x, y, width, height)} > {(image_width, image_height)}")
        return x, y, width, height

    @staticmethod
    def _resize(image: Any, target_size: Tuple[int, int], cv2_module: Any) -> Any:
        """按固定尺寸缩放，使不同来源图标能直接比较。"""
        width, height = target_size
        if int(image.shape[1]) == width and int(image.shape[0]) == height:
            return image.copy() if hasattr(image, "copy") else image
        return cv2_module.resize(image, (width, height))

    def _resolve_gallery_path(self, image_path: str) -> Path:
        """解析 equipment_images.csv 中可能是相对路径的图片路径。"""
        path = Path(image_path)
        return path if path.is_absolute() else self.project_root / path

    def _resolve_config_path(self, raw_path: str | Path) -> Path:
        """解析配置中的相对路径，统一以项目根目录为锚点。"""
        path = Path(raw_path)
        return path if path.is_absolute() else self.project_root / path

    @staticmethod
    def _load_default_matching_config(project_root: Path) -> Dict[str, Any]:
        """读取项目识别配置中的装备图库段；文件缺失时安全回退默认值。"""
        config_path = project_root / "config" / "recognition" / "roi_config.json"
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        matching = payload.get("equipment_icon_matching", {}) if isinstance(payload, dict) else {}
        return dict(matching) if isinstance(matching, dict) else {}

    def _dependency_warning(self) -> str:
        """生成依赖不可用提示。"""
        if self._get_cv2() is None:
            return "OpenCV(cv2) 不可用，无法执行装备图标匹配。"
        if self._get_np() is None:
            return "NumPy 不可用，无法执行装备图标匹配。"
        return ""

    def _require_cv2(self) -> Any:
        """获取 cv2 模块，不可用时抛出明确错误。"""
        cv2_module = self._get_cv2()
        if cv2_module is None:
            raise RuntimeError("OpenCV(cv2) 不可用。")
        return cv2_module

    def _require_np(self) -> Any:
        """获取 NumPy 模块，不可用时抛出明确错误。"""
        np_module = self._get_np()
        if np_module is None:
            raise RuntimeError("NumPy 不可用。")
        return np_module

    def _get_cv2(self) -> Optional[Any]:
        """优先使用测试注入的 cv2。"""
        if self._cv2 is not None:
            return self._cv2
        return _cv2

    def _get_np(self) -> Optional[Any]:
        """优先使用测试注入的 NumPy。"""
        if self._np is not None:
            return self._np
        return _np

    @classmethod
    def _icon_ratios_from_config(cls, raw: Any) -> Dict[str, Tuple[RatioRegion, ...]]:
        """读取配置中的装备卡/碎片卡图标比例 ROI。"""
        ratios = {key: tuple(value) for key, value in cls.DEFAULT_ICON_RATIOS.items()}
        if not isinstance(raw, dict):
            return ratios
        for key, values in raw.items():
            parsed: List[RatioRegion] = []
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, (list, tuple)) and len(item) == 4:
                    ratio = tuple(float(value) for value in item)
                    if all(0.0 <= value <= 1.0 for value in ratio) and ratio[2] > 0 and ratio[3] > 0:
                        parsed.append(ratio)  # type: ignore[arg-type]
            if parsed:
                ratios[str(key)] = tuple(parsed)
        return ratios

    @staticmethod
    def _target_size_from_config(raw: Any) -> Tuple[int, int]:
        """读取 target_size=[width,height]，非法时使用 96x96。"""
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            width, height = int(raw[0]), int(raw[1])
            if width > 0 and height > 0:
                return width, height
        return 96, 96

    @staticmethod
    def _region_grid_from_config(raw: Any) -> Tuple[int, int]:
        """读取分块评分网格，非法时使用 3x3。"""
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            rows, cols = int(raw[0]), int(raw[1])
            if rows > 0 and cols > 0:
                return rows, cols
        return 3, 3
