import AVFoundation
import CoreAudio
import Foundation

// The call audio: a Core Audio process tap (macOS 14.2+) of every process EXCEPT
// this one, attached to a private aggregate device that also holds the default
// input, with drift compensation — so microphone and call audio arrive in ONE
// IO callback on ONE clock, sample-aligned (two engines drift apart over an hour).
// ScreenCaptureKit audio-only is the documented fallback; not built.

/// What the recorder needs from a microphone + call-audio source; a protocol so the rules can be tested with a fake.
protocol SystemAudioSource: AnyObject {
    /// Both streams of one IO cycle, mono Float32, same rate and frame count. `system` nil = tap did not deliver (silence written). Called on an audio queue.
    var onBuffers: ((_ mic: AVAudioPCMBuffer, _ system: AVAudioPCMBuffer?) -> Void)? { get set }
    /// The default input or output device changed and the source rebuilt itself.
    var onDeviceChange: (() -> Void)? { get set }
    /// The source stopped for good (a rebuild failed); no more buffers come.
    var onFailure: ((Error) -> Void)? { get set }
    /// Start delivering. Returns the device-side format (all channels).
    func start() throws -> AudioStreamBasicDescription
    func stop()
}

enum SystemAudioError: LocalizedError, Equatable {
    case unsupportedOS
    case noInputDevice
    /// `AudioHardwareCreateProcessTap` refused — typically the "System Audio Recording" permission is off.
    case tapFailed(OSStatus)
    case aggregateFailed(OSStatus)
    case ioFailed(OSStatus)
    case unexpectedFormat

    var errorDescription: String? {
        switch self {
        case .unsupportedOS: return "Recording call audio needs macOS 14.2 or later."
        case .noInputDevice: return "No microphone to record alongside the call audio."
        case .tapFailed: return "Call audio permission is off for Notes AI Capture."
        case .aggregateFailed, .ioFailed, .unexpectedFormat:
            return "Call audio could not be recorded on this Mac."
        }
    }
}

/// The Core Audio process tap + private aggregate device.
@available(macOS 14.2, *)
final class SystemAudioTap: SystemAudioSource, @unchecked Sendable {
    /// Every aggregate device this app creates has this UID prefix, so one left by a crash can be removed.
    static let uidPrefix = "ai.notes.capture.aggregate."
    static let deviceName = "Notes AI Capture (call audio)"

    var onBuffers: ((_ mic: AVAudioPCMBuffer, _ system: AVAudioPCMBuffer?) -> Void)? {
        get { callbacks.withLock { $0.buffers } }
        set { callbacks.withLock { $0.buffers = newValue } }
    }
    var onDeviceChange: (() -> Void)? {
        get { callbacks.withLock { $0.deviceChange } }
        set { callbacks.withLock { $0.deviceChange = newValue } }
    }
    var onFailure: ((Error) -> Void)? {
        get { callbacks.withLock { $0.failure } }
        set { callbacks.withLock { $0.failure = newValue } }
    }

    private struct Callbacks {
        var buffers: ((AVAudioPCMBuffer, AVAudioPCMBuffer?) -> Void)?
        var deviceChange: (() -> Void)?
        var failure: ((Error) -> Void)?
    }
    private let callbacks = Locked(Callbacks())

    /// Serializes start/stop/rebuild. The IO block runs on `ioQueue`.
    private let controlQueue = DispatchQueue(label: "ai.notes.capture.tap.control")
    private let ioQueue = DispatchQueue(label: "ai.notes.capture.tap.io", qos: .userInteractive)

    // All below: touched on controlQueue only.
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var tapUUID = UUID()
    private var aggregateID = AudioObjectID(kAudioObjectUnknown)
    private var ioProcID: AudioDeviceIOProcID?
    private var running = false
    private var pendingRebuild: DispatchWorkItem?
    private var listeners: [(AudioObjectPropertyAddress, AudioObjectPropertyListenerBlock)] = []
    /// Read by the IO block; set before each IO start.
    private let layout = Locked(StreamLayout(micChannels: 1, sampleRate: 48_000))

    struct StreamLayout {
        var micChannels: Int
        var sampleRate: Double
    }

    init() {}

    deinit {
        // stop() is the contract; this is the safety net for a leak.
        if running { teardownAll() }
    }

