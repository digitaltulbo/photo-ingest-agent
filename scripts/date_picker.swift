import Cocoa

let formatter = DateFormatter()
formatter.dateFormat = "yyyy-MM-dd"

let defaultDate: Date
if CommandLine.arguments.count > 1, let parsed = formatter.date(from: CommandLine.arguments[1]) {
    defaultDate = parsed
} else {
    defaultDate = Date()
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
app.activate(ignoringOtherApps: true)

let picker = NSDatePicker(frame: NSRect(x: 0, y: 0, width: 260, height: 150))
picker.datePickerStyle = .clockAndCalendar
picker.datePickerElements = [.yearMonthDay]
picker.dateValue = defaultDate

let alert = NSAlert()
alert.messageText = "촬영 날짜를 선택하세요"
alert.informativeText = "선택한 날짜의 사진만 가져오고 컬링합니다."
alert.accessoryView = picker
alert.addButton(withTitle: "확인")
alert.addButton(withTitle: "취소")

let response = alert.runModal()
if response == .alertFirstButtonReturn {
    print(formatter.string(from: picker.dateValue))
} else {
    exit(1)
}
