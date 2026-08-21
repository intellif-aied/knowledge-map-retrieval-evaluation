#!/usr/bin/env python3
import argparse
import base64
import csv
import hmac
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".work"
MAX_BYTES = 50 * 1024 * 1024
BASE_URLS = {
    "vortex": "https://raw.githubusercontent.com/vortexgpgpu/vortex",
    "opentitan": "https://raw.githubusercontent.com/lowRISC/opentitan",
}
EXPECTED_PROJECTS = Counter(vortex=700, opentitan=300)
EXPECTED_CATEGORIES = {
    "file-path-symbol": 50,
    "chinese-natural-language": 50,
    "late-file": 40,
    "multi-document": 50,
    "similar-distractor": 40,
    "no-answer": 30,
    "multiple-expansions": 40,
}
SMOKE_EXPECTED_CATEGORIES = {
    "file-path-symbol": 8,
    "chinese-natural-language": 8,
    "late-file": 6,
    "multi-document": 6,
    "similar-distractor": 4,
    "no-answer": 4,
    "multiple-expansions": 4,
}
FRESH_LOCKED_SOURCE_IDS = """V002,V004,V027,V028,V043,V045,V046,V047,V048,V049,V050,V053,V060,V082,V134,V135,V136,V137,V138,V139,V140,V141,V142,V143,V144,V145,V146,V147,V148,V149,V150,V151,V152,V153,V154,V155,V156,V157,V158,V159,V160,V161,V162,V163,V164,V165,V166,V167,V168,V169,O005,O006,O007,O031,O043,O044,O045,O046,O047,O048,O050,O051,O052,O053,O054,O055,O056,O057,O058,O059,O060,O061,O062,O063,O064,O068,O069,O070,O071,O073,O074,O077,O078,O079,O081,O082,O083,O084,O088,O091,O092,O095,O098,O100,O103,O104,O108,O109,O112,O113""".split(",")


def rows(name):
    with (ROOT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_search_rounds(value):
    return [[term.strip() for term in part.split(";") if term.strip()] for part in value.split(" | ")]


def parse_search_questions(value):
    questions = json.loads(value)
    if not isinstance(questions, list) or any(not isinstance(question, str) for question in questions):
        raise ValueError("每轮检索问题必须是JSON字符串数组")
    return questions


def check_text(path):
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"超过50 MiB: {path}")
    if b"\0" in data:
        raise ValueError(f"包含NUL字节: {path}")
    data.decode("utf-8")


def download(url, target):
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "knowledge-map-evaluation/1"})
            with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as output:
                shutil.copyfileobj(response, output)
            return
        except Exception:
            target.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def check_structure():
    public = rows("public-files.tsv")
    if len(public) != 1000 or Counter(row["project"] for row in public) != EXPECTED_PROJECTS:
        raise ValueError("公开语料必须是Vortex 700份、OpenTitan 300份")
    for field in ("id", "upload_name"):
        values = [row[field] for row in public]
        if len(values) != len(set(values)):
            raise ValueError(f"public-files.tsv存在重复{field}")
    source_keys = [(row["project"], row["revision"], row["path"]) for row in public]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("public-files.tsv存在重复来源Path")
    chinese = rows("chinese-files.tsv")
    if len(chinese) != 20:
        raise ValueError("中文交付材料必须是20份")
    questions = rows("questions.tsv")
    if len(questions) != 300 or len({row["id"] for row in questions}) != 300:
        raise ValueError("评测问题必须是300条且ID不重复")
    counts = Counter(row["category"] for row in questions)
    if counts != Counter(EXPECTED_CATEGORIES):
        raise ValueError(f"评测问题分类数量不正确: {dict(counts)}")
    smoke_files = rows("smoke-files.tsv")
    public_by_id = {row["id"]: row for row in public}
    if len(smoke_files) != 20 or any(public_by_id.get(row["id"]) != row for row in smoke_files):
        raise ValueError("冒烟文件必须是公开语料中固定的20份")
    smoke_questions = rows("smoke-questions.tsv")
    if len(smoke_questions) != 40 or len({row["id"] for row in smoke_questions}) != 40:
        raise ValueError("冒烟问题必须是40条且ID不重复")
    smoke_counts = Counter(row["category"] for row in smoke_questions)
    if smoke_counts != Counter(SMOKE_EXPECTED_CATEGORIES):
        raise ValueError(f"冒烟问题分类数量不正确: {dict(smoke_counts)}")
    used_ids = {
        item
        for question in [*questions, *smoke_questions]
        for item in question["expected_match_ids"].split(",")
        if item
    }
    if len(FRESH_LOCKED_SOURCE_IDS) != 100 or len(set(FRESH_LOCKED_SOURCE_IDS)) != 100:
        raise ValueError("全新锁定集必须固定100个不重复来源")
    if any(item not in public_by_id or item in used_ids for item in FRESH_LOCKED_SOURCE_IDS):
        raise ValueError("全新锁定集来源必须存在且未被开发集、旧对比集或冒烟集使用")
    return public, chinese, questions


