#!/usr/bin/env sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 "$root/datasets/chip-retrieval-v1/dataset.py" prepare
python3 "$root/datasets/chip-retrieval-v1/dataset.py" verify --public-only
python3 "$root/datasets/repoqa-2024-06-23/repoqa.py" prepare
python3 "$root/datasets/repoqa-2024-06-23/repoqa.py" verify
