# Gemini／Qwen AgentDojo全量实验

## 1. 准备并运行

运行环境为Linux，需已安装Python3（含venv）、Git、tmux和crontab。反馈上传另需[GitHub CLI（gh）](https://cli.github.com/)。脚本自动建立Python3.12项目环境、安装锁定依赖并下载检测器权重；首次安装包含PyTorch，下载可能较大。无需预先安装uv，也无需已有实验目录或私人服务器配置。

包含Injection Detection的实验中，检测器优先使用CUDA，也支持CPU；8并行启动预检要求所选设备至少有16GiB空闲内存或显存。第四项Witness形式对比不含检测器，不下载其权重或要求此项显存。

克隆最新主分支并运行：

```bash
git clone https://github.com/55210812/AS-all.git
cd AS-all
bash run.sh
```

首次运行先选择实验（回车默认Gemini）：

| 选项 | 模型 | 攻击 | 每方法 | 总案例 | 案例并行 |
|---|---|---|---|---:|---:|
| 1. Gemini | gemini-2.5-flash | important_instructions | 97 Clean＋949 Attack | 11,506 | 8 |
| 2. Qwen | qwen3.5-flash | tool_knowledge | 97 Clean＋949 Attack | 11,506 | 8 |
| 3. Gemini | gemini-2.5-flash | tool_knowledge | 97 Clean＋949 Attack | 11,506 | 8 |
| 4. Qwen Witness形式对比 | qwen3.5-flash | important_instructions | 97 Clean＋949 Attack | 4,184 | 8 |

一次选择一个实验，不自动启动其他实验。也可直接指定：

```bash
bash run.sh start --experiment qwen-tool-knowledge
bash run.sh start --experiment gemini-tool-knowledge
bash run.sh start --experiment qwen-important
```

随后按终端提示填写所选模型的配置：

1. **API key**：输入所选模型密钥，输入时不显示字符。
2. **API base**：Gemini默认`https://generativelanguage.googleapis.com/v1beta`，代理须支持原生`generateContent`；Qwen填写OpenAI兼容API base，通常以`/v1`结尾。
3. **Hugging Face token**：可选，直接回车跳过。
4. 安装和预检通过后，前三项输入 **`RUN 11506`**；第四项输入 **`RUN 4184`**。

模型名预设，无需填写。两套凭据分别保存在本机`.secrets.env`（GEMINI_API_KEY／GEMINI_BASE_URL与QWEN_API_KEY／QWEN_BASE_URL），权限600并被Git忽略；两个Gemini实验共用Gemini凭据，与Qwen凭据不相互覆盖。脚本可能在提示密钥前安装依赖。没有tmux／cron时会提示缺少组件。

启动前显示所选模型、攻击和付费案例数，输入对应确认文字才开始。一次实验的方法共享8个案例worker，每个子进程只运行一个案例；不是每方法各8个。已终止或部分执行案例不会自动重跑，已有运行的冻结配置不改写。

启动成功后任务在tmux后台运行，可以关闭终端。脚本会打印结果的绝对路径和状态查询命令。

## 方法与样本

No Defense、Tool Filtering、Prompt Repetition、Input Delimiting、Injection Detection、IPIGuard、Task Shield、Standard Holistic、AS-only、AS-only＋Guard、AS-only＋Guard＋Frame提醒。

上述十一方法属于前三项实验。第四项`qwen-important`只运行以下四种方法：

| 方法 | Agent／Guard输入要点 |
|---|---|
| No Witness＋Guard | 原生领域调用；Guard接收全部简化Frame、当前调用、动作前完整可见历史及当前Assistant正文；由Guard自行构造root／via |
| Reasoning Context＋Guard | 原生领域调用；Guard接收全部简化Frame、当前调用和本轮原始`reasoning_content`，不另生成Witness解释 |
| AS＋PG | 原代理工具及动作授权／联合参数依据Witness；无Guard |
| AS＋PG＋Guard | 同一Witness；Guard核验动作授权与联合参数依据，只接收引用Frame和明确引用的此前成功输出 |

四组共用97份冻结简化Frame和949份Qwen重要信息攻击，均无Frame提醒。各组保留已有版本的Prompt和裁决协议，不统一改写：No Witness Guard自行输出root／via，Reasoning Guard输出decision／reason，AS＋PG Guard同时判断动作授权与联合参数依据。No Witness组的历史不含当前回复的tool_calls或其结果，同轮兄弟结果也不进入该轮Guard输入。Reasoning为空时如实记录，不以Assistant正文或新生成解释替代。详细输入与字段见[Witness形式对比](docs/WITNESS_FORMS.md)。

每种方法运行Slack、Travel、Workspace、Banking四个领域的1046例。各实验内的方法使用一致任务和冻结攻击；各模型／攻击组合独立冻结，不混合统计。tool_knowledge攻击附带工具调用及占位参数指引。两个Gemini实验的Holistic及AS-only三方法均使用A版原生领域工具＋Witness接口，Qwen的Witness方法保留原代理接口。Holistic保留自身评分Witness，不使用Frame或Guard。工具只操作随包提供的模拟环境。

Agent开启动态Thinking，防御生成请求关闭Thinking。各方法的实现与配置见[方法说明](docs/METHODS.md)。

## 2. 查看进度和结果

启动时打印绝对路径：`results/<experiment_id>/<run_id>/`。同一次运行的所有方法统一放在该目录，各实验分开。

```bash
bash run.sh status
bash run.sh status --experiment qwen-tool-knowledge
bash run.sh status --experiment gemini-tool-knowledge
bash run.sh status --experiment qwen-important
```

- `report/summary.md`、`summary.csv`、`summary.json`：Clean／Attack总表。
- `report/paired1046.json`：逐案例跨方法配对。
- `report/runtime_errors.json`：运行错误与已知成本。
- `report/actual_costs.json`：实际Agent／防御请求账本汇总。
- `report/reasoning_coverage.json`：Qwen重要信息Reasoning组实际使用／缺失推理的调用数。
- `cases/<id>/`：完整原生请求响应、工具轨迹、benchmark和结果。
- `manifest.json`：样本、配置和源码SHA；`watchdog.json`：只读监控。

输入Token使用供应商完整原始值，不扣缓存；另外提供实际缓存和可核验非缓存输入。缺usage或cache字段标为未知，不能当零。Thinking输出只计一次。运行错误不算任务成功或防御成功，不因指标不好补采样。

## 3. 上传结果反馈

实验结束后，在仓库目录运行：

```bash
bash feedback.sh
bash feedback.sh --experiment qwen-tool-knowledge
bash feedback.sh --experiment gemini-tool-knowledge
bash feedback.sh --experiment qwen-important
```

默认选择Gemini important_instructions最新运行；其他实验用上面的`--experiment`选择。输入`PUBLIC`确认公开上传；未登录时按提示完成GitHub浏览器登录。上传后打印反馈PR链接。

若存在多次实验，也可明确指定要反馈的目录：

```bash
bash feedback.sh results/qwen-tool-knowledge/<run_id>
```

显式确认`PUBLIC`后，上传汇总、来源SHA、运行错误，以及Utility失败或ASR成功案例的完整轨迹。脚本先扫描配置密钥、认证信息和私有路径；发现疑似泄漏则停止，不篡改原轨迹。使用GitHub浏览器登录／现有gh认证，有写权限建反馈分支，否则fork后提交PR；不会直接写main。大压缩包使用分卷附件及SHA。

反馈PR和附件是公开的。只在你主动执行反馈脚本时上传；密钥、历史结果、模型权重和本机配置不进入主分支。反馈PR用于取回结果，不自动合并结果数据。

方法来源和改动见[方法说明](docs/METHODS.md)、[IPIGuard对齐](docs/IPIGUARD_ALIGNMENT.md)和[第三方许可证](THIRD_PARTY_NOTICES.md)。