def fresh_locked_questions(public):
    public_by_id = {row["id"]: row for row in public}
    questions = []
    for index, source_id in enumerate(FRESH_LOCKED_SOURCE_IDS, 1):
        source = public_by_id[source_id]
        path = WORK / "sources" / source["project"] / source["path"]
        lines = [" ".join(line.split()) for line in path.read_text(encoding="utf-8").splitlines()]
        quote = next((line[:160] for line in lines if len(line) >= 4), "")
        if not quote:
            raise ValueError(f"{source_id}没有可校验的首段原文")
        filename = Path(source["path"]).name
        question = f"请定位名为{filename}的文件，并返回能够确认该文件的第一处原文。"
        questions.append({
            "id": f"N{index:03d}",
            "category": "fresh-locked-path",
            "user_question": question,
            "search_round_questions": json.dumps([question], ensure_ascii=False),
            "standard_answer": f"目标文件是{source['path']}。",
            "expected_paths": source["path"],
            "required_quote": quote,
            "allowed_search_terms": filename,
            "expected_match_ids": source_id,
            "max_expansions": "1",
            "stop_condition": "定位唯一文件并取得第一处原文即可停止",
            "review_status": "SOURCE_VERIFIED",
            "reviewer": "dataset.py/source-check",
        })
    return questions


def prepare():
    public, _, _ = check_structure()
    sources = WORK / "sources"
    upload = WORK / "upload"
    upload.mkdir(parents=True, exist_ok=True)

    def fetch(row):
        target = sources / row["project"] / row["path"]
        url = f'{BASE_URLS[row["project"]]}/{row["revision"]}/{row["path"]}'
        download(url, target)
        check_text(target)
        shutil.copyfile(target, upload / row["upload_name"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, public))
    licenses = WORK / "LICENSES"
    for project in BASE_URLS:
        revision = next(row["revision"] for row in public if row["project"] == project)
        download(f"{BASE_URLS[project]}/{revision}/LICENSE", licenses / f"{project}-LICENSE")
    lines = []
    for row in public:
        source = sources / row["project"] / row["path"]
        lines.append(f'{hashlib.sha256(source.read_bytes()).hexdigest()}  {row["project"]}/{row["path"]}')
    computed = "\n".join(lines) + "\n"
    (WORK / "computed.sha256").write_text(computed, encoding="utf-8")
    expected = ROOT / "checksums.sha256"
    if expected.exists() and expected.stat().st_size and expected.read_text(encoding="utf-8") != computed:
        raise ValueError("公开语料校验值与checksums.sha256不一致")
    print(f"已准备{len(public)}份公开语料: {upload}")


