"""只统计 Codex 生图目录内 PNG 文件元数据，不读取图片或会话内容。"""
import os
import stat
from datetime import date, datetime
from pathlib import Path

from agent_meter.model import DISPLAY_ZONE, SourceError, metric, period_bounds


def image_files(root, now, *, max_files=50000, max_dirs=10000):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("codex_images_not_found")
    def redirected(info):
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if redirected(os.stat(root, follow_symlinks=False)):
        raise SourceError("codex_images_redirected")
    periods = {key: 0 for key in ("today", "7d", "30d", "all")}
    bounds = {key: period_bounds(now, key, DISPLAY_ZONE) for key in periods}
    days, incomplete, seen, directories = {}, False, 0, 0
    def failed(_error):
        nonlocal incomplete
        incomplete = True
    for directory, names, files in os.walk(root, followlinks=False, onerror=failed):
        directories += 1
        if directories > max_dirs:
            incomplete = True
            break
        names.sort(); files.sort()
        safe_dirs = []
        for name in names:
            try:
                info = os.stat(Path(directory) / name, follow_symlinks=False)
                if redirected(info) or not stat.S_ISDIR(info.st_mode):
                    incomplete = True
                else: safe_dirs.append(name)
            except OSError:
                incomplete = True
        names[:] = safe_dirs
        for filename in files:
            if not filename.lower().endswith(".png"):
                continue
            if seen >= max_files:
                incomplete = True
                break
            seen += 1
            path = Path(directory) / filename
            try:
                info = os.stat(path, follow_symlinks=False)
                if redirected(info) or not stat.S_ISREG(info.st_mode) or not 0 <= info.st_mtime <= now:
                    incomplete = True
                    continue
                day = datetime.fromtimestamp(info.st_mtime, DISPLAY_ZONE).date().isoformat()
            except (OSError, ValueError, OverflowError):
                incomplete = True
                continue
            days[day] = days.get(day, 0) + 1
            for key, (start, end) in bounds.items():
                if (start is None or info.st_mtime >= start) and info.st_mtime <= end:
                    periods[key] += 1
        if seen >= max_files:
            # 达到上限即保守标记不完整，避免把截断结果当作总数。
            incomplete = True
            break
    value = {"basis": "codex_generated_images_png_files", "time_basis": "file_modified_time",
             "periods": {key: {"files": count} for key, count in periods.items()},
             "daily_buckets": [{"date": day, "images": count} for day, count in sorted(days.items())],
             "timezone": str(DISPLAY_ZONE)}
    return metric(value, status="partial" if incomplete else "available",
                  reason="codex_image_files_incomplete" if incomplete else None)


def medal_image_source(item, today):
    """只有完整、可复核的文件数量才进入图片徽章计算。"""
    if not isinstance(item, dict) or item.get("status") != "available": return None
    value = item.get("value")
    if not isinstance(value, dict) or value.get("basis") != "codex_generated_images_png_files": return None
    periods, rows = value.get("periods"), value.get("daily_buckets")
    if not isinstance(periods, dict) or not isinstance(periods.get("all"), dict) or not isinstance(rows, list): return None
    total = periods["all"].get("files")
    if isinstance(total, bool) or not isinstance(total, int) or not 0 <= total <= 50000: return None
    valid = []
    for row in rows:
        if not isinstance(row, dict): return None
        try:
            day = date.fromisoformat(row.get("date", ""))
        except (TypeError, ValueError): return None
        count = row.get("images")
        if day > today or day.isoformat() != row.get("date") or isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 50000: return None
        valid.append({"date": day.isoformat(), "images": count})
    if sum(row["images"] for row in valid) != total: return None
    return {"id": "codex_images", "metrics": {"image_generation": {"status": "available", "value": {"daily_buckets": valid}}}}
