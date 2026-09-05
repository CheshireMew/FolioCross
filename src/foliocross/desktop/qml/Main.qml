import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: window
    width: 1440
    height: 900
    minimumWidth: 1120
    minimumHeight: 720
    visible: true
    title: "FolioCross"
    font.pixelSize: Math.round(14 * backend.uiScale)
    color: darkMode ? "#171513" : "#f5f1ea"
    property bool darkMode: backend.darkMode
    property int pageIndex: 0
    property int detailTab: 0
    property var doctorResult: ({})
    property var historyRows: []
    property var historyComparison: ({})
    property string historySegment: ""
    property string retranslateSegmentId: ""
    property string pendingGlossarySource: ""
    property string pendingGlossaryTarget: ""
    property var reviewEstimate: ({})
    property string newJobId: ""
    property var affectedRows: []
    property string pendingIssueId: ""
    property string pendingIssueSuggestion: ""
    property string pendingExportFormat: ""
    property string previewContent: ""
    property string previewTitle: ""
    property string glossaryQuery: ""

    Material.theme: darkMode ? Material.Dark : Material.Light
    Material.accent: "#c86a3b"
    Material.primary: "#5d3928"

    function tr(zh, en) {
        return backend.uiLanguage === "en" ? en : zh
    }

    function statusText(status) {
        const labels = {
            "queued": tr("排队中", "Queued"), "preparing": tr("译前准备", "Preparing"), "translating": tr("翻译中", "Translating"),
            "quality_check": tr("质量检查", "Quality check"), "ready": tr("可以导出", "Ready"), "exporting": tr("正在导出", "Exporting"),
            "completed": tr("已完成", "Completed"), "paused": tr("已暂停", "Paused"), "interrupted": tr("已中断", "Interrupted"),
            "cancelled": tr("已取消", "Cancelled"), "failed": tr("失败", "Failed"), "pending": tr("待翻译", "Pending"),
            "translated": tr("已翻译", "Translated"), "needs_review": tr("需要检查", "Needs review")
        }
        return labels[status] || status || tr("未知", "Unknown")
    }

    function originText(origin) {
        const labels = {
            "manual": tr("人工编辑", "Manual edit"), "model_translation": tr("模型翻译", "Model translation"),
            "retranslation": tr("单段重译", "Retranslation"), "history_restore": tr("历史恢复", "History restore"),
            "glossary_apply": tr("术语应用", "Glossary update"), "review_accept": tr("采纳审校建议", "Accepted review"),
            "wenyi_translation": tr("Wenyi 译文", "Wenyi translation"), "wenyi_final": tr("Wenyi 定稿", "Wenyi final"),
            "wenyi_structure_restore": tr("迁移格式恢复", "Migration structure restore")
        }
        return labels[origin] || origin || tr("未知来源", "Unknown origin")
    }

    function issueStatusText(status) {
        const labels = {"open":tr("待处理", "Open"), "resolved":tr("已检查", "Reviewed"), "dismissed":tr("已忽略", "Dismissed"), "accepted":tr("已采纳", "Accepted")}
        return labels[status] || status || ""
    }

    function requestStatusText(status) {
        const labels = {"pending":tr("进行中", "Pending"), "succeeded":tr("成功", "Succeeded"), "failed":tr("失败", "Failed"), "aborted":tr("已中止", "Aborted")}
        return labels[status] || status || ""
    }

    function stageText(stage) {
        const labels = {"imported":tr("已导入", "Imported"), "prepare":tr("全书理解", "Book analysis"), "translate":tr("正文翻译", "Translation"), "quality":tr("质量检查", "Quality"), "deep_review":tr("深度审校", "Deep review"), "export":tr("生成成品", "Export"), "completed":tr("完成", "Completed"), "migrated":tr("迁移完成", "Migrated")}
        return labels[stage] || stage || ""
    }

    function eventText(type) {
        const labels = {
            "book.imported":tr("书籍已导入", "Book imported"), "job.started":tr("任务开始运行", "Job started"),
            "stage.changed":tr("处理阶段已切换", "Stage changed"), "progress.updated":tr("翻译进度已更新", "Progress updated"),
            "usage.recorded":tr("记录了一次模型用量", "Model usage recorded"), "warning.raised":tr("运行中出现提醒", "Warning raised"),
            "job.paused":tr("任务已安全暂停", "Job safely paused"), "job.completed":tr("任务已经完成", "Job completed"),
            "job.failed":tr("任务运行失败", "Job failed"), "job.interrupted":tr("检测到上次运行中断", "Previous interruption detected"),
            "segment.retranslated":tr("一个段落已重译", "Segment retranslated"), "review.completed":tr("深度审校完成", "Deep review completed"),
            "export.completed":tr("成品已重新导出", "Export regenerated"), "job.archived":tr("任务已归档", "Job archived"),
            "glossary.frozen":tr("术语版本已冻结", "Glossary snapshot frozen"), "job.ready":tr("译文可以导出", "Translation ready")
        }
        return labels[type] || type
    }

    function requestExport(formatName) {
        const hasErrors = backend.issues.some(function(issue) {
            return issue.status === "open" && issue.severity === "error"
        })
        if (hasErrors) {
            pendingExportFormat = formatName
            exportWarningDialog.open()
        } else {
            backend.reExport(backend.selectedJob.id, formatName)
        }
    }

    function durationText(seconds) {
        if (seconds === null || seconds === undefined) return "—"
        const value = Math.max(0, Math.round(Number(seconds)))
        if (value < 60) return value + tr(" 秒", " sec")
        if (value < 3600) return Math.ceil(value / 60) + tr(" 分钟", " min")
        return (value / 3600).toFixed(1) + tr(" 小时", " hr")
    }

    Shortcut {
        objectName: "shortcutOpen"
        sequences: [StandardKey.Open]
        onActivated: importDialog.open()
    }
    Shortcut {
        objectName: "shortcutLibrary"
        sequence: "Ctrl+1"
        onActivated: pageIndex = 0
    }
    Shortcut {
        objectName: "shortcutSettings"
        sequence: "Ctrl+,"
        onActivated: { pageIndex = 1; doctorResult = backend.doctor() }
    }
    Shortcut {
        objectName: "shortcutRefresh"
        sequences: ["Ctrl+R", "F5"]
        onActivated: backend.refresh()
    }
    Shortcut {
        objectName: "shortcutNextTab"
        sequence: "Ctrl+Tab"
        enabled: pageIndex === 0 && !!backend.selectedJob.id
        onActivated: tabs.currentIndex = (tabs.currentIndex + 1) % tabs.count
    }
    Shortcut {
        objectName: "shortcutPreviousTab"
        sequence: "Ctrl+Shift+Tab"
        enabled: pageIndex === 0 && !!backend.selectedJob.id
        onActivated: tabs.currentIndex = (tabs.currentIndex + tabs.count - 1) % tabs.count
    }
    Shortcut {
        objectName: "shortcutZoomIn"
        sequence: "Ctrl+="
        onActivated: backend.setUiScale(Math.min(1.5, backend.uiScale + 0.1))
    }
    Shortcut {
        objectName: "shortcutZoomOut"
        sequence: "Ctrl+-"
        onActivated: backend.setUiScale(Math.max(0.8, backend.uiScale - 0.1))
    }
    Shortcut {
        objectName: "shortcutResetZoom"
        sequence: "Ctrl+0"
        onActivated: backend.setUiScale(1.0)
    }
    Shortcut {
        objectName: "shortcutStartPause"
        sequence: "Ctrl+Shift+P"
        enabled: pageIndex === 0 && !!backend.selectedJob.id
        onActivated: {
            if (backend.selectedJob.status === "translating" || backend.selectedJob.status === "preparing")
                backend.pauseJob(backend.selectedJob.id)
            else if (backend.selectedJob.status !== "completed")
                backend.startJob(backend.selectedJob.id)
        }
    }

    FileDialog {
        id: importDialog
        title: tr("选择要翻译的书籍", "Choose a book to translate")
        nameFilters: [tr("支持的书籍", "Supported books") + " (*.epub *.mobi *.azw *.azw3 *.azw4 *.fb2 *.html *.htm *.txt *.md *.markdown *.docx)", tr("所有文件", "All files") + " (*)"]
        onAccepted: backend.importBook(selectedFile)
    }

    FileDialog {
        id: calibreDialog
        title: tr("选择 ebook-convert.exe", "Choose ebook-convert.exe")
        nameFilters: ["Calibre ebook-convert (ebook-convert.exe)"]
        onAccepted: backend.setCalibrePath(selectedFile)
    }

    Connections {
        target: backend
        function onMessage(kind, text) {
            toast.kind = kind
            toast.text = backend.localizeText(text)
            toast.visible = true
            toastTimer.restart()
        }
        function onWorkerEvent(eventType, payloadJson) {
            if (eventType !== "warning.raised" && eventType !== "operation.failed") return
            let payload = ({})
            try {
                payload = JSON.parse(payloadJson)
            } catch (error) {
                payload = ({})
            }
            toast.kind = eventType === "operation.failed" ? "error" : "warning"
            toast.text = payload.message ? backend.localizeText(payload.message) : (eventType === "operation.failed" ? tr("后台操作失败，请查看任务日志。", "The background operation failed. See the job log for details.") : tr("运行中出现需要注意的情况，请查看日志。", "Something needs attention. See the event log for details."))
            toast.visible = true
            toastTimer.restart()
        }
        function onImportFinished(jobId) {
            pageIndex = 0
            newJobId = jobId
            newJobDialog.open()
        }
        function onHistoryReady(rows) {
            historyRows = rows
            historyComparison = rows.length ? rows[0] : ({})
            historyDialog.open()
        }
        function onAffectedSegmentsReady(rows) {
            affectedRows = rows
            affectedDialog.open()
        }
    }

    Timer {
        id: toastTimer
        interval: 5000
        onTriggered: toast.visible = false
    }

    Rectangle {
        id: toast
        property string kind: "info"
        property alias text: toastLabel.text
        visible: false
        z: 100
        radius: 10
        color: kind === "error" ? "#8f302b" : kind === "warning" ? "#9c6422" : kind === "success" ? "#35714d" : "#3f5369"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 22
        width: Math.min(720, toastLabel.implicitWidth + 44)
        height: toastLabel.implicitHeight + 28
        Label {
            id: toastLabel
            anchors.centerIn: parent
            width: parent.width - 36
            color: "white"
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Dialog {
        id: historyDialog
        modal: true
        width: Math.min(window.width - 120, 900)
        height: Math.min(window.height - 120, 680)
        anchors.centerIn: parent
        title: tr("段落修改历史", "Segment history")
        standardButtons: Dialog.Close
        RowLayout {
            anchors.fill: parent
            ListView {
                Layout.preferredWidth: 390
                Layout.fillHeight: true
                model: historyRows
                spacing: 10
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width
                    height: historyColumn.implicitHeight + 24
                    radius: 8
                    color: darkMode ? "#292522" : "#faf8f4"
                    border.color: darkMode ? "#413b36" : "#e4ddd3"
                    ColumnLayout {
                        id: historyColumn
                        anchors.fill: parent
                        anchors.margins: 12
                        Label { text: tr("版本 ", "Version ") + modelData.version + " · " + originText(modelData.origin) + " · " + modelData.created_at; color: "#aa795d" }
                        Label { Layout.fillWidth: true; text: modelData.display_text; wrapMode: Text.Wrap; font.pixelSize: 15 }
                        RowLayout {
                            Layout.fillWidth: true
                            Button { text: tr("对比", "Compare"); flat: true; onClicked: historyComparison = modelData }
                            Item { Layout.fillWidth: true }
                            Label { text: modelData.is_current ? tr("当前版本", "Current") : ""; color: "#4d9b69" }
                            Button {
                                text: tr("恢复这个版本", "Restore version")
                                enabled: !modelData.is_current
                                onClicked: {
                                    backend.restoreRevision(modelData.id)
                                    historyDialog.close()
                                }
                            }
                        }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true; radius: 8
                color: darkMode ? "#211e1b" : "#f5f1ea"
                RowLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 10
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Label { text: tr("历史版本", "Historical version"); font.bold: true }
                        ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                            Label { width: parent.width; text: historyComparison.display_text || ""; wrapMode: Text.Wrap }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Label { text: tr("当前译文", "Current translation"); font.bold: true }
                        ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                            Label { width: parent.width; text: historyComparison.current_display_text || ""; wrapMode: Text.Wrap }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: firstRunDialog
        modal: true
        closePolicy: Popup.NoAutoClose
        width: Math.min(window.width - 100, 700)
        anchors.centerIn: parent
        title: tr("欢迎使用 FolioCross", "Welcome to FolioCross")
        ColumnLayout {
            width: parent.width
            spacing: 14
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: tr("先确认本地转换工具和模型连接。API Key 会保存到 Windows 凭据管理器，不会写入仓库。", "Check the local conversion tools and model connection first. The API key is stored in Windows Credential Manager, never in the repository.") }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: firstCheckColumn.implicitHeight + 28
                radius: 10; color: darkMode ? "#24211e" : "#f8f3eb"
                ColumnLayout {
                    id: firstCheckColumn
                    anchors.fill: parent; anchors.margins: 14
                    Label { text: tr("Python 组件：", "Python components: ") + (doctorResult.ok ? tr("正常", "Ready") : tr("有缺失", "Missing")); color: doctorResult.ok ? "#4d9b69" : "#d46b62" }
                    Label { text: tr("Kindle 转换：", "Kindle conversion: ") + (doctorResult.kindle_conversion && doctorResult.kindle_conversion.available ? tr("可用", "Available") : tr("未配置", "Not configured")) }
                    Label { text: tr("默认模型：deepseek-v4-flash（thinking 关闭）", "Default model: deepseek-v4-flash (thinking off)") }
                    Label { text: tr("官方谷时单价：缓存 0.007 / 输入 0.22 / 输出 0.66 USD（每百万 token）", "Official off-peak prices per million tokens: cached 0.007 / input 0.22 / output 0.66 USD") ; opacity: .65 }
                }
            }
            TextField {
                id: firstApiKey
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: doctorResult.model_api_key && doctorResult.model_api_key.available ? tr("已经从凭据或环境变量找到 API Key，可留空", "An API key is available from credentials or environment; leave blank") : tr("填写 DeepSeek API Key", "Enter DeepSeek API key")
            }
            RowLayout {
                Layout.fillWidth: true
                Button { text: tr("重新检查", "Check again"); flat: true; onClicked: doctorResult = backend.doctor() }
                Button { text: tr("测试模型连接", "Test model connection"); onClicked: backend.testModelConnection() }
                Item { Layout.fillWidth: true }
                Button {
                    text: tr("使用当前配置", "Use current settings")
                    highlighted: true
                    onClicked: {
                        if (backend.completeFirstRun(firstApiKey.text)) firstRunDialog.close()
                    }
                }
            }
        }
    }

    Dialog {
        id: retranslateDialog
        modal: true
        width: 620
        anchors.centerIn: parent
        title: tr("单段重译", "Retranslate segment")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: {
            backend.retranslateSegment(backend.selectedJob.id, retranslateSegmentId, retranslateInstruction.text)
            retranslateInstruction.clear()
        }
        ColumnLayout {
            width: parent.width
            Label { text: tr("可以说明这一段需要怎样调整；留空则按全书规则重新翻译。", "Describe the adjustment, or leave blank to use the book-wide rules."); wrapMode: Text.Wrap; Layout.fillWidth: true }
            TextArea {
                id: retranslateInstruction
                Layout.fillWidth: true
                Layout.preferredHeight: 120
                placeholderText: tr("例如：语气更克制，保留专业术语的英文缩写", "For example: use a restrained tone and keep technical abbreviations")
                wrapMode: TextEdit.Wrap
            }
        }
    }

    Dialog {
        id: glossaryApplyDialog
        modal: true
        width: 620
        anchors.centerIn: parent
        title: tr("把术语改动应用到已有译文", "Apply glossary change to existing translations")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: backend.saveGlossary(
            backend.selectedJob.id,
            pendingGlossarySource,
            pendingGlossaryTarget,
            true
        )
        Label {
            width: parent.width
            wrapMode: Text.Wrap
            text: tr("只会在包含原词的段落中，把旧译名精确替换为新译名。每个变化都会保存为人工锁定版本，可以从历史中恢复。", "Only exact old translations in segments containing the source term are replaced. Each change is saved as a locked manual revision and can be restored from history.")
        }
    }

    Dialog {
        id: reviewDialog
        modal: true
        width: 660
        anchors.centerIn: parent
        title: tr("启动深度审校", "Start deep review")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: backend.startDeepReview(backend.selectedJob.id)
        ColumnLayout {
            width: parent.width
            spacing: 10
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: tr("深度审校是额外模型调用。它只生成问题和修改建议，不会直接覆盖译文。", "Deep review makes additional model calls. It creates issues and suggestions without overwriting translations.") }
            Label { text: tr("模型：", "Model: ") + (reviewEstimate.model || "") }
            Label { text: tr("预计调用：", "Estimated calls: ") + (reviewEstimate.estimated_calls || 0) }
            Label { text: tr("预计 token：", "Estimated tokens: ") + (reviewEstimate.estimated_input_tokens || 0) + tr(" 输入 / ", " input / ") + (reviewEstimate.estimated_output_tokens || 0) + tr(" 输出", " output") }
            Label {
                text: reviewEstimate.estimated_cost_min === null || reviewEstimate.estimated_cost_min === undefined
                    ? tr("费用：当前价格未配置", "Cost: pricing is not configured")
                    : tr("预计费用：", "Estimated cost: ") + Number(reviewEstimate.estimated_cost_min).toFixed(4) + "–" + Number(reviewEstimate.estimated_cost_max).toFixed(4) + " " + reviewEstimate.currency
                font.bold: true
                color: "#c86a3b"
            }
        }
    }

    Dialog {
        id: issueSuggestionDialog
        modal: true
        width: Math.min(window.width - 100, 760)
        anchors.centerIn: parent
        title: tr("编辑并应用审校建议", "Edit and apply review suggestion")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: backend.acceptIssue(pendingIssueId, issueSuggestionEdit.text)
        TextArea {
            id: issueSuggestionEdit
            width: parent.width
            height: 260
            text: pendingIssueSuggestion
            wrapMode: TextEdit.Wrap
        }
    }

    Dialog {
        id: affectedDialog
        modal: true
        width: Math.min(window.width - 100, 820)
        height: Math.min(window.height - 120, 620)
        anchors.centerIn: parent
        title: tr("受这个术语影响的段落", "Segments affected by this term")
        standardButtons: Dialog.Close
        ListView {
            anchors.fill: parent
            model: affectedRows
            clip: true
            spacing: 8
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: affectedColumn.implicitHeight + 20
                radius: 8
                color: darkMode ? "#292522" : "#faf8f4"
                ColumnLayout {
                    id: affectedColumn
                    anchors.fill: parent; anchors.margins: 10
                    Label { text: modelData.chapter_title + " · " + tr("段落 ", "Segment ") + (modelData.segment_index + 1); font.bold: true }
                    Label { Layout.fillWidth: true; text: modelData.source_display_text; wrapMode: Text.Wrap; opacity: .65 }
                    Label { Layout.fillWidth: true; text: modelData.target_display_text || tr("尚未翻译", "Not translated"); wrapMode: Text.Wrap }
                }
            }
        }
    }

    Dialog {
        id: exportWarningDialog
        modal: true
        width: 620
        anchors.centerIn: parent
        title: tr("仍有严重质量问题", "Unresolved critical quality issues")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: backend.reExport(backend.selectedJob.id, pendingExportFormat)
        Label {
            width: parent.width
            wrapMode: Text.Wrap
            text: tr("质量列表中仍有未解决的严重问题。你可以取消并先处理，也可以确认继续导出当前版本。", "Critical issues remain unresolved. Cancel to address them first, or confirm to export the current version anyway.")
        }
    }

    Dialog {
        id: previewDialog
        modal: true
        width: Math.min(window.width - 80, 920)
        height: Math.min(window.height - 80, 760)
        anchors.centerIn: parent
        title: previewTitle
        standardButtons: Dialog.Close
        ScrollView {
            anchors.fill: parent
            TextArea { text: previewContent; readOnly: true; wrapMode: TextEdit.Wrap; selectByMouse: true }
        }
    }

    Dialog {
        id: newJobDialog
        modal: true
        width: Math.min(window.width - 100, 760)
        anchors.centerIn: parent
        title: tr("新建翻译", "New translation")

        function selectValue(control, value) {
            for (let index = 0; index < control.model.length; ++index) {
                if (control.model[index].value === value) {
                    control.currentIndex = index
                    return
                }
            }
        }

        onOpened: {
            let config = backend.selectedJob.config || {}
            selectValue(sourceLanguage, config.source_lang || "auto")
            selectValue(
                outputFormat,
                config.output_format === "markdown" ? "md" : (config.output_format || "epub")
            )
            bilingualOutput.checked = !!config.bilingual
            softBudget.text = config.soft_budget === null || config.soft_budget === undefined ? "" : String(config.soft_budget)
            hardBudget.text = config.hard_budget === null || config.hard_budget === undefined ? "" : String(config.hard_budget)
            translationConcurrency.value = Number(config.translation_max_concurrency || 4)
            rpmLimit.text = config.requests_per_minute === null || config.requests_per_minute === undefined ? "" : String(config.requests_per_minute)
            tpmLimit.text = config.tokens_per_minute === null || config.tokens_per_minute === undefined ? "" : String(config.tokens_per_minute)
        }

        function submit(action) {
            let saved = backend.configureJob(
                newJobId || backend.selectedJob.id,
                sourceLanguage.currentValue,
                outputFormat.currentValue,
                bilingualOutput.checked,
                softBudget.text,
                hardBudget.text,
                translationConcurrency.value,
                rpmLimit.text,
                tpmLimit.text,
                action
            )
            if (saved) close()
        }

        ColumnLayout {
            width: parent.width
            spacing: 14
            Label { text: backend.selectedJob.title || ""; font.bold: true; font.pixelSize: 20 }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: tr("源语言", "Source language"); font.bold: true }
                    ComboBox {
                        id: sourceLanguage
                        Layout.fillWidth: true
                        textRole: "label"; valueRole: "value"
                        model: [
                            {label:tr("自动识别", "Auto-detect"), value:"auto"}, {label:tr("英语", "English"), value:"en"},
                            {label:tr("日语", "Japanese"), value:"ja"}, {label:tr("法语", "French"), value:"fr"},
                            {label:tr("德语", "German"), value:"de"}, {label:tr("西班牙语", "Spanish"), value:"es"}
                        ]
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: tr("目标语言", "Target language"); font.bold: true }
                    TextField { Layout.fillWidth: true; text: tr("简体中文（zh-CN）", "Simplified Chinese (zh-CN)"); readOnly: true }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: tr("输出格式", "Output format"); font.bold: true }
                    ComboBox {
                        id: outputFormat
                        Layout.fillWidth: true
                        textRole: "label"; valueRole: "value"
                        model: [
                            {label:"EPUB", value:"epub"}, {label:"DOCX", value:"docx"},
                            {label:"HTML", value:"html"}, {label:"TXT", value:"txt"},
                            {label:"Markdown", value:"md"}
                        ]
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: estimateColumn.implicitHeight + 28
                radius: 10; color: darkMode ? "#24211e" : "#f8f3eb"
                ColumnLayout {
                    id: estimateColumn
                    anchors.fill: parent; anchors.margins: 14
                    Label { text: tr("稳妥加速", "Steady acceleration"); font.bold: true; color: "#c86a3b" }
                    Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: tr("Flash 直接翻译；译前扫描最多 4 路，正文从 2 路开始、最高 4 路；不执行二次全文润色或自动深度审校。", "Direct Flash translation; up to 4-way pre-scan, translation starts at 2 and scales to 4; no second full-book polish or automatic deep review.") }
                    Label { text: tr("预计字符数：", "Estimated characters: ") + Number(backend.selectedJob.source_characters || 0); opacity: .65 }
                    Label { text: tr("预计 token：", "Estimated tokens: ") + Number(backend.selectedJob.estimated_input_tokens || 0) + tr(" 输入 / ", " input / ") + Number(backend.selectedJob.estimated_output_tokens || 0) + tr(" 输出", " output"); opacity: .65 }
                    Label {
                        text: backend.selectedJob.estimated_cost === null || backend.selectedJob.estimated_cost === undefined
                            ? tr("预计费用：价格未配置", "Estimated cost: pricing is not configured")
                            : tr("预计费用：", "Estimated cost: ") + Number(backend.selectedJob.estimated_cost).toFixed(4) + "–" + Number(backend.selectedJob.estimated_cost_peak).toFixed(4) + " " + (backend.selectedJob.currency || "")
                        opacity: .65
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                CheckBox { id: bilingualOutput; text: tr("生成双语对照", "Bilingual output") }
                Item { Layout.fillWidth: true }
                Label { text: tr("费用提醒", "Budget alert") }
                TextField { id: softBudget; Layout.preferredWidth: 110; placeholderText: tr("可选", "Optional") }
                Label { text: tr("硬预算上限", "Hard budget") }
                TextField { id: hardBudget; Layout.preferredWidth: 110; placeholderText: tr("可选", "Optional") }
                Label { text: backend.selectedJob.currency || "USD"; opacity: .6 }
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: tr("单本最大并发", "Max concurrency per book") }
                SpinBox { id: translationConcurrency; from: 1; to: 4; value: 4 }
                Label { text: "RPM" }
                TextField { id: rpmLimit; Layout.preferredWidth: 110; placeholderText: tr("自动", "Auto"); inputMethodHints: Qt.ImhDigitsOnly }
                Label { text: "TPM" }
                TextField { id: tpmLimit; Layout.preferredWidth: 130; placeholderText: tr("自动", "Auto"); inputMethodHints: Qt.ImhDigitsOnly }
                Item { Layout.fillWidth: true }
            }
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; opacity: .55; text: tr("先做译前准备会生成全书概览和冻结术语表，然后自动暂停，方便确认后再翻译。", "Preparation creates a book overview and frozen glossary, then pauses so you can review them before translation.") }
            RowLayout {
                Layout.fillWidth: true
                Button { text: tr("稍后处理", "Later"); flat: true; onClicked: newJobDialog.close() }
                Item { Layout.fillWidth: true }
                Button { text: tr("只做译前准备", "Prepare only"); onClicked: newJobDialog.submit("prepare") }
                Button { text: tr("直接开始", "Start now"); highlighted: true; onClicked: newJobDialog.submit("start") }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 270
            Layout.fillHeight: true
            color: darkMode ? "#211e1b" : "#eee7dc"
            border.color: darkMode ? "#302b27" : "#dfd4c5"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Rectangle {
                        Layout.preferredWidth: 42; Layout.preferredHeight: 42; radius: 12; color: "#c86a3b"
                        Label { anchors.centerIn: parent; text: "F"; color: "white"; font.bold: true; font.pixelSize: 23 }
                    }
                    ColumnLayout {
                        spacing: 0
                        Label { text: "FolioCross"; font.bold: true; font.pixelSize: 20 }
                        Label { text: tr("整本书翻译工作台", "Whole-book translation studio"); opacity: .58; font.pixelSize: 12 }
                    }
                }

                Button {
                    objectName: "navImportButton"
                    Layout.fillWidth: true
                    text: "+  " + backend.t("import_book")
                    highlighted: true
                    ToolTip.visible: hovered
                    ToolTip.text: tr("导入书籍（Ctrl+O）", "Import book (Ctrl+O)")
                    onClicked: importDialog.open()
                }

                ToolSeparator { Layout.fillWidth: true; orientation: Qt.Horizontal }

                Label { text: backend.t("library"); font.bold: true; opacity: .65 }

                ListView {
                    id: jobList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 6
                    model: backend.jobs
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width
                        height: 76
                        radius: 10
                        color: backend.selectedJob.id === modelData.id ? (darkMode ? "#3b2b24" : "#fff7ef") : "transparent"
                        border.color: backend.selectedJob.id === modelData.id ? "#d28a65" : "transparent"
                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                pageIndex = 0
                                detailTab = backend.detailTab(modelData.id)
                                glossaryQuery = ""
                                backend.selectJob(modelData.id)
                                Qt.callLater(function() {
                                    segmentList.contentY = backend.editorPosition(backend.selectedJob.id, backend.selectedChapterId)
                                })
                            }
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 9
                            Rectangle {
                                Layout.preferredWidth: 38; Layout.preferredHeight: 56; radius: 4
                                color: darkMode ? "#342d28" : "#dfd5c8"
                                Image { anchors.fill: parent; source: modelData.cover_url || ""; fillMode: Image.PreserveAspectCrop; visible: status === Image.Ready }
                                Label { anchors.centerIn: parent; text: "F"; opacity: .4 }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Label { Layout.fillWidth: true; text: modelData.title; elide: Text.ElideRight; font.bold: true }
                                RowLayout {
                                    Label { text: statusText(modelData.status); color: "#c86a3b"; font.pixelSize: 12 }
                                    Label { text: modelData.completed_segments + "/" + modelData.total_segments; opacity: .55; font.pixelSize: 12 }
                                }
                                ProgressBar {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 5
                                    from: 0
                                    to: Math.max(1, modelData.total_segments)
                                    value: modelData.completed_segments
                                }
                            }
                        }
                    }
                }

                ToolSeparator { Layout.fillWidth: true; orientation: Qt.Horizontal }

                Button {
                    objectName: "navSettingsButton"
                    Layout.fillWidth: true
                    flat: pageIndex !== 1
                    text: backend.t("settings")
                    ToolTip.visible: hovered
                    ToolTip.text: tr("设置（Ctrl+,）", "Settings (Ctrl+,)")
                    onClicked: { pageIndex = 1; doctorResult = backend.doctor() }
                }
                Label { text: "v0.1.0 · Windows"; opacity: .38; font.pixelSize: 11; Layout.alignment: Qt.AlignHCenter }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: pageIndex

            Item {
                DropArea {
                    anchors.fill: parent
                    onDropped: function(drop) {
                        if (drop.urls.length > 0) backend.importBook(drop.urls[0])
                    }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 26
                    visible: !backend.selectedJob.id
                    Item { Layout.fillHeight: true }
                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: 68; Layout.preferredHeight: 68; radius: 18; color: "#c86a3b"
                        Label { anchors.centerIn: parent; text: "F"; color: "white"; font.bold: true; font.pixelSize: 36 }
                    }
                    Label { Layout.alignment: Qt.AlignHCenter; text: backend.t("empty_library"); font.pixelSize: 22; font.bold: true }
                    Label { Layout.alignment: Qt.AlignHCenter; text: tr("支持 EPUB、MOBI、AZW3、FB2、HTML、TXT、Markdown 和 DOCX", "Supports EPUB, MOBI, AZW3, FB2, HTML, TXT, Markdown, and DOCX"); opacity: .55 }
                    Button { Layout.alignment: Qt.AlignHCenter; text: backend.t("import_book"); highlighted: true; onClicked: importDialog.open() }
                    Item { Layout.fillHeight: true }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24
                    visible: !!backend.selectedJob.id
                    spacing: 14

                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Label { text: backend.selectedJob.title || ""; font.bold: true; font.pixelSize: 26 }
                            Label { text: (backend.selectedJob.author || tr("作者未知", "Unknown author")) + " · " + (backend.selectedJob.source_format || "").toUpperCase() + " · " + statusText(backend.selectedJob.status); opacity: .58 }
                        }
                        Button {
                            objectName: "startJobButton"
                            text: backend.selectedJob.status === "paused" || backend.selectedJob.status === "failed" || backend.selectedJob.status === "interrupted" ? tr("继续翻译", "Continue") : tr("开始翻译", "Start")
                            highlighted: true
                            enabled: backend.selectedJob.status !== "translating" && backend.selectedJob.status !== "preparing" && backend.selectedJob.status !== "completed"
                            onClicked: backend.startJob(backend.selectedJob.id)
                        }
                        Button {
                            text: tr("翻译设置…", "Translation settings…")
                            enabled: backend.selectedJob.status !== "translating" && backend.selectedJob.status !== "preparing" && backend.selectedJob.status !== "quality_check" && backend.selectedJob.status !== "exporting"
                            onClicked: { newJobId = backend.selectedJob.id; newJobDialog.open() }
                        }
                        Button {
                            objectName: "pauseJobButton"
                            text: tr("安全暂停", "Pause safely")
                            enabled: backend.selectedJob.status === "translating" || backend.selectedJob.status === "preparing"
                            onClicked: backend.pauseJob(backend.selectedJob.id)
                        }
                        Button {
                            text: tr("归档", "Archive")
                            flat: true
                            enabled: backend.selectedJob.status !== "translating" && backend.selectedJob.status !== "preparing" && backend.selectedJob.status !== "quality_check" && backend.selectedJob.status !== "exporting"
                            onClicked: backend.archiveJob(backend.selectedJob.id)
                        }
                        RoundButton {
                            objectName: "refreshButton"
                            text: "↻"
                            ToolTip.visible: hovered
                            ToolTip.text: tr("刷新（Ctrl+R 或 F5）", "Refresh (Ctrl+R or F5)")
                            onClicked: backend.refresh()
                        }
                    }

                    TabBar {
                        id: tabs
                        objectName: "detailTabs"
                        Layout.fillWidth: true
                        currentIndex: detailTab
                        onCurrentIndexChanged: {
                            detailTab = currentIndex
                            if (backend.selectedJob.id) backend.saveDetailTab(backend.selectedJob.id, currentIndex)
                        }
                        TabButton { text: backend.t("overview") }
                        TabButton { text: backend.t("editor") }
                        TabButton { text: backend.t("glossary") + "  " + backend.glossaryTotal }
                        TabButton { text: backend.t("quality") + "  " + backend.issues.length }
                        TabButton { text: backend.t("usage") }
                        TabButton { text: backend.t("outputs") }
                        TabButton { text: backend.t("logs") }
                    }

                    StackLayout {
                        objectName: "detailPages"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: detailTab

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width
                                spacing: 16
                                RowLayout {
                                    Layout.fillWidth: true
                                    Repeater {
                                        model: [
                                            {label:tr("当前阶段", "Current stage"), value:stageText(backend.selectedJob.stage)},
                                            {label:tr("完成段落", "Segments completed"), value:backend.selectedJob.completed_segments + " / " + backend.selectedJob.total_segments},
                                            {label:tr("实际费用", "Actual cost"), value:backend.selectedJob.cost_configured ? Number(backend.selectedJob.actual_cost || 0).toFixed(4) + " " + (backend.selectedJob.currency || "") : tr("价格未配置", "Pricing not configured")},
                                            {label:tr("默认模型", "Default model"), value:(backend.selectedJob.config && backend.selectedJob.config.profile) ? backend.selectedJob.config.profile.translation_model : ""}
                                        ]
                                        Rectangle {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 104
                                            radius: 12
                                            color: darkMode ? "#24211e" : "#fffdf9"
                                            border.color: darkMode ? "#39332e" : "#e5ddd2"
                                            Column { anchors.fill: parent; anchors.margins: 16; spacing: 9
                                                Label { text: modelData.label; opacity: .55 }
                                                Label { width: parent.width; text: modelData.value; font.bold: true; font.pixelSize: 18; elide: Text.ElideRight }
                                            }
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 118
                                    radius: 12
                                    color: darkMode ? "#24211e" : "#fffdf9"
                                    border.color: darkMode ? "#39332e" : "#e5ddd2"
                                    ColumnLayout { anchors.fill: parent; anchors.margins: 18
                                        RowLayout { Layout.fillWidth: true
                                            Label { text: tr("整本翻译进度", "Whole-book progress"); font.bold: true }
                                            Item { Layout.fillWidth: true }
                                            Label { text: Math.round(100 * Number(backend.selectedJob.completed_segments || 0) / Math.max(1, Number(backend.selectedJob.total_segments || 0))) + "%"; color: "#c86a3b" }
                                        }
                                        ProgressBar { Layout.fillWidth: true; from: 0; to: Math.max(1, Number(backend.selectedJob.total_segments || 0)); value: Number(backend.selectedJob.completed_segments || 0) }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: backend.selectedJob.display_message || tr("任务已经导入，等待开始", "Imported and waiting to start"); opacity: .6; Layout.fillWidth: true }
                                            Label {
                                                visible: backend.selectedJob.status === "translating" && Number(backend.selectedJob.segments_per_minute || 0) > 0
                                                text: Number(backend.selectedJob.segments_per_minute).toFixed(1) + tr(" 段/分钟 · 预计剩余 ", " segments/min · ETA ") + durationText(backend.selectedJob.eta_seconds)
                                                opacity: .6
                                            }
                                        }
                                    }
                                }
                                Rectangle {
                                    visible: !!(backend.selectedJob.warnings && backend.selectedJob.warnings.length > 0)
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: visible ? warningColumn.implicitHeight + 30 : 0
                                    radius: 12
                                    color: darkMode ? "#33291e" : "#fff6df"
                                    border.color: "#d4a04d"
                                    ColumnLayout {
                                        id: warningColumn
                                        anchors.fill: parent
                                        anchors.margins: 15
                                        Label { text: tr("导入与格式提醒", "Import and format notes"); font.bold: true; color: "#b37421" }
                                        Repeater {
                                            model: backend.selectedJob.warnings || []
                                            Label {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                wrapMode: Text.Wrap
                                                text: "• " + backend.localizeText(typeof modelData === "string" ? modelData : (modelData.message || JSON.stringify(modelData)))
                                            }
                                        }
                                    }
                                }
                                Rectangle {
                                    visible: !!(backend.selectedJob.book_context && backend.selectedJob.book_context.overview)
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: visible ? contextColumn.implicitHeight + 30 : 0
                                    radius: 12
                                    color: darkMode ? "#24211e" : "#fffdf9"
                                    border.color: darkMode ? "#39332e" : "#e5ddd2"
                                    ColumnLayout {
                                        id: contextColumn
                                        anchors.fill: parent
                                        anchors.margins: 15
                                        Label { text: tr("全书理解", "Book context"); font.bold: true; font.pixelSize: 18 }
                                        Label { Layout.fillWidth: true; text: backend.selectedJob.book_context ? (backend.selectedJob.book_context.overview || "") : ""; wrapMode: Text.Wrap }
                                        Label {
                                            visible: !!(backend.selectedJob.book_context && backend.selectedJob.book_context.style)
                                            Layout.fillWidth: true
                                            text: tr("文体：", "Style: ") + (backend.selectedJob.book_context ? (backend.selectedJob.book_context.style || "") : "")
                                            wrapMode: Text.Wrap
                                            opacity: .65
                                        }
                                        Label {
                                            visible: !!(backend.selectedJob.book_context && backend.selectedJob.book_context.characters && Object.keys(backend.selectedJob.book_context.characters).length > 0)
                                            Layout.fillWidth: true
                                            text: tr("人物与关系：", "Characters and relationships: ") + JSON.stringify(backend.selectedJob.book_context ? (backend.selectedJob.book_context.characters || []) : [])
                                            wrapMode: Text.Wrap
                                            opacity: .65
                                        }
                                    }
                                }
                                Label { text: tr("处理阶段", "Processing stages"); font.bold: true; font.pixelSize: 18 }
                                Repeater {
                                    model: backend.steps
                                    Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 64
                                        radius: 10
                                        color: darkMode ? "#24211e" : "#fffdf9"
                                        RowLayout { anchors.fill: parent; anchors.margins: 14
                                            Label { text: modelData.status === "done" ? "✓" : modelData.status === "running" ? "●" : "○"; color: modelData.status === "done" ? "#4d9b69" : "#c86a3b"; font.pixelSize: 18 }
                                            Label { text: stageText(modelData.name); font.bold: true; Layout.preferredWidth: 130 }
                                            ProgressBar { Layout.fillWidth: true; from: 0; to: Math.max(1, modelData.total); value: modelData.completed }
                                            Label { text: modelData.display_message || (modelData.completed + "/" + modelData.total); opacity: .55; Layout.preferredWidth: 260; elide: Text.ElideRight }
                                        }
                                    }
                                }
                            }
                        }

                        Item {
                            objectName: "editorPage"
                            RowLayout {
                                objectName: "editorLayout"
                                anchors.fill: parent
                                spacing: 14
                                Rectangle {
                                    Layout.preferredWidth: 245
                                    Layout.fillHeight: true
                                    radius: 10
                                    color: darkMode ? "#211e1b" : "#eee7dc"
                                    ColumnLayout { anchors.fill: parent; anchors.margins: 10
                                        Label { text: tr("章节", "Chapters"); font.bold: true; font.pixelSize: 17 }
                                        ListView {
                                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
                                            model: backend.chapters
                                            delegate: ItemDelegate {
                                                required property var modelData
                                                width: ListView.view.width
                                                text: modelData.title + "  " + modelData.translated_count + "/" + modelData.segment_count
                                                highlighted: backend.selectedChapterId === modelData.id
                                                onClicked: {
                                                    backend.selectChapter(modelData.id)
                                                    Qt.callLater(function() {
                                                        segmentList.contentY = backend.editorPosition(backend.selectedJob.id, modelData.id)
                                                    })
                                                }
                                            }
                                        }
                                    }
                                }
                                ListView {
                                    id: segmentList
                                    objectName: "segmentList"
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumWidth: 360
                                    Layout.minimumHeight: 300
                                    cacheBuffer: 480
                                    clip: true
                                    spacing: 12
                                    model: backend.segments
                                    onContentYChanged: editorPositionTimer.restart()
                                    Timer {
                                        id: editorPositionTimer
                                        interval: 500
                                        onTriggered: backend.saveEditorPosition(backend.selectedJob.id, backend.selectedChapterId, segmentList.contentY)
                                    }
                                    delegate: Rectangle {
                                        objectName: "segmentDelegate"
                                        required property var modelData
                                        property int editVersion: modelData.version
                                        property bool manuallyLocked: modelData.locked
                                        width: ListView.view.width
                                        height: Math.max(230, editorRow.implicitHeight + 38)
                                        radius: 12
                                        color: darkMode ? "#24211e" : "#fffdf9"
                                        border.color: manuallyLocked ? "#d28a65" : (darkMode ? "#39332e" : "#e5ddd2")
                                        ColumnLayout {
                                            anchors.fill: parent; anchors.margins: 14; spacing: 8
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label { text: tr("段落 ", "Segment ") + (modelData.segment_index + 1); font.bold: true; color: "#c86a3b" }
                                                Label {
                                                    objectName: "segmentStatusLabel"
                                                    property string segmentId: modelData.id
                                                    text: manuallyLocked ? tr("人工锁定", "Manually locked") : statusText(modelData.status)
                                                    opacity: .55
                                                }
                                                Item { Layout.fillWidth: true }
                                                ToolButton { text: tr("撤销", "Undo"); enabled: targetEdit.canUndo; onClicked: targetEdit.undo() }
                                                ToolButton { text: tr("恢复", "Redo"); enabled: targetEdit.canRedo; onClicked: targetEdit.redo() }
                                                ToolButton { text: tr("历史", "History"); onClicked: { historySegment = modelData.id; backend.segmentHistory(modelData.id) } }
                                                ToolButton {
                                                    text: tr("重译", "Retranslate")
                                                    enabled: modelData.target_display_text.length > 0
                                                    onClicked: {
                                                        retranslateSegmentId = modelData.id
                                                        retranslateInstruction.clear()
                                                        retranslateDialog.open()
                                                    }
                                                }
                                            }
                                            RowLayout {
                                                id: editorRow
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                spacing: 12
                                                Rectangle {
                                                    Layout.fillWidth: true; Layout.fillHeight: true; radius: 8
                                                    color: darkMode ? "#1d1a18" : "#f4f0e9"
                                                    ScrollView { anchors.fill: parent; anchors.margins: 10
                                                        Label {
                                                            objectName: "sourceTextLabel"
                                                            property string segmentId: modelData.id
                                                            width: parent.width
                                                            text: modelData.source_display_text
                                                            wrapMode: Text.Wrap
                                                            font.pixelSize: 15
                                                            lineHeight: 1.4
                                                        }
                                                    }
                                                }
                                                Rectangle {
                                                    Layout.fillWidth: true; Layout.fillHeight: true; radius: 8
                                                    color: darkMode ? "#1d1a18" : "white"
                                                    ScrollView { anchors.fill: parent; anchors.margins: 5
                                                        TextArea {
                                                            id: targetEdit
                                                            objectName: "translationEditor"
                                                            property string segmentId: modelData.id
                                                            text: modelData.target_display_text
                                                            placeholderText: tr("译文尚未生成", "Translation not generated")
                                                            wrapMode: TextEdit.Wrap
                                                            font.pixelSize: 15
                                                            background: null
                                                            selectByMouse: true
                                                            onTextChanged: if (activeFocus) saveTimer.restart()
                                                            onActiveFocusChanged: {
                                                                if (!activeFocus && saveTimer.running) {
                                                                    saveTimer.stop()
                                                                    saveNow()
                                                                }
                                                            }
                                                            function saveNow() {
                                                                let savedVersion = backend.saveSegment(modelData.id, targetEdit.text, editVersion)
                                                                if (savedVersion > editVersion) {
                                                                    editVersion = savedVersion
                                                                    manuallyLocked = true
                                                                }
                                                            }
                                                            Keys.onPressed: function(event) {
                                                                if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_S) {
                                                                    saveTimer.stop()
                                                                    saveNow()
                                                                    event.accepted = true
                                                                }
                                                            }
                                                            Timer {
                                                                id: saveTimer
                                                                interval: 600
                                                                onTriggered: targetEdit.saveNow()
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Item {
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 10
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: tr("全书术语表", "Book glossary"); font.pixelSize: 19; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    TextField {
                                        Layout.preferredWidth: 240
                                        text: glossaryQuery
                                        placeholderText: tr("搜索原词或译名", "Search source or translation")
                                        onTextChanged: {
                                            glossaryQuery = text.trim()
                                            glossarySearchTimer.restart()
                                        }
                                    }
                                    Timer { id: glossarySearchTimer; interval: 250; onTriggered: backend.searchGlossary(glossaryQuery) }
                                    Label { text: tr("当前冻结版本 ", "Frozen version ") + (backend.selectedJob.glossary_snapshot_version || 0); opacity: .5 }
                                    Label { text: tr("显示 ", "Showing ") + backend.glossary.length + " / " + backend.glossaryTotal; opacity: .5 }
                                    Button { text: tr("刷新冻结版本", "Refresh snapshot"); onClicked: backend.refreshGlossarySnapshot(backend.selectedJob.id) }
                                }
                                ListView {
                                    id: glossaryList
                                    objectName: "glossaryList"
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    spacing: 8
                                    model: backend.glossary
                                    onContentYChanged: {
                                        if (contentY + height >= contentHeight - 240)
                                            backend.loadMoreGlossary()
                                    }
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: ListView.view.width
                                        height: modelData.status === "conflict" ? 108 : 76
                                        radius: 10
                                        color: darkMode ? "#24211e" : "#fffdf9"
                                        border.color: modelData.status === "conflict" ? "#d38b43" : (darkMode ? "#39332e" : "#e5ddd2")
                                        ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 4
                                            RowLayout { Layout.fillWidth: true; spacing: 12
                                                TextField { id: termSource; Layout.preferredWidth: 240; text: modelData.source; readOnly: true }
                                                Label { text: "→"; opacity: .5 }
                                                TextField { id: termTarget; Layout.fillWidth: true; text: modelData.target }
                                                Label { text: modelData.term_type; opacity: .5; Layout.preferredWidth: 80 }
                                                Label { text: modelData.status === "conflict" ? tr("有冲突", "Conflict") : tr("已批准", "Approved"); color: modelData.status === "conflict" ? "#d38b43" : "#4d9b69" }
                                                Button { text: tr("影响段落", "Affected segments"); flat: true; onClicked: backend.showAffectedSegments(backend.selectedJob.id, termSource.text) }
                                                Button { text: tr("保存并批准", "Save and approve"); onClicked: backend.saveGlossary(backend.selectedJob.id, termSource.text, termTarget.text) }
                                                Button {
                                                    text: tr("保存并应用", "Save and apply")
                                                    enabled: termTarget.text !== modelData.target
                                                    onClicked: {
                                                        pendingGlossarySource = termSource.text
                                                        pendingGlossaryTarget = termTarget.text
                                                        glossaryApplyDialog.open()
                                                    }
                                                }
                                            }
                                            RowLayout {
                                                visible: modelData.status === "conflict" && modelData.alternatives && modelData.alternatives.length > 0
                                                Layout.fillWidth: true
                                                Label { text: tr("候选译名：", "Alternatives:"); opacity: .65 }
                                                ComboBox {
                                                    Layout.fillWidth: true
                                                    model: [modelData.target].concat(modelData.alternatives || [])
                                                    onActivated: termTarget.text = currentText
                                                }
                                            }
                                        }
                                    }
                                }
                                Label { visible: backend.glossaryTotal === 0; text: tr("译前准备完成后，这里会显示真正影响全书一致性的术语。", "Terms that affect book-wide consistency appear here after preparation."); opacity: .55 }
                            }
                        }

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 10
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: tr("质量问题", "Quality issues"); font.pixelSize: 19; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: tr("深度审校…", "Deep review…")
                                        enabled: Number(backend.selectedJob.completed_segments || 0) > 0
                                        onClicked: {
                                            reviewEstimate = backend.reviewEstimate(backend.selectedJob.id)
                                            if (reviewEstimate.ok) reviewDialog.open()
                                        }
                                    }
                                }
                                Repeater {
                                    model: backend.issues
                                    Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true; Layout.preferredHeight: issueRow.implicitHeight + 28; radius: 10
                                        color: darkMode ? "#24211e" : "#fffdf9"
                                        border.color: modelData.severity === "error" ? "#b9584f" : "#d4a04d"
                                        RowLayout { id: issueRow; anchors.fill: parent; anchors.margins: 14; spacing: 12
                                            Label { text: modelData.severity === "error" ? tr("严重", "Critical") : tr("提醒", "Warning"); color: modelData.severity === "error" ? "#d46b62" : "#d4a04d"; font.bold: true }
                                            ColumnLayout { Layout.fillWidth: true
                                                Label { text: modelData.category; opacity: .55 }
                                                Label { Layout.fillWidth: true; text: modelData.message; wrapMode: Text.Wrap }
                                                Label { visible: !!modelData.suggestion; Layout.fillWidth: true; text: tr("建议：", "Suggestion: ") + modelData.suggestion; wrapMode: Text.Wrap; opacity: .7 }
                                            }
                                             Label { text: issueStatusText(modelData.status); opacity: .5 }
                                             Button {
                                                 visible: modelData.status === "open" && modelData.suggestion
                                                 text: tr("编辑并应用", "Edit and apply")
                                                 onClicked: {
                                                     pendingIssueId = modelData.id
                                                     pendingIssueSuggestion = modelData.suggestion
                                                     issueSuggestionEdit.text = modelData.suggestion
                                                     issueSuggestionDialog.open()
                                                 }
                                             }
                                             Button { visible: modelData.status === "open"; text: tr("已检查", "Mark reviewed"); onClicked: backend.resolveIssue(modelData.id, "resolved") }
                                            Button { visible: modelData.status === "open"; text: tr("忽略", "Dismiss"); flat: true; onClicked: backend.resolveIssue(modelData.id, "dismissed") }
                                        }
                                    }
                                }
                                Label { visible: backend.issues.length === 0; text: tr("当前没有质量问题。深度审校不会自动运行。", "There are no quality issues. Deep review never runs automatically."); opacity: .55 }
                            }
                        }

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 14
                                Label { text: tr("模型用量与费用", "Model usage and cost"); font.pixelSize: 19; font.bold: true }
                                Label {
                                    visible: !!backend.usage.current_request
                                    text: backend.usage.current_request ? tr("当前请求：", "Current request: ") + stageText(backend.usage.current_request.stage) + " · " + backend.usage.current_request.model + " · " + tr("第 ", "attempt ") + backend.usage.current_request.attempt + tr(" 次尝试", "") : ""
                                    color: "#c86a3b"
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Repeater {
                                        model: [
                                            {label:tr("输入 token", "Input tokens"), value:(backend.usage.total ? backend.usage.total.prompt_tokens : 0)},
                                            {label:tr("输出 token", "Output tokens"), value:(backend.usage.total ? backend.usage.total.completion_tokens : 0)},
                                            {label:tr("缓存命中", "Cached tokens"), value:(backend.usage.total ? backend.usage.total.cache_hit_tokens : 0)},
                                            {label:tr("实际调用", "Calls"), value:(backend.usage.total ? backend.usage.total.calls : 0)},
                                            {label:tr("重试", "Retries"), value:(backend.usage.retries || 0)}
                                        ]
                                        Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 86; radius: 10; color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                                            Column { anchors.centerIn: parent; spacing: 6; Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.value; font.bold: true; font.pixelSize: 20 } Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; opacity: .5 } }
                                        }
                                    }
                                }
                                Label {
                                    text: tr("重试请求消耗：", "Retry usage: ") + (backend.usage.retry_usage ? (backend.usage.retry_usage.prompt_tokens + backend.usage.retry_usage.completion_tokens) : 0) + " token · " + (backend.usage.retry_usage && backend.usage.retry_usage.cost !== null && backend.usage.retry_usage.cost !== undefined ? Number(backend.usage.retry_usage.cost).toFixed(4) + " " + backend.selectedJob.currency : tr("费用未配置", "Pricing not configured"))
                                    opacity: .6
                                }
                                Label { text: tr("按阶段和实际模型", "By stage and actual model"); font.bold: true }
                                Repeater {
                                    model: backend.usage.by_stage_model || []
                                    Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 58; radius: 8; color: darkMode ? "#24211e" : "#fffdf9"
                                        RowLayout { anchors.fill: parent; anchors.margins: 12
                                            Label { text: stageText(modelData.stage); font.bold: true; Layout.preferredWidth: 150 }
                                            Label { text: modelData.model; Layout.fillWidth: true }
                                            Label { text: (modelData.prompt_tokens + modelData.completion_tokens) + " tok"; Layout.preferredWidth: 120 }
                                            Label { text: modelData.cost === null || modelData.cost === undefined ? tr("价格未配置", "Pricing not configured") : Number(modelData.cost).toFixed(4) + " " + backend.selectedJob.currency; opacity: .65; Layout.preferredWidth: 140 }
                                        }
                                    }
                                }
                                Label { text: tr("按章节", "By chapter"); font.bold: true }
                                Repeater {
                                    model: backend.usage.by_chapter || []
                                    Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 54; radius: 8; color: darkMode ? "#24211e" : "#fffdf9"
                                        RowLayout { anchors.fill: parent; anchors.margins: 12
                                            Label { text: modelData.chapter_title; Layout.fillWidth: true; elide: Text.ElideRight }
                                            Label { text: modelData.calls + tr(" 次", " calls"); Layout.preferredWidth: 70 }
                                            Label { text: (modelData.prompt_tokens + modelData.completion_tokens) + " tok"; Layout.preferredWidth: 120 }
                                            Label { text: modelData.cost === null || modelData.cost === undefined ? tr("价格未配置", "Pricing not configured") : Number(modelData.cost).toFixed(4) + " " + backend.selectedJob.currency; opacity: .65; Layout.preferredWidth: 140 }
                                        }
                                    }
                                }
                                Label { text: tr("最近请求明细", "Recent request details"); font.bold: true }
                                Repeater {
                                    model: backend.usage.requests || []
                                    Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 48; radius: 7; color: darkMode ? "#211e1b" : "#f8f3eb"
                                        RowLayout { anchors.fill: parent; anchors.margins: 10
                                            Label { text: stageText(modelData.stage); Layout.preferredWidth: 120 }
                                            Label { text: modelData.chapter_title || tr("全书任务", "Whole-book task"); Layout.fillWidth: true; elide: Text.ElideRight }
                                            Label { text: modelData.model; Layout.preferredWidth: 170; elide: Text.ElideRight }
                                            Label { text: tr("尝试 ", "Attempt ") + modelData.attempt; Layout.preferredWidth: 65 }
                                            Label { text: requestStatusText(modelData.status); Layout.preferredWidth: 80 }
                                            Label { text: (modelData.prompt_tokens + modelData.completion_tokens) + " tok"; Layout.preferredWidth: 100 }
                                        }
                                    }
                                }
                            }
                        }

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 12
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: tr("成品与中间产物", "Outputs and artifacts"); font.pixelSize: 19; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    ComboBox {
                                        id: reExportFormat
                                        textRole: "label"; valueRole: "value"
                                        model: [
                                            {label:"EPUB", value:"epub"}, {label:"DOCX", value:"docx"},
                                            {label:"HTML", value:"html"}, {label:"TXT", value:"txt"},
                                            {label:"Markdown", value:"md"}
                                        ]
                                    }
                                    Button {
                                        text: tr("重新导出", "Export again")
                                        enabled: Number(backend.selectedJob.completed_segments || 0) > 0
                                        onClicked: requestExport(reExportFormat.currentValue)
                                    }
                                }
                                Repeater {
                                    model: backend.artifacts
                                    Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 72; radius: 10; color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                                        RowLayout { anchors.fill: parent; anchors.margins: 12
                                            Label { text: modelData.format.toUpperCase(); color: "#c86a3b"; font.bold: true; Layout.preferredWidth: 80 }
                                            Label { text: modelData.path; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                            Button {
                                                visible: modelData.kind === "translation"
                                                text: tr("预览", "Preview")
                                                onClicked: {
                                                    previewTitle = modelData.format.toUpperCase() + tr(" 预览", " preview")
                                                    previewContent = backend.previewArtifact(modelData.path)
                                                    if (previewContent.length) previewDialog.open()
                                                }
                                            }
                                            Button { text: tr("打开", "Open"); onClicked: backend.openPath(modelData.path) }
                                            Button { text: tr("所在目录", "Show folder"); flat: true; onClicked: backend.openContainingFolder(modelData.path) }
                                        }
                                    }
                                }
                                Label { visible: backend.artifacts.length === 0; text: tr("翻译完成后会自动生成设置中的输出格式。", "The configured output format is generated when translation finishes."); opacity: .55 }
                            }
                        }

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 7
                                RowLayout { Layout.fillWidth: true; Label { text: tr("任务日志", "Job log"); font.pixelSize: 19; font.bold: true } Item { Layout.fillWidth: true } Button { text: tr("立即停止 Worker", "Stop worker now"); flat: true; onClicked: backend.forceStopJob(backend.selectedJob.id) } }
                                Repeater {
                                    model: backend.events
                                    Rectangle {
                                        required property var modelData
                                        property bool expanded: false
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: logColumn.implicitHeight + 20
                                        radius: 7; color: darkMode ? "#24211e" : "#fffdf9"
                                        ColumnLayout {
                                            id: logColumn
                                            anchors.fill: parent; anchors.margins: 10
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label { text: modelData.seq; opacity: .35; Layout.preferredWidth: 45 }
                                                Label { text: eventText(modelData.event_type); color: "#c86a3b"; Layout.fillWidth: true }
                                                Label { text: modelData.created_at; opacity: .4 }
                                                ToolButton { text: expanded ? tr("收起", "Collapse") : tr("详情", "Details"); onClicked: expanded = !expanded }
                                            }
                                            Label {
                                                visible: expanded
                                                Layout.fillWidth: true
                                                text: JSON.stringify(modelData.display_payload || modelData.payload, null, 2)
                                                wrapMode: Text.WrapAnywhere
                                                opacity: .65
                                                font.family: "Consolas"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            ScrollView {
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: 18
                    anchors.margins: 30
                    Label { text: tr("设置", "Settings"); font.pixelSize: 28; font.bold: true }
                    Label { text: tr("连接与本地依赖", "Connections and local dependencies"); font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: settingsColumn.implicitHeight + 36; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        ColumnLayout {
                            id: settingsColumn
                            anchors.fill: parent; anchors.margins: 18; spacing: 12
                            Label { text: tr("模型 API Key", "Model API key"); font.bold: true }
                            RowLayout { Layout.fillWidth: true
                                TextField { id: apiKey; Layout.fillWidth: true; echoMode: TextInput.Password; placeholderText: tr("保存在 Windows 凭据管理器，不写入项目", "Stored in Windows Credential Manager, never in the project") }
                                Button { text: tr("保存", "Save"); enabled: apiKey.text.length > 0; onClicked: { backend.saveApiKey("deepseek-default", apiKey.text); apiKey.clear() } }
                            }
                            Label { text: tr("模型服务", "Model provider"); font.bold: true }
                            RowLayout {
                                Layout.fillWidth: true
                                ComboBox {
                                    id: modelProvider
                                    Layout.preferredWidth: 190
                                    textRole: "label"; valueRole: "value"
                                    model: [
                                        {label:"DeepSeek", value:"deepseek"},
                                        {label:tr("OpenAI 兼容", "OpenAI compatible"), value:"openai"},
                                        {label:tr("Ollama 本地", "Local Ollama"), value:"ollama"},
                                        {label:tr("vLLM 本地", "Local vLLM"), value:"vllm"}
                                    ]
                                    currentIndex: doctorResult.model_profile && doctorResult.model_profile.provider === "ollama" ? 2 : doctorResult.model_profile && doctorResult.model_profile.provider === "vllm" ? 3 : doctorResult.model_profile && doctorResult.model_profile.provider === "openai" ? 1 : 0
                                    onActivated: {
                                        if (currentValue === "deepseek") {
                                            modelBaseUrl.text = "https://api.deepseek.com"
                                            modelName.text = "deepseek-v4-flash"
                                            inputPrice.text = "0.22"
                                            cachedPrice.text = "0.007"
                                            outputPrice.text = "0.66"
                                        } else {
                                            modelBaseUrl.text = currentValue === "openai" ? "https://api.openai.com/v1" : (currentValue === "ollama" ? "http://127.0.0.1:11434/v1" : "http://127.0.0.1:8000/v1")
                                            modelName.clear()
                                            inputPrice.clear()
                                            cachedPrice.clear()
                                            outputPrice.clear()
                                            priceDate.clear()
                                        }
                                    }
                                }
                                TextField {
                                    id: modelBaseUrl
                                    Layout.fillWidth: true
                                    placeholderText: tr("OpenAI 兼容接口地址", "OpenAI-compatible endpoint")
                                    text: doctorResult.model_profile ? doctorResult.model_profile.base_url : "https://api.deepseek.com"
                                }
                            }
                            Label { text: tr("默认模型（翻译、译前准备、修复和主动审校）", "Default model (translation, preparation, repair, and optional review)"); font.bold: true }
                            TextField {
                                id: modelName
                                Layout.fillWidth: true
                                text: doctorResult.model_profile ? doctorResult.model_profile.translation_model : "deepseek-v4-flash"
                            }
                            Label { text: tr("每百万 token 单价", "Price per million tokens"); font.bold: true }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField { id: inputPrice; Layout.fillWidth: true; placeholderText: tr("未缓存输入", "Uncached input"); text: doctorResult.model_profile ? doctorResult.model_profile.input_price_per_million : "0.22" }
                                TextField { id: cachedPrice; Layout.fillWidth: true; placeholderText: tr("缓存命中输入", "Cached input"); text: doctorResult.model_profile ? doctorResult.model_profile.cached_input_price_per_million : "0.007" }
                                TextField { id: outputPrice; Layout.fillWidth: true; placeholderText: tr("输出", "Output"); text: doctorResult.model_profile ? doctorResult.model_profile.output_price_per_million : "0.66" }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField { id: priceCurrency; Layout.preferredWidth: 120; placeholderText: tr("币种", "Currency"); text: doctorResult.model_profile ? doctorResult.model_profile.currency : "USD" }
                                TextField { id: priceDate; Layout.fillWidth: true; placeholderText: tr("生效日期", "Effective date"); text: doctorResult.model_profile ? doctorResult.model_profile.price_effective_date : "2026-08-16" }
                                Button {
                                    text: tr("保存模型设置", "Save model settings")
                                    onClicked: backend.saveModelSettings(modelProvider.currentValue, modelBaseUrl.text, modelName.text, inputPrice.text, cachedPrice.text, outputPrice.text, priceCurrency.text, priceDate.text, priceSource.text)
                                }
                            }
                            TextField {
                                id: priceSource
                                Layout.fillWidth: true
                                placeholderText: tr("价格来源网址或说明", "Pricing source URL or note")
                                text: doctorResult.model_profile && doctorResult.model_profile.price_source ? doctorResult.model_profile.price_source : ""
                            }
                            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; opacity: .5; text: tr("DeepSeek 默认按官方峰谷规则计费；其他服务不会沿用 DeepSeek 的价格或峰谷规则。任务创建后会保存配置快照。", "DeepSeek uses its official peak/off-peak pricing. Other providers never inherit DeepSeek pricing rules. Each job stores its own configuration snapshot.") }
                            Label { text: tr("Kindle 格式转换", "Kindle format conversion"); font.bold: true }
                            RowLayout { Layout.fillWidth: true
                                TextField { Layout.fillWidth: true; readOnly: true; text: doctorResult.kindleunpack && doctorResult.kindleunpack.path ? "KindleUnpack: " + doctorResult.kindleunpack.path : (doctorResult.calibre && doctorResult.calibre.path ? "Calibre: " + doctorResult.calibre.path : tr("未找到转换后端", "No conversion backend found")) }
                                Button { text: tr("选择 Calibre 兜底路径", "Choose optional Calibre fallback"); onClicked: calibreDialog.open() }
                            }
                            Label { text: tr("工作区", "Workspace"); font.bold: true }
                            TextField { Layout.fillWidth: true; readOnly: true; text: doctorResult.workspace || "" }
                        }
                    }
                    Label { text: tr("外观", "Appearance"); font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 78; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        RowLayout { anchors.fill: parent; anchors.margins: 18
                            Label { text: tr("深色模式", "Dark mode"); Layout.fillWidth: true }
                            Switch { checked: backend.darkMode; onToggled: backend.setDarkMode(checked) }
                            Label { text: tr("界面语言", "Language") }
                            ComboBox {
                                textRole: "label"; valueRole: "value"
                                model: [{label:"简体中文", value:"zh-CN"}, {label:"English", value:"en"}]
                                currentIndex: backend.uiLanguage === "en" ? 1 : 0
                                onActivated: backend.setLanguage(currentValue)
                            }
                            Label { text: tr("缩放", "Scale") }
                            ComboBox {
                                textRole: "label"; valueRole: "value"
                                model: [{label:"80%",value:0.8},{label:"100%",value:1.0},{label:"125%",value:1.25},{label:"150%",value:1.5}]
                                currentIndex: backend.uiScale <= 0.8 ? 0 : backend.uiScale <= 1.0 ? 1 : backend.uiScale <= 1.25 ? 2 : 3
                                onActivated: backend.setUiScale(currentValue)
                            }
                        }
                    }
                    Label { text: tr("任务并发", "Job concurrency"); font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 92; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        RowLayout { anchors.fill: parent; anchors.margins: 18
                            ColumnLayout { Layout.fillWidth: true
                                Label { text: tr("同时运行的书籍数", "Simultaneous books"); font.bold: true }
                                Label { text: tr("默认一次一本；其余任务自动排队，单本内部仍按稳妥加速并发。", "One book by default; others queue automatically while each book uses steady internal concurrency."); opacity: .5 }
                            }
                            SpinBox {
                                id: activeTaskLimit
                                from: 1; to: 4; value: doctorResult.active_task_limit || 1
                                onValueModified: backend.saveActiveTaskLimit(value)
                            }
                        }
                    }
                    Label { text: tr("环境检查", "Environment check"); font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: doctorColumn.implicitHeight + 34; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        ColumnLayout { id: doctorColumn; anchors.fill: parent; anchors.margins: 17
                            Label { text: tr("核心依赖：", "Core dependencies: ") + (doctorResult.ok ? tr("正常", "Ready") : tr("有缺失", "Missing")); color: doctorResult.ok ? "#4d9b69" : "#d46b62" }
                            Label { text: ((doctorResult.model_profile && doctorResult.model_profile.provider) || "Model") + " API Key: " + (doctorResult.model_api_key && doctorResult.model_api_key.available ? tr("已配置", "Configured") : tr("未配置", "Not configured")) }
                            Label { text: "KindleUnpack: " + (doctorResult.kindleunpack && doctorResult.kindleunpack.available ? tr("可用", "Available") : tr("未配置", "Not configured")) }
                            Label { text: tr("Calibre（可选兜底）：", "Calibre (optional fallback): ") + (doctorResult.calibre && doctorResult.calibre.available ? tr("可用", "Available") : tr("未配置", "Not configured")) }
                            RowLayout {
                                Button { text: tr("重新检查", "Check again"); onClicked: doctorResult = backend.doctor() }
                                Button { text: tr("测试模型连接", "Test model connection"); onClicked: backend.testModelConnection() }
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }
    }

    BusyIndicator {
        visible: backend.busy
        running: visible
        z: 90
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 24
    }

    Component.onCompleted: {
        doctorResult = backend.doctor()
        if (backend.selectedJob.id) {
            detailTab = backend.detailTab(backend.selectedJob.id)
            Qt.callLater(function() {
                segmentList.contentY = backend.editorPosition(backend.selectedJob.id, backend.selectedChapterId)
            })
        }
        if (backend.firstRun) firstRunDialog.open()
    }
}
