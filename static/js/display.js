window.app = Vue.createApp({
  el: '#vue',
  mixins: [window.windowMixin],
  delimiters: ['${', '}'],
  data() {
    return {
      charge: mapCharge(charge_data),
      mempool_url: mempool_url,
      ws: null,
      wallet: {
        inkey: ''
      },
      tab: 'uqr'
    }
  },
  computed: {
    mempoolLink() {
      // remove trailing slash
      const url = this.mempool_url.replace(/\/$/, '')
      return `${url}/address/${this.charge.onchainaddress}`
    },
    unifiedQR() {
      const bitcoin = (this.charge.onchainaddress || '').toUpperCase()
      let queryString = `bitcoin:${bitcoin}?amount=${(
        this.charge.amount / 1e8
      ).toFixed(8)}`
      if (this.charge.payment_request) {
        queryString += `&lightning=${this.charge.payment_request.toUpperCase()}`
      }
      return queryString
    },
    hasEnded() {
      const chargeTimeSeconds = this.charge.time * 60
      const now = new Date().getTime() / 1000
      const then = new Date(this.charge.timestamp).getTime() / 1000
      const timeSecondsLeft = chargeTimeSeconds - now + then
      return timeSecondsLeft <= 0 || this.charge.paid
    }
  },
  methods: {
    initWs: async function () {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${protocol}://${window.location.host}/satspay/${this.charge.id}/ws`
      this.ws = new WebSocket(url)
      this.ws.addEventListener('message', async ({data}) => {
        const res = JSON.parse(data.toString())
        this.charge.balance = res.balance
        this.charge.pending = res.pending
        this.charge.paid = res.paid
        this.charge.completelink = res.completelink
        if (this.charge.paid) {
          this.charge.progress = 1
          this.charge.paid = true
          if (this.charge.completelink) {
            setTimeout(() => {
              window.location.href = this.charge.completelink
            }, 5000)
          }
          this.$q.notify({
            type: 'positive',
            message: 'Payment received',
            timeout: 10000
          })
        }
      })
      this.ws.addEventListener('close', async () => {
        this.$q.notify({
          type: 'negative',
          message: 'WebSocket connection closed. Retrying...',
          timeout: 1000
        })
        setTimeout(() => {
          this.initWs()
        }, 3000)
      })
    }
  },
  created: async function () {
    // add custom-css to make overrides easier
    if (this.charge.custom_css) {
      document.body.setAttribute('id', 'custom-css')
    }
    this.initWs()
  }
})
