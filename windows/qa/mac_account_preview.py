"""将 Windows 隔离窗口使用的虚构账户数据转换为原版离线预览格式。"""
import json
import sys
import time
from pathlib import Path

from agent_meter.model import SCHEMA_VERSION, metric, source, timestamp


def reference(frame, now):
    # 原版使用运行时的系统时钟。平移演示时间，保留每个额度窗口的剩余时长。
    offset = now - frame["clock"]
    rows = []
    for provider in ("codex", "kimi", "claude", "minimax"):
        sample = frame[provider]
        row = source("minimax_code" if provider == "minimax" else provider, "account", now)
        rows.append(row)
        if sample["plan"]:
            row["subscription"] = {"plan": sample["plan"]}
        quotas = []
        for q in sample["quota"]:
            quota = dict(q, used_percent=100 - q["remaining_percent"])
            if q.get("resets_at"):
                quota["resets_at"] = timestamp(q["resets_at"]["epoch_seconds"] + offset)
            quotas.append(quota)
        metrics = row["metrics"]
        metrics["quota"] = metric(quotas)
        if sample["credits"] is not None:
            metrics["credits"] = metric(sample["credits"])
        if sample["cards"] is not None:
            cards = sample["cards"]
            metrics["reset_cards"] = metric(dict(cards, cards=[
                dict(card, expires_at=timestamp(card["expires_at"]["epoch_seconds"] + offset))
                for card in cards["cards"]]))
        if sample["history"]:
            history = sample["history"]
            # 原版账户页按模型组上的 app 归集；Windows 投影已经按来源分桶。
            periods = {key: dict(bucket, groups=[dict(group, app=provider) for group in bucket.get("groups", [])])
                       for key, bucket in history["periods"].items()}
            metrics["tokens"] = metric({"periods": periods,
                                        "daily_buckets": (history.get("daily_trend") or {}).get("days", [])})
    return {"schema_version": SCHEMA_VERSION, "collected_at": timestamp(now), "sources": rows}


if __name__ == "__main__":
    sample = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    Path(sys.argv[2]).write_text(json.dumps(reference(sample, int(time.time()))), encoding="utf-8")
