# -*- coding: utf-8 -*-
"""
传送员NPC自动传送模块
通过传送员NPC直接飞到目标地图，进图后自动找怪打怪
支持找怪打怪
支持找图识别NPC位置
"""

import time
import logging
import os
import key_sender
import screen_capture
import numpy as np
import cv2
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# 脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# NPC对话框设置
# 不同服的传送员菜单顺序不一样，改为按行号点击
DIALOG_CONFIG = {
    'first_row_y': 240,      # 第一行文字的Y坐标（相对客户区）
    'click_x': 400,          # 点击的X坐标（每行都一样）
    'row_height': 30,        # 每行高度（像素）
}


class NpcTeleporter:
    """NPC传送器 - 找传送员→对话→鼠标点按钮→飞图"""

    def __init__(self):
        self.enabled = False
        self.hwnd = None
        self.client_rect = None

        # 传送参数
        self.npc_find_timeout = 30  # 找NPC超时（秒）
        self.target_dungeon_row = 1  # 传送员对话框第几行

        # NPC找图模式: 'none' / 'image' / 'color' / 'auto'
        self.find_npc_mode = 'none'

        # 状态
        self.teleporting = False
        self._npc_walk_start = 0
        self._dialog_opened = False
        self._npc_found = False

        # 当前目的地
        self.target_map = None
        self.after_teleport_callback = None

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd
        if hwnd:
            self.client_rect = screen_capture.get_client_rect(hwnd)

    def capture_full_screen(self) -> Optional[np.ndarray]:
        """前台截取游戏窗口画面（兼容DirectX）"""
        return screen_capture.capture_client(self.hwnd)

    def find_npc_by_image(self, template_name: str = "npc_template.png") -> Optional[Tuple[int, int]]:
        """
        在游戏画面中找NPC模板图片（OpenCV模板匹配）
        template_name: NPC模板图片文件名（放在脚本同目录）
        返回: 找到的NPC客户区坐标 (client_x, client_y)，没找到返回None
        """
        screen = self.capture_full_screen()
        if screen is None:
            return None

        template_path = os.path.join(SCRIPT_DIR, template_name)
        if not os.path.exists(template_path):
            logger.warning(f"NPC模板图片不存在: {template_path}")
            return None

        template = cv2.imread(template_path)
        if template is None:
            logger.warning(f"无法读取模板图片: {template_path}")
            return None

        h, w = template.shape[:2]
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < 0.7:  # 匹配度阈值
            logger.info(f"未找到NPC，最高匹配度: {max_val:.2f}（需>=0.7）")
            return None

        # 返回模板中心位置
        cx = max_loc[0] + w // 2
        cy = max_loc[1] + h // 2
        logger.info(f"找到NPC！坐标({cx},{cy}) 匹配度={max_val:.2f}")
        return (cx, cy)

    def find_npc_by_color(self) -> Optional[Tuple[int, int]]:
        """
        用颜色检测找NPC头顶黄色名字（不依赖模板图片）
        传奇2 NPC名字通常是亮黄色（RGB 255,255,0附近）
        返回: 找到的NPC客户区坐标，没找到返回None
        """
        screen = self.capture_full_screen()
        if screen is None:
            return None

        # 转换为HSV，黄色在HSV空间中更容易分割
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        # 黄色范围
        lower = np.array([20, 100, 100])
        upper = np.array([30, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)

        # 找轮廓过滤噪声
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 20 < area < 500:  # NPC名字大小范围
                x, y, w, h = cv2.boundingRect(cnt)
                # 名字通常是横条（宽>高）
                if w > h and w < 200:
                    cx = x + w // 2
                    cy = y + h // 2
                    valid.append((cx, cy, area))

        if not valid:
            logger.info("未找到NPC（颜色检测）")
            return None

        # 返回面积最大的黄色区域（通常是最显眼的NPC名字）
        best = max(valid, key=lambda v: v[2])
        logger.info(f"颜色检测找到NPC！坐标({best[0]},{best[1]})")
        return (best[0], best[1])

    def send_key(self, key_char: str, duration: float = 0.1):
        """前台按键（keybd_event 模拟真实按键）"""
        key_sender.send_key(key_char, duration, self.hwnd)

    def send_key_enter(self):
        """按回车"""
        key_sender.send_key('Enter', 0.1, self.hwnd)
        time.sleep(0.3)

    def mouse_click_background(self, client_x: int, client_y: int):
        """
        前台鼠标点击（SetCursorPos + mouse_event 模拟真实点击）
        """
        key_sender.click_at(self.hwnd, client_x, client_y)

    def mouse_click_foreground(self, client_x: int, client_y: int):
        """
        前台鼠标点击（通过 key_sender.click_at）
        参数改为 client_x, client_y 客户区坐标，自动转屏幕坐标
        """
        key_sender.click_at(self.hwnd, client_x, client_y)

    def client_to_screen(self, client_x: int, client_y: int) -> Tuple[int, int]:
        """客户区坐标转屏幕坐标"""
        if not self.hwnd:
            return (0, 0)
        return key_sender.client_to_screen(self.hwnd, client_x, client_y)

    # ====== 传送流程 ======

    def start_teleport(self, callback=None):
        """
        开始传送流程
        callback: 传送完成后的回调函数
        """
        self.after_teleport_callback = callback
        self.teleporting = True
        self._npc_walk_start = time.time()
        self._dialog_opened = False
        logger.info(f"开始传送流程 -> 第{self.target_dungeon_row}行")
        return True

    def stop_teleport(self):
        """停止传送"""
        self.teleporting = False
        self._dialog_opened = False
        logger.info("停止传送流程")

    def update(self, coords=None) -> str:
        """
        每帧调用，驱动传送流程
        返回状态: 'idle' / 'finding_npc' / 'opening_dialog' / 'arrived' / 'failed'
        """
        if not self.enabled or not self.teleporting:
            return 'idle'

        if not self.target_dungeon_row or self.target_dungeon_row < 1:
            self.teleporting = False
            return 'idle'

        # 超时检查
        if time.time() - self._npc_walk_start > self.npc_find_timeout:
            logger.warning(f"传送超时（{self.npc_find_timeout}秒）")
            self.stop_teleport()
            return 'failed'

        # 阶段0: 找NPC（如果需要）
        if not self._npc_found and self.find_npc_mode != 'none':
            npc_pos = self._find_npc()
            if npc_pos:
                # 点击NPC位置
                cx, cy = npc_pos
                logger.info(f"点击NPC位置 ({cx}, {cy})")
                self.mouse_click_background(cx, cy)
                time.sleep(0.5)
                self._npc_found = True
                return 'finding_npc'
            else:
                # 没找到NPC，等待后重试
                logger.info("未找到NPC，等待1秒重试...")
                time.sleep(1)
                return 'finding_npc'

        # 阶段1: 按Enter打开对话框
        if not self._dialog_opened:
            self._open_npc_dialog()
            return 'opening_dialog'

        # 阶段2: 点击目的地按钮
        self._click_destination()
        return 'arrived'

    def _find_npc(self) -> Optional[Tuple[int, int]]:
        """找NPC位置，根据self.find_npc_mode选择方式"""
        if self.find_npc_mode == 'image' or self.find_npc_mode == 'auto':
            pos = self.find_npc_by_image()
            if pos:
                return pos

        if self.find_npc_mode == 'color' or self.find_npc_mode == 'auto':
            pos = self.find_npc_by_color()
            if pos:
                return pos

        return None

    def _open_npc_dialog(self):
        """打开NPC对话框 - 不需要坐标，直接按Enter"""
        logger.info("按Enter打开NPC对话框...")
        self.send_key_enter()
        time.sleep(0.3)
        self.send_key('Space', 0.1)
        time.sleep(0.3)
        self.send_key_enter()
        time.sleep(1.0)
        self._dialog_opened = True

    def _click_destination(self):
        """点击对话框第N行（按行号点击）"""
        row = self.target_dungeon_row
        click_x = DIALOG_CONFIG['click_x']
        click_y = DIALOG_CONFIG['first_row_y'] + (row - 1) * DIALOG_CONFIG['row_height']

        # 保存对话框截图（调试用）
        debug_img = self.capture_full_screen()
        if debug_img is not None:
            debug_path = os.path.join(SCRIPT_DIR, 'dialog_debug.png')
            cv2.imwrite(debug_path, debug_img)
            logger.info(f"已保存对话框截图: {debug_path}")

        # 后台鼠标点击
        logger.info(f"点击对话框第{row}行 ({click_x}, {click_y})")
        self.mouse_click_background(click_x, click_y)
        time.sleep(0.5)
        # 按Enter确认
        self.send_key_enter()
        time.sleep(1.0)

        # 等待传送
        logger.info("等待传送... (3秒)")
        time.sleep(3.0)

        self.teleporting = False
        self._dialog_opened = False
        logger.info(f"传送完成 -> {self.target_map}")

        if self.after_teleport_callback:
            self.after_teleport_callback()

    def _walk_toward(self, dx: int, dy: int):
        """朝目标方向走一步"""
        if abs(dx) > abs(dy):
            if dx > 0:
                self.send_key('D', 0.2)
            else:
                self.send_key('A', 0.2)
        else:
            if dy > 0:
                self.send_key('S', 0.2)
            else:
                self.send_key('W', 0.2)
        time.sleep(0.3)


class MonsterHunter:
    """
    自动找怪导航模块
    检测小地图红点 → 走过去 → 内挂自动打
    不手动攻击，只负责导航
    """

    def __init__(self):
        self.enabled = False
        self.hwnd = None

        # 导航设置
        self.nav_range = 6                # 走到红点多近算"到了"（小地图像素）
        self.walk_duration = 0.3
        self.walk_pause = 0.5

        # 状态
        self.is_hunting = False
        self.current_target = None

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd

    def send_key(self, key_char: str, duration: float = 0.1):
        """前台按键（keybd_event 模拟真实按键）"""
        key_sender.send_key(key_char, duration, self.hwnd)

    def navigate(self, red_dots: List[Tuple[int, int, int]],
             minimap_center_x: int, minimap_center_y: int) -> str:
        """
        导航到最近的红点（怪物）
        走到足够近后返回 'arrived'，让内挂自动打
        red_dots: [(x, y, area), ...]
        返回: 'idle' / 'walking' / 'arrived' / 'no_target'
        """
        if not self.enabled or not self.is_hunting:
            return 'idle'

        if not red_dots:
            return 'no_target'

        # 找最近的红点
        nearest = None
        nearest_dist = float('inf')
        for x, y, area in red_dots:
            dist = abs(x - minimap_center_x) + abs(y - minimap_center_y)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = (x, y, area)

        if not nearest:
            return 'no_target'

        tx, ty, area = nearest
        self.current_target = (tx, ty)

        # 计算方向
        dx = tx - minimap_center_x
        dy = ty - minimap_center_y

        logger.debug(f"导航: 目标({tx},{ty}) 距离={nearest_dist}")

        if nearest_dist <= self.nav_range:
            # 走到红点旁边了，让内挂自动打
            return 'arrived'
        else:
            # 走向目标
            self._walk_to(dx, dy)
            return 'walking'

    def _walk_to(self, dx: int, dy: int):
        """朝红点方向走"""
        if abs(dx) > abs(dy):
            if dx > 0:
                self.send_key('D', self.walk_duration)
            else:
                self.send_key('A', self.walk_duration)
        else:
            if dy > 0:
                self.send_key('S', self.walk_duration)
            else:
                self.send_key('W', self.walk_duration)
        time.sleep(self.walk_pause)

    def start_hunting(self):
        """开始导航模式"""
        self.is_hunting = True
        self.current_target = None
        logger.info("开始自动找怪导航")

    def stop_hunting(self):
        """停止导航"""
        self.is_hunting = False
        self.current_target = None
        logger.info("停止自动找怪导航")