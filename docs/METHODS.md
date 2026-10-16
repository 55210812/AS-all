# 方法实现

统一入口src/as_all/methods.py只注册十一种方法，不读取历史结果。

| 方法 | 实现 |
|---|---|
| No Defense | 原OpenAILLM、ToolsExecutor和18轮循环 |
| Tool Filtering | reference/tool_filter_openai.py中的兼容适配筛选；严格工具名集合，不把筛选对话留给后续Agent |
| Prompt Repetition | 每轮工具输出后插入原InitQuery |
| Input Delimiting | system边界说明＋工具输出`<<...>>` |
| Injection Detection | 原content-only detector，SAFE阈值0.5、message模式；固定权重revision，不检测error通道 |
| IPIGuard | 官方对齐DAG构造、模拟／真实执行、扩展和reflection |
| Task Shield | 原提取、对齐、工具检查、拒绝和恢复流程，独立关闭Thinking的Judge客户端 |
| Holistic | 原始任务＋完整历史＋contribute_to_score Witness，无Frame、无Guard |
| AS-only | A版原生领域工具＋动作授权Witness，无Guard |
| AS-only＋Guard | 相同Agent，原via-claim Guard及root引用Frame／此前有效输出切片 |
| AS-only＋Guard＋Frame提醒 | 仅有效Block后附完整冻结Frame，保留原拒绝 |

Task Shield、IPIGuard和Holistic保留冻结方法内部协议处理；统一HTTP层只重试明确连接未送达或429，最多两次，不重发部分请求。方法内格式请求同样进入实际成本账本。SDK和Tenacity隐藏传输重试关闭。

A版来源session01a1433f-c9ea-7bc2-b774-1525f9d3a27a。原61份人工Frame与四域97份来源的交集逐字一致，新增36份沿用冻结源；不调用Frame生成。97任务原文和949攻击字节独立冻结，十一方法同用。攻击文字目标模型为AI model developed by Google，不混入Qwen版本。

A版72条配对的协议及历史／签名审计通过，但效果门槛未通过。只复用实现，不导入72条轨迹、历史610条基准、取优规则或额外复跑。22例验收也不作为全量效果证明。

benchmark原Utility／ASR保留；评分器不是人工语义复核，已知弱判定不能因此自动修分。失败轨迹回传用于后续核对。所有工具为模拟环境工具，网络访问只用于模型API、依赖和模型权重下载。
