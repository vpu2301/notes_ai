// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "NotesAICapture",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .executableTarget(
            name: "NotesAICapture",
            path: "Sources/NotesAICapture"
        )
    ]
)
