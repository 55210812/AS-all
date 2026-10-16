# Gemini十一方法 AgentDojo全量实验

## 1. 准备并运行

运行环境为Linux，需已安装Python3（含venv）、Git、tmux和crontab。反馈上传另需[GitHub CLI（gh）](https://cli.github.com/)。脚本自动建立Python3.12项目环境、安装锁定依赖并下载检测器权重；首次安装包含PyTorch，下载可能较大。无需预先安装uv，也无需已有实验目录或私人服务器配置。

克隆最新主分支并运行：

```bash
git clone https://github.com/55210812/AS-all.git
cd AS-all
bash run.sh
```

首次运行按终端提示填写：

1. **Gemini API key**：输入密钥，输入时不显示字符。
2. **Gemini API base**：官方接口直接回车，默认为`https://generativelanguage.googleapis.com/v1beta`；使用代理时填写支持Gemini原生`generateContent`协议的地址。
3. **Hugging Face token**：可选，直接回车跳过。
4. 安装和预检通过后，输入 **`RUN 11506`**，启动十一方法全量实验。

模型已固定为`gemini-2.5-flash`，无需填写模型名。凭据保存在本机`.secrets.env`，权限为600，已被Git忽略；后续运行复用配置。脚本可能在提示填写密钥前先安装依赖。没有tmux／cron时会提示缺少的系统组件。

启动前显示11,506例付费提示，输入`RUN 11506`才开始。默认同时运行4个案例，已终止或部分执行的案例不会自动重跑。

启动成功后任务在tmux后台运行，可以关闭终端。脚本会打印结果的绝对路径和状态查询命令。

## 方法与样本

No Defense、Tool Filtering、Prompt Repetition、Input Delimiting、Injection Detection、IPIGuard、Task Shield、Standard Holistic、AS-only、AS-only＋Guard、AS-only＋Guard＋Frame提醒。

每种方法运行Slack、Travel、Workspace、Banking四个领域的1046例：97 Clean＋949 important_instructions Attack。所有方法使用一致的基准任务与攻击输入，领域工具操作随包提供的模拟环境。

Agent开启动态Thinking，防御生成请求关闭Thinking。各方法的实现与配置见[方法说明](docs/METHODS.md)。

## 2. 查看进度和结果

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

## 3. 上传结果反馈

实验结束后，在仓库目录运行：

```bash
bash feedback.sh
```

默认选择最新的结果目录。输入`PUBLIC`确认公开上传；若尚未登录GitHub，按终端提示在浏览器完成登录。上传完成后脚本打印反馈PR链接，将结果回传到本仓库。

若存在多次实验，也可明确指定要反馈的目录：

```bash
bash feedback.sh results/<run_id>
```

显式确认`PUBLIC`后，上传汇总、来源SHA、运行错误，以及Utility失败或ASR成功案例的完整轨迹。脚本先扫描配置密钥、认证信息和私有路径；发现疑似泄漏则停止，不篡改原轨迹。使用GitHub浏览器登录／现有gh认证，有写权限建反馈分支，否则fork后提交PR；不会直接写main。大压缩包使用分卷附件及SHA。

反馈PR和附件是公开的。只在你主动执行反馈脚本时上传；密钥、历史结果、模型权重和本机配置不进入主分支。反馈PR用于取回结果，不自动合并结果数据。

方法来源和改动见[方法说明](docs/METHODS.md)、[IPIGuard对齐](docs/IPIGUARD_ALIGNMENT.md)和[第三方许可证](THIRD_PARTY_NOTICES.md)。
