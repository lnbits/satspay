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

const mapCharge = (obj, oldObj = {}) => {
  let charge = {...oldObj, ...obj}
  charge.displayUrl = ['/satspay/', obj.id].join('')
  charge.expanded = oldObj.expanded || false
  charge.extra =
    charge.extra && typeof charge.extra == 'string'
      ? JSON.parse(charge.extra)
      : charge.extra
  const now = new Date().getTime() / 1000
  const then = new Date(charge.timestamp).getTime() / 1000
  const chargeTimeSeconds = charge.time * 60
  const secondsSinceCreated = chargeTimeSeconds - now + then
  charge.timeSecondsLeft = chargeTimeSeconds - now + then
  charge.timeLeft =
    charge.timeSecondsLeft <= 0
      ? '00:00:00'
      : secondsToTime(charge.timeSecondsLeft)
  charge.progress = progress(charge.time * 60, secondsSinceCreated)
  return charge
}

if (window.app) {
  window.app.component('satspay-paid', {
    props: ['charge'],
    computed: {
      settlementLabel() {
        const m = this.charge.settlement_method
        if (!m) return null
        if (m === 'lightning') return 'Lightning'
        if (m === 'onchain') return 'On-chain'
        return m.charAt(0).toUpperCase() + m.slice(1)
      },
      settlementProofs() {
        const p = this.charge.settlement_proof
        if (!p) return []
        try {
          const parsed = JSON.parse(p)
          return Array.isArray(parsed) ? parsed : [String(parsed)]
        } catch {
          return [String(p)]
        }
      }
    },
    template: `
    <div>
      <q-icon
        name="check"
        style="color: green; font-size: 21.4em"
        class="fit"
      ></q-icon>
      <div v-if="settlementLabel" class="row justify-center q-mt-md">
        <div class="col-sm-10 col-md-8 text-center">
          <div class="text-subtitle2">
            Paid via <span v-text="settlementLabel"></span>
          </div>
          <div
            v-for="proof in settlementProofs"
            :key="proof"
            class="text-caption text-grey ellipsis"
            v-text="proof"
          ></div>
        </div>
      </div>
      <div class="row text-center q-mt-lg">
        <div class="col text-center">
          <q-btn
            outline
            v-if="charge.completelink"
            type="a"
            :href="charge.completelink"
            :label="charge.completelinktext || 'View your tickets'"
          ></q-btn>
        </div>
      </div>
    </div>`
  })

  window.app.component('satspay-show-qr', {
    props: ['charge-amount', 'type', 'value', 'href'],
    mixins: [windowMixin],
    template: `
    <div>
      <div class="row justify-center q-mb-sm">
        <div class="col text-center">
          <span v-if="type == 'btc'" class="text-subtitle2">
            Send <strong><span v-text="chargeAmountBtc"></span> BTC</strong> <span v-text="$t('satspay.send_btc_to_address')"></span>:
          </span>
          <span v-if="type == 'ln'" class="text-subtitle2" v-text="$t('satspay.pay_ln_invoice')"></span>
          <span v-if="type == 'uqr'" class="text-subtitle2" v-text="$t('satspay.scan_uqr')"></span>
        </div>
      </div>
      <div class="row justify-center q-mb-sm">
        <div class="col-all text-center">
          <lnbits-qrcode
            ref="qrcode"
            :value="value"
            :href="href"
            :show-buttons="false"
            :max-width="420"
          ></lnbits-qrcode>
        </div>
      </div>
      <div class="row justify-center q-mt-sm" style="flex-wrap: wrap;">
        <q-btn unelevated color="primary" icon="payment" class="q-mr-sm q-mb-sm" @click="pay">
          <span v-text="$t('satspay.pay')"></span>
        </q-btn>
        <q-btn unelevated color="grey" icon="content_copy" class="q-mr-sm q-mb-sm" @click="utils.copyText(value)">
          <span v-text="$t('satspay.copy')"></span>
        </q-btn>
        <q-btn unelevated color="grey" icon="download" class="q-mb-sm" @click="downloadQr">
          <span v-text="$t('satspay.download')"></span>
        </q-btn>
      </div>
    </div>`,
    computed: {
      chargeAmountBtc() {
        return (this.chargeAmount / 1e8).toFixed(8)
      }
    },
    methods: {
      pay() {
        if (this.href) {
          window.location.href = this.href
        } else {
          this.utils.copyText(this.value)
        }
      },
      downloadQr() {
        if (this.$refs.qrcode) {
          this.$refs.qrcode.downloadSVG()
        }
      }
    }
  })

  window.app.component('satspay-time-elapsed', {
    props: ['charge'],
    data() {
      return {
        timeSeconds: 0,
        timeLeft: 60,
        progress: 0,
        barColor: 'grey'
      }
    },
    template: `
    <div class="text-center">
      <q-linear-progress size="30px" :value="progress" :color="barColor">
        <div class="absolute-full flex flex-center text-white text-subtitle2">
          <span
            v-if="charge.paid"
            v-text="$t('satspay.payment_received')"
          ></span>
          <span
            v-else-if="timeSeconds <= 0"
            v-text="$t('satspay.time_elapsed')"
          ></span>
          <div v-else class="full-width">
            <span class="q-ml-md">
              <q-spinner size="1em" class="q-mr-xs"></q-spinner>
              <span v-text="$t('satspay.awaiting_payment')"></span>
            </span>
            <span v-text="timeLeft"></span>
          </div>
        </div>
      </q-linear-progress>
    </div>`,
    created() {
      this.timeSeconds = this.charge.timeSecondsLeft
      this.timeLeft = this.charge.timeLeft
      this.progress = this.charge.progress
      if (this.charge.paid) {
        this.barColor = 'positive'
        this.progress = 1
      }
      if (!this.charge.paid && this.timeSeconds > 0) {
        this.barColor = 'secondary'
        setInterval(() => {
          if (!this.charge.paid && this.timeSeconds > 0) {
            this.timeSeconds -= 1
            this.timeLeft = secondsToTime(this.timeSeconds)
            this.progress = progress(this.charge.time * 60, this.timeSeconds)
          }
          if (this.charge.paid) {
            this.barColor = 'positive'
            this.progress = 1
          }
        }, 1000)
      }
    }
  })
}

