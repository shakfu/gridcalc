import { useEffect, useMemo, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { bridge } from '../bridge/api'
import type { ChartData } from '../bridge/types'

const PALETTE = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#af7aa1', '#76b7b2']

// A bar chart from an A1 range. `chart_data` returns a renderer-agnostic
// {title, labels, series} shape; here it is drawn with Recharts.
export function ChartDialog({
  open,
  onOpenChange,
  rangeRef,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  rangeRef?: string
}) {
  const [spec, setSpec] = useState('')
  const [data, setData] = useState<ChartData | null>(null)

  useEffect(() => {
    if (open) {
      setSpec(rangeRef ?? '')
      setData(null)
    }
  }, [open, rangeRef])

  const draw = async () => {
    setData(await bridge.chart_data(spec.trim()))
  }

  // Recharts wants row objects keyed by series name; pivot {labels, series}.
  const rows = useMemo(() => {
    if (!data || data.error || !data.labels) return []
    return data.labels.map((label, i) => {
      const row: Record<string, string | number | null> = { label }
      data.series?.forEach((s) => {
        row[s.name] = s.values[i]
      })
      return row
    })
  }, [data])

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content wide">
          <Dialog.Title className="dialog-title">Chart</Dialog.Title>
          <div className="field-row">
            <span className="field-label">Range</span>
            <input
              value={spec}
              onChange={(e) => setSpec(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void draw()
              }}
              placeholder="A4:D6"
            />
            <button className="btn-primary" onClick={() => void draw()}>
              Draw
            </button>
          </div>

          {data?.error ? (
            <p className="error">{data.error}</p>
          ) : rows.length > 0 && data?.series ? (
            <div className="chart-box" data-testid="chart-box">
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={rows} margin={{ top: 16, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#3a3d44" />
                  <XAxis dataKey="label" stroke="#9aa0a8" fontSize={12} />
                  <YAxis stroke="#9aa0a8" fontSize={12} />
                  <Tooltip
                    contentStyle={{ background: '#2b2e34', border: '1px solid #3a3d44' }}
                    cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                  />
                  <Legend />
                  {data.series.map((s, i) => (
                    <Bar key={s.name} dataKey={s.name} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="note">Enter a range and press Draw.</p>
          )}

          <div className="dialog-actions">
            <Dialog.Close className="btn">Close</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
