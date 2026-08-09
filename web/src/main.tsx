import { FormEvent, ReactNode, useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

type Todo = { id: number; text: string }
type Reminder = { id: number; text: string; dueAt: string; recurrence: string | null; status: string }
type Tab = 'today' | 'todos' | 'reminders' | 'shopping' | 'weather'

const tabs: { id: Tab; label: string; icon: string }[] = [
  { id: 'today', label: 'Today', icon: '⌂' },
  { id: 'todos', label: 'Todos', icon: '✓' },
  { id: 'reminders', label: 'Reminders', icon: '◷' },
  { id: 'shopping', label: 'Shopping', icon: '▣' },
  { id: 'weather', label: 'Weather', icon: '☀' },
]

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || 'Something went wrong.')
  return data
}

function weatherDescription(code: number): string {
  if (code === 0) return 'Clear sky'
  if (code <= 3) return 'Partly cloudy'
  if (code <= 48) return 'Foggy'
  if (code <= 67) return 'Rain showers'
  if (code <= 77) return 'Snow showers'
  return 'Thunderstorms'
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-xl shadow-slate-950/30"><h2 className="mb-4 text-xl font-semibold">{title}</h2>{children}</section>
}

function ItemList({ items, onArchive, empty }: { items: Todo[]; onArchive: (id: number) => void; empty: string }) {
  if (!items.length) return <p className="py-6 text-center text-slate-400">{empty}</p>
  return <ul className="space-y-3">{items.map(item => <li key={item.id} className="flex items-center justify-between gap-3 rounded-2xl bg-slate-800/80 px-4 py-3 text-lg"><span>{item.text}</span><button onClick={() => onArchive(item.id)} className="rounded-xl bg-emerald-500 px-4 py-2 font-semibold text-slate-950 active:scale-95">Done</button></li>)}</ul>
}

