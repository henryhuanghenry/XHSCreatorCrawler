# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import os
import random
from asyncio import Task
from typing import Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
from tenacity import RetryError

import config
from base.base_crawler import AbstractCrawler
from model.m_xiaohongshu import NoteUrlInfo, CreatorUrlInfo
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import xhs as xhs_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var, current_creator_id_var

from .client import XiaoHongShuClient
from .exception import DataFetchError, NoteNotFoundError, BrowserContextClosedError
from .field import SearchSortType
from .help import parse_note_info_from_note_url, parse_creator_info_from_url, get_search_id
from .login import XiaoHongShuLogin


class XiaoHongShuCrawler(AbstractCrawler):
    context_page: Page
    xhs_client: XiaoHongShuClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://www.xiaohongshu.com"
        # self.user_agent = utils.get_user_agent()
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            # Choose launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[XiaoHongShuCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[XiaoHongShuCrawler] Launching browser using standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.HEADLESS,
                )
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url)

            # Create a client to interact with the Xiaohongshu website.
            self.xhs_client = await self.create_xhs_client(httpx_proxy_format)
            if not await self.xhs_client.pong():
                login_obj = XiaoHongShuLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # input your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.xhs_client.update_cookies(browser_context=self.browser_context)

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass

            utils.logger.info("[XiaoHongShuCrawler.start] Xhs Crawler finished ...")

    async def search(self) -> None:
        """Search for notes and retrieve their comment information."""
        utils.logger.info("[XiaoHongShuCrawler.search] Begin search Xiaohongshu keywords")
        xhs_limit_count = 20  # Xiaohongshu limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < xhs_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = xhs_limit_count
        start_page = config.START_PAGE
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[XiaoHongShuCrawler.search] Current search keyword: {keyword}")
            page = 1
            search_id = get_search_id()
            while (page - start_page + 1) * xhs_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Skip page {page}")
                    page += 1
                    continue

                try:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] search Xiaohongshu keyword: {keyword}, page: {page}")
                    note_ids: List[str] = []
                    xsec_tokens: List[str] = []
                    notes_res = await self.xhs_client.get_note_by_keyword(
                        keyword=keyword,
                        search_id=search_id,
                        page=page,
                        sort=(SearchSortType(config.SORT_TYPE) if config.SORT_TYPE != "" else SearchSortType.GENERAL),
                    )
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Search notes response: {notes_res}")
                    if not notes_res or not notes_res.get("has_more", False):
                        utils.logger.info("[XiaoHongShuCrawler.search] No more content!")
                        break
                    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                    task_list = [
                        self.get_note_detail_async_task(
                            note_id=post_item.get("id"),
                            xsec_source=post_item.get("xsec_source"),
                            xsec_token=post_item.get("xsec_token"),
                            semaphore=semaphore,
                        ) for post_item in notes_res.get("items", {}) if post_item.get("model_type") not in ("rec_query", "hot_query")
                    ]
                    note_details = await asyncio.gather(*task_list)
                    for note_detail in note_details:
                        if note_detail:
                            await xhs_store.update_xhs_note(note_detail)
                            await self.get_notice_media(note_detail)
                            note_ids.append(note_detail.get("note_id"))
                            xsec_tokens.append(note_detail.get("xsec_token"))
                    page += 1
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Note details: {note_details}")
                    await self.batch_get_note_comments(note_ids, xsec_tokens)

                    # Sleep after each page navigation
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
                except DataFetchError:
                    utils.logger.error("[XiaoHongShuCrawler.search] Get note detail error")
                    break

    async def get_creators_and_notes(self) -> None:
        """Get creator's notes and retrieve their comment information.
        
        New two-phase process:
        Phase 1: Fetch all note IDs (with full/incremental mode support)
        Phase 2: Fetch note content for unfetched notes only
        """
        from .note_id_manager import NoteIdManager
        
        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] Begin get Xiaohongshu creators")
        for creator_url in config.XHS_CREATOR_ID_LIST:
            try:
                # Parse creator URL to get user_id and security tokens
                creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)
                utils.logger.info(f"[XiaoHongShuCrawler.get_creators_and_notes] Parse creator URL info: {creator_info}")
                user_id = creator_info.user_id
                
                # Set current creator ID in context variable
                current_creator_id_var.set(user_id)

                # get creator detail info from web html content
                createor_info: Dict = await self.xhs_client.get_creator_info(
                    user_id=user_id,
                    xsec_token=creator_info.xsec_token,
                    xsec_source=creator_info.xsec_source
                )
                if createor_info:
                    await xhs_store.save_creator(user_id, creator=createor_info)
            except ValueError as e:
                utils.logger.error(f"[XiaoHongShuCrawler.get_creators_and_notes] Failed to parse creator URL: {e}")
                continue

            # ========== PHASE 1: Fetch all note IDs ==========
            utils.logger.info(
                f"[XiaoHongShuCrawler.get_creators_and_notes] Phase 1: Fetching note IDs for creator {user_id} "
                f"(mode: {config.CREATOR_CRAWL_MODE})"
            )
            
            # Initialize note ID manager
            note_id_manager = NoteIdManager(creator_id=user_id)
            await note_id_manager.load_existing_ids()
            
            # ========== Check for incremental mode without checkpoint ==========
            if config.CREATOR_CRAWL_MODE == "incremental":
                stats = note_id_manager.get_stats()
                
                # If no existing note IDs found in incremental mode, suggest switching to full mode
                if stats['total_ids'] == 0:
                    utils.logger.warning(
                        f"[XiaoHongShuCrawler.get_creators_and_notes] Incremental mode detected but no checkpoint found for creator {user_id}"
                    )
                    print("\n" + "="*70)
                    print("⚠️  增量模式警告 - Incremental Mode Warning")
                    print("="*70)
                    print("📭 未检测到本地checkpoint文件（note_ids.json）")
                    print("   No local checkpoint file (note_ids.json) found")
                    print("")
                    print("💡 建议切换到全量模式进行首次爬取")
                    print("   Recommend switching to full mode for first-time crawl")
                    print("="*70)
                    print("")
                    print("选项 Options:")
                    print("  [1] 切换到全量模式 (Switch to full mode)")
                    print("  [2] 继续使用增量模式 (Continue with incremental mode)")
                    print("  [3] 退出程序 (Exit)")
                    print("")
                    
                    user_choice = input("请选择 Please choose [1/2/3]: ").strip()
                    
                    if user_choice == "1":
                        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] User chose to switch to full mode")
                        print("✅ 已切换到全量模式 Switched to full mode")
                        print("")
                        print("📌 全量模式工作流程说明:")
                        print("   Phase 1: 先爬取所有笔记链接（ID列表）")
                        print("   Phase 2: 再逐个拉取笔记详细内容")
                        print("")
                        print("📌 Full mode workflow:")
                        print("   Phase 1: Fetch all note IDs first")
                        print("   Phase 2: Then fetch note details one by one")
                        print("")
                        config.CREATOR_CRAWL_MODE = "full"  # Switch to full mode
                    elif user_choice == "2":
                        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] User chose to continue with incremental mode")
                        print("✅ 继续使用增量模式 Continue with incremental mode\n")
                    else:
                        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] User chose to exit")
                        print("👋 已退出程序 Exiting...\n")
                        return  # Exit the function
            
            # Check for saved cursor (resume from last position) - ONLY in full mode
            start_cursor = ""
            if config.CREATOR_CRAWL_MODE == "full":
                saved_cursor_data = await note_id_manager.load_cursor()
                start_cursor = saved_cursor_data.get("cursor", "") if saved_cursor_data else ""
                
                if start_cursor:
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.get_creators_and_notes] 🔄 Resuming from saved cursor: {start_cursor}, "
                        f"last updated: {saved_cursor_data.get('last_updated', 'unknown')}, "
                        f"previously fetched: {saved_cursor_data.get('total_ids_fetched', 0)} IDs"
                    )
                    print("\n" + "="*70)
                    print("🔄 检测到上次未完成的全量爬取任务")
                    print("   Detected incomplete full mode crawl task")
                    print("="*70)
                    print(f"📍 上次爬取位置 Last position: cursor={start_cursor}")
                    print(f"⏰ 上次更新时间 Last updated: {saved_cursor_data.get('last_updated', 'unknown')}")
                    print(f"📊 已获取笔记ID数 Fetched IDs: {saved_cursor_data.get('total_ids_fetched', 0)} 条 notes")
                    print("="*70)
                    user_input = input("\n是否从上次位置继续爬取? Resume from last position? (yes继续/no重新开始): ").strip().lower()
                    
                    if user_input != 'yes':
                        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] User chose to restart from beginning")
                        print("✅ 将从头开始重新爬取 Restarting from beginning\n")
                        start_cursor = ""
                        await note_id_manager.clear_cursor()
                    else:
                        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] User chose to resume from saved cursor")
                        print("✅ 将从上次位置继续爬取 Resuming from last position\n")
            else:
                # Incremental mode: always start fresh, no resume
                utils.logger.info(
                    f"[XiaoHongShuCrawler.get_creators_and_notes] Incremental mode: starting fresh (no resume)"
                )
            
            # Log existing state
            stats = note_id_manager.get_stats()
            utils.logger.info(
                f"[XiaoHongShuCrawler.get_creators_and_notes] Existing state: "
                f"{stats['total_ids']} total IDs, {stats['unfetched']} unfetched"
            )
            
            # ========== Full Mode Workflow Notice ==========
            if config.CREATOR_CRAWL_MODE == "full":
                print("\n" + "="*70)
                print("🚀 全量模式启动 - Full Mode Started")
                print("="*70)
                print("📋 工作流程 Workflow:")
                print("   ⏩ Phase 1: 爬取所有笔记ID列表 (Fetch all note IDs)")
                print("   ⏩ Phase 2: 拉取笔记详细内容 (Fetch note details)")
                print("")
                print("💡 提示: Phase 1 完成后才会开始下载内容")
                print("   Note: Content download starts after Phase 1 completes")
                print("="*70)
                print("")
            
            # Callback to collect note IDs
            async def collect_note_ids(note_list: List[Dict]):
                """Callback to collect note items with tokens"""
                new_count = note_id_manager.add_note_ids(note_list)
                utils.logger.info(
                    f"[XiaoHongShuCrawler.get_creators_and_notes] Collected {len(note_list)} note items, "
                    f"{new_count} new"
                )
            
            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            
            # Get all note IDs (will start from saved cursor if available)
            all_notes_list = await self.xhs_client.get_all_notes_by_creator(
                user_id=user_id,
                crawl_interval=crawl_interval,
                callback=collect_note_ids,
                xsec_token=creator_info.xsec_token,
                xsec_source=creator_info.xsec_source,
                note_id_manager=note_id_manager,
                start_cursor=start_cursor,  # Pass the start cursor
            )
            
            # Save note IDs to storage
            await note_id_manager.save_note_ids()
            
            stats_after = note_id_manager.get_stats()
            utils.logger.info(
                f"[XiaoHongShuCrawler.get_creators_and_notes] Phase 1 completed: "
                f"{stats_after['total_ids']} total IDs, {stats_after['unfetched']} unfetched"
            )

            # ========== User Confirmation for Incremental Mode ==========
            if config.CREATOR_CRAWL_MODE == "incremental":
                # Calculate incremental notes (new notes discovered in this run)
                incremental_count = stats_after['total_ids'] - stats['total_ids']
                existing_unfetched = stats_after['unfetched']
                
                print("\n" + "="*70)
                print("📊 小红书Creator增量模式 - 笔记统计")
                print("   XHS Creator Incremental Mode - Note Statistics")
                print("="*70)
                print(f"✨ 本次发现的增量笔记数 New notes discovered: {incremental_count} 条 notes")
                print(f"📦 存量未拉取笔记数 Existing unfetched notes: {existing_unfetched} 条 notes")
                print(f"📝 总计待拉取笔记数 Total to fetch: {existing_unfetched} 条 notes")
                print(f"📋 已拉取笔记数 Already fetched: {stats_after['fetched']} 条 notes")
                print(f"🔢 总笔记ID数 Total note IDs: {stats_after['total_ids']} 条 notes")
                print("="*70)
                
                if existing_unfetched > 0:
                    print(f"\n⚠️  即将拉取 {existing_unfetched} 条笔记的详细内容（包括图片和视频）")
                    print(f"   About to fetch {existing_unfetched} notes' details (including images and videos)")
                    print("💡 提示 Tip: 输入 'yes' 继续 Enter 'yes' to continue, 输入其他任何内容退出 others to exit\n")
                    
                    user_input = input("是否继续拉取笔记内容? Continue fetching note content? (yes/no): ").strip().lower()
                    
                    if user_input != 'yes':
                        utils.logger.info(
                            f"[XiaoHongShuCrawler.get_creators_and_notes] User cancelled content fetching. "
                            f"Phase 1 completed, {existing_unfetched} notes remain unfetched."
                        )
                        print("\n✋ 用户取消操作，已保存笔记ID列表，可稍后继续拉取内容。")
                        print("   User cancelled. Note ID list saved, you can continue fetching later.")
                        continue  # Skip to next creator
                    
                    print(f"\n✅ 用户确认，开始拉取 {existing_unfetched} 条笔记内容...")
                    print(f"   User confirmed, starting to fetch {existing_unfetched} notes...\n")
                else:
                    print("\n✅ 没有待拉取的笔记，跳过Phase 2")
                    print("   No unfetched notes, skipping Phase 2\n")

            # ========== PHASE 2: Fetch note content ==========
            utils.logger.info(
                f"[XiaoHongShuCrawler.get_creators_and_notes] Phase 2: Fetching note content for unfetched notes"
            )
            
            unfetched_items = note_id_manager.get_unfetched_note_ids(include_not_found=config.FETCH_NOT_FOUND_NOTES)
            if not unfetched_items:
                utils.logger.info(
                    f"[XiaoHongShuCrawler.get_creators_and_notes] No unfetched notes for creator {user_id}"
                )
            else:
                utils.logger.info(
                    f"[XiaoHongShuCrawler.get_creators_and_notes] Fetching content for {len(unfetched_items)} notes "
                    f"(FETCH_NOT_FOUND_NOTES={config.FETCH_NOT_FOUND_NOTES})"
                )
                
                # Build note items from all_notes_list for unfetched IDs that are in the current fetch
                note_items_to_fetch = []
                fetched_ids_from_list = set()
                
                # Convert unfetched items to dict for faster lookup
                unfetched_dict = {item["note_id"]: item for item in unfetched_items}
                
                # Prioritize using fresh tokens from all_notes_list (from current API fetch)
                for note_item in all_notes_list:
                    note_id = note_item.get("note_id")
                    if note_id in unfetched_dict:
                        # Use fresh token from current fetch if available
                        note_items_to_fetch.append(note_item)
                        fetched_ids_from_list.add(note_id)
                
                # For unfetched IDs not in all_notes_list, use stored tokens from previous fetch
                # These are notes from previous runs that weren't fetched
                missing_unfetched_ids = set(unfetched_dict.keys()) - fetched_ids_from_list
                
                if missing_unfetched_ids:
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.get_creators_and_notes] Found {len(missing_unfetched_ids)} "
                        f"previously stored but unfetched notes, using stored tokens"
                    )
                    
                    # Use stored tokens from note_id_manager
                    for note_id in missing_unfetched_ids:
                        stored_item = unfetched_dict[note_id]
                        note_items_to_fetch.append(stored_item)
                        if not stored_item.get("xsec_token"):
                            utils.logger.warning(
                                f"[XiaoHongShuCrawler.get_creators_and_notes] Note {note_id} has no stored token, "
                                f"may fail to fetch"
                            )
                
                # Apply fetch order based on configuration
                if config.CREATOR_NOTE_FETCH_ORDER == "random":
                    # Shuffle the fetch order to randomize access pattern (helps avoid anti-crawler detection)
                    random.shuffle(note_items_to_fetch)
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.get_creators_and_notes] Shuffled {len(note_items_to_fetch)} notes for random fetch order"
                    )
                elif config.CREATOR_NOTE_FETCH_ORDER == "sorted":
                    # Sort by note_id in descending order (larger IDs first)
                    note_items_to_fetch.sort(key=lambda x: x.get("note_id", ""), reverse=True)
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.get_creators_and_notes] Sorted {len(note_items_to_fetch)} notes by note_id (descending)"
                    )
                else:
                    utils.logger.warning(
                        f"[XiaoHongShuCrawler.get_creators_and_notes] Unknown fetch order '{config.CREATOR_NOTE_FETCH_ORDER}', "
                        f"using original order"
                    )
                
                # Fetch note details in batches
                if note_items_to_fetch:
                    await self.fetch_creator_notes_detail_with_manager(
                        note_items_to_fetch, 
                        note_id_manager
                    )
                
                # Save updated note ID status
                await note_id_manager.save_note_ids()
                
                stats_final = note_id_manager.get_stats()
                utils.logger.info(
                    f"[XiaoHongShuCrawler.get_creators_and_notes] Phase 2 completed: "
                    f"{stats_final['fetched']} fetched, {stats_final['unfetched']} remaining"
                )

            # ========== Get comments for all notes ==========
            if config.ENABLE_GET_COMMENTS:
                note_ids = []
                xsec_tokens = []
                for note_item in all_notes_list:
                    note_ids.append(note_item.get("note_id"))
                    xsec_tokens.append(note_item.get("xsec_token"))
                await self.batch_get_note_comments(note_ids, xsec_tokens)

    async def fetch_creator_notes_detail_with_manager(
        self, 
        note_list: List[Dict],
        note_id_manager
    ):
        """Fetch note details and mark them as fetched in the manager
        
        This method implements STREAMING PROCESSING:
        - Each note is fetched, processed, saved, and exported IMMEDIATELY upon completion
        - No waiting for all notes to be fetched before processing
        - Images are downloaded and markdown is exported as soon as detail is available
        - Status is marked as fetched immediately in JSON
        """
        import re
        from datetime import datetime
        
        # Parse date filters once
        start_timestamp = None
        end_timestamp = None
        
        if config.CRAWLER_START_DATE:
            try:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', config.CRAWLER_START_DATE):
                    start_dt = datetime.strptime(config.CRAWLER_START_DATE, '%Y-%m-%d')
                    start_timestamp = int(start_dt.timestamp() * 1000)
            except ValueError:
                pass
        
        if config.CRAWLER_END_DATE:
            try:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', config.CRAWLER_END_DATE):
                    end_dt = datetime.strptime(config.CRAWLER_END_DATE, '%Y-%m-%d')
                    end_timestamp = int((end_dt.timestamp() + 86399.999) * 1000)
            except ValueError:
                pass
        
        saved_count = 0
        filtered_count = 0
        failed_count = 0
        total_count = len(note_list)
        
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        
        # Track which IDs have been marked as fetched (batch save)
        fetched_ids = []
        fetched_ids_lock = asyncio.Lock()
        
        utils.logger.info(
            f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
            f"Starting to fetch and process {total_count} notes with streaming approach"
        )
        
        async def fetch_and_process_note(post_item: Dict):
            """Fetch a single note and process it immediately"""
            nonlocal saved_count, filtered_count, failed_count
            
            note_id = post_item.get("note_id")
            
            try:
                # Fetch note detail
                note_detail = await self.get_note_detail_async_task(
                    note_id=note_id,
                    xsec_source=post_item.get("xsec_source"),
                    xsec_token=post_item.get("xsec_token"),
                    semaphore=semaphore,
                    note_id_manager=note_id_manager,  # Pass manager to handle not_found marking
                )
                
                if isinstance(note_detail, Exception):
                    failed_count += 1
                    utils.logger.error(
                        f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
                        f"Exception fetching note {note_id}: {note_detail}"
                    )
                    return
                
                if not note_detail:
                    # Note fetch failed - check if it's marked as not_found
                    # If not marked, will retry next time
                    failed_count += 1
                    utils.logger.debug(
                        f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
                        f"Failed to fetch note {note_id}"
                    )
                    return
                
                # Check date filter
                note_time = note_detail.get("time", 0)
                note_title = note_detail.get("title", "")[:40]
                
                # Apply date filtering
                if start_timestamp and note_time < start_timestamp:
                    filtered_count += 1
                    readable_time = datetime.fromtimestamp(note_time / 1000).strftime('%Y-%m-%d %H:%M:%S') if note_time else "N/A"
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
                        f"Filtered out (before start date): '{note_title}' ({readable_time})"
                    )
                    # Mark as fetched - we successfully got it but filtered it out
                    note_id_manager.mark_as_fetched(note_id)
                    async with fetched_ids_lock:
                        fetched_ids.append(note_id)
                    return
                
                if end_timestamp and note_time > end_timestamp:
                    filtered_count += 1
                    readable_time = datetime.fromtimestamp(note_time / 1000).strftime('%Y-%m-%d %H:%M:%S') if note_time else "N/A"
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
                        f"Filtered out (after end date): '{note_title}' ({readable_time})"
                    )
                    # Mark as fetched - we successfully got it but filtered it out
                    note_id_manager.mark_as_fetched(note_id)
                    async with fetched_ids_lock:
                        fetched_ids.append(note_id)
                    return
                
                # IMMEDIATE PROCESSING: Save, download images, export markdown
                # 1. Save note to storage and get formatted data
                note_id = note_detail.get("note_id")
                user_info = note_detail.get("user", {})
                interact_info = note_detail.get("interact_info", {})
                image_list: List[Dict] = note_detail.get("image_list", [])
                tag_list: List[Dict] = note_detail.get("tag_list", [])

                for img in image_list:
                    if img.get('url_default') != '':
                        img.update({'url': img.get('url_default')})

                from store.xhs import get_video_url_arr
                video_url = ','.join(get_video_url_arr(note_detail))

                # Format note data for storage and markdown export
                formatted_note = {
                    "note_id": note_detail.get("note_id"),
                    "type": note_detail.get("type"),
                    "title": note_detail.get("title") or note_detail.get("desc", "")[:255],
                    "desc": note_detail.get("desc", ""),
                    "video_url": video_url,
                    "time": note_detail.get("time"),
                    "last_update_time": note_detail.get("last_update_time", 0),
                    "user_id": user_info.get("user_id"),
                    "nickname": user_info.get("nickname"),
                    "avatar": user_info.get("avatar"),
                    "liked_count": interact_info.get("liked_count"),
                    "collected_count": interact_info.get("collected_count"),
                    "comment_count": interact_info.get("comment_count"),
                    "share_count": interact_info.get("share_count"),
                    "ip_location": note_detail.get("ip_location", ""),
                    "image_list": ','.join([img.get('url', '') for img in image_list]),
                    "tag_list": ','.join([tag.get('name', '') for tag in tag_list if tag.get('type') == 'topic']),
                    "note_url": f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={note_detail.get('xsec_token')}&xsec_source=pc_search",
                    "xsec_token": note_detail.get("xsec_token"),
                }
                
                # Save to storage (will use the same formatting logic)
                await xhs_store.update_xhs_note(note_detail)
                
                # 2. Download images immediately
                await self.get_notice_media(note_detail)
                
                # 3. Export to markdown immediately - use formatted data
                await self.export_note_to_markdown(formatted_note)
                
                # 4. Mark as fetched in JSON immediately
                note_id_manager.mark_as_fetched(note_id)
                async with fetched_ids_lock:
                    fetched_ids.append(note_id)
                
                saved_count += 1
                utils.logger.info(
                    f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
                    f"✓ Processed note {note_id}: '{note_title}' ({saved_count}/{total_count})"
                )
                
                # Batch save every 10 notes to reduce I/O
                async with fetched_ids_lock:
                    if len(fetched_ids) >= 10:
                        await note_id_manager.save_note_ids()
                        utils.logger.info(f"[XiaoHongShuCrawler] 📝 Batch saved {len(fetched_ids)} note statuses to note_ids.json")
                        fetched_ids.clear()
                
            except Exception as e:
                failed_count += 1
                utils.logger.error(
                    f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
                    f"Error processing note {note_id}: {e}"
                )
                import traceback
                utils.logger.error(traceback.format_exc())
        
        # Create tasks for all notes - each will fetch and process immediately
        tasks = [fetch_and_process_note(post_item) for post_item in note_list]
        
        # Run all tasks concurrently - each completes independently
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Final save for any remaining IDs
        if fetched_ids:
            await note_id_manager.save_note_ids()
            utils.logger.info(f"[XiaoHongShuCrawler] 📝 Final batch saved {len(fetched_ids)} note statuses to note_ids.json")
        
        utils.logger.info(
            f"[XiaoHongShuCrawler.fetch_creator_notes_detail_with_manager] "
            f"Completed: {saved_count} saved, {filtered_count} filtered, {failed_count} failed/skipped "
            f"(total: {saved_count + filtered_count + failed_count}/{total_count})"
        )
    
    async def export_note_to_markdown(self, note_detail: Dict):
        """Export a single note to markdown file"""
        if config.SAVE_DATA_OPTION != "json":
            return
        
        try:
            from tools.markdown_exporter import export_note_to_markdown
            from pathlib import Path
            from var import current_creator_id_var
            
            # Determine output directory based on creator mode
            creator_id = current_creator_id_var.get()
            base_dir = Path(config.SAVE_DATA_PATH or "data") / config.PLATFORM
            
            if creator_id:
                output_dir = base_dir / f"creator_{creator_id}" / "markdown_export"
            else:
                output_dir = base_dir / "markdown_export"
            
            # Export to markdown
            await export_note_to_markdown(note_detail, output_dir)
            
        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler.export_note_to_markdown] Error: {e}")

    async def fetch_creator_notes_detail(self, note_list: List[Dict]):
        """Concurrently obtain the specified post list and save the data
        
        This method also handles date filtering since timestamps are only available
        after fetching note details.
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_note_detail_async_task(
                note_id=post_item.get("note_id"),
                xsec_source=post_item.get("xsec_source"),
                xsec_token=post_item.get("xsec_token"),
                semaphore=semaphore,
            ) for post_item in note_list
        ]

        note_details = await asyncio.gather(*task_list)
        
        # Apply date filtering if configured
        import re
        from datetime import datetime
        
        start_timestamp = None
        end_timestamp = None
        
        if config.CRAWLER_START_DATE:
            try:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', config.CRAWLER_START_DATE):
                    start_dt = datetime.strptime(config.CRAWLER_START_DATE, '%Y-%m-%d')
                    start_timestamp = int(start_dt.timestamp() * 1000)
            except ValueError:
                pass
        
        if config.CRAWLER_END_DATE:
            try:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', config.CRAWLER_END_DATE):
                    end_dt = datetime.strptime(config.CRAWLER_END_DATE, '%Y-%m-%d')
                    end_timestamp = int((end_dt.timestamp() + 86399.999) * 1000)
            except ValueError:
                pass
        
        saved_count = 0
        filtered_count = 0
        
        for note_detail in note_details:
            if not note_detail:
                continue
            
            # Check date filter
            note_time = note_detail.get("time", 0)
            note_id = note_detail.get("note_id", "unknown")
            note_title = note_detail.get("title", "")[:40]
            
            # Apply date filtering
            if start_timestamp and note_time < start_timestamp:
                filtered_count += 1
                readable_time = datetime.fromtimestamp(note_time / 1000).strftime('%Y-%m-%d %H:%M:%S') if note_time else "N/A"
                utils.logger.info(
                    f"[XiaoHongShuCrawler.fetch_creator_notes_detail] Filtered out (before start date): "
                    f"'{note_title}' ({readable_time})"
                )
                continue
            
            if end_timestamp and note_time > end_timestamp:
                filtered_count += 1
                readable_time = datetime.fromtimestamp(note_time / 1000).strftime('%Y-%m-%d %H:%M:%S') if note_time else "N/A"
                utils.logger.info(
                    f"[XiaoHongShuCrawler.fetch_creator_notes_detail] Filtered out (after end date): "
                    f"'{note_title}' ({readable_time})"
                )
                continue
            
            # Save notes within date window
            await xhs_store.update_xhs_note(note_detail)
            await self.get_notice_media(note_detail)
            saved_count += 1
        
        if start_timestamp or end_timestamp:
            utils.logger.info(
                f"[XiaoHongShuCrawler.fetch_creator_notes_detail] Date filtering: "
                f"{saved_count} saved, {filtered_count} filtered out"
            )

    async def get_specified_notes(self):
        """Get the information and comments of the specified post

        Note: Must specify note_id, xsec_source, xsec_token
        """
        get_note_detail_task_list = []
        for full_note_url in config.XHS_SPECIFIED_NOTE_URL_LIST:
            note_url_info: NoteUrlInfo = parse_note_info_from_note_url(full_note_url)
            utils.logger.info(f"[XiaoHongShuCrawler.get_specified_notes] Parse note url info: {note_url_info}")
            crawler_task = self.get_note_detail_async_task(
                note_id=note_url_info.note_id,
                xsec_source=note_url_info.xsec_source,
                xsec_token=note_url_info.xsec_token,
                semaphore=asyncio.Semaphore(config.MAX_CONCURRENCY_NUM),
            )
            get_note_detail_task_list.append(crawler_task)

        need_get_comment_note_ids = []
        xsec_tokens = []
        note_details = await asyncio.gather(*get_note_detail_task_list)
        for note_detail in note_details:
            if note_detail:
                need_get_comment_note_ids.append(note_detail.get("note_id", ""))
                xsec_tokens.append(note_detail.get("xsec_token", ""))
                await xhs_store.update_xhs_note(note_detail)
                await self.get_notice_media(note_detail)
        await self.batch_get_note_comments(need_get_comment_note_ids, xsec_tokens)

    async def get_note_detail_async_task(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        semaphore: asyncio.Semaphore,
        note_id_manager=None,  # Optional: for marking not_found notes
    ) -> Optional[Dict]:
        """Get note detail

        Args:
            note_id:
            xsec_source:
            xsec_token:
            semaphore:

        Returns:
            Dict: note detail
        """
        note_detail = None
        utils.logger.info(f"[get_note_detail_async_task] Begin get note detail, note_id: {note_id}")
        async with semaphore:
            try:
                try:
                    note_detail = await self.xhs_client.get_note_by_id(note_id, xsec_source, xsec_token)
                except RetryError:
                    pass

                if not note_detail:
                    try:
                        note_detail = await self.xhs_client.get_note_by_id_from_html(note_id, xsec_source, xsec_token,
                                                                                     enable_cookie=True)
                    except BrowserContextClosedError:
                        utils.logger.warning(
                            f"[get_note_detail_async_task] Browser context closed for {note_id}, "
                            f"attempting to recreate browser and page..."
                        )
                        
                        # Recreate browser context and page
                        try:
                            # Close old context if possible (may already be closed)
                            try:
                                if self.browser_context:
                                    await self.browser_context.close()
                            except:
                                pass
                            
                            # Recreate browser context using the same method as start()
                            playwright_proxy_format = None
                            if config.ENABLE_IP_PROXY and self.ip_proxy_pool:
                                ip_proxy_info = await self.ip_proxy_pool.get_proxy()
                                playwright_proxy_format, _ = utils.format_proxy_info(ip_proxy_info)
                            
                            # Get playwright instance - we need to access it from the running context
                            # Since we're inside async_playwright() context, we can't easily recreate it here
                            # Instead, let's just create a new page from a new context if CDP manager exists
                            if self.cdp_manager:
                                # For CDP mode, reconnect to browser
                                utils.logger.info("[get_note_detail_async_task] Reconnecting to CDP browser...")
                                self.browser_context = await self.cdp_manager.get_browser_context()
                            else:
                                # For non-CDP mode, we're in trouble - can't recreate playwright context easily
                                utils.logger.error(
                                    "[get_note_detail_async_task] Cannot recreate browser context in non-CDP mode. "
                                    "Please restart the crawler."
                                )
                                return None
                            
                            # Create new page
                            self.context_page = await self.browser_context.new_page()
                            await self.context_page.goto(self.index_url)
                            utils.logger.info("[get_note_detail_async_task] Successfully recreated browser context and page")
                            
                            # Update xhs_client with new context and page
                            self.xhs_client.browser_context = self.browser_context
                            self.xhs_client.playwright_page = self.context_page
                            
                            # Update cookies
                            await self.xhs_client.update_cookies(browser_context=self.browser_context)
                            
                            # Retry getting note detail with new context
                            note_detail = await self.xhs_client.get_note_by_id_from_html(
                                note_id, xsec_source, xsec_token, enable_cookie=True
                            )
                            utils.logger.info(
                                f"[get_note_detail_async_task] Successfully fetched note {note_id} after browser recreation"
                            )
                            
                        except Exception as recreate_err:
                            utils.logger.error(
                                f"[get_note_detail_async_task] Failed to recreate browser context: {recreate_err}"
                            )
                            import traceback
                            utils.logger.error(traceback.format_exc())
                            return None
                    
                    if not note_detail:
                        # Anti-crawler mechanism triggered - sleep and return None instead of raising
                        sleep_time = random.uniform(25, 35)
                        utils.logger.warning(
                            f"[get_note_detail_async_task] Failed to get note detail for {note_id}, "
                            f"possibly due to anti-crawler mechanism. Sleeping for {sleep_time:.1f}s..."
                        )
                        await asyncio.sleep(sleep_time)
                        utils.logger.info(f"[get_note_detail_async_task] Resumed after anti-crawler sleep for {note_id}")
                        return None

                note_detail.update({"xsec_token": xsec_token, "xsec_source": xsec_source})

                # Sleep after fetching note detail
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[get_note_detail_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note {note_id}")

                return note_detail

            except NoteNotFoundError as ex:
                utils.logger.warning(f"[XiaoHongShuCrawler.get_note_detail_async_task] Note not found: {note_id}, {ex}")
                # Mark as not_found if manager is available
                if note_id_manager:
                    note_id_manager.mark_as_not_found(note_id)
                    utils.logger.info(f"[XiaoHongShuCrawler.get_note_detail_async_task] Marked note {note_id} as not_found")
                return None
            except DataFetchError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] Get note detail error: {ex}")
                # Anti-crawler or network issue - sleep before continuing
                sleep_time = random.uniform(25, 35)
                utils.logger.warning(f"[get_note_detail_async_task] Sleeping {sleep_time:.1f}s due to DataFetchError...")
                await asyncio.sleep(sleep_time)
                return None
            except KeyError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None
            except Exception as ex:
                # Catch any other unexpected errors
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] Unexpected error for {note_id}: {ex}")
                sleep_time = random.uniform(25, 35)
                utils.logger.warning(f"[get_note_detail_async_task] Sleeping {sleep_time:.1f}s due to unexpected error...")
                await asyncio.sleep(sleep_time)
                return None

    async def batch_get_note_comments(self, note_list: List[str], xsec_tokens: List[str]):
        """Batch get note comments"""
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Begin batch get note comments, note list: {note_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for index, note_id in enumerate(note_list):
            task = asyncio.create_task(
                self.get_comments(note_id=note_id, xsec_token=xsec_tokens[index], semaphore=semaphore),
                name=note_id,
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(self, note_id: str, xsec_token: str, semaphore: asyncio.Semaphore):
        """Get note comments with keyword filtering and quantity limitation"""
        async with semaphore:
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Begin get note id comments {note_id}")
            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            await self.xhs_client.get_note_all_comments(
                note_id=note_id,
                xsec_token=xsec_token,
                crawl_interval=crawl_interval,
                callback=xhs_store.batch_update_xhs_note_comments,
                max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
            )

            # Sleep after fetching comments
            await asyncio.sleep(crawl_interval)
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for note {note_id}")

    async def create_xhs_client(self, httpx_proxy: Optional[str]) -> XiaoHongShuClient:
        """Create Xiaohongshu client"""
        utils.logger.info("[XiaoHongShuCrawler.create_xhs_client] Begin create Xiaohongshu API client ...")
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        xhs_client_obj = XiaoHongShuClient(
            proxy=httpx_proxy,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/json;charset=UTF-8",
                "origin": "https://www.xiaohongshu.com",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": "https://www.xiaohongshu.com/",
                "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Cookie": cookie_str,
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
            browser_context=self.browser_context,  # Pass browser context for page recreation
        )
        return xhs_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[XiaoHongShuCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            # feat issue #14
            # we will save login state to avoid login every time
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser using CDP mode"""
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Display browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[XiaoHongShuCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler] CDP mode launch failed, falling back to standard mode: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def close(self):
        """Close browser context"""
        # Special handling if using CDP mode
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[XiaoHongShuCrawler.close] Browser context closed ...")

    async def get_notice_media(self, note_detail: Dict):
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[XiaoHongShuCrawler.get_notice_media] Crawling image mode is not enabled")
            return
        # Only download images, skip images
        await self.get_note_images(note_detail)
        # await self.get_note_images(note_detail)
        #await self.get_notice_video(note_detail)

    async def get_note_images(self, note_item: Dict):
        """Get note images. Please use get_notice_media

        Args:
            note_item: Note item dictionary
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")
        image_list: List[Dict] = note_item.get("image_list", [])

        for img in image_list:
            if img.get("url_default") != "":
                img.update({"url": img.get("url_default")})

        if not image_list:
            return
        picNum = 0
        for pic in image_list:
            url = pic.get("url")
            if not url:
                continue
            content = await self.xhs_client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum}.jpg"
            picNum += 1
            await xhs_store.update_xhs_note_image(note_id, content, extension_file_name)

    async def get_notice_video(self, note_item: Dict):
        """Get note videos. Please use get_notice_media

        Args:
            note_item: Note item dictionary
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")

        videos = xhs_store.get_video_url_arr(note_item)

        if not videos:
            return
        videoNum = 0
        for url in videos:
            content = await self.xhs_client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{videoNum}.mp4"
            videoNum += 1
            await xhs_store.update_xhs_note_video(note_id, content, extension_file_name)
