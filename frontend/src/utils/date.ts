export function toDateInputValue(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function getTodayDateInputValue(): string {
  return toDateInputValue(new Date())
}

export function getRelativeDateInputValue(daysOffset: number): string {
  const date = new Date()
  date.setDate(date.getDate() + daysOffset)
  return toDateInputValue(date)
}
