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
        ),
        // IDX-M1. Tests link the executable target directly (supported since
        // Swift 5.5): the session, the transport and the capture-safety
        // rules are worth exercising, and splitting the app into a library
        // to test them would move every file for no other reason.
        .testTarget(
            name: "NotesAICaptureTests",
            dependencies: ["NotesAICapture"],
            path: "Tests/NotesAICaptureTests"
        ),
    ]
)
