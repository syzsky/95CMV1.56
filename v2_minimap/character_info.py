# -*- coding: utf-8 -*-
"""
角色信息读取模块
从已绑定的游戏窗口读取 HP、MP、等级等信息

三种方式：
1. 窗口标题 - GetWindowText() 获取窗口标题（可能有角色名）
2. 血条颜色检测 - 截图客户区左下角，读红色=HP，蓝色=MP
3. OCR读数字 - Tesseract识别画面上的数字（如 HP: 123/500）
"""

import time
import logging
import os
import win32gui
import win32con
import win32api
import win32ui
import numpy as np
import cv2
from typing import Optional, Tuple, Dict

logger = logging.getLogger(__name__)


class CharacterInfo:
    """角色信息读取器"""

    def __init__(self):
        self.hwnd = None
        self.client_rect = None

        # ========== HP 血条区域（相对于客户区） ==========
        # 默认值针对 1920×1080 全屏窗口
        # 底栏左侧：红条=HP，蓝条=MP
        self.hp_bar_x = 50      # 血条左上X
        self.hp_bar_y = 1000     # 血条左上Y
        self.hp_bar_w = 200     # 血条宽度
        self.hp_bar_h = 25      # 血条高度

        # ========== MP 蓝条区域 ==========
        self.mp_bar_x = 50
        self.mp_bar_y = 1030
        self.mp_bar_w = 200
        self.mp_bar_h = 25

        # ========== 等级/名字区域（左上角） ==========
        self.info_region_x = 10
        self.info_region_y = 10
        self.info_region_w = 200
        self.info_region_h = 50

        # ========== 缓存 ==========
        self.cached_info: Dict[str, any] = {
            'character_name': '',
            'level': 0,
            'hp_current': 0,
            'hp_max': 0,
            'hp_percent': 0.0,
            'mp_current': 0,
            'mp_max': 0,
            'mp_percent': 0.0,
            'window_title': '',
            'char_display': '',
        }
        self.last_update_time = 0

    def set_hwnd(self, hwnd: int):
        """绑定窗口"""
        self.hwnd = hwnd
        if hwnd:
            self.client_rect = win32gui.GetClientRect(hwnd)

    def _capture_client(self) -> Optional[np.ndarray]:
        """截图客户区（同 supply_manager 里的方法）"""
        if not self.hwnd or not self.client_rect:
            return None
        try:
            cw = self.client_rect[2] - self.client_rect[0]
            ch = self.client_rect[3] - self.client_rect[1]
            hwndDC = win32gui.GetWindowDC(self.hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, cw, ch)
            saveDC.SelectObject(saveBitMap)
            saveDC.BitBlt((0, 0), (cw, ch), mfcDC, (0, 0), win32con.SRCCOPY)
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype='uint8')
            img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwndDC)
            return img
        except Exception as e:
            logger.debug(f"截图失败: {e}")
            return None

    # ==================== 1. 窗口标题 ====================

    def read_window_title(self) -> str:
        """读取窗口标题（有时包含角色名）"""
        if not self.hwnd:
            return ''
        try:
            title = win32gui.GetWindowText(self.hwnd)
            self.cached_info['window_title'] = title
            return title
        except:
            return ''

    # ==================== 2. 血条颜色检测 ====================

    def detect_hp_bar(self, screen: np.ndarray) -> float:
        """
        检测 HP 血条百分比
        截取红色血条区域 → 红色像素占比 = 血量百分比
        返回: 0.0 ~ 1.0（0=空血, 1=满血）
        """
        h, w = screen.shape[:2]

        x1 = min(self.hp_bar_x, w - 10)
        y1 = min(self.hp_bar_y, h - 10)
        x2 = min(x1 + self.hp_bar_w, w)
        y2 = min(y1 + self.hp_bar_h, h)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        # 截取血条区域
        bar = screen[y1:y2, x1:x2]
        bar_h, bar_w = bar.shape[:2]

        # 红色检测：R 明显大于 G 和 B
        # 在 BGR 色彩空间中，红色像素 B小 G小 R大
        red_mask = cv2.inRange(bar,
            np.array([0, 0, 150]),      # 最低 BGR
            np.array([100, 100, 255])   # 最高 BGR
        )

        # 统计红色像素比例
        red_pixels = cv2.countNonZero(red_mask)
        total_pixels = bar_h * bar_w
        if total_pixels == 0:
            return 0.0

        ratio = red_pixels / total_pixels
        # 血条背景通常是黑色/灰色，所以红色比例就是血量
        # 也能用"红色像素的水平分布"更精确——先看最左边红色在哪
        # 简单方法：找红色像素最右边的位置
        red_cols = np.any(red_mask > 0, axis=0)  # 每列是否有红色
        if not np.any(red_cols):
            return 0.0

        rightmost_red = np.max(np.where(red_cols))
        percent = (rightmost_red + 1) / bar_w
        return min(max(percent, 0.0), 1.0)

    def detect_mp_bar(self, screen: np.ndarray) -> float:
        """
        检测 MP 蓝条百分比
        蓝色像素占比 = 魔法量百分比
        """
        h, w = screen.shape[:2]

        x1 = min(self.mp_bar_x, w - 10)
        y1 = min(self.mp_bar_y, h - 10)
        x2 = min(x1 + self.mp_bar_w, w)
        y2 = min(y1 + self.mp_bar_h, h)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        bar = screen[y1:y2, x1:x2]
        bar_h, bar_w = bar.shape[:2]

        # 蓝色检测：B 明显大于 R 和 G
        blue_mask = cv2.inRange(bar,
            np.array([150, 0, 0]),      # B大
            np.array([255, 100, 100])
        )

        blue_cols = np.any(blue_mask > 0, axis=0)
        if not np.any(blue_cols):
            return 0.0

        rightmost_blue = np.max(np.where(blue_cols))
        percent = (rightmost_blue + 1) / bar_w
        return min(max(percent, 0.0), 1.0)

    # ==================== 3. OCR 读数字 ====================

    def ocr_info_region(self, screen: np.ndarray) -> Dict[str, str]:
        """
        用 Tesseract OCR 读左上角信息（等级、名字、HP/MP数字）
        需要安装 tesseract 和 chi_sim 语言包
        返回: {'name': '', 'level': '', 'hp': '', 'mp': ''}
        """
        result = {'name': '', 'level': '', 'hp': '', 'mp': ''}
        h, w = screen.shape[:2]

        x1 = min(self.info_region_x, w - 10)
        y1 = min(self.info_region_y, h - 10)
        x2 = min(x1 + self.info_region_w, w)
        y2 = min(y1 + self.info_region_h, h)

        if x2 <= x1 or y2 <= y1:
            return result

        region = screen[y1:y2, x1:x2]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        try:
            import pytesseract
            text = pytesseract.image_to_string(binary, lang='chi_sim+eng',
                                               config='--psm 6')
            text = text.strip()
            logger.debug(f"OCR识别结果: {text!r}")
            result['raw'] = text
        except ImportError:
            logger.debug("pytesseract 未安装")
        except Exception as e:
            logger.debug(f"OCR出错: {e}")

        return result

    # ==================== 统一更新接口 ====================

    def update(self) -> Dict[str, any]:
        """
        更新所有角色信息
        返回: {
            'character_name': str,
            'level': int,
            'hp_percent': float,
            'mp_percent': float,
            'hp_current': int,
            'hp_max': int,
            'window_title': str,
        }
        """
        if not self.hwnd:
            return self.cached_info

        # 1. 读窗口标题
        self.read_window_title()

        # 2. 截图画面的客户区
        screen = self._capture_client()
        if screen is None:
            return self.cached_info

        # 3. 检测血条
        hp_pct = self.detect_hp_bar(screen)
        mp_pct = self.detect_mp_bar(screen)

        self.cached_info['hp_percent'] = round(hp_pct * 100, 1)
        self.cached_info['mp_percent'] = round(mp_pct * 100, 1)
        self.cached_info['char_display'] = self.get_info_text()

        # 4. OCR（台服可能有数字，先不强制）
        # ocr_data = self.ocr_info_region(screen)

        self.last_update_time = time.time()
        return self.cached_info

    def get_info_text(self) -> str:
        """生成一行信息文本，给 GUI 显示用"""
        info = self.cached_info
        parts = []

        title = info.get('window_title', '')
        if title:
            parts.append(title)

        hp = info.get('hp_percent', 0)
        mp = info.get('mp_percent', 0)
        parts.append(f"HP {hp:.0f}%")
        parts.append(f"MP {mp:.0f}%")

        return ' | '.join(parts)

    # ==================== 自动校准坐标 ====================

    def auto_calibrate(self, screen: np.ndarray = None):
        """
        自动校准血条位置
        在全屏画面中搜索红色水平长条（HP条）和蓝色水平长条（MP条）
        """
        if screen is None:
            screen = self._capture_client()
        if screen is None:
            logger.warning("无法截图，不能自动校准")
            return

        h, w = screen.shape[:2]
        logger.info(f"开始自动校准血条位置，画面 {w}x{h}")

        # 只在底部 1/3 区域搜索（血条在底部）
        search_y_start = h * 2 // 3
        search = screen[search_y_start:, :]

        # 搜索红色长条
        red_mask = cv2.inRange(search,
            np.array([0, 0, 150]),
            np.array([100, 100, 255])
        )

        # 找到所有红色轮廓
        contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        red_bars = []
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            # 长条：宽 > 50 且 高 < 40
            if bw > 50 and bh < 40 and bw > bh * 3:
                red_bars.append((x, y + search_y_start, bw, bh))

        if red_bars:
            # 取最左边的长条（通常是HP条）
            red_bars.sort(key=lambda r: r[0])
            bx, by, bw, bh = red_bars[0]
            self.hp_bar_x = bx
            self.hp_bar_y = by
            self.hp_bar_w = bw
            self.hp_bar_h = bh
            logger.info(f"自动校准 HP 条: x={bx} y={by} w={bw} h={bh}")

            # 如果还有第二个同区域的红色条，应该是MP条风格的红蓝显示
            # 否则找蓝色条
            if len(red_bars) > 1:
                bx2, by2, bw2, bh2 = red_bars[1]
                self.mp_bar_x = bx2
                self.mp_bar_y = by2
                self.mp_bar_w = bw2
                self.mp_bar_h = bh2
                logger.info(f"自动校准 MP 条（红色条2）: x={bx2} y={by2} w={bw2} h={bh2}")
        else:
            logger.warning("未找到红色血条，请手动设置坐标")

        # 搜索蓝色长条（MP条）
        blue_mask = cv2.inRange(search,
            np.array([150, 0, 0]),
            np.array([255, 100, 100])
        )
        blue_contours, _ = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blue_bars = []
        for cnt in blue_contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw > 50 and bh < 40 and bw > bh * 3:
                blue_bars.append((x, y + search_y_start, bw, bh))

        if blue_bars:
            blue_bars.sort(key=lambda r: r[0])
            bx, by, bw, bh = blue_bars[0]
            self.mp_bar_x = bx
            self.mp_bar_y = by
            self.mp_bar_w = bw
            self.mp_bar_h = bh
            logger.info(f"自动校准 MP 条: x={bx} y={by} w={bw} h={bh}")


