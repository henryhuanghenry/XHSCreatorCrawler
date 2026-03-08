# -*- coding: utf-8 -*-
"""
Markdown exporter for MediaCrawler
Export crawled posts to markdown files with images and videos
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import aiofiles
import httpx
import config


def sanitize_filename(filename: str) -> str:
    """
    Remove illegal characters and all punctuation from filename
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    # Remove all punctuation marks (both Chinese and English)
    # Keep only: letters, numbers, Chinese characters, underscores, and spaces
    import unicodedata
    import string
    
    # Chinese punctuation characters to remove
    chinese_punctuation = '！？｡。＂＃＄％＆＇（）＊＋，－／：；＜＝＞＠［＼］＾＿｀｛｜｝～｟｠｢｣､、〃》「」『』【】〔〕〖〗〘〙〚〛〜〝〞〟〰〾〿–—''‛""„‟…‧﹏'
    
    # Remove English punctuation
    translator = str.maketrans('', '', string.punctuation)
    filename = filename.translate(translator)
    
    # Remove Chinese punctuation
    for char in chinese_punctuation:
        filename = filename.replace(char, '')
    
    # Remove line breaks and tabs
    filename = filename.replace('\n', '').replace('\r', '').replace('\t', '')
    
    # Remove filesystem-illegal characters
    illegal_chars = r'[<>:"/\\|?*]'
    filename = re.sub(illegal_chars, '', filename)
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    
    # Replace multiple spaces with single space
    filename = re.sub(r'\s+', ' ', filename)
    
    # Limit filename length
    if len(filename) > 200:
        filename = filename[:200]
    
    return filename


def format_markdown_filename(note_item: Dict) -> str:
    """
    Format markdown filename according to requirements: yy_mm_dd_hh_title
    
    Args:
        note_item: Note item dictionary
        
    Returns:
        Formatted filename
    """
    # Get timestamp (milliseconds)
    timestamp = note_item.get('time', 0)
    if timestamp:
        dt = datetime.fromtimestamp(timestamp / 1000)
        date_prefix = dt.strftime('%y_%m_%d_%H')
    else:
        date_prefix = datetime.now().strftime('%y_%m_%d_%H')
    
    # Get and sanitize title
    title = note_item.get('title', 'untitled')
    title = sanitize_filename(title)
    
    # Combine: date_title.md
    filename = f"{date_prefix}_{title}.md"
    
    return filename


def get_image_markdown(image_url: str, alt_text: str = "image") -> str:
    """
    Get markdown format for image
    
    Args:
        image_url: Image URL
        alt_text: Alternative text for image
        
    Returns:
        Markdown image syntax
    """
    return f"![{alt_text}]({image_url})"


def get_video_local_path(note_id: str, video_num: int = 0) -> str:
    """
    Get local video file path
    
    Args:
        note_id: Note ID
        video_num: Video number
        
    Returns:
        Relative path to video file
    """
    return f"../videos/{note_id}/video_{video_num}.mp4"


async def download_image(image_url: str, save_path: Path) -> bool:
    """
    Download image from URL to local path
    
    Args:
        image_url: Image URL
        save_path: Local save path
        
    Returns:
        True if download successful, False otherwise
    """
    try:
        # Create directory if not exists
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download image
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(image_url, follow_redirects=True)
            response.raise_for_status()
            
            # Save to file
            async with aiofiles.open(save_path, 'wb') as f:
                await f.write(response.content)
        
        return True
    except Exception as e:
        print(f"Error downloading image {image_url}: {e}")
        return False


