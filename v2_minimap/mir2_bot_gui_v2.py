# -*- coding: utf-8 -*-
"""
传奇2自动挂机脚本 V2 - 图形界面版本
功能: 检测小地图黄点（其他玩家），自动使用随机传送石
特性: 后台截图，窗口被遮挡也能正常工作
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import time
import keyboard
import win32gui
import win32con
import win32api
import win32ui
import logging
import configparser
import os
import numpy as np
import cv2
from datetime import datetime
from typing import Optional, Tuple, List
from PIL import Image, ImageTk
import ctypes

# 新功能模块
from npc_teleporter import NpcTeleporter, MonsterHunter
from bot_engine import SmartEngine, BotState
from class_skills import ClassSkillManager
from auto_nav import AutoNavigator
from map_detector import MapDetector
from status_monitor import StatusMonitor
from character_info import CharacterInfo

# 获取脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, 'mir2_bot_v2.log')
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'bot_config_v2.ini')

class MinimapDetector:
    """小地图黄点检测器"""

    def __init__(self):
        self.yellow_lower_rgb = np.array([250, 250, 0])
        self.yellow_upper_rgb = np.array([255, 255, 5])
        self.min_contour_area = 1

    def detect(self, image: np.ndarray) -> List[Tuple[int, int, int]]:
        """精确检测RGB(255,255,0)的黄点"""
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        yellow_mask = cv2.inRange(rgb, self.yellow_lower_rgb, self.yellow_upper_rgb)
        contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        yellow_dots = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= self.min_contour_area:
                M = cv2.moments(contour)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    yellow_dots.append((cx, cy, int(area)))
        return yellow_dots

class Mir2AutoBotV2:
    """传奇2自动挂机机器人 V2 - 后台截图版"""

    def __init__(self, config_file: str = None, log_callback=None):
        self.running = False
        self.paused = False
        self.log_callback = log_callback

        if config_file is None:
            config_file = CONFIG_FILE

        self.minimap_detector = MinimapDetector()
        self.config = self._load_config(config_file)

        self.hwnd = None
        self.window_rect = None
        self.client_rect = None
        self.client_offset = (0, 0)
        self.minimap_region = None
        self.window_title = ""
        self.last_teleport_time = 0
        self.teleport_cooldown = self.config.getfloat('Teleport', 'cooldown', fallback=4.0)

        # ===== 新功能模块 =====
        # 地图白名单检测器
        self.map_detector = MapDetector()
        self._init_map_detector()

        # 掉线/死亡检测器
        self.status_monitor = StatusMonitor()
        self._init_status_monitor()

        # ===== NPC传送器 =====
        self.npc_teleporter = NpcTeleporter()
        self.npc_teleporter.enabled = self.config.getboolean('NpcTeleport', 'enabled', fallback=False)
        self.npc_teleporter.find_npc_mode = self.config.get('NpcTeleport', 'find_npc_mode', fallback='none')
        self.npc_teleporter.target_dungeon_row = self.config.getint('NpcTeleport', 'target_dungeon_row', fallback=1)

        # ===== 怪物猎手 =====
        self.monster_hunter = MonsterHunter()
        self.monster_hunter.enabled = self.config.getboolean('MonsterHunt', 'enabled', fallback=False)

        # ===== 自动回收器 =====
        from auto_recycler import AutoRecycler
        self.recycler = AutoRecycler()
        self.recycler.enabled = self.config.getboolean('AutoRecycle', 'enabled', fallback=False)
        self.recycler.bag_key = self.config.get('AutoRecycle', 'bag_key', fallback='F9')
        self.recycler.recycle_interval = self.config.getint('AutoRecycle', 'recycle_interval', fallback=180)

        # ===== 自动补给 =====
        from supply_manager import SupplyManager
        self.supply = SupplyManager()
        self.supply.enabled = self.config.getboolean('Supply', 'enabled', fallback=False)
        self.supply.buy_row = self.config.getint('Supply', 'buy_row', fallback=1)
        self.supply.repair_row = self.config.getint('Supply', 'repair_row', fallback=2)
        self.supply.slot1_x = self.config.getint('Supply', 'slot1_x', fallback=770)
        self.supply.slot1_y = self.config.getint('Supply', 'slot1_y', fallback=980)
        self.supply.slot1_w = self.config.getint('Supply', 'slot1_w', fallback=40)
        self.supply.slot1_h = self.config.getint('Supply', 'slot1_h', fallback=40)

        # ===== 职业技能（全职业） =====
        self.class_skills = ClassSkillManager()
        self.class_skills.enabled = self.config.getboolean('ClassSkills', 'enabled', fallback=False)
        self.class_skills.class_name = self.config.get('ClassSkills', 'class_name', fallback='taoist')

        # ===== 自动寻路 =====
        self.auto_nav = AutoNavigator()
        self.auto_nav.enabled = self.config.getboolean('AutoNav', 'enabled', fallback=False)

        # ===== 状态机引擎 =====
        self.engine = None  # 在 run_with_window 时初始化

        # 全屏截图缓存
        self._full_screen_cache = None
        self._full_screen_time = 0

        self.stats = {
            'yellow_dots_detected': 0,
            'teleports_used': 0,
            'detection_runs': 0,
            'start_time': None
        }

        self._log("Bot V2 (Background Capture) initialized")

    def _log(self, message: str, level: str = "INFO"):
        """记录日志"""
        if self.log_callback:
            self.log_callback(message, level)

    def _load_config(self, config_file: str) -> configparser.ConfigParser:
        """加载配置文件"""
        config = configparser.ConfigParser()

        default_config = {
            'Game': {
                'window_title': '九五沉默',
            },
            'Minimap': {
                'enabled': 'true',
                'offset_x': '10',
                'offset_y': '10',
                'width': '150',
                'height': '150',
                'from_right': 'true',
            },
            'Detection': {
                'enabled': 'true',
                'detection_interval': '0.3',
                'min_contour_area': '1',
                'debug': 'false',
            },
            'Teleport': {
                'enabled': 'true',
                'teleport_key': '2',
                'cooldown': '4.0',
            },
            'YellowColor': {
                'r_lower': '250',
                'r_upper': '255',
                'g_lower': '250',
                'g_upper': '255',
                'b_lower': '0',
                'b_upper': '5',
            },
            'MapDetection': {
                'enabled': 'false',
                'map_name_x': '300',
                'map_name_y': '5',
                'map_name_width': '200',
                'map_name_height': '30',
                'no_teleport_maps': '盟重省,安全区,比奇省',
                'respawn_x': '330',
                'respawn_y': '330',
                'respawn_tolerance': '20',
            },
            'StatusMonitor': {
                'enabled': 'false',
                'check_interval': '0.5',
                'coord_frozen_threshold': '30',
                'alert_sound_enabled': 'true',
                'coord_region_x': '10',
                'coord_region_y': '10',
                'coord_region_width': '150',
                'coord_region_height': '25',
            },
            'ClassSkills': {
                'enabled': 'false',
                'class_name': 'taoist',
                'hp_potion_key': '1',
                'hp_potion_interval': '3',
                'hp_potion_enabled': 'true',
                'mp_potion_key': '2',
                'mp_potion_interval': '3',
                'mp_potion_enabled': 'false',
                'summon_key': '3',
                'summon_interval': '300',
                'summon_enabled': 'true',
                'heal_key': '4',
                'heal_interval': '15',
                'heal_enabled': 'true',
                'buff_key': '5',
                'buff_interval': '120',
                'buff_enabled': 'true',
            },
            'AutoNav': {
                'enabled': 'false',
                'arrive_distance': '5',
                'nav_timeout': '120',
            }
        }

        if os.path.exists(config_file):
            config.read(config_file, encoding='utf-8')
            self._log(f"Config loaded: {config_file}")
        else:
            for section, settings in default_config.items():
                config.add_section(section)
                for key, value in settings.items():
                    config.set(section, key, value)
            with open(config_file, 'w', encoding='utf-8') as f:
                config.write(f)
            self._log(f"Config created: {config_file}")

        self._update_detector_params(config)
        return config

    def _update_detector_params(self, config: configparser.ConfigParser):
        """更新检测器参数"""
        r_lower = config.getint('YellowColor', 'r_lower', fallback=250)
        r_upper = config.getint('YellowColor', 'r_upper', fallback=255)
        g_lower = config.getint('YellowColor', 'g_lower', fallback=250)
        g_upper = config.getint('YellowColor', 'g_upper', fallback=255)
        b_lower = config.getint('YellowColor', 'b_lower', fallback=0)
        b_upper = config.getint('YellowColor', 'b_upper', fallback=5)

        self.minimap_detector.yellow_lower_rgb = np.array([r_lower, g_lower, b_lower])
        self.minimap_detector.yellow_upper_rgb = np.array([r_upper, g_upper, b_upper])
        self.minimap_detector.min_contour_area = config.getint('Detection', 'min_contour_area', fallback=1)

    def _init_map_detector(self):
        try:
            section = self.config['MapDetection']
            self.map_detector.enabled = section.getboolean('enabled', fallback=False)
            if self.map_detector.enabled:
                x = section.getint('map_name_x', fallback=300)
                y = section.getint('map_name_y', fallback=5)
                w = section.getint('map_name_width', fallback=200)
                h = section.getint('map_name_height', fallback=30)
                self.map_detector.set_region(x, y, w, h)
                maps_str = section.get('no_teleport_maps', fallback='盟重省,安全区,比奇省')
                maps_list = [m.strip() for m in maps_str.replace('，', ',').split(',') if m.strip()]
                self.map_detector.set_no_teleport_maps(maps_list)
        except Exception as e:
            self._log(f"Init map detector: {e}", "WARNING")

    def _init_status_monitor(self):
        try:
            section = self.config['StatusMonitor']
            self.status_monitor.enabled = section.getboolean('enabled', fallback=False)
            if self.status_monitor.enabled:
                self.status_monitor.check_interval = section.getfloat('check_interval', fallback=0.5)
                self.status_monitor.coord_frozen_threshold = section.getint('coord_frozen_threshold', fallback=30)
                self.status_monitor.alert_sound_enabled = section.getboolean('alert_sound_enabled', fallback=True)
                cx = section.getint('coord_region_x', fallback=10)
                cy = section.getint('coord_region_y', fallback=10)
                cw = section.getint('coord_region_width', fallback=150)
                ch = section.getint('coord_region_height', fallback=25)
                self.status_monitor.set_coord_region(cx, cy, cw, ch)
                map_section = self.config['MapDetection']
                rx = map_section.getint('respawn_x', fallback=330)
                ry = map_section.getint('respawn_y', fallback=330)
                rt = map_section.getint('respawn_tolerance', fallback=20)
                self.status_monitor.respawn_coords = (rx, ry)
                self.status_monitor.respawn_tolerance = rt
        except Exception as e:
            self._log(f"Init status monitor: {e}", "WARNING")

    def _init_class_skills(self):
        """从配置加载职业技能设置"""
        try:
            section = self.config['ClassSkills']
            self.class_skills.enabled = section.getboolean('enabled', fallback=False)
            if self.class_skills.enabled:
                self.class_skills.class_name = section.get('class_name', fallback='taoist')
                self._log(f"职业技能已启用（{self.class_skills.class_name}）")
        except Exception as e:
            self._log(f"职业技能初始化: {e}", "WARNING")

    def find_game_window(self) -> bool:
        """查找游戏窗口"""
        window_title = self.config.get('Game', 'window_title', fallback='九五沉默')
        possible_titles = [window_title, 'Legend of Mir2', '传奇']

        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                for possible_title in possible_titles:
                    if possible_title.lower() in title.lower():
                        try:
                            client_rect = win32gui.GetClientRect(hwnd)
                            client_width = client_rect[2] - client_rect[0]
                            client_height = client_rect[3] - client_rect[1]
                            if client_width > 0 and client_height > 0:
                                windows.append((hwnd, title))
                        except:
                            pass
            return True

        windows = []
        win32gui.EnumWindows(callback, windows)

        if windows:
            self.hwnd, self.window_title = windows[0]
            self._init_window_info()
            if self.hwnd:
                self.class_skills.set_hwnd(self.hwnd)
                self.npc_teleporter.set_hwnd(self.hwnd)
                self.monster_hunter.set_hwnd(self.hwnd)
                self.recycler.set_hwnd(self.hwnd)
                self.supply.set_hwnd(self.hwnd)
            return True
        else:
            self._log("Game window not found", "ERROR")
            return False

    def _init_window_info(self):
        """初始化窗口信息"""
        self.window_rect = win32gui.GetWindowRect(self.hwnd)
        self.client_rect = win32gui.GetClientRect(self.hwnd)
        client_left, client_top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        window_left, window_top = self.window_rect[0], self.window_rect[1]
        self.client_offset = (client_left - window_left, client_top - window_top)
        self._log(f"Game window found: {self.window_title}")
        self._calculate_minimap_region()

    def _calculate_minimap_region(self):
        """计算小地图区域"""
        if not self.client_rect:
            return
        client_width = self.client_rect[2] - self.client_rect[0]
        offset_x = self.config.getint('Minimap', 'offset_x', fallback=10)
        offset_y = self.config.getint('Minimap', 'offset_y', fallback=10)
        width = self.config.getint('Minimap', 'width', fallback=150)
        height = self.config.getint('Minimap', 'height', fallback=150)
        from_right = self.config.getboolean('Minimap', 'from_right', fallback=True)

        if from_right:
            x = client_width - width - offset_x
        else:
            x = offset_x
        y = offset_y
        self.minimap_region = (x, y, width, height)
        self._log(f"Minimap region: {self.minimap_region}")

    def capture_minimap(self) -> Optional[np.ndarray]:
        """后台捕获小地图 - 使用Win32 API"""
        if not self.client_rect or not self.minimap_region:
            return None

        try:
            client_width = self.client_rect[2] - self.client_rect[0]
            client_height = self.client_rect[3] - self.client_rect[1]

            # 获取窗口DC
            hwndDC = win32gui.GetWindowDC(self.hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            # 创建位图
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, client_width, client_height)
            saveDC.SelectObject(saveBitMap)

            img = None
            
            # 方法1: 尝试PrintWindow
            # 使用BitBlt进行截图（比PrintWindow更可靠）

            saveDC.BitBlt((0, 0), (client_width, client_height), mfcDC, (0, 0), win32con.SRCCOPY)

            bmpinfo = saveBitMap.GetInfo()

            bmpstr = saveBitMap.GetBitmapBits(True)

            img = np.frombuffer(bmpstr, dtype='uint8')

            img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)

            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            minimap_x, minimap_y, minimap_w, minimap_h = self.minimap_region
            minimap = img[minimap_y:minimap_y+minimap_h, minimap_x:minimap_x+minimap_w]

            # 清理资源
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwndDC)

            return minimap

        except Exception as e:
            self._log(f"Background capture failed: {e}", "ERROR")
            return None

    def capture_full_screen(self) -> Optional[np.ndarray]:
        """后台捕获完整客户区画面"""
        if not self.client_rect:
            return None

        try:
            client_width = self.client_rect[2] - self.client_rect[0]
            client_height = self.client_rect[3] - self.client_rect[1]

            hwndDC = win32gui.GetWindowDC(self.hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, client_width, client_height)
            saveDC.SelectObject(saveBitMap)

            # 使用BitBlt进行截图（比PrintWindow更可靠）
            saveDC.BitBlt((0, 0), (client_width, client_height), mfcDC, (0, 0), win32con.SRCCOPY)

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
            self._log(f"Full screen capture failed: {e}", "ERROR")
            return None


    def detect_yellow_dots(self, minimap_image: np.ndarray) -> Tuple[bool, List[Tuple[int, int, int]]]:
        """检测小地图中的黄点"""
        if not self.config.getboolean('Detection', 'enabled', fallback=True):
            return False, []

        yellow_dots = self.minimap_detector.detect(minimap_image)

        if yellow_dots:
            self.stats['yellow_dots_detected'] += len(yellow_dots)
            self._log(f"Detected {len(yellow_dots)} yellow dot(s) - other player(s)!")
            return True, yellow_dots

        return False, []

    def use_teleport(self, full_screen=None):
        """使用随机传送石 - 使用PostMessage发送按键（含地图白名单检查）"""
        if not self.config.getboolean('Teleport', 'enabled', fallback=True):
            return

        # 地图白名单检查
        if self.map_detector.enabled and full_screen is not None:
            if self.map_detector.should_skip_teleport(full_screen):
                self._log("安全地图，跳过传送")
                return

        current_time = time.time()
        self.teleport_cooldown = self.config.getfloat('Teleport', 'cooldown', fallback=4.0)

        if current_time - self.last_teleport_time < self.teleport_cooldown:
            return

        teleport_key = self.config.get('Teleport', 'teleport_key', fallback='2')

        try:
            vk_code = win32api.VkKeyScan(teleport_key)
            vk_code = vk_code & 0xFF

            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk_code, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk_code, 0)

            self.last_teleport_time = current_time
            self.stats['teleports_used'] += 1
            self._log(f"Teleport used (key: {teleport_key})")
        except Exception as e:
            self._log(f"Teleport failed: {e}", "ERROR")

    def run(self):
        """启动挂机脚本（自动找窗口）"""
        self._log("启动挂机 V2（后台截图模式）...")

        if not self.find_game_window():
            self._log("找不到游戏窗口，退出", "ERROR")
            return

        self.running = True
        self.stats['start_time'] = datetime.now()
        self._init_engine()
        self._log("挂机已启动，F10可停止")
        self._run_loop()

    def run_with_window(self):
        """用已选窗口启动（GUI调用）"""
        self._log("挂机已启动，F10可停止")
        self._init_engine()
        self._run_loop()

    def _init_engine(self):
        """初始化状态机引擎"""
        use_engine = (self.npc_teleporter.enabled or self.monster_hunter.enabled)
        if use_engine:
            self.engine = SmartEngine(self)
            self._log("智能引擎已启用")
        else:
            self.engine = None

    def _run_loop(self):
        """主运行循环"""
        try:
            while self.running:
                if self.paused:
                    time.sleep(0.1)
                    continue

                # 检查窗口
                if not win32gui.IsWindow(self.hwnd):
                    self._log("游戏窗口已关闭", "WARNING")
                    break

                # 使用智能引擎
                if self.engine:
                    self.engine.update()
                    self.stats['current_state'] = self.engine.state.name
                else:
                    # 原始简单循环（只检测黄点传送）
                    self._run_simple_loop()

                detection_interval = self.config.getfloat('Detection', 'detection_interval', fallback=0.3)
                time.sleep(detection_interval)

        except Exception as e:
            self._log(f"错误: {e}", "ERROR")
        finally:
            self.stop()

    def _run_simple_loop(self):
        """简单循环：只检测黄点+自动技能"""
        minimap = self.capture_minimap()
        status_counter = getattr(self, '_status_counter', 0) + 1
        self._status_counter = status_counter

        if minimap is not None:
            self.stats['detection_runs'] += 1
            has_players, yellow_dots = self.detect_yellow_dots(minimap)

            full_screen = None
            check_interval = max(1, int(getattr(self.status_monitor, 'check_interval', 0.5) / 0.3))
            if self.map_detector.enabled or self.status_monitor.enabled:
                if status_counter % check_interval == 0 or has_players:
                    full_screen = self.capture_full_screen()

            if has_players:
                self.use_teleport(full_screen)

            # 状态监控
            if self.status_monitor.enabled and status_counter % check_interval == 0:
                changed, s_type, msg = self.status_monitor.update(full_screen)
                if changed:
                    self._log(f"[状态] {msg}", "WARNING")

        # 职业技能
        if self.class_skills.enabled:
            self.class_skills.tick()

    def stop(self):
        """停止挂机脚本"""
        self.running = False
        self._log("Bot V2 stopped")

    def pause(self):
        """暂停/继续"""
        self.paused = not self.paused
        status = "已暂停" if self.paused else "已恢复"
        self._log(f"挂机 {status}")

class MinimapAdjustWindow:
    """小地图范围调整窗口"""

    def __init__(self, parent, config, on_save_callback=None, config_file=None):
        self.parent = parent
        self.config = config
        self.on_save_callback = on_save_callback
        self.config_file = config_file if config_file else CONFIG_FILE

        self.window = tk.Toplevel(parent)
        self.window.title("调整小地图范围")
        self.window.geometry("900x650")

        self.full_screen_image = None
        self.preview_image = None
        self.canvas_image = None

        self._create_widgets()
        self._capture_screen()

    def _create_widgets(self):
        """创建界面组件"""
        control_frame1 = ttk.Frame(self.window, padding="10")
        control_frame1.pack(fill=tk.X)

        ttk.Label(control_frame1, text="偏移 X:").grid(row=0, column=0, padx=5, sticky='e')
        self.offset_x_var = tk.StringVar(value=self.config.get('Minimap', 'offset_x', fallback='10'))
        ttk.Entry(control_frame1, textvariable=self.offset_x_var, width=8).grid(row=0, column=1, padx=5)

        ttk.Label(control_frame1, text="偏移 Y:").grid(row=0, column=2, padx=5, sticky='e')
        self.offset_y_var = tk.StringVar(value=self.config.get('Minimap', 'offset_y', fallback='10'))
        ttk.Entry(control_frame1, textvariable=self.offset_y_var, width=8).grid(row=0, column=3, padx=5)

        ttk.Label(control_frame1, text="宽度:").grid(row=0, column=4, padx=5, sticky='e')
        self.width_var = tk.StringVar(value=self.config.get('Minimap', 'width', fallback='150'))
        ttk.Entry(control_frame1, textvariable=self.width_var, width=8).grid(row=0, column=5, padx=5)

        ttk.Label(control_frame1, text="高度:").grid(row=0, column=6, padx=5, sticky='e')
        self.height_var = tk.StringVar(value=self.config.get('Minimap', 'height', fallback='150'))
        ttk.Entry(control_frame1, textvariable=self.height_var, width=8).grid(row=0, column=7, padx=5)

        self.from_right_var = tk.BooleanVar(value=self.config.getboolean('Minimap', 'from_right', fallback=True))
        ttk.Checkbutton(control_frame1, text="从右边", variable=self.from_right_var).grid(row=0, column=8, padx=10)

        control_frame2 = ttk.Frame(self.window, padding="5")
        control_frame2.pack(fill=tk.X)

        ttk.Button(control_frame2, text="预览", command=self._preview, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(control_frame2, text="保存", command=self._save, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(control_frame2, text="刷新画面", command=self._capture_screen, width=10).pack(side=tk.LEFT, padx=10)

        preset_frame = ttk.Frame(self.window, padding="5")
        preset_frame.pack(fill=tk.X)

        ttk.Label(preset_frame, text="预设:").pack(side=tk.LEFT, padx=5)
        ttk.Button(preset_frame, text="右上 150x150", command=lambda: self._apply_preset(10, 10, 150, 150, True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_frame, text="右上 160x160", command=lambda: self._apply_preset(5, 5, 160, 160, True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_frame, text="右上 130x130", command=lambda: self._apply_preset(15, 15, 130, 130, True)).pack(side=tk.LEFT, padx=2)

        self.canvas = tk.Canvas(self.window, bg='black')
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.status_label = ttk.Label(self.window, text="点击「刷新画面」捕获游戏画面")
        self.status_label.pack(fill=tk.X, padx=10, pady=5)

    def _capture_screen(self):
        """后台捕获游戏画面"""
        self.status_label.config(text="正在后台捕获游戏画面...")

        temp_bot = Mir2AutoBotV2()
        if temp_bot.find_game_window():
            self.full_screen_image = temp_bot.capture_full_screen()
            self.client_rect = temp_bot.client_rect
            if self.full_screen_image is not None:
                self._preview()
                self.status_label.config(text="截图成功（后台模式）")
            else:
                self.status_label.config(text="截图失败")
        else:
            self.status_label.config(text="未找到游戏窗口")

    def _apply_preset(self, offset_x, offset_y, width, height, from_right):
        """应用预设"""
        self.offset_x_var.set(str(offset_x))
        self.offset_y_var.set(str(offset_y))
        self.width_var.set(str(width))
        self.height_var.set(str(height))
        self.from_right_var.set(from_right)
        self._preview()

    def _preview(self):
        """预览小地图区域"""
        if self.full_screen_image is None:
            messagebox.showwarning("提示", "请先捕获游戏画面")
            return

        try:
            offset_x = int(self.offset_x_var.get())
            offset_y = int(self.offset_y_var.get())
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            from_right = self.from_right_var.get()

            client_width = self.client_rect[2] - self.client_rect[0]

            if from_right:
                x = client_width - width - offset_x
            else:
                x = offset_x
            y = offset_y

            preview = self.full_screen_image.copy()
            cv2.rectangle(preview, (x, y), (x + width, y + height), (0, 255, 0), 2)
            cv2.putText(preview, f"小地图: {width}x{height}", (x, y - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            preview_rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
            h, w = preview_rgb.shape[:2]

            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            if canvas_width < 100:
                canvas_width = 780
            if canvas_height < 100:
                canvas_height = 450

            scale = min(canvas_width / w, canvas_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)

            preview_resized = cv2.resize(preview_rgb, (new_w, new_h))
            self.preview_image = Image.fromarray(preview_resized)
            self.canvas_image = ImageTk.PhotoImage(self.preview_image)

            self.canvas.delete("all")
            self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=self.canvas_image)

            self.status_label.config(text=f"Minimap region: x={x}, y={y}, w={width}, h={height}")

        except ValueError as e:
            messagebox.showerror("错误", f"参数无效: {e}")

    def _save(self):
        """保存设置"""
        try:
            config = configparser.ConfigParser()
            config.read(self.config_file, encoding='utf-8')

            config.set('Minimap', 'offset_x', self.offset_x_var.get())
            config.set('Minimap', 'offset_y', self.offset_y_var.get())
            config.set('Minimap', 'width', self.width_var.get())
            config.set('Minimap', 'height', self.height_var.get())
            config.set('Minimap', 'from_right', str(self.from_right_var.get()).lower())

            # 保存到实例专用的配置文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                config.write(f)

            if self.config:
                self.config.read(self.config_file, encoding='utf-8')

            self.status_label.config(text="设置已保存!")
            messagebox.showinfo("成功", f"设置已保存到 {os.path.basename(self.config_file)}")

            if self.on_save_callback:
                self.on_save_callback()
            self.window.destroy()

        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

class BotGUI:
    """图形界面"""
    
    # 类变量，用于生成唯一的实例ID
    _instance_counter = 0

    def __init__(self):
        # 生成唯一的实例ID
        BotGUI._instance_counter += 1
        self.instance_id = BotGUI._instance_counter
        
        self.root = tk.Tk()
        self.root.title(f"九五沉默自动挂机 V2 (实例 {self.instance_id})")
        self.root.geometry("720x780")
        self.root.resizable(True, True)

        self.bot = None
        self.bot_thread = None
        
        # 角色信息读取器
        self.character_info = CharacterInfo()
        
        # 为每个实例创建独立的配置文件
        self.config_file = self._get_instance_config_file()
        self.config = self._load_config()

        # 窗口显示/隐藏状态
        self.window_visible = True
        self.toggle_hotkey = 'F9'  # 呼出/隐藏热键

        self._create_widgets()
        
        # 注册热键
        keyboard.add_hotkey('F10', self.stop_bot)
        keyboard.add_hotkey(self.toggle_hotkey, self.toggle_window)
    
    def _get_instance_config_file(self):
        """获取实例专用的配置文件路径"""
        if self.instance_id == 1:
            # 第一个实例使用默认配置文件
            return CONFIG_FILE
        else:
            # 其他实例使用独立的配置文件
            return os.path.join(SCRIPT_DIR, f'bot_config_v2_instance{self.instance_id}.ini')

    def _load_config(self):
        """加载配置"""
        config = configparser.ConfigParser()
        
        # 如果实例配置文件不存在，从默认配置文件复制
        if not os.path.exists(self.config_file) and os.path.exists(CONFIG_FILE):
            import shutil
            shutil.copy(CONFIG_FILE, self.config_file)
        
        if os.path.exists(self.config_file):
            config.read(self.config_file, encoding='utf-8')

        return config

    def _create_widgets(self):
        """创建界面组件（中文）"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="九五沉默自动挂机 V2",
                                font=('Arial', 14, 'bold'))
        title_label.pack(pady=2)

        desc_label = ttk.Label(main_frame,
                               text="后台截图 | 小地图红点导航+内挂打怪 | NPC传送 | 职业技能 | 黄点躲避 | 单向巡逻",
                               font=('Arial', 9))
        desc_label.pack(pady=1)

        # 热键提示
        hotkey_label = ttk.Label(main_frame,
                                text="F9=隐藏窗口  |  F10=停止挂机",
                                font=('Arial', 9, 'italic'),
                                foreground='gray')
        hotkey_label.pack(pady=2)

        # ===== 窗口选择 =====
        window_frame = ttk.LabelFrame(main_frame, text="游戏窗口", padding="5")
        window_frame.pack(fill=tk.X, pady=3)

        window_row = ttk.Frame(window_frame)
        window_row.pack(fill=tk.X, pady=2)

        ttk.Label(window_row, text="选择窗口:").pack(side=tk.LEFT, padx=5)
        self.window_combo = ttk.Combobox(window_row, width=40, state='readonly')
        self.window_combo.pack(side=tk.LEFT, padx=5)
        ttk.Button(window_row, text="刷新", command=self.refresh_windows, width=6).pack(side=tk.LEFT, padx=5)

        self.window_info_label = ttk.Label(window_frame, text="未选择窗口", font=('Arial', 9))
        self.window_info_label.pack(anchor=tk.W, padx=5)

        # ===== 控制按钮 =====
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=5)

        self.start_btn = ttk.Button(control_frame, text="开始", command=self.start_bot, width=10)
        self.start_btn.pack(side=tk.LEFT, padx=3)

        self.stop_btn = ttk.Button(control_frame, text="停止", command=self.stop_bot, width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=3)

        self.pause_btn = ttk.Button(control_frame, text="暂停", command=self.pause_bot, width=10, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=3)

        self.test_btn = ttk.Button(control_frame, text="测试检测", command=self.test_detection, width=10)
        self.test_btn.pack(side=tk.LEFT, padx=3)

        self.adjust_btn = ttk.Button(control_frame, text="调整小地图", command=self.adjust_minimap, width=10)
        self.adjust_btn.pack(side=tk.LEFT, padx=3)

        # ===== 功能开关（新） =====
        features_frame = ttk.LabelFrame(main_frame, text="功能开关", padding="8")
        features_frame.pack(fill=tk.X, pady=3)

        # --- NPC传送 ---
        npc_row = ttk.Frame(features_frame)
        npc_row.pack(fill=tk.X, pady=1)
        self.npc_enabled_var = tk.BooleanVar(
            value=self.config.getboolean('NpcTeleport', 'enabled', fallback=False))
        ttk.Checkbutton(npc_row, text="NPC传送", variable=self.npc_enabled_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(npc_row, text="模式:").pack(side=tk.LEFT, padx=2)
        self.npc_mode_var = tk.StringVar(
            value=self.config.get('NpcTeleport', 'find_npc_mode', fallback='color'))
        ttk.Combobox(npc_row, textvariable=self.npc_mode_var, values=['none', 'color', 'image', 'auto'],
                     width=8, state='readonly').pack(side=tk.LEFT, padx=2)
        ttk.Label(npc_row, text="行数:").pack(side=tk.LEFT, padx=2)
        self.npc_row_var = tk.StringVar(
            value=self.config.get('NpcTeleport', 'target_dungeon_row', fallback='1'))
        ttk.Spinbox(npc_row, from_=1, to=20, textvariable=self.npc_row_var, width=4).pack(side=tk.LEFT, padx=2)

        # --- 自动找怪导航 ---
        hunt_row = ttk.Frame(features_frame)
        hunt_row.pack(fill=tk.X, pady=1)
        self.hunt_enabled_var = tk.BooleanVar(
            value=self.config.getboolean('MonsterHunt', 'enabled', fallback=False))
        ttk.Checkbutton(hunt_row, text="自动找怪（小地图红点导航）", variable=self.hunt_enabled_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(hunt_row, text="（内挂负责打怪）", font=('Arial', 8, 'italic'), foreground='gray').pack(side=tk.LEFT, padx=2)

        # --- 自动回收 ---
        recycle_row = ttk.Frame(features_frame)
        recycle_row.pack(fill=tk.X, pady=1)
        self.recycle_enabled_var = tk.BooleanVar(
            value=self.config.getboolean('AutoRecycle', 'enabled', fallback=False))
        ttk.Checkbutton(recycle_row, text="自动回收背包", variable=self.recycle_enabled_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(recycle_row, text="背包键:", font=('Arial', 9)).pack(side=tk.LEFT, padx=2)
        self.recycle_bag_key_var = tk.StringVar(
            value=self.config.get('AutoRecycle', 'bag_key', fallback='F9'))
        ttk.Entry(recycle_row, textvariable=self.recycle_bag_key_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(recycle_row, text="（截取回收按钮图片 = recycle_button.png）",
                  font=('Arial', 8, 'italic'), foreground='gray').pack(side=tk.LEFT, padx=5)

        # --- 自动补给 ---
        supply_row = ttk.Frame(features_frame)
        supply_row.pack(fill=tk.X, pady=1)
        self.supply_enabled_var = tk.BooleanVar(
            value=self.config.getboolean('Supply', 'enabled', fallback=False))
        ttk.Checkbutton(supply_row, text="自动补给（买药+修装备）", variable=self.supply_enabled_var).pack(side=tk.LEFT, padx=5)

        # --- 职业技能 ---
        skill_row = ttk.Frame(features_frame)
        skill_row.pack(fill=tk.X, pady=1)
        self.skill_enabled_var = tk.BooleanVar(
            value=self.config.getboolean('ClassSkills', 'enabled', fallback=False))
        ttk.Checkbutton(skill_row, text="职业技能", variable=self.skill_enabled_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(skill_row, text="职业:").pack(side=tk.LEFT, padx=2)
        self.class_var = tk.StringVar(
            value=self.config.get('ClassSkills', 'class_name', fallback='taoist'))
        ttk.Combobox(skill_row, textvariable=self.class_var, values=['warrior', 'wizard', 'taoist'],
                     width=8, state='readonly').pack(side=tk.LEFT, padx=2)

        # --- 自动寻路 ---
        nav_row = ttk.Frame(features_frame)
        nav_row.pack(fill=tk.X, pady=1)
        self.nav_enabled_var = tk.BooleanVar(
            value=self.config.getboolean('AutoNav', 'enabled', fallback=False))
        ttk.Checkbutton(nav_row, text="自动寻路", variable=self.nav_enabled_var).pack(side=tk.LEFT, padx=5)

        ttk.Button(nav_row, text="保存功能", command=self.save_features_settings, width=8).pack(side=tk.RIGHT, padx=5)

        # ===== 状态 =====
        status_frame = ttk.LabelFrame(main_frame, text="状态", padding="5")
        status_frame.pack(fill=tk.X, pady=3)

        self.status_label = ttk.Label(status_frame, text="状态：未启动", font=('Arial', 10))
        self.status_label.pack(anchor=tk.W)

        self.stats_label = ttk.Label(status_frame, text="检测: 0 | 黄点: 0 | 传送: 0", font=('Arial', 9))
        self.stats_label.pack(anchor=tk.W)

        self.minimap_label = ttk.Label(status_frame, text="小地图: 未设置", font=('Arial', 9))
        self.minimap_label.pack(anchor=tk.W)

        # 角色信息
        char_frame = ttk.Frame(status_frame)
        char_frame.pack(fill=tk.X, pady=2)
        self.char_info_label = ttk.Label(char_frame, text="角色: 未读取", font=('Arial', 9))
        self.char_info_label.pack(side=tk.LEFT)
        self.calibrate_char_btn = ttk.Button(char_frame, text="校准信息", command=self.calibrate_character_info, width=10)
        self.calibrate_char_btn.pack(side=tk.RIGHT, padx=5)

        # ===== 运行日志 =====
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=3)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ===== 快速设置 =====
        settings_frame = ttk.LabelFrame(main_frame, text="快速设置", padding="8")
        settings_frame.pack(fill=tk.X, pady=3)

        row1_frame = ttk.Frame(settings_frame)
        row1_frame.pack(fill=tk.X, pady=2)

        ttk.Label(row1_frame, text="传送键:").pack(side=tk.LEFT, padx=5)
        self.teleport_key_var = tk.StringVar(value=self.config.get("Teleport", "teleport_key", fallback="2"))
        ttk.Entry(row1_frame, textvariable=self.teleport_key_var, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Label(row1_frame, text="冷却(秒):").pack(side=tk.LEFT, padx=5)
        self.cooldown_var = tk.StringVar(value=self.config.get("Teleport", "cooldown", fallback="4.0"))
        ttk.Entry(row1_frame, textvariable=self.cooldown_var, width=6).pack(side=tk.LEFT, padx=2)

        ttk.Label(row1_frame, text="检测间隔(秒):").pack(side=tk.LEFT, padx=5)
        self.interval_var = tk.StringVar(value=self.config.get("Detection", "detection_interval", fallback="0.3"))
        ttk.Entry(row1_frame, textvariable=self.interval_var, width=6).pack(side=tk.LEFT, padx=2)

        ttk.Button(row1_frame, text="保存设置", command=self.save_settings, width=10).pack(side=tk.LEFT, padx=10)

        self._update_minimap_label()

        # 存储找到的窗口
        self.found_windows = []

        # 初始刷新窗口列表
        self.root.after(500, self.refresh_windows)


    def refresh_windows(self):
        """刷新游戏窗口列表"""
        self.log("正在扫描游戏窗口...")
        self.found_windows = []
        
        window_title = self.config.get('Game', 'window_title', fallback='九五沉默')
        possible_titles = [window_title, 'Legend of Mir2', '传奇']

        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                for possible_title in possible_titles:
                    if possible_title.lower() in title.lower():
                        try:
                            client_rect = win32gui.GetClientRect(hwnd)
                            client_width = client_rect[2] - client_rect[0]
                            client_height = client_rect[3] - client_rect[1]
                            if client_width > 0 and client_height > 0:
                                windows.append((hwnd, title))
                        except:
                            pass
            return True

        win32gui.EnumWindows(callback, self.found_windows)

        # 更新下拉框
        window_names = [f"[{hwnd}] {title}" for hwnd, title in self.found_windows]
        self.window_combo['values'] = window_names
        
        if window_names:
            self.window_combo.current(0)
            self._on_window_selected()
            self.log(f"找到 {len(self.found_windows)} 个游戏窗口")
        else:
            self.window_combo.set('')
            self.window_info_label.config(text="未找到游戏窗口")
            self.log("未找到游戏窗口", "WARNING")

    def _on_window_selected(self, event=None):
        """窗口选择变化时的回调"""
        selection = self.window_combo.current()
        if 0 <= selection < len(self.found_windows):
            hwnd, title = self.found_windows[selection]
            try:
                client_rect = win32gui.GetClientRect(hwnd)
                client_size = f"{client_rect[2]-client_rect[0]}x{client_rect[3]-client_rect[1]}"
                self.window_info_label.config(text=f"HWND: {hwnd} | Size: {client_size}")
            except:
                self.window_info_label.config(text=f"HWND: {hwnd}")

    def _update_minimap_label(self):
        """更新小地图区域显示"""
        offset_x = self.config.get('Minimap', 'offset_x', fallback='10')
        offset_y = self.config.get('Minimap', 'offset_y', fallback='10')
        width = self.config.get('Minimap', 'width', fallback='150')
        height = self.config.get('Minimap', 'height', fallback='150')
        from_right = self.config.get('Minimap', 'from_right', fallback='true')
        self.minimap_label.config(text=f"小地图: offset=({offset_x},{offset_y}), 大小={width}x{height}, from_right={from_right}")

    def log(self, message: str, level: str = "INFO"):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)

    def update_status(self, status: str):
        """更新状态"""
        self.status_label.config(text=f"状态：{status}")

    def update_stats(self):
        """更新统计"""
        if self.bot:
            stats = self.bot.stats
            state = stats.get('current_state', 'IDLE')
            self.stats_label.config(
                text=f"检测: {stats['detection_runs']} | 黄点: {stats['yellow_dots_detected']} | 红点: {stats.get('red_dots_detected', 0)} | 传送: {stats['teleports_used']} | 状态: {state}"
            )

    def start_bot(self):
        """启动机器人"""
        selection = self.window_combo.current()
        if selection < 0 or selection >= len(self.found_windows):
            messagebox.showwarning("提示", "请先选择游戏窗口")
            return

        hwnd, title = self.found_windows[selection]
        self.log(f"启动挂机，窗口: {title}")
        
        # 创建bot实例
        self.bot = Mir2AutoBotV2(config_file=self.config_file, log_callback=self.log)

        # 设置选中的窗口
        self.bot.hwnd = hwnd
        self.bot.window_title = title
        self.bot._init_window_info()

        # 连接角色信息读取器
        self.character_info.set_hwnd(hwnd)
        # 自动校准血条位置
        self.character_info.auto_calibrate()
        info = self.character_info.update()
        self.char_info_label.config(text=info.get('char_display', '角色信息已连接'))
        self.log(f"角色信息已连接: {self.character_info.get_info_text()}")

        # 传递快速设置
        self.bot.config.set('Teleport', 'teleport_key', self.teleport_key_var.get())
        self.bot.config.set('Teleport', 'cooldown', self.cooldown_var.get())
        self.bot.config.set('Detection', 'detection_interval', self.interval_var.get())

        # 传递功能开关设置
        self.bot.npc_teleporter.enabled = self.npc_enabled_var.get()
        self.bot.npc_teleporter.find_npc_mode = self.npc_mode_var.get()
        self.bot.npc_teleporter.target_dungeon_row = int(self.npc_row_var.get())

        self.bot.monster_hunter.enabled = self.hunt_enabled_var.get()

        self.bot.recycler.enabled = self.recycle_enabled_var.get()
        self.bot.recycler.bag_key = self.recycle_bag_key_var.get()

        self.bot.supply.enabled = self.supply_enabled_var.get()

        self.bot.class_skills.enabled = self.skill_enabled_var.get()
        self.bot.class_skills.class_name = self.class_var.get()

        self.bot.auto_nav.enabled = self.nav_enabled_var.get()

        self.bot.running = True
        self.bot.stats['start_time'] = datetime.now()
        
        self.bot_thread = threading.Thread(target=self.bot.run_with_window, daemon=True)
        self.bot_thread.start()

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.NORMAL)
        self.adjust_btn.config(state=tk.DISABLED)
        self.update_status("运行中")

        self._update_stats_loop()

    def stop_bot(self):
        """停止挂机"""
        if self.bot:
            self.bot.stop()
            self.bot = None

        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.DISABLED)
        self.adjust_btn.config(state=tk.NORMAL)
        self.update_status("已停止")
        self.log("挂机已停止")

    def pause_bot(self):
        """暂停/继续"""
        if self.bot:
            self.bot.pause()
            status = "已暂停" if self.bot.paused else "运行中"
            self.update_status(status)
            self.pause_btn.config(text="继续" if self.bot.paused else "暂停")

    def toggle_window(self):
        """切换窗口显示/隐藏"""
        if self.window_visible:
            self.root.withdraw()
            self.window_visible = False
        else:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.window_visible = True

    def test_detection(self):
        """测试检测"""
        selection = self.window_combo.current()
        if selection < 0 or selection >= len(self.found_windows):
            messagebox.showwarning("提示", "请先选择游戏窗口")
            return

        hwnd, title = self.found_windows[selection]
        self.log(f"测试检测，窗口: {title}")
        
        test_bot = Mir2AutoBotV2(log_callback=self.log)
        test_bot.hwnd = hwnd
        test_bot.window_title = title
        test_bot._init_window_info()

        minimap = test_bot.capture_minimap()
        if minimap is not None:
            has_players, yellow_dots = test_bot.detect_yellow_dots(minimap)
            self.log(f"测试结果: {len(yellow_dots)} 个黄点，发现玩家: {has_players}")

            debug_dir = os.path.join(SCRIPT_DIR, 'debug')
            os.makedirs(debug_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            cv2.imwrite(os.path.join(debug_dir, f'test_minimap_{timestamp}.jpg'), minimap)
            self.log(f"小地图已保存到 debug/test_minimap_{timestamp}.jpg")
        else:
            self.log("截图失败", "ERROR")

    def adjust_minimap(self):
        """调整小地图范围"""
        # 传递配置文件路径给调整窗口
        MinimapAdjustWindow(self.root, self.config, self._on_minimap_adjusted, self.config_file)

    def _on_minimap_adjusted(self):
        """小地图调整完成回调"""
        self.config = self._load_config()
        self._update_minimap_label()
        self.log(f"小地图范围已更新至 {os.path.basename(self.config_file)}")

    def save_settings(self):
        """保存设置"""
        self.config.set('Teleport', 'teleport_key', self.teleport_key_var.get())
        self.config.set('Teleport', 'cooldown', self.cooldown_var.get())
        self.config.set('Detection', 'detection_interval', self.interval_var.get())

        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
        self.log(f"设置已保存至 {os.path.basename(self.config_file)}")

    def save_features_settings(self):
        """保存功能开关设置"""
        self.config.set('NpcTeleport', 'enabled', str(self.npc_enabled_var.get()))
        self.config.set('NpcTeleport', 'find_npc_mode', self.npc_mode_var.get())
        self.config.set('NpcTeleport', 'target_dungeon_row', self.npc_row_var.get())

        self.config.set('MonsterHunt', 'enabled', str(self.hunt_enabled_var.get()))

        self.config.set('AutoRecycle', 'enabled', str(self.recycle_enabled_var.get()))
        self.config.set('AutoRecycle', 'bag_key', self.recycle_bag_key_var.get())

        self.config.set('Supply', 'enabled', str(self.supply_enabled_var.get()))

        self.config.set('ClassSkills', 'enabled', str(self.skill_enabled_var.get()))
        self.config.set('ClassSkills', 'class_name', self.class_var.get())

        self.config.set('AutoNav', 'enabled', str(self.nav_enabled_var.get()))

        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
        self.log("功能设置已保存")

    def _update_stats_loop(self):
        """更新统计循环"""
        if self.bot and self.bot.running:
            self.update_stats()
            
            # 更新角色信息（每2秒）
            now_ms = int(time.time() * 1000)
            if getattr(self, '_last_char_update', 0) + 2000 < now_ms:
                self._last_char_update = now_ms
                try:
                    info = self.character_info.update()
                    hp = info.get('hp_percent', 0)
                    mp = info.get('mp_percent', 0)
                    self.char_info_label.config(
                        text=f"角色: 💖HP {hp:.0f}% | 💙MP {mp:.0f}% | {info.get('window_title', '')}"
                    )
                except Exception as e:
                    self.log(f"读取角色信息失败: {e}", "WARNING")
            
            # 每15分钟清理一次debug目录
            if self.bot.stats['start_time']:
                elapsed = (datetime.now() - self.bot.stats['start_time']).total_seconds()
                if int(elapsed) > 0 and int(elapsed) % 900 == 0:  # 900秒 = 15分钟
                    self._cleanup_debug_dir()
            
            self.root.after(1000, self._update_stats_loop)
    
    def calibrate_character_info(self):
        """校准角色信息（血条位置）"""
        selection = self.window_combo.current()
        if selection < 0 or selection >= len(self.found_windows):
            messagebox.showwarning("提示", "请先选择游戏窗口")
            return

        hwnd, title = self.found_windows[selection]
        self.character_info.set_hwnd(hwnd)
        self.character_info.auto_calibrate()
        info = self.character_info.update()
        self.char_info_label.config(
            text=f"角色: 💖HP {info.get('hp_percent', 0):.0f}% | 💙MP {info.get('mp_percent', 0):.0f}%"
        )
        self.log(f"角色校准完成: HP条({self.character_info.hp_bar_x},{self.character_info.hp_bar_y}) "
                 f"MP条({self.character_info.mp_bar_x},{self.character_info.mp_bar_y})")
    
    def _cleanup_debug_dir(self):
        """清理debug目录"""
        debug_dir = os.path.join(SCRIPT_DIR, 'debug')
        if not os.path.exists(debug_dir):
            return
        
        try:
            # 获取目录下所有文件
            files = [f for f in os.listdir(debug_dir) if f.endswith(('.jpg', '.png', '.bmp'))]
            if files:
                for file in files:
                    file_path = os.path.join(debug_dir, file)
                    try:
                        os.remove(file_path)
                    except:
                        pass
                self.log(f"已清理debug目录: {len(files)} 个文件已删除")
        except Exception as e:
            self.log(f"清理debug目录失败: {e}", "WARNING")

    def run(self):
        """运行界面"""
        self.log("挂机界面已启动（后台截图模式）")
        self.log("点击「开始」启动挂机，F10停止")
        self.log("F9隐藏/显示窗口")
        self.root.mainloop()

    def on_closing(self):
        """关闭窗口"""
        self.stop_bot()
        keyboard.unhook_all()
        self.root.destroy()

def main():
    """主函数"""
    gui = BotGUI()
    gui.root.protocol("WM_DELETE_WINDOW", gui.on_closing)
    gui.run()

if __name__ == '__main__':
    main()