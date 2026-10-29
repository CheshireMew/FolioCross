# 全面审查修复记录（2026-09-21）

本轮已修复当前任务中列出的 FC-A01 至 FC-A10，20 条完成条件均验证通过。审查基线为
`f1ea0923ba633ba50a26f4b51110577bf01ba910`。修复包含源码、旧数据兼容、消费者界面、回归测试和操作文档。
验收范围为当前 Windows 上的源码运行；模型请求使用本地替身和真实 SDK 异常类型验证，未调用收费接口。

## 原问题与最终行为

| ID | 原问题 | 修复后的行为 |
| --- | --- | --- |
| FC-A01 | SQLite 建表/加列已经提交，迁移版本尚未登记；失败后无法再次打开 | 所有升级语句和版本登记在同一事务内提交；串行化多进程启动；对旧 1–5 版已部分执行且结构一致的升级进行恢复 |
| FC-A02 | HTML/EPUB 中 div、section 与 p 混用时漏正文 | 统一提取可见正文及容器直接文本，嵌套块只提取一次；脚本、注释和隐藏节点保留在模板中；已有图书补入漏段并保留原段落身份、人工修订及锁定 |
| FC-A03 | 同一个 EPUB 资源中的多个目录项都被最后一个标题覆盖 | 以资源路径和锚点共同匹配 NAV/NCX；保留多层目录关系，文档标题使用首个标题 |
| FC-A04 | 固定导出文件被直接覆盖，失败破坏旧文件，历史校验值失真 | 每次生成独立版本，完成渲染后原子发布；指定输出路径是交付副本；持久发布记录支持文件替换后数据库提交前中断的恢复 |
| FC-A05 | 暂停后，已经排队但尚未发送的请求仍会发出 | 并发等待、速率等待及实际发送前检查控制状态；请求用量入账后才释放并发位置，使下一个请求看到最新预算 |
| FC-A06 | 实际 SDK 超时和连接异常未进入重试 | 识别 SDK 连接/超时异常；鉴权失败不重试；每次实际发送登记请求，只有收到用量时入账 |
| FC-A07 | 后台重译、审校、导出或外部 CLI 操作未改变粗粒度状态时界面不刷新 | 数据修订计数驱动详情刷新；编辑草稿单独保存，旧版本保存被拒绝时保留草稿；输出、质量和用量面板随数据变化更新 |
| FC-A08 | 工作区恢复到其他目录后仍使用旧绝对路径 | 工作区自有文件保存为相对路径；打开旧库时转换自有路径；用户明确引用的外部文件保留原绝对路径 |
| FC-A09 | 术语批量替换、审校估算、预览解析占用 GUI 线程 | 术语操作进入持久后台队列；估算、影响列表和预览在查询子进程完成，通过信号返回结果或错误 |
| FC-A10 | Wenyi 迁移失败后留下半成品，再次导入被“已存在”阻止 | 数据库写入作为一个事务提交；失败可重试；仅重建没有用户后续改动的旧版迁移半成品，人工译文和新增术语均受保护 |

## 完成条件与回归依据

以下条件保留原问题的范围。表中测试名对应正式 pytest 收集结果，参数化实例均实际执行。
结构化记录中的证据身份还绑定当前源码与测试文件的内容摘要，避免把旧的通过结果用于后续变更。

