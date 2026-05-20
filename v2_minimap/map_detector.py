# -*- coding: utf-8 -*-
"""
地图名检测模块 - 模板匹配方式（无需Tesseract OCR）
用户首次在某地图点击"截图记录"，之后自动匹配
"""

import logging
import os
import cv2
import numpy as np
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_TEMPLATE_DIR = os.path.join(SCRIPT_DIR, 'map_templates')


class MapDetector:
    """地图名检测器 - 使用模板匹配识别当前地图名称"""

    def __init__(self):
        self.map_name_region = (300, 5, 200, 30)  # (x, y, width, height)
        self.no_teleport_maps: List[str] = ['盟重省', '安全区', '比奇省']
        self.enabled = False
        self.last_map_name = ""
        # 加载已保存的地图模板
        self._templates: dict = {}  # {map_name: template_img}
        self._load_templates()

    def set_region(self, x: int, y: int, width: int, height: int):
        """设置地图名检测区域"""
        self.map_name_region = (x, y, width, height)

    def set_no_teleport_maps(self, maps: List[str]):
        """设置不飞随机的地图列表"""
        self.no_teleport_maps = [m.strip() for m in maps if m.strip()]

    def _load_templates(self):
        """加载已保存的地图模板"""
        self._templates = {}
        if not os.path.exists(MAP_TEMPLATE_DIR):
            os.makedirs(MAP_TEMPLATE_DIR, exist_ok=True)
            return
        for fname in os.listdir(MAP_TEMPLATE_DIR):
            if fname.endswith('.png'):
                map_name = fname[:-4]  # 去掉.png
                path = os.path.join(MAP_TEMPLATE_DIR, fname)
                template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if template is not None:
                    self._templates[map_name] = template
                    logger.info(f"加载地图模板: {map_name}")

    def save_map_template(self, map_name: str, full_screen: np.ndarray) -> bool:
        """保存当前地图的模板截图"""
        os.makedirs(MAP_TEMPLATE_DIR, exist_ok=True)
        x, y, w, h = self.map_name_region
        h_f, w_f = full_screen.shape[:2]
        x = max(0, min(x, w_f - 1))
        y = max(0, min(y, h_f - 1))
        w = min(w, w_f - x)
        h = min(h, h_f - y)
        if w <= 0 or h <= 0:
            return False
        region = full_screen[y:y+h, x:x+w]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        path = os.path.join(MAP_TEMPLATE_DIR, f"{map_name}.png")
        cv2.imwrite(path, gray)
        self._templates[map_name] = gray
        logger.info(f"已保存地图模板: {map_name}")
        return True

    def delete_map_template(self, map_name: str):
        """删除地图模板"""
        path = os.path.join(MAP_TEMPLATE_DIR, f"{map_name}.png")
        if os.path.exists(path):
            os.remove(path)
        self._templates.pop(map_name, None)

    def get_saved_maps(self) -> List[str]:
        """获取已保存的地图列表"""
        return list(self._templates.keys())

    def detect_map_name(self, full_screen: np.ndarray,
                        threshold: float = 0.7) -> Optional[str]:
        """检测当前地图名称（模板匹配）

        Args:
            full_screen: 完整游戏画面（BGR格式）
            threshold: 匹配阈值（0~1），越高越严格

        Returns:
            匹配到的地图名，未匹配返回None
        """
        if not self.enabled or not self._templates:
            return None

        try:
            x, y, w, h = self.map_name_region
            h_f, w_f = full_screen.shape[:2]
            x = max(0, min(x, w_f - 1))
            y = max(0, min(y, h_f - 1))
            w = min(w, w_f - x)
            h = min(h, h_f - y)
            if w <= 0 or h <= 0:
                return None

            region = full_screen[y:y+h, x:x+w]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

            best_match = None
            best_score = 0

            for map_name, template in self._templates.items():
                # 模板大小可能不同，需要缩放
                t_h, t_w = template.shape
                if t_h == 0 or t_w == 0:
                    continue
                # 缩放到当前区域大小
                resized = cv2.resize(gray, (t_w, t_h))
                result = cv2.matchTemplate(resized, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, _ = cv2.minMaxLoc(result)

                if score > best_score:
                    best_score = score
                    best_match = map_name

            if best_match and best_score >= threshold:
                self.last_map_name = best_match
                logger.info(f"检测到地图: {best_match} (匹配度: {best_score:.2f})")
                return best_match

            return None

        except Exception as e:
            logger.debug(f"地图名检测失败: {e}")
            return None

    def is_safe_map(self, map_name: str) -> bool:
        """判断是否是安全地图（不飞随机）"""
        if not map_name:
            return False
        for safe_map in self.no_teleport_maps:
            if safe_map in map_name or map_name in safe_map:
                logger.info(f"当前地图 [{map_name}] 在保护列表中，跳过传送")
                return True
        return False

    def should_skip_teleport(self, full_screen: np.ndarray) -> bool:
        """综合判断是否应该跳过传送"""
        if not self.enabled or not self._templates:
            return False
        map_name = self.detect_map_name(full_screen)
        if map_name:
            return self.is_safe_map(map_name)
        return False