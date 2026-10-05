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
        // Tests link the executable target directly (Swift 5.5+) rather than
        // splitting the app into a library.
        .testTarget(
            name: "NotesAICaptureTests",
            dependencies: ["NotesAICapture"],
            path: "Tests/NotesAICaptureTests"
        ),
    ]
)