    // MARK: - Lifecycle

    func start() throws -> AudioStreamBasicDescription {
        try controlQueue.sync {
            guard !running else { throw SystemAudioError.ioFailed(kAudioHardwareIllegalOperationError) }
            Self.removeOrphanAggregateDevices()
            try createTap()
            do {
                let format = try buildAggregate()
                running = true
                addDeviceListeners()
                return format
            } catch {
                teardownAll()
                throw error
            }
        }
    }

    func stop() {
        controlQueue.sync {
            guard running || tapID != kAudioObjectUnknown else { return }
            teardownAll()
        }
    }

    private func teardownAll() {
        running = false
        pendingRebuild?.cancel()
        pendingRebuild = nil
        removeDeviceListeners()
        teardownAggregate()
        if tapID != kAudioObjectUnknown {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID(kAudioObjectUnknown)
        }
    }

    // MARK: - The tap

    private func createTap() throws {
        // Exclude this process: whatever the app plays is not the meeting.
        let own = HAL.processObject(pid: ProcessInfo.processInfo.processIdentifier)
        let description = CATapDescription(stereoGlobalTapButExcludeProcesses: own.map { [$0] } ?? [])
        tapUUID = UUID()
        description.uuid = tapUUID
        description.name = Self.deviceName
        // Private: dies with this process, never visible to other apps.
        description.isPrivate = true
        // The person still hears the call.
        description.muteBehavior = .unmuted
        var id = AudioObjectID(kAudioObjectUnknown)
        let status = AudioHardwareCreateProcessTap(description, &id)
        guard status == noErr, id != kAudioObjectUnknown else { throw SystemAudioError.tapFailed(status) }
        tapID = id
    }

    // MARK: - The aggregate device

    /// Build the aggregate (default input + tap), start IO and return its input format.
    @discardableResult
    private func buildAggregate() throws -> AudioStreamBasicDescription {
        guard let input = HAL.defaultInputDevice(), let inputUID = HAL.deviceUID(input) else {
            throw SystemAudioError.noInputDevice
        }
        let micChannels = HAL.inputChannelCount(input)
        guard micChannels > 0 else { throw SystemAudioError.noInputDevice }

        let description: [String: Any] = [
            kAudioAggregateDeviceNameKey: Self.deviceName,
            kAudioAggregateDeviceUIDKey: Self.uidPrefix + UUID().uuidString,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            // The microphone is the clock; the tap is resampled onto it.
            kAudioAggregateDeviceMainSubDeviceKey: inputUID,
            kAudioAggregateDeviceClockDeviceKey: inputUID,
            // Do NOT wait for a tapped process to play: the microphone must record from the first second.
            kAudioAggregateDeviceTapAutoStartKey: false,
            kAudioAggregateDeviceSubDeviceListKey: [
                [kAudioSubDeviceUIDKey: inputUID, kAudioSubDeviceDriftCompensationKey: false],
            ],
            kAudioAggregateDeviceTapListKey: [
                [kAudioSubTapUIDKey: tapUUID.uuidString, kAudioSubTapDriftCompensationKey: true],
            ],
        ]
        var aggregate = AudioObjectID(kAudioObjectUnknown)
        var status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &aggregate)
        guard status == noErr, aggregate != kAudioObjectUnknown else {
            throw SystemAudioError.aggregateFailed(status)
        }
        aggregateID = aggregate

        guard let format = HAL.inputStreamFormat(aggregate),
              format.mFormatID == kAudioFormatLinearPCM,
              format.mFormatFlags & kAudioFormatFlagIsFloat != 0,
              format.mBitsPerChannel == 32
        else {
            teardownAggregate()
            throw SystemAudioError.unexpectedFormat
        }
        let rate = HAL.nominalSampleRate(aggregate) ?? format.mSampleRate
        layout.withLock { $0 = StreamLayout(micChannels: micChannels, sampleRate: rate) }

