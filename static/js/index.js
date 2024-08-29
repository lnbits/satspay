new Vue({
  el: '#vue',
  mixins: [windowMixin],
  computed: {
    endpoint() {
      return `/satspay/api/v1/settings?usr=${this.g.user.id}`
    }
  },
  data: function () {
    return {
      currencies: [],
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
      admin: admin,
      network: network,
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
          {
            name: 'theId',
            align: 'left',
            label: 'ID',
            field: 'id'
          },
          {
            name: 'name',
            align: 'left',
            label: 'Name',
            field: 'name'
          },
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
          {
            name: 'balance',
            align: 'left',
            label: 'Balance',
            field: 'balance'
          },
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
        pagination: {
          rowsPerPage: 10
        }
      },
      customCSSTable: {
        columns: [
          {
            name: 'title',
            align: 'left',
            label: 'Title',
            field: 'title'
          },
          {
            name: 'css_id',
            align: 'left',
            label: 'ID',
            field: 'css_id'
          }
        ],
        pagination: {
          rowsPerPage: 10
        }
      },
      formDialogCharge: {
        show: false,
        data: {
          onchain: false,
          onchainwallet: '',
          zeroconf: false,
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
        data: {
          custom_css: ''
        }
      },
      showWebhookResponse: false,
      webhookResponse: ''
    }
  },
  methods: {
    cancelThemes: function (data) {
      this.formDialogCharge.data.custom_css = ''
      this.formDialogThemes.show = false
    },
    cancelCharge: function (data) {
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

    getWalletLinks: async function () {
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
    getOnchainWalletName: function (walletId) {
      const wallet = this.walletLinks.find(w => w.id === walletId)
      if (!wallet) return 'unknown'
      return wallet.label
    },
    getLNbitsWalletName: function (walletId) {
      const wallet = this.g.user.walletOptions.find(w => w.value === walletId)
      if (!wallet) return 'unknown'
      return wallet.label
    },

    getCharges: async function () {
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
    getThemes: async function () {
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

    sendFormDataThemes: function () {
      const wallet = this.g.user.wallets[0].adminkey
      const data = this.formDialogThemes.data
      this.createTheme(wallet, data)
    },
    sendFormDataCharge: function () {
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
    updateformDialog: function (themeId) {
      const theme = _.findWhere(this.themeLinks, {css_id: themeId})
      this.formDialogThemes.data.css_id = theme.css_id
      this.formDialogThemes.data.title = theme.title
      this.formDialogThemes.data.custom_css = theme.custom_css
      this.formDialogThemes.show = true
    },
    createTheme: async function (wallet, data) {
      try {
        if (data.css_id) {
          const resp = await LNbits.api.request(
            'POST',
            '/satspay/api/v1/themes/' + data.css_id,
            wallet,
            data
          )
          this.themeLinks = _.reject(this.themeLinks, function (obj) {
            return obj.css_id === data.css_id
          })
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
        this.formDialogThemes.data = {
          title: '',
          custom_css: ''
        }
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    deleteTheme: function (themeId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this theme?')
        .onOk(async () => {
          try {
            await LNbits.api.request(
              'DELETE',
              `/satspay/api/v1/themes/${themeId}`,
              this.g.user.wallets[0].adminkey
            )
            this.themeLinks = _.reject(this.themeLinks, function (obj) {
              return obj.css_id === themeId
            })
          } catch (error) {
            LNbits.utils.notifyApiError(error)
          }
        })
    },
    createCharge: async function (wallet, data) {
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
    deleteChargeLink: function (chargeId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this pay link?')
        .onOk(async () => {
          try {
            await LNbits.api.request(
              'DELETE',
              `/satspay/api/v1/charge/${chargeId}`,
              this.g.user.wallets[0].adminkey
            )

            this.chargeLinks = _.reject(this.chargeLinks, function (obj) {
              return obj.id === chargeId
            })
          } catch (error) {
            LNbits.utils.notifyApiError(error)
          }
        })
    },
    sendWebhook: function (chargeId) {
      LNbits.api
        .request(
          'GET',
          `/satspay/api/v1/charge/webhook/${chargeId}`,
          this.g.user.wallets[0].adminkey
        )
        .then(response => {
          console.log(response)
          this.$q.notify({
            message: 'Webhook sent',
            color: 'positive'
          })
        })
        .catch(err => {
          LNbits.utils.notifyApiError(err)
        })
    },
    checkChargeBalance: function (chargeId) {
      LNbits.api
        .request(
          'GET',
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
            this.$q.notify({
              message: 'Charge paid',
              color: 'positive'
            })
          } else {
            this.$q.notify({
              message: 'Charge still pending...',
              color: 'negative'
            })
          }
        })
        .catch(err => {
          console.log(err)
          LNbits.utils.notifyApiError(err)
        })
    },
    showWebhookResponseDialog(webhookResponse) {
      this.webhookResponse = webhookResponse
      this.showWebhookResponse = true
    },
    exportchargeCSV: function () {
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
        .catch(err => {
          LNbits.utils.notifyApiError(err)
        })
    }
  },
  created: async function () {
    if (this.admin == 'True') {
      await this.getThemes()
    }
    await this.getCharges()
    await this.getWalletLinks()
    LNbits.api
      .request('GET', '/api/v1/currencies')
      .then(response => {
        this.currencies = ['satoshis', ...response.data]
        this.formDialogCharge.data.currency = 'satoshis'
      })
      .catch(err => {
        LNbits.utils.notifyApiError(err)
      })
  }
})