def verify_questions(public, questions):
    required = ("user_question", "search_round_questions", "standard_answer", "required_quote", "allowed_search_terms", "max_expansions", "stop_condition", "reviewer")
    sources = {row["id"]: WORK / "sources" / row["project"] / row["path"] for row in public}
    source_paths = {row["id"]: row["path"] for row in public}
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in sources.values()).lower()
    for row in questions:
        if row["review_status"] not in {"SOURCE_VERIFIED", "APPROVED"} or any(not row[field].strip() for field in required):
            raise ValueError(f'{row["id"]}尚未完成原文校验')
        search_rounds = parse_search_rounds(row["allowed_search_terms"])
        search_questions = parse_search_questions(row["search_round_questions"])
        if not 1 <= len(search_rounds) <= 3 or any(not 1 <= len(terms) <= 5 for terms in search_rounds) or not 1 <= int(row["max_expansions"]) <= 3:
            raise ValueError(f'{row["id"]}搜索词或展开次数不合法')
        if len(search_questions) != len(search_rounds) or any(not question.strip() or len(question) > 2000 for question in search_questions):
            raise ValueError(f'{row["id"]}每轮检索问题不合法')
        ids = [item for item in row["expected_match_ids"].split(",") if item]
        if row["category"] == "multi-document" and (len(search_rounds) != len(ids) or len(ids) < 2):
            raise ValueError(f'{row["id"]}多文档题必须每份预期文档使用一轮搜索')
        if row["category"] == "no-answer":
            if ids or row["expected_paths"] or row["required_quote"] != "NONE":
                raise ValueError(f'{row["id"]}无答案题不得声明命中来源')
            if any(term.lower() in corpus for terms in search_rounds for term in terms):
                raise ValueError(f'{row["id"]}无答案搜索词实际存在于语料中')
            continue
        if not ids or any(item not in sources for item in ids):
            raise ValueError(f'{row["id"]}引用了不存在的来源ID')
        if row["expected_paths"] != " | ".join(source_paths[item] for item in ids):
            raise ValueError(f'{row["id"]}预期Path与来源ID不一致')
        normalized_sources = "\n".join(" ".join(sources[item].read_text(encoding="utf-8").split()) for item in ids)
        for quote in row["required_quote"].split(" || "):
            if quote not in normalized_sources:
                raise ValueError(f'{row["id"]}引用不在固定原文中: {quote}')


def verify(structure_only, public_only):
    public, chinese, questions = check_structure()
    if structure_only:
        print("数据集结构检查通过；企业中文材料尚未验收")
        return
    expected = ROOT / "checksums.sha256"
    computed = WORK / "computed.sha256"
    if not expected.exists() or not computed.exists() or expected.read_bytes() != computed.read_bytes():
        raise ValueError("请先运行dataset.py prepare并确认公开语料校验值")
    verify_questions(public, questions)
    verify_questions(rows("smoke-files.tsv"), rows("smoke-questions.tsv"))
    locked_files = [row for row in public if row["id"] in set(FRESH_LOCKED_SOURCE_IDS)]
    verify_questions(locked_files, fresh_locked_questions(public))
    if public_only:
        print("20文件/40题冒烟集、1000文件/300题工程集及100题全新Path锁定集原文校验通过；未包含企业中文领域验收")
        return
    for row in chinese:
        if row["review_status"] != "APPROVED" or not row["reviewer"].strip() or not row["file_name"].strip():
            raise ValueError(f'{row["id"]}尚未完成人工复核')
        check_text(WORK / "chinese" / row["file_name"])
    print("工程回归数据集验证通过")


def bearer_token(secret, user_id):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signing_input = encode({"alg": "HS256", "typ": "JWT"}) + "." + encode({"uid": user_id})
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return signing_input + "." + signature