| 条件 | 要证明的结果 | 主要测试（tests/ 下） |
| --- | --- | --- |
| A01.1 | DDL 与版本登记原子提交，中断回滚 | `test_audit_recovery.py::test_schema_upgrade_rolls_back_version_and_ddl`；`test_concurrent_workspace_startup_is_serialized` |
| A01.2 | 已存在的半次升级可恢复并重复打开 | `test_audit_recovery.py::test_recovers_legacy_partial_schema[1…5]` |
| A02.1 | 混合及嵌套可见正文不遗漏、不重复 | `test_audit_formats.py::test_mixed_html_prose_round_trip`；原有嵌套列表/HTML 回归 |
| A02.2 | 导入、翻译、实际导出完整且保留结构 | `test_audit_formats.py::test_mixed_epub_completes_through_worker_and_both_exports`；`test_existing_book_adds_omitted_prose_without_changing_manual_revision`；原有 EPUB 资源/标记回归 |
| A03.1 | 同资源不同锚点分别匹配对应标题 | `test_audit_formats.py::test_epub_distinct_fragment_labels_and_document_title` |
| A03.2 | NAV、NCX、多层目录的实际导出正确 | 同上测试检查 ZIP 中 NAV、嵌套 NCX、正文锚点和文档标题 |
| A04.1 | 写入中途失败不破坏上次成功输出 | `test_audit_exports.py::test_failed_explicit_export_preserves_previous_output` 的五格式实例；`test_publication_recovers_after_file_replace_before_database_commit` |
| A04.2 | 历史文件、摘要和消费端语义一致 | `test_audit_exports.py::test_reexport_keeps_artifact_content` 的五格式实例；旧库恢复、CLI 后台导出和 QML 预览测试 |
| A05.1 | 发出请求前再次检查暂停、取消和预算 | `test_audit_requests.py::test_queued_request_does_not_dispatch_after_control`；`test_queued_request_checks_cost_committed_by_previous_request` |
| A05.2 | 已发送请求可完成，排队请求不再发送 | 上述双线程测试检查实际调用次数为 1，并检查首个请求完成、后续请求退出 |
| A06.1 | 实际 SDK 传输异常重试，鉴权异常不重试 | `test_audit_requests.py::test_sdk_transport_errors_retry_and_account` 的两异常实例；`test_authentication_failure_is_not_retried` |
| A06.2 | 重试时请求状态与用量记录准确 | 同上测试检查失败/成功尝试和仅一条有效用量；原有损坏响应重试测试验证两次返回用量均保留 |
| A07.1 | 后台重译可见，刷新保护草稿与版本冲突 | `test_audit_desktop.py::test_background_retranslate_refreshes_without_status_change`；`test_refresh_preserves_draft_and_rejects_stale_save`；真实 QML 编辑测试 |
| A07.2 | 导出、审校及外部 CLI 修改刷新相应面板 | `test_audit_desktop.py::test_export_review_and_external_cli_refresh_their_panels`；`test_qml_consumes_async_preview_estimate_and_keeps_draft` |
| A08.1 | 自有文件在移动后的工作区正常定位 | `test_audit_recovery.py::test_workspace_copy_resolves_own_files_in_new_root` |
| A08.2 | 原路径不可用时旧库可打开、导出和访问成品 | `test_audit_recovery.py::test_v5_restore_rebases_files_and_reconciles_overwritten_history` |
| A09.1 | 批量操作和文档解析离开 GUI 线程 | `test_audit_desktop.py::test_glossary_application_runs_through_durable_worker`；`test_review_estimate_child_returns_actual_result`；预览子进程测试 |
| A09.2 | 大输入时 Qt 事件循环仍响应，结果与错误可返回 | `test_audit_desktop.py::test_preview_child_keeps_qt_event_loop_active`（10 万段 HTML、10 ms 定时器）；查询失败反馈和实际鼠标点击 QML 控件测试 |
| A10.1 | 失败后能重试，旧半成品不自我阻塞 | `test_audit_recovery.py::test_failed_wenyi_import_retries_without_partial_database`；`test_old_partial_wenyi_retry_preserves_user_changes[False]` |
| A10.2 | 重试不重复或丢失修订、术语、用量，源状态不变 | `test_audit_recovery.py::test_wenyi_late_failure_rolls_back_glossary_usage_and_versions`；人工修订及术语保护实例；原有 copy-only 迁移测试 |

## 使用与恢复语义

首次打开旧工作区会进行事务式升级。旧 HTML/EPUB 在重新导入、运行或导出时检查正文覆盖；补入的正文需要翻译，
已有译文不被替换。无法精确对应旧段落的图书会停止升级并报告源书不一致，保留现有数据供检查。

导出接口返回 `path`、`artifact_id` 和 `artifact_path`。指定导出位置时，`path` 是交付副本，
`artifact_path` 是工作区保留的不可变版本。历史上已被旧版覆盖且没有备份的文件字节无法凭摘要恢复；
这类旧记录保留在数据库并标为不可用，不再伪装成可下载的历史成品。仍匹配摘要的旧成品会另存版本。

旧 Wenyi 半成品只有确认尚无人工修订、人工术语变化或后续运行时才能重建。
如果存在这些变化，迁移会明确拒绝重置，以免覆盖用户工作。
测试只使用临时构造的旧状态，未修改 `E:\Code\wenyi`。

