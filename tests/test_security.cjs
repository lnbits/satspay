const assert = require('node:assert/strict')
const {readFileSync} = require('node:fs')
const {resolve} = require('node:path')
const {test} = require('node:test')
const vm = require('node:vm')

const load = file => {
  const context = vm.createContext({
    URL,
    window: {app: {component() {}}},
    windowMixin: {}
  })
  vm.runInContext(
    readFileSync(resolve(__dirname, '../static', file), 'utf8'),
    context
  )
  return context
}

for (const file of ['display.js', 'index.js']) {
  test(`${file}: safe URLs and legacy metadata`, () => {
    const context = load(file)
    const validate =
      file === 'display.js'
        ? vm.runInContext('satspayHttpUrl', context)
        : context.window.PageSatspay.methods.safeHttpUrl
    for (const value of [
      'javascript:alert(1)',
      'JaVaScRiPt:alert(1)',
      '  javascript:alert(1)  ',
      'data:text/html,test',
      '//evil.example/path',
      '/relative',
      '  ',
      '',
      null,
      'https://paypal.com@evil.example/',
      'https://user:password@merchant.example/',
      'https://:password@merchant.example/'
    ]) {
      assert.equal(validate(value), null)
    }
    for (const value of [
      'http://merchant.example/complete',
      'https://merchant.example/complete'
    ]) {
      assert.equal(validate(value), value)
      context.value = value
      assert.equal(
        vm.runInContext(
          'mapCharge({completelink: value, time: 1}).completelink',
          context
        ),
        value
      )
    }
    assert.equal(
      validate('  HtTpS://merchant.example/complete  '),
      'https://merchant.example/complete'
    )
    assert.equal(
      vm.runInContext('mapCharge({extra: "invalid", time: 1}).extra', context),
      null
    )
    if (file === 'display.js') {
      assert.equal(
        vm.runInContext(
          'mapCharge({completelink: "javascript:alert(1)", time: 1}).completelink',
          context
        ),
        null
      )
    }
  })
}

test('websocket completion redirects reject legacy script URLs', async () => {
  const context = load('display.js')
  const handlers = {}
  let navigation = null
  context.window.location = {protocol: 'https:', host: 'lnbits.example'}
  Object.defineProperty(context.window.location, 'href', {
    set(value) {
      navigation = value
    }
  })
  context.WebSocket = class {
    addEventListener(name, handler) {
      handlers[name] = handler
    }
  }
  context.setTimeout = callback => callback()
  const page = {
    charge: {id: 'charge'},
    $q: {notify() {}},
    $t: key => key
  }
  await context.window.PageSatspayPublic.methods.initWs.call(page)
  await handlers.message({
    data: JSON.stringify({paid: true, completelink: 'javascript:alert(1)'})
  })
  assert.equal(navigation, null)
  await handlers.message({
    data: JSON.stringify({
      paid: false,
      completelink: 'https://merchant.example/complete'
    })
  })
  assert.equal(navigation, null)
  await handlers.message({
    data: JSON.stringify({
      paid: true,
      completelink: 'https://merchant.example/complete'
    })
  })
  assert.equal(navigation, 'https://merchant.example/complete')
})

test('currencies use the full list unless the operator restricts it', () => {
  const currencies = load('index.js').window.PageSatspay.computed.currencies
  for (const [allowedCurrencies, expected] of [
    [[], ['satoshis', 'USD', 'EUR']],
    [['EUR'], ['satoshis', 'EUR']]
  ]) {
    const values = currencies.call({
      g: {allowedCurrencies, currencies: ['USD', 'EUR']}
    })
    assert.deepEqual([...values], expected)
  }
})
