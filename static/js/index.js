new Vue({
  el: '#vue',
  mixins: [windowMixin],
  data: function () {
    return {
      settings: {},
      filter: '',
      admin: admin,
      balance: null,
      walletLinks: [],
      chargeLinks: [],
      themeLinks: [],
      themeOptions: [],
      onchainwallet: '',
      rescanning: false,
      mempool: {
        endpoint: '',
        network: 'Mainnet'
      },
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
            name: 'description',
            align: 'left',
            label: 'Title',
            field: 'description'
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
            name: 'pendingBalance',
            align: 'left',
            label: 'Pending Balance',
            field: 'pendingBalance'
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
            name: 'css_id',
            align: 'left',
            label: 'ID',
            field: 'css_id'
          },
          {
            name: 'title',
            align: 'left',
            label: 'Title',
            field: 'title'
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
          amount: null
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
      this.formDialogCharge.data.description = null
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
        const {data} = await LNbits.api.request(
          'GET',
          `/watchonly/api/v1/wallet?network=${this.mempool.network}`,
          this.g.user.wallets[0].adminkey
        )
        this.walletLinks = data.map(w => ({
          id: w.id,
          label: w.title + ' - ' + w.id
        }))
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    getWalletConfig: async function () {
      try {
        const {data} = await LNbits.api.request(
          'GET',
          '/watchonly/api/v1/config',
          this.g.user.wallets[0].inkey
        )
        this.mempool.endpoint = data.mempool_endpoint
        this.mempool.network = data.network || 'Mainnet'
        const url = new URL(this.mempool.endpoint)
        this.mempool.hostname = url.hostname
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
      const theme = _.findWhere(this.themeLinks, {id: themeId})
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this theme?')
        .onOk(async () => {
          try {
            const response = await LNbits.api.request(
              'DELETE',
              '/satspay/api/v1/themes/' + themeId,
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
          amount: null
        }
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    deleteChargeLink: function (chargeId) {
      const link = _.findWhere(this.chargeLinks, {id: chargeId})
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this pay link?')
        .onOk(async () => {
          try {
            const response = await LNbits.api.request(
              'DELETE',
              '/satspay/api/v1/charge/' + chargeId,
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
    }
  },
  created: async function () {
    if (this.admin == 'True') {
      await this.getThemes()
    }
    await this.getCharges()
    await this.getWalletConfig()
    await this.getWalletLinks()
  }
})
