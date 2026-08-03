"""兼容直接以脚本运行的 Fixture 评估入口。"""

from __future__ import annotations

import sys
from pathlib import Path

# ``python run_fixture_evaluation.py`` 时补上包的父目录；模块方式不受影响。
if __package__ in (None, ""):
    package_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(package_dir.parent))
    package_name = package_dir.name
    if package_name == "evaluation":
        from evaluation.evaluator import main
    else:
        from _llm_eval_stage.evaluator import main
else:
    from .evaluator import main


if __name__ == "__main__":
    raise SystemExit(main())