        var procID: AudioDeviceIOProcID?
        status = AudioDeviceCreateIOProcIDWithBlock(&procID, aggregate, ioQueue) { [weak self] _, input, _, _, _ in
            self?.deliver(input)
        }
        guard status == noErr, let procID else {
            teardownAggregate()
            throw SystemAudioError.ioFailed(status)
        }
        ioProcID = procID
        status = AudioDeviceStart(aggregate, procID)
        guard status == noErr else {
            teardownAggregate()
            throw SystemAudioError.ioFailed(status)
        }
        var result = format
        result.mSampleRate = rate
        return result
    }

    private func teardownAggregate() {
        if aggregateID != kAudioObjectUnknown {
            if let ioProcID {
                AudioDeviceStop(aggregateID, ioProcID)
                AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
            }
            AudioHardwareDestroyAggregateDevice(aggregateID)
        }
        ioProcID = nil
        aggregateID = AudioObjectID(kAudioObjectUnknown)
    }

    // MARK: - IO

    /// Split one cycle's input into microphone (channel 0 of the input sub-device) and call audio (the tap's stereo pair, mixed to mono).
    private func deliver(_ inputData: UnsafePointer<AudioBufferList>) {
        guard let handler = callbacks.withLock({ $0.buffers }) else { return }
        let layout = self.layout.withLock { $0 }
        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inputData))
        guard let split = InputSplitter.split(buffers: buffers, micChannels: layout.micChannels) else { return }
        guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: layout.sampleRate,
                                         channels: 1, interleaved: false),
              let mic = AVAudioPCMBuffer.mono(split.mic, format: format)
        else { return }
        handler(mic, split.system.flatMap { AVAudioPCMBuffer.mono($0, format: format) })
    }

    // MARK: - Device changes

    private func addDeviceListeners() {
        for selector in [kAudioHardwarePropertyDefaultInputDevice, kAudioHardwarePropertyDefaultOutputDevice] {
            var address = AudioObjectPropertyAddress(mSelector: selector,
                                                     mScope: kAudioObjectPropertyScopeGlobal,
                                                     mElement: kAudioObjectPropertyElementMain)
            let block: AudioObjectPropertyListenerBlock = { [weak self] _, _ in
                self?.scheduleRebuild()
            }
            if AudioObjectAddPropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &address,
                                                   controlQueue, block) == noErr {
                listeners.append((address, block))
            }
        }
    }

    private func removeDeviceListeners() {
        for (address, block) in listeners {
            var address = address
            AudioObjectRemovePropertyListenerBlock(AudioObjectID(kAudioObjectSystemObject), &address,
                                                   controlQueue, block)
        }
        listeners.removeAll()
    }

    /// A device change arrives as a burst of notifications; wait for it to settle, then rebuild once.
    private func scheduleRebuild() {
        pendingRebuild?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.rebuild() }
        pendingRebuild = work
        controlQueue.asyncAfter(deadline: .now() + .milliseconds(250), execute: work)
    }

    private func rebuild() {
        guard running else { return }
        teardownAggregate()
        do {
            try buildAggregate()
            callbacks.withLock { $0.deviceChange }?()
        } catch {
            teardownAll()
            callbacks.withLock { $0.failure }?(error)
        }
    }

    // MARK: - Orphans

    /// Remove aggregate devices a previous run left behind (crash between create and destroy). Called at launch and before each start.
    static func removeOrphanAggregateDevices() {
        for device in HAL.allDevices() {
            guard let uid = HAL.deviceUID(device), uid.hasPrefix(uidPrefix) else { continue }
            AudioHardwareDestroyAggregateDevice(device)
        }
    }
}

/// The pure part of the IO block: which channels are the microphone and which the call audio.
enum InputSplitter {
    struct Split {
        var mic: [Float]
        /// Nil when the tap's channels are missing from this cycle.
        var system: [Float]?
    }

    /// `buffers` are the aggregate's interleaved Float32 input streams: channel 0 the microphone, the two after `micChannels` the tap (L, R), mixed to mono.
    static func split(buffers: UnsafeMutableAudioBufferListPointer, micChannels: Int) -> Split? {
        var channels: [(data: UnsafePointer<Float>, stride: Int)] = []
        var frames = Int.max
        for buffer in buffers {
            let count = Int(buffer.mNumberChannels)
            guard count > 0, let data = buffer.mData else { continue }
            let perChannel = Int(buffer.mDataByteSize) / (MemoryLayout<Float>.size * count)
            frames = min(frames, perChannel)
            let base = data.assumingMemoryBound(to: Float.self)
            for c in 0..<count { channels.append((UnsafePointer(base + c), count)) }
        }
        guard !channels.isEmpty, frames != .max, frames > 0 else { return nil }
        func read(_ index: Int) -> [Float] {
            let channel = channels[index]
            return (0..<frames).map { channel.data[$0 * channel.stride] }
        }
        let mic = read(0)
        let left = micChannels, right = micChannels + 1
        guard channels.count > left else { return Split(mic: mic, system: nil) }
        let l = read(left)
        guard channels.count > right else { return Split(mic: mic, system: l) }
        let r = read(right)
        return Split(mic: mic, system: zip(l, r).map { ($0 + $1) * 0.5 })
    }
}

