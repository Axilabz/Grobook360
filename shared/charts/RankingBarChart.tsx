import React from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { formatCompactInr } from '../formatters';

export interface RankingBarRow {
  id: string;
  label: string;
  value: number;
}

export interface RankingBarChartProps {
  data: RankingBarRow[];
  height?: number;
  color?: string;
  onBarClick?: (row: RankingBarRow) => void;
}

const RankingBarChart: React.FC<RankingBarChartProps> = ({ data, height = 280, color = '#0066ff', onBarClick }) => {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-[13px] text-gray-400 dark:text-gray-500" style={{ height }}>
        No data for this period.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }}>
        <XAxis type="number" tickFormatter={(v) => formatCompactInr(v)} tick={{ fontSize: 11 }} stroke="currentColor" className="text-gray-400 dark:text-gray-500" />
        <YAxis type="category" dataKey="label" width={140} tick={{ fontSize: 11 }} stroke="currentColor" className="text-gray-400 dark:text-gray-500" />
        <Tooltip formatter={(value: number) => formatCompactInr(value)} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
        <Bar
          dataKey="value"
          radius={[0, 4, 4, 0]}
          onClick={onBarClick ? (entry: any) => onBarClick((entry.payload ?? entry) as RankingBarRow) : undefined}
          cursor={onBarClick ? 'pointer' : undefined}
        >
          {data.map((row) => (
            <Cell key={row.id} fill={color} className={onBarClick ? 'cursor-pointer' : undefined} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};

export default RankingBarChart;
