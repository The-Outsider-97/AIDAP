"""Child-process entry point: parse stdin bytes, write one JSON document to stdout.

Run as a script with ``python -I`` so that the working directory and
user site-packages cannot shadow the standard library. Stdlib-only.
"""
import importlib.util
import json
import os
import sys


def _limit() -> None:
    try:
        import resource  # POSIX only; absent on Windows
        cpu = int(os.environ.get("AIDAP_PARSE_CPU_S", "20"))
        mem = int(os.environ.get("AIDAP_PARSE_MEM_MB", "1024")) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        except (ValueError, OSError):
            pass
    except ImportError:
        pass


def main() -> int:
    _limit()
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("aidap_parsers", os.path.join(here, "parsers.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fmt = sys.argv[1]
    max_records = int(sys.argv[2])
    max_chars = int(sys.argv[3])
    data = sys.stdin.buffer.read()
    out = mod.parse(data, fmt, max_records=max_records, max_chars=max_chars)
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
