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

const mapCSS = (obj, oldObj = {}) => {
  return _.clone(obj)
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

window.PageSatspay = {
  template: '#page-satspay',
  computed: {
    endpoint() {
      return `/satspay/api/v1/settings?usr=${this.g.user.id}`
    },
    currencies() {
      return [
        'satoshis',
        ...(this.g.allowedCurrencies || this.g.currencies || [])
      ]
    }
  },
  data() {
    return {
      fiatRates: {},
      settings: [
        {
          type: 'str',
          description:
            'Network used by OnchainWallet extension Wallet. default: `Mainnet`, or `Testnet` for testnet',
          name: 'network'
        },
        {
          type: 'str',
          description:
            'Mempool API URL. default: `https://mempool.space`, use `https://mempool.space/testnet` for testnet',
          name: 'mempool_url'
        },
        {
          type: 'str',
          description:
            'Webhook Method with which the webhook is sent (GET is required for Woocommerce plugin). default: `GET`, or `POST`',
          name: 'webhook_method'
        }
      ],
      filter: '',
      network: 'Mainnet',
      balance: null,
      walletLinks: [],
      chargeLinks: [],
      themeLinks: [],
      themeOptions: [],
      onchainwallet: '',
      rescanning: false,
      showAdvanced: false,
      chargesTable: {
        columns: [
          {name: 'theId', align: 'left', label: 'ID', field: 'id'},
          {name: 'name', align: 'left', label: 'Name', field: 'name'},
          {
            name: 'timeLeft',
            align: 'left',
            label: 'Time left',
            field: 'timeLeft'
          },
          {
            name: 'time to pay',
            align: 'left',
            label: 'Time to Pay',
            field: 'time'
          },
          {
            name: 'amount',
            align: 'left',
            label: 'Amount to pay',
            field: 'amount'
          },
          {name: 'balance', align: 'left', label: 'Balance', field: 'balance'},
          {
            name: 'pending',
            align: 'left',
            label: 'Pending Balance',
            field: 'pending'
          },
          {
            name: 'onchain address',
            align: 'left',
            label: 'Onchain Address',
            field: 'onchainaddress'
          },
          {
            name: 'LNbits wallet',
            align: 'left',
            label: 'LNbits wallet',
            field: 'lnbitswallet'
          },
          {
            name: 'Webhook link',
            align: 'left',
            label: 'Webhook link',
            field: 'webhook'
          },
          {
            name: 'Paid link',
            align: 'left',
            label: 'Paid link',
            field: 'completelink'
          }
        ],
        pagination: {rowsPerPage: 10}
      },
      customCSSTable: {
        columns: [
          {name: 'title', align: 'left', label: 'Title', field: 'title'},
          {name: 'css_id', align: 'left', label: 'ID', field: 'css_id'}
        ],
        pagination: {rowsPerPage: 10}
      },
      formDialogCharge: {
        show: false,
        data: {
          onchain: false,
          onchainwallet: '',
          zeroconf: false,
          fasttrack: false,
          lnbits: false,
          description: '',
          custom_css: '',
          time: null,
          amount: null,
          currency: 'satoshis'
        }
      },
      formDialogThemes: {
        show: false,
        data: {custom_css: ''}
      },
      showWebhookResponse: false,
      webhookResponse: ''
    }
  },
  methods: {
    cancelThemes() {
      this.formDialogCharge.data.custom_css = ''
      this.formDialogThemes.show = false
    },
    cancelCharge() {
      this.formDialogCharge.data.description = ''
      this.formDialogCharge.data.onchain = false
      this.formDialogCharge.data.onchainwallet = ''
      this.formDialogCharge.data.zeroconf = false
      this.formDialogCharge.data.lnbitswallet = ''
      this.formDialogCharge.data.time = null
      this.formDialogCharge.data.amount = null
      this.formDialogCharge.data.webhook = ''
      this.formDialogCharge.data.custom_css = ''
      this.formDialogCharge.data.completelink = ''
      this.formDialogCharge.show = false
    },

    async getWalletLinks() {
      try {
        let {data} = await LNbits.api.request(
          'GET',
          `/watchonly/api/v1/wallet?network=${this.network}`,
          this.g.user.wallets[0].adminkey
        )
        data = data.filter(w => w.network === this.network)
        this.walletLinks = data.map(w => ({
          id: w.id,
          label: w.title + ' - ' + w.id
        }))
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    getOnchainWalletName(walletId) {
      const wallet = this.walletLinks.find(w => w.id === walletId)
      if (!wallet) return 'unknown'
      return wallet.label
    },
    getLNbitsWalletName(walletId) {
      const wallet = this.g.user.walletOptions.find(w => w.value === walletId)
      if (!wallet) return 'unknown'
      return wallet.label
    },

    async getCharges() {
      try {
        const {data} = await LNbits.api.request(
          'GET',
          '/satspay/api/v1/charges',
          this.g.user.wallets[0].adminkey
        )
        this.chargeLinks = data.map(c =>
          mapCharge(
            c,
            this.chargeLinks.find(old => old.id === c.id)
          )
        )
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    async getThemes() {
      try {
        const {data} = await LNbits.api.request(
          'GET',
          '/satspay/api/v1/themes',
          this.g.user.wallets[0].adminkey
        )
        this.themeLinks = data.map(c =>
          mapCSS(
            c,
            this.themeLinks.find(old => old.css_id === c.css_id)
          )
        )
        this.themeOptions = data.map(w => ({
          id: w.css_id,
          label: w.title + ' - ' + w.css_id
        }))
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    sendFormDataThemes() {
      const wallet = this.g.user.wallets[0].adminkey
      const data = this.formDialogThemes.data
      this.createTheme(wallet, data)
    },
    sendFormDataCharge() {
      this.formDialogCharge.data.custom_css =
        this.formDialogCharge.data.custom_css?.id
      const data = this.formDialogCharge.data
      const wallet = this.g.user.wallets[0].inkey
      data.amount = parseInt(data.amount)
      data.time = parseInt(data.time)
      data.lnbitswallet = data.lnbits ? data.lnbitswallet : null
      data.onchainwallet = data.onchain ? this.onchainwallet?.id : null
      this.createCharge(wallet, data)
    },
    updateformDialog(themeId) {
      const theme = _.findWhere(this.themeLinks, {css_id: themeId})
      this.formDialogThemes.data.css_id = theme.css_id
      this.formDialogThemes.data.title = theme.title
      this.formDialogThemes.data.custom_css = theme.custom_css
      this.formDialogThemes.show = true
    },
    async createTheme(wallet, data) {
      try {
        if (data.css_id) {
          const resp = await LNbits.api.request(
            'POST',
            '/satspay/api/v1/themes/' + data.css_id,
            wallet,
            data
          )
          this.themeLinks = _.reject(
            this.themeLinks,
            obj => obj.css_id === data.css_id
          )
          this.themeLinks.unshift(mapCSS(resp.data))
        } else {
          const resp = await LNbits.api.request(
            'POST',
            '/satspay/api/v1/themes',
            wallet,
            data
          )
          this.themeLinks.unshift(mapCSS(resp.data))
        }
        this.formDialogThemes.show = false
        this.formDialogThemes.data = {title: '', custom_css: ''}
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    deleteTheme(themeId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this theme?')
        .onOk(async () => {
          try {
            await LNbits.api.request(
              'DELETE',
              `/satspay/api/v1/themes/${themeId}`,
              this.g.user.wallets[0].adminkey
            )
            this.themeLinks = _.reject(
              this.themeLinks,
              obj => obj.css_id === themeId
            )
          } catch (error) {
            LNbits.utils.notifyApiError(error)
          }
        })
    },
    async createCharge(wallet, data) {
      try {
        const resp = await LNbits.api.request(
          'POST',
          '/satspay/api/v1/charge',
          wallet,
          data
        )
        this.chargeLinks.unshift(mapCharge(resp.data))
        this.formDialogCharge.show = false
        this.formDialogCharge.data = {
          onchain: false,
          zeroconf: false,
          lnbits: false,
          description: '',
          time: null,
          amount: null,
          currency: 'satoshis'
        }
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    deleteChargeLink(chargeId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this pay link?')
        .onOk(async () => {
          try {
            await LNbits.api.request(
              'DELETE',
              `/satspay/api/v1/charge/${chargeId}`,
              this.g.user.wallets[0].adminkey
            )
            this.chargeLinks = _.reject(
              this.chargeLinks,
              obj => obj.id === chargeId
            )
          } catch (error) {
            LNbits.utils.notifyApiError(error)
          }
        })
    },
    sendWebhook(chargeId) {
      LNbits.api
        .request(
          'GET',
          `/satspay/api/v1/charge/webhook/${chargeId}`,
          this.g.user.wallets[0].adminkey
        )
        .then(() => {
          this.$q.notify({message: 'Webhook sent', color: 'positive'})
        })
        .catch(err => {
          LNbits.utils.notifyApiError(err)
        })
    },
    checkChargeBalance(chargeId) {
      LNbits.api
        .request(
          'PUT',
          `/satspay/api/v1/charge/balance/${chargeId}`,
          this.g.user.wallets[0].adminkey
        )
        .then(response => {
          const charge = _.findWhere(this.chargeLinks, {id: chargeId})
          charge.balance = response.data.balance
          charge.pending = response.data.pending
          charge.paid = response.data.paid
          const index = this.chargeLinks.findIndex(c => c.id === chargeId)
          this.chargeLinks[index] = mapCharge(charge, this.chargeLinks[index])
          if (charge.paid) {
            this.$q.notify({message: 'Charge paid', color: 'positive'})
          } else {
            this.$q.notify({
              message: 'Charge still pending...',
              color: 'negative'
            })
          }
        })
        .catch(err => {
          LNbits.utils.notifyApiError(err)
        })
    },
    showWebhookResponseDialog(webhookResponse) {
      this.webhookResponse = webhookResponse
      this.showWebhookResponse = true
    },
    exportchargeCSV() {
      LNbits.utils.exportCSV(
        this.chargesTable.columns,
        this.chargeLinks,
        'charges'
      )
    },
    updateFiatRate(currency) {
      LNbits.api
        .request('GET', '/lnurlp/api/v1/rate/' + currency, null)
        .then(response => {
          let rates = _.clone(this.fiatRates)
          rates[currency] = response.data.rate
          this.fiatRates = rates
        })
        .catch(LNbits.utils.notifyApiError)
    }
  },
  async created() {
    try {
      const {data} = await LNbits.api.request(
        'GET',
        '/satspay/api/v1/settings/public'
      )
      this.network = data.network
    } catch (e) {}
    if (this.g.user.admin) {
      await this.getThemes()
    }
    await this.getCharges()
    await this.getWalletLinks()
  }
}
