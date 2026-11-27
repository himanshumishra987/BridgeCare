import { FileText } from 'lucide-react';

/**
 * Preview a file by its URL (blob URL or authenticated endpoint).
 * Falls back to a plain icon if the file type cannot be rendered inline.
 */
export default function DocumentPreview({ url, mimeType, filename, className = '' }) {
  if (!url) return null;

  if (mimeType === 'application/pdf') {
    return (
      <div className={`overflow-hidden rounded-xl border border-slate-200 ${className}`}>
        <iframe
          src={url}
          title={filename || 'Document preview'}
          className="h-96 w-full"
        />
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
