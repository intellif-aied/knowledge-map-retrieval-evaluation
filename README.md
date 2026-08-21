# Knowledge Map 检索评测集

该仓库独立保存 Knowledge Map 渐进检索使用的固定题目、公开语料清单、数据准备脚本和校验规则，不包含 Knowledge Map 或 knowledge-server 的产品代码。

## 数据集

| 目录 | 用途 | 规模 |
| --- | --- | --- |
| `datasets/chip-retrieval-v1` | 芯片研发场景工程回归 | 1000个固定文件、300题、40题冒烟集 |
| `datasets/repoqa-2024-06-23` | 未参与调参的外部代码检索对照 | 60个GitHub仓库、600题、8775个源文件 |

两套结果分别报告，不能合并成一个“准确率”。前者接近当前产品场景，后者检查对陌生仓库的泛化能力。

## 克隆后开始

机器只需Git、Python 3和网络访问。克隆后执行一条命令：

```bash
./prepare.sh
```

脚本下载两套固定公开语料并完成题目、目标Path、目标范围和SHA-256校验。下载内容统一保存在各数据集的`.work/`，不会提交Git。执行成功后即可把数据交给被测检索系统。

RepoQA的[`repositories.tsv`](datasets/repoqa-2024-06-23/repositories.tsv)和[`questions.tsv`](datasets/repoqa-2024-06-23/questions.tsv)直接纳入Git，可以在网页中浏览、审查和比较版本。

## 数据边界

- Vortex 和 OpenTitan 公共语料按其 Apache-2.0 许可证使用；仓库只提交文件清单、题目和校验值，不重复分发源码。
- RepoQA 项目为 Apache-2.0；发布包中的上游源码仍受各仓库许可证约束，因此只在本地下载。
- `chinese-files.tsv` 仅保留20个企业材料审核槽位，当前没有真实企业正文，不得把公开数据结果称为企业中文材料准确率。
- 评测结果只能说明检索层表现，不代表 Codex 或 Claude 最终回答质量。
