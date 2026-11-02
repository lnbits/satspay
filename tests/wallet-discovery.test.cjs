const assert = require('node:assert/strict')
const {readFileSync} = require('node:fs')
const {join} = require('node:path')
const {test} = require('node:test')
const vm = require('node:vm')

test('Watchonly discovery only requests wallets when enabled', async () => {
  for (const enabled of [false, true]) {
    const requests = []
    const notices = []
    const context = {
      window: {},
      LNbits: {
        api: {
          request: async (...args) => {
            requests.push(args)
            if (!enabled) throw {response: {status: 404}}
            return {
              data: [{id: 'watch-wallet', title: 'Savings', network: 'Mainnet'}]
            }
          }
        },
        utils: {notifyApiError: error => notices.push(error)}
      }
    }
    vm.createContext(context)
    vm.runInContext(
      readFileSync(join(__dirname, '../static/index.js'), 'utf8'),
      context
    )
    const page = context.window.PageSatspay
    const state = {
      ...page.data(),
      g: {
        user: {
          extensions: enabled ? ['watchonly'] : [],
          wallets: [{adminkey: 'admin-key'}]
        }
      }
    }

    await page.methods.getWalletLinks.call(state)

    assert.equal(requests.length, enabled ? 1 : 0)
    assert.equal(notices.length, 0)
    assert.equal(state.walletLinks.length, enabled ? 1 : 0)
    if (enabled) {
      assert.deepEqual(requests[0], [
        'GET',
        '/watchonly/api/v1/wallet?network=Mainnet',
        'admin-key'
      ])
      assert.equal(state.walletLinks[0].id, 'watch-wallet')
    }
  }
})
