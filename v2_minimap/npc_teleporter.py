# -*- coding: utf-8 -*-
"""
传送员NPC自动传送模块
通过传送员NPC直接飞到目标地图，进图后自动找怪打怪
"""

import time
import logging
import win32gui
import win32con
import win32
import win32api
import win32con
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# 传送员NPC坐标（95沉默安全区一般位置）
# 你可以在游戏里看坐标后修改这里
NPC_POSITIONS = {
    '盟重省': {'x': 330, 'y': 330, 'name': '传送员'},
    '比奇省': {'x': 280, 'y': 260, 'name': '传送员'},
    '土城':   {'x': 330, 'y': 330, 'name': '传送员'},
}

# 预设传送目的地
# 对话框里地图按钮的屏幕坐标（相对于游戏客户区左上角）
# 需要你实际量一下按钮位置后修改
PRESET_DESTINATIONS = {
    '石墓阵': {
        'click_x': 400,   # 对话框里"石墓"按钮的X坐标（相对客户区）
        'click_y': 250,   # 对话框里"石墓"按钮的Y坐标
        'wait_after': 3.0, # 传送后等待时间（秒）
    },
    '猪洞': {
        'click_x': 400,
        'click_y': 280,
        'wait_after': 3.0,
    },
    '蜈蚣洞': {
        'click_x': 400,
        'click_y': 310,
        'wait_after': 3.0,
    },
    '矿区': {
        'click_x': 400,
        'click_y': 340,
        'wait_after': 3.0,
    },
    '沃玛寺庙': {
        'click_x': 400,
        'click_y': 370,
        'wait_after': 3.0,
    },
    '祖玛寺庙': {
        'click_x': 400,
        'click_y': 400,
        'wait_after': 3.0,
    },
}


