# -*- coding: utf-8 -*-
"""
Note ID Manager for XiaoHongShu Creator Crawling
Manages note IDs storage, retrieval, and incremental detection
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from tools import utils


class NoteIdManager:
    """
    Manages note IDs for creator crawling with support for:
    1. Full mode: Crawl all note IDs from scratch
    2. Incremental mode: Only crawl new note IDs
    """
    
    def __init__(self, creator_id: str, base_path: str = "data/xhs"):
        """
        Initialize NoteIdManager
        
        Args:
            creator_id: Creator user ID
            base_path: Base data storage path
        """
        self.creator_id = creator_id
        self.base_path = Path(base_path)
        self.creator_dir = self.base_path / f"creator_{creator_id}"
        self.note_ids_file = self.creator_dir / "note_ids.json"
        self.cursor_file = self.creator_dir / "crawl_cursor.json"
        
        # Ensure directory exists
        self.creator_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory data structure
        self.note_records: Dict[str, Dict] = {}  # {date: {note_id: {"fetched": bool, "xsec_token": str, "xsec_source": str}}}
        self.current_cursor: str = ""  # Current pagination cursor
        self.last_save_time: float = 0  # Last save timestamp for throttling
        
    async def load_existing_ids(self) -> None:
        """Load existing note IDs from storage"""
        if not self.note_ids_file.exists():
            utils.logger.info(f"[NoteIdManager] No existing note IDs file for creator {self.creator_id}")
            self.note_records = {}
            return
            
        try:
            async with asyncio.Lock():
                with open(self.note_ids_file, 'r', encoding='utf-8') as f:
                    self.note_records = json.load(f)
            utils.logger.info(
                f"[NoteIdManager] Loaded {self._count_total_ids()} note IDs for creator {self.creator_id}"
            )
        except Exception as e:
            utils.logger.error(f"[NoteIdManager] Error loading note IDs: {e}")
            self.note_records = {}
    
    async def save_note_ids(self) -> None:
        """Save note IDs to storage"""
        try:
            async with asyncio.Lock():
                with open(self.note_ids_file, 'w', encoding='utf-8') as f:
                    json.dump(self.note_records, f, ensure_ascii=False, indent=2)
            utils.logger.info(
                f"[NoteIdManager] Saved {self._count_total_ids()} note IDs for creator {self.creator_id}"
            )
        except Exception as e:
            utils.logger.error(f"[NoteIdManager] Error saving note IDs: {e}")
    
    def add_note_ids(self, note_items: List[Dict], fetch_date: Optional[str] = None) -> int:
        """
        Add note IDs with their tokens to the manager
        
        Args:
            note_items: List of note dictionaries containing note_id, xsec_token, xsec_source
            fetch_date: Date of the fetch session (YYYY-MM-DD), defaults to today
            
        Returns:
            Number of new note IDs added
        """
        if fetch_date is None:
            fetch_date = datetime.now().strftime('%Y-%m-%d')
        
        if fetch_date not in self.note_records:
            self.note_records[fetch_date] = {}
        
        new_count = 0
        for note_item in note_items:
            note_id = note_item.get("note_id")
            if not note_id:
                continue
                
            # Check if note_id already exists in any date
            if not self._note_id_exists(note_id):
                self.note_records[fetch_date][note_id] = {
                    "fetched": False,
                    "not_found": False,
                    "xsec_token": note_item.get("xsec_token", ""),
                    "xsec_source": note_item.get("xsec_source", "pc_feed")
                }
                new_count += 1
        
        utils.logger.info(
            f"[NoteIdManager] Added {new_count} new note IDs (total: {len(note_items)}) on {fetch_date}"
        )
        return new_count
    
    def get_all_note_ids(self) -> Set[str]:
        """Get all note IDs across all dates"""
        all_ids = set()
        for date_records in self.note_records.values():
            all_ids.update(date_records.keys())
        return all_ids
    
    def get_unfetched_note_ids(self, include_not_found: bool = False) -> List[Dict]:
        """
        Get note items that haven't been fetched yet
        
        Args:
            include_not_found: Whether to include notes marked as not_found
        
        Returns:
            List of note item dicts with note_id, xsec_token, xsec_source
        """
        unfetched = []
        for date_records in self.note_records.values():
            for note_id, info in date_records.items():
                if not info.get("fetched", False):
                    # Skip not_found notes unless explicitly requested
                    if not include_not_found and info.get("not_found", False):
                        continue
                    unfetched.append({
                        "note_id": note_id,
                        "xsec_token": info.get("xsec_token", ""),
                        "xsec_source": info.get("xsec_source", "pc_feed")
                    })
        return unfetched
    
    def mark_as_fetched(self, note_id: str) -> bool:
        """
        Mark a note ID as fetched
        
        Args:
            note_id: Note ID to mark
            
        Returns:
            True if marked successfully, False if not found
        """
        for date_records in self.note_records.values():
            if note_id in date_records:
                date_records[note_id]["fetched"] = True
                return True
        return False
    
    def mark_as_not_found(self, note_id: str) -> bool:
        """
        Mark a note ID as not found (deleted/unavailable)
        
        Args:
            note_id: Note ID to mark
            
        Returns:
            True if marked successfully, False if not found
        """
        for date_records in self.note_records.values():
            if note_id in date_records:
                date_records[note_id]["not_found"] = True
                date_records[note_id]["fetched"] = True  # Also mark as fetched to skip in future
                return True
        return False
    
    def check_incremental_stop(self, new_note_ids: List[str], threshold: float = 0.5) -> bool:
        """
        Check if we should stop in incremental mode
        
        Args:
            new_note_ids: Newly fetched note IDs from API
            threshold: If more than this ratio already exists, stop crawling
            
        Returns:
            True if should stop, False otherwise
        """
        if not new_note_ids:
            return True
        
        existing_ids = self.get_all_note_ids()
        overlap_count = sum(1 for nid in new_note_ids if nid in existing_ids)
        overlap_ratio = overlap_count / len(new_note_ids)
        
        should_stop = overlap_ratio >= threshold
        
        if should_stop:
            utils.logger.info(
                f"[NoteIdManager] Incremental mode: {overlap_count}/{len(new_note_ids)} "
                f"({overlap_ratio:.1%}) IDs already exist, stopping"
            )
        
        return should_stop
    
    def _note_id_exists(self, note_id: str) -> bool:
        """Check if note ID exists in any date record"""
        for date_records in self.note_records.values():
            if note_id in date_records:
                return True
        return False
    
    def _count_total_ids(self) -> int:
        """Count total number of note IDs"""
        return len(self.get_all_note_ids())
    
    def get_stats(self) -> Dict:
        """Get statistics about stored note IDs"""
        all_ids = self.get_all_note_ids()
        unfetched = self.get_unfetched_note_ids()
        
        return {
            "total_ids": len(all_ids),
            "fetched": len(all_ids) - len(unfetched),
            "unfetched": len(unfetched),
            "dates": list(self.note_records.keys()),
        }
    
    def get_creator_dir(self) -> Path:
        """Get the creator's data directory path"""
        return self.creator_dir
    
    async def save_cursor(self, cursor: str, has_more: bool = True) -> None:
        """
        Save current pagination cursor to disk
        
        Args:
            cursor: Current cursor value
            has_more: Whether there are more pages
        """
        try:
            cursor_data = {
                "cursor": cursor,
                "has_more": has_more,
                "last_updated": datetime.now().isoformat(),
                "total_ids_fetched": self._count_total_ids()
            }
            async with asyncio.Lock():
                with open(self.cursor_file, 'w', encoding='utf-8') as f:
                    json.dump(cursor_data, f, ensure_ascii=False, indent=2)
            utils.logger.info(
                f"[NoteIdManager] Saved cursor: {cursor}, has_more: {has_more}, "
                f"total_ids: {cursor_data['total_ids_fetched']}"
            )
        except Exception as e:
            utils.logger.error(f"[NoteIdManager] Error saving cursor: {e}")
    
    async def load_cursor(self) -> Dict:
        """
        Load saved pagination cursor from disk
        
        Returns:
            Dict with cursor, has_more, last_updated, total_ids_fetched
            Returns empty dict if no saved cursor
        """
        if not self.cursor_file.exists():
            utils.logger.info(f"[NoteIdManager] No saved cursor found for creator {self.creator_id}")
            return {}
        
        try:
            async with asyncio.Lock():
                with open(self.cursor_file, 'r', encoding='utf-8') as f:
                    cursor_data = json.load(f)
            utils.logger.info(
                f"[NoteIdManager] Loaded cursor: {cursor_data.get('cursor', '')}, "
                f"has_more: {cursor_data.get('has_more', False)}, "
                f"last_updated: {cursor_data.get('last_updated', 'unknown')}"
            )
            return cursor_data
        except Exception as e:
            utils.logger.error(f"[NoteIdManager] Error loading cursor: {e}")
            return {}
    
    async def clear_cursor(self) -> None:
        """Clear saved cursor (called when crawling completes)"""
        try:
            if self.cursor_file.exists():
                self.cursor_file.unlink()
                utils.logger.info(f"[NoteIdManager] Cleared cursor for creator {self.creator_id}")
        except Exception as e:
            utils.logger.error(f"[NoteIdManager] Error clearing cursor: {e}")
    
    async def save_incremental(self, cursor: str = "", has_more: bool = True) -> None:
        """
        Save both note IDs and cursor incrementally (throttled to avoid too frequent writes)
        
        Args:
            cursor: Current cursor value
            has_more: Whether there are more pages
        """
        import time
        current_time = time.time()
        
        # Throttle saves to once per 5 seconds to avoid excessive I/O
        if current_time - self.last_save_time < 5:
            return
        
        self.last_save_time = current_time
        await self.save_note_ids()
        if cursor:
            await self.save_cursor(cursor, has_more)

