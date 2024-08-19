const sleep = ms => new Promise(r => setTimeout(r, ms))
const retryWithDelay = async function (fn, retryCount = 0) {
  try {
    await sleep(25)
    // Do not return the call directly, use result.
    // Otherwise the error will not be cought in this try-catch block.
    const result = await fn()
    return result
  } catch (err) {
    if (retryCount > 100) throw err
    await sleep((retryCount + 1) * 1000)
    return retryWithDelay(fn, retryCount + 1)
  }
}

const mapCharge = (obj, oldObj = {}) => {
  let charge = {...oldObj, ...obj}
  charge.paid = charge.balance >= charge.amount
  charge.displayUrl = ['/satspay/', obj.id].join('')
  charge.expanded = oldObj.expanded || false
  charge.pending = oldObj.pending || 0
  charge.extra =
    charge.extra && charge.extra instanceof String
      ? JSON.parse(charge.extra)
      : charge.extra
  const now = new Date().getTime() / 1000
  const chargeTimeSeconds = charge.time * 60
  const secondsSinceCreated = chargeTimeSeconds - now + charge.timestamp
  charge.timeSecondsLeft = chargeTimeSeconds - now + charge.timestamp
  charge.timeLeft =
    charge.timeSecondsLeft <= 0
      ? '00:00:00'
      : secondsToTime(charge.timeSecondsLeft)
  charge.progress = progress(charge.time * 60, secondsSinceCreated)
  return charge
}

const mapCSS = (obj, oldObj = {}) => {
  const theme = _.clone(obj)
  return theme
}

const padString = num => num.toString().padStart(2, '0')

const secondsToTime = seconds => {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  return `${padString(hours)}:${padString(minutes)}:${padString(secs)}`
}

const progress = (startSeconds, currentSeconds) => {
  return 1 - (startSeconds - currentSeconds) / startSeconds
}
