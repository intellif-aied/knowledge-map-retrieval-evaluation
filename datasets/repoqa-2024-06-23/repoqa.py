#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".work"
VERSION = "2024-06-23"
ARCHIVE = WORK / f"repoqa-{VERSION}.json.gz"
URL = f"https://github.com/evalplus/repoqa_release/releases/download/{VERSION}/repoqa-{VERSION}.json.gz"
SHA256 = "c050a2ad90a7df89d9dc1f1c3b3b20683edd20a56293b35fcaae43dec115d681"
EXPECTED_LANGUAGES = {"python", "cpp", "java", "typescript", "rust", "go"}
EXPECTED_REPOSITORIES = 60
EXPECTED_FILES = 8775
EXPECTED_QUESTIONS = 600
MAX_BYTES = 50 * 1024 * 1024
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+-]{2,}")
TERM_STOP = {
    "the", "and", "for", "with", "this", "that", "from", "into", "within", "based",
    "a", "an", "to", "of", "is", "are", "be", "as", "or", "not", "it", "its", "by", "on", "in",
    "purpose", "input", "output", "procedure", "function", "method", "designed",
    "using", "used", "given", "specified", "provided", "returns", "return", "none",
    "which", "where", "when", "then", "than", "have", "will", "also", "their", "there", "such",
}


def download() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists() and hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == SHA256:
        return
    ARCHIVE.unlink(missing_ok=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "knowledge-map-repoqa-evaluation/1"})
    with urllib.request.urlopen(request, timeout=180) as response, ARCHIVE.open("wb") as output:
        shutil.copyfileobj(response, output)
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    if digest != SHA256:
        ARCHIVE.unlink(missing_ok=True)
        raise ValueError(f"RepoQA发布包校验失败: {digest}")


def load_data() -> dict[str, list[dict]]:
    if not ARCHIVE.exists():
        raise ValueError("请先运行 repoqa.py prepare")
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != SHA256:
        raise ValueError("RepoQA发布包SHA-256不匹配")
    with gzip.open(ARCHIVE, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    validate(data)
    return data


def validate(data: dict[str, list[dict]]) -> None:
    if set(data) != EXPECTED_LANGUAGES or any(len(repositories) != 10 for repositories in data.values()):
        raise ValueError("RepoQA必须是6种语言、每种10个仓库")
    repositories = [(language, repository) for language, items in data.items() for repository in items]
    if len(repositories) != EXPECTED_REPOSITORIES or len({repository["repo"] for _, repository in repositories}) != EXPECTED_REPOSITORIES:
        raise ValueError("RepoQA仓库数量或名称不正确")
    file_count = 0
    question_count = 0
    for language, repository in repositories:
        content = repository.get("content")
        needles = repository.get("needles")
        if not isinstance(content, dict) or not isinstance(needles, list) or len(needles) != 10:
            raise ValueError(f"{repository.get('repo')}数据结构不正确")
        file_count += len(content)
        question_count += len(needles)
        for path, body in content.items():
            if not isinstance(path, str) or not path or not isinstance(body, str):
                raise ValueError(f"{repository['repo']}包含无效Path或正文")
            encoded = body.encode("utf-8")
            if len(encoded) > MAX_BYTES or b"\0" in encoded:
                raise ValueError(f"{repository['repo']}/{path}不符合文本文件限制")
        for needle in needles:
            path = needle.get("path")
            description = str(needle.get("description") or "").strip()
            if path not in content or not description or not query_terms(description):
                raise ValueError(f"{repository['repo']}包含无效题目")
            encoded = content[path].encode("utf-8")
            start, end = needle.get("start_byte"), needle.get("end_byte")
            if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(encoded):
                raise ValueError(f"{repository['repo']}/{path}目标函数范围不正确")
            encoded[start:end].decode("utf-8")
            if (
                encoded[:start].count(b"\n") != needle.get("start_line")
                or encoded[:end].count(b"\n") != needle.get("end_line") - 1
            ):
                raise ValueError(f"{repository['repo']}/{path}目标函数行号不正确")
    if file_count != EXPECTED_FILES or question_count != EXPECTED_QUESTIONS:
        raise ValueError(f"RepoQA数量不正确: files={file_count}, questions={question_count}")


def query_terms(description: str) -> list[str]:
    terms: list[str] = []
    for match in WORD_RE.finditer(description):
        term = match.group(0).casefold()
        if term in TERM_STOP or term in terms:
            continue
        terms.append(term)
        if len(terms) == 5:
            break
    return terms


def main() -> None:
    parser = argparse.ArgumentParser(description="准备和验证RepoQA固定数据集")
    parser.add_argument("command", choices=("prepare", "verify"))
    args = parser.parse_args()
    if args.command == "prepare":
        download()
        data = load_data()
        print(f"RepoQA {VERSION}已准备: {len(data)}种语言/{EXPECTED_REPOSITORIES}仓库/{EXPECTED_QUESTIONS}题")
    elif args.command == "verify":
        load_data()
        print(f"RepoQA {VERSION}校验通过")
    else:
        load_data()
        print(f"RepoQA {VERSION}校验通过")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"错误: {error}", file=sys.stderr)
        raise SystemExit(1)
