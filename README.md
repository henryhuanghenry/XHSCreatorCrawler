# 小红书创作者爬虫 - XHS Creator Crawler 🔥

<div align="center">

[![GitHub Stars](https://img.shields.io/github/stars/henryhuanghenry/XHSCreatorCrawler?style=social)](https://github.com/henryhuanghenry/XHSCreatorCrawler/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/henryhuanghenry/XHSCreatorCrawler?style=social)](https://github.com/henryhuanghenry/XHSCreatorCrawler/network/members)
[![License](https://img.shields.io/github/license/henryhuanghenry/XHSCreatorCrawler)](https://github.com/henryhuanghenry/XHSCreatorCrawler/blob/main/LICENSE)

</div>

---

## 📌 项目说明 | Project Description

> **本项目基于 [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 开发**  
> **This project is forked from [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)**

本仓库专注于**小红书创作者爬取**功能的深度优化，新增了**全量模式**和**增量模式**两种爬取策略，支持断点续爬、Markdown导出等实用功能。

> **✨ 本项目通过 Vibe Coding 方式开发**  
> 本项目的大部分功能优化和代码改进都是通过 **Vibe Coding**（AI辅助编程）的方式对原项目进行修改和增强的。这种开发方式充分利用了AI的能力来提升开发效率，同时保持代码质量和项目可维护性。

This repository focuses on **Xiaohongshu (RED) creator crawling** with enhanced **full mode** and **incremental mode** strategies, supporting resume from breakpoint and Markdown export.

> **✨ Developed with Vibe Coding**  
> Most features and improvements in this project were developed and enhanced through **Vibe Coding** (AI-assisted programming). This development approach leverages AI capabilities to boost development efficiency while maintaining code quality and project maintainability.

---

## ⚠️ 免责声明 | Disclaimer

> **请以学习为目的使用本仓库**
> 
> 本仓库的所有内容仅供学习和参考之用，**禁止用于商业用途**。任何人或组织不得将本仓库的内容用于非法用途或侵犯他人合法权益。本仓库所涉及的爬虫技术仅用于学习和研究，不得用于对其他平台进行大规模爬虫或其他非法行为。对于因使用本仓库内容而引起的任何法律责任，本仓库不承担任何责任。
>
> **For educational purposes only.** This repository is for learning and reference only. Commercial use is prohibited. Any illegal activities or infringement of others' rights using this code are not allowed.

---

## ✨ 核心功能 | Core Features

### 🎯 小红书创作者爬取增强 | Enhanced XHS Creator Crawling

本项目针对**小红书创作者爬取**进行了深度改进，新增以下核心功能：

#### 1️⃣ 全量模式 (Full Mode)

完整爬取创作者的所有笔记，支持断点续爬。

**Crawl all notes from a creator with resume-from-breakpoint support.**

**工作流程 | Workflow:**

⚠️ **重要提示**: 全量模式分为两个阶段，Phase 1 完成后才会开始 Phase 2  
⚠️ **Important**: Full mode has two phases, Phase 2 starts only after Phase 1 completes

1. **Phase 1: 获取所有笔记列表** | Fetch all note IDs
   - 自动翻页获取创作者的全部笔记ID
   - 支持断点续爬（中断后可继续）
   - 断点文件路径：`data/xhs/creator_{creator_id}/crawl_cursor.json`
   - Auto-pagination to fetch all note IDs
   - Resume from breakpoint if interrupted
   - Breakpoint file: `data/xhs/creator_{creator_id}/crawl_cursor.json`

2. **Phase 2: 逐个爬取笔记内容** | Fetch note details
   - 根据本地存储的笔记列表逐个获取详细内容
   - 自动跳过已爬取的笔记
   - 笔记列表保存路径：`data/xhs/creator_{creator_id}/note_ids.json`
   - Fetch details for each note ID
   - Skip already fetched notes
   - Note list saved at: `data/xhs/creator_{creator_id}/note_ids.json`

3. **导出为Markdown** | Export to Markdown
   - 自动将每篇笔记导出为Markdown文件
   - 保存路径：`data/xhs/markdown_export/`
   - 文件命名：`yy_mm_dd_hh_笔记标题.md`
   - Auto-export each note to Markdown format
   - Saved at: `data/xhs/markdown_export/`
   - Filename format: `yy_mm_dd_hh_note_title.md`

4. **自动调起浏览器阅读** | Auto browser reading mode
   - 触发反爬机制时，自动调起浏览器阅读模式
   - 每次获取约300条笔记，而后需等待约8小时
   - Automatically triggers browser reading when anti-crawler detected
   - Can fetch ~300 notes per crawling, and then requires ~8h waiting

**启动命令 | Command:**

```bash
# 全量模式爬取（默认）
uv run main.py --platform xhs --lt qrcode --type creator \
  --creator_id "XXXX"

# Full mode (default)
# Replace creator_id with the target creator's ID from their profile URL
```

**配置文件设置 | Config File:**

在 `config/base_config.py` 中设置：
```python
CREATOR_CRAWL_MODE = "full"  # 全量模式 | Full mode
```

---

#### 2️⃣ 增量模式 (Incremental Mode)

仅爬取最新发布且本地未爬取的笔记，适合定期更新。

**Only crawl new notes that are not yet fetched locally, ideal for periodic updates.**

**工作原理 | How it works:**

1. **检测新笔记** | Detect new notes
   - 拉取创作者最新的笔记列表
   - 与本地已保存的笔记ID对比
   - 自动停止于已存在笔记达到阈值时
   - Fetch latest note list from creator
   - Compare with local note IDs
   - Auto-stop when existing notes ratio exceeds threshold

2. **爬取新内容** | Fetch new content
   - 仅爬取新发现的笔记
   - 自动跳过已存在的笔记
   - Only fetch newly discovered notes
   - Skip existing notes automatically

3. **自动导出** | Auto-export
   - 新笔记同样会导出为Markdown
   - New notes are exported to Markdown format

**启动命令 | Command:**

```bash
# 增量模式爬取
uv run main.py --platform xhs --lt qrcode --type creator \
  --creator_id "XXXX"

# Incremental mode
# Make sure CREATOR_CRAWL_MODE is set to "incremental" in config
```

**配置文件设置 | Config File:**

在 `config/base_config.py` 中设置：
```python
CREATOR_CRAWL_MODE = "incremental"  # 增量模式 | Incremental mode
INCREMENTAL_STOP_THRESHOLD = 0.5    # 停止阈值：50%已存在则停止 | Stop threshold: 50%
```

**说明 | Notes:**
- `INCREMENTAL_STOP_THRESHOLD = 0.5` 表示当单页中50%以上的笔记ID已存在时，停止爬取
- `0.5` means stop when 50% or more note IDs in a page already exist locally
- ⚠️ **首次使用**：如果本地无checkpoint文件，程序会提示切换到全量模式
- ⚠️ **First-time use**: If no local checkpoint exists, you'll be prompted to switch to full mode

---

## 🚀 快速开始 | Quick Start

### 📋 前置依赖 | Prerequisites

#### 1. 安装 uv (推荐 | Recommended)

```bash
# 安装 uv | Install uv
# 参考官方文档 | See official docs: https://docs.astral.sh/uv/getting-started/installation

# 验证安装 | Verify installation
uv --version
```

#### 2. 安装 Node.js

```bash
# 下载并安装 | Download and install
# 官网 | Official site: https://nodejs.org/
# 版本要求 | Version: >= 16.0.0
```

#### 3. 安装系统依赖（macOS）| Install system dependencies (macOS)

```bash
# macOS 用户需要先安装图像处理库 | macOS users need to install image libraries first
brew install jpeg zlib libtiff

# 如果遇到 Pillow 安装错误，执行上述命令后重新安装 | If Pillow installation fails, run above command and retry
```

#### 4. 安装项目依赖 | Install dependencies

```bash
# 进入项目目录 | Navigate to project directory
cd XHSCreatorCrawler

# 安装 Python 依赖 | Install Python dependencies
uv sync

# 安装浏览器驱动 | Install browser drivers
uv run playwright install
```

**常见问题 | Common Issues:**

如果遇到 `RequiredDependencyException: jpeg` 错误：
```bash
# macOS 解决方法 | macOS Solution
brew install jpeg zlib libtiff
uv sync  # 重新安装依赖 | Re-install dependencies
```

If you encounter `RequiredDependencyException: jpeg` error:
```bash
# Install required libraries
brew install jpeg zlib libtiff
uv sync  # Retry dependency installation
```

---

### 🎮 使用示例 | Usage Examples

#### 示例 1：全量爬取创作者笔记 | Example 1: Full mode

```bash
# 爬取指定创作者的所有笔记（全量模式）
uv run main.py --platform xhs --lt qrcode --type creator \
  --creator_id "XXXX"

# Crawl all notes from a creator (full mode)
# 1. QR code login will pop up
# 2. Scan QR code with Xiaohongshu app
# 3. Crawler starts fetching note IDs
# 4. Then fetches note details
# 5. Exports to Markdown automatically
```

**获取 creator_id 的方法 | How to get creator_id:**
1. 访问创作者主页 | Visit creator's profile
2. URL 格式为：`https://www.xiaohongshu.com/user/profile/{creator_id}?...`
3. 复制 URL 中的 creator_id

---

#### 示例 2：增量爬取最新笔记 | Example 2: Incremental mode

```bash
# 首先在 config/base_config.py 中设置 | First set in config/base_config.py:
# CREATOR_CRAWL_MODE = "incremental"

# 然后运行 | Then run:
uv run main.py --platform xhs --lt qrcode --type creator \
  --creator_id "XXXX"

# Incremental mode: only fetch new notes
# Ideal for daily/weekly updates
```

---

#### 示例 3：启用媒体下载 | Example 3: With media download

```bash
# 下载笔记中的图片和视频 | Download images and videos
uv run main.py --platform xhs --lt qrcode --type creator \
  --creator_id "XXXX" \
  --enable_get_media true

# Media files saved at:
# - Images: data/xhs/images/{note_id}/
# - Videos: data/xhs/videos/{note_id}/
```

---

#### 示例 4：按日期范围爬取 | Example 4: Date range crawling

```bash
# 爬取2024年的笔记 | Crawl notes from 2024
uv run main.py --platform xhs --lt qrcode --type creator \
  --creator_id "XXXX" \
  --start_date "2024-01-01" \
  --end_date "2024-12-31"

# 只爬取某个日期之后的笔记 | Crawl notes after a date
uv run main.py --platform xhs --lt qrcode --type creator \
  --creator_id "XXXX" \
  --start_date "2024-06-01"
```

---

## 📁 数据存储路径 | Data Storage Paths

```
data/xhs/
├── creator_{creator_id}/
│   ├── note_ids.json              # 笔记ID列表 | Note ID list
│   └── crawl_cursor.json          # 断点文件 | Breakpoint file
├── json/
│   ├── creator_contents_*.json    # 笔记内容 | Note content (JSON)
│   └── creator_comments_*.json    # 评论数据 | Comments (JSON)
├── images/                         # 图片 | Images
│   └── {note_id}/
│       ├── 0.jpg
│       └── 1.jpg
├── videos/                         # 视频 | Videos
│   └── {note_id}/
│       └── video_0.mp4
└── markdown_export/                # Markdown导出 | Markdown exports
    ├── 26_02_16_14_笔记标题1.md
    └── 26_02_15_18_笔记标题2.md
```

---

## 🔧 配置说明 | Configuration

### 核心配置文件 | Main Config File

配置文件路径：`config/base_config.py`  
Config file: `config/base_config.py`

```python
# === 创作者爬取模式配置 | Creator Crawl Mode ===
CREATOR_CRAWL_MODE = "incremental"  # "full" 或 "incremental" | "full" or "incremental"

# === 增量模式停止阈值 | Incremental Stop Threshold ===
INCREMENTAL_STOP_THRESHOLD = 0.5    # 0.0-1.0，建议 0.5 | Recommended: 0.5

# === 日期范围配置 | Date Range ===
CRAWLER_START_DATE = ""             # 开始日期（包含）| Start date (inclusive), e.g., "2024-01-01"
CRAWLER_END_DATE = ""               # 结束日期（包含）| End date (inclusive), e.g., "2024-12-31"

# === 最大笔记数 | Max Notes Count ===
CRAWLER_MAX_NOTES_COUNT = 10000     # 最多爬取笔记数 | Max notes to crawl

# === 媒体下载 | Media Download ===
ENABLE_GET_MEIDAS = False           # 是否下载图片/视频 | Download images/videos

# === 评论爬取 | Comment Crawling ===
ENABLE_GET_COMMENTS = False         # 是否爬取评论 | Crawl comments

# === 笔记获取顺序 | Note Fetch Order ===
CREATOR_NOTE_FETCH_ORDER = "sorted" # "random" 或 "sorted" | "random" or "sorted"

# === 是否获取已删除笔记 | Fetch Deleted Notes ===
FETCH_NOT_FOUND_NOTES = False       # False: 跳过已删除笔记 | Skip deleted notes
```

---

## 🆚 全量模式 vs 增量模式 | Full vs Incremental

| 特性 | 全量模式 (Full) | 增量模式 (Incremental) |
|------|----------------|----------------------|
| **适用场景** | 首次爬取、完整备份 | 定期更新、追踪最新内容 |
| **Use Case** | First-time crawl, full backup | Periodic updates, track new content |
| **爬取范围** | 所有笔记 | 仅新增笔记 |
| **Crawl Scope** | All notes | New notes only |
| **断点续爬** | ✅ 支持 | ❌ 不支持（不需要） |
| **Resume** | ✅ Supported | ❌ Not needed |
| **停止条件** | 爬完所有或达到上限 | 遇到已存在笔记达阈值 |
| **Stop Condition** | All notes or max count | Existing notes ratio > threshold |
| **速度** | 较慢（笔记多时） | 快速（仅爬新内容） |
| **Speed** | Slower (many notes) | Faster (new notes only) |
| **推荐频率** | 一次性或不定期 | 每天/每周 |
| **Frequency** | One-time or irregular | Daily/Weekly |

---

## 🛠️ 高级用法 | Advanced Usage

### 1. 断点续爬 | Resume from Breakpoint

全量模式下，如果爬取中断（网络问题、程序崩溃等），重新运行相同命令即可从断点继续。

In full mode, if crawling is interrupted, simply re-run the same command to resume.

**断点文件 | Breakpoint file:**
- 路径 | Path: `data/xhs/creator_{creator_id}/crawl_cursor.json`
- 内容 | Content: 包含当前爬取进度（cursor、已爬取笔记数等）| Contains current progress

**清空断点重新爬取 | Clear breakpoint to start over:**
```bash
rm -rf data/xhs/creator_{creator_id}/
```

---

### 2. 查看爬取统计 | View Crawl Statistics

运行时会输出详细统计信息：

```
==================================================
📊 小红书Creator增量模式 - 笔记统计
==================================================
✨ 本次发现的增量笔记数: 15 条
📦 存量未拉取笔记数: 120 条
总笔记数: 1500 条
已拉取: 1365 条
未拉取: 135 条
==================================================
```

---

### 3. Markdown 导出格式 | Markdown Export Format

导出的Markdown文件包含：
- ✅ 笔记标题和发布时间 | Note title and publish time
- ✅ 作者信息 | Author info
- ✅ 点赞、收藏、评论数 | Likes, favorites, comments count
- ✅ 完整笔记内容 | Full note content
- ✅ 图片（本地路径）| Images (local paths)
- ✅ 视频链接 | Video links
- ✅ 标签列表 | Tags
- ✅ 原文链接 | Original URL

**示例文件 | Example file:**
```
data/xhs/markdown_export/26_02_16_14_笔记XXX.md
```

---

## 🤝 贡献 | Contributing

欢迎提交 Issue 和 Pull Request！  
Issues and Pull Requests are welcome!

---

## 📜 许可证 | License

本项目采用与原项目相同的许可证：**非商业学习使用许可证 1.1 (NON-COMMERCIAL LEARNING LICENSE 1.1)**

**双重版权声明 | Dual Copyright:**
- **原始项目 | Original Project**: Copyright (c) 2024 relakkes@gmail.com
- **修改部分 | Modifications**: Copyright (c) 2026 github.com/henryhuanghenry

所有修改、增强和新增功能（包括全量/增量模式、断点续爬、Markdown导出等）的版权归 github.com/henryhuanghenry 所有，但依然遵循相同的非商业学习使用许可证。

**This project uses the same license as the original project: NON-COMMERCIAL LEARNING LICENSE 1.1**

**Dual Copyright Notice:**
- **Original Project**: Copyright (c) 2024 relakkes@gmail.com
- **Modifications**: Copyright (c) 2026 github.com/henryhuanghenry

All modifications, enhancements, and new features (including full/incremental modes, resume-from-breakpoint, Markdown export, etc.) are copyrighted by github.com/henryhuanghenry, but still comply with the same non-commercial learning license.

详见：[LICENSE](LICENSE)  
See: [LICENSE](LICENSE)

---

## 🙏 致谢 | Acknowledgments

特别感谢 [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 原项目提供的优秀基础架构。

Special thanks to [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) for the excellent foundation.

---

## 📞 联系方式 | Contact

如有问题或建议，欢迎通过以下方式联系：  
For questions or suggestions:

- GitHub Issues: [提交Issue](https://github.com/henryhuanghenry/XHSCreatorCrawler/issues)

---

<div align="center">

**⭐ 如果这个项目对您有帮助，请给个 Star 支持一下！**  
**⭐ If this project helps you, please give it a Star!**

</div>
