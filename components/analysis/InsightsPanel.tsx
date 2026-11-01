// Rule-based insights (§17 of the source spec): every insight is a
// plain, traceable observation already present in the fetched analysis
// payload — nothing is inferred or predicted. Severity is purely
// descriptive (positive/negative/neutral change), never a causal claim.
import React from 'react';
import { Lightbulb, ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';

export interface Insight {
  text: string;
  detail?: string;
  severity: 'positive' | 'negative' | 'neutral';
  onInvestigate?: () => void;
}

const ICON: Record<Insight['severity'], React.ReactNode> = {
  positive: <ArrowUpRight size={16} className="text-green-600 dark:text-green-400" />,
  negative: <ArrowDownRight size={16} className="text-red-600 dark:text-red-400" />,
  neutral: <Minus size={16} className="text-gray-400 dark:text-gray-500" />,
};

const InsightsPanel: React.FC<{ insights: Insight[] }> = ({ insights }) => {
  if (insights.length === 0) return null;
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
      <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3 flex items-center gap-2">
        <Lightbulb size={16} className="text-amber-500" /> Insights
      </h3>
      <ul className="space-y-3">
        {insights.map((insight, i) => (
          <li key={i} className="flex items-start gap-2.5">
            <span className="mt-0.5 shrink-0">{ICON[insight.severity]}</span>
            <div className="flex-1">
              <p className="text-[13px] text-gray-700 dark:text-gray-200">{insight.text}</p>
              {insight.detail && <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">{insight.detail}</p>}
              {insight.onInvestigate && (
                <button onClick={insight.onInvestigate} className="text-[11px] text-blue-600 dark:text-blue-400 font-medium hover:underline mt-0.5">
                  Investigate →
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default InsightsPanel;
