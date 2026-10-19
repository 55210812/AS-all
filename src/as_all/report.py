"""Case-weighted reports built only from the unique native request ledger."""

import csv
import json
from collections import defaultdict
from as_all.cli import atomic, read, sha, status
from as_all.experiments import get_experiment
from as_all.methods import METHODS


def cost(path):
    result = {
        stage: dict(
            requests=0,
            responses=0,
            raw_input=0,
            output=0,
            cached_input=0,
            noncached_input=0,
            missing_usage=0,
            unknown_cache=0,
            request_seconds=0.0,
        )
        for stage in ("agent", "defense")
    }
    if not path.exists():
        return result
    seen = set()
    for line in path.read_text().splitlines():
        event = json.loads(line)
        identity = (event["request_id"], event["event"])
        if identity in seen:
            raise ValueError("Duplicate request ledger event")
        seen.add(identity)
        bucket = result[event["stage"]]
        if event["event"] == "request_started":
            bucket["requests"] += 1
        elif event["event"] in ("request_completed", "request_error"):
            bucket["request_seconds"] += event.get("elapsed_seconds", 0)
            # Each attempt is a real HTTP request, including rejected429/failed connects.
            bucket["requests"] += max(0, len(event.get("transport_attempts", [])) - 1)
            attempts = event.get("transport_attempts", [])
            # The last successful attempt is represented by the top-level usage.
            # Earlier retries can have their own billed usage; never discard it.
            usages = [a.get("raw_usage") for a in attempts if a.get("retry")]
            usages.append(event.get("raw_usage"))
            for usage in usages:
                _add_usage(bucket, usage, event.get("provider"))
    return result


