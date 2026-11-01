import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { formatCompactInr, formatDate } from '../formatters';

export interface TrendSeries {
  name: string;
  color: string;
  points: { date: string; value: string }[];
}

export interface TrendLineChartProps {
  series: TrendSeries[];
  height?: number;
}

const TrendLineChart: React.FC<TrendLineChartProps> = ({ series, height = 260 }) => {
  const hasData = series.some((s) => s.points.length > 0);
  if (!hasData) {
    return (
      <div className="flex items-center justify-center text-[13px] text-gray-400 dark:text-gray-500" style={{ height }}>
        No data for this period.
      </div>
    );
  }

  // Merge series by date into one row-per-date dataset recharts expects.
  const dateSet = new Set<string>();
  series.forEach((s) => s.points.forEach((p) => dateSet.add(p.date)));
  const dates = Array.from(dateSet).sort();
  const merged = dates.map((date) => {
    const row: Record<string, string | number> = { date };
    series.forEach((s) => {
      const point = s.points.find((p) => p.date === date);
      row[s.name] = point ? Number(point.value) : 0;
    });
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={merged} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-gray-100 dark:text-gray-800" />
        <XAxis dataKey="date" tickFormatter={(d) => formatDate(d)} tick={{ fontSize: 11 }} stroke="currentColor" className="text-gray-400 dark:text-gray-500" />
        <YAxis tickFormatter={(v) => formatCompactInr(v)} tick={{ fontSize: 11 }} stroke="currentColor" className="text-gray-400 dark:text-gray-500" width={64} />
        <Tooltip
          formatter={(value: number) => formatCompactInr(value)}
          labelFormatter={(d) => formatDate(d as string)}
          contentStyle={{ fontSize: 12, borderRadius: 8 }}
        />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s) => (
          <Line key={s.name} type="monotone" dataKey={s.name} stroke={s.color} strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 4 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
};

export default TrendLineChart;
