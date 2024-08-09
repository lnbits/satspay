Vue.component(VueQrcode.name, VueQrcode)

Vue.component('satspay-paid', {
  props: ['charge', 'timer'],
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
          :percentage="timer"
          type="a"
          :href="charge.completelink"
          :label="charge.completelinktext"
          >{%raw%}<template v-slot:loading> {{charge.completelinktext}} </template
          >{%endraw%}</q-btn
        >
        <p v-if="charge.completelink" class="q-pt-md">
          Redirecting after 5 seconds
        </p>
      </div>
    </div>
  </div>`
})

Vue.component('satspay-show-qr', {
  props: ['charge-amount', 'type', 'value', 'href'],
  mixins: [windowMixin],
  template: `
  <div>
    <div class="row justify-center q-mb-sm">
      <div class="col text-center">
        <span v-if="type == 'btc'" class="text-subtitle2">Send
          <strong>
          <span v-text="chargeAmountBtc"></span> BTC
          </strong>
           to this onchain address</span>
        <span v-if="type == 'ln'" class="text-subtitle2">Pay this lightning-network invoice:</span>
        <span v-if="type == 'uqr'" class="text-subtitle2">Scan QR with a wallet supporting BIP21:</span>
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
        <q-btn outline color="grey" @click="copyText(value)">Copy address</q-btn>
      </div>
    </div>
  </div>`,
  computed: {
    chargeAmountBtc(){
      return (this.chargeAmount / 1e8).toFixed(8)
    }
  }
})

Vue.component('satspay-time-elapsed', {
  props: ['charge'],
  data() {
    return {
      barColor: 'grey',
      barText: 'Time elapsed'
    }
  },
  template: `
  <div class="text-center">
    <q-linear-progress size="30px" :value="charge.progress" :color="barColor">
      <div class="absolute-full flex flex-center text-white text-subtitle2">
        <span v-if="+charge.timeLeft <= 0 || charge.paid">{{barText}}</span>
        <div v-else class="full-width">
          <span class="q-ml-md" style="position: absolute; left: 0">
            <q-spinner size="1em" class="q-mr-xs"></q-spinner>
            {{barText}}
          </span>
          <span>{{charge.timeLeft}}</span>
        </div>
      </div>
    </q-linear-progress>
  </div>`,
  created() {
    if (!this.charge.timeLeft && !this.charge.paid) {
      this.barText = 'Time elapsed'
    } else if (this.charge.paid) {
      this.barText = 'Payment received'
    } else {
      this.barText = 'Awaiting payment...'
      this.barColor = 'secondary'
    }
  }
})