def _add_usage(bucket, usage, provider=None):
    if not usage:
        bucket["missing_usage"] += 1
        return
    is_qwen = provider == "qwen" or any(
        key in usage for key in ("prompt_tokens", "completion_tokens", "prompt_tokens_details")
    )
    if is_qwen:
        if not all(k in usage for k in ("prompt_tokens", "completion_tokens")):
            bucket["missing_usage"] += 1
            return
        raw = usage["prompt_tokens"]
        output = usage["completion_tokens"]
        if type(raw) is not int or type(output) is not int or raw < 0 or output < 0:
            raise ValueError("Invalid supplier token count")
        bucket["responses"] += 1
        bucket["raw_input"] += raw
        # OpenAI-compatible completion_tokens already includes reasoning tokens.
        bucket["output"] += output
        details = usage.get("prompt_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        if cached is None:
            bucket["unknown_cache"] += 1
        else:
            if type(cached) is not int or not 0 <= cached <= raw:
                raise ValueError("Invalid supplier cache count")
            bucket["cached_input"] += cached
            bucket["noncached_input"] += raw - cached
        return
    if not all(k in usage for k in ("promptTokenCount", "candidatesTokenCount")):
        bucket["missing_usage"] += 1
        return
    bucket["responses"] += 1
    raw = usage["promptTokenCount"]
    bucket["raw_input"] += raw
    # Candidate + thought is counted once, not total + thought.
    thoughts = usage.get("thoughtsTokenCount")
    if thoughts is None:
        thoughts = (
            usage.get("totalTokenCount", usage["promptTokenCount"] + usage["candidatesTokenCount"])
            - raw
            - usage["candidatesTokenCount"]
        )
    if thoughts < 0:
        raise ValueError("Invalid supplier reasoning count")
    bucket["output"] += usage["candidatesTokenCount"] + thoughts
    cached = usage.get("cachedContentTokenCount")
    if cached is None:
        bucket["unknown_cache"] += 1
    else:
        if not 0 <= cached <= raw:
            raise ValueError("Invalid supplier cache count")
        bucket["cached_input"] += cached
        bucket["noncached_input"] += raw - cached


def report(run_dir):
    manifest = read(run_dir / "manifest.json")
    experiment = manifest.get(
        "experiment_id", manifest.get("experiment", "gemini-important")
    )
    profile = get_experiment(experiment)
    model = manifest.get("model", profile.model)
    attack = manifest.get("attack", profile.attack)
    provider = manifest.get("provider", profile.provider)
    rows = []
    for path in sorted((run_dir / "cases").glob("*/result.json")):
        row = read(path)
        row_experiment = row.get("experiment_id", row.get("experiment"))
        if row_experiment not in (None, experiment):
            raise ValueError(
                f"Case {row.get('id', path.parent.name)} belongs to experiment "
                f"{row_experiment}, not {experiment}"
            )
        if "costs" not in row:
            row["costs"] = cost(path.parent / "requests.jsonl")
        rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        groups[row["method"], "Attack" if row["injection"] else "Clean"].append(row)
    summaries = []
    lines = [
        f"# {model} {attack} 十一方法结果",
        "",
        f"实验：`{experiment}`；供应商：`{provider}`。",
        "",
        "原始评测保留；运行错误不是成功防御。Token按案例平均，输入不扣缓存。",
        "缺失usage或缓存字段列为未知；带unknown的数值仅是已知部分。",
        "",
    ]
    for scene in ("Clean", "Attack"):
        lines += [
            f"## {scene}",
            "",
            "| 方法 | 正常/终止 | Utility | ASR | Agent请求 | 防御请求 | Agent平均原始输入 | Agent平均输出 | 防御平均原始输入 | 防御平均输出 | 平均秒 | 未知usage/缓存 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for method in METHODS:
            items = groups[method, scene]
            normal = [r for r in items if not r.get("error")]
            n = len(normal)
            data = dict(
                method=method,
                scene=scene,
                terminal=len(items),
                normal=n,
                utility=sum(r["utility"] for r in normal),
                asr=sum(bool(r["asr"]) for r in normal) if scene == "Attack" else None,
            )
            for stage in ("agent", "defense"):
                for field in (
                    "requests",
                    "raw_input",
                    "output",
                    "cached_input",
                    "noncached_input",
                    "missing_usage",
                    "unknown_cache",
                ):
                    # Selected normal cases and runtime error costs stay in separate files.
                    data[f"{stage}_{field}"] = sum(r["costs"][stage][field] for r in normal)
            data["average_seconds"] = sum(r["duration_seconds"] or 0 for r in normal) / n if n else None
            summaries.append(data)

            def avg(key):
                return f"{data[key] / n:.2f}" if n else "—"

            lines.append(
                "| "
                + " | ".join(
                    [
                        method,
                        f"{n}/{len(items)}",
                        f"{data['utility']}/{n}" if n else "—",
                        f"{data['asr']}/{n}" if scene == "Attack" and n else "—",
                        str(data["agent_requests"]),
                        str(data["defense_requests"]),
                        avg("agent_raw_input"),
                        avg("agent_output"),
                        avg("defense_raw_input"),
                        avg("defense_output"),
                        f"{data['average_seconds']:.2f}" if n else "—",
                        str(sum(data[f"{s}_missing_usage"] for s in ("agent", "defense")))
                        + "/"
                        + str(sum(data[f"{s}_unknown_cache"] for s in ("agent", "defense"))),
                    ]
                )
                + " |"
            )
        lines += [""]
        lines += ["### 实际缓存（按案例平均）", "",
                  "未知字段不当作零；以下缓存／非缓存列仅汇总供应商可核验部分。", "",
                  "| 方法 | Agent缓存 | Agent非缓存 | Agent未知usage/缓存 | 防御缓存 | 防御非缓存 | 防御未知usage/缓存 |",
                  "|---|---:|---:|---|---:|---:|---|"]
        for data in [row for row in summaries if row["scene"] == scene]:
            n = data["normal"]
            cells = [data["method"]]
            for stage in ("agent", "defense"):
                cells += [f"{data[f'{stage}_{field}']/n:.2f}" if n else "—"
                          for field in ("cached_input", "noncached_input")]
                cells.append(f"{data[f'{stage}_missing_usage']}/{data[f'{stage}_unknown_cache']}")
            lines.append("| " + " | ".join(cells) + " |")
        lines += [""]
    out = run_dir / "report"
    atomic(out / "summary.json", summaries)
    atomic(out / "runtime_errors.json", [r for r in rows if r.get("error")])
    atomic(out / "source_hashes.json", manifest["source_hashes"])
    atomic(
        out / "paired1046.json",
        {cid: {r["method"]: r for r in rows if r["case_id"] == cid} for cid in sorted({r["case_id"] for r in rows})},
    )
    atomic(
        out / "actual_costs.json",
        [{"id": r["id"], "method": r["method"], "error": r.get("error"), "costs": r["costs"]} for r in rows],
    )
    out.mkdir(exist_ok=True)
    (out / "summary.md").write_text("\n".join(lines))
    with (out / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    current = status(run_dir)
    atomic(run_dir / "status.json", current)
    if current["all_terminal"]:
        atomic(
            run_dir / "completion.json",
            {**current, "all_outputs_valid": not current["runtime_errors"], "report_sha256": sha(out / "summary.json")},
        )
    return current
