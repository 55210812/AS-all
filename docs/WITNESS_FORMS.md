# Qwen重要信息攻击：Witness形式对比

入口：`bash run.sh start --experiment qwen-important`。模型固定为`qwen3.5-flash`，四方法各97 Clean＋949 Attack，共4,184例；四方法共享8个案例worker。

## 共同设置

Agent开启Thinking，Guard及其格式修复关闭Thinking；temperature=0，Guard最大输出2048 Token。使用原OpenAI兼容通道、完整动作前Agent历史和18轮工具循环，最多一次最终回答尝试。四组均无Frame提醒。

Agent和Guard使用`data/manual_frames97.json`中的同一份当前任务简化Frame，每项只有`id`和`task`。不重新生成Frame。攻击由原`ImportantInstructionsAttack`按Qwen模型称谓冻结到`data/qwen_important949.json`，四方法完全一致，不混入tool_knowledge或Gemini攻击。

## 输入与输出

| 方法ID | Guard输入 | Guard裁决 |
|---|---|---|
| `no_witness_guard` | 当前任务完整`trusted_task_frames`、`proposed_tool_call`、`conversation_history`、`related_content` | `root`、`via`、`decision`、`reason` |
| `reasoning_context_guard` | 当前任务完整`trusted_task_frames`、`proposed_tool_call`、`reasoning_context` | `decision`、`reason` |
| `as_pg` | 无Guard请求 | 无 |
| `as_pg_guard` | 引用的`trusted_task_frames`、`proposed_tool_call`、`authorization_witness`、明确引用的`prior_tool_outputs` | `action_support_valid`、`parameter_grounding_valid`、`decision`、`reason` |

各Guard保留其原版Prompt和输出协议，不统一改写。共同授权原则是可信Frame提供任务授权，其他内容不能产生或扩展权限；但Prompt措辞、信息范围、裁决字段及参数核验范围存在差异。AS＋PG额外核验参数授权，不能把四组当作仅改变表示、验证对象完全相同的对照。

### 无Witness＋Guard

复用`qwen_no_witness_historyfix122`的历史边界修正版。Agent直接调用领域工具，不提交root／via；Guard自行构造动作依据。allow必须返回已有Frame ID作为root、非空via和reason；block必须返回root=null、via=null和非空reason。

历史包含本轮提议之前的全部可见消息、历史调用、工具输出及错误，不截断。当前提出调用的整条Assistant回复不放入`conversation_history`；当前调用只出现在`proposed_tool_call`，当前Assistant正文单列为`related_content`，不代表调用已经执行。历史不包含隐藏推理。同轮多个提议在任何工具执行前统一快照，A的执行结果不进入同轮B的Guard输入。

### Reasoning Context＋Guard

复用`qwen_reasoning122`的当前轮推理版。Agent直接调用领域工具，Guard使用提出该调用的当前Assistant响应里的原始`reasoning_content`，保留其文字和空白，不拼接历史推理、不额外调用模型生成解释，也不以Assistant正文代替。模型未返回该字段时传空字符串并记录缺失；空推理本身不是自动Block条件。裁决只返回decision和非空reason，不生成root／via。

这一组不提供完整执行历史或工具输出切片。它与全历史Guard的信息范围不同，不把结果差异仅归因于文字格式。

### AS＋PG两组

Agent使用原代理`submit_tool_call_with_authorization_witness`，保持system领域工具注册表。Witness包含：

```json
{
  "action_support": {"root": "t1", "via": "动作授权依据"},
  "parameter_grounding": {"roots": ["t1"], "via": "所有参数共同满足授权要求的依据"}
}
```

`action_support`可按原规则提供`authorization_evidence`，但只能引用此前成功输出。参数依据是联合判断，不拆成逐参数解释。非空参数缺失PG时进入原结构修复／协议错误流程，不能当作Guard成功阻断；真正零参数调用归一化PG为null，由程序确定参数有效性，Guard仅判断动作。

无Guard组执行经过Witness结构检查的调用；有Guard组仅在动作与参数授权均有效时执行。Guard只接收AS根与PG根引用的Frame并集和明确引用的此前成功输出，不补证、不换root，不带完整历史。

## 来源与结果

运行接线位于`src/as_all/witness_forms.py`。无Witness和Reasoning的原方法函数／类逐字提取到`reference/witness_forms/history_guard.py`与`reasoning_guard.py`，只替换可移植导入并绑定停止检查回调；原Prompt保存在同目录的`history_prompt.txt`和`reasoning_prompt.txt`。`component_sources.json`记录来源文件及逐符号SHA，连同全包`source_manifest.json`核验。

AS＋PG复用vendor中的`semantic_frame_alignment_agent_witness_no_guard.py`、`semantic_frame_alignment_joint_witness_guard.py`和`joint_witness_runtime_guard.py`，保留原Guard Prompt、联合Witness与空参数分支。接线将原Frame缓存绑定到97份冻结简化Frame，根字段使用其`id`，并隔离方法模块状态，不改变其他方法。

结果位于`results/qwen-important/<run_id>/`，包括Clean／Attack总表、逐例配对、原始请求响应、运行错误、真实usage和来源SHA。缺失reasoning、usage或缓存字段如实记录；Thinking只计一次。程序／协议拒绝不记作有效语义Block，正常失败不补采样、不取优。

本入口只添加Qwen重要信息四组。既有Gemini重要信息、Gemini工具知识和Qwen工具知识入口仍各运行原十一方法。升级源码后请用新运行目录，不将旧冻结运行续接到新版本。