function App() {
  const [tab, setTab] = useState<Tab>('today')
  const [todos, setTodos] = useState<Todo[]>([])
  const [shopping, setShopping] = useState<Todo[]>([])
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [toast, setToast] = useState('')
  const [weather, setWeather] = useState<any>(null)
  const [location, setLocation] = useState('Sapulpa, Oklahoma')

  const refresh = useCallback(async () => {
    try {
      const [todoItems, reminderItems, shoppingItems] = await Promise.all([
        request<Todo[]>('/todos'), request<Reminder[]>('/reminders'), request<Todo[]>('/shopping-items'),
      ])
      setTodos(todoItems); setReminders(reminderItems); setShopping(shoppingItems)
    } catch (error) { setToast(error instanceof Error ? error.message : 'Unable to load dashboard.') }
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { if (!toast) return; const id = window.setTimeout(() => setToast(''), 3500); return () => clearTimeout(id) }, [toast])

  async function add(event: FormEvent<HTMLFormElement>, endpoint: string) {
    event.preventDefault()
    const form = new FormData(event.currentTarget); const text = String(form.get('text') || '')
    try { await request(endpoint, { method: 'POST', body: JSON.stringify({ text }) }); event.currentTarget.reset(); await refresh() } catch (error) { setToast(error instanceof Error ? error.message : 'Unable to add item.') }
  }
  async function archive(endpoint: string, id: number) { try { await request(`${endpoint}/${id}`, { method: 'DELETE' }); await refresh() } catch (error) { setToast(error instanceof Error ? error.message : 'Unable to update item.') } }
  async function addReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget)
    try { await request('/reminders', { method: 'POST', body: JSON.stringify({ text: form.get('text'), schedule: form.get('schedule') }) }); event.currentTarget.reset(); await refresh() } catch (error) { setToast(error instanceof Error ? error.message : 'Unable to set reminder.') }
  }
  async function completeReminder(id: number) { try { await request(`/reminders/${id}/complete`, { method: 'POST', body: '{}' }); await refresh() } catch (error) { setToast(error instanceof Error ? error.message : 'Unable to complete reminder.') } }
  async function loadWeather(event?: FormEvent) {
    event?.preventDefault()
    try { setWeather(await request(`/weather?location=${encodeURIComponent(location)}`)) } catch (error) { setToast(error instanceof Error ? error.message : 'Weather is unavailable.') }
  }

  const AddForm = ({ endpoint, placeholder }: { endpoint: string; placeholder: string }) => <form onSubmit={event => add(event, endpoint)} className="mb-5 flex gap-3"><input name="text" required placeholder={placeholder} className="min-w-0 flex-1 rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-lg outline-none focus:border-sky-400" /><button className="rounded-2xl bg-sky-400 px-5 py-3 text-lg font-bold text-slate-950 active:scale-95">Add</button></form>

  return <main className="mx-auto flex min-h-screen max-w-6xl flex-col px-4 py-5 sm:px-8">
    <header className="mb-6 flex items-center justify-between"><div><p className="text-sm font-semibold uppercase tracking-[0.22em] text-orange-300">Orange Castle Assistant</p><h1 className="text-3xl font-bold">Your day, at a glance</h1></div><div className="rounded-2xl bg-slate-900 px-4 py-2 text-right text-sm text-slate-300">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}</div></header>
    <nav className="mb-6 grid grid-cols-5 gap-2 rounded-3xl bg-slate-900 p-2">{tabs.map(item => <button key={item.id} onClick={() => setTab(item.id)} className={`rounded-2xl px-2 py-3 text-sm font-semibold sm:text-base ${tab === item.id ? 'bg-sky-400 text-slate-950' : 'text-slate-300 active:bg-slate-800'}`}><span className="mr-1">{item.icon}</span>{item.label}</button>)}</nav>
    {toast && <div className="mb-5 rounded-2xl border border-amber-300/30 bg-amber-300/10 px-4 py-3 text-amber-100">{toast}</div>}
    {tab === 'today' && <div className="grid gap-5 lg:grid-cols-2"><Panel title={`Open todos · ${todos.length}`}><ItemList items={todos.slice(0, 5)} onArchive={id => archive('/todos', id)} empty="Nothing on your list." /></Panel><Panel title={`Upcoming reminders · ${reminders.length}`}>{reminders.length ? <ul className="space-y-3">{reminders.slice(0, 5).map(reminder => <li key={reminder.id} className="rounded-2xl bg-slate-800/80 px-4 py-3"><p className="text-lg">{reminder.text}</p><p className="text-sm text-sky-300">{new Date(reminder.dueAt).toLocaleString()}</p></li>)}</ul> : <p className="py-6 text-center text-slate-400">No upcoming reminders.</p>}</Panel></div>}
    {tab === 'todos' && <Panel title="Todos"><AddForm endpoint="/todos" placeholder="What needs doing?" /><ItemList items={todos} onArchive={id => archive('/todos', id)} empty="No active todos." /></Panel>}
    {tab === 'shopping' && <Panel title="Shopping list"><AddForm endpoint="/shopping-items" placeholder="Add milk, bread, or anything else" /><ItemList items={shopping} onArchive={id => archive('/shopping-items', id)} empty="Your shopping list is empty." /></Panel>}
    {tab === 'reminders' && <Panel title="Reminders"><form onSubmit={addReminder} className="mb-5 grid gap-3 sm:grid-cols-[1fr_1fr_auto]"><input required name="text" placeholder="What should I remind you about?" className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-lg outline-none focus:border-sky-400"/><input required name="schedule" placeholder="in 10 minutes / every day at 9 am" className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-lg outline-none focus:border-sky-400"/><button className="rounded-2xl bg-sky-400 px-5 py-3 text-lg font-bold text-slate-950 active:scale-95">Set</button></form>{reminders.length ? <ul className="space-y-3">{reminders.map(reminder => <li key={reminder.id} className="flex items-center justify-between gap-3 rounded-2xl bg-slate-800/80 px-4 py-3"><div><p className="text-lg">{reminder.text}</p><p className="text-sm text-sky-300">{new Date(reminder.dueAt).toLocaleString()}{reminder.recurrence ? ' · Repeats' : ''}</p></div><button onClick={() => completeReminder(reminder.id)} className="rounded-xl bg-emerald-500 px-4 py-2 font-semibold text-slate-950 active:scale-95">Complete</button></li>)}</ul> : <p className="py-6 text-center text-slate-400">No active reminders.</p>}</Panel>}
    {tab === 'weather' && <Panel title="Weather"><form onSubmit={loadWeather} className="mb-5 flex gap-3"><input value={location} onChange={event => setLocation(event.target.value)} className="min-w-0 flex-1 rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-lg outline-none focus:border-sky-400"/><button className="rounded-2xl bg-sky-400 px-5 py-3 text-lg font-bold text-slate-950">Update</button></form>{weather ? <Weather weather={weather} /> : <div className="rounded-2xl bg-slate-800/80 p-6 text-center"><p className="mb-3 text-4xl">☀</p><p className="text-slate-300">Tap Update to load the forecast for {location}.</p></div>}</Panel>}
  </main>
}

function Weather({ weather }: { weather: any }) {
  const daily = weather.forecast.daily; const current = weather.forecast.current
  return <><div className="mb-5 rounded-3xl bg-gradient-to-br from-sky-400 to-indigo-500 p-6 text-slate-950"><p className="font-semibold">{weather.location}</p><div className="mt-3 flex items-end gap-4"><span className="text-6xl">{Math.round(current.temperature_2m)}°F</span><span className="mb-2 text-xl">{weatherDescription(current.weather_code)}</span></div></div><div className="grid gap-3 sm:grid-cols-3">{daily.time.slice(0, 3).map((date: string, index: number) => <div key={date} className="rounded-2xl bg-slate-800/80 p-4"><p className="font-semibold">{new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short' })}</p><p className="my-2 text-2xl">{weatherDescription(daily.weather_code[index])}</p><p><span className="font-bold">{Math.round(daily.temperature_2m_max[index])}°F</span> <span className="text-slate-400">/ {Math.round(daily.temperature_2m_min[index])}°F</span></p><p className="mt-1 text-sm text-sky-300">Rain {daily.precipitation_probability_max[index] ?? 0}%</p></div>)}</div></>
}

createRoot(document.getElementById('root')!).render(<App />)
