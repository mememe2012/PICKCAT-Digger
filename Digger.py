import requests
import json
import threading
import tkinter as tk
import zipfile
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from rich import console
from urllib.parse import urlparse

SITE_URL = "https://cdsq.dao3.fun"
POST_URL = f"{SITE_URL}/forum/post/"
API_URL = f"{SITE_URL}/api/v1/topics"
CONSOLE = console.Console()


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[tuple[str, int]] = []
        self.link_stack: list[str] = []
        self.in_pre = False
        self.blockquote_depth = 0

    def _line_break(self, blank: bool = False) -> None:
        current = "".join(self.parts).rstrip(" \t")
        self.parts = [current]
        if not current.endswith("\n"):
            self.parts.append("\n")
        if blank and not current.endswith("\n\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._line_break(blank=True)
            if self.blockquote_depth:
                self.parts.append("> " * self.blockquote_depth)
            if tag.startswith("h"):
                self.parts.append(f"{'#' * int(tag[1])} ")
        elif tag in {"ul", "ol"}:
            self._line_break(blank=True)
            self.list_stack.append((tag, 0))
        elif tag == "li":
            self._line_break()
            if self.list_stack:
                list_type, count = self.list_stack[-1]
                count += 1
                self.list_stack[-1] = (list_type, count)
                marker = f"{count}. " if list_type == "ol" else "- "
                self.parts.append(f"{'  ' * (len(self.list_stack) - 1)}{marker}")
        elif tag == "blockquote":
            self._line_break(blank=True)
            self.blockquote_depth += 1
        elif tag == "pre":
            self._line_break(blank=True)
            self.parts.append("```\n")
            self.in_pre = True
        elif tag == "br":
            self._line_break()
        elif tag == "hr":
            self._line_break(blank=True)
            self.parts.append("---")
            self._line_break(blank=True)
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "del":
            self.parts.append("~~")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag == "a":
            self.parts.append("[")
            self.link_stack.append(attributes.get("href") or "")
        elif tag == "img":
            alt = attributes.get("alt") or ""
            src = attributes.get("src") or ""
            if src.startswith("/api/v1/files/"):
                src = f"{SITE_URL}{src}"
            self.parts.append(f"![{alt}]({src})")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
            self._line_break(blank=tag != "li")
        elif tag == "blockquote":
            self._line_break(blank=True)
            self.blockquote_depth = max(0, self.blockquote_depth - 1)
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self._line_break(blank=True)
        elif tag == "pre":
            self._line_break()
            self.parts.append("```")
            self._line_break(blank=True)
            self.in_pre = False
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "del":
            self.parts.append("~~")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag == "a" and self.link_stack:
            href = self.link_stack.pop()
            self.parts.append(f"]({href})" if href else "]")

    def handle_data(self, data: str) -> None:
        if not self.in_pre and "\n" in data and data.isspace():
            return
        if self.blockquote_depth and (
            not self.parts or self.parts[-1].endswith("\n")
        ):
            self.parts.append("> " * self.blockquote_depth)
        self.parts.append(data)

def _html_to_markdown(content: str) -> str:
    parser = _MarkdownParser()
    parser.feed(content)
    string = "".join(parser.parts).strip()
    return string

class Digger:
    def FindPostByDate(self, target_date: date | str) -> list[str]:
        """Return URLs of posts created on the given UTC date."""
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)
        elif isinstance(target_date, datetime):
            target_date = target_date.date()
        elif not isinstance(target_date, date):
            raise TypeError("target_date must be a date or an ISO date string")

        return self.FindPostsByDateRange(target_date, target_date)

    def FindPostsByDateRange(
        self, start_date: date | str, end_date: date | str
    ) -> list[str]:
        """Return post URLs created within the inclusive UTC date range."""
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        elif isinstance(start_date, datetime):
            start_date = start_date.date()
        elif not isinstance(start_date, date):
            raise TypeError("start_date must be a date or an ISO date string")

        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)
        elif isinstance(end_date, datetime):
            end_date = end_date.date()
        elif not isinstance(end_date, date):
            raise TypeError("end_date must be a date or an ISO date string")
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        params: dict[str, int | str] = {"limit": 50}
        post_urls: list[str] = []

        while True:
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()

            for topic in payload["items"]:
                created_at = datetime.fromisoformat(
                    topic["createdAt"].replace("Z", "+00:00")
                )
                created_date = created_at.astimezone(timezone.utc).date()
                if start_date <= created_date <= end_date:
                    post_urls.append(f"{POST_URL}{topic['id']}")

            page_info = payload["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            params["cursor"] = page_info["nextCursor"]

        return post_urls

    def GetInfo(self, post_url: str) -> dict[str, str | int | None]:
        """Return public post information extracted from a forum post URL."""
        parsed_url = urlparse(post_url)
        post_path = parsed_url.path.removeprefix("/forum/post/")
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != urlparse(POST_URL).netloc
            or not parsed_url.path.startswith("/forum/post/")
            or not post_path
            or "/" in post_path
        ):
            raise ValueError("post_url must be a pickCat forum post URL")

        response = requests.get(f"{API_URL}/{post_path}", timeout=30)
        response.raise_for_status()
        topic = response.json()
        first_post = topic["firstPost"]

        return {
            "date": datetime.fromisoformat(
                topic["createdAt"].replace("Z", "+00:00")
            ).astimezone(timezone.utc).date().isoformat(),
            "author": topic["author"]["username"],
            "title": topic["title"],
            "Markdown": _html_to_markdown(first_post["cookedHtml"]),
            "repost": topic.get("repostCount"),
            "like": first_post["likeCount"],
            "reply": topic["replyCount"],
        }


