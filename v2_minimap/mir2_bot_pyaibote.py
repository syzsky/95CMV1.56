# -*- coding: utf-8 -*-
"""
95沉默传奇 - PyAibote 版挂机脚本
================================
基于 PyAibote (Windows RPA 框架)

原理：
  WindowsDriver.exe（C++驱动后台操作）
        ↓ TCP 连接
  PyAibote.WinBotMain（Python 控制层）
        ↓
  本脚本（挂机逻辑）

使用方式：
  1. pip install PyAibote
  2. 把 WindowsDriver.exe 放脚本同目录
  3. 运行本脚本（自动启动驱动并连接）
"""
import time
import os
import sys
import subprocess
from datetime import datetime
from PyAibote import WinBotMain


# ===== 配置 =====
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "templates")
os.makedirs(TEMPLATE_DIR, exist_ok=True)


class Mir2Bot(WinBotMain):
    """95沉默传奇 自动挂机脚本 - PyAibote版"""

    Log_Level = "DEBUG"
    Log_Storage = True

    def script_main(self):
        """=== 挂机主入口 ==="""
        self.log("=" * 40)
        self.log("95沉默 PyAibote 挂机脚本 启动")
        self.log("=" * 40)

        # 1. 找游戏窗口
        hwnd = self._find_game_window()
        if not hwnd:
            self.log("❌ 找不到游戏窗口", "ERROR")
            return

        # 2. 获取窗口信息
        _, _, w, h = self.get_window_pos(hwnd)
        self.log(f"✅ 窗口: {self.get_window_name(hwnd)} ({w}x{h})")

        # 3. 计算小地图区域（右上角）
        mm_x = w - 150 - 10  # 从右边偏移10像素
        mm_y = 10
        mm_w = 150
        mm_h = 150

        # 4. 主挂机循环
        self._start_time = time.time()
        self.log("🚀 开始挂机...")
        self._run_loop(hwnd, mm_x, mm_y, mm_w, mm_h)

    # ==================== 找窗口 ====================

    def _find_game_window(self):
        """在所有窗口中找传奇窗口"""
        windows = self.find_windows()
        if not windows:
            return None

        titles = ["九五沉默", "Legend of Mir2", "传奇", "Mir2"]
        for hwnd, title in windows:
            for t in titles:
                if t.lower() in title.lower():
                    return hwnd
        return None

    # ==================== 主循环 ====================

    def _run_loop(self, hwnd, mm_x, mm_y, mm_w, mm_h):
        """主挂机循环 - 全用 PyAibote API"""
        teleport_key = ord("2")     # 按2飞随机
        bag_key = 0x78              # VK_F9 开背包
        patrol_dirs = ["D", "S", "A", "W"]

        loop = 0
        last_recycle = 0
        running = True
        patrol_idx = 0

        try:
            while running and self._window_exists(hwnd):
                loop += 1
                now = time.time()

                # ===== 第1步：在小地图区域检测颜色 =====
                # PyAibote 的 find_color 直接在窗口指定区域找颜色
                # mode=True = 后台操作

                # 找红点（怪物）：RGB(255,0,0)
                red_dots = self.find_color(
                    hwnd, "#FF0000",
                    region=(mm_x, mm_y, mm_x + mm_w, mm_y + mm_h),
                    similarity=0.85,
                    mode=True,            # 后台！
                    wait_time=0.5,
                )

                # 找黄点（玩家）：RGB(255,255,0)
                yellow_dots = self.find_color(
                    hwnd, "#FFFF00",
                    region=(mm_x, mm_y, mm_x + mm_w, mm_y + mm_h),
                    similarity=0.9,
                    mode=True,            # 后台！
                    wait_time=0.5,
                )

                has_monster = red_dots is not None
                has_player = yellow_dots is not None

                # ===== 第2步：决策 =====
                if has_player:
                    # 有玩家→飞走
                    self.send_vk_by_hwnd(hwnd, teleport_key)
                    self.log("🟡 发现玩家！已传送")
                    time.sleep(3)

                elif has_monster:
                    # 有怪物→走过去
                    try:
                        # find_color 返回 (x_str, y_str)
                        mx, my = float(red_dots[0]), float(red_dots[1])
                        cx, cy = mm_x + mm_w // 2, mm_y + mm_h // 2
                        dx, dy = mx - cx, my - cy

                        # 决定方向
                        if abs(dx) > abs(dy):
                            key = "D" if dx > 0 else "A"
                        else:
                            key = "S" if dy > 0 else "W"

                        self.send_keys_by_hwnd(hwnd, key)
                        time.sleep(0.5)
                    except (ValueError, IndexError, TypeError):
                        pass

                else:
                    # 没怪→巡逻（顺时针换方向）
                    patrol_idx = (loop // 30) % 4  # 每30步换方向
                    self.send_keys_by_hwnd(hwnd, patrol_dirs[patrol_idx])
                    time.sleep(0.8)

                # ===== 第3步：定时功能 =====

                # 自动回收（每180秒）
                if now - last_recycle > 180:
                    self._do_recycle(hwnd, bag_key)
                    last_recycle = now

                # 状态输出（每20次）
                if loop % 20 == 0:
                    elapsed = int(now - self._start_time)
                    self.log(
                        f"[{elapsed}s] loog:{loop} "
                        f"{'🟡玩家' if has_player else '🔴打怪' if has_monster else '🚶巡逻'}"
                    )

                time.sleep(0.3)

        except Exception as e:
            self.log(f"❌ 主循环异常: {e}", "ERROR")
        finally:
            self.log("🏁 挂机已停止")

    # ==================== 自动回收 ====================

    def _do_recycle(self, hwnd, bag_key):
        """自动回收 - 用 PyAibote 找图"""
        self.log("开始回收...")

        btn_path = os.path.join(TEMPLATE_DIR, "recycle_button.png")
        if not os.path.exists(btn_path):
            self.log("⚠️ 找不到 recycle_button.png 模板图片，跳过回收", "WARNING")
            return

        # 开背包
        self.send_vk_by_hwnd(hwnd, bag_key)
        time.sleep(0.5)

        # 找回收按钮（后台找图！）
        result = self.find_images(
            hwnd, btn_path,
            similarity=0.8,
            mode=True,       # 后台！
            wait_time=2,
        )
        if result:
            x, y = result[0]
            self.click_mouse(hwnd, x, y)
            self.log("✅ 回收完成")
            time.sleep(0.5)
        else:
            self.log("⚠️ 没找到回收按钮")

        # 关背包
        self.send_vk_by_hwnd(hwnd, bag_key)
        time.sleep(0.3)

    # ==================== 工具 ====================

    def _window_exists(self, hwnd):
        """检查窗口是否还存在"""
        try:
            name = self.get_window_name(hwnd)
            return bool(name)
        except:
            return False

    def log(self, msg, level="INFO"):
        """带时间戳日志"""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {msg}")


def _launch_driver():
    """查找当前目录的WindowsDriver.exe并启动（仅打包版需要）"""
    # 检查 EXE 同目录
    exe_dir = os.path.dirname(os.path.abspath(__file__))
    driver_paths = [
        os.path.join(exe_dir, "WindowsDriver.exe"),
        os.path.join(os.getcwd(), "WindowsDriver.exe"),
    ]
    for p in driver_paths:
        if os.path.exists(p):
            print(f"[INFO] 找到 WindowsDriver.exe: {p}")
            subprocess.Popen(
                [p],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            print("[INFO] WindowsDriver.exe 已启动，等待2秒...")
            time.sleep(2)
            return True

    print("[WARN] 当前目录没有 WindowsDriver.exe")
    print("[WARN] 下载地址: www.pyaibote.com")
    return False


# ==================== 启动 ====================
if __name__ == "__main__":
    print("=" * 50)
    print("95沉默 PyAibote 挂机脚本")
    print("=" * 50)

    is_packaged = getattr(sys, 'frozen', False)

    if is_packaged:
        # 打包模式：需要用户自己下载 WindowsDriver.exe 放同目录
        if not _launch_driver():
            print("[ERROR] 请下载 WindowsDriver.exe 放到 EXE 同目录")
            print("   下载地址: https://www.pyaibote.com")
            input("按回车退出...")
            sys.exit(1)

        Mir2Bot.execute(
            IP="127.0.0.1",
            Port=9999,
            Debug=False,
            Qt=None,
            WebsocketSwitch=False,
            WebsocketPort=8888,
        )
    else:
        # 源码模式：PyAibote 自动管理驱动
        Mir2Bot.execute(
            IP="0.0.0.0",
            Port=9999,
            Debug=True,
            Qt=None,
            WebsocketSwitch=False,
            WebsocketPort=8888,
        )