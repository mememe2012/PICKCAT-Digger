import requests
import json
import threading
import tkinter as tk
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from rich import console
from rich.text import Text
from urllib.parse import urlparse

SITE_URL = "https://cdsq.dao3.fun"
POST_URL = f"{SITE_URL}/forum/post/"
API_URL = f"{SITE_URL}/api/v1/topics"
OPENING_DATE = date(2026, 9, 9)
CONSOLE = console.Console()


def _log(level: str, message: str) -> None:
    styles = {
        "INFO": "cyan",
        "SUCCESS": "green",
        "WARNING": "yellow",
        "ERROR": "bold red",
    }
    CONSOLE.log(Text(f"{level}: {message}", style=styles.get(level, "white")))


def _format_tags(tags: list[dict[str, str]]) -> str:
    return " ".join(f"#{tag['name']}" for tag in tags if tag.get("name"))


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[tuple[str, int]] = []
        self.link_stack: list[str] = []
        self.in_pre = False
        self.blockquote_depth = 0
        self.user_mention_depth = 0
        self.user_mention_spans: list[bool] = []

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
        elif tag == "span":
            is_user_mention = (
                "markdown-user-mention" in (attributes.get("class") or "").split()
                and bool(attributes.get("data-user-id"))
            )
            self.user_mention_spans.append(is_user_mention)
            if is_user_mention:
                user_id = attributes["data-user-id"]
                self.parts.append(f"@{{{SITE_URL}/profile/{user_id}}}")
                self.user_mention_depth += 1
        elif tag == "img":
            alt = attributes.get("alt") or ""
            src = attributes.get("src") or ""
            if src.startswith("/api/v1/files/"):
                src = f"{SITE_URL}{src}"
            self.parts.append(f"![{alt}]({src})")

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self.user_mention_spans:
            if self.user_mention_spans.pop():
                self.user_mention_depth -= 1
        elif tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
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
        if self.user_mention_depth:
            return
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
    def __init__(self) -> None:
        self._sessions = threading.local()

    def _get(
        self, url: str, params: dict[str, int | str] | None = None
    ) -> requests.Response:
        session = getattr(self._sessions, "session", None)
        if session is None:
            session = requests.Session()
            self._sessions.session = session
        response = session.get(url, params=params, timeout=30)
        if response.status_code >= 400:
            _log(
                "ERROR",
                f"GET {response.url} returned HTTP {response.status_code}: "
                f"{response.text[:300]}",
            )
        return response

    @staticmethod
    def _post_id(post_url: str) -> str:
        parsed_url = urlparse(post_url)
        post_id = parsed_url.path.removeprefix("/forum/post/")
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != urlparse(POST_URL).netloc
            or not parsed_url.path.startswith("/forum/post/")
            or not post_id
            or "/" in post_id
        ):
            raise ValueError("post_url must be a pickCat forum post URL")
        return post_id

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
            response = self._get(API_URL, params=params)
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
        post_id = self._post_id(post_url)
        response = self._get(f"{API_URL}/{post_id}")
        response.raise_for_status()
        topic = response.json()
        first_post = topic["firstPost"]

        return {
            "date": datetime.fromisoformat(
                topic["createdAt"].replace("Z", "+00:00")
            ).astimezone(timezone.utc).date().isoformat(),
            "author": topic["author"]["username"],
            "title": topic["title"],
            "tags": _format_tags(topic.get("tags", [])),
            "Markdown": _html_to_markdown(first_post["cookedHtml"]),
            "repost": topic.get("repostCount"),
            "like": first_post["likeCount"],
            "reply": topic["replyCount"],
        }

    def GetPostHistory(self, post_url: str) -> list[dict[str, str | int]]:
        """Return public revisions of a post, including each revision's content."""
        topic_id = self._post_id(post_url)
        topic_response = self._get(f"{API_URL}/{topic_id}")
        topic_response.raise_for_status()
        post_id = topic_response.json()["firstPost"]["id"]
        response = self._get(f"{SITE_URL}/api/v1/posts/{post_id}/revisions")
        response.raise_for_status()
        revisions = response.json()["items"]
        revisions.sort(key=lambda revision: revision["revision"])
        return [
            {
                "revision": revision["revision"],
                "date": str(revision.get("publishedAt") or ""),
                "title": revision.get("title") or "",
                "tags": _format_tags(revision.get("tags", [])),
                "Markdown": _html_to_markdown(revision.get("cookedHtml") or ""),
            }
            for revision in revisions
        ]


