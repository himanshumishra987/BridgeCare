import { useRef, useState } from 'react';
import { Bot, FileText, RotateCcw, Send, User } from 'lucide-react';

/**
 * Reusable conversational chat widget.
 * Props:
 *   onSend: async (message: string) => string | {
 *     answer: string,
 *     sources?: { id?, title?, label?, page?, url? }[],
 *     uncertainty?: string,
 *     disclaimer?: string
 *   }
 *   placeholder: string
 *   systemNote: string   — shown above chat (e.g., "Based on your verified records only")
 *   retryLabel: string   — label for the retry action after a failure
 */
export default function ChatWidget({
  onSend,
  placeholder = 'Ask a question…',
  systemNote,
  retryLabel = 'Retry',
}) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const bottomRef = useRef(null);

  const scrollToBottom = () =>
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);

  // Accepts a plain string or a grounded reply object from the backend
  const normalise = (reply) => {
    if (reply && typeof reply === 'object') {
      return {
        role: 'assistant',
        text: reply.answer || reply.text || 'No answer returned.',
        sources: Array.isArray(reply.sources) ? reply.sources : [],
        uncertainty: reply.uncertainty || '',
        disclaimer: reply.disclaimer || '',
      };
    }
    return { role: 'assistant', text: String(reply ?? 'No answer returned.') };
  };

  const deliver = async (text) => {
    setSending(true);
    try {
      const reply = await onSend(text);
      setMessages((prev) => [...prev, normalise(reply)]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', text: err.message, isError: true, retryFor: text }]);
    } finally {
      setSending(false);
      scrollToBottom();
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text }]);
    await deliver(text);
  };

  const handleRetry = async (text) => {
    if (sending) return;
    setMessages((prev) => prev.filter((m) => m.retryFor !== text || m.role !== 'assistant'));
    await deliver(text);
  };

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
      {systemNote && (
        <div className="border-b border-slate-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          {systemNote}
        </div>
      )}
      <div className="min-h-48 max-h-96 flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="mt-8 text-center text-xs text-slate-400">
            Your conversation will appear here.
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex items-start gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
          >
            <div className="mt-0.5 shrink-0">
              {msg.role === 'user' ? (
                <User className="h-5 w-5 text-brand-600" />
              ) : (
                <Bot className="h-5 w-5 text-slate-500" />
              )}
            </div>
            <div
              className={`max-w-xs whitespace-pre-wrap rounded-xl px-3 py-2 text-sm lg:max-w-md ${
                msg.role === 'user'
                  ? 'bg-brand-600 text-white'
                  : msg.isError
                    ? 'border border-red-200 bg-red-50 text-red-700'
                    : 'border border-slate-200 bg-white text-slate-800'
              }`}
            >
              {msg.isError && <p className="font-semibold">Could not get an answer.</p>}
              {msg.text}

              {msg.sources?.length > 0 && (
                <div className="mt-2 border-t border-slate-200 pt-2">
                  <p className="text-xs font-semibold text-slate-500">Sources</p>
                  <ul className="mt-1 space-y-0.5">
                    {msg.sources.map((s, si) => (
                      <li key={s.id ?? si} className="flex items-start gap-1 text-xs text-slate-600">
                        <FileText className="mt-0.5 h-3 w-3 shrink-0 text-brand-600" />
                        <span>
                          {s.title || s.label || s.original_filename || 'Record'}
                          {s.page ? ` · page ${s.page}` : ''}
                          {s.clause ? ` · clause ${s.clause}` : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {msg.uncertainty && (
                <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
                  Uncertainty: {msg.uncertainty}
                </p>
              )}
              {msg.disclaimer && (
                <p className="mt-1 text-xs italic text-slate-500">{msg.disclaimer}</p>
              )}

              {msg.retryFor && (
                <button
                  type="button"
                  onClick={() => handleRetry(msg.retryFor)}
                  className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-red-700 underline"
                >
                  <RotateCcw className="h-3 w-3" /> {retryLabel}
                </button>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-slate-400" />
            <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm italic text-slate-400">
              Thinking…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2 border-t border-slate-200 p-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder={placeholder}
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          disabled={sending}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!input.trim() || sending}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          aria-label="Send message"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
