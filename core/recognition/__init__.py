"""OCR 识别相关核心接口。"""

from .equipment_card_reader import EquipmentCardDigitReader, FragmentQuantityReadResult
from .equipment_attribute_reranker import (
    AttributeRerankCandidate,
    AttributeRerankResult,
    EquipmentAttributeReranker,
    tokenize_attribute_text,
)
from .design_fragment_detector import (
    DesignFragmentCardCandidate,
    DesignFragmentDetectionResult,
    DesignFragmentDetector,
    get_design_fragment_detector,
)
from .equipment_icon_matcher import EquipmentIconCandidate, EquipmentIconMatcher, EquipmentIconMatchResult
from .equipment_name_resolver import (
    EquipmentNameCandidate,
    EquipmentNameResolver,
    EquipmentNameResolveResult,
    get_equipment_name_resolver,
    normalize_equipment_base_name,
    normalize_equipment_name,
)
from .filter_state_detector import (
    FilterStateDetector,
    FilterStateElement,
    FilterStateOption,
    FilterStateResult,
    get_filter_state_detector,
)
from .harbor_resource_detector import HarborResourceDetector, HarborResourceResult, get_harbor_resource_detector
from .ocr_engine import OcrEngine, OcrReadResult, OcrTextLine, normalize_number_text
from .ocr_task_api import OcrTaskApi, OcrTaskResult, get_ocr_task_api
from .scene_analyzer import SceneAnalyzer
from .template_matcher import TemplateMatch, TemplateMatcher, TemplateMatchResult
from .warehouse_label_detector import (
    WarehouseLabelDetection,
    WarehouseLabelDetector,
    WarehouseLabelResult,
    get_warehouse_label_detector,
)

__all__ = [
    "EquipmentCardDigitReader",
    "AttributeRerankCandidate",
    "AttributeRerankResult",
    "DesignFragmentCardCandidate",
    "DesignFragmentDetectionResult",
    "DesignFragmentDetector",
    "EquipmentAttributeReranker",
    "EquipmentIconCandidate",
    "EquipmentIconMatcher",
    "EquipmentIconMatchResult",
    "EquipmentNameCandidate",
    "EquipmentNameResolver",
    "EquipmentNameResolveResult",
    "FilterStateDetector",
    "FilterStateElement",
    "FilterStateOption",
    "FilterStateResult",
    "FragmentQuantityReadResult",
    "HarborResourceDetector",
    "HarborResourceResult",
    "OcrEngine",
    "OcrReadResult",
    "OcrTaskApi",
    "OcrTaskResult",
    "OcrTextLine",
    "SceneAnalyzer",
    "TemplateMatch",
    "TemplateMatchResult",
    "TemplateMatcher",
    "WarehouseLabelDetection",
    "WarehouseLabelDetector",
    "WarehouseLabelResult",
    "get_ocr_task_api",
    "get_design_fragment_detector",
    "get_filter_state_detector",
    "get_equipment_name_resolver",
    "get_harbor_resource_detector",
    "get_warehouse_label_detector",
    "normalize_equipment_base_name",
    "normalize_equipment_name",
    "normalize_number_text",
    "tokenize_attribute_text",
]