window.PageSatspayPublic = {
  template: '#page-satspay-public',
  data() {
    return {
      charge: null,
      mempool_url: 'https://mempool.space',
      ws: null,
      tab: 'uqr'
    }
  },
  computed: {
    mempoolLink() {
      const url = this.mempool_url.replace(/\/$/, '')
      return `${url}/address/${this.charge.onchainaddress}`
    },
    unifiedQR() {
      const bitcoin = (this.charge.onchainaddress ?? '').toUpperCase()
      let queryString = `bitcoin:${bitcoin}?amount=${(this.charge.amount / 1e8).toFixed(8)}`
      if (this.charge.payment_request) {
        queryString += `&lightning=${this.charge.payment_request.toUpperCase()}`
      }
      return queryString
    },
    fiatProvidersList() {
      if (!this.charge?.fiat_payment_requests) return []
      try {
        const reqs = typeof this.charge.fiat_payment_requests === 'string'
          ? JSON.parse(this.charge.fiat_payment_requests)
          : this.charge.fiat_payment_requests
        return Object.entries(reqs).map(([name, data]) => ({
          name,
          payment_request: data.payment_request
        }))
      } catch {
        return []
      }
    },
    formattedFiatAmount() {
      const amt = this.charge?.currency_amount
      const cur = this.charge?.fiat_currency || this.charge?.currency
      if (amt == null || !cur) return ''
      return `${Number(amt).toFixed(2)} ${cur.toUpperCase()}`
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
    async getCharge() {
      const chargeId = this.$route.params.charge_id
      try {
        const {data} = await LNbits.api.request(
          'GET',
          `/satspay/api/v1/charge/public/${chargeId}`
        )
        this.mempool_url = data.mempool_url || this.mempool_url
        this.charge = mapCharge(data)
        if (!this.charge.onchainaddress) {
          this.tab = 'ln'
        }
        if (this.charge.custom_css) {
          document.body.setAttribute('id', 'custom-css')
          const link = document.createElement('link')
          link.rel = 'stylesheet'
          link.href = `/satspay/css/${this.charge.custom_css}`
          document.head.appendChild(link)
        }
        this.initWs()
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    payFiat(provider) {
      if (!provider.payment_request) {
        this.$q.notify({
          type: 'negative',
          message: this.$t('satspay.fiat_no_payment_url'),
          timeout: 5000
        })
        return
      }
      const win = window.open(provider.payment_request, '_blank')
      if (!win) {
        this.$q.notify({
          type: 'warning',
          message: this.$t('satspay.fiat_popup_blocked'),
          timeout: 10000
        })
      }
    },
    async initWs() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${protocol}://${window.location.host}/satspay/${this.charge.id}/ws`
      this.ws = new WebSocket(url)
      this.ws.addEventListener('message', async ({data}) => {
        const res = JSON.parse(data.toString())
        this.charge.balance = res.balance
        this.charge.pending = res.pending
        this.charge.paid = res.paid
        this.charge.completelink = res.completelink
        this.charge.settlement_method = res.settlement_method
        this.charge.settlement_proof = res.settlement_proof
        if (this.charge.paid) {
          this.charge.progress = 1
          this.charge.paid = true
          this.$q.notify({
            type: 'positive',
            message: this.$t('satspay.payment_received'),
            timeout: 10000
          })
        }
      })
      this.ws.addEventListener('close', async () => {
        this.$q.notify({
          type: 'negative',
          message: this.$t('satspay.ws_reconnecting'),
          timeout: 1000
        })
        setTimeout(() => {
          this.initWs()
        }, 3000)
      })
    }
  },
  async created() {
    await this.getCharge()
  }
}