# ==================== 快速测试 ====================
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
    print("=" * 50)
    print("角色信息读取模块 - 快速测试")
    print("=" * 50)

    ci = CharacterInfo()

    # 找游戏窗口
    def find_game():
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    try:
                        rect = win32gui.GetClientRect(hwnd)
                        w = rect[2] - rect[0]
                        h = rect[3] - rect[1]
                        if w > 100 and h > 100:
                            windows.append((hwnd, title, w, h))
                    except:
                        pass
            return True

        windows = []
        win32gui.EnumWindows(callback, windows)

        if not windows:
            print("没有找到任何可见窗口")
            return None

        print(f"\n找到 {len(windows)} 个窗口:")
        for i, (hwnd, title, w, h) in enumerate(windows):
            print(f"  [{i}] {title} ({w}x{h})")

        choice = input("\n选择窗口编号（回车=0）: ").strip()
        if not choice:
            choice = '0'
        idx = int(choice)
        if 0 <= idx < len(windows):
            return windows[idx][0]
        return None

    hwnd = find_game()
    if hwnd:
        ci.set_hwnd(hwnd)
        title = ci.read_window_title()
        print(f"\n✅ 窗口标题: {title}")

        print("\n正在自动校准血条位置...")
        ci.auto_calibrate()

        print("\n读取角色信息...")
        info = ci.update()
        print(f"  窗口标题: {info.get('window_title', '')}")
        print(f"  HP: {info.get('hp_percent', 0):.0f}%")
        print(f"  MP: {info.get('mp_percent', 0):.0f}%")
        print(f"\n{ci.get_info_text()}")
    else:
        print("未选择窗口")