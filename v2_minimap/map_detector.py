# -*- coding: utf-8 -*-
"""
地图名检测模块 - OCR识别当前地图名，用于白名单/黑名单判断
功能：截取游戏画面中地图名区域，使用OCR识别地图名称
      如果当前地图在"不飞随机"列表中，则跳过传送
"""

import logging
import numpy as np
import cv2
from typing import List, Optional

logger = logging.getLogger(__name__)


class MapDetector:
    """地图名检测器 - 使用OCR识别当前地图名称"""

    def __init__(self):
        # 地图名区域（相对于客户区） 默认在左上角
        self.map_name_region = (300, 5, 200, 30)  # (x, y, width, height)
        # 不飞随机的安全地图列表
        self.no_teleport_maps: List[str] = ['盟重省', '安全区', '比奇省']
        # 是否启用
        self.enabled = False
        # 是否安装了Tesseract
        self.tesseract_available = False
        # 上次识别到的地图名
        self.last_map_name = ""
        self._check_tesseract()

    def _check_tesseract(self):
        """检查Tesseract是否可用"""
        try:
            import pytesseract
            # 尝试获取版本
            version = pytesseract.get_tesseract_version()
            if version:
                # 检查中文语言包
                langs = pytesseract.get_languages()
                self.tesseract_available = 'chi_sim' in langs
                if not self.tesseract_available:
                    logger.warning("Tesseract未安装中文语言包(chi_sim)，地图检测功能不可用")
                else:
                    logger.info(f"Tesseract v{version} 可用，地图检测功能已就绪")
        except Exception as e:
            self.tesseract_available = False
            logger.warning(f"Tesseract不可用，地图检测功能将跳过: {e}")

    def set_region(self, x: int, y: int, width: int, height: int):
        """设置地图名检测区域"""
        self.map_name_region = (x, y, width, height)

    def set_no_teleport_maps(self, maps: List[str]):
        """设置不飞随机的地图列表"""
        self.no_teleport_maps = [m.strip() for m in maps if m.strip()]

    def detect_map_name(self, full_screen: np.ndarray) -> Optional[str]:
        """检测当前地图名称

        Args:
            full_screen: 完整游戏画面（BGR格式）

        Returns:
            识别到的地图名，失败返回None
        """
        if not self.enabled or not self.tesseract_available:
            return None

        try:
            import pytesseract

            # 裁剪地图名区域
            x, y, w, h = self.map_name_region
            h_f, w_f = full_screen.shape[:2]
            # 确保不越界
            x = max(0, min(x, w_f - 1))
            y = max(0, min(y, h_f - 1))
            w = min(w, w_f - x)
            h = min(h, h_f - y)

            if w <= 0 or h <= 0:
                return None

            region = full_screen[y:y+h, x:x+w]

            # 图像预处理 - 提高OCR识别率
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            # 放大图像（小文字识别需要）
            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            # 二值化
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # OCR识别 - 只识别中文
            custom_config = r'--psm 7 -c tessedit_char_whitelist=省安市城区县镇乡村路大道口门湾河山岛洞谷关岭'
            text = pytesseract.image_to_string(binary, lang='chi_sim', config=custom_config)

            # 清理识别结果
            map_name = text.strip().replace('\n', '').replace(' ', '')
            if map_name:
                self.last_map_name = map_name
                logger.info(f"检测到地图: {map_name}")
                return map_name

            return None

        except ImportError:
            self.tesseract_available = False
            return None
        except Exception as e:
            logger.debug(f"地图名检测失败: {e}")
            return None

    def is_safe_map(self, map_name: str) -> bool:
        """判断是否是安全地图（不飞随机）

        Args:
            map_name: 检测到的地图名称

        Returns:
            True=安全地图，跳过传送
        """
        if not map_name:
            return False

        for safe_map in self.no_teleport_maps:
            if safe_map in map_name or map_name in safe_map:
                logger.info(f"当前地图 [{map_name}] 在保护列表中，跳过传送")
                return True
        return False

    def should_skip_teleport(self, full_screen: np.ndarray) -> bool:
        """综合判断是否应该跳过传送

        Args:
            full_screen: 完整游戏画面

        Returns:
            True=跳过本次传送
        """
        if not self.enabled or not self.tesseract_available:
            return False

        map_name = self.detect_map_name(full_screen)
        if map_name:
            return self.is_safe_map(map_name)
        return False