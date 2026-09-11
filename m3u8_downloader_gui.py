import hashlib
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


DURATION_PATTERN = re.compile(
    r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)"
)


class M3U8DownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("M3U8 视频下载器")
        self.root.geometry("760x620")
        self.root.minsize(680, 500)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.current_process: subprocess.Popen[str] | None = None
        self.worker_thread: threading.Thread | None = None

        self.output_dir = tk.StringVar(value=str(Path.cwd() / "downloads"))
        self.user_agent = tk.StringVar(
            value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
        )
        self.referer = tk.StringVar()
        self.status = tk.StringVar(value="就绪")

        self._build_ui()
        self.root.after(100, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)

    def _build_ui(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(5, weight=1)

        ttk.Label(
            root,
            text="M3U8 地址（每行一个，可批量下载）",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))

        url_frame = ttk.Frame(root)
        url_frame.grid(row=1, column=0, sticky="nsew", padx=16)
        url_frame.columnconfigure(0, weight=1)
        url_frame.rowconfigure(0, weight=1)

        self.url_text = tk.Text(url_frame, height=8, wrap="word")
        self.url_text.grid(row=0, column=0, sticky="nsew")

        url_scrollbar = ttk.Scrollbar(
            url_frame,
            orient="vertical",
            command=self.url_text.yview,
        )
        url_scrollbar.grid(row=0, column=1, sticky="ns")
        self.url_text.configure(yscrollcommand=url_scrollbar.set)

        output_frame = ttk.Frame(root)
        output_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(14, 0))
        output_frame.columnconfigure(1, weight=1)

        ttk.Label(output_frame, text="下载位置").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(
            output_frame,
            textvariable=self.output_dir,
        ).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(
            output_frame,
            text="选择文件夹",
            command=self._choose_output_dir,
        ).grid(row=0, column=2)

        advanced_frame = ttk.LabelFrame(root, text="可选请求参数")
        advanced_frame.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=16,
            pady=(14, 0),
        )
        advanced_frame.columnconfigure(1, weight=1)

        ttk.Label(advanced_frame, text="User-Agent").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(10, 6),
            pady=(8, 4),
        )
        ttk.Entry(
            advanced_frame,
            textvariable=self.user_agent,
        ).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 10),
            pady=(8, 4),
        )

        ttk.Label(advanced_frame, text="Referer").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(10, 6),
            pady=(4, 8),
        )
        ttk.Entry(
            advanced_frame,
            textvariable=self.referer,
        ).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 10),
            pady=(4, 8),
        )

        action_frame = ttk.Frame(root)
        action_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=14)
        action_frame.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(
            action_frame,
            mode="indeterminate",
            maximum=100,
        )
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.start_button = ttk.Button(
            action_frame,
            text="开始下载",
            command=self._start_download,
        )
        self.start_button.grid(row=0, column=1, padx=(0, 6))

        self.cancel_button = ttk.Button(
            action_frame,
            text="取消",
            command=self._cancel_download,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=2)

        ttk.Label(root, textvariable=self.status).grid(
            row=5,
            column=0,
            sticky="nw",
            padx=16,
            pady=(0, 5),
        )

        log_frame = ttk.LabelFrame(root, text="下载日志")
        log_frame.grid(row=6, column=0, sticky="nsew", padx=16, pady=(0, 14))
        root.rowconfigure(6, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            height=8,
            state="disabled",
            wrap="word",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

        log_scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        log_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(
            title="选择下载位置",
            initialdir=self.output_dir.get() or str(Path.cwd()),
        )
        if selected:
            self.output_dir.set(selected)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _get_urls(self) -> list[str]:
        urls = []
        for line in self.url_text.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not re.match(r"^https?://", line, flags=re.IGNORECASE):
                raise ValueError(f"不是有效的 HTTP/HTTPS 地址：{line}")
            urls.append(line)
        return urls

    @staticmethod
    def _make_filename(url: str, index: int) -> str:
        parsed = urlparse(url)
        name = Path(parsed.path).stem
        name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")

        if not name or name.lower() in {"m3u8", "index", "playlist"}:
            name = f"video_{index}"

        short_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        return f"{name}_{short_hash}.mp4"

    def _start_download(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        try:
            urls = self._get_urls()
        except ValueError as exc:
            messagebox.showerror("地址错误", str(exc))
            return

        if not urls:
            messagebox.showwarning("缺少地址", "请先粘贴至少一个 m3u8 地址。")
            return

        if shutil.which("ffmpeg") is None:
            messagebox.showerror(
                "找不到 FFmpeg",
                "请先安装 FFmpeg，并确保 ffmpeg 已加入系统 PATH。",
            )
            return

        output_dir_text = self.output_dir.get().strip()
        if not output_dir_text:
            messagebox.showwarning("缺少下载位置", "请选择下载位置。")
            return
        output_dir = Path(output_dir_text).expanduser()

        user_agent = self.user_agent.get().strip()
        referer = self.referer.get().strip()

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("无法创建目录", str(exc))
            return

        self.cancel_event.clear()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self._append_log(f"已加入 {len(urls)} 个下载任务。")
        self.status.set(f"准备下载，共 {len(urls)} 个任务")

        self.worker_thread = threading.Thread(
            target=self._download_worker,
            args=(urls, output_dir, user_agent, referer),
            daemon=True,
        )
        self.worker_thread.start()

    def _download_worker(
        self,
        urls: list[str],
        output_dir: Path,
        user_agent: str,
        referer: str,
    ) -> None:
        completed = 0
        failed = 0

        try:
            for index, url in enumerate(urls, start=1):
                if self.cancel_event.is_set():
                    break

                filename = self._make_filename(url, index)
                output_file = output_dir / filename
                temp_file = output_dir / f".{filename}.part.mp4"

                self.events.put(
                    (
                        "status",
                        f"正在下载 {index}/{len(urls)}：{filename}",
                    )
                )
                self.events.put(("log", f"[{index}/{len(urls)}] {url}"))

                if output_file.exists() and output_file.stat().st_size > 0:
                    completed += 1
                    self.events.put(("log", f"已存在，跳过：{output_file}"))
                    continue

                if temp_file.exists():
                    temp_file.unlink()

                command = [
                    "ffmpeg",
                    "-hide_banner",
                    "-nostdin",
                    "-loglevel",
                    "info",
                    "-nostats",
                    "-progress",
                    "pipe:1",
                    "-y",
                    "-protocol_whitelist",
                    "file,http,https,tcp,tls,crypto",
                ]

                if user_agent:
                    command.extend(["-user_agent", user_agent])
                if referer:
                    command.extend(["-referer", referer])

                command.extend(
                    [
                        "-i",
                        url,
                        "-c",
                        "copy",
                        str(temp_file),
                    ]
                )

                output_lines: list[str] = []
                progress_data: dict[str, float | str | None] = {
                    "duration_us": None,
                    "out_time_us": 0,
                    "speed": None,
                }
                try:
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                    )
                except OSError as exc:
                    failed += 1
                    self.events.put(("error", f"启动 FFmpeg 失败：{exc}"))
                    continue

                self.current_process = process
                reader = threading.Thread(
                    target=self._read_process_output,
                    args=(process, output_lines, progress_data),
                    daemon=True,
                )
                progress_reader = threading.Thread(
                    target=self._read_progress_output,
                    args=(
                        process.stdout,
                        progress_data,
                        index,
                        len(urls),
                        filename,
                    ),
                    daemon=True,
                )
                reader.start()
                progress_reader.start()

                while process.poll() is None:
                    if self.cancel_event.is_set():
                        process.terminate()
                        break
                    time.sleep(0.1)

                if process.poll() is None:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

                reader.join(timeout=2)
                progress_reader.join(timeout=2)
                return_code = process.returncode
                self.current_process = None

                if self.cancel_event.is_set():
                    if temp_file.exists():
                        temp_file.unlink()
                    break

                if return_code == 0 and temp_file.exists() and temp_file.stat().st_size:
                    temp_file.replace(output_file)
                    completed += 1
                    self.events.put(("log", f"下载完成：{output_file}"))
                else:
                    failed += 1
                    if temp_file.exists():
                        temp_file.unlink()
                    detail = output_lines[-1] if output_lines else "未知错误"
                    self.events.put(
                        ("error", f"下载失败：{filename}；{detail}")
                    )
        finally:
            self.current_process = None
            self.events.put(("finished", (completed, failed)))

    @staticmethod
    def _read_process_output(
        process: subprocess.Popen[str],
        output_lines: list[str],
        progress_data: dict[str, float | str | None],
    ) -> None:
        if process.stderr is None:
            return

        for line in process.stderr:
            line = line.strip()
            if line:
                output_lines.append(line)
                match = DURATION_PATTERN.search(line)
                if match:
                    hours, minutes, seconds = match.groups()
                    duration_us = (
                        int(hours) * 3_600_000_000
                        + int(minutes) * 60_000_000
                        + int(float(seconds) * 1_000_000)
                    )
                    progress_data["duration_us"] = duration_us

    def _read_progress_output(
        self,
        stream,
        progress_data: dict[str, float | str | None],
        index: int,
        total: int,
        filename: str,
    ) -> None:
        if stream is None:
            return

        for line in stream:
            line = line.strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            if key == "out_time_us":
                try:
                    progress_data["out_time_us"] = max(0, int(value))
                except ValueError:
                    continue
            elif key == "speed":
                progress_data["speed"] = value
            elif key == "progress":
                duration_us = progress_data["duration_us"]
                current_us = progress_data["out_time_us"] or 0
                if value == "end":
                    percent = 100.0
                elif duration_us:
                    percent = min(100.0, current_us / duration_us * 100)
                else:
                    continue

                self.events.put(
                    (
                        "progress",
                        (
                            percent,
                            index,
                            total,
                            filename,
                            progress_data["speed"] or "",
                        ),
                    )
                )

    def _cancel_download(self) -> None:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return

        self.cancel_event.set()
        process = self.current_process
        if process and process.poll() is None:
            process.terminate()
        self.status.set("正在取消下载……")
        self._append_log("已请求取消，正在清理当前任务。")
        self.cancel_button.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()

                if event == "status":
                    if str(self.progress["mode"]) == "determinate":
                        self.progress.stop()
                        self.progress.configure(mode="indeterminate", value=0)
                        self.progress.start(12)
                    self.status.set(str(value))
                elif event == "log":
                    self._append_log(str(value))
                elif event == "error":
                    self._append_log(f"错误：{value}")
                elif event == "progress":
                    percent, index, total, filename, speed = value
                    self.progress.stop()
                    self.progress.configure(
                        mode="determinate",
                        maximum=100,
                        value=percent,
                    )
                    speed_text = f"，速度 {speed}" if speed else ""
                    self.status.set(
                        f"正在下载 {index}/{total}：{filename} "
                        f"({percent:.1f}%{speed_text})"
                    )
                elif event == "finished":
                    completed, failed = value
                    cancelled = self.cancel_event.is_set()
                    self.progress.stop()
                    self.progress.configure(mode="indeterminate", value=0)
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    if cancelled:
                        self.status.set(f"已取消，已完成 {completed} 个任务")
                    elif failed:
                        self.status.set(
                            f"处理完成，成功 {completed} 个，失败 {failed} 个"
                        )
                        messagebox.showwarning(
                            "部分任务失败",
                            f"成功 {completed} 个，失败 {failed} 个。\n"
                            "请查看下载日志。",
                        )
                    else:
                        self.status.set(f"全部完成，成功 {completed} 个任务")
                        messagebox.showinfo(
                            "下载完成",
                            f"成功完成 {completed} 个下载任务。",
                        )
        except queue.Empty:
            pass

        self.root.after(100, self._poll_events)

    def _close_window(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            should_close = messagebox.askyesno(
                "退出程序",
                "下载正在进行，确定要取消并退出吗？",
            )
            if not should_close:
                return
            self._cancel_download()

        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    M3U8DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
