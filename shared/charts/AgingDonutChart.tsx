import React from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { formatCompactInr } from '../formatters';

const BUCKET_LABELS: Record<string, string> = {
  current: 'Current', days_1_30: '1-30 Days', days_31_60: '31-60 Days',
  days_61_90: '61-90 Days', days_90_plus: '90+ Days', no_due_date: 'No Due Date',
};
const BUCKET_COLORS: Record<string, string> = {
  current: '#16a34a', days_1_30: '#eab308', days_31_60: '#f97316',
  days_61_90: '#ef4444', days_90_plus: '#991b1b', no_due_date: '#9ca3af',
};

export interface AgingDonutChartProps {
  aging: Record<string, string>;
  height?: number;
}

const AgingDonutChart: React.FC<AgingDonutChartProps> = ({ aging, height = 220 }) => {
  const data = Object.entries(aging)
    .map(([key, value]) => ({ key, label: BUCKET_LABELS[key] ?? key, value: Number(value) }))
    .filter((d) => d.value > 0);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-[13px] text-gray-400 dark:text-gray-500" style={{ height }}>
        No outstanding amounts.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="label" cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2}>
          {data.map((d) => (
            <Cell key={d.key} fill={BUCKET_COLORS[d.key] ?? '#9ca3af'} />
          ))}
        </Pie>
        <Tooltip formatter={(value: number) => formatCompactInr(value)} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>
  );
};

export default AgingDonutChart;