def _write_posts_zip(
    posts: list[tuple[str, dict[str, str | int | None]]], destination: str
) -> None:
    """Write fetched posts as Markdown files and a JSON index in a ZIP archive."""
    manifest: list[dict[str, str | int | None]] = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for post_url, info in posts:
            post_id = urlparse(post_url).path.rstrip("/").rsplit("/", 1)[-1]
            archive.writestr(f"posts/{post_id}.md", str(info["Markdown"] or ""))
            manifest.append({"url": post_url, **info})

        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )


class DiggerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PickCat 帖子采集器")
        self.geometry("900x600")
        self.minsize(720, 440)
        self.digger = Digger()
        self.posts: list[tuple[str, dict[str, str | int | None]]] = []
        self.busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(5, weight=1)

        today = date.today().isoformat()
        self.start_date = tk.StringVar(value=today)
        self.end_date = tk.StringVar(value=today)
        ttk.Label(controls, text="开始日期").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(controls, textvariable=self.start_date, width=13).grid(
            row=0, column=1, padx=(0, 12)
        )
        ttk.Label(controls, text="结束日期").grid(row=0, column=2, padx=(0, 6))
        ttk.Entry(controls, textvariable=self.end_date, width=13).grid(
            row=0, column=3, padx=(0, 12)
        )
        self.search_button = ttk.Button(
            controls, text="查找帖子", command=self._start_search
        )
        self.search_button.grid(row=0, column=4, padx=(0, 8))
        self.save_selected_button = ttk.Button(
            controls, text="保存选中为 ZIP", command=self._save_selected
        )
        self.save_selected_button.grid(row=0, column=5, sticky="e", padx=(0, 8))
        self.save_all_button = ttk.Button(
            controls, text="保存全部为 ZIP", command=self._save_all
        )
        self.save_all_button.grid(row=0, column=6)

        table_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("date", "title", "author", "reply", "like")
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "date": ("日期", 100),
            "title": ("标题", 390),
            "author": ("作者", 150),
            "reply": ("评论", 70),
            "like": ("点赞", 70),
        }
        for name, (label, width) in headings.items():
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=60, anchor="w")
        scrollbar = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.table.yview
        )
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="输入日期范围后查找；日期格式：YYYY-MM-DD")
        ttk.Label(footer, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, sticky="e")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.search_button.configure(state=state)
        self.save_selected_button.configure(state=state)
        self.save_all_button.configure(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _start_search(self) -> None:
        if self.busy:
            return
        try:
            start = date.fromisoformat(self.start_date.get().strip())
            end = date.fromisoformat(self.end_date.get().strip())
            if start > end:
                raise ValueError("开始日期不能晚于结束日期")
        except ValueError as error:
            messagebox.showerror("日期格式错误", str(error), parent=self)
            return

        self.posts.clear()
        self.table.delete(*self.table.get_children())
        self.status.set("正在查找帖子并读取内容…")
        self._set_busy(True)
        threading.Thread(
            target=self._search_worker, args=(start, end), daemon=True
        ).start()

    def _search_worker(self, start: date, end: date) -> None:
        try:
            urls = self.digger.FindPostsByDateRange(start, end)
            results: list[tuple[str, dict[str, str | int | None]]] = []
            errors: list[str] = []
            for index, url in enumerate(urls, start=1):
                try:
                    results.append((url, self.digger.GetInfo(url)))
                except Exception as error:
                    errors.append(f"{url}: {error}")
                self.after(
                    0,
                    lambda current=index, total=len(urls): self.status.set(
                        f"正在读取帖子 {current}/{total}…"
                    ),
                )
            self.after(0, lambda: self._show_results(results, errors))
        except Exception as error:
            self.after(0, lambda error=error: self._search_failed(error))

    def _show_results(
        self,
        results: list[tuple[str, dict[str, str | int | None]]],
        errors: list[str],
    ) -> None:
        self.posts = results
        for index, (_, info) in enumerate(results):
            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    info["date"] or "",
                    info["title"] or "",
                    info["author"] or "",
                    info["reply"] or 0,
                    info["like"] or 0,
                ),
            )
        self._set_busy(False)
        self.status.set(f"查找完成：成功读取 {len(results)} 篇，失败 {len(errors)} 篇")
        if errors:
            messagebox.showwarning(
                "部分帖子读取失败",
                "\n".join(errors[:10])
                + (f"\n…另有 {len(errors) - 10} 个错误" if len(errors) > 10 else ""),
                parent=self,
            )

    def _search_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.status.set("查找失败")
        messagebox.showerror("查找失败", str(error), parent=self)

    def _save_selected(self) -> None:
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("未选择帖子", "请先在列表中选择要保存的帖子。", parent=self)
            return
        self._save_posts([self.posts[int(item)] for item in selected])

    def _save_all(self) -> None:
        if not self.posts:
            messagebox.showinfo("没有数据", "请先查找并读取帖子。", parent=self)
            return
        self._save_posts(self.posts)

    def _save_posts(
        self, posts: list[tuple[str, dict[str, str | int | None]]]
    ) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="保存帖子 ZIP",
            defaultextension=".zip",
            filetypes=[("ZIP 压缩包", "*.zip")],
            initialfile=f"pickcat-posts-{date.today().isoformat()}.zip",
        )
        if not destination:
            return
        self.status.set(f"正在打包 {len(posts)} 篇帖子…")
        self._set_busy(True)
        threading.Thread(
            target=self._save_worker, args=(posts, destination), daemon=True
        ).start()

    def _save_worker(
        self, posts: list[tuple[str, dict[str, str | int | None]]], destination: str
    ) -> None:
        try:
            _write_posts_zip(posts, destination)
        except Exception as error:
            self.after(0, lambda error=error: self._save_failed(error))
            return
        self.after(0, lambda: self._save_complete(len(posts), destination))

    def _save_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.status.set("保存失败")
        messagebox.showerror("保存失败", str(error), parent=self)

    def _save_complete(self, count: int, destination: str) -> None:
        self._set_busy(False)
        self.status.set(f"已保存 {count} 篇帖子")
        messagebox.showinfo(
            "保存完成",
            f"已将 {count} 篇帖子保存到：\n{Path(destination)}",
            parent=self,
        )


if __name__ == "__main__":
    DiggerApp().mainloop()