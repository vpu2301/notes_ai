import { useCallback, useEffect, useRef, useState } from "react";
import { messageFor } from "./errorCopy";
import type { ChannelLayout } from "../api/types";

export const LEVEL_BARS = 28;

export interface RecordedAudio {
  blob: Blob;
  filename: string;
  /** `mic_system` when the file carries the microphone on L and the tab audio on R; omitted = mono. */
  channelLayout?: ChannelLayout;
  /** When Record was clicked (ISO 8601, this browser's clock). */
  recordPressedAt?: string;
  /** ms from the click to the first audio the recorder wrote. */
  firstFrameOffsetMs?: number;
}

export interface RecorderOptions {
  /** Also capture tab/screen audio as a second channel ("Me / Them"). */
  systemAudio?: boolean;
  /** The tab audio was wanted but the browser offered none: the recording went on with the microphone only. */
  onSystemAudioUnavailable?: () => void;
}

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

/** Which layout a recording gets, and whether that is a step down. Pure. */
export function chooseLayout(
  systemAudioWanted: boolean,
  hasSystemTrack: boolean,
): { layout: ChannelLayout; fellBack: boolean } {
  if (systemAudioWanted && hasSystemTrack) return { layout: "mic_system", fellBack: false };
  return { layout: "mono", fellBack: systemAudioWanted };
}

/** Tab/system audio track or null. Chrome only offers tab audio with video, so video is asked for and stopped at once. */
async function acquireSystemAudio(): Promise<MediaStream | null> {
  const devices = navigator.mediaDevices as MediaDevices | undefined;
  if (!devices || typeof devices.getDisplayMedia !== "function") return null;
  let display: MediaStream;
  try {
    display = await devices.getDisplayMedia({ video: true, audio: true });
  } catch {
    return null;
  }
  display.getVideoTracks().forEach((t) => {
    t.stop();
    display.removeTrack(t);
  });
  const audio = display.getAudioTracks();
  if (audio.length === 0) return null;
  return new MediaStream(audio);
}

/** The longest offset the server accepts (10 minutes). */
export const MAX_FIRST_FRAME_OFFSET_MS = 600_000;

/** Capture timing: wall clock for the click, monotonic for the distance. No first frame → no offset. */
export function captureTiming(
  pressedWallMs: number,
  pressedPerfMs: number,
  firstFramePerfMs: number | null,
): { recordPressedAt: string; firstFrameOffsetMs?: number } {
  const recordPressedAt = new Date(pressedWallMs).toISOString();
  if (firstFramePerfMs == null) return { recordPressedAt };
  const offset = Math.round(firstFramePerfMs - pressedPerfMs);
  return {
    recordPressedAt,
    firstFrameOffsetMs: Math.min(MAX_FIRST_FRAME_OFFSET_MS, Math.max(0, offset)),
  };
}

/** Microphone recorder with a rolling level strip and an elapsed timer. */
export function useRecorder(
  onDone: (audio: RecordedAudio) => void,
  onError: (msg: string) => void,
  options: RecorderOptions = {},
) {
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  // null until the recorder has written its first audio.
  const [firstFrameOffsetMs, setFirstFrameOffsetMs] = useState<number | null>(null);
  const [levels, setLevels] = useState<number[]>(() => Array(LEVEL_BARS).fill(0));

  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const systemStream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const raf = useRef(0);
  const timer = useRef(0);
  // Read at Record time, so a toggled option never re-creates `start`.
  const opts = useRef(options);
  opts.current = options;

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current);
    window.clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    systemStream.current?.getTracks().forEach((t) => t.stop());
    systemStream.current = null;
    void audioCtx.current?.close().catch(() => undefined);
    audioCtx.current = null;
    recorder.current = null;
    setLevels(Array(LEVEL_BARS).fill(0));
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    // Stamped before permission prompts and the picker: that gap is lost speech.
    const pressedWall = Date.now();
    const pressedPerf = performance.now();
    let firstFramePerf: number | null = null;
    const firstFrame = () => {
      if (firstFramePerf !== null) return;
      firstFramePerf = performance.now();
      setFirstFrameOffsetMs(captureTiming(pressedWall, pressedPerf, firstFramePerf).firstFrameOffsetMs ?? 0);
    };
    setFirstFrameOffsetMs(null);
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.current = media;

      const wantSystem = opts.current.systemAudio === true;
      const system = wantSystem ? await acquireSystemAudio() : null;
      systemStream.current = system;
      const { layout, fellBack } = chooseLayout(wantSystem, system !== null);
      if (fellBack) opts.current.onSystemAudioUnavailable?.();

      const ctx = new AudioContext();
      audioCtx.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      // The level strip always shows the microphone — the author's side.
      const micSource = ctx.createMediaStreamSource(media);
      micSource.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) {
          const c = (v - 128) / 128;
          sum += c * c;
        }
        const rms = Math.min(1, Math.sqrt(sum / buf.length) * 3);
        setLevels((prev) => [...prev.slice(1), rms]);
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);

      // `mic_system`: mic → L (input 0), tab → R (input 1), one 2-channel stream.
      let recorded = media;
      if (system) {
        const mono = () => {
          const g = ctx.createGain();
          g.channelCount = 1;
          g.channelCountMode = "explicit";
          return g;
        };
        const merger = ctx.createChannelMerger(2);
        micSource.connect(mono()).connect(merger, 0, 0);
        ctx.createMediaStreamSource(system).connect(mono()).connect(merger, 0, 1);
        const dest = ctx.createMediaStreamDestination();
        dest.channelCount = 2;
        merger.connect(dest);
        recorded = dest.stream;
      }

      const mimeType = pickMimeType();
      const rec = new MediaRecorder(recorded, mimeType ? { mimeType } : undefined);
      const chunks: BlobPart[] = [];
      // `start` marks the first frame; the first chunk (a timeslice later) is only the fallback.
      rec.onstart = firstFrame;
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) {
          firstFrame();
          chunks.push(e.data);
        }
      };
      rec.onstop = () => {
        const type = rec.mimeType || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : "webm";
        const blob = new Blob(chunks, { type });
        cleanup();
        setRecording(false);
        if (blob.size === 0) {
          onError("The recording came out empty — check the microphone.");
          return;
        }
        onDone({
          blob,
          filename: `meeting-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.${ext}`,
          channelLayout: layout,
          ...captureTiming(pressedWall, pressedPerf, firstFramePerf),
        });
      };
      recorder.current = rec;
      rec.start(1000);

      const startedAt = Date.now();
      setElapsedMs(0);
      timer.current = window.setInterval(() => setElapsedMs(Date.now() - startedAt), 250);
      setRecording(true);
    } catch (err) {
      cleanup();
      onError(
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Microphone access was denied — allow it in the browser and try again."
          : messageFor(err),
      );
    }
  }, [cleanup, onDone, onError]);

  const stop = useCallback(() => {
    recorder.current?.stop();
  }, []);

  return { recording, elapsedMs, firstFrameOffsetMs, levels, start, stop };
}
