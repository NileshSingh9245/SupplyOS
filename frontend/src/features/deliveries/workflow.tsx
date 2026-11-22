"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { moneyInput, type OrderFinance } from "@/lib/finance";
import { useIntentPost } from "@/lib/intent";
import { formatDateTime, formatINR } from "@/lib/utils";
import { Modal } from "@/components/modal";
import { OrderBalance } from "@/components/financial-summary";
import { privateProofPath, ProofPreview, SignaturePad, type DeliveryProof } from "./proof-capture";

export interface Delivery {
  id: string;
  order_id: string;
  partner_id: string | null;
  scheduled_date: string | null;
  priority: number;
  otp_verified: boolean;
  signature_url: string | null;
  proof_photo_url: string | null;
  cash_collected: string;
  upi_collected: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export function DeliveryWorkflow({ open, delivery, onClose, onRefresh, onCompleted }: {
  open: boolean;
  delivery: Delivery;
  onClose: () => void;
  onRefresh: () => Promise<unknown>;
  onCompleted: (result: Delivery) => void;
}) {
  const order = useQuery({
    queryKey: ["order", delivery.order_id], enabled: open, staleTime: 0,
    queryFn: async ({ signal }) => (await api.get<OrderFinance>(`/orders/${delivery.order_id}`, { signal })).data,
  });
  const mutation = useIntentPost();
  const actionActive = useRef(false);
  const [action, setAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [signature, setSignature] = useState("");
  const [photo, setPhoto] = useState("");
  const [cash, setCash] = useState("0.00");
  const [upi, setUpi] = useState("0.00");
  const signatureRef = signature || delivery.signature_url || "";
  const photoRef = photo || delivery.proof_photo_url || "";
  const busy = !!action || mutation.busy;
  const completed = !!delivery.completed_at;
  const cashAmount = moneyInput(cash);
  const upiAmount = moneyInput(upi);
  const canComplete = !completed && !!order.data && delivery.otp_verified && !!privateProofPath(signatureRef) && !!privateProofPath(photoRef) && cashAmount !== null && upiAmount !== null;

  async function run(name: "start" | "verify-otp") {
    if (actionActive.current || mutation.busy) return;
    actionActive.current = true; setAction(name); setActionError(null);
    try {
      await api.post(`/deliveries/${delivery.id}/${name}`, name === "verify-otp" ? { otp_code: otp } : undefined);
      await onRefresh();
      if (name === "verify-otp") setOtp("");
      toast.success(name === "start" ? "Delivery started." : "OTP verified.");
    } catch (error) { setActionError(apiError(error)); }
    finally { actionActive.current = false; setAction(null); }
  }

  async function upload(kind: "signature" | "photo", source: File | HTMLCanvasElement) {
    if (actionActive.current || mutation.busy) return;
    actionActive.current = true; setAction(kind); setActionError(null);
    try {
      const file = source instanceof HTMLCanvasElement ? await new Promise<File>((resolve, reject) => {
        source.toBlob((blob) => blob ? resolve(new File([blob], "signature.png", { type: "image/png" })) : reject(new Error("Signature could not be encoded.")), "image/png");
      }) : source;
      if (!["image/png", "image/jpeg"].includes(file.type) || file.size === 0 || file.size > 5 * 1024 * 1024) {
        throw new Error("Choose a PNG or JPEG image no larger than 5 MiB.");
      }
      const body = new FormData(); body.append("kind", kind); body.append("file", file);
      const { data } = await api.post<DeliveryProof>(`/deliveries/${delivery.id}/proofs`, body);
      if (data.delivery_id !== delivery.id || data.kind !== kind || !privateProofPath(data.url)) throw new Error("Proof response did not match this delivery and proof kind.");
      mutation.payloadChanged();
      if (kind === "signature") setSignature(data.url); else setPhoto(data.url);
      toast.success(`${kind === "signature" ? "Signature" : "Photo"} uploaded privately.`);
    } catch (error) { setActionError(apiError(error)); }
    finally { actionActive.current = false; setAction(null); }
  }

  async function complete() {
    if (!canComplete || actionActive.current) return;
    const result = await mutation.post<Delivery>(`/deliveries/${delivery.id}/complete`, {
      cash_amount: cashAmount, upi_amount: upiAmount,
      signature_url: signatureRef, proof_photo_url: photoRef,
    });
    if (!result) return;
    onCompleted(result);
    await order.refetch();
    toast.success("Delivery completed with proof and server-validated funding.");
  }

  return (
    <Modal open={open} busy={busy} onClose={onClose} labelledBy="delivery-title" testId="delivery-detail">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div><p className="data-label">Delivery / {delivery.id.slice(0, 8)}</p><h2 id="delivery-title" className="font-display text-2xl font-bold">{order.data?.order_number || delivery.order_id.slice(0, 8)}</h2></div>
        <span className={`chip ${completed ? "chip-success" : "chip-warning"}`}>{completed ? "Completed" : "In progress"}</span>
      </div>
      <div className="space-y-4">
        {order.isPending && <p role="status">Loading order funding...</p>}
        {order.error && <p role="alert">{apiError(order.error)} <button className="btn-ghost" onClick={() => void order.refetch()}>Retry order</button></p>}
        {order.data && <OrderBalance order={order.data} />}
        <p className="text-xs text-text-secondary">Started {formatDateTime(delivery.started_at)} / Completed {formatDateTime(delivery.completed_at)}</p>
        {completed ? <p className="pane p-4" data-testid="delivery-receipt">Recorded cash {formatINR(delivery.cash_collected)} / UPI {formatINR(delivery.upi_collected)}. Proofs are read-only.</p> : (
          <>
            <section className="pane p-4 space-y-3">
              <h3 className="data-label">1 / Start and recipient verification</h3>
              {!delivery.started_at && <button className="btn-ghost" disabled={busy} onClick={() => void run("start")} data-testid="delivery-start">{action === "start" ? "Starting..." : "Start delivery"}</button>}
              {delivery.otp_verified ? <p className="chip chip-success" data-testid="delivery-otp-verified">OTP verified</p> : <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void run("verify-otp"); }}>
                <label className="data-label" htmlFor="delivery-otp">Recipient OTP (6 digits)</label>
                <input id="delivery-otp" className="input" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={otp} disabled={busy} onChange={(event) => setOtp(event.target.value)} data-testid="delivery-otp" />
                <button className="btn-volt" disabled={busy || !/^[0-9]{6}$/.test(otp)} data-testid="delivery-verify">{action === "verify-otp" ? "Verifying..." : "Verify OTP"}</button>
              </form>}
              <p className="text-xs text-text-secondary">Ask the recipient for the OTP. Automatic SMS/WhatsApp delivery is not connected.</p>
            </section>
            <fieldset disabled={busy} className="pane p-4 space-y-4">
              <legend className="data-label px-1">2 / Capture proof</legend>
              <SignaturePad disabled={busy} onCapture={(canvas) => void upload("signature", canvas)} />
              <div><label className="data-label" htmlFor="delivery-signature-file">Upload signature image instead</label><input id="delivery-signature-file" className="input mt-1" type="file" accept="image/png,image/jpeg" data-testid="delivery-signature-file" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload("signature", file); }} /></div>
              <div><label className="data-label" htmlFor="delivery-photo-file">Delivery photo</label><input id="delivery-photo-file" className="input mt-1" type="file" accept="image/png,image/jpeg" data-testid="delivery-photo-file" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload("photo", file); }} /></div>
              <p className="text-xs text-text-secondary">PNG/JPEG only, at most 5 MiB and 20 million pixels. The server validates images and binds them to this delivery.</p>
              {action === "signature" || action === "photo" ? <p role="status">Uploading {action}...</p> : null}
            </fieldset>
          </>
        )}
        {signatureRef && <ProofPreview reference={signatureRef} label="Signature" />}
        {photoRef && <ProofPreview reference={photoRef} label="Photo" />}
        {!completed && <fieldset disabled={busy} className="pane p-4 space-y-3">
          <legend className="data-label px-1">3 / Collection and completion</legend>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div><label className="data-label" htmlFor="delivery-cash">Cash collected (INR)</label><input id="delivery-cash" className="input mt-1" inputMode="decimal" value={cash} onChange={(event) => { mutation.payloadChanged(); setCash(event.target.value); }} data-testid="delivery-cash" /></div>
            <div><label className="data-label" htmlFor="delivery-upi">UPI collected (INR)</label><input id="delivery-upi" className="input mt-1" inputMode="decimal" value={upi} onChange={(event) => { mutation.payloadChanged(); setUpi(event.target.value); }} data-testid="delivery-upi" /></div>
          </div>
          {(cashAmount === null || upiAmount === null) && <p role="alert">Use non-negative amounts with at most two decimal places, without commas or exponent.</p>}
          <p className="text-xs text-text-secondary">Cash orders require fully allocated cash/UPI/bank receipts before completion. Credit holds and remaining funding are checked by the server. This records declared receipts, not a gateway verification.</p>
          <button className="btn-volt" disabled={busy || !canComplete} onClick={() => void complete()} data-testid="delivery-complete">{mutation.busy ? "Completing..." : mutation.unconfirmed ? "Retry completion" : "Complete delivery"}</button>
        </fieldset>}
        {actionError && <p role="alert" data-testid="delivery-action-error">{actionError}</p>}
        {mutation.error && <p role="alert" data-testid="delivery-complete-error">{mutation.error}</p>}
        {mutation.unconfirmed && <p role="status" className="text-sm" data-testid="delivery-unconfirmed">Result unconfirmed. Retry unchanged with the same request key. Do not collect the payment again.</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <button className="btn-ghost" disabled={busy} onClick={() => void Promise.all([onRefresh(), order.refetch()])} data-testid="delivery-refresh">Refresh server state</button>
          <button className="btn-ghost" disabled={busy} onClick={onClose} data-testid="delivery-close">Close</button>
        </div>
      </div>
    </Modal>
  );
}
