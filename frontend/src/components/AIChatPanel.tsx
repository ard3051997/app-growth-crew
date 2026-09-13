import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader, Plus, Sparkles, ChevronRight, X } from 'lucide-react';
import { api } from '../api';
import { getErrorMessage } from '../utils';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const SUGGESTED = [
  { icon: '📉', text: 'Why did installs drop recently?' },
  { icon: '💰', text: 'What is my biggest revenue opportunity?' },
  { icon: '🔍', text: 'Which keyword should I target next?' },
  { icon: '🔁', text: 'Is my paywall conversion rate healthy?' },
  { icon: '📊', text: "Summarize this app's last 30 days" },
  { icon: '⚠️', text: 'What funnel stage is leaking the most?' },
];

interface Props {
  packageId: string;
  onClose?: () => void; // available for future close-from-panel button
}

export default function AIChatPanel({ packageId, onClose }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [chatId, setChatId] = useState(0); // increment to reset chat
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const requestGeneration = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Auto-focus input when panel opens
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 100);
  }, []);

  // Reset chat when app changes
  useEffect(() => {
    requestGeneration.current += 1;
    activeRequest.current?.abort();
    setMessages([]);
    setLoading(false);
    return () => activeRequest.current?.abort();
  }, [packageId]);

  const appDisplayName = packageId.split('.').slice(-1)[0]
    ?.replace(/_/g, ' ')
    ?.replace(/([A-Z])/g, ' $1')
    ?.trim() || packageId;

  const send = async (question: string) => {
    if (!question.trim() || loading) return;
    const q = question.trim();
    const requestId = ++requestGeneration.current;
    const requestPackage = packageId;
    const controller = new AbortController();
    activeRequest.current = controller;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setLoading(true);
    try {
      const res = await api.askAppChat(requestPackage, q, controller.signal);
      if (controller.signal.aborted || requestGeneration.current !== requestId) return;
      setMessages(prev => [...prev, { role: 'assistant', content: res.answer }]);
    } catch (err: unknown) {
      if (controller.signal.aborted || requestGeneration.current !== requestId) return;
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Unable to get an answer right now: ${getErrorMessage(err, 'Unexpected API error')}`
      }]);
    } finally {
      if (!controller.signal.aborted && requestGeneration.current === requestId) setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      send(input);
    }
  };

  const newChat = () => {
    requestGeneration.current += 1;
    activeRequest.current?.abort();
    setMessages([]);
    setChatId(c => c + 1);
    setInput('');
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  return (
    <div className="flex flex-col h-full bg-[#0d0d14] border-l border-white/[0.06]">
      {/* Header — Cursor-like top bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06] shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-6 h-6 rounded-md bg-gradient-to-br from-accent-primary to-accent-secondary flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-text-primary">AI Chat</span>
          <ChevronRight className="w-3 h-3 text-text-muted" />
          <span className="text-xs text-text-muted font-mono truncate max-w-[120px]" title={packageId}>
            {appDisplayName}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={newChat}
            className="p-1.5 rounded-md hover:bg-white/5 text-text-muted hover:text-text-primary transition-colors"
            title="New chat"
          >
            <Plus className="w-4 h-4" />
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-white/5 text-text-muted hover:text-text-primary transition-colors"
              title="Close AI chat"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Context badge */}
      <div className="px-4 py-2 border-b border-white/[0.04] shrink-0">
        <div className="flex items-center gap-2 text-[10px] font-mono text-text-muted">
          <div className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
          <span>Analyzing: <span className="text-text-secondary">{packageId}</span></span>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto py-4 px-3 space-y-1 min-h-0">
        {messages.length === 0 && !loading ? (
          <div className="px-1 space-y-2 pt-2">
            <p className="text-[11px] text-text-muted font-mono text-center pb-3">
              Ask anything about this app
            </p>
            {SUGGESTED.map((s) => (
              <button
                key={s.text}
                onClick={() => send(s.text)}
                className="w-full text-left flex items-start gap-2.5 px-3 py-2.5 rounded-lg text-xs text-text-secondary hover:text-text-primary hover:bg-white/[0.04] border border-white/[0.04] hover:border-white/[0.08] transition-all group"
              >
                <span className="shrink-0 text-sm mt-0.5">{s.icon}</span>
                <span className="leading-relaxed">{s.text}</span>
              </button>
            ))}
          </div>
        ) : (
          <>
            {messages.map((msg, i) => (
              <div key={`${chatId}-${i}`} className={`flex gap-2 py-1.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'assistant' && (
                  <div className="w-6 h-6 rounded-full bg-gradient-to-br from-accent-primary to-accent-secondary flex items-center justify-center shrink-0 mt-0.5">
                    <Bot className="w-3 h-3 text-white" />
                  </div>
                )}
                <div className={`max-w-[88%] text-xs leading-relaxed whitespace-pre-wrap rounded-xl px-3.5 py-2.5 ${
                  msg.role === 'user'
                    ? 'bg-accent-primary/15 text-text-primary border border-accent-primary/20 rounded-tr-sm'
                    : 'bg-white/[0.04] text-text-primary border border-white/[0.06] rounded-tl-sm'
                }`}>
                  {msg.content}
                </div>
                {msg.role === 'user' && (
                  <div className="w-6 h-6 rounded-full bg-white/[0.06] border border-white/[0.08] flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-3 h-3 text-text-secondary" />
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-2 py-1.5">
                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-accent-primary to-accent-secondary flex items-center justify-center shrink-0">
                  <Bot className="w-3 h-3 text-white" />
                </div>
                <div className="bg-white/[0.04] border border-white/[0.06] px-3.5 py-2.5 rounded-xl rounded-tl-sm flex items-center gap-2">
                  <Loader className="w-3 h-3 text-accent-primary animate-spin" />
                  <span className="text-[11px] text-text-muted font-mono">Analyzing data…</span>
                </div>
              </div>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area — Cursor-style */}
      <div className="shrink-0 border-t border-white/[0.06] p-3">
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] focus-within:border-accent-primary/40 transition-colors overflow-hidden">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about revenue, funnel, ASO…"
            disabled={loading}
            rows={3}
            className="w-full bg-transparent px-3.5 pt-3 pb-1 text-xs text-text-primary outline-none resize-none font-mono placeholder:text-text-muted/60 disabled:opacity-50"
          />
          <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
            <span className="text-[10px] text-text-muted/50 font-mono">⌘↵ to send</span>
            <button
              onClick={() => send(input)}
              disabled={!input.trim() || loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent-primary disabled:opacity-30 hover:bg-accent-primary/80 transition-colors text-white text-[11px] font-medium"
            >
              <Send className="w-3 h-3" />
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
