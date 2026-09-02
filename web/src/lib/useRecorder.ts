import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../api/http";

export const LEVEL_BARS = 28;

export interface RecordedAudio {
  blob: Blob;
  filename: string;
}

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

/** Microphone recorder with a rolling level strip and an elapsed timer. */
export function useRecorder(onDone: (audio: RecordedAudio) => void, onError: (msg: string) => void) {
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [levels, setLevels] = useState<number[]>(() => Array(LEVEL_BARS).fill(0));

  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const raf = useRef(0);
  const timer = useRef(0);

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current);
    window.clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void audioCtx.current?.close().catch(() => undefined);
    audioCtx.current = null;
    recorder.current = null;
    setLevels(Array(LEVEL_BARS).fill(0));
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.current = media;

      const ctx = new AudioContext();
      audioCtx.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(media).connect(analyser);
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

      const mimeType = pickMimeType();
      const rec = new MediaRecorder(media, mimeType ? { mimeType } : undefined);
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
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
          : errorMessage(err),
      );
    }
  }, [cleanup, onDone, onError]);

  const stop = useCallback(() => {
    recorder.current?.stop();
  }, []);

  return { recording, elapsedMs, levels, start, stop };
}