详细操作说明见 [恢复](recovery.md)、[格式](formats.md)、[迁移](migration-wenyi.md) 和 [CLI](cli.md)。

## 验证记录

最终检查结果与结构化结项账本保存在本地 `workspace/fix-audit-*` 文件中，workspace 不进入 Git。
原始审查账本从当前任务的原答复重新取得，逐字快照为 `workspace/fix-audit-original.md`；结构化记录
保留原始标题和每条完成条件，没有用当前实现改写完成标准。

| 最终检查 | 实际结果 | 证据 |
| --- | --- | --- |
| pytest 正式收集与完整运行 | 147 个唯一节点全部通过，0 跳过，53.30 秒 | `fix-audit-collected-final.txt`、`fix-audit-complete.xml` |
| Ruff check | 通过 | `python -B -m ruff check . --no-cache` |
| Ruff format check | 78 个文件符合格式 | `python -B -m ruff format --check . --no-cache` |
| Git diff check | 通过 | `git diff --check`；仅有 Git 换行转换提示 |
| 原生 Windows 窗口交互 | 10 万段 HTML 解析期间，Escape 关闭预览、鼠标进入设置用时 0.407 秒，此时查询仍在运行；之后结果正常返回 | `fix-audit-interactive2/result.json` 及该目录的预览、审校估算、编辑页截图 |
| 逐项结项校验 | 10 项、20 条条件全部 resolved，无阻塞，验证器退出 0 | `fix-audit-closure.json`、`fix-audit-closure-result.json` |

以上本地证据路径均相对于 `workspace/`。结项验证器只校验账本一致性；完成判断还依据测试断言、实际消费者
和截图检查。最终源码、测试、项目配置和依赖锁文件的组合 SHA-256 为
`fa5209514a8b154869e55cb93908d432b9776f25274edd6662ce4f57beae2e6c`。
运行使用现有 `D:\Tools\venvs\FolioCross\Scripts\python.exe`，Python 3.10.11、pytest 9.1.1、PySide6 6.11.2。
测试隔离根为 `workspace/fix-audit-complete`；未复用旧目录或旧数据库，关闭 pytest 缓存写入。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
& D:\Tools\venvs\FolioCross\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp E:\Code\FolioCross\workspace\fix-audit-complete --junitxml=workspace/fix-audit-complete.xml
& D:\Tools\venvs\FolioCross\Scripts\python.exe -B -m ruff check . --no-cache
& D:\Tools\venvs\FolioCross\Scripts\python.exe -B -m ruff format --check . --no-cache
git diff --check
```

这段记录是本次已执行命令；以后重跑应换用新的 `--basetemp`，避免 pytest 清空既有证据目录。

验证过程中出现过以下非通过事件，不能把最后通过解释为整个过程从未失败：

- 原始缺陷的失败复现推动了这十项修复。
- Windows 不接受本次只读文件描述符上的 `fsync`，改为可写文件句柄后导出故障注入通过。
- 中间全套回归曾有两条旧断言失败：数据库版本仍写死为 1–5、指定交付文件被误认为历史版本路径；已按最终接口更新并复测。
- 旧迁移半成品中新增的人工术语保护测试先失败，再修复检测逻辑，随后通过。
- Qt offscreen 测试出现过事件处理阶段异常退出；诊断运行完整通过，随后为新增测试补上显式对象生命周期清理并复测。
- QML 实际鼠标测试一度点击到尚未结束关闭动画的遮罩层，改为等待弹窗关闭后再次操作；另有测试构造及截图脚本错误，均不作为产品通过证据。
- 原生窗口探针最初把参考文件当成可预览译本，选择了隐藏按钮；修正构造样本的类型和可见控件选择后，同一预览消费路径通过。

自动 UI 回归使用本机 Qt offscreen 平台，涵盖控件加载、实际鼠标事件、草稿、异步进程返回和事件循环响应。
另以原生 Windows 平台核对了上述大文件交互与三处画面。大型 HTML 是为检查预览而构造的文件；
导出生产链由五格式导出、故障注入及 EPUB 完整链测试单独证明。
这些结果不代表所有 DPI、无障碍或真实模型翻译质量均已验收。没有打包、发布或推送。
