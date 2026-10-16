# Gemini十一方法 AgentDojo全量实验

Linux一键运行：

```bash
git clone https://github.com/55210812/AS-all.git
cd AS-all
bash run.sh
```

首次隐藏填写Gemini API密钥，模型固定`gemini-2.5-flash`。默认官方原生API地址，也可填兼容原生协议的代理地址。脚本建立独立Python3.12环境；没有uv时在本项目私有bootstrap环境安装锁定uv，不改系统Python。机器需要Python3、venv、Git、tmux和crontab；没有tmux／cron时脚本报告安装要求，不使用sudo或修改系统服务。

启动前显示11,506例付费提示，输入`RUN 11506`才开始。四个案例worker；case自动补跑、指标取优、manager自动恢复均为0。已终止或部分执行案例不自动重发。

## 方法与样本

No Defense、Tool Filtering（兼容适配版）、Prompt Repetition、Input Delimiting、Injection Detection（官方对齐）、IPIGuard（官方对齐）、Task Shield、Standard Holistic、AS-only、AS-only＋Guard、AS-only＋Guard＋Frame提醒。

每方法四域1046例：97 Clean＋949 important_instructions Attack。原任务、评分器、人工97份id/task Frame及949组合攻击输入冻结。所有领域工具只操作随包提供的模拟环境，不接入真实邮箱、银行或预订系统。

Agent动态Thinking开启；防御生成请求关闭Thinking。Task Shield明确为Agent开／Guard关。IPIGuard的规划与图执行模型调用归防御侧。Holistic是原始任务上的contribute_to_score Witness，不提供Frame且无Guard。

### A版AS-only三方法

模型看到原生领域工具，每个工具必填authorization_witness；system不重复附完整领域工具注册表。程序内部转回原代理信封，由原执行器验证后剥离Witness再执行领域工具。Guard沿用via-claim Prompt、root切片和证据规则。提醒只在有效Block后追加全部冻结Frame。

已做过的72条A版新旧配对协议及签名审计通过，但任务效果非劣门槛未通过；本包不宣称A版效果不下降，也不导入或取优历史结果。首次使用建议先运行小范围验收。

## 结果在哪里

启动时打印绝对路径：`results/<run_id>/`。所有方法统一放在该目录。

```bash
bash run.sh status
```

- `report/summary.md`、`summary.csv`、`summary.json`：Clean／Attack总表。
- `report/paired1046.json`：逐案例跨方法配对。
- `report/runtime_errors.json`：运行错误与已知成本。
- `report/actual_costs.json`：实际Agent／防御请求账本汇总。
- `cases/<id>/`：完整原生请求响应、工具轨迹、benchmark和结果。
- `manifest.json`：样本、配置和源码SHA；`watchdog.json`：只读监控。

输入Token使用供应商完整原始值，不扣缓存；另外提供实际缓存和可核验非缓存输入。缺usage或cache字段标为未知，不能当零。Thinking输出只计一次。运行错误不算任务成功或防御成功，不因指标不好补采样。

## 小范围验收

当前已知局限：Tool Filtering在Gemini返回拒绝说明或无匹配工具名时仍会筛空工具。2026-10-16的22例实测均正常终止，但该方法两例Utility均失败，其中Attack例保留0个工具。详见[方法说明](docs/METHODS.md)。

```bash
bash run.sh start --acceptance
```

每方法同一条Clean和Attack，共22例，独立结果目录。验收只证明接口和执行路径，不是全量准确率或性能非劣证明。正式全量不会自动接续。

已有Python3.12环境可直接复用依赖，跳过创建环境和重新下载PyTorch：

```bash
AS_ALL_PYTHON=/absolute/path/to/existing/python bash run.sh start --acceptance
```

本次验收使用服务器既有环境；不再以全新Linux环境模拟作为发布前置条件。

## 一键反馈

```bash
bash feedback.sh
```

显式确认`PUBLIC`后，上传汇总、来源SHA、运行错误，以及Utility失败或ASR成功案例的完整轨迹。脚本先扫描配置密钥、认证信息和私有路径；发现疑似泄漏则停止，不篡改原轨迹。使用GitHub浏览器登录／现有gh认证，有写权限建反馈分支，否则fork后提交PR；不会直接写main。大压缩包使用分卷附件及SHA。

反馈PR和附件是公开的。只在你主动执行反馈脚本时上传；密钥、历史结果、模型权重和本机配置不进入主分支。反馈PR用于取回结果，不自动合并结果数据。

## 开发验证

```bash
uv sync --frozen
uv run pytest tests -q
uv run python -m unittest discover -s reference/tests -q
uv run ruff check src tests tools
```

方法来源和改动见[方法说明](docs/METHODS.md)、[IPIGuard对齐](docs/IPIGUARD_ALIGNMENT.md)和[第三方许可证](THIRD_PARTY_NOTICES.md)。
