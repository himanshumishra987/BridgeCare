import { FileText } from 'lucide-react';

/**
 * Preview a file by its URL (blob URL or authenticated endpoint).
 * Falls back to a plain icon if the file type cannot be rendered inline.
 *
 * Security: the previewed file is untrusted uploaded content, so the PDF frame
 * runs with `sandbox=""` — no scripts, no same-origin, no forms, no popups, no
 * downloads, no top navigation. `allow-scripts` / `allow-same-origin` are
 * deliberately NOT granted: with both, the frame could reach this origin, and
 * neither is needed to display a document.
 *
 * Limitation (verified against Chromium's own bug tracker, issue 41131921):
 * Chromium refuses to render PDFs inside any sandboxed frame, because its PDF
 * viewer is a plugin the sandbox blocks. A cleared PDF may therefore show a
 * blocked frame here; the note below points at the gated download instead. Do
 * not remove the sandbox to make previews work — render cleared PDFs with a
 * bundled same-origin viewer if inline preview is required.
 */
export default function DocumentPreview({ url, mimeType, filename, className = '' }) {
  if (!url) return null;

  if (mimeType === 'application/pdf') {
    return (
      <div className={`overflow-hidden rounded-xl border border-slate-200 ${className}`}>
        <iframe
          src={url}
          title={filename || 'Document preview'}
          sandbox=""
          referrerPolicy="no-referrer"
          className="h-96 w-full"
        />
        <p className="border-t border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
          This preview is rendered in an isolated frame with scripts disabled. Some browsers block
          inline PDFs in an isolated frame — if the preview stays empty, use Download once security
          screening has cleared the file.
        </p>
      </div>
    );
  }

  if (mimeType?.startsWith('image/')) {
    return (
      <div className={`overflow-hidden rounded-xl border border-slate-200 ${className}`}>
        <img
          src={url}
          alt={filename || 'Document preview'}
          className="max-h-96 w-full object-contain"
        />
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 ${className}`}>
      <FileText className="h-8 w-8 text-brand-600" />
      <p className="text-sm text-slate-600">{filename || 'Document'}</p>
    </div>
  );
}
