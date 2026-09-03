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
    color: darkMode ? "#171513" : "#f5f1ea"
    property bool darkMode: false
    property int pageIndex: 0
    property int detailTab: 0
    property var doctorResult: ({})
    property var historyRows: []
    property string historySegment: ""
    property string retranslateSegmentId: ""
    property string pendingGlossarySource: ""
    property string pendingGlossaryTarget: ""
    property var reviewEstimate: ({})
    property string newJobId: ""

    Material.theme: darkMode ? Material.Dark : Material.Light
    Material.accent: "#c86a3b"
    Material.primary: "#5d3928"

    function statusText(status) {
        const labels = {
            "queued": "排队中", "preparing": "译前准备", "translating": "翻译中",
            "quality_check": "质量检查", "ready": "可以导出", "exporting": "正在导出",
            "completed": "已完成", "paused": "已暂停", "interrupted": "已中断",
            "cancelled": "已取消", "failed": "失败"
        }
        return labels[status] || status || "未知"
    }

    function stageText(stage) {
        const labels = {"imported":"已导入", "prepare":"全书理解", "translate":"正文翻译", "quality":"质量检查", "deep_review":"深度审校", "export":"生成成品", "completed":"完成", "migrated":"迁移完成"}
        return labels[stage] || stage || ""
    }

    function eventText(type) {
        const labels = {
            "book.imported":"书籍已导入", "job.started":"任务开始运行",
            "stage.changed":"处理阶段已切换", "progress.updated":"翻译进度已更新",
            "usage.recorded":"记录了一次模型用量", "warning.raised":"运行中出现提醒",
            "job.paused":"任务已安全暂停", "job.completed":"任务已经完成",
            "job.failed":"任务运行失败", "job.interrupted":"检测到上次运行中断",
            "segment.retranslated":"一个段落已重译", "review.completed":"深度审校完成",
            "export.completed":"成品已重新导出", "job.archived":"任务已归档"
        }
        return labels[type] || type
    }

    FileDialog {
        id: importDialog
        title: "选择要翻译的书籍"
        nameFilters: ["支持的书籍 (*.epub *.mobi *.azw *.azw3 *.azw4 *.fb2 *.html *.htm *.txt *.md *.markdown *.docx)", "所有文件 (*)"]
        onAccepted: backend.importBook(selectedFile)
    }

    FileDialog {
        id: calibreDialog
        title: "选择 ebook-convert.exe"
        nameFilters: ["Calibre ebook-convert (ebook-convert.exe)"]
        onAccepted: backend.setCalibrePath(selectedFile)
    }

    Connections {
        target: backend
        function onMessage(kind, text) {
            toast.kind = kind
            toast.text = text
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
            historyDialog.open()
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
        title: "段落修改历史"
        standardButtons: Dialog.Close
        ScrollView {
            anchors.fill: parent
            ListView {
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
                        Label { text: "版本 " + modelData.version + " · " + modelData.origin + " · " + modelData.created_at; color: "#aa795d" }
                        Label { Layout.fillWidth: true; text: modelData.text; wrapMode: Text.Wrap; font.pixelSize: 15 }
                        Button {
                            text: "恢复这个版本"
                            Layout.alignment: Qt.AlignRight
                            onClicked: {
                                backend.restoreRevision(modelData.id)
                                historyDialog.close()
                            }
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
        title: "欢迎使用 FolioCross"
        ColumnLayout {
            width: parent.width
            spacing: 14
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "先确认本地转换工具和模型连接。API Key 会保存到 Windows 凭据管理器，不会写入仓库。" }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: firstCheckColumn.implicitHeight + 28
                radius: 10; color: darkMode ? "#24211e" : "#f8f3eb"
                ColumnLayout {
                    id: firstCheckColumn
                    anchors.fill: parent; anchors.margins: 14
                    Label { text: "Python 组件：" + (doctorResult.ok ? "正常" : "有缺失"); color: doctorResult.ok ? "#4d9b69" : "#d46b62" }
                    Label { text: "Calibre：" + (doctorResult.calibre && doctorResult.calibre.available ? "已找到" : "未找到，MOBI/AZW3 暂不能导入") }
                    Label { text: "默认模型：deepseek-v4-flash（thinking 关闭）" }
                    Label { text: "官方谷时单价：缓存 0.007 / 输入 0.22 / 输出 0.66 USD（每百万 token）"; opacity: .65 }
                }
            }
            TextField {
                id: firstApiKey
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: doctorResult.deepseek_api_key && doctorResult.deepseek_api_key.available ? "已经从凭据或环境变量找到 API Key，可留空" : "填写 DeepSeek API Key"
            }
            RowLayout {
                Layout.fillWidth: true
                Button { text: "重新检查"; flat: true; onClicked: doctorResult = backend.doctor() }
                Button { text: "测试模型连接"; onClicked: backend.testModelConnection() }
                Item { Layout.fillWidth: true }
                Button {
                    text: "使用当前配置"
                    highlighted: true
                    onClicked: { backend.completeFirstRun(firstApiKey.text); firstRunDialog.close() }
                }
            }
        }
    }

    Dialog {
        id: retranslateDialog
        modal: true
        width: 620
        anchors.centerIn: parent
        title: "单段重译"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: {
            backend.retranslateSegment(backend.selectedJob.id, retranslateSegmentId, retranslateInstruction.text)
            retranslateInstruction.clear()
        }
        ColumnLayout {
            width: parent.width
            Label { text: "可以说明这一段需要怎样调整；留空则按全书规则重新翻译。"; wrapMode: Text.Wrap; Layout.fillWidth: true }
            TextArea {
                id: retranslateInstruction
                Layout.fillWidth: true
                Layout.preferredHeight: 120
                placeholderText: "例如：语气更克制，保留专业术语的英文缩写"
                wrapMode: TextEdit.Wrap
            }
        }
    }

    Dialog {
        id: glossaryApplyDialog
        modal: true
        width: 620
        anchors.centerIn: parent
        title: "把术语改动应用到已有译文"
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
            text: "只会在包含原词的段落中，把旧译名精确替换为新译名。每个变化都会保存为人工锁定版本，可以从历史中恢复。"
        }
    }

    Dialog {
        id: reviewDialog
        modal: true
        width: 660
        anchors.centerIn: parent
        title: "启动深度审校"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: backend.startDeepReview(backend.selectedJob.id)
        ColumnLayout {
            width: parent.width
            spacing: 10
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "深度审校是额外模型调用。它只生成问题和修改建议，不会直接覆盖译文。" }
            Label { text: "模型：" + (reviewEstimate.model || "") }
            Label { text: "预计调用：" + (reviewEstimate.estimated_calls || 0) + " 次" }
            Label { text: "预计 token：" + (reviewEstimate.estimated_input_tokens || 0) + " 输入 / " + (reviewEstimate.estimated_output_tokens || 0) + " 输出" }
            Label {
                text: reviewEstimate.estimated_cost_min === null || reviewEstimate.estimated_cost_min === undefined
                    ? "费用：当前价格未配置"
                    : "预计费用：" + Number(reviewEstimate.estimated_cost_min).toFixed(4) + "–" + Number(reviewEstimate.estimated_cost_max).toFixed(4) + " " + reviewEstimate.currency
                font.bold: true
                color: "#c86a3b"
            }
        }
    }

    Dialog {
        id: newJobDialog
        modal: true
        width: Math.min(window.width - 100, 760)
        anchors.centerIn: parent
        title: "新建翻译"

        function submit(action) {
            backend.configureJob(
                newJobId || backend.selectedJob.id,
                sourceLanguage.currentValue,
                outputFormat.currentValue,
                bilingualOutput.checked,
                softBudget.text,
                hardBudget.text,
                action
            )
            close()
        }

        ColumnLayout {
            width: parent.width
            spacing: 14
            Label { text: backend.selectedJob.title || ""; font.bold: true; font.pixelSize: 20 }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: "源语言"; font.bold: true }
                    ComboBox {
                        id: sourceLanguage
                        Layout.fillWidth: true
                        textRole: "label"; valueRole: "value"
                        model: [
                            {label:"自动识别", value:"auto"}, {label:"英语", value:"en"},
                            {label:"日语", value:"ja"}, {label:"法语", value:"fr"},
                            {label:"德语", value:"de"}, {label:"西班牙语", value:"es"}
                        ]
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: "目标语言"; font.bold: true }
                    TextField { Layout.fillWidth: true; text: "简体中文（zh-CN）"; readOnly: true }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: "输出格式"; font.bold: true }
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
                    Label { text: "稳妥加速"; font.bold: true; color: "#c86a3b" }
                    Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Flash 直接翻译；译前扫描最多 4 路，正文从 2 路开始、最高 4 路；不执行二次全文润色或自动深度审校。" }
                    Label { text: "预计 token：" + Number(backend.selectedJob.estimated_input_tokens || 0) + " 输入 / " + Number(backend.selectedJob.estimated_output_tokens || 0) + " 输出"; opacity: .65 }
                    Label {
                        text: backend.selectedJob.estimated_cost === null || backend.selectedJob.estimated_cost === undefined
                            ? "预计费用：价格未配置"
                            : "预计谷时费用约 " + Number(backend.selectedJob.estimated_cost).toFixed(4) + " " + (backend.selectedJob.currency || "") + "，峰时可能更高"
                        opacity: .65
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                CheckBox { id: bilingualOutput; text: "生成双语对照" }
                Item { Layout.fillWidth: true }
                Label { text: "费用提醒" }
                TextField { id: softBudget; Layout.preferredWidth: 110; placeholderText: "可选" }
                Label { text: "硬预算上限" }
                TextField { id: hardBudget; Layout.preferredWidth: 110; placeholderText: "可选" }
                Label { text: backend.selectedJob.currency || "USD"; opacity: .6 }
            }
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; opacity: .55; text: "先做译前准备会生成全书概览和冻结术语表，然后自动暂停，方便确认后再翻译。" }
            RowLayout {
                Layout.fillWidth: true
                Button { text: "稍后处理"; flat: true; onClicked: newJobDialog.close() }
                Item { Layout.fillWidth: true }
                Button { text: "只做译前准备"; onClicked: newJobDialog.submit("prepare") }
                Button { text: "直接开始"; highlighted: true; onClicked: newJobDialog.submit("start") }
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
                        Label { text: "整本书翻译工作台"; opacity: .58; font.pixelSize: 12 }
                    }
                }

                Button {
                    Layout.fillWidth: true
                    text: "+  " + backend.t("import_book")
                    highlighted: true
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
                            onClicked: { pageIndex = 0; backend.selectJob(modelData.id) }
                        }
                        Column {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 4
                            Label { width: parent.width; text: modelData.title; elide: Text.ElideRight; font.bold: true }
                            Row {
                                spacing: 8
                                Label { text: statusText(modelData.status); color: "#c86a3b"; font.pixelSize: 12 }
                                Label { text: modelData.completed_segments + "/" + modelData.total_segments; opacity: .55; font.pixelSize: 12 }
                            }
                            ProgressBar {
                                width: parent.width
                                height: 5
                                from: 0
                                to: Math.max(1, modelData.total_segments)
                                value: modelData.completed_segments
                            }
                        }
                    }
                }

                ToolSeparator { Layout.fillWidth: true; orientation: Qt.Horizontal }

                Button {
                    Layout.fillWidth: true
                    flat: pageIndex !== 1
                    text: backend.t("settings")
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
                    Label { Layout.alignment: Qt.AlignHCenter; text: "支持 EPUB、MOBI、AZW3、FB2、HTML、TXT、Markdown 和 DOCX"; opacity: .55 }
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
                            Label { text: (backend.selectedJob.author || "作者未知") + " · " + (backend.selectedJob.source_format || "").toUpperCase() + " · " + statusText(backend.selectedJob.status); opacity: .58 }
                        }
                        Button {
                            text: backend.selectedJob.status === "paused" || backend.selectedJob.status === "failed" || backend.selectedJob.status === "interrupted" ? "继续翻译" : "开始翻译"
                            highlighted: true
                            enabled: backend.selectedJob.status !== "translating" && backend.selectedJob.status !== "preparing" && backend.selectedJob.status !== "completed"
                            onClicked: backend.startJob(backend.selectedJob.id)
                        }
                        Button {
                            text: "翻译设置…"
                            enabled: backend.selectedJob.status !== "translating" && backend.selectedJob.status !== "preparing" && backend.selectedJob.status !== "quality_check" && backend.selectedJob.status !== "exporting"
                            onClicked: { newJobId = backend.selectedJob.id; newJobDialog.open() }
                        }
                        Button {
                            text: "安全暂停"
                            enabled: backend.selectedJob.status === "translating" || backend.selectedJob.status === "preparing"
                            onClicked: backend.pauseJob(backend.selectedJob.id)
                        }
                        Button {
                            text: "归档"
                            flat: true
                            enabled: backend.selectedJob.status !== "translating" && backend.selectedJob.status !== "preparing" && backend.selectedJob.status !== "quality_check" && backend.selectedJob.status !== "exporting"
                            onClicked: backend.archiveJob(backend.selectedJob.id)
                        }
                        RoundButton { text: "↻"; onClicked: backend.refresh() }
                    }

                    TabBar {
                        id: tabs
                        Layout.fillWidth: true
                        currentIndex: detailTab
                        onCurrentIndexChanged: detailTab = currentIndex
                        TabButton { text: backend.t("overview") }
                        TabButton { text: backend.t("editor") }
                        TabButton { text: backend.t("glossary") + "  " + backend.glossary.length }
                        TabButton { text: backend.t("quality") + "  " + backend.issues.length }
                        TabButton { text: backend.t("usage") }
                        TabButton { text: backend.t("outputs") }
                        TabButton { text: backend.t("logs") }
                    }

                    StackLayout {
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
                                            {label:"当前阶段", value:stageText(backend.selectedJob.stage)},
                                            {label:"完成段落", value:backend.selectedJob.completed_segments + " / " + backend.selectedJob.total_segments},
                                            {label:"实际费用", value:Number(backend.selectedJob.actual_cost || 0).toFixed(4) + " " + (backend.selectedJob.currency || "")},
                                            {label:"默认模型", value:(backend.selectedJob.config && backend.selectedJob.config.profile) ? backend.selectedJob.config.profile.translation_model : ""}
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
                                            Label { text: "整本翻译进度"; font.bold: true }
                                            Item { Layout.fillWidth: true }
                                            Label { text: Math.round(100 * Number(backend.selectedJob.completed_segments || 0) / Math.max(1, Number(backend.selectedJob.total_segments || 0))) + "%"; color: "#c86a3b" }
                                        }
                                        ProgressBar { Layout.fillWidth: true; from: 0; to: Math.max(1, Number(backend.selectedJob.total_segments || 0)); value: Number(backend.selectedJob.completed_segments || 0) }
                                        Label { text: backend.selectedJob.current_message || "任务已经导入，等待开始"; opacity: .6 }
                                    }
                                }
                                Rectangle {
                                    visible: backend.selectedJob.warnings && backend.selectedJob.warnings.length > 0
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: visible ? warningColumn.implicitHeight + 30 : 0
                                    radius: 12
                                    color: darkMode ? "#33291e" : "#fff6df"
                                    border.color: "#d4a04d"
                                    ColumnLayout {
                                        id: warningColumn
                                        anchors.fill: parent
                                        anchors.margins: 15
                                        Label { text: "导入与格式提醒"; font.bold: true; color: "#b37421" }
                                        Repeater {
                                            model: backend.selectedJob.warnings || []
                                            Label {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                wrapMode: Text.Wrap
                                                text: "• " + (typeof modelData === "string" ? modelData : (modelData.message || JSON.stringify(modelData)))
                                            }
                                        }
                                    }
                                }
                                Label { text: "处理阶段"; font.bold: true; font.pixelSize: 18 }
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
                                            Label { text: modelData.message || (modelData.completed + "/" + modelData.total); opacity: .55; Layout.preferredWidth: 260; elide: Text.ElideRight }
                                        }
                                    }
                                }
                            }
                        }

                        Item {
                            RowLayout {
                                anchors.fill: parent
                                spacing: 14
                                Rectangle {
                                    Layout.preferredWidth: 245
                                    Layout.fillHeight: true
                                    radius: 10
                                    color: darkMode ? "#211e1b" : "#eee7dc"
                                    ColumnLayout { anchors.fill: parent; anchors.margins: 10
                                        Label { text: "章节"; font.bold: true; font.pixelSize: 17 }
                                        ListView {
                                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
                                            model: backend.chapters
                                            delegate: ItemDelegate {
                                                required property var modelData
                                                width: ListView.view.width
                                                text: modelData.title + "  " + modelData.translated_count + "/" + modelData.segment_count
                                                onClicked: backend.selectChapter(modelData.id)
                                            }
                                        }
                                    }
                                }
                                ListView {
                                    id: segmentList
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    spacing: 12
                                    model: backend.segments
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: ListView.view.width
                                        height: Math.max(230, editorRow.implicitHeight + 38)
                                        radius: 12
                                        color: darkMode ? "#24211e" : "#fffdf9"
                                        border.color: modelData.locked ? "#d28a65" : (darkMode ? "#39332e" : "#e5ddd2")
                                        ColumnLayout {
                                            anchors.fill: parent; anchors.margins: 14; spacing: 8
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label { text: "段落 " + (modelData.segment_index + 1); font.bold: true; color: "#c86a3b" }
                                                Label { text: modelData.locked ? "人工锁定" : statusText(modelData.status); opacity: .55 }
                                                Item { Layout.fillWidth: true }
                                                ToolButton { text: "历史"; onClicked: { historySegment = modelData.id; backend.segmentHistory(modelData.id) } }
                                                ToolButton {
                                                    text: "重译"
                                                    enabled: modelData.target_text.length > 0
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
                                                        Label { width: parent.width; text: modelData.source_text; wrapMode: Text.Wrap; font.pixelSize: 15; lineHeight: 1.4 }
                                                    }
                                                }
                                                Rectangle {
                                                    Layout.fillWidth: true; Layout.fillHeight: true; radius: 8
                                                    color: darkMode ? "#1d1a18" : "white"
                                                    ScrollView { anchors.fill: parent; anchors.margins: 5
                                                        TextArea {
                                                            id: targetEdit
                                                            text: modelData.target_text
                                                            placeholderText: "译文尚未生成"
                                                            wrapMode: TextEdit.Wrap
                                                            font.pixelSize: 15
                                                            background: null
                                                            onTextChanged: if (activeFocus) saveTimer.restart()
                                                            Timer {
                                                                id: saveTimer
                                                                interval: 600
                                                                onTriggered: backend.saveSegment(modelData.id, targetEdit.text, modelData.version)
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

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width
                                spacing: 10
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "全书术语表"; font.pixelSize: 19; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    Label { text: "修改后不会自动覆盖正文"; opacity: .5 }
                                }
                                Repeater {
                                    model: backend.glossary
                                    Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true; Layout.preferredHeight: 76; radius: 10
                                        color: darkMode ? "#24211e" : "#fffdf9"
                                        border.color: modelData.status === "conflict" ? "#d38b43" : (darkMode ? "#39332e" : "#e5ddd2")
                                        RowLayout { anchors.fill: parent; anchors.margins: 12; spacing: 12
                                            TextField { id: termSource; Layout.preferredWidth: 240; text: modelData.source; readOnly: true }
                                            Label { text: "→"; opacity: .5 }
                                            TextField { id: termTarget; Layout.fillWidth: true; text: modelData.target }
                                            Label { text: modelData.term_type; opacity: .5; Layout.preferredWidth: 80 }
                                            Label { text: modelData.status === "conflict" ? "有冲突" : "已批准"; color: modelData.status === "conflict" ? "#d38b43" : "#4d9b69" }
                                             Button { text: "保存"; onClicked: backend.saveGlossary(backend.selectedJob.id, termSource.text, termTarget.text) }
                                             Button {
                                                 text: "保存并应用"
                                                 enabled: termTarget.text !== modelData.target
                                                 onClicked: {
                                                     pendingGlossarySource = termSource.text
                                                     pendingGlossaryTarget = termTarget.text
                                                     glossaryApplyDialog.open()
                                                 }
                                             }
                                        }
                                    }
                                }
                                Label { visible: backend.glossary.length === 0; text: "译前准备完成后，这里会显示真正影响全书一致性的术语。"; opacity: .55 }
                            }
                        }

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 10
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "质量问题"; font.pixelSize: 19; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: "深度审校…"
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
                                            Label { text: modelData.severity === "error" ? "严重" : "提醒"; color: modelData.severity === "error" ? "#d46b62" : "#d4a04d"; font.bold: true }
                                            ColumnLayout { Layout.fillWidth: true
                                                Label { text: modelData.category; opacity: .55 }
                                                Label { Layout.fillWidth: true; text: modelData.message; wrapMode: Text.Wrap }
                                            }
                                             Label { text: modelData.status; opacity: .5 }
                                             Button { visible: modelData.status === "open" && modelData.suggestion; text: "应用建议"; onClicked: backend.acceptIssue(modelData.id) }
                                             Button { visible: modelData.status === "open"; text: "已检查"; onClicked: backend.resolveIssue(modelData.id, "resolved") }
                                            Button { visible: modelData.status === "open"; text: "忽略"; flat: true; onClicked: backend.resolveIssue(modelData.id, "dismissed") }
                                        }
                                    }
                                }
                                Label { visible: backend.issues.length === 0; text: "当前没有质量问题。深度审校不会自动运行。"; opacity: .55 }
                            }
                        }

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 14
                                Label { text: "模型用量与费用"; font.pixelSize: 19; font.bold: true }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Repeater {
                                        model: [
                                            {label:"输入 token", value:(backend.usage.total ? backend.usage.total.prompt_tokens : 0)},
                                            {label:"输出 token", value:(backend.usage.total ? backend.usage.total.completion_tokens : 0)},
                                            {label:"缓存命中", value:(backend.usage.total ? backend.usage.total.cache_hit_tokens : 0)},
                                            {label:"实际调用", value:(backend.usage.total ? backend.usage.total.calls : 0)},
                                            {label:"重试", value:(backend.usage.retries || 0)}
                                        ]
                                        Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 86; radius: 10; color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                                            Column { anchors.centerIn: parent; spacing: 6; Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.value; font.bold: true; font.pixelSize: 20 } Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; opacity: .5 } }
                                        }
                                    }
                                }
                                Label {
                                    text: "重试请求消耗：" + (backend.usage.retry_usage ? (backend.usage.retry_usage.prompt_tokens + backend.usage.retry_usage.completion_tokens) : 0) + " token · " + (backend.usage.retry_usage && backend.usage.retry_usage.cost !== null && backend.usage.retry_usage.cost !== undefined ? Number(backend.usage.retry_usage.cost).toFixed(4) + " " + backend.selectedJob.currency : "费用未配置")
                                    opacity: .6
                                }
                                Label { text: "按阶段和实际模型"; font.bold: true }
                                Repeater {
                                    model: backend.usage.by_stage_model || []
                                    Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 58; radius: 8; color: darkMode ? "#24211e" : "#fffdf9"
                                        RowLayout { anchors.fill: parent; anchors.margins: 12
                                            Label { text: stageText(modelData.stage); font.bold: true; Layout.preferredWidth: 150 }
                                            Label { text: modelData.model; Layout.fillWidth: true }
                                            Label { text: (modelData.prompt_tokens + modelData.completion_tokens) + " tok"; Layout.preferredWidth: 120 }
                                            Label { text: modelData.cost === null || modelData.cost === undefined ? "价格未配置" : Number(modelData.cost).toFixed(4) + " " + backend.selectedJob.currency; opacity: .65; Layout.preferredWidth: 140 }
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
                                    Label { text: "成品与中间产物"; font.pixelSize: 19; font.bold: true }
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
                                        text: "重新导出"
                                        enabled: Number(backend.selectedJob.completed_segments || 0) > 0
                                        onClicked: backend.reExport(backend.selectedJob.id, reExportFormat.currentValue)
                                    }
                                }
                                Repeater {
                                    model: backend.artifacts
                                    Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 72; radius: 10; color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                                        RowLayout { anchors.fill: parent; anchors.margins: 12
                                            Label { text: modelData.format.toUpperCase(); color: "#c86a3b"; font.bold: true; Layout.preferredWidth: 80 }
                                            Label { text: modelData.path; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                            Button { text: "打开"; onClicked: backend.openPath(modelData.path) }
                                            Button { text: "所在目录"; flat: true; onClicked: backend.openContainingFolder(modelData.path) }
                                        }
                                    }
                                }
                                Label { visible: backend.artifacts.length === 0; text: "翻译完成后会自动生成设置中的输出格式。"; opacity: .55 }
                            }
                        }

                        ScrollView {
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 7
                                RowLayout { Layout.fillWidth: true; Label { text: "任务日志"; font.pixelSize: 19; font.bold: true } Item { Layout.fillWidth: true } Button { text: "立即停止 Worker"; flat: true; onClicked: backend.forceStopJob(backend.selectedJob.id) } }
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
                                                ToolButton { text: expanded ? "收起" : "详情"; onClicked: expanded = !expanded }
                                            }
                                            Label {
                                                visible: expanded
                                                Layout.fillWidth: true
                                                text: JSON.stringify(modelData.payload, null, 2)
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
                    Label { text: "设置"; font.pixelSize: 28; font.bold: true }
                    Label { text: "连接与本地依赖"; font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: settingsColumn.implicitHeight + 36; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        ColumnLayout {
                            id: settingsColumn
                            anchors.fill: parent; anchors.margins: 18; spacing: 12
                            Label { text: "模型 API Key"; font.bold: true }
                            RowLayout { Layout.fillWidth: true
                                TextField { id: apiKey; Layout.fillWidth: true; echoMode: TextInput.Password; placeholderText: "保存在 Windows 凭据管理器，不写入项目" }
                                Button { text: "保存"; enabled: apiKey.text.length > 0; onClicked: { backend.saveApiKey("deepseek-default", apiKey.text); apiKey.clear() } }
                            }
                            Label { text: "模型服务"; font.bold: true }
                            RowLayout {
                                Layout.fillWidth: true
                                ComboBox {
                                    id: modelProvider
                                    Layout.preferredWidth: 190
                                    textRole: "label"; valueRole: "value"
                                    model: [
                                        {label:"DeepSeek", value:"deepseek"},
                                        {label:"OpenAI 兼容", value:"openai"},
                                        {label:"Ollama 本地", value:"ollama"},
                                        {label:"vLLM 本地", value:"vllm"}
                                    ]
                                    currentIndex: doctorResult.model_profile && doctorResult.model_profile.provider === "ollama" ? 2 : doctorResult.model_profile && doctorResult.model_profile.provider === "vllm" ? 3 : doctorResult.model_profile && doctorResult.model_profile.provider === "openai" ? 1 : 0
                                }
                                TextField {
                                    id: modelBaseUrl
                                    Layout.fillWidth: true
                                    placeholderText: "OpenAI 兼容接口地址"
                                    text: doctorResult.model_profile ? doctorResult.model_profile.base_url : "https://api.deepseek.com"
                                }
                            }
                            Label { text: "默认模型（翻译、译前准备、修复和主动审校）"; font.bold: true }
                            TextField {
                                id: modelName
                                Layout.fillWidth: true
                                text: doctorResult.model_profile ? doctorResult.model_profile.translation_model : "deepseek-v4-flash"
                            }
                            Label { text: "每百万 token 单价"; font.bold: true }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField { id: inputPrice; Layout.fillWidth: true; placeholderText: "未缓存输入"; text: doctorResult.model_profile ? doctorResult.model_profile.input_price_per_million : "0.22" }
                                TextField { id: cachedPrice; Layout.fillWidth: true; placeholderText: "缓存命中输入"; text: doctorResult.model_profile ? doctorResult.model_profile.cached_input_price_per_million : "0.007" }
                                TextField { id: outputPrice; Layout.fillWidth: true; placeholderText: "输出"; text: doctorResult.model_profile ? doctorResult.model_profile.output_price_per_million : "0.66" }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                TextField { id: priceCurrency; Layout.preferredWidth: 120; placeholderText: "币种"; text: doctorResult.model_profile ? doctorResult.model_profile.currency : "USD" }
                                TextField { id: priceDate; Layout.fillWidth: true; placeholderText: "生效日期"; text: doctorResult.model_profile ? doctorResult.model_profile.price_effective_date : "2026-08-16" }
                                Button {
                                    text: "保存模型设置"
                                    onClicked: backend.saveModelSettings(modelProvider.currentValue, modelBaseUrl.text, modelName.text, inputPrice.text, cachedPrice.text, outputPrice.text, priceCurrency.text, priceDate.text)
                                }
                            }
                            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; opacity: .5; text: "默认按官方峰谷规则计费；任务创建后会保存配置快照，之后改设置不会改动旧任务。" }
                            Label { text: "Calibre ebook-convert"; font.bold: true }
                            RowLayout { Layout.fillWidth: true
                                TextField { Layout.fillWidth: true; readOnly: true; text: doctorResult.calibre && doctorResult.calibre.path ? doctorResult.calibre.path : "未找到；MOBI/AZW3 导入前需要配置" }
                                Button { text: "选择路径"; onClicked: calibreDialog.open() }
                            }
                            Label { text: "工作区"; font.bold: true }
                            TextField { Layout.fillWidth: true; readOnly: true; text: doctorResult.workspace || "" }
                        }
                    }
                    Label { text: "外观"; font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 78; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        RowLayout { anchors.fill: parent; anchors.margins: 18
                            Label { text: "深色模式"; Layout.fillWidth: true }
                            Switch { checked: darkMode; onToggled: darkMode = checked }
                        }
                    }
                    Label { text: "任务并发"; font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: 92; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        RowLayout { anchors.fill: parent; anchors.margins: 18
                            ColumnLayout { Layout.fillWidth: true
                                Label { text: "同时运行的书籍数"; font.bold: true }
                                Label { text: "默认一次一本；单本内部仍按稳妥加速并发。"; opacity: .5 }
                            }
                            SpinBox {
                                id: activeTaskLimit
                                from: 1; to: 4; value: doctorResult.active_task_limit || 1
                                onValueModified: backend.saveActiveTaskLimit(value)
                            }
                        }
                    }
                    Label { text: "环境检查"; font.pixelSize: 18; font.bold: true }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: doctorColumn.implicitHeight + 34; radius: 12
                        color: darkMode ? "#24211e" : "#fffdf9"; border.color: darkMode ? "#39332e" : "#e5ddd2"
                        ColumnLayout { id: doctorColumn; anchors.fill: parent; anchors.margins: 17
                            Label { text: "核心依赖：" + (doctorResult.ok ? "正常" : "有缺失"); color: doctorResult.ok ? "#4d9b69" : "#d46b62" }
                            Label { text: "DeepSeek API Key：" + (doctorResult.deepseek_api_key && doctorResult.deepseek_api_key.available ? "已配置" : "未配置") }
                            Label { text: "Calibre：" + (doctorResult.calibre && doctorResult.calibre.available ? "可用" : "未配置") }
                            RowLayout {
                                Button { text: "重新检查"; onClicked: doctorResult = backend.doctor() }
                                Button { text: "测试模型连接"; onClicked: backend.testModelConnection() }
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
        if (backend.firstRun) firstRunDialog.open()
    }
}
