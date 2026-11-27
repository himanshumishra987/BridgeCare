import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import DocumentPreview from './DocumentPreview';

describe('DocumentPreview sandbox', () => {
  it('renders a PDF in an iframe with no sandbox permissions at all', () => {
    render(<DocumentPreview url="blob:preview-1" mimeType="application/pdf" filename="report.pdf" />);

    const frame = screen.getByTitle('report.pdf');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('sandbox', '');
    // Neither token may be present: both would re-grant privileges we removed.
    expect(frame.getAttribute('sandbox')).not.toMatch(/allow-scripts/);
    expect(frame.getAttribute('sandbox')).not.toMatch(/allow-same-origin/);
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('tells the user what to do when a browser blocks a sandboxed PDF', () => {
    render(<DocumentPreview url="blob:preview-1" mimeType="application/pdf" filename="report.pdf" />);
    expect(screen.getByText(/use Download once security screening has cleared/i)).toBeInTheDocument();
  });

  it('renders an image as an img, not an iframe, so no frame sandbox is involved', () => {
    render(<DocumentPreview url="blob:preview-2" mimeType="image/png" filename="scan.png" />);

    const image = screen.getByAltText('scan.png');
    expect(image.tagName).toBe('IMG');
    expect(screen.queryByRole('iframe')).not.toBeInTheDocument();
  });

  it('falls back to a file card for types it cannot render inline', () => {
    render(<DocumentPreview url="blob:preview-3" mimeType="text/plain" filename="notes.txt" />);
    expect(screen.getByText('notes.txt')).toBeInTheDocument();
    expect(screen.queryByRole('iframe')).not.toBeInTheDocument();
  });
});
