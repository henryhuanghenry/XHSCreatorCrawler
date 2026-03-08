# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/client.py
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
import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union
from urllib.parse import urlencode

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_not_exception_type

import config
from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import DataFetchError, IPBlockError, NoteNotFoundError, BrowserContextClosedError
from .field import SearchNoteType, SearchSortType
from .help import get_search_id
from .extractor import XiaoHongShuExtractor
from .playwright_sign import sign_with_playwright


class XiaoHongShuClient(AbstractApiClient, ProxyRefreshMixin):

    def __init__(
        self,
        timeout=60,  # If media crawling is enabled, Xiaohongshu long videos need longer timeout
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
        browser_context: Optional[BrowserContext] = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://edith.xiaohongshu.com"
        self._domain = "https://www.xiaohongshu.com"
        self.IP_ERROR_STR = "Network connection error, please check network settings or restart"
        self.IP_ERROR_CODE = 300012
        self.NOTE_NOT_FOUND_CODE = -510000
        self.NOTE_ABNORMAL_STR = "Note status abnormal, please check later"
        self.NOTE_ABNORMAL_CODE = -510001
        self.playwright_page = playwright_page
        self.browser_context = browser_context
        self.cookie_dict = cookie_dict
        self._extractor = XiaoHongShuExtractor()
        # Initialize proxy pool (from ProxyRefreshMixin)
        self.init_proxy_pool(proxy_ip_pool)

    async def _pre_headers(self, url: str, params: Optional[Dict] = None, payload: Optional[Dict] = None) -> Dict:
        """Request header parameter signing (using playwright injection method)

        Args:
            url: Request URL
            params: GET request parameters
            payload: POST request parameters

        Returns:
            Dict: Signed request header parameters
        """
        a1_value = self.cookie_dict.get("a1", "")

        # Determine request data, method and URI
        if params is not None:
            data = params
            method = "GET"
        elif payload is not None:
            data = payload
            method = "POST"
        else:
            raise ValueError("params or payload is required")

        # Generate signature using playwright injection method
        signs = await sign_with_playwright(
            page=self.playwright_page,
            uri=url,
            data=data,
            a1=a1_value,
            method=method,
        )

        headers = {
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "x-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"],
        }
        self.headers.update(headers)
        return self.headers

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1), retry=retry_if_not_exception_type(NoteNotFoundError))
    async def request(self, method, url, **kwargs) -> Union[str, Any]:
        """
        Wrapper for httpx common request method, processes request response
        Args:
            method: Request method
            url: Request URL
            **kwargs: Other request parameters, such as headers, body, etc.

        Returns:

        """
        # Check if proxy is expired before each request
        await self._refresh_proxy_if_expired()

        # return response.text
        return_response = kwargs.pop("return_response", False)
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)

        if response.status_code == 471 or response.status_code == 461:
            # someday someone maybe will bypass captcha
            verify_type = response.headers["Verifytype"]
            verify_uuid = response.headers["Verifyuuid"]
            msg = f"CAPTCHA appeared, request failed, Verifytype: {verify_type}, Verifyuuid: {verify_uuid}, Response: {response}"
            utils.logger.error(msg)
            raise Exception(msg)

        if return_response:
            return response.text
        data: Dict = response.json()
        if data["success"]:
            return data.get("data", data.get("success", {}))
        elif data["code"] == self.IP_ERROR_CODE:
            raise IPBlockError(self.IP_ERROR_STR)
        elif data["code"] in (self.NOTE_NOT_FOUND_CODE, self.NOTE_ABNORMAL_CODE):
            raise NoteNotFoundError(f"Note not found or abnormal, code: {data['code']}")
        else:
            err_msg = data.get("msg", None) or f"{response.text}"
            raise DataFetchError(err_msg)

    async def get(self, uri: str, params: Optional[Dict] = None) -> Dict:
        """
        GET request, signs request headers
        Args:
            uri: Request route
            params: Request parameters

        Returns:

        """
        headers = await self._pre_headers(uri, params)
        full_url = f"{self._host}{uri}"

        return await self.request(
            method="GET", url=full_url, headers=headers, params=params
        )

    async def post(self, uri: str, data: dict, **kwargs) -> Dict:
        """
        POST request, signs request headers
        Args:
            uri: Request route
            data: Request body parameters

        Returns:

        """
        headers = await self._pre_headers(uri, payload=data)
        json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return await self.request(
            method="POST",
            url=f"{self._host}{uri}",
            data=json_str,
            headers=headers,
            **kwargs,
        )

    async def get_note_media(self, url: str) -> Union[bytes, None]:
        # Check if proxy is expired before request
        await self._refresh_proxy_if_expired()

        async with httpx.AsyncClient(proxy=self.proxy) as client:
            try:
                response = await client.request("GET", url, timeout=self.timeout)
                response.raise_for_status()
                if not response.reason_phrase == "OK":
                    utils.logger.error(
                        f"[XiaoHongShuClient.get_note_media] request {url} err, res:{response.text}"
                    )
                    return None
                else:
                    return response.content
            except (
                httpx.HTTPError
            ) as exc:  # some wrong when call httpx.request method, such as connection error, client error, server error or response status code is not 2xx
                utils.logger.error(
                    f"[XiaoHongShuClient.get_aweme_media] {exc.__class__.__name__} for {exc.request.url} - {exc}"
                )  # Keep original exception type name for developer debugging
                return None

    async def query_self(self) -> Optional[Dict]:
        """
        Query self user info to check login state
        Returns:
            Dict: User info if logged in, None otherwise
        """
        uri = "/api/sns/web/v1/user/selfinfo"
        headers = await self._pre_headers(uri, params={})
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            response = await client.get(f"{self._host}{uri}", headers=headers)
            if response.status_code == 200:
                return response.json()
        return None

    async def pong(self) -> bool:
        """
        Check if login state is still valid by querying self user info
        Returns:
            bool: True if logged in, False otherwise
        """
        utils.logger.info("[XiaoHongShuClient.pong] Begin to check login state...")
        ping_flag = False
        try:
            self_info: Dict = await self.query_self()
            if self_info and self_info.get("data", {}).get("result", {}).get("success"):
                ping_flag = True
        except Exception as e:
            utils.logger.error(
                f"[XiaoHongShuClient.pong] Check login state failed: {e}, and try to login again..."
            )
            ping_flag = False
        utils.logger.info(f"[XiaoHongShuClient.pong] Login state result: {ping_flag}")
        return ping_flag

    async def update_cookies(self, browser_context: BrowserContext):
        """
        Update cookies method provided by API client, usually called after successful login
        Args:
            browser_context: Browser context object

        Returns:

        """
        cookie_str, cookie_dict = utils.convert_cookies(await browser_context.cookies())
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict

    async def get_note_by_keyword(
        self,
        keyword: str,
        search_id: str = get_search_id(),
        page: int = 1,
        page_size: int = 20,
        sort: SearchSortType = SearchSortType.GENERAL,
        note_type: SearchNoteType = SearchNoteType.ALL,
    ) -> Dict:
        """
        Search notes by keyword
        Args:
            keyword: Keyword parameter
            page: Page number
            page_size: Page data length
            sort: Search result sorting specification
            note_type: Type of note to search

        Returns:

        """
        uri = "/api/sns/web/v1/search/notes"
        data = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": search_id,
            "sort": sort.value,
            "note_type": note_type.value,
        }
        return await self.post(uri, data)

    async def get_note_by_id(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
    ) -> Dict:
        """
        Get note detail API
        Args:
            note_id: Note ID
            xsec_source: Channel source
            xsec_token: Token returned from search keyword result list

        Returns:

        """
        if xsec_source == "":
            xsec_source = "pc_search"

        data = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        uri = "/api/sns/web/v1/feed"
        res = await self.post(uri, data)
        if res and res.get("items"):
            res_dict: Dict = res["items"][0]["note_card"]
            return res_dict
        # When crawling frequently, some notes may have results while others don't
        utils.logger.error(
            f"[XiaoHongShuClient.get_note_by_id] get note id:{note_id} empty and res:{res}"
        )
        return dict()

    async def get_note_comments(
        self,
        note_id: str,
        xsec_token: str,
        cursor: str = "",
    ) -> Dict:
        """
        Get first-level comments API
        Args:
            note_id: Note ID
            xsec_token: Verification token
            cursor: Pagination cursor

        Returns:

        """
        uri = "/api/sns/web/v2/comment/page"
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": "",
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        return await self.get(uri, params)

    async def get_note_sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str,
        num: int = 10,
        cursor: str = "",
    ):
        """
        Get sub-comments under specified parent comment API
        Args:
            note_id: Post ID of sub-comments
            root_comment_id: Root comment ID
            xsec_token: Verification token
            num: Pagination quantity
            cursor: Pagination cursor

        Returns:

        """
        uri = "/api/sns/web/v2/comment/sub/page"
        params = {
            "note_id": note_id,
            "root_comment_id": root_comment_id,
            "num": str(num),
            "cursor": cursor,
            "image_formats": "jpg,webp,avif",
            "top_comment_id": "",
            "xsec_token": xsec_token,
        }
        return await self.get(uri, params)

    async def get_note_all_comments(
        self,
        note_id: str,
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        max_count: int = 10,
    ) -> List[Dict]:
        """
        Get all first-level comments under specified note, this method will continuously find all comment information under a post
        Args:
            note_id: Note ID
            xsec_token: Verification token
            crawl_interval: Crawl delay per note (seconds)
            callback: Callback after one note crawl ends
            max_count: Maximum number of comments to crawl per note
        Returns:

        """
        result = []
        comments_has_more = True
        comments_cursor = ""
        while comments_has_more and len(result) < max_count:
            comments_res = await self.get_note_comments(
                note_id=note_id, xsec_token=xsec_token, cursor=comments_cursor
            )
            comments_has_more = comments_res.get("has_more", False)
            comments_cursor = comments_res.get("cursor", "")
            if "comments" not in comments_res:
                utils.logger.info(
                    f"[XiaoHongShuClient.get_note_all_comments] No 'comments' key found in response: {comments_res}"
                )
                break
            comments = comments_res["comments"]
            if len(result) + len(comments) > max_count:
                comments = comments[: max_count - len(result)]
            if callback:
                await callback(note_id, comments)
            await asyncio.sleep(crawl_interval)
            result.extend(comments)
            sub_comments = await self.get_comments_all_sub_comments(
                comments=comments,
                xsec_token=xsec_token,
                crawl_interval=crawl_interval,
                callback=callback,
            )
            result.extend(sub_comments)
        return result

    async def get_comments_all_sub_comments(
        self,
        comments: List[Dict],
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        Get all second-level comments under specified first-level comments, this method will continuously find all second-level comment information under first-level comments
        Args:
            comments: Comment list
            xsec_token: Verification token
            crawl_interval: Crawl delay per comment (seconds)
            callback: Callback after one comment crawl ends

        Returns:

        """
        if not config.ENABLE_GET_SUB_COMMENTS:
            utils.logger.info(
                f"[XiaoHongShuCrawler.get_comments_all_sub_comments] Crawling sub_comment mode is not enabled"
            )
            return []

        result = []
        for comment in comments:
            try:
                note_id = comment.get("note_id")
                sub_comments = comment.get("sub_comments")
                if sub_comments and callback:
                    await callback(note_id, sub_comments)

                sub_comment_has_more = comment.get("sub_comment_has_more")
                if not sub_comment_has_more:
                    continue

                root_comment_id = comment.get("id")
                sub_comment_cursor = comment.get("sub_comment_cursor")

                while sub_comment_has_more:
                    try:
                        comments_res = await self.get_note_sub_comments(
                            note_id=note_id,
                            root_comment_id=root_comment_id,
                            xsec_token=xsec_token,
                            num=10,
                            cursor=sub_comment_cursor,
                        )

                        if comments_res is None:
                            utils.logger.info(
                                f"[XiaoHongShuClient.get_comments_all_sub_comments] No response found for note_id: {note_id}"
                            )
                            break
                        sub_comment_has_more = comments_res.get("has_more", False)
                        sub_comment_cursor = comments_res.get("cursor", "")
                        if "comments" not in comments_res:
                            utils.logger.info(
                                f"[XiaoHongShuClient.get_comments_all_sub_comments] No 'comments' key found in response: {comments_res}"
                            )
                            break
                        comments = comments_res["comments"]
                        if callback:
                            await callback(note_id, comments)
                        await asyncio.sleep(crawl_interval)
                        result.extend(comments)
                    except DataFetchError as e:
                        utils.logger.warning(
                            f"[XiaoHongShuClient.get_comments_all_sub_comments] Failed to get sub-comments for note_id: {note_id}, root_comment_id: {root_comment_id}, error: {e}. Skipping this comment's sub-comments."
                        )
                        break  # Break out of the sub-comment acquisition loop of the current comment and continue processing the next comment
                    except Exception as e:
                        utils.logger.error(
                            f"[XiaoHongShuClient.get_comments_all_sub_comments] Unexpected error when getting sub-comments for note_id: {note_id}, root_comment_id: {root_comment_id}, error: {e}"
                        )
                        break
            except Exception as e:
                utils.logger.error(
                    f"[XiaoHongShuClient.get_comments_all_sub_comments] Error processing comment: {comment.get('id', 'unknown')}, error: {e}. Continuing with next comment."
                )
                continue  # Continue to next comment
        return result

    async def get_creator_info(
        self, user_id: str, xsec_token: str = "", xsec_source: str = ""
    ) -> Dict:
        """
        Get user profile brief information by parsing user homepage HTML
        The PC user homepage has window.__INITIAL_STATE__ variable, just parse it

        Args:
            user_id: User ID
            xsec_token: Verification token (optional, pass if included in URL)
            xsec_source: Channel source (optional, pass if included in URL)

        Returns:
            Dict: Creator information
        """
        # Build URI, add xsec parameters to URL if available
        uri = f"/user/profile/{user_id}"
        if xsec_token and xsec_source:
            uri = f"{uri}?xsec_token={xsec_token}&xsec_source={xsec_source}"

        html_content = await self.request(
            "GET", self._domain + uri, return_response=True, headers=self.headers
        )
        return self._extractor.extract_creator_info_from_html(html_content)

    async def get_notes_by_creator(
        self,
        creator: str,
        cursor: str,
        page_size: int = 60,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> Dict:
        """
        Get creator's notes
        Args:
            creator: Creator ID
            cursor: Last note ID from previous page
            page_size: Page data length
            xsec_token: Verification token
            xsec_source: Channel source

        Returns:

        """
        uri = f"/api/sns/web/v1/user_posted"
        params = {
            "num": page_size,
            "cursor": cursor,
            "user_id": creator,
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
        }
        return await self.get(uri, params)

    async def get_all_notes_by_creator(
        self,
        user_id: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
        note_id_manager = None,
        start_cursor: str = "",
    ) -> List[Dict]:
        """
        Get all posts published by specified user, this method will continuously find all post information under a user
        
        NOTE: Date filtering is NOT performed here because the API only returns note IDs without timestamps.
        Timestamps are only available after fetching note details via callback.
        Date filtering should be done in the callback or after all notes are fetched.
        
        Args:
            user_id: User ID
            crawl_interval: Crawl delay (seconds)
            callback: Update callback function after one pagination crawl ends
            xsec_token: Verification token
            xsec_source: Channel source
            note_id_manager: NoteIdManager instance for incremental crawling
            start_cursor: Starting cursor for resuming from saved position

        Returns:

        """
        result = []
        notes_has_more = True
        notes_cursor = start_cursor  # Start from saved cursor if provided
        is_incremental_mode = config.CREATOR_CRAWL_MODE == "incremental" and note_id_manager is not None
        page_count = 0
        
        utils.logger.info(
            f"[XiaoHongShuClient.get_all_notes_by_creator] Starting to fetch notes for user {user_id}, "
            f"mode: {config.CREATOR_CRAWL_MODE}, max_count: {config.CRAWLER_MAX_NOTES_COUNT}"
        )
        
        while notes_has_more and len(result) < config.CRAWLER_MAX_NOTES_COUNT:
            page_count += 1
            utils.logger.info(
                f"[XiaoHongShuClient.get_all_notes_by_creator] Fetching page {page_count}, "
                f"cursor: {notes_cursor or 'initial'}"
            )
            
            notes_res = await self.get_notes_by_creator(
                user_id, notes_cursor, xsec_token=xsec_token, xsec_source=xsec_source
            )
            if not notes_res:
                utils.logger.error(
                    f"[XiaoHongShuClient.get_notes_by_creator] The current creator may have been banned by xhs, so they cannot access the data."
                )
                break

            notes_has_more = notes_res.get("has_more", False)
            notes_cursor = notes_res.get("cursor", "")
            
            utils.logger.info(
                f"[XiaoHongShuClient.get_all_notes_by_creator] Page {page_count} result: "
                f"has_more={notes_has_more}, cursor={notes_cursor}"
            )
            
            if "notes" not in notes_res:
                utils.logger.info(
                    f"[XiaoHongShuClient.get_all_notes_by_creator] No 'notes' key found in response: {notes_res}"
                )
                break

            notes = notes_res["notes"]
            utils.logger.info(
                f"[XiaoHongShuClient.get_all_notes_by_creator] Page {page_count}: got {len(notes)} notes "
                f"(total so far: {len(result)})"
            )

            # Check for incremental mode stop condition
            if is_incremental_mode:
                note_ids_in_page = [note.get("note_id") for note in notes]
                should_stop = note_id_manager.check_incremental_stop(
                    note_ids_in_page, 
                    threshold=config.INCREMENTAL_STOP_THRESHOLD
                )
                if should_stop:
                    utils.logger.info(
                        f"[XiaoHongShuClient.get_all_notes_by_creator] Stopping in incremental mode"
                    )
                    # Still add new notes from this page before stopping
                    notes_to_add = notes
                    if callback:
                        await callback(notes_to_add)
                    result.extend(notes_to_add)
                    break

            # Check CRAWLER_MAX_NOTES_COUNT limit
            remaining = config.CRAWLER_MAX_NOTES_COUNT - len(result)
            if remaining <= 0:
                utils.logger.info(f"[XiaoHongShuClient.get_all_notes_by_creator] Reached max notes count limit: {config.CRAWLER_MAX_NOTES_COUNT}")
                break
            
            notes_to_add = notes[:remaining]
            if callback:
                await callback(notes_to_add)

            result.extend(notes_to_add)
            
            # Save progress incrementally after each page - ONLY in full mode
            if note_id_manager and config.CREATOR_CRAWL_MODE == "full":
                await note_id_manager.save_incremental(
                    cursor=notes_cursor,
                    has_more=notes_has_more
                )
            
            await asyncio.sleep(crawl_interval)

        # Clear cursor when crawling completes successfully - ONLY in full mode
        if note_id_manager and not notes_has_more and config.CREATOR_CRAWL_MODE == "full":
            await note_id_manager.clear_cursor()
            utils.logger.info(
                f"[XiaoHongShuClient.get_all_notes_by_creator] Crawling completed, cleared cursor"
            )
        
        utils.logger.info(
            f"[XiaoHongShuClient.get_all_notes_by_creator] Finished getting notes for user {user_id}, total: {len(result)}"
        )
        return result

    async def get_note_short_url(self, note_id: str) -> Dict:
        """
        Get note short URL
        Args:
            note_id: Note ID

        Returns:

        """
        uri = f"/api/sns/web/short_url"
        data = {"original_url": f"{self._domain}/discovery/item/{note_id}"}
        return await self.post(uri, data=data, return_response=True)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1), retry=retry_if_not_exception_type((NoteNotFoundError, BrowserContextClosedError)))
    async def get_note_by_id_from_html(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        enable_cookie: bool = False,
    ) -> Optional[Dict]:
        """
        Get note details by parsing note detail page HTML using browser navigation
        This method uses the browser to visit the note detail page, which is more resistant to anti-crawler mechanisms
        and allows you to see what's happening in the browser (captchas, blocks, etc.)
        If the browser page is closed, it will be recreated automatically
        
        Args:
            note_id: Note ID
            xsec_source: xsec source
            xsec_token: xsec token
            enable_cookie: Whether to enable cookies

        Returns:
            Optional[Dict]: Note detail dict or None if failed
        """
        url = (
            "https://www.xiaohongshu.com/explore/"
            + note_id
            + f"?xsec_token={xsec_token}&xsec_source={xsec_source}"
        )
        
        # Check if page is closed and recreate if needed
        try:
            if not self.playwright_page or self.playwright_page.is_closed():
                if self.browser_context:
                    # Check if browser_context is still valid
                    try:
                        # Try to check if context is still alive by accessing its pages
                        _ = self.browser_context.pages
                        utils.logger.warning(
                            f"[get_note_by_id_from_html] Browser page is closed, creating new page for note {note_id}"
                        )
                        self.playwright_page = await self.browser_context.new_page()
                        utils.logger.info("[get_note_by_id_from_html] Successfully created new browser page")
                    except Exception as ctx_err:
                        utils.logger.error(
                            f"[get_note_by_id_from_html] Browser context is also closed: {ctx_err}"
                        )
                        # Raise a custom exception to signal that browser context needs recreation
                        from .exception import BrowserContextClosedError
                        raise BrowserContextClosedError("Browser context has been closed and needs to be recreated")
                else:
                    utils.logger.error(
                        f"[get_note_by_id_from_html] Browser context not available, cannot recreate page"
                    )
                    return None
        except Exception as e:
            # If it's our custom exception, re-raise it
            from .exception import BrowserContextClosedError
            if isinstance(e, BrowserContextClosedError):
                raise
            utils.logger.error(f"[get_note_by_id_from_html] Error checking/recreating page: {e}")
            return None
        
        # Use browser to navigate to the note detail page
        utils.logger.info(f"[get_note_by_id_from_html] Using browser to visit note detail page: {url}")
        
        try:
            response = await self.playwright_page.goto(
                url,
                wait_until="networkidle",
                timeout=30000
            )
            
            if response is None or response.status >= 400:
                utils.logger.error(
                    f"[get_note_by_id_from_html] Failed to load page, status: {response.status if response else 'None'}"
                )
                return None
            
            # Wait for JavaScript to render
            await self.playwright_page.wait_for_timeout(2000)
            
            # Get the page HTML content
            html = await self.playwright_page.content()
            
            utils.logger.info(f"[get_note_by_id_from_html] Successfully loaded page for note {note_id}")
            
            return self._extractor.extract_note_detail_from_html(note_id, html)
            
        except Exception as e:
            utils.logger.error(f"[get_note_by_id_from_html] Browser navigation failed for note {note_id}: {e}")
            return None
