# M3U8 视频下载器

一个基于 Tkinter 和 FFmpeg 的图形界面 M3U8 下载器。

## 运行

先安装 FFmpeg，并确保 `ffmpeg` 在系统 `PATH` 中。

```bash
python3 m3u8_downloader_gui.py
```

在界面中粘贴 M3U8 地址，每行一个地址，然后选择下载位置并点击“开始下载”。程序支持批量任务、下载日志、取消下载，以及可选的 User-Agent 和 Referer。

## 说明

程序适用于有权保存的普通 HLS/M3U8 内容，不用于绕过 DRM 或访问控制。带有效期的签名地址过期后，需要重新获取地址。
