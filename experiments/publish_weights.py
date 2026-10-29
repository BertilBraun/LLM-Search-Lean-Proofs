"""Merge an adapter and swap running vLLM servers to it in place, or free and restore the servers' GPUs.

    python experiments/publish_weights.py merge --adapter <adapter> --output <merged> [--device cuda:0|--dtype float16]
    python experiments/publish_weights.py publish --weights <merged> --server-url http://127.0.0.1:8100/v1 ...
    python experiments/publish_weights.py release --server-url ...      # sleep: weights and KV cache freed
    python experiments/publish_weights.py restore --weights <merged> --server-url ...
    python experiments/publish_weights.py difference --target <value adapter> --merged <policy adapter> \
        --output <adapter> [--name value-v0 --server-url ...]

Servers must run with VLLM_SERVER_DEV_MODE=1 (serve_model.sh sets it), release/restore also with
SLEEP_MODE=1. Each command prints its phase timings as JSON.
"""

import argparse
import asyncio
import dataclasses
import json
import time
from pathlib import Path

from lean_search.policy.adapters import difference_adapter, merge_adapter, merge_adapter_fp16
from lean_search.policy.server_control import publish_weights, release_gpu, replace_adapter, restore_gpu


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--base-model", default="Qwen/Qwen3.5-2B")
    merge.add_argument("--adapter", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--device", default="cpu")
    merge.add_argument(
        "--dtype",
        choices=["bfloat16", "float16"],
        default="bfloat16",
        help="float16: merged in fp32 on the CPU, then cast",
    )
    for name in ("publish", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--weights", type=Path, required=True)
        command.add_argument("--server-url", action="append", required=True)
    release = commands.add_parser("release")
    release.add_argument("--server-url", action="append", required=True)
    difference = commands.add_parser("difference")
    difference.add_argument("--target", type=Path, required=True, help="adapter the served model should apply")
    difference.add_argument("--merged", type=Path, required=True, help="adapter merged into the served weights")
    difference.add_argument("--output", type=Path, required=True)
    difference.add_argument("--name", help="served adapter name to replace on --server-url")
    difference.add_argument("--server-url", action="append", default=[])
    return parser.parse_args()


async def on_servers(arguments: argparse.Namespace) -> list[object]:
    match arguments.command:
        case "publish":
            phases = [publish_weights(url, arguments.weights.resolve()) for url in arguments.server_url]
        case "release":
            phases = [release_gpu(url) for url in arguments.server_url]
        case "restore":
            phases = [restore_gpu(url, arguments.weights.resolve()) for url in arguments.server_url]
        case "difference":
            phases = [replace_adapter(url, arguments.name, arguments.output.resolve()) for url in arguments.server_url]
    return list(await asyncio.gather(*phases))


def main() -> None:
    arguments = parse_arguments()
    started = time.monotonic()
    match arguments.command:
        case "merge" if arguments.dtype == "float16":
            merge_adapter_fp16(arguments.base_model, arguments.adapter, arguments.output)
            print(json.dumps({"merge_seconds": time.monotonic() - started}))
        case "merge":
            merge_adapter(arguments.base_model, arguments.adapter, arguments.output, arguments.device)
            print(json.dumps({"merge_seconds": time.monotonic() - started}))
        case "difference":
            difference_adapter(arguments.target, arguments.merged, arguments.output)
            written = time.monotonic()
            asyncio.run(on_servers(arguments))
            print(json.dumps({"write_seconds": written - started, "load_seconds": time.monotonic() - written}))
        case "publish" | "release" | "restore":
            phases = asyncio.run(on_servers(arguments))
            report = {
                "servers": [dataclasses.asdict(phase) | {"total": phase.total} for phase in phases],
                "seconds": time.monotonic() - started,
            }
            print(json.dumps(report))


if __name__ == "__main__":
    main()
