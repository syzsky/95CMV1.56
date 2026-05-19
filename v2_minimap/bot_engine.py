# -*- coding: utf-8 -*-
"""
智能挂机状态机引擎
自动判断当前状态并执行对应操作
V2 - 内挂版：只负责导航，不手动攻击
"""

import time
import logging
import random
from enum import Enum, auto

logger = logging.getLogger(__name__)


class BotState(Enum):
    """挂机状态"""
    IDLE = auto()
    TELEPORT = auto()       # 找NPC飞图
    HUNT = auto()           # 找红点→走过去
    FLEE = auto()           # 检测到玩家，逃跑
    PATROL = auto()         # 没怪了，单向巡逻（不再随机乱走）
    FLEE_BACK = auto()      # 逃跑后等几秒返回
    COMPLETED = auto()      # 完成


class SmartEngine:
    """
    智能挂机引擎 - 状态机驱动
    自动切换：传送 → 找红点走过去 → 内挂自动打 → 继续找 → 没怪了单向巡逻
    """

    # 巡逻方向顺序（右→下→左→上，顺时针扫图）
    PATROL_DIRECTIONS = ['D', 'S', 'A', 'W']

    def __init__(self, bot):
        """
        bot: Mir2AutoBotV2 实例
        """
        self.bot = bot
        self.state = BotState.IDLE
        self.last_change_time = 0
        self._patrol_start = 0

        # 各状态启动时间
        self._state_times = {}
        self._last_check_time = 0

        # 状态切换冷却
        self.min_state_time = 2.0

        # 巡逻方向索引
        self._patrol_dir_idx = 0
        # 巡逻时没有看到红点的累计时间
        self._patrol_no_red_time = 0

    def change_state(self, new_state: BotState):
        """切换状态"""
        if new_state == self.state:
            return
        old = self.state
        self.state = new_state
        self.last_change_time = time.time()
        self._state_times[new_state] = time.time()
        logger.info(f"[引擎] {old.name} → {new_state.name}")

    def update(self):
        """
        主更新循环，每秒调用一次
        """
        if not self.bot.running:
            return

        now = time.time()

        # 截图小地图
        minimap = self.bot.capture_minimap()
        if minimap is None:
            time.sleep(0.3)
            return

        self.bot.stats['detection_runs'] += 1

        # 检测红点（怪物）和黄点（玩家）
        red_dots = self.bot.minimap_detector.detect_red_dots(minimap)
        yellow_dots = self.bot.minimap_detector.detect(minimap)

        has_monsters = len(red_dots) > 0
        has_players = len(yellow_dots) > 0

        mm_w = self.bot.minimap_region[2]
        mm_h = self.bot.minimap_region[3]
        center_x = mm_w // 2
        center_y = mm_h // 2

        # ====== 状态机调度 ======
        if self.state == BotState.IDLE:
            self._handle_idle()

        elif self.state == BotState.TELEPORT:
            self._handle_teleport()

        elif self.state == BotState.HUNT:
            self._handle_hunt(red_dots, yellow_dots, center_x, center_y,
                             has_monsters, has_players)

        elif self.state == BotState.FLEE:
            self._handle_flee(has_players)

        elif self.state == BotState.PATROL:
            self._handle_patrol(red_dots, center_x, center_y, has_monsters, now)

        elif self.state == BotState.FLEE_BACK:
            self._handle_flee_back()

        # 统计更新
        self.bot.update_stats()

        # 定时自动回收（间隔足够的话才执行）
        self.bot.recycler.try_recycle()

        # 定时自动补给（间隔足够的话才执行）
        self.bot.supply.do_supply()

        # 检测间隔
        interval = self.bot.config.getfloat('Detection', 'detection_interval', fallback=0.3)
        time.sleep(interval)

    # ====== 各状态处理方法 ======

    def _handle_idle(self):
        """初始状态 - 决定要做什么"""
        npc_enabled = self.bot.npc_teleporter.enabled
        hunt_enabled = self.bot.monster_hunter.enabled

        if npc_enabled:
            logger.info("[引擎] 开始NPC传送流程")
            self.bot.npc_teleporter.start_teleport(callback=self._on_teleport_done)
            self.change_state(BotState.TELEPORT)
        elif hunt_enabled:
            logger.info("[引擎] 直接开始导航找怪")
            self.bot.monster_hunter.start_hunting()
            self.change_state(BotState.PATROL)
        else:
            self.change_state(BotState.COMPLETED)

    def _on_teleport_done(self):
        """传送完成回调 - 开始导航找怪"""
        logger.info("[引擎] 传送完成，开始导航找怪")
        if self.bot.monster_hunter.enabled:
            self.bot.monster_hunter.start_hunting()
            self.change_state(BotState.PATROL)
        else:
            self.change_state(BotState.COMPLETED)

    def _handle_teleport(self):
        """传送中 - 等待NPC传送器完成"""
        status = self.bot.npc_teleporter.update()
        if status == 'failed':
            logger.warning("[引擎] 传送失败，重新尝试")
            self.bot.npc_teleporter.start_teleport(self._on_teleport_done)

    def _handle_hunt(self, red_dots, yellow_dots, cx, cy,
                     has_monsters, has_players):
        """
        导航状态 - 找最近的红点走过去
        走到红点附近后，返回 PATROL 继续找下一个
        内挂负责自动打怪
        """
        # 有玩家→逃跑
        if has_players and self.bot.config.getboolean('Teleport', 'enabled', fallback=True):
            logger.info("[引擎] 检测到玩家！切换逃跑")
            self.change_state(BotState.FLEE)
            return

        if has_monsters:
            # 导航到最近的红点
            result = self.bot.monster_hunter.navigate(red_dots, cx, cy)
            if result == 'arrived':
                # 走到红点旁边了，内挂会自动打
                # 等一小会儿，然后继续找下一个
                time.sleep(1.0)
                self.change_state(BotState.PATROL)
            # 'walking' 保持 HUNT 继续走
        else:
            # 没怪了→巡逻
            logger.info("[引擎] 没有红点了，开始单向巡逻")
            self._patrol_start = time.time()
            self._patrol_dir_idx = 0
            self._patrol_no_red_time = 0
            self.change_state(BotState.PATROL)

    def _handle_flee(self, has_players):
        """逃跑状态 - 使用随机传送石"""
        self.bot.use_teleport()
        # 等一会儿再检查
        if time.time() - self.last_change_time > 5:
            self.change_state(BotState.FLEE_BACK)

    def _handle_flee_back(self):
        """逃跑后返回 - 等传送冷却"""
        if time.time() - self.last_change_time > 3:
            self.change_state(BotState.PATROL)

    def _handle_patrol(self, red_dots, cx, cy, has_monsters, now):
        """
        巡逻状态 - 单向走，不回头
        
        巡逻方向顺序：右→下→左→上（顺时针）
        走到地图边缘或30秒没红点，换方向
        """
        # 发现怪物→切换导航
        if has_monsters:
            logger.info("[引擎] 巡逻时发现红点！切换导航")
            self.change_state(BotState.HUNT)
            return

        # 巡逻时间
        elapsed = now - self._patrol_start

        # 巡逻了30秒还没见怪→换个方向
        if elapsed > 30:
            self._patrol_dir_idx = (self._patrol_dir_idx + 1) % len(self.PATROL_DIRECTIONS)
            self._patrol_start = now
            dir_name = self.PATROL_DIRECTIONS[self._patrol_dir_idx]
            logger.info(f"[引擎] 巡逻30秒无怪，换方向 [{dir_name}]")

        # 按当前方向走一步
        direction = self.PATROL_DIRECTIONS[self._patrol_dir_idx]
        self.bot.monster_hunter.send_key(direction, 0.3)
        time.sleep(0.8)

        # 每走10秒再截一次小地图检查
        if int(elapsed) % 10 == 0 and elapsed > 1:
            # 再检查一次小地图（上面已经检查过了，但巡逻过程中可能会有新怪刷出来）
            minimap = self.bot.capture_minimap()
            if minimap is not None:
                new_red = self.bot.minimap_detector.detect_red_dots(minimap)
                if new_red:
                    logger.info("[引擎] 巡逻中发现新刷怪！")
                    self.change_state(BotState.HUNT)