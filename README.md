# PickCat 挖掘机

一个基于 Python 和 Tkinter 的 PickCat 论坛帖子采集工具。可以按 UTC 日期范围查找帖子、查看帖子信息，并将选中的帖子或全部结果导出为 ZIP 压缩包。

## 功能

- 按开始日期和结束日期查找帖子，日期范围包含首尾两天。
- 查看帖子的日期、标题、作者、评论数和点赞数。
- 支持在结果列表中多选，并将选中帖子或全部帖子批量保存为 ZIP。
- ZIP 中每篇帖子保存为 Markdown 文件，并附带包含帖子信息的 `manifest.json`。
- HTML 正文转换为 Markdown；帖子图片的站内 `/api/v1/files/` 地址会转换为完整地址。
- 查询和 ZIP 打包在后台运行，减少等待时界面无响应的情况。

## 环境要求

- Python 3.10 或更高版本。
- 可用的网络连接。
- 支持 Tkinter 的 Python 安装（Windows 的官方 Python 安装包通常已包含 Tkinter）。

## 安装

在项目目录打开终端，运行：

```powershell
python -m pip install -r requirements.txt
```

如果 Windows 上 `python` 命令不可用，也可以尝试：

```powershell
py -m pip install -r requirements.txt
```

## 启动

```powershell
python Digger.py
```

也可以使用：

```powershell
py Digger.py
```

## 使用方法

1. 在开始日期和结束日期输入框中填写日期，格式为 `YYYY-MM-DD`，例如 `2026-10-01`。
2. 点击“查找帖子”。程序会按 UTC 日期查询该日期范围内的帖子，并读取帖子内容。
3. 查找完成后，在列表中选择一篇或多篇帖子，点击“保存选中为 ZIP”；或者点击“保存全部为 ZIP”导出所有已成功读取的帖子。
4. 在文件保存对话框中选择 ZIP 文件的保存位置。

ZIP 文件结构示例：

```text
pickcat-posts-2026-10-07.zip
├── posts/
│   ├── 123.md
│   └── 456.md
└── manifest.json
```

## 依赖

运行时 Python 包列在 [`requirements.txt`](./requirements.txt) 中。Tkinter、JSON、线程和 ZIP 等功能使用 Python 标准库，无需单独安装。
