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

const updateProgress = function (charge) {
  const now = parseInt(new Date().getTime() / 1000)
  const timeLeft = now - charge.timestamp
  // time is in minutes
  percent = timeLeft < 0 ? 1 : parseInt((timeLeft / charge.time) * 60)
  charge.progress = charge.paid ? 1 : percent
  charge.timeLeft = secondsToTime(timeLeft)
  charge.timeElapsed = timeLeft < 0
  console.log(charge)
  return charge
}

const mapCharge = (obj, oldObj = {}) => {
  let charge = {...oldObj, ...obj}
  charge = updateProgress(charge)
  charge.paid = charge.amount == charge.balance
  charge.displayUrl = ['/satspay/', obj.id].join('')
  charge.expanded = oldObj.expanded || false
  charge.pendingBalance = oldObj.pendingBalance || 0
  charge.extra = charge.extra ? JSON.parse(charge.extra) : charge.extra
  return charge
}

const mapCSS = (obj, oldObj = {}) => {
  const theme = _.clone(obj)
  return theme
}

const secondsToTime = seconds =>
  seconds > 0 ? new Date(seconds * 1000).toISOString().substring(14, 19) : ''
