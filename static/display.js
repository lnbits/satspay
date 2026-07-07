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
    template: `
    <div>
      <q-icon
        name="check"
        style="color: green; font-size: 21.4em"
        class="fit"
      ></q-icon>
      <div class="row text-center q-mt-lg">
        <div class="col text-center">
          <q-btn
            outline
            v-if="charge.completelink"
            :loading="charge.paid"
            type="a"
            :href="charge.completelink"
            :label="charge.completelinktext"
          >
            <template v-slot:loading>
              <span v-text="charge.completelinktext"></span>
            </template>
          </q-btn>
          <p
            v-if="charge.completelink"
            class="q-pt-md"
            v-text="$t('satspay.redirecting')"
          ></p>
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
            Send
            <strong><span v-text="chargeAmountBtc"></span> BTC</strong>
            <span v-text="$t('satspay.send_btc_to_address')"></span>
          </span>
          <span
            v-if="type == 'ln'"
            class="text-subtitle2"
            v-text="$t('satspay.pay_ln_invoice')"
          ></span>
          <span
            v-if="type == 'uqr'"
            class="text-subtitle2"
            v-text="$t('satspay.scan_uqr')"
          ></span>
        </div>
      </div>
      <div class="row justify-center q-mb-sm">
        <div class="col-all">
          <a class="text-secondary" :href="href">
            <q-responsive :ratio="1" class="q-mx-md">
              <lnbits-qrcode :value="value"></lnbits-qrcode>
            </q-responsive>
          </a>
        </div>
      </div>
      <div class="row items-center q-mt-lg">
        <div class="col text-center">
          <q-btn
            outline
            color="grey"
            @click="utils.copyText(value)"
            :label="$t('satspay.copy_address')"
          ></q-btn>
        </div>
      </div>
    </div>`,
    computed: {
      chargeAmountBtc() {
        return (this.chargeAmount / 1e8).toFixed(8)
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