def _write_posts_zip(
    posts: list[tuple[str, dict[str, str | int | None]]],
    destination: str,
    histories: dict[str, list[dict[str, str | int]]] | None = None,
) -> None:
    """Write fetched posts as Markdown files and a JSON index in a ZIP archive."""
    manifest: list[dict[str, object]] = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for post_url, info in posts:
            post_id = urlparse(post_url).path.rstrip("/").rsplit("/", 1)[-1]
            archive.writestr(f"posts/{post_id}.md", str(info["Markdown"] or ""))
            manifest_item: dict[str, object] = {"url": post_url, **info}
            if histories is not None:
                revision_entries = []
                for revision in histories.get(post_url, []):
                    revision_path = (
                        f"posts/{post_id}_history/"
                        f"revision-{revision['revision']}.md"
                    )
                    archive.writestr(revision_path, str(revision["Markdown"]))
                    revision_entries.append(
                        {
                            "revision": revision["revision"],
                            "date": revision["date"],
                            "title": revision["title"],
                            "tags": revision["tags"],
                            "file": revision_path,
                        }
                    )
                manifest_item["history"] = revision_entries
            manifest.append(manifest_item)

        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )


class DiggerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PickCat 挖掘机")
        self.geometry("900x600")
        self.minsize(820, 480)
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
        latest_date = max(date.today(), OPENING_DATE)
        self.start_date = tk.StringVar(value=today)
        self.end_date = tk.StringVar(value=latest_date.isoformat())
        date_options = [
            (latest_date - timedelta(days=offset)).isoformat()
            for offset in range((latest_date - OPENING_DATE).days + 1)
        ]
        self.start_date.set(latest_date.isoformat())
        ttk.Label(controls, text="开始日期").grid(row=0, column=0, padx=(0, 6))
        ttk.Combobox(
            controls,
            textvariable=self.start_date,
            values=date_options,
            width=12,
            state="readonly",
        ).grid(
            row=0, column=1, padx=(0, 12)
        )
        ttk.Label(controls, text="结束日期").grid(row=0, column=2, padx=(0, 6))
        ttk.Combobox(
            controls,
            textvariable=self.end_date,
            values=date_options,
            width=12,
            state="readonly",
        ).grid(
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

        ttk.Label(controls, text="筛选").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(10, 0)
        )
        self.filter_text = tk.StringVar()
        self.filter_text.trace_add("write", lambda *_: self._refresh_table())
        ttk.Entry(controls, textvariable=self.filter_text, width=32).grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=(10, 0)
        )
        ttk.Label(controls, text="范围").grid(
            row=1, column=3, padx=(0, 6), pady=(10, 0)
        )
        self.filter_scope = tk.StringVar(value="标题和内容")
        self.filter_scope_box = ttk.Combobox(
            controls,
            textvariable=self.filter_scope,
            values=("标题和内容", "标题", "内容"),
            width=12,
            state="readonly",
        )
        self.filter_scope_box.grid(row=1, column=4, sticky="w", pady=(10, 0))
        self.filter_scope_box.bind(
            "<<ComboboxSelected>>", lambda _: self._refresh_table()
        )
        self.history_button = ttk.Button(
            controls, text="获取历史版本", command=self._start_history
        )
        self.history_button.grid(row=1, column=6, pady=(10, 0))

        ttk.Label(controls, text="保存帖子历史版本：").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(10, 0)
        )
        self.save_history = tk.BooleanVar(value=False)
        self.save_history_yes = ttk.Radiobutton(
            controls, text="是", variable=self.save_history, value=True
        )
        self.save_history_yes.grid(row=2, column=1, sticky="w", pady=(10, 0))
        self.save_history_no = ttk.Radiobutton(
            controls, text="否", variable=self.save_history, value=False
        )
        self.save_history_no.grid(row=2, column=2, sticky="w", pady=(10, 0))

        table_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("date", "title", "tags", "author", "reply", "like")
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "date": ("日期", 90),
            "title": ("标题", 330),
            "tags": ("主题", 125),
            "author": ("作者", 120),
            "reply": ("评论", 65),
            "like": ("点赞", 65),
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
        self.table.bind("<Double-1>", self._open_post)

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(
            value="选择日期范围后查找；日期范围从 2026-09-09（开站）开始"
        )
        ttk.Label(footer, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, sticky="e")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.search_button.configure(state=state)
        self.save_selected_button.configure(state=state)
        self.save_all_button.configure(state=state)
        self.history_button.configure(state=state)
        self.save_history_yes.configure(state=state)
        self.save_history_no.configure(state=state)
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
        if start < OPENING_DATE or end < OPENING_DATE:
            messagebox.showerror(
                "日期范围错误",
                f"日期不能早于开站时间 {OPENING_DATE.isoformat()}。",
                parent=self,
            )
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
            _log("INFO", f"Searching topics from {start.isoformat()} to {end.isoformat()}")
            urls = self.digger.FindPostsByDateRange(start, end)
            _log("INFO", f"Found {len(urls)} topics; reading details with up to 8 workers")
            indexed_results: list[
                tuple[int, str, dict[str, str | int | None]]
            ] = []
            errors: list[str] = []
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {
                    executor.submit(self.digger.GetInfo, url): (index, url)
                    for index, url in enumerate(urls)
                }
                for current, future in enumerate(as_completed(futures), start=1):
                    index, url = futures[future]
                    try:
                        indexed_results.append((index, url, future.result()))
                    except Exception as error:
                        errors.append(f"{url}: {error}")
                        _log("ERROR", f"Failed to read topic {url}: {error}")
                    self.after(
                        0,
                        lambda current=current, total=len(urls): self.status.set(
                            f"正在读取帖子 {current}/{total}…"
                        ),
                    )
            indexed_results.sort(key=lambda item: item[0])
            results = [(url, info) for _, url, info in indexed_results]
            _log(
                "SUCCESS" if not errors else "WARNING",
                f"Topic search complete: {len(results)} read, {len(errors)} failed",
            )
            self.after(0, lambda: self._show_results(results, errors))
        except Exception as error:
            _log("ERROR", f"Topic search failed: {error}")
            self.after(0, lambda error=error: self._search_failed(error))

    def _show_results(
        self,
        results: list[tuple[str, dict[str, str | int | None]]],
        errors: list[str],
    ) -> None:
        self.posts = results
        self._refresh_table()
        self._set_busy(False)
        self.status.set(f"查找完成：成功读取 {len(results)} 篇，失败 {len(errors)} 篇")
        if errors:
            messagebox.showwarning(
                "部分帖子读取失败",
                "\n".join(errors[:10])
                + (f"\n…另有 {len(errors) - 10} 个错误" if len(errors) > 10 else ""),
                parent=self,
            )

    def _refresh_table(self) -> None:
        self.table.delete(*self.table.get_children())
        needle = self.filter_text.get().strip().casefold()
        scope = self.filter_scope.get()
        for index, (_, info) in enumerate(self.posts):
            title = str(info["title"] or "")
            content = str(info["Markdown"] or "")
            if needle:
                if scope == "标题":
                    searchable = title
                elif scope == "内容":
                    searchable = content
                else:
                    searchable = f"{title}\n{content}"
                if needle not in searchable.casefold():
                    continue
            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    info["date"] or "",
                    title,
                    info["tags"] or "",
                    info["author"] or "",
                    info["reply"] or 0,
                    info["like"] or 0,
                ),
            )

    def _open_post(self, event: tk.Event) -> None:
        item = self.table.identify_row(event.y)
        if item:
            webbrowser.open(self.posts[int(item)][0])

    def _start_history(self) -> None:
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("未选择帖子", "请先选择要查看历史版本的帖子。", parent=self)
            return
        selected_item = self.table.focus()
        if selected_item not in selected:
            selected_item = selected[0]
        post_url = self.posts[int(selected_item)][0]
        self.status.set("正在获取帖子历史版本…")
        self._set_busy(True)
        threading.Thread(
            target=self._history_worker, args=(post_url,), daemon=True
        ).start()

    def _history_worker(self, post_url: str) -> None:
        try:
            revisions = self.digger.GetPostHistory(post_url)
        except Exception as error:
            _log("ERROR", f"Failed to fetch history for {post_url}: {error}")
            self.after(0, lambda error=error: self._history_failed(error))
            return
        _log("SUCCESS", f"Fetched {len(revisions)} history revisions for {post_url}")
        self.after(0, lambda: self._show_history(post_url, revisions))

    def _history_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.status.set("获取历史版本失败")
        messagebox.showerror("获取历史版本失败", str(error), parent=self)

    def _show_history(
        self, post_url: str, revisions: list[dict[str, str | int]]
    ) -> None:
        self._set_busy(False)
        self.status.set(f"已获取 {len(revisions)} 个历史版本")
        if not revisions:
            messagebox.showinfo("没有历史版本", "该帖子没有可用的历史版本。", parent=self)
            return

        window = tk.Toplevel(self)
        window.title(
            f"帖子历史版本 - {urlparse(post_url).path.rsplit('/', 1)[-1]}"
        )
        window.geometry("820x600")
        window.minsize(600, 400)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        window.rowconfigure(1, weight=2)

        history_table = ttk.Treeview(
            window, columns=("revision", "date", "title", "tags"), show="headings"
        )
        for name, label, width in (
            ("revision", "版本", 70),
            ("date", "更新时间", 175),
            ("title", "标题", 360),
            ("tags", "主题", 140),
        ):
            history_table.heading(name, text=label)
            history_table.column(name, width=width, anchor="w")
        history_table.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        history_scrollbar = ttk.Scrollbar(
            window, orient="vertical", command=history_table.yview
        )
        history_scrollbar.grid(row=0, column=1, sticky="ns", pady=8)
        history_table.configure(yscrollcommand=history_scrollbar.set)

        content_frame = ttk.Frame(window)
        content_frame.grid(
            row=1, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8)
        )
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)
        content = tk.Text(content_frame, wrap="word", state="disabled")
        content.grid(row=0, column=0, sticky="nsew")
        content_scrollbar = ttk.Scrollbar(
            content_frame, orient="vertical", command=content.yview
        )
        content_scrollbar.grid(row=0, column=1, sticky="ns")
        content.configure(yscrollcommand=content_scrollbar.set)

        for index, revision in enumerate(revisions):
            history_table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    revision["revision"],
                    revision["date"],
                    revision["title"],
                    revision["tags"],
                ),
            )

        def show_revision(_: tk.Event | None = None) -> None:
            selection = history_table.selection()
            if not selection:
                return
            revision = revisions[int(selection[0])]
            content.configure(state="normal")
            content.delete("1.0", "end")
            content.insert(
                "1.0",
                f"{revision['title']}\n主题：{revision['tags']}\n"
                f"版本：{revision['revision']}  更新时间：{revision['date']}\n\n"
                f"{revision['Markdown']}",
            )
            content.configure(state="disabled")

        history_table.bind("<<TreeviewSelect>>", show_revision)
        first_item = history_table.get_children()[0]
        history_table.selection_set(first_item)
        show_revision()

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
        include_history = self.save_history.get()
        _log(
            "INFO",
            f"Exporting {len(posts)} posts to {destination}; "
            f"include_history={include_history}",
        )
        self.status.set(f"正在打包 {len(posts)} 篇帖子…")
        self._set_busy(True)
        threading.Thread(
            target=self._save_worker,
            args=(posts, destination, include_history),
            daemon=True,
        ).start()

    def _save_worker(
        self,
        posts: list[tuple[str, dict[str, str | int | None]]],
        destination: str,
        include_history: bool,
    ) -> None:
        try:
            histories = None
            history_errors: dict[str, str] = {}
            if include_history:
                histories = {}
                _log("INFO", f"Fetching history for {len(posts)} posts")
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = {
                        executor.submit(self.digger.GetPostHistory, post_url): post_url
                        for post_url, _ in posts
                    }
                    for current, future in enumerate(as_completed(futures), start=1):
                        post_url = futures[future]
                        try:
                            histories[post_url] = future.result()
                        except Exception as error:
                            history_errors[post_url] = str(error)
                            _log(
                                "WARNING",
                                f"Skipping history for {post_url}: {error}",
                            )
                        self.after(
                            0,
                            lambda current=current, total=len(posts): self.status.set(
                                f"正在读取历史版本 {current}/{total}…"
                            ),
                        )
            posts_to_save = [
                post for post in posts if post[0] not in history_errors
            ]
            _write_posts_zip(posts_to_save, destination, histories)
            if history_errors:
                _log(
                    "WARNING",
                    "Skipped posts with failed history requests: "
                    + ", ".join(history_errors),
                )
        except Exception as error:
            _log("ERROR", f"ZIP export failed for {destination}: {error}")
            self.after(0, lambda error=error: self._save_failed(error))
            return
        _log(
            "SUCCESS" if not history_errors else "WARNING",
            f"Export complete: {len(posts_to_save)} posts saved, "
            f"{len(history_errors)} history requests failed",
        )
        self.after(
            0,
            lambda: self._save_complete(
                len(posts_to_save), destination, len(history_errors), history_errors
            ),
        )

    def _save_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.status.set("保存失败")
        messagebox.showerror("保存失败", str(error), parent=self)

    def _save_complete(
        self,
        count: int,
        destination: str,
        skipped_histories: int = 0,
        history_errors: dict[str, str] | None = None,
    ) -> None:
        self._set_busy(False)
        status = f"已保存 {count} 篇帖子"
        if skipped_histories:
            status += f"，跳过 {skipped_histories} 篇历史版本请求失败的帖子"
        self.status.set(status)
        if skipped_histories:
            details = history_errors or {}
            error_lines = [
                f"{post_url}: {error}" for post_url, error in details.items()
            ]
            messagebox.showwarning(
                "部分历史版本未保存",
                f"已保存 {count} 篇帖子；有 {skipped_histories} 篇的历史版本请求失败，"
                "这些帖子已从 ZIP 中跳过。失败原因已记录在 rich 控制台日志中。\n\n"
                + "\n".join(error_lines[:10])
                + (
                    f"\n…另有 {len(error_lines) - 10} 个错误"
                    if len(error_lines) > 10
                    else ""
                ),
                parent=self,
            )
            return
        messagebox.showinfo(
            "保存完成",
            f"已将 {count} 篇帖子保存到：\n{Path(destination)}",
            parent=self,
        )


if __name__ == "__main__":
    DiggerApp().mainloop()