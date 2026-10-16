#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "未找到项目虚拟环境。请先运行 bash run.sh 完成安装。" >&2
  exit 2
fi

echo "即将生成公开反馈：汇总、来源哈希、运行错误，以及 Utility 失败或 ASR 成功案例的完整轨迹。"
echo "反馈会作为独立分支和 Pull Request 提交；大文件会作为公开 Release 附件上传。"
read -r -p "确认公开上传？请输入 PUBLIC 确认： " confirmation
if [[ "$confirmation" != "PUBLIC" ]]; then
  echo "未确认公开上传；没有生成提交，也没有上传任何内容。"
  exit 0
fi

args=(--confirm-public-upload)
if [[ $# -gt 0 ]]; then
  args+=(--run-dir "$1")
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m as_all.feedback "${args[@]}"