extension AVAudioPCMBuffer {
    /// A mono buffer holding `samples`.
    static func mono(_ samples: [Float], format: AVAudioFormat) -> AVAudioPCMBuffer? {
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(max(samples.count, 1))),
              let channel = buffer.floatChannelData?[0]
        else { return nil }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { source in
            if let base = source.baseAddress { channel.update(from: base, count: samples.count) }
        }
        return buffer
    }
}

/// A value behind a lock.
final class Locked<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) { self.value = value }

    func withLock<T>(_ body: (inout Value) throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try body(&value)
    }
}

// MARK: - HAL helpers

/// The few Core Audio property reads the tap needs.
enum HAL {
    private static func address(_ selector: AudioObjectPropertySelector,
                                scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal)
        -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    }

    static func defaultInputDevice() -> AudioObjectID? {
        var address = address(kAudioHardwarePropertyDefaultInputDevice)
        var device = AudioObjectID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil,
                                                &size, &device)
        return status == noErr && device != kAudioObjectUnknown ? device : nil
    }

    static func deviceUID(_ device: AudioObjectID) -> String? {
        var address = address(kAudioDevicePropertyDeviceUID)
        var uid: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let status = withUnsafeMutablePointer(to: &uid) {
            AudioObjectGetPropertyData(device, &address, 0, nil, &size, $0)
        }
        guard status == noErr, let uid else { return nil }
        return uid.takeRetainedValue() as String
    }

    static func allDevices() -> [AudioObjectID] {
        var address = address(kAudioHardwarePropertyDevices)
        var size: UInt32 = 0
        let system = AudioObjectID(kAudioObjectSystemObject)
        guard AudioObjectGetPropertyDataSize(system, &address, 0, nil, &size) == noErr, size > 0 else { return [] }
        var devices = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(system, &address, 0, nil, &size, &devices) == noErr else { return [] }
        return devices
    }

    /// The HAL's process object for `pid`, or nil if it has none.
    static func processObject(pid: pid_t) -> AudioObjectID? {
        var address = address(kAudioHardwarePropertyTranslatePIDToProcessObject)
        var pid = pid
        var object = AudioObjectID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address,
                                                UInt32(MemoryLayout<pid_t>.size), &pid, &size, &object)
        return status == noErr && object != kAudioObjectUnknown ? object : nil
    }

    static func inputChannelCount(_ device: AudioObjectID) -> Int {
        var address = address(kAudioDevicePropertyStreamConfiguration, scope: kAudioObjectPropertyScopeInput)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size),
                                                   alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, raw) == noErr else { return 0 }
        let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
        return list.reduce(0) { $0 + Int($1.mNumberChannels) }
    }

    /// The virtual format of the device's first input stream.
    static func inputStreamFormat(_ device: AudioObjectID) -> AudioStreamBasicDescription? {
        var address = address(kAudioDevicePropertyStreams, scope: kAudioObjectPropertyScopeInput)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr, size > 0 else { return nil }
        var streams = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, &streams) == noErr,
              let first = streams.first
        else { return nil }
        var formatAddress = self.address(kAudioStreamPropertyVirtualFormat)
        var format = AudioStreamBasicDescription()
        var formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        guard AudioObjectGetPropertyData(first, &formatAddress, 0, nil, &formatSize, &format) == noErr else {
            return nil
        }
        return format
    }

    static func nominalSampleRate(_ device: AudioObjectID) -> Double? {
        var address = address(kAudioDevicePropertyNominalSampleRate)
        var rate: Float64 = 0
        var size = UInt32(MemoryLayout<Float64>.size)
        guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, &rate) == noErr, rate > 0 else {
            return nil
        }
        return rate
    }
}