class MCPClient:
    def __init__(self, endpoint, token):
        self.endpoint = endpoint
        self.token = token
        self.request_id = 0
        self.request("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "knowledge-map-evaluator", "version": "1"},
        })

    def request(self, method, params):
        self.request_id += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params}).encode()
        request = urllib.request.Request(self.endpoint, data=payload, headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        with urllib.request.urlopen(request, timeout=180) as response:
            envelope = json.load(response)
        if "error" in envelope:
            raise RuntimeError(f"MCP {method}失败: {envelope['error']}")
        return envelope["result"]

    def call(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            message = next((item.get("text", "") for item in result.get("content", []) if item.get("type") == "text"), "")
            raise RuntimeError(f"{name}失败: {message}")
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        text_result = next((item.get("text") for item in result.get("content", []) if item.get("type") == "text"), None)
        return json.loads(text_result) if text_result else {}


def wait_for_task(client, task_id, wanted, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.call("get_knowledge_base_task", {"task_id": task_id})
        task = result.get("task") or {}
        status = (task.get("summary") or {}).get("status")
        if status in wanted:
            return task
        if status in {"failed", "publishing_failed", "cancelled", "no_content"}:
            raise RuntimeError(f"任务{task_id}异常结束: {status} {task.get('failure')}")
        time.sleep(0.5)
    raise TimeoutError(f"等待任务{task_id}超时")


def upload_corpus(client, public):
    upload_root = WORK / "upload"
    uploaded = {}
    for offset in range(0, len(public), 10):
        batch = public[offset:offset + 10]
        prepared = client.call("prepare_knowledge_file_uploads", {"files": [
            {"name": row["upload_name"], "size_bytes": (upload_root / row["upload_name"]).stat().st_size}
            for row in batch
        ]})["results"]
        paths = []
        for row, item in zip(batch, prepared, strict=True):
            if not item.get("accepted"):
                raise RuntimeError(f'{row["id"]}上传准备失败: {item.get("error")}')
            source = upload_root / row["upload_name"]
            request = urllib.request.Request(item["upload_url"], data=source.read_bytes(), method="PUT", headers={
                "Content-Type": "application/octet-stream", "Content-Length": str(source.stat().st_size),
            })
            with urllib.request.urlopen(request, timeout=180) as response:
                if response.status != 201:
                    raise RuntimeError(f'{row["id"]}上传失败: HTTP {response.status}')
            paths.append({"path": item["platform_path"]})
            uploaded[row["id"]] = {"file_id": item["upload_id"], "platform_path": item["platform_path"]}
        operation = "create" if offset == 0 else "update"
        started = client.call("start_knowledge_base_creation_or_update", {"operation": operation, "files": paths})
        task_id = started["task"]["summary"]["task_id"]
        task = wait_for_task(client, task_id, {"awaiting_review"})
        client.call("submit_knowledge_item_selection", {
            "task_id": task_id, "items_revision": task["items_revision"],
            "selection": "all", "selected_item_ids": [],
        })
        wait_for_task(client, task_id, {"published"})
        total_batches = (len(public) + 9) // 10
        print(f"已完成第{offset // 10 + 1}/{total_batches}批: {operation} {len(batch)}个文件", flush=True)
    return uploaded


def poll_query(client, question, terms):
    result = client.call("query_my_knowledge_base", {"question": question, "search_terms": terms})
    deadline = time.monotonic() + 60
    while result.get("status") == "processing" and time.monotonic() < deadline:
        time.sleep(0.2)
        result = client.call("query_my_knowledge_base", {"question": question, "query_id": result["query_id"]})
    if result.get("status") != "completed":
        raise RuntimeError(f"查询未完成: {result.get('status')}")
    return result


def rank_matches_by_expected_preview(matches, expected_quotes):
    """Oracle ordering for evidence-retrievability metrics, not Agent-quality scoring."""
    def score(match):
        preview = " ".join(str(match.get("preview") or "").casefold().split())
        best = 0
        for quote in expected_quotes:
            normalized = " ".join(quote.casefold().split())
            terms = re.findall(r"[a-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]{2,}", normalized)
            value = (10_000 if normalized and normalized in preview else 0) + sum(len(term) for term in set(terms) if term in preview)
            best = max(best, value)
        return best
    return sorted(matches, key=score, reverse=True)


def evaluate_questions(client, public, questions):
    upload_names = {row["id"]: row["upload_name"] for row in public}
    results = []
    for index, row in enumerate(questions, 1):
        started_at = time.monotonic()
        record = {"id": row["id"], "category": row["category"]}
        try:
            expected_ids = [item for item in row["expected_match_ids"].split(",") if item]
            expected_names = {upload_names[item] for item in expected_ids}
            search_rounds = parse_search_rounds(row["allowed_search_terms"])
            search_questions = parse_search_questions(row["search_round_questions"])
            if len(search_rounds) > 1 and len(expected_ids) == len(search_rounds):
                round_expected_names = [{upload_names[item]} for item in expected_ids]
            else:
                round_expected_names = [expected_names for _ in search_rounds]
            evidence = []
            top_sources_5 = []
            top_sources_10 = []
            first_round_sources_5 = []
            first_round_sources_10 = []
            round_top_sources = []
            total_matches = 0
            expanded_count = 0
            max_expansions = int(row["max_expansions"])
            quotes = [] if row["required_quote"] == "NONE" else row["required_quote"].split(" || ")
            for round_number, terms in enumerate(search_rounds, 1):
                result = poll_query(client, search_questions[round_number - 1], terms)
                matches = result.get("matches", [])
                total_matches += len(matches)
                round_sources_10 = []
                for match in matches:
                    source = match.get("source") or match.get("title")
                    if source not in round_sources_10:
                        round_sources_10.append(source)
                    if len(round_sources_10) == 10:
                        break
                round_sources_5 = round_sources_10[:5]
                if round_number == 1:
                    first_round_sources_5 = round_sources_5
                    first_round_sources_10 = round_sources_10
                round_top_sources.append(round_sources_10)
                for source in round_sources_5:
                    if source not in top_sources_5:
                        top_sources_5.append(source)
                for source in round_sources_10:
                    if source not in top_sources_10:
                        top_sources_10.append(source)
                candidates = [match for match in matches if (match.get("source") or match.get("title")) in round_expected_names[round_number - 1]]
                round_quotes = [quotes[round_number - 1]] if len(quotes) == len(search_rounds) else quotes
                candidates = rank_matches_by_expected_preview(candidates, round_quotes)
                round_limit = 1 if len(search_rounds) > 1 and len(expected_ids) == len(search_rounds) else max_expansions
                for match in candidates[:round_limit]:
                    expanded = client.call("query_my_knowledge_base", {
                        "question": search_questions[round_number - 1], "query_id": result["query_id"], "match_id": match["match_id"],
                    })
                    evidence.extend(item.get("content", "") for item in expanded.get("evidence", []))
                    expanded_count += 1
                normalized_evidence = " ".join("\n".join(evidence).split())
                if expected_names.issubset(set(top_sources_10)) and all(quote in normalized_evidence for quote in quotes):
                    break
            record["first_round_path_recall_at_5"] = expected_names.issubset(set(first_round_sources_5)) if expected_names else not first_round_sources_5
            record["first_round_path_recall_at_10"] = expected_names.issubset(set(first_round_sources_10)) if expected_names else not first_round_sources_10
            record["first_round_subquestion_recall_at_5"] = round_expected_names[0].issubset(set(first_round_sources_5)) if expected_names else not first_round_sources_5
            record["first_round_subquestion_recall_at_10"] = round_expected_names[0].issubset(set(first_round_sources_10)) if expected_names else not first_round_sources_10
            record["path_recall_at_5"] = expected_names.issubset(set(top_sources_5)) if expected_names else not top_sources_5
            record["path_recall_at_10"] = expected_names.issubset(set(top_sources_10)) if expected_names else not top_sources_10
            record["evidence_covered"] = all(quote in normalized_evidence for quote in quotes)
            record["match_count"] = total_matches
            record["expanded_count"] = expanded_count
            record["top_sources"] = top_sources_10
            record["round_top_sources"] = round_top_sources
        except Exception as error:
            record.update({"path_recall_at_5": False, "path_recall_at_10": False, "evidence_covered": False, "error": str(error)})
        record["duration_ms"] = round((time.monotonic() - started_at) * 1000)
        results.append(record)
        print(f"题目 {index}/{len(questions)}: {row['id']} path={record['path_recall_at_5']} evidence={record['evidence_covered']}", flush=True)
    return results


def evaluate():
    public, chinese, questions = check_structure()
    prepare()
    evaluation_split = os.environ.get("EVALUATION_SPLIT", "development").strip()
    if evaluation_split == "smoke":
        public = rows("smoke-files.tsv")
        questions = rows("smoke-questions.tsv")
    elif evaluation_split == "locked-v2":
        questions = fresh_locked_questions(public)
        public = [row for row in public if row["id"] in set(FRESH_LOCKED_SOURCE_IDS)]
    elif evaluation_split == "development":
        questions = questions[:200]
    elif evaluation_split == "locked":
        questions = questions[200:]
    elif evaluation_split != "all":
        raise ValueError("EVALUATION_SPLIT必须是smoke、development、locked、locked-v2或all")
    endpoint = os.environ.get("MCP_URL", "").strip()
    secret = os.environ.get("AIHUB_SECRET", "").strip()
    user_id = os.environ.get("AIHUB_USER_ID", "eval-user").strip()
    if not endpoint or not secret or not user_id:
        raise ValueError("MCP_URL、AIHUB_SECRET和AIHUB_USER_ID不能为空")
    client = MCPClient(endpoint, bearer_token(secret, user_id))
    upload_started_at = time.monotonic()
    uploaded = upload_corpus(client, public)
    publication_seconds = round(time.monotonic() - upload_started_at, 3)
    results = evaluate_questions(client, public, questions)
    query_durations = sorted(int(row["duration_ms"]) for row in results)
    first_round_passed = sum(bool(row.get("first_round_path_recall_at_5")) for row in results)
    first_round_passed_10 = sum(bool(row.get("first_round_path_recall_at_10")) for row in results)
    first_subquestion_passed = sum(bool(row.get("first_round_subquestion_recall_at_5")) for row in results)
    first_subquestion_passed_10 = sum(bool(row.get("first_round_subquestion_recall_at_10")) for row in results)
    path_passed = sum(bool(row["path_recall_at_5"]) for row in results)
    path_passed_10 = sum(bool(row["path_recall_at_10"]) for row in results)
    evidence_passed = sum(bool(row["evidence_covered"]) for row in results)
    no_answer = [row for row in results if row["category"] == "no-answer"]
    category_metrics = {}
    for category in sorted({row["category"] for row in results}):
        category_results = [row for row in results if row["category"] == category]
        category_metrics[category] = {
            "questions": len(category_results),
            "first_round_path_passed": sum(bool(row.get("first_round_path_recall_at_5")) for row in category_results),
            "first_round_path_passed_at_10": sum(bool(row.get("first_round_path_recall_at_10")) for row in category_results),
            "first_round_subquestion_passed": sum(bool(row.get("first_round_subquestion_recall_at_5")) for row in category_results),
            "first_round_subquestion_passed_at_10": sum(bool(row.get("first_round_subquestion_recall_at_10")) for row in category_results),
            "path_passed": sum(bool(row["path_recall_at_5"]) for row in category_results),
            "path_passed_at_10": sum(bool(row["path_recall_at_10"]) for row in category_results),
            "evidence_passed": sum(bool(row["evidence_covered"]) for row in category_results),
        }
    report = {
        "dataset": (
            "progressive-retrieval-smoke-v1" if evaluation_split == "smoke"
            else "progressive-retrieval-locked-v2" if evaluation_split == "locked-v2"
            else "progressive-retrieval-v1"
        ),
        "files": len(public), "questions": len(questions),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "commit": os.environ.get("EVALUATION_COMMIT", "unknown"),
        "environment": "isolated-docker", "test_user": user_id,
        "publication_seconds": publication_seconds,
        "query_duration_ms": {
            "p50": query_durations[len(query_durations) // 2],
            "p95": query_durations[max(0, int(len(query_durations) * 0.95) - 1)],
            "max": query_durations[-1],
        },
        "chinese_files_included": sum(row["review_status"] == "APPROVED" for row in chinese),
        "first_round_path_recall_at_5": first_round_passed / len(results),
        "first_round_path_recall_at_10": first_round_passed_10 / len(results),
        "first_round_subquestion_recall_at_5": first_subquestion_passed / len(results),
        "first_round_subquestion_recall_at_10": first_subquestion_passed_10 / len(results),
        "path_recall_at_5": path_passed / len(results),
        "path_recall_at_10": path_passed_10 / len(results),
        "evidence_coverage": evidence_passed / len(results),
        "no_answer_accuracy": (
            sum(bool(row["path_recall_at_5"]) for row in no_answer) / len(no_answer)
            if no_answer else None
        ),
        "category_metrics": category_metrics, "uploaded": uploaded, "results": results,
    }
    result_dir = WORK / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"uploaded", "results"}}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="准备和验证渐进检索评测数据集")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("evaluate")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--structure-only", action="store_true")
    verify_parser.add_argument("--public-only", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "evaluate":
        evaluate()
    else:
        verify(args.structure_only, args.public_only)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"错误: {error}", file=sys.stderr)
        raise SystemExit(1)
