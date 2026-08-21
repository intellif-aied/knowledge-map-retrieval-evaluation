# 渐进检索评测数据集 v1

本目录保存Knowledge Map渐进检索的固定芯片研发场景评测数据。

## 当前组成

- `public-files.tsv`：1000份固定公开语料，Vortex 700份、OpenTitan 300份；
- `smoke-files.tsv`：从固定公开语料中选出的20份流程冒烟文件；
- `smoke-questions.tsv`：40条流程冒烟问题，答案和引用均已通过固定原文校验；
- `chinese-files.tsv`：20份企业中文交付材料审核槽位，不包含虚构正文；
- `questions.tsv`：300题工程回归集，答案和引用均绑定固定公开原文；
- `dataset.py`：下载固定Revision、生成上传文件并验证数据集；
- `checksums.sha256`：公开语料固定校验值，由准备脚本校验。

`dataset.py`还固定了100个未被冒烟集或300题工程集引用的来源，用确定性模板形成全新Path锁定集。该集合只验证未调参来源的文件定位泛化，不替代多文档、远距离片段和无答案等综合指标。

## 使用

```bash
cd evaluation/progressive-retrieval-v1
python3 dataset.py prepare
```

生成内容位于本目录的`.work/`，不提交Git：

- `.work/sources/`：保留项目名和原始相对Path；
- `.work/upload/`：扁平化后的1000个上传文件；
- `.work/LICENSES/`：两个项目的许可证；
- `.work/computed.sha256`：本次下载内容校验值。

300题已完成固定原文校验：前200题是开发回归集，后100题是锁定对比集。它们可证明工程检索效果，但不冒充芯片专家金标准；领域人员后续复核后，才可将对应`review_status`改为`APPROVED`。

`questions.tsv`的`allowed_search_terms`以分号分隔同一轮的搜索词，以` | `分隔不同搜索轮次；每题最多三轮、每轮1至5个搜索词。
用户的原始问题保存在`user_question`；Agent每轮实际提交的完整问题以JSON字符串数组保存在`search_round_questions`，数组顺序必须与搜索轮次一致。
多文档题按每份预期文档一轮搜索固定执行，累计指标只在所有轮次均命中对应文档时通过。
报告同时记录“首轮是否一次召回全部预期文档”、“首轮是否召回当前子问题的预期文档”和“所有轮次是否累计召回全部预期文档”，三者不混用。

Vortex按`docs` 49份、`hw` 300份、`sw` 80份、`tests` 200份、`sim` 70份及根`README` 1份组成；OpenTitan按`doc` 35份、`hw` 180份、`sw` 70份和`util` 15份组成。清单排除`third_party`、Git submodule、二进制和未纳入平台文本策略的文件。

正式运行前还需：

1. 提供并核对`chinese-files.tsv`中的20份脱敏中文材料；
2. 运行`python3 dataset.py verify`。只有验证通过的数据集才能用于完整工程回归结论。

模板结构可先用`python3 dataset.py verify --structure-only`检查；它不代表数据集已通过人工验收。

仅核对固定公开语料、校验值和300题原文：

```bash
python3 dataset.py verify --public-only
```

该命令通过不代表企业中文领域验收通过。

## 对Knowledge Map执行评测

`dataset.py evaluate`通过Knowledge Map MCP上传数据并查询，不负责启动产品服务。调用方需要明确提供目标MCP地址和测试身份：

```bash
MCP_URL=http://目标服务/mcp \
AIHUB_SECRET=测试环境密钥 \
AIHUB_USER_ID=固定测试用户 \
EVALUATION_SPLIT=smoke \
python3 dataset.py evaluate
```

`EVALUATION_SPLIT`支持`smoke`、`development`、`locked`、`locked-v2`和`all`。开发期间只使用`smoke`和`development`；检索实现冻结后才能运行锁定集，且不得根据锁定集结果逐题调参。结果写入`.work/results/latest.json`。

公开语料使用Apache-2.0项目的固定Revision。不得添加`third_party`、Git submodule或生成物。公开语料不冒充企业内部知识。
