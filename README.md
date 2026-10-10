# PickCat 挖掘机

一个基于 Python 和 Tkinter 的 PickCat 论坛帖子采集工具。可以按 UTC 日期范围查找帖子、查看帖子信息和历史版本，并将选中的帖子或全部结果导出为 ZIP 压缩包。

## 功能

- 从日期下拉菜单选择开始和结束日期（不早于 2026-09-09 开站日），按 UTC 日期范围查找帖子，日期范围包含首尾两天。
- 查看帖子的日期、标题、主题标签、作者、评论数和点赞数。
- 按关键词筛选标题和正文，也可以限定只搜索标题或正文。
- 双击帖子可在浏览器中打开原网站；选择帖子后可查看其历史版本及各版本正文。
- 支持在结果列表中多选，并将选中帖子或全部帖子批量保存为 ZIP。
- 可选择是否在 ZIP 中保存帖子历史版本；启用后会保存每个版本的 Markdown 文件，并在 `manifest.json` 中记录版本信息和文件路径。若某帖历史请求失败，该帖会被跳过，其他帖子仍会正常导出，并显示失败详情。
- ZIP 中每篇帖子的当前版本保存为 Markdown 文件，并附带包含帖子信息的 `manifest.json`。
- HTML 正文转换为 Markdown；用户提及中的 UUID 会转换为 `@{https://cdsq.dao3.fun/profile/用户UUID}`，帖子图片的站内 `/api/v1/files/` 地址会转换为完整地址。
- 查询和 ZIP 打包在后台运行；帖子正文使用并发请求读取，减少等待时间并避免界面无响应。关键操作和请求失败会输出到 rich 控制台日志。

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

1. 从“开始日期”和“结束日期”下拉菜单中选择日期，日期不得早于 2026-09-09。
2. 点击“查找帖子”。程序会按 UTC 日期查询该日期范围内的帖子，并并发读取帖子内容。
3. 在筛选框输入关键词；使用“范围”菜单选择搜索标题、正文或标题和正文。
4. 双击帖子可在浏览器中打开原网站。选择一篇帖子并点击“获取历史版本”，可查看不同版本的标题、主题和正文。
5. 在“保存帖子历史版本”处选择“是”或“否”，再点击“保存选中为 ZIP”导出选中帖子，或点击“保存全部为 ZIP”导出所有已成功读取的帖子。选择“是”时会并发获取历史版本；若某帖请求失败，该帖会跳过，其他帖子仍会保存，错误详情会显示在提示框和 rich 控制台中。
6. 在文件保存对话框中选择 ZIP 文件的保存位置。

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
