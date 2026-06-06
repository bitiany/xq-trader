/** A 股连续竞价时段：9:30-11:30、13:00-15:00（周一至周五）。 */

export function isAshareTradingSession(now: Date = new Date()): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) {
    return false
  }
  const minutes = now.getHours() * 60 + now.getMinutes()
  const inMorning = minutes >= 9 * 60 + 30 && minutes < 11 * 60 + 30
  const inAfternoon = minutes >= 13 * 60 && minutes < 15 * 60
  return inMorning || inAfternoon
}
