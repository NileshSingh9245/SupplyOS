"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import { api, apiError } from "@/lib/api";

export interface DeliveryProof {
  id: string;
  delivery_id: string;
  kind: "signature" | "photo";
  mime: string;
  size: number;
  url: string;
}

export function privateProofPath(reference: string): string | null {
  const match = /^\/api\/v1\/delivery-proofs\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.exec(reference);
  return match ? `/delivery-proofs/${match[1]}` : null;
}

export function ProofPreview({ reference, label }: { reference: string; label: string }) {
  const path = privateProofPath(reference);
  const proof = useQuery({
    queryKey: ["delivery-proof", reference], enabled: !!path,
    retry: false, gcTime: 0,
    queryFn: async ({ signal }) => {
      if (!path) throw new Error("Only private uploaded proof references are supported.");
      const { data } = await api.get<Blob>(path, { responseType: "blob", signal });
      if (!["image/png", "image/jpeg"].includes(data.type)) throw new Error("Proof response is not a PNG or JPEG image.");
      return data;
    },
  });
  const [source, setSource] = useState<{ blob: Blob; url: string } | null>(null);
  useEffect(() => {
    if (!proof.data) return;
    const url = URL.createObjectURL(proof.data);
    // Publish this external resource only after allocation; cleanup revokes it on identity changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSource({ blob: proof.data, url });
    return () => URL.revokeObjectURL(url);
  }, [proof.data]);
  const url = source?.blob === proof.data ? source?.url : null;

  return (
    <div className="pane p-3 space-y-2" data-testid={`proof-preview-${label.toLowerCase()}`}>
      <p className="data-label">{label} / authenticated preview</p>
      {!path ? <p role="alert">Only private uploaded proof references are supported.</p> : proof.error ? (
        <p role="alert">{apiError(proof.error)} <button className="btn-ghost" onClick={() => void proof.refetch()}>Retry preview</button></p>
      ) : url ? <Image unoptimized src={url} width={960} height={320} alt={`${label} proof of delivery`} className="w-full max-h-48 object-contain" /> : <p role="status">Loading proof...</p>}
    </div>
  );
}

export function SignaturePad({ disabled, onCapture }: { disabled: boolean; onCapture: (canvas: HTMLCanvasElement) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const point = useRef<{ x: number; y: number; pointer: number } | null>(null);
  const [hasInk, setHasInk] = useState(false);
  useEffect(() => {
    const context = canvas.current?.getContext("2d");
    if (context) { context.fillStyle = "#ffffff"; context.fillRect(0, 0, 960, 320); }
  }, []);

  function draw(event: PointerEvent<HTMLCanvasElement>) {
    if (disabled || (!point.current && event.type !== "pointerdown") || (event.type === "pointerdown" && event.button !== 0)) return;
    const element = event.currentTarget;
    const bounds = element.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * element.width / bounds.width;
    const y = (event.clientY - bounds.top) * element.height / bounds.height;
    const context = element.getContext("2d");
    if (!context || (point.current && point.current.pointer !== event.pointerId)) return;
    event.preventDefault();
    context.strokeStyle = "#111111";
    context.fillStyle = "#111111";
    context.lineWidth = 3;
    context.lineCap = "round";
    context.beginPath();
    if (event.type === "pointerdown") {
      element.setPointerCapture(event.pointerId);
      context.arc(x, y, 1.5, 0, Math.PI * 2);
      context.fill();
      setHasInk(true);
    } else if (point.current) {
      context.moveTo(point.current.x, point.current.y);
      context.lineTo(x, y);
      context.stroke();
    }
    point.current = { x, y, pointer: event.pointerId };
  }

  return (
    <div className="space-y-2">
      <p id="signature-help" className="text-xs text-text-secondary">Draw the recipient signature below, then upload it as a private PNG. Image upload is also available.</p>
      <canvas ref={canvas} width={960} height={320} className="w-full h-auto border border-border bg-white touch-none" aria-label="Draw recipient signature" aria-describedby="signature-help" data-testid="signature-canvas" onPointerDown={draw} onPointerMove={draw} onPointerUp={() => { point.current = null; }} onPointerCancel={() => { point.current = null; }} onLostPointerCapture={() => { point.current = null; }} />
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" disabled={disabled || !hasInk} data-testid="signature-clear" onClick={() => {
          const context = canvas.current?.getContext("2d");
          if (context) { context.fillStyle = "#ffffff"; context.fillRect(0, 0, 960, 320); }
          point.current = null; setHasInk(false);
        }}>Clear signature</button>
        <button type="button" className="btn-volt" disabled={disabled || !hasInk} data-testid="signature-upload" onClick={() => { if (canvas.current) onCapture(canvas.current); }}>Upload drawn signature</button>
      </div>
    </div>
  );
}