class NpcTeleporter:
    """NPC传送器 - 找传送员→对话→鼠标点按钮→飞图"""

    def __init__(self):
        self.enabled = False
        self.hwnd = None
        self.client_rect = None

        # 传送参数
        self.npc_x = 330       # NPC坐标X
        self.npc_y = 330       # NPC坐标Y
        self.npc_walk_range = 3  # 走到NPC旁边时的判定范围
        self.npc_find_timeout = 30  # 找NPC超时（秒）

        # 状态
        self.teleporting = False      # 正在传送中
        self._npc_walk_start = 0
        self._dialog_opened = False

        # 当前目的地
        self.target_map = None
        self.after_teleport_callback = None  # 传送完后回调

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd
        if hwnd:
            self.client_rect = win32gui.GetClientRect(hwnd)

    def send_key(self, key_char: str, duration: float = 0.1):
        """后台按键"""
        if not self.hwnd:
            return
        try:
            vk = win32api.VkKeyScan(key_char) & 0xFF
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(duration)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        except Exception as e:
            logger.debug(f"按键[{key_char}]: {e}")

    def send_key_enter(self):
        """按回车"""
        self.send_key('Enter', 0.1)
        time.sleep(0.3)

    def mouse_click_background(self, client_x: int, client_y: int):
        """
        后台鼠标点击（在游戏窗口内发送点击消息）
        client_x, client_y 是相对于客户区左上角的坐标
        """
        if not self.hwnd:
            return
        try:
            # 将坐标打包成LPARAM
            lparam = win32api.MAKELONG(client_x, client_y)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            logger.debug(f"后台点击: ({client_x}, {client_y})")
        except Exception as e:
            logger.debug(f"后台点击失败: {e}")

    def mouse_click_foreground(self, screen_x: int, screen_y: int):
        """
        前台鼠标点击（需要窗口在前台）
        如果后台点击无效，用这个方法
        """
        try:
            # 保存原光标位置
            old_pos = win32api.GetCursorPos()
            # 移动鼠标
            win32api.SetCursorPos((screen_x, screen_y))
            time.sleep(0.1)
            # 点击
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.1)
            # 移回原位
            win32api.SetCursorPos(old_pos)
        except Exception as e:
            logger.debug(f"前台点击失败: {e}")

    def client_to_screen(self, client_x: int, client_y: int) -> Tuple[int, int]:
        """客户区坐标转屏幕坐标"""
        if not self.hwnd:
            return (0, 0)
        return win32gui.ClientToScreen(self.hwnd, (client_x, client_y))

    # ====== 传送流程 ======

    def start_teleport(self, target_map: str, callback=None):
        """
        开始传送流程
        target_map: 目的地名称（如 '石墓阵'）
        callback: 传送完成后的回调函数
        """
        if target_map not in PRESET_DESTINATIONS:
            logger.warning(f"未知目的地: {target_map}")
            return False

        self.target_map = target_map
        self.after_teleport_callback = callback
        self.teleporting = True
        self._npc_walk_start = time.time()
        self._dialog_opened = False
        logger.info(f"开始传送流程 -> {target_map}")
        return True

    def stop_teleport(self):
        """停止传送"""
        self.teleporting = False
        self.target_map = None
        self._dialog_opened = False
        logger.info("停止传送流程")

    def update(self, coords: Optional[Tuple[int, int]] = None) -> str:
        """
        每帧调用，驱动传送流程
        返回状态: 'idle' / 'walking' / 'opening_dialog' / 'clicking_map' / 'arrived' / 'failed'
        """
        if not self.enabled or not self.teleporting:
            return 'idle'

        if not self.target_map:
            self.teleporting = False
            return 'idle'

        # 超时检查
        if time.time() - self._npc_walk_start > self.npc_find_timeout:
            logger.warning(f"传送超时（{self.npc_find_timeout}秒）")
            self.stop_teleport()
            return 'failed'

        # 阶段1: 走向NPC
        if not self._dialog_opened:
            if coords:
                # 计算到NPC的距离
                dx = self.npc_x - coords[0]
                dy = self.npc_y - coords[1]
                dist = abs(dx) + abs(dy)

                if dist <= self.npc_walk_range:
                    # 到NPC旁边了，按Enter对话
                    logger.info("已到达NPC位置，打开对话框")
                    self.send_key_enter()
                    time.sleep(0.5)
                    # 有些私服需要按Space
                    self.send_key('Space', 0.1)
                    time.sleep(0.5)
                    # 再按一次Enter确定
                    self.send_key_enter()
                    time.sleep(1.0)
                    self._dialog_opened = True
                    return 'opening_dialog'
                else:
                    # 朝NPC走
                    self._walk_toward(dx, dy)
                    return 'walking'
            else:
                # 没有坐标信息，先按Space试试
                self.send_key_enter()
                time.sleep(1.0)
                self._dialog_opened = True
                return 'opening_dialog'

        # 阶段2: 对话框已打开，点击地图按钮
        if self._dialog_opened:
            dest = PRESET_DESTINATIONS[self.target_map]
            click_x = dest['click_x']
            click_y = dest['click_y']

            # 先尝试后台点击
            self.mouse_click_background(click_x, click_y)
            time.sleep(0.5)

            # 再按Enter确认（有些服点完需要确认）
            self.send_key_enter()
            time.sleep(1.0)

            logger.info(f"已点击地图按钮: {self.target_map}")

            # 等待传送
            wait_time = dest['wait_after']
            logger.info(f"等待传送... ({wait_time}秒)")
            time.sleep(wait_time)

            # 完成传送
            self.teleporting = False
            self._dialog_opened = False
            logger.info(f"传送完成 -> {self.target_map}")

            # 调用回调
            if self.after_teleport_callback:
                self.after_teleport_callback()

            return 'arrived'

        return 'idle'

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
    自动找怪打怪模块
    通过检测小地图上的红点（怪物）自动走过去攻击
    支持多技能按键循环
    """

    def __init__(self):
        self.enabled = False
        self.hwnd = None

        # 攻击设置 - 支持多技能循环
        self.attack_keys = ['F1', 'F2']   # 技能按键列表
        self.attack_interval = 0.5         # 每个技能间隔
        self.skill_rotation_interval = 2.0 # 一轮技能打完后等待

        self.attack_range = 5              # 攻击范围（小地图像素）

        # 走路设置
        self.walk_duration = 0.3
        self.walk_pause = 0.5

        # 状态
        self.is_hunting = False
        self.current_target = None
        self.last_attack_time = 0
        self._skill_index = 0               # 当前技能索引

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd

    def send_key(self, key_char: str, duration: float = 0.1):
        if not self.hwnd:
            return
        try:
            vk = win32api.VkKeyScan(key_char) & 0xFF
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(duration)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        except Exception as e:
            logger.debug(f"按键[{key_char}]: {e}")

    def hunt(self, red_dots: List[Tuple[int, int, int]],
             minimap_center_x: int, minimap_center_y: int) -> str:
        """
        找怪打怪主逻辑
        red_dots: [(x, y, area), ...] 红点列表
        minimap_center_x/y: 小地图中心（玩家位置）
        返回: 'idle' / 'walking' / 'attacking' / 'no_target'
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

        # 计算方向（小地图上，上=北=W，右=东=D）
        dx = tx - minimap_center_x
        dy = ty - minimap_center_y
        dist = abs(dx) + abs(dy)

        logger.debug(f"猎怪: 目标({tx},{ty}) 距离={dist} 方向=({dx},{dy})")

        if dist <= self.attack_range:
            # 在攻击范围内，攻击
            self._attack()
            return 'attacking'
        else:
            # 走向目标
            self._walk_to(dx, dy)
            return 'walking'

    def _walk_to(self, dx: int, dy: int):
        """朝红点方向走"""
        # 优先走距离更长的方向
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

    def _attack(self):
        """攻击当前目标 - self.attack_keys 里多项技能轮流按 - """
        current_time = time.time()
        if current_time - self.last_attack_time < self.attack_interval:
            return

        if not self.attack_keys:
            return

        try:
            # 取当前技能
            key = self.attack_keys[self._skill_index]
            self._send_vk(key)

            self.last_attack_time = current_time
            logger.info(f"攻击 [{key}] (技能{self._skill_index+1}/{len(self.attack_keys)})")

            # 切换到下一个技能
            self._skill_index = (self._skill_index + 1) % len(self.attack_keys)
            if self._skill_index == 0:
                # 一轮技能打完，等待
                time.sleep(self.skill_rotation_interval)
        except Exception as e:
            logger.debug(f"攻击失败: {e}")

    def _send_vk(self, key: str):
        """根据键名发送虚拟按键"""
        if not self.hwnd:
            return
        # F1-F12
        if key.startswith('F') and key[1:].isdigit():
            f_num = int(key[1:])
            vk = win32con.VK_F1 + f_num - 1
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        # 数字键 0-9
        elif key.isdigit():
            vk = win32con.VK_0 + int(key)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        # 字母键 A-Z
        elif len(key) == 1 and key.isalpha():
            vk = win32api.VkKeyScan(key.upper()) & 0xFF
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        # 特殊键
        else:
            key_map = {
                'Enter': win32con.VK_RETURN,
                'Space': win32con.VK_SPACE,
                'Tab':   win32con.VK_TAB,
                'Esc':   win32con.VK_ESCAPE,
            }
            vk = key_map.get(key)
            if vk:
                win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
                time.sleep(0.05)
                win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)

    def start_hunting(self):
        """开始打怪模式"""
        self.is_hunting = True
        self.current_target = None
        logger.info("开始自动打怪")

    def stop_hunting(self):
        """停止打怪"""
        self.is_hunting = False
        self.current_target = None
        logger.info("停止自动打怪")