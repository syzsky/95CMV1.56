# -*- coding: utf-8 -*-
"""
掉线/死亡检测模块 - 监测游戏状态，检测掉线或死亡
功能：
1. 追踪人物坐标变化，检测卡死/掉线
2. 检测死亡状态（复活点坐标/画面变化）
3. 使用winsound发出声音提醒
"""

import time
import logging
import numpy as np
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# 尝试导入winsound（仅Windows可用）
try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False
    logger.warning("winsound不可用（非Windows环境），声音提醒功能将跳过")


class StatusMonitor:
    """游戏状态监控器 - 检测掉线、死亡"""

    def __init__(self):
        # 是否启用
        self.enabled = False

        # 坐标追踪
        self.last_coords: Optional[Tuple[int, int]] = None
        self.coord_frozen_count = 0       # 坐标未变化计数
        self.coord_frozen_threshold = 30  # 连续30次坐标不变=可能掉线（约15秒）

        # 死亡检测
        self.death_check_count = 0
        self.death_detected = False

        # 检查间隔（秒）
        self.check_interval = 0.5

        # 声音提醒控制
        self.alert_sound_enabled = True
        self.last_alert_time = 0
        self.alert_cooldown = 60  # 同一类型提醒至少间隔60秒

        # 状态标志
        self.is_disconnected = False
        self.is_dead = False
        self.alert_message = ""

        # 坐标区域（默认在右上角小地图旁边，或底部状态栏）
        # 需要用户根据实际游戏调整
        self.coord_region = (10, 10, 150, 25)  # (x, y, width, height)

        # 死亡检测 - 检查复活点附近的坐标特征
        # 盟重省复活点大约坐标 (330, 330)，不同私服可能不同
        self.respawn_coords = (330, 330)
        self.respawn_tolerance = 20

        # 上一次完整的状态报告时间
        self.last_status_time = 0

    def set_coord_region(self, x: int, y: int, width: int, height: int):
        """设置坐标检测区域"""
        self.coord_region = (x, y, width, height)

    def sound_alert(self, message: str):
        """发出声音提醒

        使用winsound发出3次急促的蜂鸣声，持续2秒
        """
        if not self.alert_sound_enabled:
            return

        current_time = time.time()
        if current_time - self.last_alert_time < self.alert_cooldown:
            return

        self.last_alert_time = current_time
        self.alert_message = message
        logger.warning(f"⚠️ 声音提醒: {message}")

        if WINSOUND_AVAILABLE:
            try:
                # 急促蜂鸣 3次
                for _ in range(3):
                    winsound.Beep(880, 300)  # 880Hz, 300ms
                    time.sleep(0.2)
                # 稍长提示音
                winsound.Beep(660, 500)
                logger.info(f"声音提醒已播放: {message}")
            except Exception as e:
                logger.error(f"播放声音失败: {e}")
        else:
            # 非Windows环境用终端提示
            print(f"\a\a\a ** {message} **")

    def detect_coordinates(self, full_screen: np.ndarray) -> Optional[Tuple[int, int]]:
        """从游戏画面中检测人物坐标

        使用OCR识别画面中的坐标文字（如 "123:456"）
        需要Tesseract支持

        Args:
            full_screen: 完整游戏画面

        Returns:
            (x, y) 坐标元组，失败返回None
        """
        if full_screen is None:
            return None

        try:
            import pytesseract

            x, y, w, h = self.coord_region
            h_f, w_f = full_screen.shape[:2]
            x = max(0, min(x, w_f - 1))
            y = max(0, min(y, h_f - 1))
            w = min(w, w_f - x)
            h = min(h, h_f - y)

            if w <= 0 or h <= 0:
                return None

            region = full_screen[y:y+h, x:x+w]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            custom_config = r'--psm 7 -c tessedit_char_whitelist=0123456789:'
            text = pytesseract.image_to_string(binary, lang='eng', config=custom_config)

            # 解析 "123:456" 格式
            text = text.strip().replace(' ', '')
            if ':' in text:
                parts = text.split(':')
                if len(parts) >= 2:
                    # 取前两个数字部分
                    try:
                        coord_x = int(''.join(c for c in parts[0] if c.isdigit()))
                        coord_y = int(''.join(c for c in parts[1] if c.isdigit()))
                        return (coord_x, coord_y)
                    except (ValueError, IndexError):
                        pass
            return None

        except ImportError:
            return None
        except Exception:
            return None

    def check_death_screen(self, full_screen: np.ndarray) -> bool:
        """检测是否死亡

        通过检测画面是否有死亡提示/复活界面来判断
        策略：
        1. 检查画面中是否有"复活"、"死亡"等文字（需OCR）
        2. 检查画面是否有明显的弹窗/界面变化

        Args:
            full_screen: 完整游戏画面

        Returns:
            True=检测到死亡
        """
        if full_screen is None:
            return False

        try:
            import pytesseract

            # 检测画面中央区域（通常是弹窗出现的位置）
            h, w = full_screen.shape[:2]
            center_region = full_screen[h//3:2*h//3, w//4:3*w//4]
            gray = cv2.cvtColor(center_region, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # 识别关键词
            text = pytesseract.image_to_string(binary, lang='chi_sim', config='--psm 6')
            death_keywords = ['复活', '死亡', '已经死亡', '确定', '回城']
            for kw in death_keywords:
                if kw in text:
                    logger.warning(f"检测到死亡提示: 画面中包含'{kw}'")
                    return True

            return False

        except ImportError:
            return False
        except Exception:
            return False

    def check_screen_frozen(self) -> bool:
        """检查画面是否可能卡死（辅助判断）

        通过检测画面底部状态栏的像素变化来判断
        如果连续多次截图没有变化，可能已经掉线

        注意：此方法比较粗略，仅供参考
        """
        # 这个方法需要保存上一帧画面进行比较
        # 为了简化，用坐标检测来做主要判断
        return False

    def update(self, full_screen: Optional[np.ndarray]) -> Tuple[bool, str, str]:
        """更新状态检测

        Args:
            full_screen: 完整游戏画面（可以为None，跳过画面分析）

        Returns:
            (状态变化标志, 状态类型, 消息)
            状态类型: 'disconnect', 'death', 'normal', 'respawn'
        """
        if not self.enabled:
            return False, 'normal', ''

        result_changed = False
        result_type = 'normal'
        result_msg = ''

        # 1. 坐标检测
        coords = None
        if full_screen is not None:
            coords = self.detect_coordinates(full_screen)

        if coords:
            # 比较坐标是否变化
            if self.last_coords:
                if coords == self.last_coords:
                    self.coord_frozen_count += 1
                else:
                    # 检查是否刚从复活点出来
                    if self.is_dead:
                        # 坐标发生变化，说明已复活
                        self.is_dead = False
                        self.death_detected = False
                        result_changed = True
                        result_type = 'respawn'
                        result_msg = '角色已复活'
                        logger.info("角色已复活，继续监控")
                    self.coord_frozen_count = 0

            self.last_coords = coords

            # 掉线检测：坐标长时间未变化
            if self.coord_frozen_count >= self.coord_frozen_threshold and not self.is_disconnected:
                self.is_disconnected = True
                result_changed = True
                result_type = 'disconnect'
                result_msg = f'⚠️ 疑似掉线！坐标已 {self.coord_frozen_count * self.check_interval:.0f} 秒未变化'
                self.sound_alert(result_msg)

            # 复活检测：坐标在复活点附近
            if self.is_dead:
                rx, ry = self.respawn_coords
                cx, cy = coords
                if abs(cx - rx) <= self.respawn_tolerance and abs(cy - ry) <= self.respawn_tolerance:
                    self.is_dead = False
                    self.death_detected = False
                    result_changed = True
                    result_type = 'respawn'
                    result_msg = '检测到角色在复活点附近，疑似已复活'
                    logger.info(result_msg)

        else:
            # 如果连续无法获取坐标，可能是掉线
            if self.last_coords:
                self.coord_frozen_count += 1
                if self.coord_frozen_count >= self.coord_frozen_threshold and not self.is_disconnected:
                    self.is_disconnected = True
                    result_changed = True
                    result_type = 'disconnect'
                    result_msg = '⚠️ 疑似掉线！无法读取坐标'
                    self.sound_alert(result_msg)

        # 2. 死亡检测
        if full_screen is not None and not self.is_dead:
            if self.check_death_screen(full_screen):
                self.is_dead = True
                self.death_detected = True
                result_changed = True
                result_type = 'death'
                result_msg = '⚠️ 角色死亡！请尽快处理'
                self.sound_alert(result_msg)

        # 3. 掉线恢复检测
        if self.is_disconnected and coords is not None:
            # 再次读到坐标，说明可能恢复连接
            self.is_disconnected = False
            self.coord_frozen_count = 0
            result_changed = True
            result_type = 'normal'
            result_msg = '连接可能已恢复'

        # 定期报告状态
        current_time = time.time()
        if result_changed or current_time - self.last_status_time > 300:  # 每5分钟报告一次
            self.last_status_time = current_time
            if not result_changed and self.last_coords:
                logger.info(f"状态正常 - 坐标: {self.last_coords}")
            elif not result_changed:
                logger.info("状态正常")

        return result_changed, result_type, result_msg

    def reset(self):
        """重置状态"""
        self.last_coords = None
        self.coord_frozen_count = 0
        self.is_disconnected = False
        self.is_dead = False
        self.death_detected = False