async def export_note_to_markdown(note_item: Dict, output_dir: Path) -> str:
    """
    Export a single note to markdown file
    
    Args:
        note_item: Note item dictionary
        output_dir: Output directory path
        
    Returns:
        Path to created markdown file
    """
    # Debug: Log the note_item structure
    from tools import utils
    utils.logger.info(f"[export_note_to_markdown] Processing note_id: {note_item.get('note_id')}")
    utils.logger.debug(f"[export_note_to_markdown] Note item keys: {list(note_item.keys())}")
    utils.logger.debug(f"[export_note_to_markdown] liked_count value: {note_item.get('liked_count')} (type: {type(note_item.get('liked_count'))})")
    utils.logger.debug(f"[export_note_to_markdown] note_url value: {note_item.get('note_url')}")
    
    # Create output directory if not exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    filename = format_markdown_filename(note_item)
    file_path = output_dir / filename
    
    # Build markdown content
    md_lines = []
    
    # Title - keep original title with all characters
    title = note_item.get('title', 'Untitled')
    # Clean up title for display (remove excessive newlines but keep content)
    title_display = title.replace('\n', ' ').strip()
    md_lines.append(f"# {title_display}\n")
    
    # Metadata
    md_lines.append("## 📋 基本信息\n")
    
    # Get values with proper defaults
    nickname = note_item.get('nickname') or note_item.get('user_id') or 'Unknown'
    note_type = note_item.get('type', 'unknown')
    liked_count = note_item.get('liked_count') or '0'
    collected_count = note_item.get('collected_count') or '0'
    comment_count = note_item.get('comment_count') or '0'
    share_count = note_item.get('share_count') or '0'
    
    md_lines.append(f"- **作者**: {nickname}")
    md_lines.append(f"- **类型**: {note_type}")
    md_lines.append(f"- **点赞**: {liked_count}")
    md_lines.append(f"- **收藏**: {collected_count}")
    md_lines.append(f"- **评论**: {comment_count}")
    md_lines.append(f"- **分享**: {share_count}")
    
    # Publish time
    timestamp = note_item.get('time', 0)
    if timestamp:
        dt = datetime.fromtimestamp(timestamp / 1000)
        md_lines.append(f"- **发布时间**: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Location
    ip_location = note_item.get('ip_location')
    if ip_location:
        md_lines.append(f"- **IP属地**: {ip_location}")
    
    # Original link - IMPORTANT: Always include if available
    note_url = note_item.get('note_url')
    if note_url:
        md_lines.append(f"- **原文链接**: {note_url}")
    
    md_lines.append("")
    
    # Description/Content
    desc = note_item.get('desc', '')
    if desc:
        md_lines.append("## 📝 内容\n")
        md_lines.append(desc)
        md_lines.append("")
    
    # Images
    note_id = note_item.get('note_id', '')
    image_list = note_item.get('image_list', '')
    if image_list:
        md_lines.append("## 🖼️ 图片\n")
        
        # Handle different image_list formats
        if isinstance(image_list, str):
            # Split by comma if it's a string
            image_urls = [url.strip() for url in image_list.split(',') if url.strip()]
        elif isinstance(image_list, list):
            # Extract URLs from list of dicts or list of strings
            image_urls = []
            for img in image_list:
                if isinstance(img, dict):
                    url = img.get('url') or img.get('url_default') or img.get('url_pre', '')
                    if url:
                        image_urls.append(url)
                elif isinstance(img, str):
                    image_urls.append(img)
        else:
            image_urls = []
        
        # Check for local images downloaded by the crawler
        # Determine base directory based on crawler mode
        from var import crawler_type_var, current_creator_id_var
        crawler_type = crawler_type_var.get()
        creator_id = current_creator_id_var.get()
        
        base_dir = Path(config.SAVE_DATA_PATH or "data") / config.PLATFORM
        if crawler_type == "creator" and creator_id:
            base_dir = base_dir / f"creator_{creator_id}"
        
        images_dir = base_dir / "images" / note_id
        
        for i, img_url in enumerate(image_urls, 1):
            # Check if image was already downloaded by the crawler
            # Images are named as: 0.jpg, 1.jpg, 2.jpg, etc.
            local_filename = f"{i-1}.jpg"  # Crawler uses 0-indexed naming
            local_path = images_dir / local_filename
            
            if local_path.exists():
                # Use local path
                relative_path = f"../images/{note_id}/{local_filename}"
                md_lines.append(get_image_markdown(relative_path, f"Image {i}"))
                # Add original URL as backup comment
                md_lines.append(f"<!-- Original URL: {img_url} -->")
            else:
                # If local image doesn't exist, download it
                # Determine file extension from URL
                ext = ".jpg"
                if ".png" in img_url.lower():
                    ext = ".png"
                elif ".webp" in img_url.lower():
                    ext = ".webp"
                
                # Try downloading
                download_filename = f"{i:03d}{ext}"
                download_path = images_dir / download_filename
                download_success = await download_image(img_url, download_path)
                
                if download_success:
                    relative_path = f"../images/{note_id}/{download_filename}"
                    md_lines.append(get_image_markdown(relative_path, f"Image {i}"))
                    md_lines.append(f"<!-- Original URL: {img_url} -->")
                else:
                    # Fallback: add original URL as comment only
                    md_lines.append(f"<!-- Image {i} not available: {img_url} -->")
            
            md_lines.append("")
    
    # Video
    note_type = note_item.get('type', '')
    note_id = note_item.get('note_id', '')
    if note_type == 'video' and note_id:
        md_lines.append("## 🎬 视频\n")
        
        # Determine base directory based on crawler mode
        from var import crawler_type_var, current_creator_id_var
        crawler_type = crawler_type_var.get()
        creator_id = current_creator_id_var.get()
        
        base_dir = Path(config.SAVE_DATA_PATH or "data") / config.PLATFORM
        if crawler_type == "creator" and creator_id:
            base_dir = base_dir / f"creator_{creator_id}"
        
        # Check if local video exists
        video_dir = base_dir / "videos" / note_id
        if video_dir.exists():
            # Use relative path to local video
            video_files = list(video_dir.glob("video_*.mp4"))
            for i, video_file in enumerate(video_files):
                relative_path = f"../videos/{note_id}/{video_file.name}"
                md_lines.append(f"**视频文件**: [{video_file.name}]({relative_path})\n")
        
        # Also include online video URL if available
        video_url = note_item.get('video_url', '')
        if video_url:
            md_lines.append(f"**在线视频**: [观看视频]({video_url})\n")
    
    # Tags
    tag_list = note_item.get('tag_list', '')
    if tag_list:
        md_lines.append("## 🏷️ 标签\n")
        
        # Handle different tag formats
        if isinstance(tag_list, str):
            tags = [tag.strip() for tag in tag_list.split(',') if tag.strip()]
        elif isinstance(tag_list, list):
            tags = tag_list
        else:
            tags = []
        
        # Format tags
        tag_badges = [f"`{tag}`" for tag in tags]
        md_lines.append(" ".join(tag_badges))
        md_lines.append("")
    
    # Footer
    md_lines.append("\n---")
    md_lines.append(f"\n*导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    # Write to file
    content = "\n".join(md_lines)
    async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
        await f.write(content)
    
    return str(file_path)


async def export_notes_from_json(json_file: Path, output_dir: Path = None) -> List[str]:
    """
    Export all notes from JSON file to markdown files
    
    Args:
        json_file: Path to JSON file containing notes
        output_dir: Output directory (default: create 'markdown' folder next to JSON file)
        
    Returns:
        List of created markdown file paths
    """
    # Read JSON file
    async with aiofiles.open(json_file, 'r', encoding='utf-8') as f:
        content = await f.read()
        notes = json.loads(content)
    
    # Determine output directory
    if output_dir is None:
        # Create 'markdown_export' folder in the same directory as JSON file
        base_dir = json_file.parent.parent  # data/xhs/json -> data/xhs
        output_dir = base_dir / "markdown_export"
    
    # Export each note
    created_files = []
    for note in notes:
        try:
            file_path = await export_note_to_markdown(note, output_dir)
            created_files.append(file_path)
        except Exception as e:
            print(f"Error exporting note {note.get('note_id', 'unknown')}: {e}")
    
    return created_files


async def export_latest_crawl_results(platform: str = None) -> List[str]:
    """
    Export latest crawl results to markdown
    
    Args:
        platform: Platform name (default: use config.PLATFORM)
        
    Returns:
        List of created markdown file paths
    """
    from var import crawler_type_var, current_creator_id_var
    
    if platform is None:
        platform = config.PLATFORM
    
    # Find base data directory
    base_dir = Path(config.SAVE_DATA_PATH or "data") / platform
    
    # Check if we're in creator mode with a specific creator
    crawler_type = crawler_type_var.get()
    creator_id = current_creator_id_var.get()
    
    if crawler_type == "creator" and creator_id:
        # Creator mode: use creator-specific directory
        data_dir = base_dir / f"creator_{creator_id}" / "json"
        output_dir = base_dir / f"creator_{creator_id}" / "markdown_export"
    else:
        # Default mode: use platform root directory
        data_dir = base_dir / "json"
        output_dir = base_dir / "markdown_export"
    
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        return []
    
    # Find latest content file
    content_files = sorted(data_dir.glob("*_contents_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not content_files:
        print(f"No content files found in {data_dir}")
        return []
    
    latest_file = content_files[0]
    print(f"Exporting from: {latest_file}")
    
    # Export to markdown with custom output directory
    created_files = await export_notes_from_json(latest_file, output_dir=output_dir)
    
    print(f"✅ Exported {len(created_files)} notes to markdown")
    
    return created_files


if __name__ == "__main__":
    import asyncio
    
    # Example usage
    asyncio.run(export_latest_crawl_results())
